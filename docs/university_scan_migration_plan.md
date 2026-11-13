# University 83-to-69 scan migration plan — NOT EXECUTED

Target ONLY `classdb2.csc.ncsu.edu:3306`, schema `dkhando`, MariaDB 10.5.22. Read credentials privately from `.env.university`; do not load `.env`, edit either file, print connection arguments or allow fallback to Docker.

The corrected source and fresh installation are verified; the university migration itself has NOT been rehearsed or executed. Execution is conditional on authorization, a maintenance window, verified live preflight, trigger privileges and recovery material. There is no fully atomic transaction spanning trigger DDL and scan DML on this server. If crash-proof all-or-nothing DDL plus data is mandatory, this plan is NO-GO without additional recovery support.

## 1. Freeze, identify, capture and classify (read only)

Stop all Flask/CLI writers and coordinate with teammates; keep them stopped through verification or recovery. An advisory lock alone cannot exclude uncooperative clients. Do not proceed if exclusive maintenance cannot be established.

Construct an explicit connection from UNIVERSITY_DB_* and assert host/port/schema against the constants above before connecting. Check `SELECT DATABASE(), VERSION(), @@hostname, @@port`; also retain the actual connection host/port. Reject any mismatch. Disable automatic reconnect/retry. Do not use a command line containing credentials.

Before any DDL:

1. Verify the source hashes in `sample_data_reconciliation.md`. Capture `SHOW CREATE TABLE` for all 14 tables, `SHOW CREATE PROCEDURE dkhando.book_shipment`, both `SHOW CREATE TRIGGER` results, foreign-key metadata and engine types. Compare against reviewed definitions, allowing only known definer/creation-charset/auto-increment metadata differences. Confirm no external foreign keys reference scan_event and no unexpected triggers exist. All tables must be InnoDB.
2. Check the current session's grants privately. Confirm permission to SHOW CREATE, DROP/CREATE the BEFORE trigger and perform the specified scan/shipment DML. Recreating the captured definer must be authorized; otherwise obtain DBA assistance BEFORE dropping anything.
3. Capture the exact old BEFORE-trigger CREATE statement, SQL_MODE, character_set_client and collation_connection, plus old 83 scans and shipment derived fields, into a local private recovery directory (0700 directory, 0600 files), outside the repository. Do not include account password values. This is targeted recovery material, not a claim of a complete backup or a guarded-loader receipt. Keep a private phase journal with source digests and phase outcomes only.
4. Read every non-password row and compare values, keys and counts with the legacy source at commit `4735ae65a2190a04137ee849410e92c491c8ddf2`. Do not use moving HEAD as a baseline. The source file is `sql/02_sample_data.sql` at that revision. Compare all remaining fields against the corrected fixture too: the only expected differences are 14 synthetic arrival rows and sequence numbers on the corresponding later scans. Accounts must be exactly IDs 1–8 with roles/subtypes unchanged; password values are intentionally excluded from fixture comparison. Never expect or restore seed password markers.
5. Expected counts are the corrected counts in the reconciliation report except scan_event=83. Require exact scan tuple equality, correct status/outcomes, all 22 bookings, no lane mismatch and no over-capacity departure. A count-only check is insufficient.

Recognized states:
- Exact old 83 rows + old BEFORE trigger: eligible for migration.
- Exact official 69 rows + corrected BEFORE trigger + all postconditions: already complete; return success without writes.
- Exact old 83 rows + corrected BEFORE trigger: interrupted between phases; stop for deliberate recovery/resume, rechecking all prerequisites.
- Missing trigger, mixed scan data, any other account/sample data or object differences: STOP. Never automatically reload, delete or retry.

## 2. Replace only the BEFORE INSERT trigger (nontransactional phase)

Do not start the scan transaction yet. Finish any read transaction. Restore the captured creation SQL_MODE and character set/collation on the DDL connection. Prepare the corrected CREATE statement from **only** `trg_scan_event_before_insert` in the hash-pinned `sql/01_schema.sql`, preserving the installed definer. Verify its sole logic difference from the old definition is permitting OUT_FOR_DELIVERY after IN_TRANSIT.

Execute, separately and with stop-on-first-error:

```sql
DROP TRIGGER dkhando.trg_scan_event_before_insert;
-- Execute the complete prepared CREATE DEFINER=... TRIGGER statement here,
-- qualified to dkhando, using the exact corrected canonical body.
```

Send CREATE as one driver statement; DELIMITER is a client directive, not server SQL. Do not execute the full schema file. Immediately compare SHOW CREATE with the prepared definition and verify the AFTER trigger and procedure are untouched.

**Exact irreversible transaction boundaries:** DROP TRIGGER and CREATE TRIGGER each implicitly commit; neither can be undone by ROLLBACK. CREATE OR REPLACE TRIGGER would not solve this. Compensating DROP/CREATE to restore the old trigger are also separate implicit commits. MariaDB 10.5 predates 10.6 atomic-DDL improvements, so a crash during DDL also requires object inspection. No ALTER TABLE, TRUNCATE, LOCK TABLES, schema creation, procedure replacement or foreign-key disabling is part of this plan.

If CREATE/verification fails, keep writers stopped, inspect whether the trigger exists, and restore the captured old definition with its captured context. Verify recovery before resuming service. If permissions or connection loss prevent restoration, stop and request DBA assistance; do not enter the data phase.

References: [implicit commits](https://mariadb.com/docs/server/reference/sql-statements/transactions/sql-statements-that-cause-an-implicit-commit), [atomic DDL version boundary](https://mariadb.com/docs/server/reference/sql-statements/data-definition/atomic-ddl), [SHOW CREATE TRIGGER context](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/show/show-create-trigger).

## 3. Rebuild scans in ONE rollbackable data transaction

Use one dedicated connection, no DDL, booking procedure calls or seed-script execution. Assert the explicit university target again. Configure the canonical strict SQL mode and:

```sql
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
START TRANSACTION;
SELECT account_id, role FROM account ORDER BY account_id FOR UPDATE;
SELECT shipment_id FROM shipment ORDER BY shipment_id FOR UPDATE;
SELECT shipment_id, scan_sequence, scan_timestamp, status, hub_id
FROM scan_event ORDER BY shipment_id, scan_sequence FOR UPDATE;
```

The executor must compare the locked rows with the exact captured 83-row baseline and reread all other sample data/object prerequisites before any mutation. Account locks prevent password changes during this transaction; there must be **no account or subtype DML** anywhere in the executor.

For each of the captured 83 exact scan tuples, use this parameterized statement and require affected rows = 1:

```sql
DELETE FROM scan_event
WHERE shipment_id=%s AND scan_sequence=%s AND scan_timestamp=%s
  AND BINARY status=%s AND hub_id=%s;
```

Require scan_event count=0. Do not renumber in place: the composite primary key `(shipment_id,scan_sequence)` would collide, and there are no UPDATE/DELETE synchronization triggers. This exceptional maintenance operation is not a new application write permission.

Reset the two derived fields together for each of the 22 previously scanned shipment IDs (1–13 and 15–23):

```sql
UPDATE shipment SET current_status=NULL, delivery_outcome=NULL
WHERE shipment_id=%s;
```

Require one changed row per shipment under the verified non-NULL baseline. Shipment 14 remains untouched and NULL/NULL. All ownership, route, weight, promised date and booking data remain untouched.

Obtain the 69 tuples from the hash-pinned corrected fixture, cross-checked against `sample_data_pdf_evidence.json`. For each shipment in ascending ID and each sequence in ascending order, issue a separate prelock followed by one single-row INSERT:

```sql
SELECT shipment_id FROM shipment WHERE shipment_id=%s FOR UPDATE;
INSERT INTO scan_event
(shipment_id, scan_sequence, scan_timestamp, status, hub_id)
VALUES (%s,%s,%s,%s,%s);
```

Require each INSERT affected rows = 1. Keep both INSERT triggers active. There are NO intermediate commits. Do not copy the seed's per-shipment transaction statements. The corrected BEFORE trigger checks the rebuilt history; the unchanged AFTER trigger recomputes both derived shipment fields after every insert.

## 4. Validate BEFORE committing, then verify again

On that SAME connection and transaction:

- Compare all 69 scan tuples exactly with the independently PDF-verified evidence. Verify contiguous sequence starting at 1, nondecreasing timestamps and valid transitions. No ARRIVED_AT_HUB row belongs to this fixture, although the trigger must still support it generally.
- Verify every non-password value in all other tables is unchanged; compare all eight account IDs/roles and memberships with the captured baseline. Account passwords are preserved by zero account writes; do not select or log them. Compare the entire shipment row except the deliberately recomputed fields, then verify those fields independently against last scans and promised dates.
- Require all 14 counts: account 8, carrier 3, shipper 4, viewer 1, hub 11, lane 5, vehicle 7, box_truck 4, refrigerated_van 2, rail_car 1, departure 10, shipment 23, booking 22, scan_event 69.
- Require 14 DELIVERED, 5 IN_TRANSIT, 3 RECEIVED, 1 NULL; outcomes 9 ON_TIME, 5 LATE, 9 NULL. Recheck all lane matches and SUM(booked weight) <= capacity, not just departure 1.
- Call the six functions in app/queries.py directly with this connection (Q3 shipment_id=1). Compare outputs with the fresh isolated baseline recorded in the reconciliation report; canonicalize Q2 ties by departure ID for comparison. Require Q1 subtype counts, Q2 all ten utilization/rank rows, Q3 all four timestamps and intervals, Q4 all fourteen rows/running totals, Q5 departures 1/2/3 and Q6 shipment 14. The expected full result set must be captured from the verified isolated fixture before execution.
- Do NOT call `test_queries.run_tests()` inside this transaction: it opens a different connection and its dkhando guard intentionally rejects seed-only mode. Do not weaken that guard or pretend this is the old combined dataset.

If ANY assertion or statement fails: explicitly ROLLBACK, confirm the original 83 tuples and derived fields returned, then compensate the trigger DDL by restoring the captured old BEFORE trigger separately. Recheck all objects. Keep maintenance active if compensation fails. Never automatically rerun a partially completed operation.

Only if every assertion passes: COMMIT once. Then open a new explicit university read-only connection and repeat counts, exact tuple comparison, preserved data/object checks and all six functions. Record success without secrets and resume writers only after these pass.

If commit acknowledgement is lost, inspect the actual state on a new connection: exact old83 or exact official69. Do not assume failure and replay. A post-commit verification failure cannot be fixed with ROLLBACK; keep writers stopped and diagnose. Any compensating data restore must be a separately reviewed transaction based on the captured scan/status snapshot, never a seed reload.

## Readiness

The source is ready for the scan correction and the isolated fresh-install checks pass. Execution remains **conditional**, not an unconditional GO: the live baseline/privileges must pass, maintenance and recovery capture must be established, and the concrete executor should first rehearse success, injected-failure rollback, DDL recovery and already-complete no-op in a disposable schema. Those migration rehearsals were not performed in this planning pass. The descriptive-name limitation is separate and is not resolved by this scan migration.

No university migration, local dkhando modification, password reset, schema redesign, loader-safeguard change or full seed reload was performed or authorized by this document.
