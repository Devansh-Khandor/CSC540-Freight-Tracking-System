"""Shared helpers for the functional database tests.

Safety rules enforced here:
* Every connection is verified to be on schema ``sshett24`` (SELECT DATABASE())
  before it is handed to any test or used for any write.
* No DDL, TRUNCATE, or USE statement is ever issued.
* Cleanup deletes only rows whose IDs were recorded by this test run, in
  FK-safe reverse dependency order, with extra ownership predicates.
* Nothing in this module prints or logs credentials or .env contents.
"""

from __future__ import annotations

import pymysql
import pytest

from app.db import get_connection

EXPECTED_SCHEMA = "sshett24"
STRICT_SQL_MODE = (
    "STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ZERO_DATE,"
    "NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION"
)

# MariaDB error numbers used in assertions.
ER_SIGNAL_EXCEPTION = 1644      # SIGNAL SQLSTATE '45000'
ER_DUP_ENTRY = 1062
ER_NO_REFERENCED_ROW = 1452     # FK child insert with missing parent
ER_BAD_NULL = 1048
ER_LOCK_WAIT_TIMEOUT = 1205
ER_CONSTRAINT_FAILED = 4025     # CHECK constraint violation (MariaDB)

# Exact message texts raised by sql/01_schema.sql.
MSG_IDLE = "book_shipment requires an idle connection; finish the current transaction"
MSG_IDS_POSITIVE = "Shipment ID and departure ID must be positive"
MSG_NO_DEPARTURE = "Departure does not exist"
MSG_NO_SHIPMENT = "Shipment does not exist"
MSG_LANE_MISMATCH = "Shipment lane does not match the ordered departure lane"
MSG_ALREADY_BOOKED = "Shipment is already booked"
MSG_CAPACITY = "Departure weight capacity would be exceeded"
MSG_SCAN_ISOLATION = "Scan inserts require READ COMMITTED and the documented shipment prelock"
MSG_SEQ_POSITIVE = "scan_sequence must be positive"
MSG_TS_REQUIRED = "scan_timestamp is required"
MSG_INVALID_STATUS = "Invalid scan status"
MSG_SCAN_NO_SHIPMENT = "Scan shipment does not exist"
MSG_SEQ_ORDER = "scan_sequence must be 1 initially, then exactly previous sequence plus 1"
MSG_FIRST_RECEIVED = "The first scan must be RECEIVED"
MSG_TS_BACKWARD = "Scan timestamps cannot move backward"
MSG_BAD_TRANSITION = "Invalid or regressing scan status transition"


class SchemaGuardError(RuntimeError):
    """The connection is not on the one schema these tests may write to."""


# --------------------------------------------------------------------------
# Connections and small query helpers
# --------------------------------------------------------------------------

def fetchone(conn, sql, args=None):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def fetchall(conn, sql, args=None):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return list(cur.fetchall())


def execute(conn, sql, args=None):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid


def assert_expected_schema(conn) -> None:
    (name,) = fetchone(conn, "SELECT DATABASE()")
    if name != EXPECTED_SCHEMA:
        raise SchemaGuardError(
            f"Refusing to run: SELECT DATABASE() is not {EXPECTED_SCHEMA!r}.")


def in_transaction(conn) -> int:
    return int(fetchone(conn, "SELECT @@SESSION.in_transaction")[0])


def session_isolation(conn) -> str:
    return fetchone(conn, "SELECT @@SESSION.tx_isolation")[0]


def open_test_connection(lock_wait_timeout: int = 5):
    """Open an autocommit connection, verify the schema, set strict session mode.

    Autocommit is on so that no statement silently opens a transaction; every
    multi-statement unit below uses an explicit START TRANSACTION.
    """
    conn = get_connection()
    try:
        conn.autocommit(True)
        assert_expected_schema(conn)
        execute(conn, "SET SESSION sql_mode = %s", (STRICT_SQL_MODE,))
        execute(conn, "SET SESSION innodb_lock_wait_timeout = %s", (lock_wait_timeout,))
        fk, chk = fetchone(conn, "SELECT @@SESSION.foreign_key_checks, "
                                 "@@SESSION.check_constraint_checks")
        if int(fk) != 1 or int(chk) != 1:
            raise SchemaGuardError("FK and CHECK enforcement must both be enabled.")
    except BaseException:
        conn.close()
        raise
    return conn


def safe_close(conn) -> None:
    """Roll back anything open and close; never raise from teardown helpers."""
    if conn is None:
        return
    try:
        if conn.open:
            try:
                conn.rollback()
            finally:
                conn.close()
    except Exception:
        pass


def expect_db_error(fn, *args, codes, message=None, **kwargs):
    """Run fn(*args, **kwargs); assert a pymysql error with one of `codes` (and message)."""
    if isinstance(codes, int):
        codes = (codes,)
    with pytest.raises(pymysql.MySQLError) as info:
        fn(*args, **kwargs)
    err = info.value
    code = err.args[0] if err.args else None
    text = err.args[1] if len(err.args) > 1 else ""
    assert code in codes, f"expected error code in {codes}, got {code}: {text}"
    if message is not None:
        assert message in text, f"expected message {message!r}, got {text!r}"
    return err


def in_rolled_back_transaction(conn, sql, args=None):
    """Execute one statement inside a transaction that is always rolled back."""
    execute(conn, "START TRANSACTION")
    try:
        execute(conn, sql, args)
    finally:
        conn.rollback()


# --------------------------------------------------------------------------
# Booking procedure
# --------------------------------------------------------------------------

def book_shipment(conn, shipment_id, departure_id) -> None:
    """CALL book_shipment on an idle connection (the procedure owns its txn)."""
    assert in_transaction(conn) == 0, "book_shipment must be called on an idle connection"
    with conn.cursor() as cur:
        cur.execute("CALL book_shipment(%s, %s)", (shipment_id, departure_id))
        while cur.nextset():
            pass


# --------------------------------------------------------------------------
# Scan protocol (READ COMMITTED session + separate shipment prelock)
# --------------------------------------------------------------------------

class ScanSession:
    """Owns one connection configured for the documented scan protocol."""

    def __init__(self, conn):
        self.conn = conn
        execute(conn, "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
        assert session_isolation(conn) == "READ-COMMITTED"

    def begin_locked(self, shipment_id) -> int:
        """START TRANSACTION and take the documented shipment prelock.

        Returns how many shipment rows the prelock found (0 or 1).
        """
        assert in_transaction(self.conn) == 0, "scan must start on an idle connection"
        assert session_isolation(self.conn) == "READ-COMMITTED"
        execute(self.conn, "START TRANSACTION")
        rows = fetchall(self.conn,
                        "SELECT shipment_id FROM shipment WHERE shipment_id = %s FOR UPDATE",
                        (shipment_id,))
        return len(rows)

    def next_sequence(self, shipment_id) -> int:
        return int(fetchone(self.conn,
                            "SELECT COALESCE(MAX(scan_sequence), 0) + 1 FROM scan_event "
                            "WHERE shipment_id = %s", (shipment_id,))[0])

    def insert_row(self, shipment_id, seq, ts, status, hub_id) -> None:
        execute(self.conn,
                "INSERT INTO scan_event "
                "(shipment_id, scan_sequence, scan_timestamp, status, hub_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (shipment_id, seq, ts, status, hub_id))

    def commit(self) -> None:
        self.conn.commit()
        assert in_transaction(self.conn) == 0

    def rollback(self) -> None:
        self.conn.rollback()
        assert in_transaction(self.conn) == 0

    def insert(self, shipment_id, seq, ts, status, hub_id, *, expect_shipment=True) -> None:
        """One scan in its own transaction: prelock, INSERT, COMMIT (ROLLBACK on error)."""
        try:
            found = self.begin_locked(shipment_id)
            if expect_shipment:
                assert found == 1, "prelock must find the shipment row"
            else:
                assert found == 0, "prelock unexpectedly found a shipment row"
            self.insert_row(shipment_id, seq, ts, status, hub_id)
            self.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def append(self, shipment_id, ts, status, hub_id) -> int:
        """Documented protocol: compute next sequence while holding the prelock."""
        try:
            assert self.begin_locked(shipment_id) == 1
            seq = self.next_sequence(shipment_id)
            self.insert_row(shipment_id, seq, ts, status, hub_id)
            self.commit()
            return seq
        except BaseException:
            self.conn.rollback()
            raise


# --------------------------------------------------------------------------
# Read-only state inspection (autocommit => each SELECT sees latest commits)
# --------------------------------------------------------------------------

def departure_load(conn, departure_id):
    count, total = fetchone(
        conn,
        "SELECT COUNT(b.shipment_id), COALESCE(SUM(s.weight_kg), 0.00) "
        "FROM booking AS b JOIN shipment AS s ON s.shipment_id = b.shipment_id "
        "WHERE b.departure_id = %s", (departure_id,))
    return int(count), total


def bookings_of_shipment(conn, shipment_id):
    return [r[0] for r in fetchall(
        conn, "SELECT departure_id FROM booking WHERE shipment_id = %s "
              "ORDER BY departure_id", (shipment_id,))]


def shipment_state(conn, shipment_id):
    row = fetchone(conn, "SELECT current_status, delivery_outcome FROM shipment "
                         "WHERE shipment_id = %s", (shipment_id,))
    assert row is not None, f"shipment {shipment_id} not found"
    return tuple(row)


def scan_history(conn, shipment_id):
    return [(int(seq), ts.strftime("%Y-%m-%d %H:%M:%S"), status, int(hub))
            for seq, ts, status, hub in fetchall(
                conn, "SELECT scan_sequence, scan_timestamp, status, hub_id "
                      "FROM scan_event WHERE shipment_id = %s ORDER BY scan_sequence",
                (shipment_id,))]


def absent_id(conn, table, column) -> int:
    """A positive ID confirmed absent right now (never assumed)."""
    assert (table, column) in {("shipment", "shipment_id"), ("departure", "departure_id"),
                               ("hub", "hub_id")}
    (candidate,) = fetchone(conn, f"SELECT COALESCE(MAX({column}), 0) + 100000 FROM {table}")
    (exists,) = fetchone(conn, f"SELECT COUNT(*) FROM {table} WHERE {column} = %s",
                         (candidate,))
    assert exists == 0
    return int(candidate)


# --------------------------------------------------------------------------
# Fixture world: creates, records and cleans up this run's rows only
# --------------------------------------------------------------------------

def _in_list(values):
    return ", ".join(["%s"] * len(values))


class FixtureWorld:
    """Deterministic fixture graph compatible with every FK and CHECK.

    All rows are committed (book_shipment runs its own transaction on another
    connection, so it can only see committed fixtures). Every generated ID is
    recorded immediately so cleanup can remove exactly these rows.
    """

    def __init__(self, conn, run_tag: str):
        self.conn = conn
        self.tag = run_tag
        self.accounts: list[int] = []
        self.shippers: list[int] = []
        self.carriers: list[int] = []
        self.hubs: list[int] = []
        self.lanes: list[tuple[int, int]] = []
        self.vehicles: list[int] = []
        self.box_trucks: list[int] = []
        self.departures: list[int] = []
        self.shipments: list[int] = []
        self.cleaned = False
        self.shipper = self.carrier = self.vehicle = None
        self.origin = self.destination = self.intermediate = None

    # -- creation ---------------------------------------------------------
    def _account(self, role):
        account_id = execute(self.conn, "INSERT INTO account (password, role) VALUES (%s, %s)",
                             (f"{self.tag}-{role}-NOT-A-LOGIN", role))
        self.accounts.append(account_id)
        return account_id

    def _hub(self, region):
        hub_id = execute(self.conn, "INSERT INTO hub (region) VALUES (%s)", (region,))
        self.hubs.append(hub_id)
        return hub_id

    def _lane(self, origin, destination):
        execute(self.conn, "INSERT INTO lane (origin_hub_id, destination_hub_id) "
                           "VALUES (%s, %s)", (origin, destination))
        self.lanes.append((origin, destination))

    def build(self):
        assert_expected_schema(self.conn)
        execute(self.conn, "START TRANSACTION")
        try:
            self.shipper = self._account("SHIPPER")
            execute(self.conn, "INSERT INTO shipper (account_id) VALUES (%s)", (self.shipper,))
            self.shippers.append(self.shipper)
            self.carrier = self._account("CARRIER")
            execute(self.conn, "INSERT INTO carrier (account_id) VALUES (%s)", (self.carrier,))
            self.carriers.append(self.carrier)
            self.origin = self._hub("Northeast")
            self.destination = self._hub("West")
            self.intermediate = self._hub("Midwest")
            self._lane(self.origin, self.destination)
            self._lane(self.destination, self.origin)
            self._lane(self.origin, self.intermediate)
            self.vehicle = execute(
                self.conn, "INSERT INTO vehicle (carrier_account_id, home_hub_id) "
                           "VALUES (%s, %s)", (self.carrier, self.origin))
            self.vehicles.append(self.vehicle)
            execute(self.conn, "INSERT INTO box_truck (vehicle_id, cargo_volume, "
                               "gross_weight_rating) VALUES (%s, 20.00, 5000.00)",
                    (self.vehicle,))
            self.box_trucks.append(self.vehicle)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return self

    @property
    def main_lane(self):
        return (self.origin, self.destination)

    def add_departure(self, capacity, lane=None, when="2030-03-10 08:00:00"):
        origin, destination = lane or self.main_lane
        assert_expected_schema(self.conn)
        departure_id = execute(
            self.conn,
            "INSERT INTO departure (vehicle_id, origin_hub_id, destination_hub_id, "
            "departure_datetime, max_total_weight_kg) VALUES (%s, %s, %s, %s, %s)",
            (self.vehicle, origin, destination, when, capacity))
        self.departures.append(departure_id)
        return departure_id

    def add_shipment(self, weight, promise="2030-03-15", lane=None):
        origin, destination = lane or self.main_lane
        assert_expected_schema(self.conn)
        shipment_id = execute(
            self.conn,
            "INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id, "
            "weight_kg, promised_delivery_date) VALUES (%s, %s, %s, %s, %s)",
            (self.shipper, origin, destination, weight, promise))
        self.shipments.append(shipment_id)
        return shipment_id

    def track_shipment(self, shipment_id):
        """Record a shipment created outside add_shipment (e.g., an uncommitted probe)."""
        if shipment_id and shipment_id not in self.shipments:
            self.shipments.append(shipment_id)

    # -- cleanup ----------------------------------------------------------
    def remaining_row_count(self, conn) -> int:
        total = 0
        checks = [
            ("scan_event", "shipment_id", self.shipments),
            ("booking", "shipment_id", self.shipments),
            ("shipment", "shipment_id", self.shipments),
            ("departure", "departure_id", self.departures),
            ("box_truck", "vehicle_id", self.box_trucks),
            ("vehicle", "vehicle_id", self.vehicles),
            ("carrier", "account_id", self.carriers),
            ("shipper", "account_id", self.shippers),
            ("account", "account_id", self.accounts),
            ("hub", "hub_id", self.hubs),
        ]
        for table, column, ids in checks:
            if ids:
                total += fetchone(conn, f"SELECT COUNT(*) FROM {table} WHERE {column} "
                                        f"IN ({_in_list(ids)})", ids)[0]
        for origin, destination in self.lanes:
            total += fetchone(conn, "SELECT COUNT(*) FROM lane WHERE origin_hub_id = %s "
                                    "AND destination_hub_id = %s", (origin, destination))[0]
        return int(total)

    def cleanup(self) -> None:
        """Delete only this run's rows, reverse dependency order, own connection.

        A separate fresh connection is used because the test's connections may
        be in an aborted state. book_shipment commits on its own, so this
        explicit cleanup (not a rollback) is what removes successful bookings.
        """
        if self.cleaned:
            return
        conn = open_test_connection(lock_wait_timeout=10)
        try:
            assert_expected_schema(conn)
            execute(conn, "START TRANSACTION")
            s, d, v = self.shipments, self.departures, self.vehicles
            if d:
                foreign = fetchone(
                    conn, f"SELECT COUNT(*) FROM booking WHERE departure_id IN ({_in_list(d)})"
                          + (f" AND shipment_id NOT IN ({_in_list(s)})" if s else ""),
                    d + s)[0]
                if foreign:
                    raise RuntimeError("Unrelated bookings reference test departures; "
                                       "refusing to delete them.")
            if s:
                # Tracked IDs from rolled-back inserts may not exist; that is fine.
                # Any tracked shipment that DOES exist must belong to a test shipper.
                foreign_shipments = fetchone(
                    conn, f"SELECT COUNT(*) FROM shipment WHERE shipment_id IN ({_in_list(s)})"
                          + (f" AND shipper_account_id NOT IN ({_in_list(self.shippers)})"
                             if self.shippers else ""),
                    s + self.shippers)[0]
                if foreign_shipments:
                    raise RuntimeError("Tracked shipment IDs belong to a non-test shipper; "
                                       "refusing to delete anything.")
            if s:
                execute(conn, f"DELETE FROM scan_event WHERE shipment_id IN ({_in_list(s)})", s)
                execute(conn, f"DELETE FROM booking WHERE shipment_id IN ({_in_list(s)})", s)
                execute(conn, f"DELETE FROM shipment WHERE shipment_id IN ({_in_list(s)}) "
                              f"AND shipper_account_id IN ({_in_list(self.shippers)})",
                        s + self.shippers)
            if d:
                execute(conn, f"DELETE FROM departure WHERE departure_id IN ({_in_list(d)}) "
                              f"AND vehicle_id IN ({_in_list(v)})", d + v)
            if self.box_trucks:
                execute(conn, f"DELETE FROM box_truck WHERE vehicle_id "
                              f"IN ({_in_list(self.box_trucks)})", self.box_trucks)
            if v:
                execute(conn, f"DELETE FROM vehicle WHERE vehicle_id IN ({_in_list(v)}) "
                              f"AND carrier_account_id IN ({_in_list(self.carriers)})",
                        v + self.carriers)
            for origin, destination in self.lanes:
                execute(conn, "DELETE FROM lane WHERE origin_hub_id = %s "
                              "AND destination_hub_id = %s", (origin, destination))
            if self.carriers:
                execute(conn, f"DELETE FROM carrier WHERE account_id "
                              f"IN ({_in_list(self.carriers)})", self.carriers)
            if self.shippers:
                execute(conn, f"DELETE FROM shipper WHERE account_id "
                              f"IN ({_in_list(self.shippers)})", self.shippers)
            if self.accounts:
                # Extra guard: only accounts carrying this run's unique tag.
                execute(conn, f"DELETE FROM account WHERE account_id "
                              f"IN ({_in_list(self.accounts)}) AND LEFT(password, %s) = %s",
                        self.accounts + [len(self.tag), self.tag])
            if self.hubs:
                execute(conn, f"DELETE FROM hub WHERE hub_id IN ({_in_list(self.hubs)})",
                        self.hubs)
            # Verify inside the deletion transaction (this connection sees its own
            # deletes); an incomplete cleanup raises and the except path rolls back.
            left = self.remaining_row_count(conn)
            if left:
                raise RuntimeError(f"Cleanup incomplete: {left} test rows remain; "
                                   "deletion transaction rolled back.")
            conn.commit()
            self.cleaned = True
        except BaseException:
            safe_close(conn)
            raise
        else:
            conn.close()
