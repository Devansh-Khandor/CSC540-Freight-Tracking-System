"""Authentication and role authorization without database writes."""

import secrets
import threading
import time
from functools import wraps

from flask import (Blueprint, abort, current_app, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from app import db

bp = Blueprint("auth", __name__)
ROLES = ("SHIPPER", "CARRIER", "VIEWER")
HASH_METHOD = "scrypt:32768:8:1"
# Unknown accounts still perform a password hash check.
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32), method=HASH_METHOD)
ACCOUNT_SQL = """
SELECT a.account_id, a.password, a.role,
       EXISTS(SELECT 1 FROM shipper s WHERE s.account_id = a.account_id),
       EXISTS(SELECT 1 FROM carrier c WHERE c.account_id = a.account_id),
       EXISTS(SELECT 1 FROM viewer v WHERE v.account_id = a.account_id)
FROM account a WHERE a.account_id = %s
"""


class LoginLimiter:
    """Bounded, thread-safe, per-process fixed-window attempt limiter."""

    def __init__(self):
        self.entries = {}
        self.lock = threading.Lock()

    def allow(self, address, account_id):
        now = time.monotonic()
        keys = (("ip", address), ("account", account_id))
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if v[1] > now}
            if any(self.entries.get(k, (0, 0))[0] >= 10 for k in keys):
                return False
            if len(self.entries) + sum(k not in self.entries for k in keys) > 10000:
                return False  # Fail closed rather than evict active limits.
            for key in keys:
                count, until = self.entries.get(key, (0, now + 300))
                self.entries[key] = (count + 1, until)
            return True


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def auth_ready():
    key = current_app.secret_key
    return isinstance(key, (str, bytes)) and len(key) >= 32


def init_auth(app):
    app.extensions["login_limiter"] = LoginLimiter()
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.register_blueprint(bp)

    @app.before_request
    def session_and_csrf_guard():
        if "account_id" in session:
            expires = session.get("expires_at", 0)
            if (not isinstance(expires, (int, float)) or time.time() >= expires
                    or session.get("role") not in ROLES or not auth_ready()):
                session.clear()
        if request.blueprint == "auth" and not auth_ready():
            return render_template("error.html", code=503,
                                   heading="Sign-in unavailable",
                                   message="Sign-in is temporarily unavailable. Please try again later."), 503
        # Protect every state-changing form, including future routes.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url_rule:
            expected = session.get("csrf_token")
            supplied = request.form.get("csrf_token", "")
            if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
                abort(400)

    @app.after_request
    def private_responses(response):
        if request.blueprint == "auth" or session.get("account_id"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


def role_required(role):
    def decorate(view):
        @wraps(view)
        def protected(*args, **kwargs):
            if not session.get("account_id"):
                return redirect(url_for("auth.login"))
            if session.get("role") != role:
                abort(403)
            return view(*args, **kwargs)
        return protected
    return decorate


def valid_identity(row):
    return (row is not None and row[2] in ROLES
            and tuple(bool(value) for value in row[3:6])
            == tuple(row[2] == role for role in ROLES))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("account_id"):
        return redirect(url_for("auth." + session["role"].lower()))
    error = None
    status = 200
    if request.method == "POST":
        raw_id = request.form.get("account_id", "")
        account_id = int(raw_id) if raw_id.isascii() and raw_id.isdigit() and len(raw_id) <= 10 else 0
        if not 1 <= account_id <= 4294967295:
            account_id = 0
        if not current_app.extensions["login_limiter"].allow(request.remote_addr, account_id):
            return render_template("login.html", error="Too many sign-in attempts. Please try again in five minutes.", roles=ROLES), 429, {"Retry-After": "300"}
        password = request.form.get("password", "")
        selected_role = request.form.get("role", "")
        try:
            with db.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(ACCOUNT_SQL, (account_id,))
                    row = cursor.fetchone()
        except Exception:
            # Never log driver messages, account details, or form contents.
            return render_template("login.html", error="Sign-in is temporarily unavailable. Please try again later.", roles=ROLES), 503
        stored = row[1] if row else ""
        supported = isinstance(stored, str) and stored.startswith(HASH_METHOD + "$")
        try:
            matched = check_password_hash(stored if supported else DUMMY_HASH, password[:1024])
        except (ValueError, TypeError):
            matched = False
        if (matched and supported and 1 <= len(password) <= 1024
                and valid_identity(row) and row[2] == selected_role):
            session.clear()
            session.permanent = True
            session.update(account_id=row[0], role=row[2],
                           expires_at=time.time() + current_app.permanent_session_lifetime.total_seconds())
            csrf_token()  # Rotate the anonymous token after authentication.
            return redirect(url_for("auth." + row[2].lower()))
        error, status = "Invalid account ID, password, or role.", 401
    return render_template("login.html", error=error, roles=ROLES), status


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@bp.get("/shipper")
@role_required("SHIPPER")
def shipper():
    return render_template("dashboard.html", role="Shipper")


@bp.get("/carrier")
@role_required("CARRIER")
def carrier():
    return render_template("dashboard.html", role="Carrier")


@bp.get("/viewer")
@role_required("VIEWER")
def viewer():
    return render_template("dashboard.html", role="Viewer")
