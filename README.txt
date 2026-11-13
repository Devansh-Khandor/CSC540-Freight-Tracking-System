CSC 540 - Freight Tracking and Delivery Management
NC State University

ANALYTICS AND SAMPLE-DATA INSTRUCTIONS

This branch contains the six required analytics queries, reusable Python query
functions, a sample-data seed, and a secure password-initialization utility.
The database target is MariaDB 10.5 on the departmental class server. SQL is
executed with raw SQL and PyMySQL; no ORM is used.

IMPORTANT DATABASE SAFETY
-------------------------
sql/02_sample_data.sql uses explicit IDs and is a one-time seed script. Run it
ONLY in a fresh, dedicated schema that contains the canonical tables,
constraints, procedure, and triggers from sql/01_schema.sql. Do not run it
against a populated schema. In particular, NEVER run the seed installation
blindly against the shared dkhando schema. The analytics tests also refuse to
run against dkhando.

The team must obtain a clean, dedicated class schema before validating the
seed. Do not drop, truncate, reset, or overwrite a shared schema to make room
for this dataset. The existing canonical sql/01_schema.sql is unchanged.

FILES
-----
sql/01_schema.sql
    Canonical tables, constraints, booking procedure, and scan triggers.
sql/02_sample_data.sql
    One-time sample seed: 11 hubs, 5 directional lanes, 8 accounts,
    7 vehicles across all three subtypes, 10 departures, 23 shipments,
    22 bookings, and 83 scan events. Shipment 14 intentionally has no scans.
sql/03_queries.sql
    The six required analytical queries, in the professor-required order.
app/queries.py
    Six reusable query functions. Query 3 accepts a shipment ID and uses a
    parameterized PyMySQL placeholder.
app/bootstrap_accounts.py
    Initializes only accounts marked BOOTSTRAP_REQUIRED using Werkzeug scrypt.
test_queries.py
    Read-only integration assertions for all six analytics queries. Requires
    an explicit ANALYTICS_TEST_SCHEMA setting and checks the connected schema.
requirements.txt
    Runtime dependencies, including PyMySQL, python-dotenv, and Werkzeug.
requirements-dev.txt
    Runtime dependencies plus pytest.
diagrams/Final_Revised_ER_Diagram.drawio and .pdf
    Approved final ER diagram assets retained from main.

SETUP
-----
Use Python 3.10 or newer. From the repository root:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements-dev.txt

Create a local .env file from the template if needed:

    cp -n .env.example .env
    chmod 600 .env

Edit .env locally and set DB_HOST, DB_PORT, DB_NAME, DB_USER, and DB_PASSWORD.
Use the dedicated, empty schema assigned for analytics validation as DB_NAME.
Do not commit .env or share its contents. app/db.py loads .env from the project
root; exported environment variables take precedence.

DATABASE INSTALLATION - FRESH SCHEMA ONLY
-----------------------------------------
The following commands use an interactive password prompt (-p); they do not
place the database password in shell history or command-line arguments.
Set these non-secret shell variables to the host, port, username, and the
dedicated schema you were assigned:

    export DB_HOST=classdb2.csc.ncsu.edu
    export DB_PORT=3306
    export DB_USER=your_unity_id
    export DB_NAME=your_fresh_dedicated_schema

Confirm with your team/database administrator that DB_NAME is an empty,
dedicated schema before continuing. Then install the canonical schema:

    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/01_schema.sql

Load the sample data exactly once:

    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/02_sample_data.sql

Do not rerun the seed if any rows have already been inserted. Do not point
these commands at dkhando or another shared/populated schema.

SECURE DEMO PASSWORD INITIALIZATION
-----------------------------------
The seed inserts the eight demo accounts with the sentinel password
BOOTSTRAP_REQUIRED, not a plaintext password. After loading the seed, run:

    python -m app.bootstrap_accounts

The utility securely prompts for the shared demo password and confirmation.
It validates all eight expected account IDs and roles before changing anything,
then generates a separate salted Werkzeug hash for each account using the
existing scrypt:32768:8:1 method. It updates only rows whose password is still
BOOTSTRAP_REQUIRED and rolls back on any failure. There is no plaintext
password fallback. Do not run this utility against an already initialized
database; it intentionally refuses to overwrite existing hashes.

RUN THE SIX SQL ANALYTICS QUERIES
---------------------------------
The SQL file contains the six reports in the required order. Query 3 currently
demonstrates shipment ID 1; edit its literal shipment_id filter if a different
shipment is being demonstrated.

Execute all six statements and save the real MariaDB client output:

    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME" < sql/03_queries.sql > analytics_query_results.txt

The command prompts for the password. It writes the actual query results to
analytics_query_results.txt; do not manually create or edit that output.
Record the schema name and exact command in analytics_execution_notes.txt
separately. Do not include credentials in that notes file.

VERIFY SAMPLE ROW COUNTS
------------------------
After loading the seed, connect to the same dedicated schema:

    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p "$DB_NAME"

At the MariaDB prompt, run:

    SELECT 'hub' AS table_name, COUNT(*) AS row_count FROM hub
    UNION ALL SELECT 'lane', COUNT(*) FROM lane
    UNION ALL SELECT 'account', COUNT(*) FROM account
    UNION ALL SELECT 'vehicle', COUNT(*) FROM vehicle
    UNION ALL SELECT 'departure', COUNT(*) FROM departure
    UNION ALL SELECT 'shipment', COUNT(*) FROM shipment
    UNION ALL SELECT 'booking', COUNT(*) FROM booking
    UNION ALL SELECT 'scan_event', COUNT(*) FROM scan_event;

Expected row counts:

    hub          11
    lane          5
    account       8
    vehicle       7
    departure    10
    shipment     23
    booking      22
    scan_event   83

Expected analytical result counts:

    Query 1: 3 carrier rows; 7 vehicles in total.
    Query 2: 10 departure rows.
    Query 3: 5 scan rows for shipment 1. Expected elapsed minutes:
             NULL, 65, 595, 270, 90.
    Query 4: 14 delivered-shipment rows.
    Query 5: 3 departures with at least two distinct shippers.
    Query 6: 1 shipment without scans (shipment_id 14).

These are expected values for the supplied seed. They are not evidence that a
database execution has occurred; capture actual output after running the
commands above.

RUN THE SIX PYTHON ANALYTICS INTEGRATION TESTS
----------------------------------------------
Set ANALYTICS_TEST_SCHEMA to the exact dedicated schema being tested, and make
DB_NAME point to that same schema. For example:

    export ANALYTICS_TEST_SCHEMA="$DB_NAME"
    python -m py_compile app/queries.py app/bootstrap_accounts.py test_queries.py
    python -c "from app import queries; print('Analytics query imports: PASS')"
    python test_queries.py

The test runner checks SELECT DATABASE() against ANALYTICS_TEST_SCHEMA before
running any assertions. It refuses dkhando. The tests are read-only and verify
the expected counts and values for all six queries, including all five scan
statuses and the four elapsed intervals for shipment 1.

OTHER LOCAL CHECKS
------------------
    python -m pip check
    python -m app.main

The application connectivity command uses the credentials in .env and prints
the server version only if the MariaDB connection succeeds. A successful
compile/import check alone does not prove database connectivity or SQL
execution.

CREDENTIALS AND GENERATED FILES
-------------------------------
Never commit .env, database passwords, or other secrets. The bootstrap utility
uses getpass so the password is not echoed. Keep analytics_execution_notes.txt
free of credentials. Generate analytics_query_results.txt from actual SQL
execution rather than hand-editing it.
