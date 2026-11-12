"""Concurrency tests with independent database connections.

Coordination is deterministic, not sleep-based:
* A controller connection (main thread) holds the contended row lock.
* Each worker thread opens its OWN connection inside the thread (PyMySQL
  connections are never shared across threads) and signals readiness.
* Workers are released one at a time; the main thread polls
  information_schema.PROCESSLIST (own sessions are visible without the PROCESS
  privilege) until the worker is observed executing the exact locking
  statement, i.e. it is queued behind the controller's lock.
* Only then is the controller's transaction ended.
All waits are bounded (WAIT_LIMIT, innodb_lock_wait_timeout, thread joins),
and stay below the driver's 10 s read timeout.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal as D

import pymysql
import pytest

from db_helpers import (
    ER_SIGNAL_EXCEPTION, MSG_ALREADY_BOOKED, MSG_BAD_TRANSITION, MSG_CAPACITY,
    MSG_SEQ_ORDER, MSG_TS_BACKWARD, ScanSession, book_shipment, bookings_of_shipment,
    departure_load, execute, fetchall, fetchone, in_transaction, open_test_connection,
    safe_close, scan_history, shipment_state,
)

pytestmark = pytest.mark.concurrency

WAIT_LIMIT = 6.0          # seconds to observe a worker blocked / receive signals
JOIN_LIMIT = 9.0          # seconds to wait for a worker to finish after release
WORKER_LOCK_TIMEOUT = 8   # innodb_lock_wait_timeout for worker sessions

DEPARTURE_LOCK_SQL = ("FROM departure", "FOR UPDATE")
SHIPMENT_LOCK_SQL = ("FROM shipment", "FOR UPDATE")


class Worker(threading.Thread):
    """Runs prepare(conn) then, after `go`, action(conn, ctx) on its own connection."""

    def __init__(self, name, action, prepare=None):
        super().__init__(name=name, daemon=True)
        self.action, self.prepare = action, prepare
        self.ready, self.go, self.finished = threading.Event(), threading.Event(), threading.Event()
        self.conn_id = None
        self.ctx = None           # value returned by prepare
        self.result = None       # value returned by action
        self.db_error = None      # (code, message) of a pymysql error from action
        self.crash = None         # any other exception (test-code problem)
        self.idle_after = None    # @@in_transaction after action (must be 0)

    def run(self):
        conn = None
        try:
            conn = open_test_connection(WORKER_LOCK_TIMEOUT)
            self.conn_id = int(fetchone(conn, "SELECT CONNECTION_ID()")[0])
            ctx = self.ctx = self.prepare(conn) if self.prepare else None
            self.ready.set()
            if not self.go.wait(WAIT_LIMIT * 3):
                raise TimeoutError("go signal never arrived")
            try:
                self.result = self.action(conn, ctx)
            except pymysql.MySQLError as exc:
                self.db_error = (exc.args[0], exc.args[1] if len(exc.args) > 1 else "")
                try:
                    conn.rollback()
                except pymysql.MySQLError:
                    pass
            self.idle_after = in_transaction(conn)
        except BaseException as exc:  # recorded and asserted on by the test
            self.crash = exc
        finally:
            self.ready.set()
            safe_close(conn)
            self.finished.set()


def start_ready(*workers):
    for w in workers:
        w.start()
    for w in workers:
        assert w.ready.wait(WAIT_LIMIT), f"{w.name} never became ready"
        assert w.crash is None, f"{w.name} failed during setup: {w.crash!r}"


def release_and_await_block(observer, worker, statement_fragments):
    """Release `worker` and wait until PROCESSLIST shows it blocked on the lock."""
    worker.go.set()
    deadline = time.monotonic() + WAIT_LIMIT
    last = None
    while time.monotonic() < deadline:
        assert not worker.finished.is_set(), (
            f"{worker.name} finished before blocking (result={worker.result!r}, "
            f"error={worker.db_error!r}, crash={worker.crash!r}); lock was not contended")
        row = fetchone(observer, "SELECT COMMAND, STATE, INFO FROM information_schema.PROCESSLIST "
                                 "WHERE ID = %s", (worker.conn_id,))
        last = row
        if row and row[0] == "Query" and row[2] and all(f in row[2] for f in statement_fragments):
            return row
        time.sleep(0.02)
    pytest.fail(f"BLOCKED: could not observe {worker.name} waiting on "
                f"{statement_fragments} within {WAIT_LIMIT}s (last PROCESSLIST row: {last!r})")


def join_all(*workers):
    for w in workers:
        w.join(JOIN_LIMIT)
        assert not w.is_alive(), f"{w.name} did not finish within {JOIN_LIMIT}s"
        assert w.crash is None, f"{w.name} crashed: {w.crash!r}"
        assert w.idle_after == 0, f"{w.name} left a transaction open"


def lock_row(controller, sql, row_id):
    execute(controller, "START TRANSACTION")
    assert len(fetchall(controller, sql, (row_id,))) == 1


def booking_action(shipment_id, departure_id):
    def action(conn, _ctx):
        book_shipment(conn, shipment_id, departure_id)
        return "BOOKED"
    return action


def run_competing_calls(db, lock_sql, lock_id, lock_fragments, calls, order):
    """Controller holds a lock; workers' CALLs queue in `order`; then release."""
    controller, observer = db.connect(), db.connect()
    workers = [Worker(name, booking_action(s, d)) for name, (s, d) in calls.items()]
    by_name = {w.name: w for w in workers}
    try:
        start_ready(*workers)
        lock_row(controller, lock_sql, lock_id)
        for name in order:
            release_and_await_block(observer, by_name[name], lock_fragments)
        # Both CALLs are now queued behind the controller; neither may have finished.
        assert not any(w.finished.is_set() for w in workers)
        controller.commit()
        join_all(*workers)
    finally:
        safe_close(controller)
        for w in workers:
            w.go.set()
            w.join(JOIN_LIMIT)
    return by_name


ORDERS = [("A", "B"), ("B", "A")]


# ==========================================================================
# C1: two bookings compete for the remaining departure capacity
# ==========================================================================

@pytest.mark.parametrize("order", ORDERS, ids=["A_first", "B_first"])
def test_c1_competing_bookings_cannot_overfill_departure(db, order):
    w = db.world
    dep = w.add_departure("100.00")
    s_a, s_b = w.add_shipment("60.00"), w.add_shipment("60.00")
    res = run_competing_calls(
        db, "SELECT departure_id FROM departure WHERE departure_id = %s FOR UPDATE", dep,
        DEPARTURE_LOCK_SQL, {"A": (s_a, dep), "B": (s_b, dep)}, order)

    winners = [n for n, wk in res.items() if wk.result == "BOOKED"]
    losers = [n for n, wk in res.items() if wk.db_error is not None]
    assert len(winners) == 1 and len(losers) == 1, {n: (wk.result, wk.db_error)
                                                    for n, wk in res.items()}
    code, msg = res[losers[0]].db_error
    assert code == ER_SIGNAL_EXCEPTION and MSG_CAPACITY in msg
    count, total = departure_load(db.reader, dep)
    assert (count, total) == (1, D("60.00"))
    assert total <= D("100.00")


@pytest.mark.parametrize("order", ORDERS, ids=["A_first", "B_first"])
def test_c1_competing_bookings_that_fit_both_succeed(db, order):
    w = db.world
    dep = w.add_departure("100.00")
    s_a, s_b = w.add_shipment("60.00"), w.add_shipment("40.00")
    res = run_competing_calls(
        db, "SELECT departure_id FROM departure WHERE departure_id = %s FOR UPDATE", dep,
        DEPARTURE_LOCK_SQL, {"A": (s_a, dep), "B": (s_b, dep)}, order)
    assert all(wk.result == "BOOKED" and wk.db_error is None for wk in res.values()), \
        {n: (wk.result, wk.db_error) for n, wk in res.items()}
    assert departure_load(db.reader, dep) == (2, D("100.00"))


# ==========================================================================
# C2: one shipment booked concurrently (different departures / same departure)
# ==========================================================================

@pytest.mark.parametrize("order", ORDERS, ids=["A_first", "B_first"])
def test_c2_one_shipment_two_departures_books_once(db, order):
    w = db.world
    dep1 = w.add_departure("100.00")
    dep2 = w.add_departure("100.00", when="2030-03-10 09:00:00")
    s = w.add_shipment("60.00")
    # Lock the shipment: each CALL takes its own departure lock, then queues on it.
    res = run_competing_calls(
        db, "SELECT shipment_id FROM shipment WHERE shipment_id = %s FOR UPDATE", s,
        SHIPMENT_LOCK_SQL, {"A": (s, dep1), "B": (s, dep2)}, order)
    results = {n: (wk.result, wk.db_error) for n, wk in res.items()}
    winners = [n for n, wk in res.items() if wk.result == "BOOKED"]
    assert len(winners) == 1, results
    loser = res["B" if winners[0] == "A" else "A"]
    assert loser.db_error[0] == ER_SIGNAL_EXCEPTION and MSG_ALREADY_BOOKED in loser.db_error[1]
    booked = bookings_of_shipment(db.reader, s)
    assert booked == [dep1 if winners[0] == "A" else dep2]
    assert departure_load(db.reader, dep1)[0] + departure_load(db.reader, dep2)[0] == 1


def test_c2_duplicate_concurrent_calls_same_departure_book_once(db):
    w = db.world
    dep = w.add_departure("100.00")
    s = w.add_shipment("60.00")
    res = run_competing_calls(
        db, "SELECT departure_id FROM departure WHERE departure_id = %s FOR UPDATE", dep,
        DEPARTURE_LOCK_SQL, {"A": (s, dep), "B": (s, dep)}, ("A", "B"))
    outcomes = sorted([wk.result or wk.db_error[1] for wk in res.values()])
    assert outcomes == sorted(["BOOKED", MSG_ALREADY_BOOKED]), outcomes
    assert bookings_of_shipment(db.reader, s) == [dep]
    assert departure_load(db.reader, dep) == (1, D("60.00"))


# ==========================================================================
# C3/C4: scan append serialization through the shipment prelock
# ==========================================================================

def prepare_scan_session(shipment_id):
    """READ COMMITTED session + open transaction + pre-lock history read."""
    def prepare(conn):
        ScanSession(conn)
        execute(conn, "START TRANSACTION")
        seen = [r[0] for r in fetchall(conn, "SELECT scan_sequence FROM scan_event "
                                             "WHERE shipment_id = %s ORDER BY scan_sequence",
                                       (shipment_id,))]
        return {"seen_before_lock": seen}
    return prepare


def scan_action(shipment_id, ts, status, hub, *, stale_sequence=None):
    """Prelock (blocks), then insert recomputed (or stale) sequence and COMMIT."""
    def action(conn, ctx):
        assert len(fetchall(conn, "SELECT shipment_id FROM shipment WHERE shipment_id = %s "
                                  "FOR UPDATE", (shipment_id,))) == 1
        seq = stale_sequence or int(fetchone(
            conn, "SELECT COALESCE(MAX(scan_sequence), 0) + 1 FROM scan_event "
                  "WHERE shipment_id = %s", (shipment_id,))[0])
        ctx["sequence"] = seq
        execute(conn, "INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, "
                      "status, hub_id) VALUES (%s, %s, %s, %s, %s)",
                (shipment_id, seq, ts, status, hub))
        conn.commit()
        return seq
    return action


def booked_with_scans(db, statuses, promise="2030-03-15"):
    w = db.world
    dep = w.add_departure("1000.00")
    s = w.add_shipment("10.00", promise=promise)
    book_shipment(db.booker, s, dep)
    hubs = {"RECEIVED": w.origin, "IN_TRANSIT": w.origin, "ARRIVED_AT_HUB": w.destination,
            "OUT_FOR_DELIVERY": w.destination}
    for i, status in enumerate(statuses):
        db.scanner.append(s, f"2030-03-10 {8 + i:02d}:00:00", status, hubs[status])
    return s


def run_scan_race(db, shipment_id, a_row, a_finish, b_worker):
    """A (main-thread scanner) inserts uncommitted; B queues on the prelock."""
    observer = db.connect()
    sc = db.scanner
    try:
        start_ready(b_worker)
        assert sc.begin_locked(shipment_id) == 1
        sc.insert_row(shipment_id, *a_row)
        release_and_await_block(observer, b_worker, SHIPMENT_LOCK_SQL)
        assert not b_worker.finished.is_set()
        sc.commit() if a_finish == "commit" else sc.rollback()
        join_all(b_worker)
    finally:
        if in_transaction(sc.conn):
            sc.conn.rollback()
        b_worker.go.set()
        b_worker.join(JOIN_LIMIT)


def test_c3_second_scanner_waits_then_appends_after_commit(db):
    w = db.world
    s = booked_with_scans(db, ["RECEIVED"])
    b = Worker("B", scan_action(s, "2030-03-10 12:00:00", "ARRIVED_AT_HUB", w.intermediate),
               prepare=prepare_scan_session(s))
    run_scan_race(db, s, (2, "2030-03-10 11:00:00", "IN_TRANSIT", w.origin), "commit", b)
    # B's pre-lock read could not see A's uncommitted scan 2 ...
    assert b.ctx["seen_before_lock"] == [1]
    # ... but after the prelock it recomputed from committed state.
    assert b.db_error is None and b.result == 3
    assert [(r[0], r[2]) for r in scan_history(db.reader, s)] == \
        [(1, "RECEIVED"), (2, "IN_TRANSIT"), (3, "ARRIVED_AT_HUB")]
    assert shipment_state(db.reader, s) == ("ARRIVED_AT_HUB", None)


def test_c3_stale_sequence_after_wait_is_rejected(db):
    w = db.world
    s = booked_with_scans(db, ["RECEIVED"])
    b = Worker("B", scan_action(s, "2030-03-10 12:00:00", "IN_TRANSIT", w.origin,
                                stale_sequence=2), prepare=prepare_scan_session(s))
    run_scan_race(db, s, (2, "2030-03-10 11:00:00", "IN_TRANSIT", w.origin), "commit", b)
    assert b.result is None
    assert b.db_error[0] == ER_SIGNAL_EXCEPTION and MSG_SEQ_ORDER in b.db_error[1]
    assert [(r[0], r[2]) for r in scan_history(db.reader, s)] == \
        [(1, "RECEIVED"), (2, "IN_TRANSIT")]
    assert shipment_state(db.reader, s) == ("IN_TRANSIT", None)


def test_c3_second_scanner_sees_rollback_and_appends_next(db):
    w = db.world
    s = booked_with_scans(db, ["RECEIVED"])
    b = Worker("B", scan_action(s, "2030-03-10 12:00:00", "IN_TRANSIT", w.intermediate),
               prepare=prepare_scan_session(s))
    run_scan_race(db, s, (2, "2030-03-10 11:00:00", "IN_TRANSIT", w.origin), "rollback", b)
    assert b.db_error is None and b.result == 2
    assert scan_history(db.reader, s) == [
        (1, "2030-03-10 08:00:00", "RECEIVED", w.origin),
        (2, "2030-03-10 12:00:00", "IN_TRANSIT", w.intermediate)]
    assert shipment_state(db.reader, s) == ("IN_TRANSIT", None)


@pytest.mark.parametrize("promise, delivered_at, outcome, b_status, b_ts, b_message", [
    ("2030-03-15", "2030-03-14 10:00:00", "ON_TIME", "IN_TRANSIT", "2030-03-14 11:00:00",
     MSG_BAD_TRANSITION),
    ("2030-03-15", "2030-03-14 10:00:00", "ON_TIME", "DELIVERED", "2030-03-14 11:00:00",
     MSG_BAD_TRANSITION),
    ("2030-03-12", "2030-03-14 10:00:00", "LATE", "IN_TRANSIT", "2030-03-14 11:00:00",
     MSG_BAD_TRANSITION),
    ("2030-03-12", "2030-03-14 10:00:00", "LATE", "DELIVERED", "2030-03-14 09:00:00",
     MSG_TS_BACKWARD),
], ids=["on_time_then_in_transit", "on_time_then_redeliver", "late_then_in_transit",
        "late_then_earlier_timestamp"])
def test_c4_concurrent_scan_cannot_undo_delivery(db, promise, delivered_at, outcome,
                                                 b_status, b_ts, b_message):
    w = db.world
    s = booked_with_scans(db, ["RECEIVED", "IN_TRANSIT", "ARRIVED_AT_HUB",
                               "OUT_FOR_DELIVERY"], promise=promise)
    b = Worker("B", scan_action(s, b_ts, b_status, w.destination),
               prepare=prepare_scan_session(s))
    run_scan_race(db, s, (5, delivered_at, "DELIVERED", w.destination), "commit", b)
    assert b.result is None and b.db_error is not None, (b.result, b.db_error)
    assert b.db_error[0] == ER_SIGNAL_EXCEPTION and b_message in b.db_error[1]
    assert shipment_state(db.reader, s) == ("DELIVERED", outcome)
    assert [r[2] for r in scan_history(db.reader, s)][-1] == "DELIVERED"
    assert len(scan_history(db.reader, s)) == 5
