CSC 540 — Freight Tracking and Delivery Management
NC State University | Fall 2026

TEAM MEMBERS
Devansh Khandor
Krisha Shah
Sanjana Shetty
Sachith Bhaskar

1. PROJECT OVERVIEW

This project implements a freight tracking and delivery management
system using Python, Flask, and MariaDB 10.5.

The application supports three account roles:

SHIPPER: Create and manage shipments, book eligible departures,
track shipments, and view shipment reports.

CARRIER: Manage vehicles and scheduled departures, post shipment
scan events, and view operational reports.

VIEWER: Track shipments and view read-only performance reports.

The application uses SQL directly through PyMySQL without an ORM.
The database implements booking capacity rules using a stored
procedure and maintains scan chronology and delivery outcomes
using two triggers.

2. SUBMITTED FILES

sql/01_schema.sql:
  Database tables, keys, foreign keys, constraints, one booking
  stored procedure, and two scan-event triggers.

sql/02_sample_data.sql:
  The professor-provided sample dataset mapped to our schema.

sql/03_queries.sql:
  All six required analytical SQL queries.

app/:
  Flask application, services, routes, templates, and static files.

diagrams/:
  Revised ER diagram and explanation of the design improvements.

web_tests/, tests/, analytics_checks/, test_queries.py:
  Application, SQL, and database verification code.

requirements.txt:
  Python runtime dependencies.

3. REQUIREMENTS

Python 3.10 or newer
MariaDB 10.5
Network access to the database server
Python packages from requirements.txt

For the university database, connect to:
  Host: classdb2.csc.ncsu.edu
  Port: 3306
  Database: dkhando

Off-campus access may require the NC State VPN.

4. PYTHON SETUP

From the extracted project directory:

  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -r requirements.txt

On Windows, activate the environment using:
  .venv\Scripts\activate

5. DATABASE CONFIGURATION

Copy .env.example to .env and provide the appropriate database
connection settings:

  DB_HOST
  DB_PORT
  DB_NAME
  DB_USER
  DB_PASSWORD
  SECRET_KEY
  APP_ENV=development

SECRET_KEY should be a randomly generated secret of at least
32 characters.

Do not commit or submit real passwords or .env files.

Existing environment variables take precedence over .env.

6. DATABASE INSTALLATION

The NC State university database has already been populated
with the provided sample dataset.

Do not rerun the installation or sample-data SQL scripts against
an existing populated database.

For a NEW, EMPTY, authorized MariaDB schema only, execute these
files in this order:

  1. sql/01_schema.sql
  2. sql/02_sample_data.sql

Select the intended schema in the MariaDB client before running
either script.

The sample-data script is not idempotent. Do not run it twice
against the same schema.

The provided sample data contains:

  8 accounts
  11 hubs
  5 directed lanes
  7 vehicles
  10 departures
  23 shipments
  22 bookings
  69 scan events

Shipment 14 is unbooked and has no scan events.

The five supported statuses are RECEIVED, IN_TRANSIT,
ARRIVED_AT_HUB, OUT_FOR_DELIVERY, and DELIVERED.

The original sample data uses four-stage delivered histories.
ARRIVED_AT_HUB is optional, so the application also supports
five-stage histories.

7. DEMO ACCOUNT INITIALIZATION

On a newly seeded database, the eight sample accounts initially
have password initialization markers.

Run this command ONCE against the intended newly seeded schema:

  python -m app.bootstrap_accounts

Enter and confirm a shared demonstration password when prompted.

This command does not reset accounts whose passwords are already
initialized. Never rerun it against the populated university
database, where demo account passwords are already configured.

Sample account mapping:

  CARRIER: 1, 2, 3
  SHIPPER: 4, 5, 6, 7
  VIEWER: 8

8. START THE APPLICATION

Run from the project root:

  python -m flask --app app.web:create_app run --no-debug --port 5000

Open:

  http://127.0.0.1:5000

Check database connectivity at:

  http://127.0.0.1:5000/status

The Flask port does not determine which database is used.
The DB_* environment variables determine the database target.

The application also supports the Python CLI entry point:

  python -m app.main

9. REQUIRED ANALYTICAL QUERIES

The View Queries menu provides all six required reports:

  1. Number of vehicles of each type owned by each carrier.
  2. Departure utilization rankings within each directed lane.
  3. Time between consecutive scans for a shipment.
  4. Cumulative delivered shipment weight by carrier.
  5. Departures serving at least two distinct shippers.
  6. Shipments with no recorded scan events.

The same queries are provided in sql/03_queries.sql.

Query 3 uses the shipment ID parameter @shipment_id, which
defaults to 1 in the SQL file. Change this value to inspect
a different shipment.

With the original sample data, shipment 1 has four scan events
and elapsed intervals of NULL, 65, 865, and 90 minutes.

10. DATABASE RULES

Bookings are performed using the book_shipment stored procedure,
which checks remaining departure capacity and records the
booking atomically.

The scan-event BEFORE INSERT trigger checks sequence numbers,
chronological timestamps, and valid non-regressing transitions.

The AFTER INSERT trigger updates shipment status and determines
whether a completed delivery is ON_TIME or LATE.

Scan inserts require the documented READ COMMITTED transaction
and shipment-row locking protocol. See
sql/schema_design_notes.md for implementation details.

The application enforces role-based and owner-based access.
Shippers access only their own shipments; carriers manage only
their own vehicles and departures and their assigned scans;
viewers have read-only access.

11. TESTING

Install test dependencies before running the test suites:

  python -m pip install -r requirements-dev.txt

Run the Flask test suite:

  python -m pytest web_tests/ -q

Run the analytics offline tests:

  python -m unittest analytics_checks.test_offline -q

Run dependency verification:

  python -m pip check

The tests/ directory includes live database test cases, some
of which perform writes. These require a separately prepared
test environment and should not be executed against the
populated demonstration database.

The isolated scan verification utility also performs database
writes and is intended only for a disposable local test schema.

12. SAMPLE DATA VERIFICATION

The provided sample-data script was reconciled against the
official Sample Data for Demo and Testing document.

Expected sample counts include 14 delivered shipments,
5 in transit, 3 received, and 1 unscanned shipment.

The 14 delivered shipments consist of 9 ON_TIME and 5 LATE.

All six analytical queries were verified against the corrected
sample data. The Flask application was also exercised against
local Docker MariaDB and the NC State university database.

The schema maps the supplied hub and organization identifiers
to numeric IDs. The HUB table also stores the original hub codes
and names, while the ACCOUNT table stores organization names.

13. ADDITIONAL NOTES

The revised ER model is included in editable draw.io format
alongside a PDF export.

The system is intended for coursework demonstration using
MariaDB 10.5 and the supplied sample data.

For independent grading, configure database access using
the steps above and run the application from the project root.

ADDITIONAL SAMPLE-DATA ATTRIBUTES
---------------------------------
The HUB table stores hub_id, hub_code, hub_name, and region.
The ACCOUNT table stores account_id, password, role, and account_name.

The official sample dataset includes all 11 hub codes and names,
as well as the names of all 8 carrier, shipper, and viewer accounts.

These descriptive attributes are nullable and do not change
the existing primary keys, foreign keys, relationships,
stored procedures, triggers, or analytical queries.
