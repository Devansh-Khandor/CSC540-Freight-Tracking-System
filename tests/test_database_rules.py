"""Functional tests for book_shipment, scan_event triggers and table constraints.

Target: MariaDB 10.5.22, schema sshett24 only (guarded in conftest/db_helpers).
Every test gets a fresh, committed fixture graph and removes exactly its own
rows afterwards, even when the test fails.
"""

from decimal import Decimal as D

import pytest

from db_helpers import (
    ER_BAD_NULL, ER_CONSTRAINT_FAILED, ER_DUP_ENTRY, ER_LOCK_WAIT_TIMEOUT,
    ER_NO_REFERENCED_ROW, ER_SIGNAL_EXCEPTION, MSG_ALREADY_BOOKED, MSG_BAD_TRANSITION,
    MSG_CAPACITY, MSG_FIRST_RECEIVED, MSG_IDLE, MSG_IDS_POSITIVE, MSG_INVALID_STATUS,
    MSG_LANE_MISMATCH, MSG_NO_DEPARTURE, MSG_NO_SHIPMENT, MSG_SCAN_ISOLATION,
    MSG_SCAN_NO_SHIPMENT, MSG_SEQ_ORDER, MSG_SEQ_POSITIVE, MSG_TS_BACKWARD, MSG_TS_REQUIRED,
    ScanSession, absent_id, book_shipment, bookings_of_shipment, departure_load, execute,
    expect_db_error, fetchall, fetchone, in_rolled_back_transaction, in_transaction,
    scan_history, session_isolation, shipment_state,
)

PROMISE = "2030-03-15"


def booking_failure(db, shipment_id, departure_id, message):
    """Assert a rejected CALL leaves no booking change and no open transaction."""
    before_ship = bookings_of_shipment(db.reader, shipment_id) if shipment_id else None
    before_dep = departure_load(db.reader, departure_id) if departure_id else None
    expect_db_error(book_shipment, db.booker, shipment_id, departure_id,
                    codes=ER_SIGNAL_EXCEPTION, message=message)
    assert in_transaction(db.booker) == 0, "procedure must end its transaction on failure"
    if shipment_id:
        assert bookings_of_shipment(db.reader, shipment_id) == before_ship
    if departure_id:
        assert departure_load(db.reader, departure_id) == before_dep


# ==========================================================================
# Booking procedure
# ==========================================================================

class TestBooking:

    def test_valid_booking_creates_one_row_and_commits(self, db):
        w = db.world
        dep = w.add_departure("100.00")
        s = w.add_shipment("60.00")
        book_shipment(db.booker, s, dep)
        assert in_transaction(db.booker) == 0
        # Visible from a different connection => committed by the procedure.
        assert bookings_of_shipment(db.reader, s) == [dep]
        assert departure_load(db.reader, dep) == (1, D("60.00"))
        # Booking does not touch derived scan state.
        assert shipment_state(db.reader, s) == (None, None)

    def test_fill_to_exact_capacity_then_reject_overflow(self, db):
        w = db.world
        dep = w.add_departure("100.00")
        s60a, s40, s60b = w.add_shipment("60.00"), w.add_shipment("40.00"), w.add_shipment("60.00")
        book_shipment(db.booker, s60a, dep)
        book_shipment(db.booker, s40, dep)
        assert departure_load(db.reader, dep) == (2, D("100.00"))
        booking_failure(db, s60b, dep, MSG_CAPACITY)
        assert bookings_of_shipment(db.reader, s60b) == []
        assert sorted(r[0] for r in fetchall(
            db.reader, "SELECT shipment_id FROM booking WHERE departure_id = %s", (dep,))) \
            == sorted([s60a, s40])

    def test_single_shipment_equal_to_capacity_is_accepted(self, db):
        dep = db.world.add_departure("100.00")
        s = db.world.add_shipment("100.00")
        book_shipment(db.booker, s, dep)
        assert departure_load(db.reader, dep) == (1, D("100.00"))

    def test_capacity_exceeded_by_one_cent_is_rejected(self, db):
        w = db.world
        empty = w.add_departure("100.00")
        booking_failure(db, w.add_shipment("100.01"), empty, MSG_CAPACITY)
        assert departure_load(db.reader, empty) == (0, D("0.00"))

        partly = w.add_departure("100.00", when="2030-03-10 09:00:00")
        book_shipment(db.booker, w.add_shipment("60.00"), partly)
        booking_failure(db, w.add_shipment("40.01"), partly, MSG_CAPACITY)
        assert departure_load(db.reader, partly) == (1, D("60.00"))

    def test_duplicate_booking_same_and_other_departure_rejected(self, db):
        w = db.world
        dep1 = w.add_departure("100.00")
        dep2 = w.add_departure("100.00", when="2030-03-10 09:00:00")
        s = w.add_shipment("10.00")
        book_shipment(db.booker, s, dep1)
        booking_failure(db, s, dep1, MSG_ALREADY_BOOKED)
        booking_failure(db, s, dep2, MSG_ALREADY_BOOKED)
        assert bookings_of_shipment(db.reader, s) == [dep1]
        assert departure_load(db.reader, dep2) == (0, D("0.00"))

    def test_reverse_lane_shipment_rejected(self, db):
        w = db.world
        dep = w.add_departure("100.00")  # origin -> destination
        reverse = w.add_shipment("10.00", lane=(w.destination, w.origin))
        booking_failure(db, reverse, dep, MSG_LANE_MISMATCH)
        assert departure_load(db.reader, dep) == (0, D("0.00"))

    def test_different_lane_shipment_rejected(self, db):
        w = db.world
        dep = w.add_departure("100.00")
        other = w.add_shipment("10.00", lane=(w.origin, w.intermediate))
        booking_failure(db, other, dep, MSG_LANE_MISMATCH)
        assert bookings_of_shipment(db.reader, other) == []

    def test_missing_null_and_zero_ids_rejected(self, db):
        w = db.world
        dep = w.add_departure("100.00")
        s = w.add_shipment("10.00")
        missing_dep = absent_id(db.reader, "departure", "departure_id")
        missing_ship = absent_id(db.reader, "shipment", "shipment_id")
        booking_failure(db, s, missing_dep, MSG_NO_DEPARTURE)
        booking_failure(db, missing_ship, dep, MSG_NO_SHIPMENT)
        booking_failure(db, 0, dep, MSG_IDS_POSITIVE)
        booking_failure(db, s, 0, MSG_IDS_POSITIVE)
        booking_failure(db, None, dep, MSG_IDS_POSITIVE)
        booking_failure(db, s, None, MSG_IDS_POSITIVE)
        assert bookings_of_shipment(db.reader, s) == []
        assert departure_load(db.reader, dep) == (0, D("0.00"))

    def test_active_caller_transaction_rejected_and_left_untouched(self, db):
        w = db.world
        dep = w.add_departure("100.00")
        s = w.add_shipment("10.00")
        conn = db.booker
        execute(conn, "START TRANSACTION")
        try:
            probe = execute(conn, "INSERT INTO shipment (shipper_account_id, origin_hub_id, "
                                  "destination_hub_id, weight_kg, promised_delivery_date) "
                                  "VALUES (%s, %s, %s, 5.00, %s)",
                            (w.shipper, w.origin, w.destination, PROMISE))
            w.track_shipment(probe)
            expect_db_error(execute, conn, "CALL book_shipment(%s, %s)", (s, dep),
                            codes=ER_SIGNAL_EXCEPTION, message=MSG_IDLE)
            # The procedure neither committed nor rolled back the caller's work.
            assert in_transaction(conn) == 1
            assert fetchone(conn, "SELECT COUNT(*) FROM shipment WHERE shipment_id = %s",
                            (probe,))[0] == 1
            assert fetchone(db.reader, "SELECT COUNT(*) FROM shipment WHERE shipment_id = %s",
                            (probe,))[0] == 0, "caller work must still be uncommitted"
        finally:
            conn.rollback()
        assert in_transaction(conn) == 0
        assert fetchone(db.reader, "SELECT COUNT(*) FROM shipment WHERE shipment_id = %s",
                        (probe,))[0] == 0
        assert bookings_of_shipment(db.reader, s) == []

    def test_lock_timeout_inside_procedure_rolls_back_then_retry_succeeds(self, db):
        w = db.world
        dep = w.add_departure("100.00")
        s = w.add_shipment("10.00")
        locker = db.connect()
        caller = db.connect(lock_wait_timeout=1)
        execute(locker, "START TRANSACTION")
        try:
            assert len(fetchall(locker, "SELECT departure_id FROM departure "
                                        "WHERE departure_id = %s FOR UPDATE", (dep,))) == 1
            expect_db_error(book_shipment, caller, s, dep, codes=ER_LOCK_WAIT_TIMEOUT)
            assert in_transaction(caller) == 0, "EXIT handler must ROLLBACK"
            assert bookings_of_shipment(db.reader, s) == []
        finally:
            locker.rollback()
        book_shipment(caller, s, dep)
        assert bookings_of_shipment(db.reader, s) == [dep]
        assert departure_load(db.reader, dep) == (1, D("10.00"))


# ==========================================================================
# Table-level constraints (every probe runs in a rolled-back transaction)
# ==========================================================================

class TestConstraints:

    def test_unique_shipment_blocks_direct_second_booking(self, db):
        w = db.world
        dep1 = w.add_departure("100.00")
        dep2 = w.add_departure("100.00", when="2030-03-10 09:00:00")
        s = w.add_shipment("10.00")
        book_shipment(db.booker, s, dep1)
        expect_db_error(in_rolled_back_transaction, db.writer,
                        "INSERT INTO booking (shipment_id, departure_id) VALUES (%s, %s)",
                        (s, dep2), codes=ER_DUP_ENTRY)
        assert bookings_of_shipment(db.reader, s) == [dep1]

    def test_booking_requires_existing_shipment(self, db):
        dep = db.world.add_departure("100.00")
        missing = absent_id(db.reader, "shipment", "shipment_id")
        expect_db_error(in_rolled_back_transaction, db.writer,
                        "INSERT INTO booking (shipment_id, departure_id) VALUES (%s, %s)",
                        (missing, dep), codes=ER_NO_REFERENCED_ROW)

    @pytest.mark.parametrize("weight", ["0.00", "-1.00"])
    def test_shipment_weight_must_be_positive(self, db, weight):
        w = db.world
        err = expect_db_error(
            in_rolled_back_transaction, db.writer,
            "INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id, "
            "weight_kg, promised_delivery_date) VALUES (%s, %s, %s, %s, %s)",
            (w.shipper, w.origin, w.destination, weight, PROMISE), codes=ER_CONSTRAINT_FAILED)
        assert "chk_shipment_weight" in err.args[1]

    @pytest.mark.parametrize("capacity", ["0.00", "-5.00"])
    def test_departure_capacity_must_be_positive(self, db, capacity):
        w = db.world
        err = expect_db_error(
            in_rolled_back_transaction, db.writer,
            "INSERT INTO departure (vehicle_id, origin_hub_id, destination_hub_id, "
            "departure_datetime, max_total_weight_kg) VALUES (%s, %s, %s, %s, %s)",
            (w.vehicle, w.origin, w.destination, "2030-03-10 08:00:00", capacity),
            codes=ER_CONSTRAINT_FAILED)
        assert "chk_departure_max_total_weight" in err.args[1]

    def test_lane_rejects_same_hub_and_duplicate_pair(self, db):
        w = db.world
        sql = "INSERT INTO lane (origin_hub_id, destination_hub_id) VALUES (%s, %s)"
        err = expect_db_error(in_rolled_back_transaction, db.writer, sql,
                              (w.origin, w.origin), codes=ER_CONSTRAINT_FAILED)
        assert "chk_lane_different_hubs" in err.args[1]
        expect_db_error(in_rolled_back_transaction, db.writer, sql,
                        (w.origin, w.destination), codes=ER_DUP_ENTRY)

    def test_shipment_requires_listed_ordered_lane(self, db):
        w = db.world  # (intermediate -> origin) is not a lane; (origin -> intermediate) is.
        expect_db_error(
            in_rolled_back_transaction, db.writer,
            "INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id, "
            "weight_kg, promised_delivery_date) VALUES (%s, %s, %s, 1.00, %s)",
            (w.shipper, w.intermediate, w.origin, PROMISE), codes=ER_NO_REFERENCED_ROW)

    @pytest.mark.parametrize("status, outcome, constraint", [
        ("DELIVERED", None, "chk_shipment_status_outcome"),
        ("IN_TRANSIT", "ON_TIME", "chk_shipment_status_outcome"),
        (None, "LATE", "chk_shipment_status_outcome"),
        ("delivered", "ON_TIME", "chk_shipment_current_status"),
        ("DELIVERED", "EARLY", "chk_shipment_delivery_outcome"),
    ])
    def test_shipment_status_outcome_checks(self, db, status, outcome, constraint):
        w = db.world
        err = expect_db_error(
            in_rolled_back_transaction, db.writer,
            "INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id, "
            "weight_kg, promised_delivery_date, current_status, delivery_outcome) "
            "VALUES (%s, %s, %s, 1.00, %s, %s, %s)",
            (w.shipper, w.origin, w.destination, PROMISE, status, outcome),
            codes=ER_CONSTRAINT_FAILED)
        assert constraint in err.args[1]

    def test_role_and_region_domains(self, db):
        err = expect_db_error(in_rolled_back_transaction, db.writer,
                              "INSERT INTO account (password, role) VALUES (%s, %s)",
                              (f"{db.world.tag}-PROBE", "shipper"), codes=ER_CONSTRAINT_FAILED)
        assert "chk_account_role" in err.args[1]
        err = expect_db_error(in_rolled_back_transaction, db.writer,
                              "INSERT INTO hub (region) VALUES (%s)", ("North",),
                              codes=ER_CONSTRAINT_FAILED)
        assert "chk_hub_region" in err.args[1]


# ==========================================================================
# Scan triggers
# ==========================================================================

PREFIX_TS = ["2030-01-01 08:00:00", "2030-01-01 09:00:00",
             "2030-01-01 10:00:00", "2030-01-01 11:00:00"]
TO_OUT_FOR_DELIVERY = ["RECEIVED", "IN_TRANSIT", "ARRIVED_AT_HUB", "OUT_FOR_DELIVERY"]


def booked_shipment(db, promise=PROMISE, weight="10.00"):
    w = db.world
    dep = w.add_departure("1000.00")
    s = w.add_shipment(weight, promise=promise)
    book_shipment(db.booker, s, dep)
    return s


def advance(db, shipment_id, statuses, timestamps=PREFIX_TS):
    """Apply valid scans, each in its own READ COMMITTED + prelock transaction."""
    w = db.world
    hubs = {"RECEIVED": w.origin, "IN_TRANSIT": w.origin,
            "ARRIVED_AT_HUB": w.destination, "OUT_FOR_DELIVERY": w.destination,
            "DELIVERED": w.destination}
    for status, ts in zip(statuses, timestamps):
        db.scanner.append(shipment_id, ts, status, hubs[status])
    assert len(scan_history(db.reader, shipment_id)) == len(statuses)


def rejected_scan(db, shipment_id, seq, ts, status, hub, message, codes=ER_SIGNAL_EXCEPTION,
                  expect_shipment=True):
    """Assert a scan insert fails and changes neither history nor derived state."""
    before_state = shipment_state(db.reader, shipment_id) if expect_shipment else None
    before_hist = scan_history(db.reader, shipment_id)
    expect_db_error(db.scanner.insert, shipment_id, seq, ts, status, hub,
                    codes=codes, message=message, expect_shipment=expect_shipment)
    assert in_transaction(db.scanner.conn) == 0
    assert scan_history(db.reader, shipment_id) == before_hist
    if expect_shipment:
        assert shipment_state(db.reader, shipment_id) == before_state


class TestScanProgression:

    def test_valid_multi_hub_progression_updates_derived_state(self, db):
        w = db.world
        s = booked_shipment(db)
        steps = [
            ("2030-03-10 08:00:00", "RECEIVED", w.origin),
            ("2030-03-10 08:30:00", "IN_TRANSIT", w.origin),
            ("2030-03-10 09:00:00", "IN_TRANSIT", w.origin),            # repeat
            ("2030-03-11 09:00:00", "ARRIVED_AT_HUB", w.intermediate),
            ("2030-03-11 09:00:00", "ARRIVED_AT_HUB", w.intermediate),  # equal ts, repeat
            ("2030-03-11 10:00:00", "IN_TRANSIT", w.intermediate),      # hub cycle
            ("2030-03-12 11:00:00", "ARRIVED_AT_HUB", w.destination),
            ("2030-03-12 12:00:00", "OUT_FOR_DELIVERY", w.destination),
            ("2030-03-13 08:00:00", "OUT_FOR_DELIVERY", w.destination),  # repeat
        ]
        for expected_seq, (ts, status, hub) in enumerate(steps, start=1):
            assert db.scanner.append(s, ts, status, hub) == expected_seq
            assert shipment_state(db.reader, s) == (status, None)
            assert scan_history(db.reader, s)[-1] == (expected_seq, ts, status, hub)
        assert db.scanner.append(s, "2030-03-13 15:00:00", "DELIVERED", w.destination) == 10
        assert shipment_state(db.reader, s) == ("DELIVERED", "ON_TIME")
        assert [r[0] for r in scan_history(db.reader, s)] == list(range(1, 11))

    @pytest.mark.parametrize("status", ["IN_TRANSIT", "ARRIVED_AT_HUB",
                                        "OUT_FOR_DELIVERY", "DELIVERED"])
    def test_first_scan_must_be_received(self, db, status):
        s = booked_shipment(db)
        rejected_scan(db, s, 1, "2030-03-10 08:00:00", status, db.world.origin,
                      MSG_FIRST_RECEIVED)
        assert shipment_state(db.reader, s) == (None, None)
        assert scan_history(db.reader, s) == []

    def test_first_scan_sequence_must_be_one(self, db):
        s = booked_shipment(db)
        o = db.world.origin
        rejected_scan(db, s, 2, "2030-03-10 08:00:00", "RECEIVED", o, MSG_SEQ_ORDER)
        rejected_scan(db, s, 0, "2030-03-10 08:00:00", "RECEIVED", o, MSG_SEQ_POSITIVE)
        db.scanner.insert(s, 1, "2030-03-10 08:00:00", "RECEIVED", o)
        assert shipment_state(db.reader, s) == ("RECEIVED", None)

    def test_sequence_must_increment_by_exactly_one(self, db):
        s = booked_shipment(db)
        o = db.world.origin
        db.scanner.insert(s, 1, "2030-03-10 08:00:00", "RECEIVED", o)
        rejected_scan(db, s, 3, "2030-03-10 09:00:00", "IN_TRANSIT", o, MSG_SEQ_ORDER)  # gap
        rejected_scan(db, s, 1, "2030-03-10 09:00:00", "IN_TRANSIT", o, MSG_SEQ_ORDER)  # dup
        rejected_scan(db, s, 1, "2030-03-10 08:00:00", "RECEIVED", o, MSG_SEQ_ORDER)    # dup
        db.scanner.insert(s, 2, "2030-03-10 09:00:00", "IN_TRANSIT", o)
        assert shipment_state(db.reader, s) == ("IN_TRANSIT", None)
        assert [r[0] for r in scan_history(db.reader, s)] == [1, 2]

    def test_timestamps_cannot_decrease(self, db):
        s = booked_shipment(db)
        o = db.world.origin
        db.scanner.insert(s, 1, "2030-03-10 08:00:00", "RECEIVED", o)
        rejected_scan(db, s, 2, "2030-03-10 07:59:59", "IN_TRANSIT", o, MSG_TS_BACKWARD)
        db.scanner.insert(s, 2, "2030-03-10 08:00:00", "IN_TRANSIT", o)  # equal is allowed
        rejected_scan(db, s, 3, "2030-03-09 23:59:59", "ARRIVED_AT_HUB", o, MSG_TS_BACKWARD)
        assert shipment_state(db.reader, s) == ("IN_TRANSIT", None)

    def test_equal_timestamp_across_shipments_is_allowed(self, db):
        a, b = booked_shipment(db), booked_shipment(db)
        db.scanner.insert(a, 1, "2030-03-10 08:00:00", "RECEIVED", db.world.origin)
        db.scanner.insert(b, 1, "2030-03-10 08:00:00", "RECEIVED", db.world.origin)
        assert shipment_state(db.reader, a) == shipment_state(db.reader, b) == ("RECEIVED", None)

    @pytest.mark.parametrize("prefix, invalid_next", [
        (["RECEIVED"], ["RECEIVED", "ARRIVED_AT_HUB", "OUT_FOR_DELIVERY", "DELIVERED"]),
        (["RECEIVED", "IN_TRANSIT"], ["RECEIVED", "OUT_FOR_DELIVERY", "DELIVERED"]),
        (["RECEIVED", "IN_TRANSIT", "ARRIVED_AT_HUB"], ["RECEIVED", "DELIVERED"]),
        (TO_OUT_FOR_DELIVERY, ["RECEIVED", "IN_TRANSIT", "ARRIVED_AT_HUB"]),
    ], ids=["from_RECEIVED", "from_IN_TRANSIT", "from_ARRIVED_AT_HUB", "from_OUT_FOR_DELIVERY"])
    def test_invalid_status_transitions_rejected(self, db, prefix, invalid_next):
        s = booked_shipment(db)
        advance(db, s, prefix)
        next_seq = len(prefix) + 1
        for status in invalid_next:
            rejected_scan(db, s, next_seq, "2030-01-02 08:00:00", status,
                          db.world.destination, MSG_BAD_TRANSITION)
        assert shipment_state(db.reader, s) == (prefix[-1], None)

    def test_delivered_is_terminal(self, db):
        s = booked_shipment(db)
        advance(db, s, TO_OUT_FOR_DELIVERY + ["DELIVERED"],
                PREFIX_TS + ["2030-01-01 12:00:00"])
        assert shipment_state(db.reader, s) == ("DELIVERED", "ON_TIME")
        for status in ["RECEIVED", "IN_TRANSIT", "ARRIVED_AT_HUB",
                       "OUT_FOR_DELIVERY", "DELIVERED"]:
            rejected_scan(db, s, 6, "2030-01-02 08:00:00", status, db.world.destination,
                          MSG_BAD_TRANSITION)
        assert shipment_state(db.reader, s) == ("DELIVERED", "ON_TIME")
        assert len(scan_history(db.reader, s)) == 5


class TestDeliveryOutcome:

    @pytest.mark.parametrize("promise, delivered_at, outcome", [
        ("2030-03-15", "2030-03-14 10:00:00", "ON_TIME"),   # before promise date
        ("2030-03-15", "2030-03-15 00:00:00", "ON_TIME"),   # start of promise date
        ("2030-03-15", "2030-03-15 23:59:59", "ON_TIME"),   # end of promise date
        ("2030-03-15", "2030-03-16 00:00:00", "LATE"),      # first second after
        ("2030-01-31", "2030-01-31 23:59:59", "ON_TIME"),   # month end
        ("2030-02-28", "2030-03-01 00:00:00", "LATE"),      # month boundary
        ("2030-12-31", "2031-01-01 00:00:00", "LATE"),      # year boundary
    ])
    def test_delivered_scan_sets_outcome(self, db, promise, delivered_at, outcome):
        s = booked_shipment(db, promise=promise)
        advance(db, s, TO_OUT_FOR_DELIVERY)
        assert shipment_state(db.reader, s) == ("OUT_FOR_DELIVERY", None)
        db.scanner.append(s, delivered_at, "DELIVERED", db.world.destination)
        assert shipment_state(db.reader, s) == ("DELIVERED", outcome)

    def test_undelivered_shipment_past_promise_keeps_null_outcome(self, db):
        s = booked_shipment(db, promise="2030-01-01")
        advance(db, s, TO_OUT_FOR_DELIVERY,
                ["2030-01-05 08:00:00", "2030-01-05 09:00:00",
                 "2030-01-05 10:00:00", "2030-01-05 11:00:00"])
        assert shipment_state(db.reader, s) == ("OUT_FOR_DELIVERY", None)

    def test_rolled_back_delivery_reverts_scan_and_derived_state(self, db):
        s = booked_shipment(db)
        advance(db, s, TO_OUT_FOR_DELIVERY)
        sc = db.scanner
        try:
            assert sc.begin_locked(s) == 1
            sc.insert_row(s, 5, "2030-01-01 12:00:00", "DELIVERED", db.world.destination)
            # Inside the same transaction the AFTER trigger's update is visible...
            assert shipment_state(sc.conn, s) == ("DELIVERED", "ON_TIME")
            # ...but not to other connections before commit.
            assert shipment_state(db.reader, s) == ("OUT_FOR_DELIVERY", None)
        finally:
            sc.rollback()
        assert shipment_state(db.reader, s) == ("OUT_FOR_DELIVERY", None)
        assert [r[2] for r in scan_history(db.reader, s)] == TO_OUT_FOR_DELIVERY


class TestScanNegative:

    def test_repeatable_read_session_rejected(self, db):
        s = booked_shipment(db)
        rr = db.connect()
        execute(rr, "SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert session_isolation(rr) == "REPEATABLE-READ"
        # Isolation is per connection: the scanner session is unaffected.
        assert session_isolation(db.scanner.conn) == "READ-COMMITTED"
        execute(rr, "START TRANSACTION")
        try:
            assert len(fetchall(rr, "SELECT shipment_id FROM shipment WHERE shipment_id = %s "
                                    "FOR UPDATE", (s,))) == 1
            expect_db_error(execute, rr,
                            "INSERT INTO scan_event (shipment_id, scan_sequence, "
                            "scan_timestamp, status, hub_id) VALUES (%s, 1, %s, 'RECEIVED', %s)",
                            (s, "2030-03-10 08:00:00", db.world.origin),
                            codes=ER_SIGNAL_EXCEPTION, message=MSG_SCAN_ISOLATION)
        finally:
            rr.rollback()
        assert shipment_state(db.reader, s) == (None, None)
        assert scan_history(db.reader, s) == []

    def test_nonexistent_shipment_rejected(self, db):
        missing = absent_id(db.reader, "shipment", "shipment_id")
        rejected_scan(db, missing, 1, "2030-03-10 08:00:00", "RECEIVED", db.world.origin,
                      MSG_SCAN_NO_SHIPMENT, expect_shipment=False)

    def test_nonexistent_hub_rejected_by_fk(self, db):
        s = booked_shipment(db)
        missing_hub = absent_id(db.reader, "hub", "hub_id")
        rejected_scan(db, s, 1, "2030-03-10 08:00:00", "RECEIVED", missing_hub, None,
                      codes=ER_NO_REFERENCED_ROW)
        assert shipment_state(db.reader, s) == (None, None)

    @pytest.mark.parametrize("bad_status", ["received", "RECEIVED ", "LOST", ""])
    def test_invalid_status_value_rejected(self, db, bad_status):
        s = booked_shipment(db)
        rejected_scan(db, s, 1, "2030-03-10 08:00:00", bad_status, db.world.origin,
                      MSG_INVALID_STATUS)

    def test_null_timestamp_rejected(self, db):
        # Either the trigger's explicit check or the NOT NULL column may fire first.
        s = booked_shipment(db)
        err = expect_db_error(db.scanner.insert, s, 1, None, "RECEIVED", db.world.origin,
                              codes=(ER_SIGNAL_EXCEPTION, ER_BAD_NULL))
        if err.args[0] == ER_SIGNAL_EXCEPTION:
            assert MSG_TS_REQUIRED in err.args[1]
        assert in_transaction(db.scanner.conn) == 0
        assert shipment_state(db.reader, s) == (None, None)
        assert scan_history(db.reader, s) == []

    def test_null_status_rejected(self, db):
        s = booked_shipment(db)
        err = expect_db_error(db.scanner.insert, s, 1, "2030-03-10 08:00:00", None,
                              db.world.origin, codes=(ER_SIGNAL_EXCEPTION, ER_BAD_NULL))
        if err.args[0] == ER_SIGNAL_EXCEPTION:
            assert MSG_INVALID_STATUS in err.args[1]
        assert shipment_state(db.reader, s) == (None, None)
        assert scan_history(db.reader, s) == []

    def test_failed_scan_after_history_keeps_state(self, db):
        s = booked_shipment(db)
        advance(db, s, ["RECEIVED", "IN_TRANSIT"])
        rejected_scan(db, s, 3, "2030-01-01 12:00:00", "DELIVERED", db.world.destination,
                      MSG_BAD_TRANSITION)
        assert shipment_state(db.reader, s) == ("IN_TRANSIT", None)


def test_scan_session_isolation_is_connection_specific(db):
    """SET SESSION isolation on the scan connection must not leak to others."""
    other = db.connect()
    assert session_isolation(db.scanner.conn) == "READ-COMMITTED"
    before = session_isolation(other)
    ScanSession(db.connect())  # configures a different connection
    assert session_isolation(other) == before
