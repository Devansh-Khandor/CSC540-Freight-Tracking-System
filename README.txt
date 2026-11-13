CSC 540 - Freight Tracking and Delivery Management
NC State University

Steps 1–5: Flask foundation, authentication, shipper, carrier and viewer workflows

Uses Python 3 (3.10 or newer recommended), PyMySQL, and raw SQL against the
departmental MariaDB 10.5 server. SSL is explicitly disabled per the professor's
instructions. There is no ORM. Shipper, carrier and read-only viewer workflows are implemented.
The CLI uses SELECT VERSION(); the web diagnostic uses SELECT 1. Authentication
also reads account and subtype records. Shipper routes create/update shipments
and call the existing booking procedure. No web route creates
databases, tables, triggers, or procedures. Use your existing assigned schema; CREATE
DATABASE permission is neither assumed nor required.

FILES AND DIRECTORIES

app/__init__.py   Marks app as a Python package.
app/db.py         Loads configuration, validates required values and the port,
                  and opens a PyMySQL connection with SSL disabled and timeouts.
app/main.py       CLI connectivity test; prints the server version only after
                  SELECT VERSION() succeeds, and closes cursor and connection.
app/web.py       Flask application factory, homepage, status and error handlers.
app/auth.py      Login/logout, CSRF, role guards, and per-process login limiter.
app/shipper.py   Protected shipper routes and forms.
app/shipper_service.py Owner-scoped SQL, validation, and transaction protocols.
app/templates/   Shared Jinja2 layout, homepage, status, and error pages.
app/static/      Responsive CSS; no frontend framework or CDN required.
web_tests/       Offline Flask smoke tests, separate from database fixtures.
requirements.txt Runtime dependencies: PyMySQL, python-dotenv, Flask and Werkzeug.
requirements-dev.txt Includes runtime dependencies plus pytest for offline tests.
.env.example     Configuration template with no real credentials or schema name.
.gitignore       Excludes local credentials, virtual environments, caches, and
                  generated output. It keeps .env.example tracked.
README.txt       This setup and usage guide.
sql/             Database schema and design notes; unchanged by the web setup.
tests/           Existing functional and concurrency tests requiring MariaDB.
diagrams/        Reserved for authored database/project diagrams.
report/          Reserved for authored project reports.
Place disposable generated output in a generated/ directory.

FLASK WEB APPLICATION (STEP 1)

After activating .venv, install and launch from the project root:

   python -m pip install -r requirements-dev.txt
   python -m flask --app app.web:create_app run --no-debug

Open http://127.0.0.1:5000/. This is a local development server.
The homepage loads without database access. Login and protected role dashboards
are available (see Step 2 below).
Shipper, carrier and viewer operations are available. The six global analytics
queries are available through the authenticated Flask View Queries menu (/queries).
The Connection status link opens /status and runs only SELECT 1 using app/db.py.
It returns Connected (HTTP 200) or Unavailable (HTTP 503), with no credentials,
schema metadata, server version, or database exception details. Results are not
cached. Connections and cursors close after the check, including query failures.
The existing 10-second connection/read/write timeouts apply, so an unavailable
server can delay this diagnostic. The homepage and error pages do not query it.

Set SECRET_KEY in your ignored local .env or exported environment. To generate
a value locally, run this command and copy its output into .env (do not commit it):

   python -c "import secrets; print(secrets.token_hex(32))"

No signing secret is generated or hardcoded by the app. With SECRET_KEY missing
or shorter than 32 characters, public pages still work and authentication is
unavailable. Configure a random key before signing in. Debug defaults
to disabled, and the documented --no-debug flag also overrides FLASK_DEBUG.
Authentication is implemented in Step 2; shipment writes and booking are
implemented in Step 3 below. See ANALYTICS INTEGRATION below for the implemented
SQL/Python queries and their guarded validation commands.
The existing CLI command remains python -m app.main.

Run offline checks without university database access:

   python -m pytest web_tests -q
   python -m compileall -q app web_tests
   python -c "from app.web import create_app; assert not create_app().debug"
   python -m pip check

Always specify web_tests for offline testing. The existing tests/ suite has an
automatic live database schema guard and includes writes with cleanup; running
bare pytest selects that existing integration suite. Its fixtures and tests have
not been changed. Run those only with their documented MariaDB setup and access.

MACOS SETUP (Terminal, zsh)

1. Confirm Python 3 is installed:

   python3 --version

2. From the project directory, create and activate a virtual environment:

   cd /Users/devanshkhandor/Documents/DBMS_FinalProject
   python3 -m venv .venv
   source .venv/bin/activate

3. Install dependencies:

   python -m pip install -r requirements.txt

4. If you do not already have a .env file, create your local configuration:

   cp -n .env.example .env
   chmod 600 .env
   nano .env

   Keep DB_HOST=classdb2.csc.ncsu.edu and DB_PORT=3306.
   Set DB_NAME to your assigned existing schema, DB_USER to your database
   username, and DB_PASSWORD to your password. All five values are required.
   Quote values containing spaces or #; for example DB_PASSWORD='your value'.
   python-dotenv reads this file; do not source it as a shell script.
   Variable interpolation is disabled so dollar signs remain literal.
   Exported environment variables take precedence over .env values.
   The .env file is loaded from the project root, not an arbitrary directory.
   Never commit actual credentials. .gitignore does not protect files already
   tracked by Git.

5. Run the connectivity test from the project root:

   python -m app.main

   On a successful query it prints:
   Connectivity test succeeded. Server version: <actual server version>

   This example is not evidence of a successful connection. The actual server
   response is displayed only when the query succeeds. Exit status is 0 on
   success and 1 on configuration/database failure. Driver error text is omitted
   to avoid displaying account details. If connection fails, verify credentials,
   assigned schema access, and any departmental network/VPN requirements.

6. Local checks that do not connect to MariaDB:

   python -m compileall -q app
   python -c "import app.db; import app.main; print('Imports OK')"
   python -m pip check

   Syntax/import checks do not establish server access or confirm the server
   version. Run step 5 with valid credentials to verify real connectivity.

7. Leave the virtual environment when finished:

   deactivate

For later sessions, reactivate with source .venv/bin/activate before running.
Use python -m app.main, rather than python app/main.py, for package imports.

COMPATIBILITY

SELECT VERSION() and utf8mb4 are supported by MariaDB 10.5. The connection uses
no MySQL-only collation, ORM, or schema-creation commands. Transactions default
to autocommit=False; future writes will require explicit transaction handling.
PyMySQL connection options reference:
https://pymysql.readthedocs.io/en/latest/modules/connections.html

STEP 2: AUTHENTICATION AND ROLE ACCESS

Login is now available at /login. Enter an existing account ID, its provisioned
password, and assigned role. The server reads ACCOUNT with a parameterized query
and verifies the password hash, the exact ACCOUNT.role, and membership in exactly
one matching subtype table. Missing, mismatched, or multiple subtype memberships
are rejected with the same message as incorrect credentials. Registration,
carrier scanning, and analytical execution are not implemented. Step 3 adds
shipper create/update, booking, tracking, and owner-specific reports.

/shipper, /carrier and /viewer are working role-protected dashboards. Anonymous
visitors are redirected to /login; another role receives HTTP 403. Navigation
shows the signed-in user's dashboard and a POST logout form. GET /logout is not
allowed. Login and logout use session-bound CSRF tokens; tokens rotate on login,
and logout clears the session. Every future state-changing form must include
an input named csrf_token whose value is {{ csrf_token() }}. Missing or incorrect
tokens produce a generic HTTP 400. Form bodies are limited to 16 KiB.

Configuration:
- SECRET_KEY must contain at least 32 characters, generated randomly with the
  secrets command above. With a missing/short key, all authentication endpoints
  return a generic HTTP 503. Home and /status remain available.
- APP_ENV=development (default): cookie Secure is off for local HTTP only.
- APP_ENV=production: cookie Secure is on; serve exclusively over HTTPS through
  a production WSGI server. Do not use Flask's development server for deployment.
- Cookies are HttpOnly, SameSite=Lax, host-only, and expire after 30 minutes.
  SESSION_REFRESH_EACH_REQUEST is disabled. The server also checks a fixed
  expires_at timestamp so CSRF updates cannot extend a login indefinitely.
- Signed sessions contain account ID and role, plus expiry/permanence and CSRF
  metadata. They contain no passwords or hashes. They are signed, not encrypted.
  Dashboard authorization uses the signed role validated at login. Role changes
  in the database take effect at the next login. Logout removes the browser's
  cookie but cannot revoke an already copied cookie before its expiry. Password
  resets likewise do not revoke issued cookies. Rotate SECRET_KEY to invalidate
  all sessions in an emergency. Shared server-side sessions/revocation would be
  needed for immediate per-account invalidation in a production deployment.

Repeated-login defense:
- Ten attempts per five minutes per source IP AND per canonical account ID.
  Successful attempts count too. Limits are thread-safe and stored per process;
  restarting clears them and multiple workers do not share counters. At 10,000
  active buckets the limiter fails closed until buckets expire.
- Client IP is request.remote_addr; forwarded headers are deliberately ignored.
  Users behind NAT/proxies may share a limit, and targeted account throttling can
  temporarily deny a legitimate login. Before a public/multi-worker deployment,
  use a shared external limiter (for example Redis-backed) and configure trusted
  proxies explicitly. This foundation does not include distributed rate limiting.
- Unknown accounts still perform a dummy password hash check. All invalid
  credentials/roles use the same message; database outages return a generic 503.
  Database errors and submitted passwords are never logged by the auth handler.

PASSWORD BOOTSTRAP / EXISTING PLAINTEXT VALUES

ACCOUNT.password is VARCHAR(255). The database test suite intentionally uses
plaintext NOT-A-LOGIN markers and relies on them for cleanup. Do not change or
reuse those accounts. Protected test accounts 540001 SHIPPER, 540002 CARRIER and 540003 VIEWER
already exist in dkhando; their live logins were confirmed by the owner. Never
reset, overwrite, delete, reseed or change these accounts or their memberships.
Incoming sample accounts 1..8 are separate and initially require bootstrap.

This application accepts only Werkzeug scrypt:32768:8:1 hashes, created with
werkzeug.security.generate_password_hash and verified with check_password_hash.
Plaintext, malformed hashes, and other hash methods are rejected. The current
scrypt representation fits VARCHAR(255). Do not add plaintext compatibility.

To reset a specific, existing demo account explicitly (not a test fixture), first
ensure its ACCOUNT role and exactly one matching subtype record are provisioned
by your approved sample-data process. Coordinate this with the sample-data owner;
there is no public registration or automatic account creation in this app.

On campus/VPN, with the intended DB_* environment configured, run the following
from the repository root after activating .venv. This is an administrative
password reset, not part of app startup. It overwrites only the chosen account's
password after confirmation and commits explicitly. It does not preserve an old
plaintext password. Password input is hidden and never passed in shell arguments.
Do not run against functional-test accounts. This command was NOT executed as
part of implementation; no database rows were modified.

python - <<'PY'
from getpass import getpass
from werkzeug.security import generate_password_hash
from app.db import get_connection
from app.auth import ACCOUNT_SQL, HASH_METHOD, valid_identity

account_id = int(input("Existing demo account ID to reset: "))
if account_id in (540001, 540002, 540003):
    raise SystemExit("Protected verification accounts must not be reset.")
password = getpass("New password (at least 12 characters): ")
if len(password) < 12 or len(password) > 1024:
    raise SystemExit("Use 12 to 1024 characters.")
if password != getpass("Repeat new password: "):
    raise SystemExit("Passwords did not match.")
encoded = generate_password_hash(password, method=HASH_METHOD)
if len(encoded) > 255:
    raise SystemExit("Hash does not fit the existing column.")
with get_connection() as connection:
    with connection.cursor() as cursor:
        cursor.execute(ACCOUNT_SQL + " FOR UPDATE", (account_id,))
        row = cursor.fetchone()
        if not valid_identity(row):
            raise SystemExit("Account/subtype setup must be corrected first.")
        if row[1].startswith("PYTEST-") or "NOT-A-LOGIN" in row[1]:
            raise SystemExit("Do not reset database-test fixture accounts.")
        if input("Type RESET to replace this account's password: ") != "RESET":
            raise SystemExit("Cancelled; no changes made.")
        cursor.execute("UPDATE account SET password = %s WHERE account_id = %s",
                       (encoded, account_id))
    connection.commit()
print("Password reset complete. Sign in with the account's assigned role.")
PY

For newly provisioned demo accounts, the sample-data owner must likewise use
generate_password_hash(password, method="scrypt:32768:8:1") and store its output
through a parameterized insert, alongside the matching subtype. Keep real
passwords and generated credential hashes out of tracked seed files and logs.
This task does not alter sql/ or implement a provisioning route.

Offline checks and local launch:

   source .venv/bin/activate
   python -m pip install -r requirements-dev.txt
   python -m pytest web_tests -q
   python -m compileall -q app web_tests
   python -m flask --app app.web:create_app run --no-debug

Visit http://127.0.0.1:5000/login after configuring SECRET_KEY and a hashed demo
account. The existing CLI remains python -m app.main. Do not run bare pytest for
an offline check: tests/ has a live schema guard and database-writing fixtures.

Security API references:
https://flask.palletsprojects.com/en/stable/web-security/
https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash


STEP 3: SHIPPER WORKFLOWS

After login as SHIPPER, open /shipper. All child routes require the SHIPPER role:
- /shipper/shipments: owner-only list, booking state, and an empty state.
- /shipper/shipments/new: create from an existing directed lane, weight, and date.
- /shipper/shipments/<id>: private details and scan history in scan_sequence order.
- /shipper/shipments/<id>/edit: update eligible logistics fields only.
- /shipper/shipments/<id>/book: eligible departures and procedure-backed booking.
- /shipper/reports: own ON_TIME/LATE counts and currently in-transit shipments.

Owner IDs always come from the signed session, never a form field. Private
shipment reads and writes constrain shipper_account_id. Missing and foreign
shipments return the same 404. All writes require CSRF tokens and successful
writes redirect with HTTP 303. Status/outcome, ownership, and shipment identity
are never writable through a form. No delete, cancellation, or rebooking route
exists. Steps 4 and 5 below document the carrier and read-only viewer workflows.

Validation and display:
- Positive DECIMAL(10,2) weight: 0.01 through 99999999.99 kg; no silent rounding,
  exponent notation, or non-finite values. Only existing ordered lanes are valid.
- Valid ISO calendar dates (YYYY-MM-DD), years 1000 through 9999. Historical dates
  are allowed because the specification does not require a future promise.
- Dates/times follow the project's America/New_York convention. No timezone
  conversion is applied to MariaDB DATE/DATETIME values.
- Eligible departures match both lane endpoints and have remaining weight >=
  shipment weight. Already-booked shipments have no new booking options. No
  additional future-departure restriction is invented; historical data is usable.
- In-transit reports include IN_TRANSIT, ARRIVED_AT_HUB, OUT_FOR_DELIVERY.
  RECEIVED and unscanned shipments appear in the full shipment list. Only
  delivered ON_TIME/LATE outcomes are counted in delivery summaries.

Transactions (see sql/schema_design_notes.md):
- Each operation opens/closes its own PyMySQL connection through app/db.py.
  Reads are ended with rollback. Create/update transactions set READ COMMITTED
  and strict SQL mode, explicitly commit on success, and rollback on failure.
- Updates initially read the owner-scoped booking. If booked, they lock departure
  before shipment. They re-read booking after locking and restart if it changed.
  They reject all logistics edits once any scan exists. Unbooked/unscanned
  shipments may change lane, weight, and promise. Booked/unscanned shipments may
  change promise and weight within capacity, but cannot change lane. Capacity is
  recomputed as SUM(booked weights) - old weight + new weight under both locks.
- Booking checks ownership on a dedicated connection, then rolls back that read
  transaction before CALL book_shipment(shipment_id, departure_id). The procedure
  owns its transaction. Python does not insert bookings or duplicate its atomic
  capacity logic. Ownership is immutable under the documented database policy.
  All CALL result sets are drained before the connection closes.
- Deadlocks/lock timeouts and update mapping races retry the entire operation
  at most three times with fresh connections. Business failures are not retried.
  Lost connections/unknown commit outcomes are never automatically retried.
  The UI asks users to inspect their shipment list before retrying a write;
  create requests do not have durable idempotency keys in the existing schema.
- Procedure messages are mapped to fixed user-facing feedback for duplicate,
  capacity, or lane failures. Raw driver messages, SQL, and credentials are not
  displayed or logged by the shipper handlers. Constraints return safe feedback.

Run the complete offline Flask suite (including Steps 1 and 2):

   python -m pytest web_tests -q
   python -m compileall -q app web_tests
   python -c "from app.web import create_app; import app.main; assert not create_app().debug"
   git diff --check

The scripted database tests check ownership parameters, lock order, commit and
rollback behavior, retry bounds, procedure invocation, form flows, and safe
errors. They do not prove MariaDB SQL execution or concurrent serialization.
Before the live demo, with approved disposable data and campus/VPN access, verify:
1. The deployed schema/procedure matches sql/01_schema.sql and the demo account
   has a compatible password hash and matching subtype.
2. Create, list, edit, track, book, and report for one shipper; attempt another
   shipper's IDs and confirm no data access or changes.
3. Exact-capacity and over-capacity bookings, duplicate and wrong-lane rejection,
   plus booked-weight edits at the capacity boundary.
4. Concurrent booking versus shipment update (including initially unbooked),
   competing booked-weight changes, and update versus first scan. Confirm the
   documented lock order, stable capacity, and no logistics edits after scans.
5. Real constraint/deadlock/timeout behavior, procedure result-set cleanup, and
   lost-connection handling. Do not automatically repeat an uncertain write.

No live database writes or concurrency tests were performed during Step 3
implementation. Existing database tests and their schema guard are unchanged.
Run them only under their documented approved database setup, not as offline
Flask tests. No SQL, diagrams, reports, analytics work, or CLI behavior changed.


STEP 4: CARRIER WORKFLOWS

app/carrier.py contains carrier routes and forms. app/carrier_service.py contains
owner-scoped SQL and transaction rules, reusing the shipper connection context.
app/templates/carrier/ contains the dashboard, forms, lists, history and reports.

Sign in with an existing CARRIER account using the same authentication setup.
- /carrier: own fleet, upcoming Eastern-time departures, and assigned shipments.
- /carrier/vehicles: own vehicles and Create/Edit links.
- /carrier/vehicles/new and /carrier/vehicles/<id>/edit: home hub plus subtype
  attributes. Creation atomically inserts vehicle and one chosen subtype.
  BOX_TRUCK uses cargo_volume and gross_weight_rating (DECIMAL(10,2));
  REFRIGERATED_VAN uses temperature_range (1-50 characters) and payload_limit
  (DECIMAL(10,2)); RAIL_CAR uses positive unsigned axle_count and track_gauge
  (DECIMAL(6,2)). Numeric values are positive and never silently rounded.
  Vehicle identity, carrier ownership and subtype are immutable. Base-only
  vehicles may update their home hub; inconsistent multi-subtype rows are rejected.
  Descriptive vehicle fields do not redefine departure capacity.
- /carrier/departures and its /new and /<id>/edit pages: own vehicles and directed
  lanes only. Updates lock the departure before aggregating booked weight.
  Capacity may increase or decrease down to the booked total. With bookings,
  vehicle, lane and time are immutable in both the form and service.
- /carrier/shipments: only shipments joined through booking -> departure ->
  the carrier's vehicle. /carrier/shipments/<id>/scans shows their history and
  accepts a single scan. Terminal delivered shipments display history only.
- /carrier/reports: own departure booked kg/capacity/utilization percentage and
  delivered-only on-time rate. No deliveries displays an explicit empty state.
  These are operational reports, separate from the six global analytical queries.

Every write uses CSRF, a dedicated strict READ COMMITTED transaction and explicit
commit. Failed operations roll back and close. Scans recheck ownership after a
separate SHIPMENT FOR UPDATE prelock, allocate MAX(scan_sequence)+1 while locked,
then INSERT one row. Existing triggers enforce chronology/transitions and update
shipment status/outcome. Python never writes those derived fields or bookings.
Only deadlocks/timeouts retry, at most three whole transactions with fresh
connections. Unknown commit/connection failures are not retried: inspect records
and history before repeating a write. Scan requests have no idempotency key.

Dates use America/New_York wall-clock time, year 1000-9999, optional whole seconds.
Historical dates are accepted. New ambiguous/skipped DST times and offsets are
rejected rather than silently converted. The deployed schema is assumed to match
sql/01_schema.sql; installed trigger behavior has not been verified by offline tests.

Offline validation (never run bare pytest against the database fixtures):
   python -m pytest web_tests -q -p no:cacheprovider
   python -m compileall -q app web_tests
   python -c "from app.web import create_app; import app.main; assert not create_app().debug"
   git diff --check
Local launch remains:
   python -m flask --app app.web:create_app run --no-debug

Offline tests use mocks/scripted cursors: they check authorization, ownership
parameters, subtype atomicity, update/scan lock ordering, rollback/retry behavior,
form rendering, navigation, CSRF and reporting. They do not prove MariaDB SQL or
trigger execution or concurrent serialization. On campus/VPN with approved demo
accounts/data, verify subtype writes, capacity update versus booking, scan versus
scan, scan versus shipment update, and cross-carrier rejection before the demo.
Viewer, global analytics, SQL/schema changes and CLI changes are outside Step 4.


STEP 5: READ-ONLY VIEWER

The final specification (Viewer Functions, page 4) permits shipment-ID tracking
and published performance summaries such as on-time rates by lane or carrier.
It specifies no viewer ownership filter or additional search fields. Viewers may
therefore look up any existing shipment by ID, with strict VIEWER role access.

- /viewer: concise total, in-transit and delivered shipment counts and lookup.
- /viewer/track?shipment_id=<id>: origin/destination, current status, promise,
  outcome, optional departure/vehicle/time and scan history in scan_sequence order.
  IDs must be positive unsigned INT values. Invalid IDs get 400, absent records
  get 404, and unbooked/unscanned shipments have explicit empty states.
- /viewer/reports: all-time delivered-only on-time counts/rates by directed lane
  and carrier, computed from existing shipment outcomes. Undelivered shipments
  are excluded. A zero denominator displays No deliveries yet, not a zero rate.
  These published summaries do not implement the six global analytical queries.

app/viewer.py owns GET-only routes and generic error handling;
app/viewer_service.py executes only SELECT statements using the existing
connection context, which rolls back read transactions and closes connections.
No commits, locking reads, booking calls, or data-changing SQL are exposed.
No passwords or shipper account identifiers are selected for shipment tracking.
Viewer access to shipper/carrier management routes remains forbidden.
The standard POST logout remains available and retains its CSRF protection.

web_tests/test_viewer.py covers role guards, parameterized lookup, found/missing
shipments, ordered and empty history, read-only methods and SQL, cross-role write
rejection, generic errors, template navigation and empty report states. These are
offline mocked tests; they do not establish live MariaDB query/aggregate behavior.
Use the same documented web_tests, compileall, import and diff checks and launch
command above. Real authenticated viewing needs university database access and a
valid provisioned VIEWER account. No authentication workaround is supplied.


INTEGRATED VERIFICATION AND SAFETY

Use Python 3.10+ and the existing virtual environment. Install both runtime and
test dependencies with .venv/bin/python -m pip install -r requirements-dev.txt.
Flask 3.1 requires Werkzeug 3.1 or later; both are bounded below version 4.
Analytics offline checks use the standard-library unittest and sqlite3 modules.

Run the two offline suites explicitly (no VPN or live database required):

    .venv/bin/python -m pytest web_tests -q -p no:cacheprovider
    .venv/bin/python -m unittest analytics_checks.test_offline -v
    .venv/bin/python -m pip check
    .venv/bin/python -m compileall -q app web_tests analytics_checks test_queries.py
    git diff --check

Flask tests use mocks/scripted cursors. Analytics offline tests use SQLite as an
SQL oracle plus mocks; neither proves MariaDB compatibility or concurrency.
Previously confirmed live: database connectivity and owner-performed logins for
540001 SHIPPER, 540002 CARRIER and 540003 VIEWER. This merge resolution does not
load seed data, run live database tests or validate analytics against dkhando.
The incoming analytics result files are historical evidence from sachith, with
a recorded Q3 failure; they are not proof of a successful corrected dkhando run.

Sanjana's functional/concurrency tests are write-capable and guarded to sshett24.
Only with separate approval and that schema's approved disposable fixtures:

    .venv/bin/python -m pytest tests/test_database_rules.py tests/test_concurrency.py -q

Do not point those tests at dkhando or weaken their schema guard. Do not use bare
pytest. Live read-only analytics commands and exact-target guards are below.

Configuration: app/db.py loads root .env with override=False and interpolate=False.
DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD are required for database access.
SECRET_KEY must be random and at least 32 characters for login. APP_ENV=production
is only for HTTPS deployments; local Flask uses APP_ENV=development and --no-debug.
Analytics validation reads ANALYTICS_TEST_SCHEMA, ANALYTICS_TEST_MODE (isolated
or combined), and ANALYTICS_ALLOW_COMBINED. Set these explicitly for each live
validation command; leaving the schema/combined opt-in empty intentionally blocks
accidental execution. They do not grant permission for a seed load or bootstrap.

Professor/project requirements remain in docs/CSC540-Logistics-Project-Final-Version.docx.pdf.
Use the departmental MariaDB 10.5 server from campus or campus VPN, raw SQL and
no ORM. Preserve the final ER model and canonical one-procedure/two-trigger schema.
Submission includes the revised ER model, three SQL files (schema, sample data,
queries), executable/source code, README with team names/setup instructions, and
the report on functional dependencies, normalization and constraint enforcement.
Use the professor's naming convention and current course demo/submission schedule.

SIX GLOBAL ANALYTICAL QUERIES (CANONICAL ORDER)

1. Vehicle counts by subtype for each carrier, including carriers with no vehicles.
2. Departure weight utilization ranked within each directed lane.
3. Elapsed time between consecutive scans for a selected shipment ID.
4. Running delivered shipment weight by carrier over time.
5. Departures serving at least two distinct shippers, including their counts.
6. Shipments with no scans, including owner, route and promised date.

Implementations: app/queries.py and sql/03_queries.sql. The Flask View Queries
interface reuses these six Python functions without duplicating their SQL.
Existing carrier/viewer operational reports remain separate from these queries.

ANALYTICS INTEGRATION

Preserved integration preparation from origin/main (devansh-analytics-fix).

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

STEP 6: FLASK VIEW QUERIES

All authenticated SHIPPER, CARRIER and VIEWER accounts can open /queries from
the navigation. The six reports appear in the professor's required order above.
Each /queries/1 through /queries/6 page executes only its selected report. Query 3
first displays a form; submit a shipment ID from 1 to 4294967295 to see scans
and elapsed minutes. Missing scans do not imply that the shipment exists.

app/analytics_service.py uses the shared connection helper, a MariaDB READ ONLY
snapshot transaction, and the existing SELECT-only analytics adapter. Connections
are rolled back and closed on success or failure. Routes accept GET/HEAD only;
there are no analytics write actions. Session expiry, CSRF and login throttling
remain unchanged. Database errors show a generic message. Decimal precision is
preserved, output is escaped, and wide tables scroll inside a focusable region.

Run offline verification with:
    .venv/bin/python -m pytest web_tests -q -p no:cacheprovider
    .venv/bin/python -m unittest analytics_checks.test_offline -v
    .venv/bin/python -m compileall -q app web_tests analytics_checks
    .venv/bin/python -m pip check

Web tests use mocked connections; analytics offline checks use SQLite, not live
MariaDB. Neither proves populated results against the university database. The
final freight sample load remains pending; empty results are expected except
Query 1, which includes existing carriers with zero vehicle counts. Do not run
seed loaders or write-capable database tests as part of this verification.
