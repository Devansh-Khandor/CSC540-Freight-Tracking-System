# Task 3A schema design and execution notes

## Authority and scope

Read all seven pages of [the official final specification](../docs/CSC540-Logistics-Project-Final-Version.docx.pdf), then reconciled [the preliminary schema](preliminary_schema.sql) and [the finalized ER diagram](../diagrams/Final_Revised_ER_Diagram.drawio). The workspace PDF has the extra `.docx` in its filename. The final specification takes precedence. No ER inconsistency requiring a change was found; neither reference was edited.

The implementation keeps exactly the original 14 tables, every original column/type, primary key, and foreign-key relationship. The only referential-action changes are the two lane-to-hub ON UPDATE actions, now RESTRICT for MariaDB 10.5 compatibility. `booking` keeps its composite PK and gains `UNIQUE(shipment_id)`, enforcing the ER's explicit single-departure assumption. Intermediate scan hubs do not represent additional departure bookings. There is no new region, role, status, or counter table. No sample-data or analytical-query submission file is included yet.

The official specification requires Create/Update functions (pp. 3–4) and explicitly assigns access control to the application (p. 3). Therefore updates are not universally forbidden, and database user/privilege administration is not a prerequisite. The protocols below define the safe updates the future Python CLI must support. **This task documents those Python responsibilities; it does not implement them.**

## Table rules and specialization

- All tables explicitly use InnoDB and `utf8mb4_bin`. Original identifier widths, decimal precision, subtype attributes, and nullable derived shipment fields are retained.
- Ordered lane PK `(origin_hub_id, destination_hub_id)` plus the distinct-hubs CHECK preserves direction. All referencing lane FKs use the same order.
- CHECKs preserve the five regions and three account roles, positive weights/capacities and original positive subtype attributes. Binary comparisons enforce exact status/role/region spelling.
- Shipment and scan status domains are `RECEIVED`, `IN_TRANSIT`, `ARRIVED_AT_HUB`, `OUT_FOR_DELIVERY`, `DELIVERED`. Outcomes are `ON_TIME`, `LATE`, or NULL.
- A new shipment has NULL status and outcome. An undelivered shipment has NULL outcome, even when already past its promise date. A delivered status requires an outcome. A NULL-aware CHECK enforces this pairing but cannot prove a corresponding scan exists; only the scan writer may maintain these fields.
- `scan_event` retains `(shipment_id, scan_sequence)` as PK. Scans cascade on shipment deletion in the original schema, but operational deletion is prohibited by policy to preserve history.
- Account subtype FKs guarantee a parent and subtype PKs prevent duplicates *within* each subtype. They do **not** ensure that the subtype matches `account.role`, that all accounts have a subtype, or that one account cannot appear in multiple subtype tables. The scalar role CHECK ensures one allowed role value, not total/disjoint membership.
- Vehicle subtype FKs similarly do not enforce cross-table disjointness. The finalized ER specifies disjoint vehicle types but does **not** specify completeness. Do not falsely require every vehicle to have a subtype at the database level. The normal CLI can create a chosen supported subtype; a base-only vehicle is permitted by the ER.

Preserving all original attributes and the two-trigger limit leaves these specialization assertions to transactional application creation. For accounts, insert the parent and exactly its matching subtype in one transaction, then commit; role and subtype membership become immutable. For vehicles, insert parent and selected subtype atomically, and keep subtype membership immutable. If an existing base-only vehicle is classified, lock its parent first and check all three subtype tables before inserting. All such writers must take that parent lock. A privileged ad hoc SQL writer can still violate these assertions. Composite discriminator FKs could enforce part of account disjointness but would require additional subtype discriminator columns and would still not enforce totality; they are deliberately not added to this finalized design.

## MariaDB 10.5 CHECK / foreign-key action audit

`fk_lane_origin` and `fk_lane_destination` now use **ON UPDATE RESTRICT**, retaining ON DELETE RESTRICT and `CHECK (origin_hub_id <> destination_hub_id)` unchanged. This addresses the reported error 1901: the two checked child columns could previously be assigned by ON UPDATE CASCADE. MariaDB's [MDEV-25437](https://jira.mariadb.org/browse/MDEV-25437) documents this CHECK/cascading-update restriction in 10.5.

Hub identifiers are immutable application identities, not editable hub attributes. RESTRICT blocks a hub-ID update while any lane references that hub. It does not make every hub ID unconditionally immutable: an unreferenced hub ID can still be changed by privileged SQL. `vehicle.home_hub_id` and `scan_event.hub_id` retain their original update cascades, so if no lane references a hub, those references alone do not enforce immutability. The application must prohibit hub-ID edits in all cases. No blanket rewrite of other FKs or ER relationships was made.

The static audit covered all 18 FKs and 15 CHECK constraints, including column-changing ON UPDATE CASCADE/SET NULL and ON DELETE SET NULL actions:

- **Lane:** the only overlap between CHECK operands and child FK columns is its two hub IDs, now protected by RESTRICT. Both columns remain unsigned INT, in the original ordered composite PK.
- **Shipment:** CHECKs use weight_kg, current_status, and delivery_outcome; its cascading child FK columns are shipper_account_id and the two lane IDs. They do not overlap.
- **Departure:** its CHECK uses max_total_weight_kg, not vehicle_id or the two lane IDs. `fk_shipment_lane` and `fk_departure_lane` still reference the same ordered lane PK with ON UPDATE CASCADE / ON DELETE RESTRICT. The lane CHECK is on their referenced parent, not on their cascading child columns; this does not reproduce the reported child-column conflict. Updating lane identities remains unsupported application behavior.
- **Vehicle subtypes:** CHECKs use cargo_volume/gross_weight_rating, payload_limit, or axle_count/track_gauge; the cascading FK uses vehicle_id. There is no overlap.
- **Scan events:** CHECKs use scan_sequence and status; its FKs use shipment_id and hub_id. Its composite PK containing scan_sequence does not make scan_sequence a cascading FK column.
- **Account/hub:** CHECKs use role/region, not their IDs, and these tables have no child FKs. Shipper, carrier, viewer, vehicle, and booking have no CHECK constraints.
- **Delete actions:** no SET NULL actions exist. Retained ON DELETE CASCADE actions remove child rows; they do not assign values to checked columns. All other delete actions remain RESTRICT.

No additional instance of this incompatibility was found in the source. This is a column-level audit, not proof that the complete script compiles on MariaDB 10.5.22. The verification SQL now compares each FK with an explicit expected update action: RESTRICT for the two lane FKs, CASCADE for the other 16; all expected delete actions are unchanged. Remaining operational risks are the existing READ COMMITTED/session-prelock requirement, stored-program privileges and binary-logging configuration, and non-atomic DDL during installation. Preserve enabled FK/CHECK enforcement and rerun server-side validation only after manual cleanup and review.

## Booking procedure

`CALL book_shipment(shipment_id, departure_id)` owns its transaction. Use a fresh/idle connection. It rejects an active caller transaction **before** entering its rollback handler; it must not implicitly commit or roll back unrelated work.

1. Set the next transaction to READ COMMITTED and start it.
2. Lock the target departure with `SELECT ... FOR UPDATE`, then lock the candidate shipment. Missing rows and invalid IDs produce explicit SQLSTATE `45000` errors.
3. Compare ordered lanes and reject an existing booking.
4. Calculate `COALESCE(SUM(shipment.weight_kg), 0)` through the target departure's bookings inside that transaction. A wide decimal local variable avoids narrowing the aggregate.
5. Reject if the sum plus candidate weight is greater than capacity; equality is accepted. Otherwise insert and commit.

Same-departure calls wait on the same departure row. The second call's READ COMMITTED aggregate includes the first committed booking. Same-shipment calls targeting different departures serialize on the shipment; the second duplicate check sees the first booking, and the unique key is a final safeguard. No cached counter substitutes for SUM. A scoped `SQLEXCEPTION` handler rolls back and `RESIGNAL`s the original error, including lock/deadlock errors. Callers retry the **entire** operation after a deadlock/lock timeout, with bounded retries, and report business validation errors without retrying blindly. If a connection drops at commit, check booking state before retrying.

`SQL SECURITY DEFINER` uses the installing account without embedding a named definer. It is not application authorization: with a shared departmental DB login, the procedure cannot determine which application shipper is logged in. Python must authenticate and check shipment ownership before the call. Ownership is immutable under the supported policy, avoiding an ownership-check race. The procedure does not require a newly provisioned DB login or GRANT statements.

The existing `get_connection()` uses `autocommit=False`: a preceding table SELECT can already start a transaction. Complete the read-only authorization transaction before CALL, or use a separate idle connection for CALL. Do not commit unrelated pending writes merely to bypass the active-transaction guard.

## Scan chronology and delivery state

The BEFORE INSERT trigger requires sequence 1 for the first scan and exactly last sequence + 1 thereafter. Equal timestamps are allowed; earlier timestamps are rejected. The next status must follow these explicit rules:

- No history -> RECEIVED only.
- RECEIVED -> IN_TRANSIT.
- IN_TRANSIT -> IN_TRANSIT, ARRIVED_AT_HUB, or OUT_FOR_DELIVERY.
- ARRIVED_AT_HUB -> ARRIVED_AT_HUB, IN_TRANSIT, or OUT_FOR_DELIVERY.
- OUT_FOR_DELIVERY -> OUT_FOR_DELIVERY or DELIVERED.
- DELIVERED -> no further scans, including a repeated DELIVERED.

The stages are receipt, line-haul, last-mile, completed. IN_TRANSIT and ARRIVED_AT_HUB are both line-haul states: alternating them represents legitimate intermediate hub handling, not regression to receipt. ARRIVED_AT_HUB is optional: both four-stage and five-stage histories are valid. Skipping directly from line-haul to DELIVERED remains rejected. This is a documented interpretation of the specification's example statuses; the PDF does not supply a full transition matrix. No extra requirement that every scan hub equal an endpoint is imposed.

The AFTER INSERT trigger updates both derived fields in one statement. A DELIVERED scan uses `DATE(scan_timestamp) <= promised_delivery_date` for ON_TIME; otherwise LATE. A non-delivery scan sets outcome NULL. No current clock or derived SLA replaces the explicitly stored promise. DATETIME has no time-zone conversion; the proposed application convention is America/New_York wall-clock dates/times for both inputs. Normalize inputs consistently, including DST ambiguity, before storing them. This convention is an application assumption, not a time zone specified by the PDF.

### Required scan transaction protocol

For each scan use a dedicated connection with no active transaction. Set **SESSION** isolation to READ COMMITTED before starting a transaction. Do not use a different one-transaction override. Lock the shipment in a **separate statement before INSERT**, validate carrier authorization through booking -> departure -> vehicle, determine the next sequence while locked, and insert one row with `INSERT ... VALUES`. Commit only after successful insertion. Any error requires caller ROLLBACK.

```sql
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = @shipment_id FOR UPDATE;
-- Python: require a row and verify the logged-in carrier owns the booked vehicle.
SELECT COALESCE(MAX(scan_sequence), 0) + 1 INTO @next_sequence
  FROM scan_event WHERE shipment_id = @shipment_id;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id)
VALUES (@shipment_id, @next_sequence, @scan_time, @scan_status, @scan_hub);
COMMIT;
```

The trigger also locks the parent and validates existence, but the external prelock is part of the supported protocol: the INSERT statement starts only after a competing scanner releases the parent. READ COMMITTED prevents an earlier SELECT from preserving a stale scan-history snapshot. The trigger checks `@@SESSION.tx_isolation` to reject the usual unsafe isolation setting; that variable reports the session default, so the check cannot detect all one-shot overrides or prove the caller prelocked. Those overrides and protocol bypasses are unsupported. The trigger reads `scan_event` normally; it neither mutates nor takes a self-table FOR UPDATE lock on the triggering table.

Both triggers execute within the caller's InnoDB transaction. The parent lock remains held through the derived-state update and commit/rollback. A failed statement leaves neither its scan nor its derived shipment update. A second scanner waits before its INSERT, then validates against the first committed sequence/time/status. If it submits a previously computed sequence, it is rejected; it must recompute after acquiring the lock. Avoid multi-row inserts, INSERT ... SELECT, INSERT IGNORE, REPLACE, and ON DUPLICATE KEY UPDATE. Scan posting holds only the shipment lock and does not subsequently acquire a departure lock.

## Safe Create/Update policy for the future Python CLI

These rules are **mandatory application behavior**, not additional triggers. Use raw parameterized SQL, READ COMMITTED transactions, ownership checks, and rollback on every failure. Keep FK/CHECK checks enabled and use strict SQL mode. Whenever both locks are needed, take **departure before shipment**. Never implement these operations as an unlocked read followed by an update.

1. **Departure capacity, including reductions:** lock the departure, confirm carrier ownership, recompute SUM over its booked shipments, require the new positive capacity >= that sum, UPDATE, commit. All booked-weight edits and bookings use the same departure lock. Thus both increases and valid decreases are supported, including on booked departures; under-capacity changes are rejected.
2. **Shipment weight, route, and promise:** initially read the shipment's booking departure ID without locking. If booked, lock that departure first; then lock the shipment. Re-read its booking under READ COMMITTED. If that mapping changed since the initial read, ROLLBACK and retry from the start. If initially unbooked, lock just the shipment, recheck booking, and if it became booked, ROLLBACK/retry rather than acquiring a departure lock in the wrong order. Verify shipper ownership and reject all these logistics edits after the first scan. For an unbooked/unscanned shipment, allow valid lane, weight, and promise edits. For a booked/unscanned shipment, forbid lane changes; allow promise edits and positive weight edits only if `SUM(current booked weights) - old_weight + new_weight <= capacity`. Perform the UPDATE while retaining both locks. Do not edit `current_status` or `delivery_outcome` in Python.
3. **Departure lane, vehicle, and departure time:** lock the departure and confirm carrier ownership; permit edits only with zero bookings. Verify any replacement vehicle belongs to that same carrier. Once booked, these attributes are immutable, whether or not scans have occurred. Under supported scan authorization every scan belongs to a booked shipment, so this also protects already scanned departures. Capacity edits remain governed by rule 1.
4. **Vehicle maintenance:** the owner may edit home hub and subtype-specific descriptive fields, preserving domain CHECKs. Parent identity, owning carrier, and selected subtype are immutable. This supports required Create/Update without retroactively reassigning historic shipments to a different carrier. Departure capacity is authoritative; the specification does not define a conversion from gross weight rating or axle count to freight payload.
5. **Bookings:** only CALL may insert; no direct INSERT/UPDATE/DELETE, rebooking, or cancellation endpoint. UNIQUE blocks duplicate direct inserts but does not validate lanes or capacity for arbitrary direct inserts. Do not expose a generic SQL execution menu. The required View Queries menu will execute a fixed list of parameterized read-only reports.
6. **History and identity:** no scan UPDATE/DELETE and no operational deletion or PK mutation of shipments, departures, vehicles, accounts, hubs, or lanes. No changes to account role, ownership, lane endpoint identity, or subtype membership after creation. Other original cascade actions are retained structurally but must not be exposed as a history-editing path; the two lane-to-hub update actions are RESTRICT. Administrative corrections require separate review and consistency repair outside normal operations.
7. **Creation/access:** insert shipment derived fields as NULL. Shippers act on their own shipments only; carriers create/manage their own vehicles/departures and post scans only through their booked departures; viewers cannot write. Password hashing/verification and these role scopes belong to the future application, as explicitly required by the PDF. Booking and scan triggers are not authentication mechanisms.

The shared departmental owner can bypass this policy with SQL. Table CHECKs cannot enforce cross-row SUMs, immutable history, or cross-table specialization. With the prescribed one procedure/two triggers, **database-only protection against arbitrary owner DML is not claimed**. Database privilege restrictions could be optional defense in depth if a DBA provides them, but this submission neither creates users nor grants/revokes privileges. Until Python update handlers implement these protocols, these edits must not be exposed by the CLI. Supported writes preserve capacity by sharing the departure lock; direct unsupported edits do not have that guarantee.

## Indexes and required query patterns

All child FKs have explicit left-prefix indexes or PKs; parent references target PKs. The validation script checks this. Retaining `idx_booking_departure` supports SUM and departure utilization; the booking PK/unique index supports shipment lookups. Tracking and consecutive-scan analysis use the scan PK in sequence order, with `(shipment_id, scan_timestamp)` retained for time-ordered tracking; ties use sequence. The added `(status, scan_timestamp, shipment_id)` supports delivered-period filtering.

The six official analytical queries (p. 5) are supported without adding a reporting table: carrier vehicle/type counts use the vehicle carrier index and subtype PKs; lane load ranking uses departure lane/time and booking departure indexes; scan dwell analysis uses the scan PK; cumulative delivered weight joins the delivered scan index through shipment/booking/departure/vehicle keys; distinct shippers per departure use booking departure and shipment PK; shipments with no scans use the scan PK's shipment prefix. Shipper/promise and status/promise indexes support role reports, and vehicle/time indexes support carrier scheduling. Aggregates/window queries can still require sorting or temporary results; no claim is made that an index eliminates every scan or sort. Check EXPLAIN with representative data when the later query file is implemented.

## Compatibility and verification status

The implementation uses MariaDB 10.5 features: InnoDB CHECK/FK enforcement, SELECT ... INTO, FOR UPDATE, scoped NOT FOUND/SQLEXCEPTION handlers, SIGNAL/RESIGNAL, START TRANSACTION, `in_transaction`, `tx_isolation`, and mysql-client DELIMITER directives. No MySQL 8-only collation or syntax is used. The validation script uses MariaDB-supported CTEs and INFORMATION_SCHEMA metadata. If binary logging is enabled, READ COMMITTED writes need a compatible row-logging configuration; do not change departmental server globals yourself.

Reference documentation: [constraints](https://mariadb.com/docs/server/reference/sql-statements/data-definition/constraint), [transaction isolation](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/set-commands/set-transaction), [row locks](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/for-update), [transaction boundaries](https://mariadb.com/docs/server/reference/sql-statements/transactions/start-transaction), [trigger limitations](https://mariadb.com/docs/server/server-usage/triggers-events/triggers/trigger-limitations), [RESIGNAL](https://mariadb.com/docs/server/reference/sql-statements/programmatic-compound-statements/resignal).

Static checks passed for 14 explicit InnoDB tables, one procedure, two triggers, 20 client-framed statements, unchanged original column/type and PK/FK relationships (with only the two documented lane-to-hub update-action changes), 15 unique CHECK names, index/check coverage in the verification file, and read-only verification statements. SHA-256 checks confirmed the preliminary SQL and finalized ER were unchanged. This is source inspection, not server syntax validation.

The user subsequently reported a partial MariaDB 10.5.22 installation failing with error 1901 at `chk_lane_different_hubs`. Reported existing tables: account, box_truck, carrier, hub, rail_car, refrigerated_van, shipper, vehicle, viewer; existing procedure: book_shipment; no triggers. Missing tables: lane, shipment, departure, booking, scan_event. This state was supplied by the user and was not queried or independently verified. An existing procedure does not prove its missing dependencies or runtime behavior are valid.

For this compatibility fix, no server connection or SQL execution was performed. The amended installation and verification SQL have only been statically checked; full MariaDB 10.5.22 compilation, functional behavior, and concurrency remain unverified. No credentials were read or modified, no commits were created, and no pushes were performed. Manual cleanup of the partial installation is reserved for the user after review. The script remains a fresh-install script: do not rerun it against the reported partial installation, and do not treat these edits as a migration or recovery script.

## Exact application commands after review/approval

Use an installed **MariaDB client** (`mariadb`, or `mysql` if that is the MariaDB client's binary name). These flags are for that client, not an Oracle MySQL 8 client. Connect from campus or the campus VPN. Run from the project root in macOS zsh. The application still uses environment variables/`.env`; these manual administrative client commands prompt privately for the password rather than putting it on the command line. Do not source `.env` as shell code.

```sh
cd /Users/devanshkhandor/Documents/DBMS_FinalProject
export DB_HOST=classdb2.csc.ncsu.edu
export DB_PORT=3306
export DB_NAME=dkhando
read -r 'DB_USER?Database username: '
export DB_USER

# Read-only preflight. Enter the database password at the client's prompt.
mariadb --no-defaults --protocol=TCP --skip-ssl \
  --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password \
  --database="$DB_NAME" --execute="SELECT VERSION(), DATABASE(); SHOW FULL TABLES; SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE(); SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE(); SELECT @@GLOBAL.log_bin, @@SESSION.binlog_format, @@SESSION.foreign_key_checks, @@SESSION.check_constraint_checks;"
```

Verify the selected schema and version. If **any target name** already exists (including a preliminary table or a view with that name), stop: this is a fresh installation, not an in-place migration. Do not drop existing objects or use `IF NOT EXISTS` to mask a mismatch. Obtain a reviewed migration/backup plan instead. Installation requires CREATE/CREATE ROUTINE/TRIGGER privileges on the assigned schema and the routine/trigger definer's normal data access; it does not require CREATE DATABASE. If privileges or binary logging prevent installation, report the error rather than changing globals or objects.

After reviewing the SQL and confirming the target names are free:

```sh
mariadb --no-defaults --protocol=TCP --skip-ssl \
  --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password \
  --database="$DB_NAME" < sql/01_schema.sql

# Only after the installation command succeeds:
mariadb --no-defaults --protocol=TCP --skip-ssl \
  --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password \
  --database="$DB_NAME" < tests/schema_validation.sql
```

Do not add `--force`: stop at the first error. DDL implicitly commits, so installation is not atomic or rollbackable; inspect a partial installation before any retry. Structural validation is read-only but returns PASS/FAIL as rows, not a nonzero exit status for a failed expectation. Inspect all results and definitions. Run the mutation/concurrency plan only on an explicitly approved disposable database/fixture, never automatically against departmental data. A separate database must already be provisioned; no CREATE DATABASE permission is assumed.

DELIMITER is parsed by the MariaDB/mysql **client**, not by the server. A future PyMySQL installer must remove delimiter directive lines and send each complete CREATE TABLE/PROCEDURE/TRIGGER as one statement. Never split a routine body on every semicolon or send `DELIMITER` through `cursor.execute`. CALL itself is one parameterized statement: `cursor.execute("CALL book_shipment(%s, %s)", (shipment_id, departure_id))`; drain remaining result sets with `nextset()` before reusing the connection. Do not wrap this CALL inside a Python-owned transaction.
