CSC 540 - Freight Tracking and Delivery Management
NC State University

Step 1: Python and Flask application foundation

Uses Python 3 (3.10 or newer recommended), PyMySQL, and raw SQL against the
departmental MariaDB 10.5 server. SSL is explicitly disabled per the professor's
instructions. There is no ORM or web business workflow yet.
The CLI uses SELECT VERSION(); the web diagnostic uses SELECT 1. Neither creates
databases, tables, triggers, or procedures. Use your existing assigned schema; CREATE
DATABASE permission is neither assumed nor required.

FILES AND DIRECTORIES

app/__init__.py   Marks app as a Python package.
app/db.py         Loads configuration, validates required values and the port,
                  and opens a PyMySQL connection with SSL disabled and timeouts.
app/main.py       CLI connectivity test; prints the server version only after
                  SELECT VERSION() succeeds, and closes cursor and connection.
app/web.py       Flask application factory, homepage, status and error handlers.
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
The homepage loads without database access. Login, Shipper, Carrier, Viewer,
and Analytics are visibly marked Planned and have no active workflow routes.
The Connection status link opens /status and runs only SELECT 1 using app/db.py.
It returns Connected (HTTP 200) or Unavailable (HTTP 503), with no credentials,
schema metadata, server version, or database exception details. Results are not
cached. Connections and cursors close after the check, including query failures.
The existing 10-second connection/read/write timeouts apply, so an unavailable
server can delay this diagnostic. The homepage and error pages do not query it.

Set SECRET_KEY in your ignored local .env or exported environment. To generate
a value locally, run this command and copy its output into .env (do not commit it):

   python -c "import secrets; print(secrets.token_hex(32))"

No secret is generated or hardcoded by the app. With SECRET_KEY missing or empty,
this read-only foundation still starts; signed sessions are unavailable. Configure
a key before adding session-dependent features in a later stage. Debug defaults
to disabled, and the documented --no-debug flag also overrides FLASK_DEBUG.
No authentication, password handling, database writes, or analytics are implemented.
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
