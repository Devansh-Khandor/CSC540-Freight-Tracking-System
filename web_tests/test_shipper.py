"""Offline shipper authorization, forms, SQL, and transaction tests."""
from datetime import date
from decimal import Decimal as D
from html.parser import HTMLParser
import time
from unittest.mock import MagicMock

import pymysql
import pytest

from app import db, shipper_service as service, web

FORM = {"lane": "1:2", "weight_kg": "25.50", "promised_delivery_date": "2030-02-28"}
SHIPMENT = dict(shipment_id=41, origin_hub_id=1, destination_hub_id=2,
                origin_region="Northeast", destination_region="West", weight_kg=D("25.50"),
                promised_delivery_date=date(2030, 2, 28), current_status=None,
                delivery_outcome=None, departure_id=None)
LANES = [dict(origin_hub_id=1, destination_hub_id=2, origin_region="Northeast", destination_region="West")]
PATHS = ["/shipper", "/shipper/shipments", "/shipper/shipments/new",
         "/shipper/shipments/41", "/shipper/shipments/41/edit",
         "/shipper/shipments/41/book", "/shipper/reports"]
WRITES = ["/shipper/shipments/new", "/shipper/shipments/41/edit", "/shipper/shipments/41/book"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(web, "load_dotenv", lambda *a, **k: None)
    blocked = MagicMock(side_effect=AssertionError("Live database forbidden"))
    monkeypatch.setattr(db, "get_connection", blocked)
    return blocked


@pytest.fixture
def app():
    return web.create_app({"TESTING": True, "SECRET_KEY": "test-only-secret" * 3,
                           "SESSION_COOKIE_SECURE": False})


def sign_in(client, role="SHIPPER"):
    with client.session_transaction() as session:
        session.update(account_id=7, role=role, csrf_token="test-csrf",
                       expires_at=time.time() + 1800, _permanent=True)


@pytest.fixture
def client(app):
    client = app.test_client()
    sign_in(client)
    return client


class ScriptedConnection:
    """Fail immediately on unexpected SQL; record actual transaction ordering."""
    def __init__(self, steps):
        self.steps = list(steps)
        self.events = []
        self.result = None
        self.lastrowid = 41

    def cursor(self, cursorclass):
        assert cursorclass is pymysql.cursors.DictCursor
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.events.append("cursor-close")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.events.append((normalized, params))
        if normalized.startswith("SET SESSION"):
            return
        assert self.steps, f"Unexpected query: {normalized}"
        expected, expected_params, result = self.steps.pop(0)
        assert expected in normalized
        assert params == expected_params
        if isinstance(result, Exception):
            raise result
        self.result = result

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def nextset(self):
        self.events.append("nextset")
        return None

    def begin(self):
        self.events.append("begin")

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")
        assert not self.steps, f"Unexecuted queries: {self.steps}"


def connect(monkeypatch, *scripts):
    connections = [ScriptedConnection(script) for script in scripts]
    factory = MagicMock(side_effect=connections)
    monkeypatch.setattr(db, "get_connection", factory)
    return connections, factory


def owned(row=SHIPMENT):
    return ("AND s.shipment_id = %s", (7, 41), row)


def booking(departure_id=None):
    return ("LEFT JOIN booking", (41, 7), {"shipment_id": 41, "departure_id": departure_id})


def locked():
    return ("shipper_account_id = %s FOR UPDATE", (41, 7), SHIPMENT)


def scan(row=None):
    return ("JOIN shipment s ON s.shipment_id = e.shipment_id", (41, 7), row)


def lane(row=LANES[0]):
    return ("SELECT origin_hub_id FROM lane", (1, 2), row)


def update(weight=D("25.50")):
    return ("UPDATE shipment SET origin_hub_id", (1, 2, weight, date(2030, 2, 28), 41, 7), None)


@pytest.mark.parametrize("path", PATHS)
def test_unauthenticated(app, path, offline):
    response = app.test_client().get(path)
    assert response.status_code == 302 and response.location == "/login"
    offline.assert_not_called()


@pytest.mark.parametrize("role", ["CARRIER", "VIEWER"])
@pytest.mark.parametrize("path", PATHS)
def test_wrong_role(app, role, path, offline):
    client = app.test_client()
    sign_in(client, role)
    assert client.get(path).status_code == 403
    offline.assert_not_called()


@pytest.mark.parametrize("path", WRITES)
def test_csrf_required(client, path, offline):
    assert client.post(path, data=FORM).status_code == 400
    assert client.post(path, data={**FORM, "csrf_token": "wrong"}).status_code == 400
    offline.assert_not_called()


@pytest.mark.parametrize("role", ["CARRIER", "VIEWER"])
@pytest.mark.parametrize("path", WRITES)
def test_wrong_role_post_even_with_csrf(app, role, path, offline):
    client = app.test_client()
    sign_in(client, role)
    assert client.post(path, data={**FORM, "csrf_token": "test-csrf"}).status_code == 403
    offline.assert_not_called()


@pytest.mark.parametrize("path", WRITES)
def test_anonymous_post_with_valid_anonymous_csrf(app, path, offline):
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as session:
        csrf = session["csrf_token"]
    assert client.post(path, data={**FORM, "csrf_token": csrf}).location == "/login"
    offline.assert_not_called()


def test_list_only_owner_and_empty_state(client, monkeypatch):
    connections, _ = connect(monkeypatch, [("WHERE s.shipper_account_id = %s", (7,), [])])
    response = client.get("/shipper/shipments")
    assert response.status_code == 200 and b"No shipments to display" in response.data
    assert connections[0].events[-2:] == ["rollback", "close"]


def test_list_displays_required_fields(client, monkeypatch):
    connect(monkeypatch, [("WHERE s.shipper_account_id = %s", (7,), [SHIPMENT])])
    response = client.get("/shipper/shipments")
    for value in (b"#41", b"25.50", b"Northeast", b"West", b"2030-02-28", b"Not booked", b"Not yet scanned", b"Not delivered"):
        assert value in response.data


@pytest.mark.parametrize("path,method", [
    ("/shipper/shipments/41", "get"),
    ("/shipper/shipments/41/edit", "get"), ("/shipper/shipments/41/edit", "post"),
    ("/shipper/shipments/41/book", "get"), ("/shipper/shipments/41/book", "post"),
])
def test_foreign_or_missing_shipment_hidden(client, monkeypatch, path, method):
    connect(monkeypatch, [owned(None)])
    response = getattr(client, method)(path, data={**FORM, "csrf_token": "test-csrf", "departure_id": "9"})
    assert response.status_code == 404
    assert b"Shipment not found" in response.data


def test_tracking_order_and_ownership(client, monkeypatch):
    scans = [dict(scan_sequence=i, scan_timestamp=f"2030-02-20 10:0{i}:00", status=status, hub_id=1, region="Northeast")
             for i, status in [(1, "RECEIVED"), (2, "IN_TRANSIT")]]
    connect(monkeypatch, [owned({**SHIPMENT, "current_status": "IN_TRANSIT"}),
                         ("ORDER BY e.scan_sequence ASC", (41, 7), scans)])
    response = client.get("/shipper/shipments/41")
    assert response.status_code == 200
    assert response.data.index(b"10:01:00") < response.data.index(b"10:02:00")
    assert b"Update shipment</a>" not in response.data
    assert b"RECEIVED" in response.data


def test_no_scan_empty_state(client, monkeypatch):
    connect(monkeypatch, [owned(), ("ORDER BY e.scan_sequence ASC", (41, 7), [])])
    assert b"No scan events" in client.get("/shipper/shipments/41").data


def test_create_ignores_browser_owner_status_and_uses_prg(client, monkeypatch):
    connections, _ = connect(monkeypatch, [lane(), ("INSERT INTO shipment", (7, 1, 2, D("25.50"), date(2030, 2, 28)), None)])
    response = client.post("/shipper/shipments/new", data={**FORM, "csrf_token": "test-csrf",
        "shipper_account_id": "999", "current_status": "DELIVERED", "delivery_outcome": "ON_TIME"})
    assert response.status_code == 303 and response.location == "/shipper/shipments/41"
    events = connections[0].events
    insert = next(e[0] for e in events if isinstance(e, tuple) and e[0].startswith("INSERT"))
    assert "current_status" not in insert and "delivery_outcome" not in insert
    assert "commit" in events and events[-1] == "close"


@pytest.mark.parametrize("field,value", [
    ("weight_kg", "-1"), ("weight_kg", "0"), ("weight_kg", "NaN"),
    ("weight_kg", "Infinity"), ("weight_kg", "0.001"), ("weight_kg", "100000000"),
    ("weight_kg", "1e2"), ("promised_delivery_date", "2030-02-30"),
    ("promised_delivery_date", ""), ("promised_delivery_date", "20300228"),
    ("promised_delivery_date", "0999-01-01"), ("lane", "-1:2"), ("lane", "1 OR 1=1:2"),
    ("lane", "1"), ("lane", "4294967296:2"),
])
def test_invalid_create_before_db(field, value, offline):
    with pytest.raises(service.ValidationError):
        service.create_shipment(7, {**FORM, field: value})
    offline.assert_not_called()


def test_invalid_form_rerenders_safely(client, monkeypatch):
    monkeypatch.setattr(service, "lanes", lambda: LANES)
    response = client.post("/shipper/shipments/new", data={**FORM, "weight_kg": "-1", "csrf_token": "test-csrf"})
    assert response.status_code == 400 and b"Enter a weight" in response.data


def test_nonexistent_lane_rollback(monkeypatch):
    connections, _ = connect(monkeypatch, [lane(None)])
    with pytest.raises(service.ValidationError, match="existing directed lane"):
        service.create_shipment(7, FORM)
    assert "commit" not in connections[0].events
    assert connections[0].events[-2:] == ["rollback", "close"]


def test_create_constraint_error_safe_and_rolled_back(client, monkeypatch):
    connections, _ = connect(monkeypatch, [lane(), ("INSERT INTO shipment", (7, 1, 2, D("25.50"), date(2030, 2, 28)), pymysql.IntegrityError(1452, "SECRET SQL details"))])
    response = client.post("/shipper/shipments/new", data={**FORM, "csrf_token": "test-csrf"})
    assert response.status_code == 409 and b"SECRET" not in response.data
    assert "commit" not in connections[0].events
    assert "rollback" in connections[0].events


def test_unbooked_update_lock_and_only_allowed_fields(monkeypatch):
    connections, _ = connect(monkeypatch, [booking(), locked(), booking(), scan(), lane(), update()])
    service.update_shipment(7, 41, {**FORM, "current_status": "DELIVERED", "shipper_account_id": "999"})
    events = connections[0].events
    assert events[0][0] == "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"
    assert events[2] == "begin"
    sql = [e[0] for e in events if isinstance(e, tuple)]
    assert sum("FOR UPDATE" in s for s in sql) == 1
    write = next(s for s in sql if s.startswith("UPDATE"))
    assert "current_status" not in write and "delivery_outcome" not in write
    assert "commit" in events


def booked_prefix():
    return [booking(9), ("FROM departure WHERE departure_id = %s FOR UPDATE", (9,), {"max_total_weight_kg": D("100")}), locked(), booking(9), scan()]


def test_booked_update_exact_capacity_and_lock_order(monkeypatch):
    connections, _ = connect(monkeypatch, booked_prefix() + [("COALESCE(SUM(s.weight_kg)", (9,), {"total": D("80")}), lane(), update(D("45.50"))])
    service.update_shipment(7, 41, {**FORM, "weight_kg": "45.50"})
    locks = [e[0] for e in connections[0].events if isinstance(e, tuple) and "FOR UPDATE" in e[0]]
    assert "FROM departure" in locks[0] and "FROM shipment" in locks[1]
    assert "commit" in connections[0].events


def test_booked_update_capacity_exceeded(monkeypatch):
    connections, _ = connect(monkeypatch, booked_prefix() + [("COALESCE(SUM(s.weight_kg)", (9,), {"total": D("80")})])
    with pytest.raises(service.ValidationError, match="capacity"):
        service.update_shipment(7, 41, {**FORM, "weight_kg": "45.51"})
    assert "commit" not in connections[0].events


def test_booked_lane_change_rejected(monkeypatch):
    connections, _ = connect(monkeypatch, booked_prefix())
    with pytest.raises(service.ValidationError, match="lane cannot"):
        service.update_shipment(7, 41, {**FORM, "lane": "2:1"})
    assert "commit" not in connections[0].events


def test_scanned_shipment_edit_rejected(monkeypatch):
    connections, _ = connect(monkeypatch, [booking(), locked(), booking(), scan({"scan_sequence": 1})])
    with pytest.raises(service.ValidationError, match="first scan"):
        service.update_shipment(7, 41, FORM)
    assert "commit" not in connections[0].events


def test_update_retries_booking_race_without_wrong_order_lock(monkeypatch):
    connections, factory = connect(monkeypatch,
        [booking(), locked(), booking(9)],
        booked_prefix() + [("COALESCE(SUM(s.weight_kg)", (9,), {"total": D("80")}), lane(), update()])
    service.update_shipment(7, 41, FORM)
    assert factory.call_count == 2
    assert "commit" not in connections[0].events
    assert not any(isinstance(e, tuple) and "FROM departure" in e[0] for e in connections[0].events)
    assert "commit" in connections[1].events


def test_update_retry_bound(monkeypatch):
    connections, factory = connect(monkeypatch, *[[booking(), locked(), booking(9)] for _ in range(3)])
    with pytest.raises(service.ValidationError, match="busy"):
        service.update_shipment(7, 41, FORM)
    assert factory.call_count == 3
    assert all("commit" not in c.events for c in connections)


def test_update_rechecks_owner_after_lock(monkeypatch):
    connections, _ = connect(monkeypatch, [booking(), ("shipper_account_id = %s FOR UPDATE", (41, 7), None)])
    with pytest.raises(service.ShipmentNotFound):
        service.update_shipment(7, 41, FORM)
    assert "commit" not in connections[0].events


def test_update_route_prg(client, monkeypatch):
    monkeypatch.setattr(service, "get_shipment", lambda owner, sid: SHIPMENT)
    operation = MagicMock()
    monkeypatch.setattr(service, "update_shipment", operation)
    response = client.post("/shipper/shipments/41/edit", data={**FORM, "csrf_token": "test-csrf", "shipper_account_id": "99"})
    assert response.status_code == 303 and response.location.endswith("/41")
    assert operation.call_args.args[:2] == (7, 41)


def test_departures_query_filters_owner_ordered_lane_capacity_and_duplicate(monkeypatch):
    departures = [{"departure_id": 9}]
    connections, _ = connect(monkeypatch, [owned(), ("ORDER BY d.departure_datetime, d.departure_id", (41, 7), departures)])
    _, actual = service.bookable_departures(7, 41)
    assert actual == departures
    sql = connections[0].events[1][0]
    for clause in ("d.origin_hub_id = s.origin_hub_id", "d.destination_hub_id = s.destination_hub_id", "NOT EXISTS", ">= s.weight_kg", "SUM(booked.weight_kg)", "s.shipper_account_id = %s"):
        assert clause in sql


def test_booking_authorizes_then_ends_read_transaction_before_call(monkeypatch):
    connections, _ = connect(monkeypatch, [owned(), ("CALL book_shipment(%s, %s)", (41, 9), None)])
    service.book_shipment(7, 41, "9")
    events = connections[0].events
    assert events[1] == "rollback"
    assert events[2] == ("CALL book_shipment(%s, %s)", (41, 9))
    assert "nextset" in events
    assert "begin" not in events and "commit" not in events
    assert not any(isinstance(e, tuple) and "INSERT INTO booking" in e[0] for e in events)


def test_booking_foreign_owner_never_calls_procedure(monkeypatch):
    connect(monkeypatch, [owned(None)])
    with pytest.raises(service.ShipmentNotFound):
        service.book_shipment(7, 41, "9")


@pytest.mark.parametrize("code,message,expected", [
    (1644, "Shipment is already booked", "already booked"),
    (1644, "Departure weight capacity would be exceeded", "capacity"),
    (1644, "Shipment lane does not match the ordered departure lane", "lane"),
    (1644, "Departure does not exist", "no longer available"),
    (1644, "SECRET new SQL error", "Booking was rejected"),
    (1062, "SECRET duplicate details", "already booked"),
])
def test_procedure_errors_safe(monkeypatch, code, message, expected):
    connections, _ = connect(monkeypatch, [owned(), ("CALL book_shipment", (41, 9), pymysql.OperationalError(code, message))])
    with pytest.raises(service.ValidationError, match=expected) as exc:
        service.book_shipment(7, 41, "9")
    assert "SECRET" not in str(exc.value)
    assert connections[0].events[-2:] == ["rollback", "close"]


@pytest.mark.parametrize("code", [1205, 1213])
def test_booking_retries_only_transient_lock_failures(monkeypatch, code):
    connections, factory = connect(monkeypatch,
        [owned(), ("CALL book_shipment", (41, 9), pymysql.OperationalError(code, "private"))],
        [owned(), ("CALL book_shipment", (41, 9), None)])
    service.book_shipment(7, 41, "9")
    assert factory.call_count == 2
    assert connections[0].events[-1] == "close"


def test_uncertain_booking_outcome_not_retried(monkeypatch):
    _, factory = connect(monkeypatch, [owned(), ("CALL book_shipment", (41, 9), pymysql.OperationalError(2013, "private"))])
    with pytest.raises(pymysql.OperationalError):
        service.book_shipment(7, 41, "9")
    assert factory.call_count == 1


def test_book_route_prg_and_owned_id(client, monkeypatch):
    monkeypatch.setattr(service, "bookable_departures", lambda owner, sid: (SHIPMENT, []))
    operation = MagicMock()
    monkeypatch.setattr(service, "book_shipment", operation)
    response = client.post("/shipper/shipments/41/book", data={"csrf_token": "test-csrf", "departure_id": "9", "shipment_id": "99", "shipper_account_id": "100"})
    assert response.status_code == 303 and response.location.endswith("/41")
    operation.assert_called_once_with(7, 41, "9")


def test_booking_error_feedback(client, monkeypatch):
    monkeypatch.setattr(service, "bookable_departures", lambda owner, sid: (SHIPMENT, []))
    monkeypatch.setattr(service, "book_shipment", MagicMock(side_effect=service.ValidationError("This shipment is already booked.")))
    response = client.post("/shipper/shipments/41/book", data={"csrf_token": "test-csrf", "departure_id": "9"})
    assert response.status_code == 409 and b"already booked" in response.data


def test_reports_owner_scope_and_transit_filter(client, monkeypatch):
    connect(monkeypatch, [("FROM shipment WHERE shipper_account_id = %s", (7,), {"on_time": 2, "late": 1}),
                         ("AND s.current_status IN ('IN_TRANSIT', 'ARRIVED_AT_HUB', 'OUT_FOR_DELIVERY')", (7,), [])])
    response = client.get("/shipper/reports")
    assert response.status_code == 200 and b"Currently in transit" in response.data
    assert b"<dd>2</dd>" in response.data and b"<dd>1</dd>" in response.data


@pytest.mark.parametrize("path", PATHS[1:])
def test_database_outage_safe(client, monkeypatch, path, caplog):
    monkeypatch.setattr(db, "get_connection", MagicMock(side_effect=pymysql.OperationalError(2003, "SECRET credentials")))
    response = client.get(path)
    assert response.status_code == 503
    assert b"SECRET" not in response.data and "SECRET" not in caplog.text
    assert response.headers["Cache-Control"] == "no-store"


def test_form_and_booking_pages_render(client, monkeypatch):
    monkeypatch.setattr(service, "lanes", lambda: LANES)
    monkeypatch.setattr(service, "get_shipment", lambda owner, sid: SHIPMENT)
    monkeypatch.setattr(service, "bookable_departures", lambda owner, sid: (SHIPMENT, [dict(departure_id=9, departure_datetime="2030-02-20 10:00", vehicle_id=5, max_total_weight_kg=D("100"), remaining_weight=D("50"))]))
    for path in WRITES:
        response = client.get(path)
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data


class FormControls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.controls = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.controls.append((tag, dict(attrs)))


@pytest.mark.parametrize("path,departure_id", [
    ("/shipper/shipments/new", None),
    ("/shipper/shipments/41/edit", None),
    ("/shipper/shipments/41/edit", 9),
])
def test_lane_control_preserves_booking_constraint(client, monkeypatch, path, departure_id):
    monkeypatch.setattr(service, "lanes", lambda: LANES)
    monkeypatch.setattr(service, "get_shipment", lambda owner, sid: {**SHIPMENT, "departure_id": departure_id})
    response = client.get(path)
    assert response.status_code == 200
    controls = FormControls(response.get_data(as_text=True)).controls
    selector = next(attrs for tag, attrs in controls if tag == "select" and attrs.get("name") == "lane")
    hidden = [attrs for tag, attrs in controls if tag == "input" and attrs.get("name") == "lane"]
    if departure_id is None:
        assert "disabled" not in selector
        assert not hidden
    else:
        assert "disabled" in selector
        assert selector["aria-describedby"] == "lane-help"
        assert hidden == [{"type": "hidden", "name": "lane", "value": "1:2"}]
        # Submit what a browser sends: disabled controls are omitted, hidden lane retained.
        update_mock = MagicMock()
        monkeypatch.setattr(service, "update_shipment", update_mock)
        saved = client.post(path, data={**FORM, "lane": hidden[0]["value"], "csrf_token": "test-csrf"})
        assert saved.status_code == 303
        assert update_mock.call_args.args[2]["lane"] == "1:2"


def test_booked_lane_uses_stored_value_after_invalid_post(client, monkeypatch):
    monkeypatch.setattr(service, "lanes", lambda: LANES + [
        dict(origin_hub_id=2, destination_hub_id=1, origin_region="West", destination_region="Northeast")])
    monkeypatch.setattr(service, "get_shipment", lambda owner, sid: {**SHIPMENT, "departure_id": 9})
    response = client.post("/shipper/shipments/41/edit", data={
        **FORM, "lane": "2:1", "weight_kg": "0", "csrf_token": "test-csrf"})
    assert response.status_code == 400
    controls = FormControls(response.get_data(as_text=True)).controls
    selected = [attrs["value"] for tag, attrs in controls if tag == "option" and "selected" in attrs]
    assert selected == ["1:2"]
    assert any(tag == "input" and attrs.get("name") == "lane" and attrs.get("value") == "1:2"
               for tag, attrs in controls)


@pytest.mark.parametrize("code", [1205, 1213])
def test_update_retries_deadlock_or_timeout(monkeypatch, code):
    connections, factory = connect(monkeypatch,
        [booking(), ("shipper_account_id = %s FOR UPDATE", (41, 7), pymysql.OperationalError(code, "private"))],
        [booking(), locked(), booking(), scan(), lane(), update()])
    service.update_shipment(7, 41, FORM)
    assert factory.call_count == 2
    assert "commit" not in connections[0].events
    assert "commit" in connections[1].events


def test_update_query_failure_rolls_back(monkeypatch):
    connections, _ = connect(monkeypatch, [booking(), locked(), booking(), scan(), lane(),
        ("UPDATE shipment", (1, 2, D("25.50"), date(2030, 2, 28), 41, 7), pymysql.IntegrityError(1452, "private"))])
    with pytest.raises(pymysql.IntegrityError):
        service.update_shipment(7, 41, FORM)
    assert "commit" not in connections[0].events
    assert connections[0].events[-2:] == ["rollback", "close"]


def test_booked_mapping_change_retries_from_start(monkeypatch):
    first = booked_prefix()[:3] + [booking(10)]
    connections, factory = connect(monkeypatch, first,
        [booking(), locked(), booking(), scan(), lane(), update()])
    service.update_shipment(7, 41, FORM)
    assert factory.call_count == 2 and "commit" not in connections[0].events


def test_booking_retry_limit(monkeypatch):
    connections, factory = connect(monkeypatch, *[
        [owned(), ("CALL book_shipment", (41, 9), pymysql.OperationalError(1213, "private"))]
        for _ in range(3)])
    with pytest.raises(service.ValidationError, match="busy"):
        service.book_shipment(7, 41, "9")
    assert factory.call_count == 3
    assert all(c.events[-1] == "close" for c in connections)


def test_empty_departures_state(client, monkeypatch):
    connect(monkeypatch, [owned(), ("ORDER BY d.departure_datetime", (41, 7), [])])
    response = client.get("/shipper/shipments/41/book")
    assert b"No compatible departures" in response.data


def test_update_form_validation_feedback(client, monkeypatch):
    monkeypatch.setattr(service, "get_shipment", lambda owner, sid: SHIPMENT)
    monkeypatch.setattr(service, "lanes", lambda: LANES)
    response = client.post("/shipper/shipments/41/edit", data={**FORM, "weight_kg": "0", "csrf_token": "test-csrf"})
    assert response.status_code == 400 and b"Enter a weight" in response.data


def test_expired_session_cannot_write(client, offline):
    with client.session_transaction() as session:
        session["expires_at"] = 1
    response = client.post("/shipper/shipments/new", data={**FORM, "csrf_token": "test-csrf"})
    assert response.status_code == 400
    offline.assert_not_called()


def test_maximum_and_minimum_weight_and_historical_date():
    for weight in ("0.01", "99999999.99"):
        value = service.shipment_input({**FORM, "weight_kg": weight, "promised_delivery_date": "2020-02-29"})
        assert value["weight"] == D(weight) and value["promise"] == date(2020, 2, 29)
