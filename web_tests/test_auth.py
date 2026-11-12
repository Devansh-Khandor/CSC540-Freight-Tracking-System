"""Offline authentication checks; never load credentials or contact MariaDB."""
from datetime import timedelta
from unittest.mock import MagicMock

import pymysql
import pytest
from werkzeug.security import generate_password_hash

from app import auth, db, web, carrier_service

PASSWORD = "test-only-password"
HASH = generate_password_hash(PASSWORD, method=auth.HASH_METHOD)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(web, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(db, "get_connection", MagicMock(side_effect=AssertionError("No live DB")))
    return web.create_app({"TESTING": True, "SECRET_KEY": "test-only-secret-" * 3,
                           "SESSION_COOKIE_SECURE": False})


@pytest.fixture
def client(app):
    return app.test_client()


def install_account(monkeypatch, role="SHIPPER", row="default"):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ((7, HASH, role, *(int(role == r) for r in auth.ROLES))
                                    if row == "default" else row)
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(db, "get_connection", factory)
    return factory, connection, cursor


def token(client):
    assert client.get("/login").status_code == 200
    with client.session_transaction() as session:
        return session["csrf_token"]


def login(client, role="SHIPPER", password=PASSWORD, account_id="7", csrf=None):
    return client.post("/login", data={"account_id": account_id, "password": password,
                                       "role": role, "csrf_token": csrf or token(client)})


@pytest.mark.parametrize("role", auth.ROLES)
def test_login_role_and_minimal_session(client, monkeypatch, role):
    # The carrier dashboard now reads operational data. Keep this auth test's
    # database assertions focused on the account lookup, not dashboard queries.
    monkeypatch.setattr(carrier_service, "dashboard", lambda owner: {"vehicles": [], "departures": [], "shipments": []})
    factory, connection, cursor = install_account(monkeypatch, role)
    old_token = token(client)
    response = login(client, role, csrf=old_token)
    assert response.status_code == 302
    assert response.location == "/" + role.lower()
    with client.session_transaction() as session:
        assert session["account_id"] == 7
        assert session["role"] == role
        assert session["csrf_token"] != old_token
        assert set(session) == {"account_id", "role", "csrf_token", "_permanent", "expires_at"}
        assert PASSWORD not in str(dict(session)) and HASH not in str(dict(session))
    assert client.get(response.location).status_code == 200
    factory.assert_called_once_with()
    cursor.execute.assert_called_once_with(auth.ACCOUNT_SQL, (7,))
    connection.__exit__.assert_called_once()
    connection.cursor.return_value.__exit__.assert_called_once()
    connection.commit.assert_not_called()
    for other in set(auth.ROLES) - {role}:
        assert client.get("/" + other.lower()).status_code == 403
    assert client.get("/login").location == response.location
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert "Secure;" not in response.headers["Set-Cookie"]
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("row,password,role", [
    (None, PASSWORD, "SHIPPER"),
    ((7, HASH, "SHIPPER", 1, 0, 0), "wrong", "SHIPPER"),
    ((7, PASSWORD, "SHIPPER", 1, 0, 0), PASSWORD, "SHIPPER"),
    ((7, "scrypt:32768:8:1$broken", "SHIPPER", 1, 0, 0), PASSWORD, "SHIPPER"),
    ((7, HASH, "SHIPPER", 0, 0, 0), PASSWORD, "SHIPPER"),
    ((7, HASH, "SHIPPER", 0, 1, 0), PASSWORD, "SHIPPER"),
    ((7, HASH, "SHIPPER", 1, 1, 0), PASSWORD, "SHIPPER"),
    ((7, HASH, "ADMIN", 1, 0, 0), PASSWORD, "SHIPPER"),
    ((7, HASH, "SHIPPER", 1, 0, 0), PASSWORD, "CARRIER"),
    ((7, HASH, "shipper", 1, 0, 0), PASSWORD, "SHIPPER"),
])
def test_invalid_identity_generic(client, monkeypatch, row, password, role, caplog):
    install_account(monkeypatch, row=row)
    response = login(client, password=password, role=role)
    assert response.status_code == 401
    assert b"Invalid account ID, password, or role." in response.data
    assert PASSWORD not in response.get_data(as_text=True)
    assert HASH not in response.get_data(as_text=True)
    assert PASSWORD not in caplog.text
    with client.session_transaction() as session:
        assert "account_id" not in session


@pytest.mark.parametrize("role", auth.ROLES)
def test_unauthenticated_dashboard(client, role):
    response = client.get("/" + role.lower())
    assert response.status_code == 302 and response.location == "/login"


def test_logout_and_csrf_rotation(client, monkeypatch):
    install_account(monkeypatch)
    anonymous_token = token(client)
    login(client, csrf=anonymous_token)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400
    assert client.post("/logout", data={"csrf_token": anonymous_token}).status_code == 400
    assert client.get("/shipper").status_code == 200
    with client.session_transaction() as session:
        current = session["csrf_token"]
    response = client.post("/logout", data={"csrf_token": current})
    assert response.status_code == 302 and response.location == "/"
    with client.session_transaction() as session:
        assert not session
    assert client.get("/shipper").location == "/login"


@pytest.mark.parametrize("value", ["", "wrong", "☃"])
def test_csrf_rejection_before_database(client, monkeypatch, value):
    factory, _, _ = install_account(monkeypatch)
    token(client)
    assert client.post("/login", data={"csrf_token": value}).status_code == 400
    factory.assert_not_called()


def test_cross_client_token_rejected(app, client):
    stolen = token(client)
    other = app.test_client()
    token(other)
    assert other.post("/login", data={"csrf_token": stolen}).status_code == 400


def test_expiry_absolute_even_after_cookie_update(client, monkeypatch):
    install_account(monkeypatch)
    login(client)
    with client.session_transaction() as session:
        expiry = session["expires_at"]
    monkeypatch.setattr(auth.time, "time", lambda: expiry + 1)
    assert client.get("/shipper").location == "/login"
    with client.session_transaction() as session:
        assert "account_id" not in session


def test_tampered_cookie_rejected(app, client, monkeypatch):
    install_account(monkeypatch)
    login(client)
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"]).value
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], "tampered" + cookie)
    assert client.get("/shipper").location == "/login"


def test_cookie_configuration(monkeypatch):
    monkeypatch.setattr(web, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret-" * 3)
    app = web.create_app({"TESTING": True})
    assert app.config["SESSION_COOKIE_SECURE"]
    assert app.config["SESSION_COOKIE_HTTPONLY"]
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.permanent_session_lifetime == timedelta(minutes=30)
    assert not app.config["SESSION_REFRESH_EACH_REQUEST"]
    response = app.test_client().get("/login", base_url="https://localhost")
    assert "Secure;" in response.headers["Set-Cookie"]


@pytest.mark.parametrize("secret", [None, "", "short"])
def test_missing_secret_fails_closed(app, secret):
    app.config["SECRET_KEY"] = secret
    client = app.test_client()
    assert client.get("/").status_code == 200
    for path in ("/login", "/shipper", "/carrier", "/viewer"):
        assert client.get(path).status_code == 503
    assert client.post("/logout").status_code == 503


def test_limiter_cannot_be_bypassed_with_new_cookies_or_forwarded_ip(app, client, monkeypatch):
    factory, _, _ = install_account(monkeypatch, row=None)
    csrf = token(client)
    for _ in range(10):
        assert login(client, csrf=csrf).status_code == 401
    other = app.test_client()
    response = other.post("/login", data={"account_id": "7", "password": PASSWORD,
                                          "role": "SHIPPER", "csrf_token": token(other)},
                          headers={"X-Forwarded-For": "203.0.113.42"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "300"
    assert factory.call_count == 10


def test_limiter_account_and_expiration(monkeypatch):
    limiter = auth.LoginLimiter()
    monkeypatch.setattr(auth.time, "monotonic", lambda: 100)
    for i in range(10):
        assert limiter.allow(str(i), 7)
    assert not limiter.allow("new-address", 7)
    monkeypatch.setattr(auth.time, "monotonic", lambda: 401)
    assert limiter.allow("new-address", 7)


def test_database_failure_generic(client, monkeypatch, caplog):
    monkeypatch.setattr(db, "get_connection", MagicMock(side_effect=pymysql.OperationalError(1045, "sensitive-db-details")))
    response = login(client)
    assert response.status_code == 503
    assert b"sensitive-db-details" not in response.data
    assert "sensitive-db-details" not in caplog.text


def test_query_failure_closes_connection(client, monkeypatch):
    _, connection, cursor = install_account(monkeypatch)
    cursor.execute.side_effect = pymysql.OperationalError(2013, "private")
    assert login(client).status_code == 503
    connection.__exit__.assert_called_once()
    connection.cursor.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("value", ["1 OR 1=1", "-1", "4294967296", "９", "1" * 100])
def test_invalid_account_input_is_parameterized(client, monkeypatch, value):
    _, _, cursor = install_account(monkeypatch, row=None)
    assert login(client, account_id=value).status_code == 401
    cursor.execute.assert_called_once_with(auth.ACCOUNT_SQL, (0,))


def test_csrf_applies_to_future_state_changing_routes(app):
    @app.post("/future")
    def future():
        return "Changed"
    assert app.test_client().post("/future").status_code == 400


def test_absolute_expiry_survives_fresh_cookie_signature(client, monkeypatch):
    install_account(monkeypatch)
    login(client)
    with client.session_transaction() as session:
        session["expires_at"] = 1
    assert client.get("/shipper").location == "/login"


def test_each_login_attempt_opens_its_own_connection(client, monkeypatch):
    factory, connection, _ = install_account(monkeypatch, row=None)
    csrf = token(client)
    login(client, csrf=csrf)
    login(client, csrf=csrf)
    assert factory.call_count == 2
    assert connection.__exit__.call_count == 2
