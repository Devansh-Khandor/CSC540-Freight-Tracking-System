CSC 540 - Freight Tracking and Delivery Management
Analytics integration preparation - devansh-analytics-fix

The six reports live in sql/03_queries.sql and app/queries.py. Canonical schema,
scan triggers, approved ER diagram and Flask authentication are unchanged.
Existing results/notes describe the earlier sachith run, including its Q3
four-scan failure; they are historical evidence, not a successful dkhando load.

SETUP AND OFFLINE CHECKS

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-dev.txt
    .venv/bin/python -m pip check
    .venv/bin/python -m compileall -q app analytics_checks test_queries.py
    .venv/bin/python -m unittest analytics_checks.test_offline -v
    git diff --check

app/db.py reads the root .env without interpolation; exported settings take
precedence. Configure DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD privately.
Never print or source .env as shell code. Ensure chmod 600 .env. Do not commit
credentials, password hashes, backups, receipts or journals. Tests use asserts;
do not run Python with -O. Plain pytest targets Sanjana's separate write-capable
functional tests for sshett24; do not use it to validate dkhando analytics.

A. FRESH ISOLATED-SCHEMA ANALYTICS TESTING

Obtain approval and an assigned empty dedicated schema, distinct from dkhando.
Set DB_NAME locally to that schema. Only for that approved empty target, install
sql/01_schema.sql and sql/02_sample_data.sql with a MariaDB client, using an
interactive password prompt, stopping immediately on errors:

    mariadb -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/01_schema.sql
    mariadb -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/02_sample_data.sql

The shell variables above must be set privately; .env is not shell-exported.
Do not reuse these installation commands for dkhando. Never retry a partial seed.
After a successful installation, run the existing isolated assertions:

    ANALYTICS_TEST_MODE=isolated ANALYTICS_TEST_SCHEMA="$DB_NAME" \
      .venv/bin/python test_queries.py

This retains the exact-schema guard and all six seed-only tests. dkhando is
rejected in isolated mode. The runner starts a server-enforced READ ONLY snapshot
and exposes only SELECT cursors to query/test code. It rolls back and closes.

B. AUDITED INTEGRATION INTO DKHANDO

The audited baseline is MariaDB 10.5.22, 14 InnoDB tables, book_shipment and two
scan triggers. Account/role rows are 540001 SHIPPER, 540002 CARRIER, 540003 VIEWER;
all freight tables are empty. Never reset the schema or overwrite these accounts.

Read analytics_checks/OPERATIONS.md completely before any approved write. The
current task prepares the process only: no seed, recovery or restore is authorized.
No local dump client is installed; Docker daemon access is unavailable. Routine
metadata is visible, but mysql.proc SELECT is denied (1142), so a complete
MariaDB routine dump may need DBA assistance. A complete backup and successful
isolated restore rehearsal are blocking prerequisites, not optional steps.

1. Pause all application writers. Obtain and rehearse the protected full backup
   as specified in OPERATIONS.md. Keep writers paused through validation.
2. Review live schema/routine/trigger definitions against the audited schema.
   No canonical schema modification or reinstall is needed.
3. Run the default read-only baseline check (DB_NAME must be dkhando in local
   configuration; do not override a mismatched target silently):

       .venv/bin/python -m analytics_checks.load_seed

   It rejects ANY departure from the exact three-account baseline, including
   partially loaded seeds. It verifies the pinned seed digest and all ID spaces.
4. Obtain explicit approval for the live seed load. Only after approval, use a
   verified backup receipt and a new durable journal outside Git:

       .venv/bin/python -m analytics_checks.load_seed --execute \
         --approval LOAD-DKHANDO-ONCE \
         --backup-receipt /absolute/private/verified-backup.json \
         --journal /absolute/private/dkhando-seed-run-001.jsonl

   The wrapper stops at the first failure, never retries, and logs no SQL or
   credentials. Prior commits survive failure. DO NOT run the raw seed against
   dkhando and DO NOT create a new journal to retry a failed attempt. Use the
   narrowly scoped, approval-gated recovery procedure in OPERATIONS.md.
5. Run explicit combined-dataset read-only validation:

       ANALYTICS_TEST_MODE=combined ANALYTICS_ALLOW_COMBINED=dkhando \
         ANALYTICS_TEST_SCHEMA=dkhando .venv/bin/python test_queries.py

   This requires SELECT DATABASE() == 'dkhando'. It checks all fixture values,
   the three protected account roles and their exact subtype memberships, and
   independently computes all report expectations from the current dataset.
   Additional unrelated records are allowed, including records that affect lane
   ranks and carrier running totals. Fixture corruption still fails. The four
   required carrier rows are 1:(2,1,0), 2:(2,1,0), 3:(0,0,1), 540002:(0,0,0).
   No vehicle, including an untyped vehicle, may belong to protected carrier
   540002 in this validation mode. A later change to that baseline needs review.
6. Capture actual SQL report output after successful validation, using an
   approved installed client and an interactive password prompt:

       mariadb -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p dkhando \
         < sql/03_queries.sql > analytics_query_results.txt

   Record date, schema and actual outcomes in analytics_execution_notes.txt;
   replace historical evidence only after real execution. Verify protected
   password preservation privately against the verified backup; report only
   pass/fail. The test runner deliberately never reads password columns.
7. Review the diff and integration results before any separately authorized
   commit, push or merge. Reopen application writers only after acceptance.

EXPECTED COUNTS IMMEDIATELY AFTER THE AUDITED LOAD

                     isolated seed      combined dkhando
    account                      8                    11
    shipper                      4                     5
    carrier                      3                     4
    viewer                       1                     2
    hub                         11                    11
    lane                         5                     5
    vehicle                      7                     7
    box_truck                    4                     4
    refrigerated_van             2                     2
    rail_car                     1                     1
    departure                   10                    10
    shipment                    23                    23
    booking                     22                    22
    scan_event                  83                    83

These global counts describe the audited baseline plus seed, not invariants for
arbitrary future data. The manifest enumerates every seed-owned key. Combined
tests scope fixture assertions to these known rows and validate the full reports
against independently computed current-data expectations.

Q1: 4 carrier rows for this baseline, including 540002 with zero vehicles.
Q2: 10 departures; booked kg for D1..D10: 7500,3700,4000,7000,3500,2800,
    2000,4000,2000,2000. D1 is 75%; D7 is exactly full. Ranks include future rows.
Q3: shipment 1 has RECEIVED, IN_TRANSIT, ARRIVED_AT_HUB, OUT_FOR_DELIVERY,
    DELIVERED; elapsed minutes NULL,65,595,270,90.
Q4: 14 fixture deliveries; fixture contributions by carrier: 1=18000 kg,
    2=9500 kg, 3=3500 kg. Global cumulative totals include future deliveries.
Q5: fixture departures 1,2,3 each have two distinct shippers.
Q6: fixture shipment 14 alone has no scans; future unscanned shipments may exist.

ACCOUNT BOOTSTRAP AND FLASK INTEGRATION

Sample accounts 1..8 initially use BOOTSTRAP_REQUIRED. Analytics does not require
password initialization. app/bootstrap_accounts.py is optional and write-capable:
run only with separate approval if demo logins are needed, after validation. Its
marker/role checks target only accounts 1..8. Do not recreate authentication or
modify the existing 540001..540003 accounts. Preserve the devansh-flask-ui branch.

All six app.queries functions accept an open connection and return tuple rows;
get_scan_time_intervals(connection, shipment_id) additionally requires a positive
non-boolean int and binds it as a SQL parameter. The other five functions take
only connection. Functions close their cursor, do not commit, and leave connection
ownership to the caller. Flask must supply per-request connections, enforce its
existing authorization policy, and handle Decimal/date/datetime serialization.
The reports themselves are global reports, not account-level access controls.
No function signatures or Flask branch files were changed.
