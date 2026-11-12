"""Offline tests, isolated from tests/conftest.py's live database guard."""

from unittest.mock import MagicMock

import pymysql
import pytest

from app import db, web


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Never load local credentials or attempt a real connection in this suite.
    monkeypatch.setattr(web, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    connection = MagicMock(side_effect=AssertionError("Live DB access forbidden"))
    monkeypatch.setattr(db, "get_connection", connection)
    return connection


@pytest.fixture
def app():
    return web.create_app({"TESTING": True})


def test_home_and_assets_work_without_configuration(app, isolated_environment):
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Freight Tracking and Delivery Management System" in html
    assert 'name="viewport"' in html
    for label in ("Login", "Shipper", "Carrier", "Viewer", "Analytics"):
        assert f'{label} <small>Planned</small>' in html
        assert client.get("/" + label.lower()).status_code == 404
    assert client.get("/static/css/style.css").status_code == 200
    assert not app.debug
    assert app.secret_key is None
    assert "Set-Cookie" not in response.headers
    isolated_environment.assert_not_called()


def test_secret_comes_from_environment(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-only-value")
    monkeypatch.setenv("FLASK_DEBUG", "1")
    app = web.create_app()
    assert app.secret_key == "test-only-value"
    assert not app.debug
    assert "test-only-value" not in app.test_client().get("/").get_data(as_text=True)


def fake_connection(monkeypatch, row=(1,)):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    monkeypatch.setattr(db, "get_connection", lambda: connection)
    return connection, cursor


def test_status_connected_closes_resources_and_only_selects_constant(app, monkeypatch):
    connection, cursor = fake_connection(monkeypatch)
    response = app.test_client().get("/status")
    assert response.status_code == 200
    assert b"Connected" in response.data
    assert response.headers["Cache-Control"] == "no-store"
    cursor.execute.assert_called_once_with("SELECT 1")
    connection.cursor.return_value.__exit__.assert_called_once()
    connection.__exit__.assert_called_once()
    connection.commit.assert_not_called()


@pytest.mark.parametrize("error", [
    db.ConfigurationError("private-config-details"),
    pymysql.OperationalError(1045, "private-config-details"),
    OSError("private-config-details"),
])
def test_status_failure_is_generic(app, monkeypatch, error, caplog):
    monkeypatch.setattr(db, "get_connection", MagicMock(side_effect=error))
    response = app.test_client().get("/status")
    assert response.status_code == 503
    assert b"Unavailable" in response.data
    assert b"private-config-details" not in response.data
    assert "private-config-details" not in caplog.text
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("stage", ["execute", "fetchone", "cursor_close", "connection_close"])
def test_status_query_and_cleanup_failures_are_safe(app, monkeypatch, stage):
    connection, cursor = fake_connection(monkeypatch)
    target = {"execute": cursor.execute, "fetchone": cursor.fetchone,
              "cursor_close": connection.cursor.return_value.__exit__,
              "connection_close": connection.__exit__}[stage]
    target.side_effect = pymysql.OperationalError(2013, "private-query-details")
    response = app.test_client().get("/status")
    assert response.status_code == 503
    assert b"private-query-details" not in response.data
    connection.__exit__.assert_called_once()


@pytest.mark.parametrize("row", [None, (0,), ("server-metadata",)])
def test_status_requires_expected_result(app, monkeypatch, row):
    fake_connection(monkeypatch, row)
    response = app.test_client().get("/status")
    assert response.status_code == 503
    assert b"server-metadata" not in response.data


def test_friendly_error_pages(app):
    @app.get("/test-error")
    def fail():
        raise RuntimeError("internal-error-details")

    app.config["PROPAGATE_EXCEPTIONS"] = False
    client = app.test_client()
    missing = client.get("/unknown")
    assert missing.status_code == 404
    assert b"Page not found" in missing.data
    failed = client.get("/test-error")
    assert failed.status_code == 500
    assert b"Something went wrong" in failed.data
    assert b"internal-error-details" not in failed.data
    assert b"Traceback" not in failed.data


def test_no_write_routes(app, isolated_environment):
    for path in ("/", "/status"):
        assert app.test_client().post(path).status_code == 405
    isolated_environment.assert_not_called()
    for rule in app.url_map.iter_rules():
        assert rule.methods <= {"GET", "HEAD", "OPTIONS"}
