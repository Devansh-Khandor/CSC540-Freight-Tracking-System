CSC 540 - Freight Tracking and Delivery Management
NC State University

Task 1: Python project foundation

Uses Python 3 (3.10 or newer recommended), PyMySQL, and raw SQL against the
departmental MariaDB 10.5 server. SSL is explicitly disabled per the professor's
instructions. There is no ORM, business logic, or menu workflow yet.
The only application query is SELECT VERSION(). No databases, tables, triggers,
or stored procedures are created. Use your existing assigned schema; CREATE
DATABASE permission is neither assumed nor required.

FILES AND DIRECTORIES

app/__init__.py   Marks app as a Python package.
app/db.py         Loads configuration, validates required values and the port,
                  and opens a PyMySQL connection with SSL disabled and timeouts.
app/main.py       CLI connectivity test; prints the server version only after
                  SELECT VERSION() succeeds, and closes cursor and connection.
requirements.txt Runtime dependencies: PyMySQL and python-dotenv.
.env.example     Configuration template with no real credentials or schema name.
.gitignore       Excludes local credentials, virtual environments, caches, and
                  generated output. It keeps .env.example tracked.
README.txt       This setup and usage guide.
sql/             Reserved for future raw SQL scripts; currently empty.
tests/           Reserved for future automated tests; currently empty.
diagrams/        Reserved for authored database/project diagrams.
report/          Reserved for authored project reports.
Each reserved directory contains a .gitkeep so Git can retain the directory.
Place disposable generated output in a generated/ directory.

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
