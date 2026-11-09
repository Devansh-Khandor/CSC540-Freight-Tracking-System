# Database rules test plan — Task 3A

**Execution status: NOT RUN on MariaDB.** This is a plan with executable examples, not a record of passing tests. Static source checks are reported separately in the design notes. Do not execute this document wholesale: negative tests intentionally raise errors, and several cases need fresh fixtures or multiple connections.

## Safety, setup, and evidence

Review `sql/01_schema.sql` and `sql/schema_design_notes.md` first. Apply only after approval using the exact commands in the notes. Run `tests/schema_validation.sql` for non-destructive structural inspection; inspect every PASS/FAIL result and object definition. Record actual VERSION(), database name, SQL mode, isolation, error codes/messages, and final query results; do not record passwords. Keep FK and CHECK enforcement enabled and use strict SQL mode.

Mutation tests below require an explicitly approved disposable existing schema on MariaDB **10.5.22**, not ordinary departmental project data. No permission to CREATE DATABASE is assumed. The booking procedure COMMITs its own transaction, so an outer ROLLBACK cannot clean up successful calls. Do not wrap calls in a transaction for cleanup. Have the test-schema owner reset disposable data between independent scenarios; no destructive cleanup commands are supplied here.

Each failure must leave booking count/weight and scan history/derived shipment state unchanged. After any failed scan or application update, explicitly ROLLBACK the caller transaction before the next scenario. After a procedure error, verify `@@in_transaction = 0`, except when testing its active-caller guard (which must leave the caller transaction active and untouched).

The official PDF requires application-level authorization and Create/Update functions. Cases labeled **application protocol** cannot be marked passed until those Python handlers are implemented. Testing the SQL schema alone cannot demonstrate application ownership enforcement or safe update handling.

## Disposable fixture recipe

Use auto-generated IDs; these are deliberately small test records, not the final sample-data deliverable. Run once on a clean approved test schema, then keep the displayed identifiers for additional sessions. All passwords here are dummy test data and must never be used as application credentials.

```sql
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ZERO_DATE,NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION';
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
INSERT INTO account (password, role) VALUES ('TEST-ONLY-NOT-A-LOGIN', 'SHIPPER');
SET @shipper = LAST_INSERT_ID();
INSERT INTO shipper VALUES (@shipper);
INSERT INTO account (password, role) VALUES ('TEST-ONLY-NOT-A-LOGIN', 'CARRIER');
SET @carrier = LAST_INSERT_ID();
INSERT INTO carrier VALUES (@carrier);
INSERT INTO hub (region) VALUES ('Northeast'); SET @origin = LAST_INSERT_ID();
INSERT INTO hub (region) VALUES ('West'); SET @destination = LAST_INSERT_ID();
INSERT INTO hub (region) VALUES ('Midwest'); SET @intermediate = LAST_INSERT_ID();
INSERT INTO lane VALUES (@origin, @destination), (@destination, @origin);
INSERT INTO vehicle (carrier_account_id, home_hub_id) VALUES (@carrier, @origin);
SET @vehicle = LAST_INSERT_ID();
INSERT INTO box_truck VALUES (@vehicle, 20.00, 5000.00);
INSERT INTO departure (vehicle_id, origin_hub_id, destination_hub_id,
                       departure_datetime, max_total_weight_kg)
VALUES (@vehicle, @origin, @destination, '2026-11-10 08:00:00', 100.00);
SET @departure = LAST_INSERT_ID();
INSERT INTO departure (vehicle_id, origin_hub_id, destination_hub_id,
                       departure_datetime, max_total_weight_kg)
VALUES (@vehicle, @origin, @destination, '2026-11-10 09:00:00', 100.00);
SET @other_departure = LAST_INSERT_ID();
INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id,
                      weight_kg, promised_delivery_date)
VALUES (@shipper, @origin, @destination, 60.00, '2026-11-12');
SET @s60a = LAST_INSERT_ID();
INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id,
                      weight_kg, promised_delivery_date)
VALUES (@shipper, @origin, @destination, 60.00, '2026-11-12');
SET @s60b = LAST_INSERT_ID();
INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id,
                      weight_kg, promised_delivery_date)
VALUES (@shipper, @origin, @destination, 40.00, '2026-11-12');
SET @s40 = LAST_INSERT_ID();
INSERT INTO shipment (shipper_account_id, origin_hub_id, destination_hub_id,
                      weight_kg, promised_delivery_date)
VALUES (@shipper, @destination, @origin, 10.00, '2026-11-12');
SET @reverse_shipment = LAST_INSERT_ID();
COMMIT;
SELECT @shipper, @carrier, @origin, @destination, @intermediate,
       @vehicle, @departure, @other_departure, @s60a, @s60b, @s40, @reverse_shipment;
```

For different-shipper, different-carrier, subtype, and outcome-boundary scenarios create analogous fresh fixtures. Use a confirmed absent positive ID for missing-row tests, not an ID assumed to be absent. In other sessions set the required `@variables` to the recorded fixture IDs; session variables do not transfer between connections.

## Structural and table constraint cases

1. **Object inventory:** exactly 14 InnoDB tables, one `book_shipment` procedure, and only the BEFORE/AFTER INSERT scan triggers. All original columns/types and PK/FK relationships remain; only the two lane-to-hub ON UPDATE actions change from CASCADE to RESTRICT. A second installation against existing names must fail rather than overwrite. Test reinstallation only on a disposable instance; DDL is not transactional.
2. **Lane direction:** both origin->destination and destination->origin fixtures succeed. A duplicate ordered pair and a same-hub lane fail. A shipment referencing an unlisted ordered lane fails its FK even when the reverse lane exists. In an approved disposable fixture, attempt to change a hub ID referenced by a lane: expect an FK restriction error and unchanged lane endpoints. An unreferenced hub ID is not made immutable by this FK; the application must prohibit all hub-ID edits. These are planned tests, not executed results.
3. **Domains:** accept exactly the five named regions, three roles, five statuses, and two outcomes. Reject unknown/lowercase/space-suffixed values, empty strings, and required NULLs. Test decimal zero/negative shipment weight and departure capacity, and original subtype positivity checks. Expect CHECK/NOT NULL errors, not an assumption that unsigned types alone validate positivity.
4. **Nullable derived fields:** initial shipment insertion without status/outcome succeeds with both NULL. Non-delivered status with NULL outcome is structurally valid. DELIVERED with NULL outcome, NULL status with non-NULL outcome, and non-delivered status with ON_TIME/LATE must fail the pairing CHECK. An owner can forge a logically consistent DELIVERED+ON_TIME pair directly; this illustrates the documented application policy boundary, not a successful scan test.
5. **Foreign keys:** reject orphan account/vehicle subtype rows, nonexistent shipper/carrier/hub references, and nonexistent shipment/departure bookings. Direct scan insertion needs the scan protocol; a nonexistent shipment should SIGNAL `45000`, while a nonexistent hub should fail its FK with no derived-state change.
6. **Single booking:** retain composite PK `(shipment_id, departure_id)` plus unique shipment. As owner in a disposable transaction, attempt a second booking for the same shipment and a different valid departure: it must fail UNIQUE even when bypassing CALL.
7. **Specialization boundary:** confirm an owner can insert an account into a mismatched or second subtype, or a vehicle into two different subtypes, with only these DDL constraints. ROLLBACK. The future creation handler must reject those operations and atomically create one matching account subtype. A base-only vehicle is permitted by the finalized ER. Do not report FKs as enforcing totality/disjointness.

## Booking procedure cases

Run independently with fresh booking state unless explicitly sequential.

1. `CALL book_shipment(@s60a, @departure)` succeeds; booked total 60.00 and one row. Then `CALL book_shipment(@s40, @departure)` succeeds at exactly 100.00. A subsequent 60 kg request fails without changing either existing booking.
2. A 100.01 kg shipment into an empty 100.00 kg departure fails; an exact 100.00 kg shipment succeeds. A 0.01 kg excess also fails. No floating-point rounding is involved.
3. NULL, zero, and absent shipment/departure IDs return clear failures. Verify the transaction has ended and no locks remain. For negative values outside an UNSIGNED parameter, an engine range error is also acceptable under strict mode.
4. `CALL book_shipment(@reverse_shipment, @departure)` fails the ordered-lane check even though the undirected endpoints are the same.
5. Repeat a successful call and then try booking that same shipment onto `@other_departure`; both fail as already booked, leaving exactly one booking.
6. **Caller ownership:** start a transaction, insert an otherwise valid uncommitted test row, then CALL. Expect the idle-connection error; confirm the inserted row still exists in that session and `@@in_transaction = 1`. ROLLBACK and confirm the row disappears. The procedure must neither commit nor roll back caller work in this case.
7. **Rollback handler:** hold the target departure lock in session A. In idle session B set `innodb_lock_wait_timeout = 1` and CALL. Expect a lock timeout; confirm no booking and no active B transaction. Release A, then retry the whole call successfully. Restore the session timeout afterward.
8. **Application protocol:** a logged-in shipper cannot book another shipper's shipment; a viewer cannot call any write operation through the CLI. Direct CALL by the shared schema owner is not evidence of application authorization.

Inspect capacity without mutation after each test:

```sql
SELECT d.departure_id, d.max_total_weight_kg,
       COALESCE(SUM(s.weight_kg), 0.00) AS booked_weight,
       COUNT(b.shipment_id) AS booking_count
FROM departure AS d
LEFT JOIN booking AS b ON b.departure_id = d.departure_id
LEFT JOIN shipment AS s ON s.shipment_id = b.shipment_id
WHERE d.departure_id IN (@departure, @other_departure)
GROUP BY d.departure_id, d.max_total_weight_kg;
SELECT @@in_transaction;
```

## Scan trigger cases

Use a newly booked shipment with no history. Every case follows the prelock protocol. The following complete successful multi-hub journey is rolled back so it can be inspected without leaving scan data; the existing booking is **not** rolled back.

```sql
-- If not already booked, call while idle before this transaction:
-- CALL book_shipment(@s60a, @departure);
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = @s60a FOR UPDATE;
INSERT INTO scan_event VALUES (@s60a, 1, '2026-11-10 08:00:00', 'RECEIVED', @origin);
INSERT INTO scan_event VALUES (@s60a, 2, '2026-11-10 08:30:00', 'IN_TRANSIT', @origin);
INSERT INTO scan_event VALUES (@s60a, 3, '2026-11-10 09:00:00', 'ARRIVED_AT_HUB', @intermediate);
INSERT INTO scan_event VALUES (@s60a, 4, '2026-11-10 10:00:00', 'IN_TRANSIT', @intermediate);
INSERT INTO scan_event VALUES (@s60a, 5, '2026-11-10 11:00:00', 'ARRIVED_AT_HUB', @destination);
INSERT INTO scan_event VALUES (@s60a, 6, '2026-11-10 12:00:00', 'OUT_FOR_DELIVERY', @destination);
INSERT INTO scan_event VALUES (@s60a, 7, '2026-11-12 23:59:59', 'DELIVERED', @destination);
SELECT scan_sequence, scan_timestamp, status, hub_id FROM scan_event
 WHERE shipment_id = @s60a ORDER BY scan_sequence;
SELECT current_status, delivery_outcome FROM shipment WHERE shipment_id = @s60a;
-- Expect DELIVERED / ON_TIME and seven scans.
ROLLBACK;
SELECT current_status, delivery_outcome FROM shipment WHERE shipment_id = @s60a;
-- Expect NULL / NULL and no scans for this originally unscanned fixture.
```

Positive and negative variations, each in a separate transaction:

1. First scan sequence 1/RECEIVED succeeds. Sequence 0, NULL, first sequence 2, duplicates, and gaps fail; no change to history/state. An out-of-range integer may fail type conversion before the trigger.
2. First status IN_TRANSIT or DELIVERED fails. From RECEIVED, ARRIVED_AT_HUB/OUT_FOR_DELIVERY/DELIVERED fail as skipped stages. FROM IN_TRANSIT -> RECEIVED and OUT_FOR_DELIVERY -> IN_TRANSIT/ARRIVED_AT_HUB fail.
3. Accept repeated IN_TRANSIT, ARRIVED_AT_HUB, and OUT_FOR_DELIVERY scans, each with the next sequence and nondecreasing timestamp. Accept intermediate-hub ARRIVED_AT_HUB -> IN_TRANSIT cycles. Reject repeated RECEIVED or any scan after DELIVERED.
4. At every supported status transition, a timestamp earlier than the last scan fails; an equal timestamp succeeds. Duplicate timestamp across different shipments is allowed. NULL timestamp and invalid status fail. Verify string case and trailing spaces.
5. Delivered before the promise date and at 23:59:59 on it -> ON_TIME. Delivered at 00:00:00 the next day -> LATE. A shipment with no delivery scan stays outcome NULL even after its promised date. Test month/year boundaries. Use fixed times, not CURRENT_TIMESTAMP, so results are repeatable.
6. After every successful non-delivery insert, verify current_status equals that scan and outcome remains NULL. After a failing insert, verify both fields remain as before. Rollback a successful delivery insert and confirm both the scan and derived status/outcome revert.
7. Change the scan session default to REPEATABLE READ before starting a transaction: the trigger rejects insertion. Restore READ COMMITTED afterward. A one-transaction override while the session default says READ COMMITTED is an unsupported bypass; the application must never use it, and the session-variable guard is not a proof against it.
8. **Application protocol:** require a booked departure owned by the current carrier, reject a different carrier and a viewer, and reject an unbooked shipment. Posting does not update shipment fields in Python. Direct owner INSERT bypasses these authorization checks, although the triggers still validate their database rules.

## Update and bypass cases

These exercise the documented future **application protocol**. They are not enforced by extra triggers; no additional procedure/trigger should appear after implementation.

1. With 60.00 kg booked, capacity 100 -> 80 and 80 -> 60 succeed; 60 -> 59.99 and zero fail without changes. An increase to 120 succeeds. Each change holds the departure lock and recomputes SUM before UPDATE.
2. With 60+40 booked and no scans, edit the 60 kg shipment to 61: reject. Reduce to 50, then increase to 60: accept. Test a decimal fraction at the boundary. The transaction must lock departure then shipment and validate `sum - old + new`.
3. Update lane/weight/promise on an unbooked, unscanned owned shipment: valid edits succeed, invalid lanes/weights fail. After booking, reject lane change even if the reverse lane exists; allow capacity-safe weight and promise changes before scans. After first scan, reject all three fields to preserve history/report meaning.
4. Change a departure's lane, vehicle, or datetime before bookings: allow valid owned values. After any booking (with or without scans), reject; capacity is still editable using case 1. Reject assigning another carrier's vehicle.
5. Edit an owned vehicle's home hub and existing subtype attributes: allow valid values. Reject changing owner, PK, or subtype membership. Verify another carrier cannot edit it.
6. Reject scan UPDATE/DELETE and direct writes to derived fields through the application. Reject direct booking INSERT/UPDATE/DELETE, cancellation/rebooking, parent deletions, and PK/ownership/role changes through the CLI. Keep scan history append-only.
7. **Owner bypass audit, disposable transaction only:** insert a wrong-lane or overweight booking directly, reduce capacity below its load, or increase a booked weight without the protocol. These can succeed as table definitions alone do not enforce the cross-row rules. Similarly, owner scan UPDATE/DELETE can invalidate history. ROLLBACK every probe. Record these as known enforcement boundaries, not unexpectedly passing database safeguards. A restricted application path must prevent them; no DB privilege setup is required by the final specification.

## Concurrency tests

Use separate real database connections; a single connection with interleaved statements does not demonstrate concurrency. For every test, record blocking behavior, each connection's result/error, and final invariant queries. Repeat with both arrival orders. Do not interpret a deadlock/timeout rollback as permission to accept an invalid state.

### C1: compete for the final capacity

Fresh departure capacity 100; two unbooked 60 kg shipments. To guarantee overlap, use a third controller connection to begin a transaction and lock the departure with SELECT ... FOR UPDATE. While it holds the lock, start `CALL book_shipment(s60a, departure)` in A and `CALL book_shipment(s60b, departure)` in B. Both must wait. Commit the controller. Exactly one CALL should succeed; the other must fail capacity validation. Final SUM=60, COUNT=1, no active CALL transactions. With 60 and 40 kg instead, both should eventually succeed and SUM=100. Do not add sleeps or test-only code to the production procedure.

### C2: one shipment, different departures

Two empty same-lane departures and one 60 kg shipment. Invoke a CALL concurrently for each departure. Exactly one booking survives; the other call returns already-booked/unique failure (or rolls back a lock error). If retrying a lock failure, it must return already-booked. There must never be two rows for the shipment. Repeat duplicate calls against the same departure.

### C3: scan append serialization and stale sequence

Start with committed scan 1/RECEIVED. A sets READ COMMITTED, START TRANSACTION, prelocks shipment, inserts scan 2/IN_TRANSIT, and does not commit yet. B sets READ COMMITTED, START TRANSACTION, optionally reads history (seeing scan 1), then tries the separate shipment FOR UPDATE; it must block. Commit A. B must now read latest sequence 2 and insert 3/ARRIVED_AT_HUB. Inspect correct final state after commit.

Repeat with B submitting a stale sequence 2 after acquiring its lock: trigger must reject. Repeat with A rolling back: B should see sequence 1 and validly append sequence 2. This covers visibility following both commit and rollback.

### C4: delivery cannot be undone by concurrent scan

Start after OUT_FOR_DELIVERY. A prelocks and inserts DELIVERED without committing. B attempts its prelock and blocks. Commit A. B recomputes sequence and tries IN_TRANSIT (or a second DELIVERED); trigger rejects and leaves the delivery outcome unchanged. Repeat with B using an earlier timestamp. Test both on-time and late deliveries.

### C5: capacity update versus booking (application protocol)

Initially 60 kg booked, capacity 100, candidate 40. Hold the departure lock for a safe capacity reduction to 80 in A; start CALL in B. B waits, then rejects after A commits. Reverse the order so B books first; A must see 100 booked and reject its reduction to 80. Final capacity must always be >= SUM.

### C6: booked weight update versus booking (application protocol)

Initially 60 kg booked/capacity 100; proposed existing-shipment increase to 70 and new shipment 40. Whichever gets the departure lock first may succeed; the other must reject. With old-weight reduction 60 -> 50 and new weight 50, verify B sees the committed reduction before accepting. No sum may exceed capacity.

### C7: initial booking versus shipment edit (application protocol)

Have the editor initially observe no booking. Let CALL book the shipment before the editor gets its shipment lock. The editor must re-read booking, detect the change, ROLLBACK, and retry with departure-first locks. It must not continue with an unbooked-weight/lane validation or acquire departure after shipment. In the opposite order CALL waits for the editor's shipment lock and validates the new lane/weight when released. Test both valid and invalid resulting lane/capacity combinations.

### C8: departure changes and scan/edit contention (application protocol)

Race a departure lane/vehicle change with CALL: the departure lock orders them; either the edit occurs first and CALL validates the new route, or CALL occurs first and the editor rejects because a booking exists. Race shipment weight/promise edits with the first scan: the shared shipment lock orders them; edit first affects the later scan, scan first causes edit rejection. Race two attempts to classify one base-only vehicle: parent locking plus checking all subtype tables permits at most one subtype.

## Completion record

Keep actual results next to each case after execution: environment/version, PASS/FAIL/BLOCKED, evidence, and any discrepancy. Structural inspection, stored-program compilation, functional behavior, concurrency, and application policies are separate validation categories. Do not mark the whole suite passed merely because the installation or SELECT VERSION() succeeds. The six analytical query implementations and final sample-data file belong to later tasks.
