# Functional database testing report: booking procedure and scan triggers

**Status: executed and verified.** On 2026-11-11 the full suite passed against schema `sshett24`: 72 passed, 0 failed, 0 errors. That run included both final cleanup safety changes in `tests/db_helpers.py`. Afterwards, an independent check of the database found 0 remaining test rows (see [Run history](#run-history)). No business-rule defects were found in `book_shipment` or the two `scan_event` triggers. One defect was found in the test code itself and fixed (see [Defects found](#defects-found)).

Production objects were not modified. `sql/01_schema.sql`, `tests/schema_validation.sql`, the installed procedure and triggers, and the application code under `app/` are unchanged.

## Environment

| Item | Observed value |
|---|---|
| Server | `10.5.22-MariaDB` (`SELECT VERSION()`) |
| Schema | `sshett24` (`SELECT DATABASE()`, asserted on every connection) |
| Driver / runner | PyMySQL 2.2.8, pytest 9.2.0, Python 3.13.13 (project `.venv`) |
| Session default isolation | `REPEATABLE-READ` (scan connections switch their own session to `READ-COMMITTED`) |
| Binary logging | `log_bin = 0`, `binlog_format = MIXED`, so READ COMMITTED writes are not restricted |
| SQL mode set by tests | `STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ZERO_DATE,NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION` |
| FK / CHECK enforcement | `foreign_key_checks = 1`, `check_constraint_checks = 1` (asserted on every connection) |
| `information_schema.INNODB_TRX` | Not readable (error 1227, PROCESS privilege required). Lock waits are detected through `information_schema.PROCESSLIST` instead. |

Credentials are read only by the existing `app/db.py` from `.env`. The tests never print, log or store them.

## How to run

```bash
cd CSC540-Freight-Tracking-System
source .venv/bin/activate
python -m pip install -r requirements-dev.txt   # PyMySQL, python-dotenv, pytest

python -m pytest -v                              # whole suite (72 tests, about 90 s)
python -m pytest -v tests/test_database_rules.py # booking, constraint and scan tests (58)
python -m pytest -v -m concurrency               # concurrency tests only (14)
```

## Files added

| File | Purpose |
|---|---|
| `tests/db_helpers.py` | Schema guard, connection setup, error assertion helper, `book_shipment` wrapper, `ScanSession` (scan protocol), state queries, `FixtureWorld` (fixture creation and cleanup) |
| `tests/conftest.py` | Session-wide schema guard, per-test `db` fixture, end-of-session cleanup retry |
| `tests/test_database_rules.py` | Booking procedure, table constraints, scan triggers, delivery outcome |
| `tests/test_concurrency.py` | Multi-connection concurrency tests C1–C4 |
| `pytest.ini`, `requirements-dev.txt` | Test configuration and dev dependency |

## Safety design

- **Schema guard.** Each connection runs `SELECT DATABASE()` and must get `sshett24` before it is used. Any other result raises `SchemaGuardError`. A session-scoped autouse fixture runs the guard once before any test, so a mismatch aborts the run before anything is written. Cleanup re-checks the guard on its own connection. A negative check against a fake connection that reports another schema confirmed the guard rejects it.
- **Writes are limited to rows the tests create.** The tests never issue DDL, `TRUNCATE`, `DROP`, `USE` or bulk deletes.
- **Isolated, deterministic fixtures.** Each test builds its own committed graph: a shipper account and a carrier account, 3 hubs (Northeast, West, Midwest), 3 ordered lanes (origin→destination, destination→origin, origin→intermediate), one vehicle with a `box_truck` subtype row, and whatever departures and shipments the test adds. All dates and timestamps are fixed literals in 2030–2031, and no test uses `CURRENT_TIMESTAMP`. Every account's dummy password starts with a per-run tag, `PYTEST-CSC540-<12 hex>`, so leftover rows from a killed process would be identifiable.
- **Cleanup does not depend on rollback.** `book_shipment` commits its own transaction, so tests cannot clean up by rolling back. Every generated ID is recorded as soon as it is inserted. Teardown first closes (and rolls back) every test connection to release locks. It then deletes, on a fresh guarded connection and in reverse dependency order: `scan_event` → `booking` → `shipment` → `departure` → `box_truck` → `vehicle` → `lane` → `carrier` / `shipper` → `account` → `hub`.
  - Each delete is restricted to the recorded IDs. Where possible it also checks ownership: the shipment belongs to the test shipper, the departure to the test vehicle, the vehicle to the test carrier, and the account carries the run tag.
  - Before deleting anything, cleanup checks two things and raises `RuntimeError` if either fails:
    - No unrelated booking references a test departure.
    - Every tracked shipment that still exists belongs to a shipper recorded by this test. Tracked IDs from rolled-back inserts may no longer exist, and that is allowed.
  - Before committing, it counts the recorded rows that remain, inside the same transaction. If any are left, it raises, rolls back the deletes, and fails the test teardown. `cleaned` is set only after the commit succeeds.
  - Teardown runs after failed tests too. `pytest_sessionfinish` retries any cleanup that did not complete.
- **Verified after the runs.** No account carrying the run tag remains, and `shipment`, `booking`, `scan_event` and `hub` each contain 0 rows. AUTO_INCREMENT counters advance and are not reset. That is expected and does not affect anything.

## Transaction and isolation protocol used

- **Booking.** `CALL book_shipment(%s, %s)` runs on an autocommit connection that has been checked to have `@@in_transaction = 0`. The procedure owns its transaction. After every call, successful or failed, the test asserts `@@in_transaction = 0`.
- **Scans.** `ScanSession` owns one connection and sets `SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED`, verified with `@@SESSION.tx_isolation`. Each scan runs `START TRANSACTION`, then the documented prelock `SELECT shipment_id FROM shipment WHERE shipment_id = %s FOR UPDATE` (which must return one row), then a single-row `INSERT ... VALUES`, then `COMMIT`. Any error triggers a `ROLLBACK`.
  - `append()` follows the documented protocol fully: it computes `COALESCE(MAX(scan_sequence), 0) + 1` while holding the lock.
  - The negative tests insert explicit sequence numbers on purpose.
  - Isolation is set per connection. A test confirms that setting it on the scan connection does not change any other connection.
- **Constraint probes.** Each probe runs inside an explicit transaction that is always rolled back, so even an unexpected success leaves no data.

## Test cases and results

Error code 1644 is `SIGNAL SQLSTATE '45000'`. 4025 is a CHECK constraint failure, 1452 an FK parent-not-found error, 1062 a duplicate key and 1205 a lock wait timeout. Assertions check both the error code and the exact message text from `sql/01_schema.sql`, or the CHECK constraint name.

### Booking procedure (`TestBooking`): 10 tests, all PASS

| # | Test | Expected behavior | Result |
|---|---|---|---|
| B1 | `test_valid_booking_creates_one_row_and_commits` | 60 kg onto a 100 kg departure: one booking row, visible from another connection (so it is committed), load 60.00, `in_transaction = 0`, status and outcome still NULL | PASS |
| B2 | `test_fill_to_exact_capacity_then_reject_overflow` | 60 + 40 reaches exactly 100.00. A third 60 kg booking fails with "Departure weight capacity would be exceeded"; the existing 2 bookings and the 100.00 load are unchanged | PASS |
| B3 | `test_single_shipment_equal_to_capacity_is_accepted` | 100.00 kg onto an empty 100.00 kg departure succeeds | PASS |
| B4 | `test_capacity_exceeded_by_one_cent_is_rejected` | 100.01 kg onto an empty departure is rejected. 40.01 kg onto a departure already holding 60 kg is rejected. Loads unchanged | PASS |
| B5 | `test_duplicate_booking_same_and_other_departure_rejected` | Rebooking onto the same departure and onto another same-lane departure both fail with "Shipment is already booked"; exactly one booking remains | PASS |
| B6 | `test_reverse_lane_shipment_rejected` | A shipment on destination→origin cannot be booked onto an origin→destination departure (lane mismatch message) | PASS |
| B7 | `test_different_lane_shipment_rejected` | A shipment on origin→intermediate is rejected with the lane mismatch message | PASS |
| B8 | `test_missing_null_and_zero_ids_rejected` | A missing departure gives "Departure does not exist" and a missing shipment "Shipment does not exist" (IDs confirmed absent). 0 or NULL for either ID gives "Shipment ID and departure ID must be positive". No state change | PASS |
| B9 | `test_active_caller_transaction_rejected_and_left_untouched` | With an uncommitted shipment insert open, the CALL fails with the idle-connection message. The caller's transaction stays active (`in_transaction = 1`), and the row is visible to that session only. After ROLLBACK the row is gone | PASS |
| B10 | `test_lock_timeout_inside_procedure_rolls_back_then_retry_succeeds` | While another session holds the departure lock, a CALL with `innodb_lock_wait_timeout = 1` fails with 1205, and the EXIT handler leaves `in_transaction = 0` with no booking. After the lock is released, the retry succeeds | PASS |

Every rejected call also asserts that the shipment's bookings and the departure's count and summed weight are unchanged. Together these cover atomicity of failed bookings.

### Table constraints (`TestConstraints`): 14 tests, all PASS

| # | Test | Expected behavior | Result |
|---|---|---|---|
| K1 | `test_unique_shipment_blocks_direct_second_booking` | A direct `INSERT INTO booking` for an already-booked shipment onto another departure fails with 1062 (`uq_booking_shipment`) | PASS |
| K2 | `test_booking_requires_existing_shipment` | Booking a missing shipment fails with 1452 | PASS |
| K3 | `test_shipment_weight_must_be_positive[0.00, -1.00]` | 4025 `chk_shipment_weight` | PASS ×2 |
| K4 | `test_departure_capacity_must_be_positive[0.00, -5.00]` | 4025 `chk_departure_max_total_weight` | PASS ×2 |
| K5 | `test_lane_rejects_same_hub_and_duplicate_pair` | A same-hub lane fails with 4025 `chk_lane_different_hubs`; a duplicate ordered pair fails with 1062 | PASS |
| K6 | `test_shipment_requires_listed_ordered_lane` | intermediate→origin is not a lane (only its reverse exists), so the shipment fails with 1452 | PASS |
| K7 | `test_shipment_status_outcome_checks` (5 cases) | DELIVERED with NULL outcome, IN_TRANSIT with ON_TIME, and NULL status with LATE all fail `chk_shipment_status_outcome`. Lowercase `delivered` fails `chk_shipment_current_status`. `EARLY` fails `chk_shipment_delivery_outcome` | PASS ×5 |
| K8 | `test_role_and_region_domains` | Lowercase `shipper` fails `chk_account_role`; `North` fails `chk_hub_region` | PASS |

### Scan progression (`TestScanProgression`): 14 tests, all PASS

| # | Test | Expected behavior | Result |
|---|---|---|---|
| S1 | `test_valid_multi_hub_progression_updates_derived_state` | Sequences 1–10 in separate READ COMMITTED + prelock transactions: RECEIVED → IN_TRANSIT → IN_TRANSIT → ARRIVED_AT_HUB (intermediate hub) → ARRIVED_AT_HUB (equal timestamp) → IN_TRANSIT → ARRIVED_AT_HUB → OUT_FOR_DELIVERY → OUT_FOR_DELIVERY → DELIVERED. After each non-delivery scan the shipment shows that status with outcome NULL, and the final state is DELIVERED/ON_TIME. Sequences computed under the lock are exactly 1..10 | PASS |
| S2 | `test_first_scan_must_be_received` (×4) | A first scan of IN_TRANSIT, ARRIVED_AT_HUB, OUT_FOR_DELIVERY or DELIVERED fails with "The first scan must be RECEIVED"; state stays NULL/NULL with no history | PASS ×4 |
| S3 | `test_first_scan_sequence_must_be_one` | A first sequence of 2 fails the sequence-order rule; 0 fails "scan_sequence must be positive"; 1 then succeeds | PASS |
| S4 | `test_sequence_must_increment_by_exactly_one` | After scan 1, a gap (3) and duplicates (1) are rejected; 2 then succeeds | PASS |
| S5 | `test_timestamps_cannot_decrease` | One second earlier gives "Scan timestamps cannot move backward". An equal timestamp is accepted. A day earlier is rejected again | PASS |
| S6 | `test_equal_timestamp_across_shipments_is_allowed` | Two shipments may each have a scan with the same timestamp | PASS |
| S7 | `test_invalid_status_transitions_rejected` (×4 source states) | From RECEIVED: RECEIVED, ARRIVED_AT_HUB, OUT_FOR_DELIVERY and DELIVERED rejected. From IN_TRANSIT: RECEIVED, OUT_FOR_DELIVERY and DELIVERED rejected. From ARRIVED_AT_HUB: RECEIVED and DELIVERED rejected. From OUT_FOR_DELIVERY: RECEIVED, IN_TRANSIT and ARRIVED_AT_HUB rejected. All give "Invalid or regressing scan status transition" with history and state unchanged | PASS ×4 |
| S8 | `test_delivered_is_terminal` | After DELIVERED, all five statuses are rejected at the next sequence; outcome stays ON_TIME and history stays at 5 scans | PASS |

### Delivery outcome from the AFTER INSERT trigger (`TestDeliveryOutcome`): 9 tests, all PASS

| Promise date | DELIVERED scan time | Expected | Result |
|---|---|---|---|
| 2030-03-15 | 2030-03-14 10:00:00 | ON_TIME | PASS |
| 2030-03-15 | 2030-03-15 00:00:00 | ON_TIME | PASS |
| 2030-03-15 | 2030-03-15 23:59:59 | ON_TIME | PASS |
| 2030-03-15 | 2030-03-16 00:00:00 | LATE | PASS |
| 2030-01-31 | 2030-01-31 23:59:59 | ON_TIME | PASS |
| 2030-02-28 | 2030-03-01 00:00:00 | LATE (month boundary) | PASS |
| 2030-12-31 | 2031-01-01 00:00:00 | LATE (year boundary) | PASS |

There are two further tests:

- `test_undelivered_shipment_past_promise_keeps_null_outcome`: OUT_FOR_DELIVERY after the promise date still has outcome NULL. **PASS**
- `test_rolled_back_delivery_reverts_scan_and_derived_state`: an uncommitted DELIVERED insert shows DELIVERED/ON_TIME inside its own transaction but is invisible to other connections. After ROLLBACK, both the scan and the derived fields revert to OUT_FOR_DELIVERY/NULL. **PASS**

### Negative scan operations (`TestScanNegative` and the isolation test): 11 tests, all PASS

| # | Test | Expected behavior | Result |
|---|---|---|---|
| N1 | `test_repeatable_read_session_rejected` | A connection whose session is REPEATABLE READ, even with the prelock taken, fails with "Scan inserts require READ COMMITTED…". The scanner connection still reports READ-COMMITTED. No state change | PASS |
| N2 | `test_nonexistent_shipment_rejected` | The prelock finds 0 rows, and the INSERT fails with "Scan shipment does not exist" | PASS |
| N3 | `test_nonexistent_hub_rejected_by_fk` | Fails with 1452; derived state unchanged | PASS |
| N4 | `test_invalid_status_value_rejected` (`received`, `RECEIVED ` with a trailing space, `LOST`, empty string) | "Invalid scan status" | PASS ×4 |
| N5 | `test_null_timestamp_rejected` | Rejected. Observed error: 1644 "scan_timestamp is required", meaning the trigger fires before NOT NULL | PASS |
| N6 | `test_null_status_rejected` | Rejected. Observed error: 1644 "Invalid scan status" | PASS |
| N7 | `test_failed_scan_after_history_keeps_state` | IN_TRANSIT → DELIVERED is rejected; the shipment stays IN_TRANSIT/NULL | PASS |
| N8 | `test_scan_session_isolation_is_connection_specific` | Setting READ COMMITTED on one connection does not change another connection's session isolation | PASS |

For each rejected scan, the test asserts that the caller's transaction ended (`in_transaction = 0`) and that scan history, `current_status` and `delivery_outcome` are identical to their values before the attempt.

### Concurrency (`tests/test_concurrency.py`, marker `concurrency`): 14 tests, all PASS

**How the tests coordinate.** Each worker thread opens its own PyMySQL connection inside the thread; no connection is shared between threads.

1. A controller connection in the main thread takes the contended row lock with `SELECT … FOR UPDATE`.
2. Workers are released one at a time. The main thread polls `information_schema.PROCESSLIST` until that worker is running the exact locking statement inside the procedure or scan (for example `SELECT … FROM departure … FOR UPDATE`). This proves the worker is queued behind the lock. If the worker finishes before blocking, the test fails, because the lock was not actually contended.
3. Only after every worker is confirmed blocked does the controller commit.

All waits have limits: 6 s to observe blocking, 9 s to join a thread, `innodb_lock_wait_timeout = 8` in worker sessions. All are below the driver's 10 s read timeout. The tests use no sleeps for ordering. Each arrival order (A first, B first) is tested separately.

| # | Test | Expected behavior | Result |
|---|---|---|---|
| C1a | `test_c1_competing_bookings_cannot_overfill_departure[A_first, B_first]` | Two 60 kg CALLs on separate connections queue on a 100 kg departure. Exactly one succeeds and the other fails with the capacity message. Final count is 1 and load is 60.00, which is at most 100.00. Both workers end with `in_transaction = 0` | PASS ×2 |
| C1b | `test_c1_competing_bookings_that_fit_both_succeed[A_first, B_first]` | 60 kg and 40 kg both succeed; load is exactly 100.00 | PASS ×2 |
| C2a | `test_c2_one_shipment_two_departures_books_once[A_first, B_first]` | Controller locks the shipment. CALL(s, D1) and CALL(s, D2) each hold their own departure lock and queue on the shipment. Exactly one booking exists and the other call fails with "Shipment is already booked" | PASS ×2 |
| C2b | `test_c2_duplicate_concurrent_calls_same_departure_book_once` | Two identical concurrent CALLs: one books, one gets "already booked"; a single row remains | PASS |
| C3a | `test_c3_second_scanner_waits_then_appends_after_commit` | A inserts scan 2 uncommitted. B's history read before locking sees only [1]; B's prelock blocks. After A commits, B recomputes sequence 3 and inserts ARRIVED_AT_HUB. Final history: 1, 2, 3 | PASS |
| C3b | `test_c3_stale_sequence_after_wait_is_rejected` | B submits a stale sequence 2 after waiting and is rejected with the sequence-order message; history stays 1, 2 | PASS |
| C3c | `test_c3_second_scanner_sees_rollback_and_appends_next` | A rolls back. B then appends sequence 2 (B's own row) | PASS |
| C4 | `test_c4_concurrent_scan_cannot_undo_delivery` (×4) | A inserts DELIVERED uncommitted (on time or late). B blocks, then attempts IN_TRANSIT or a second DELIVERED, which is rejected as an invalid transition, or an earlier timestamp, which is rejected as moving backward. The outcome stays as A committed it | PASS ×4 |

## Actual results summary

**Final verification run (2026-11-11, including both cleanup safety changes):** 72 passed, 0 failed, 0 errors. That breaks down as 58 booking, constraint and scan tests plus 14 concurrency tests. The project member ran this verification and the database check that followed.

After that run, an independent check of the `sshett24` database found 0 remaining rows in `shipment`, `booking`, `scan_event` and `hub`, and 0 tagged functional-test accounts (`password LIKE 'PYTEST-CSC540-%'`).

The earlier full run, before the cleanup changes (run 4 below), produced this output:

```
python -m pytest -v
======================== 72 passed in 86.08s (0:01:26) =========================
```

### Run history

| Run | Code version | Result |
|---|---|---|
| 1 | Core tests, first version | 19 failed and 39 passed. A test-helper `TypeError` (see Defects). Cleanup still removed every row. |
| 2 | After the helper fix | 58 of 58 passed (`test_database_rules.py`) |
| 3 | After the concurrency tests were added | 14 of 14 passed (`test_concurrency.py`) |
| 4 | Full suite | **72 passed**. Afterwards there were 0 tagged accounts and 0 rows in `shipment`, `booking`, `scan_event` and `hub`. |
| 5 | Full suite after the two cleanup safety changes | **Not executed against the database: 72 errors during setup.** Every test failed with `OperationalError 2003` while the session schema guard was connecting, because `classdb2.csc.ncsu.edu` did not resolve (NXDOMAIN; the public domain `ncsu.edu` did resolve). This is consistent with the NCSU VPN or campus network being disconnected. No connection was made, so nothing was read or written. The changed module compiles and all 72 tests collect. This was a connectivity problem, not a test failure. |
| 6 | Full suite with both cleanup safety changes (final) | **72 passed, 0 failed, 0 errors**: 58 tests in `test_database_rules.py` and 14 in `test_concurrency.py`. A follow-up database check found 0 rows in `shipment`, `booking`, `scan_event` and `hub`, and 0 tagged test accounts. |

| Group | Tests | Pass | Fail | Blocked |
|---|---|---|---|---|
| Booking procedure | 10 | 10 | 0 | 0 |
| Table constraints | 14 | 14 | 0 | 0 |
| Scan progression | 14 | 14 | 0 | 0 |
| Delivery outcome | 9 | 9 | 0 | 0 |
| Negative scans and isolation | 11 | 11 | 0 | 0 |
| Concurrency | 14 | 14 | 0 | 0 |
| **Total** | **72** | **72** | **0** | **0** |

## Defects found

- **Database objects: none.** Every rule documented in `sql/01_schema.sql` and `sql/schema_design_notes.md` behaved as specified, including the edge cases (exact capacity, one-cent overflow, end of day 23:59:59, month and year boundaries, trailing-space status, and isolation checked per session).
- **Test code (fixed): 1.** In the first execution of `test_database_rules.py`, 19 scan-negative tests failed with `TypeError` because `expect_db_error` did not pass keyword arguments through to the function it wraps. The fix forwards `**kwargs`, which changes no assertion. The rerun gave 58 of 58 passing. The first run's teardown still cleaned up every row, which confirmed that cleanup runs after failures.

## Environment limitations and observations

- **`INNODB_TRX` is unavailable** (error 1227, no PROCESS privilege). Blocking is proven instead with `information_schema.PROCESSLIST`, which shows a user's own sessions together with the statement they are executing. No test was blocked or skipped because of this.
- **The session default isolation is REPEATABLE-READ.** A scan connection that does not run `SET SESSION … READ COMMITTED` is correctly rejected by the trigger (N1). The future CLI must set it on every scan connection.
- **An owner can bypass the rules with direct DML**, as documented in the design notes. A direct `INSERT INTO booking` still hits UNIQUE and FK checks (K1, K2), but the database does not enforce lane or capacity on direct inserts. This is the documented enforcement boundary, not a defect, and the suite does not exercise these bypass probes.

## Not covered (out of scope or no implementation yet)

These cases from `tests/database_rules_test_plan.md` depend on the Python application layer, which does not exist yet. They are **not tested** and must not be reported as passed:

- **Application authorization:** a shipper booking only their own shipment, a carrier posting scans only for its own booked departure, and viewers having no write access.
- **Update and edit protocols:** capacity, weight, lane and promise edits.
- **Concurrency cases C5–C8:** capacity edits versus booking, weight edits versus booking, shipment edits versus booking, and departure or vehicle edits.
- **Plan structural case 7:** vehicle and account subtype disjointness.

Reinstallation and structural inventory checks belong to `tests/schema_validation.sql` and were not repeated here.
