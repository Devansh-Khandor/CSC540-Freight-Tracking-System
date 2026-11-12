CSC 540 - Freight Tracking and Delivery Management
NC State University

Steps 1 and 2: Flask foundation and authentication

Uses Python 3 (3.10 or newer recommended), PyMySQL, and raw SQL against the
departmental MariaDB 10.5 server. SSL is explicitly disabled per the professor's
instructions. There is no ORM; operational business workflows are not implemented yet.
The CLI uses SELECT VERSION(); the web diagnostic uses SELECT 1. Authentication
also reads account and subtype records. No web route creates
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
app/templates/   Shared Jinja2 layout, homepage, status, and error pages.
app/static/      Responsive CSS; no frontend framework or CDN required.
web_tests/       Offline Flask smoke tests, separate from database fixtures.
requirements.txt Runtime dependencies: PyMySQL, python-dotenv, and Flask.
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
Operational workflows and Analytics remain planned.
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
Authentication is implemented in Step 2 below; no database-write web routes or
analytics are implemented.
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
are rejected with the same message as incorrect credentials. No registration,
shipment CRUD, booking, scanning, or analytical execution is implemented.

/shipper, /carrier, and /viewer are protected dashboard placeholders. Anonymous
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
reuse those accounts. No usable hashed seed account was found in this checkout;
Sachith's unmerged sample data has not been assumed or changed.

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
