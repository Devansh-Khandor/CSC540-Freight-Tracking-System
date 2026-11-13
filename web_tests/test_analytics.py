"""Offline analytics web/service checks; never connect to MariaDB."""
from datetime import datetime
from decimal import Decimal
import time
from unittest.mock import MagicMock

import pymysql
import pytest
from app import analytics_service as service, db, queries, web

PATHS = ['/queries'] + [f'/queries/{n}' for n in range(1, 7)]

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(web, 'load_dotenv', lambda *a, **k: None)
    blocked = MagicMock(side_effect=AssertionError('Live database forbidden'))
    monkeypatch.setattr(db, 'get_connection', blocked)
    return blocked

@pytest.fixture
def app():
    return web.create_app({'TESTING': True, 'SECRET_KEY': 'test-only-secret-' * 3, 'SESSION_COOKIE_SECURE': False})

def login(client, role='VIEWER'):
    with client.session_transaction() as session:
        session.update(account_id=7, role=role, csrf_token='test-csrf', expires_at=time.time()+1800)

@pytest.fixture
def client(app):
    client = app.test_client()
    login(client)
    return client

def connect(monkeypatch, rows=()):
    conn = MagicMock()
    conn.cursor.return_value.fetchall.return_value = rows
    monkeypatch.setattr(db, 'get_connection', lambda: conn)
    return conn

@pytest.mark.parametrize('path', PATHS)
def test_anonymous(app, path, offline):
    response = app.test_client().get(path)
    assert response.status_code == 302 and response.location == '/login'
    assert response.headers['Cache-Control'] == 'no-store'
    offline.assert_not_called()

@pytest.mark.parametrize('path', PATHS)
def test_missing_secret(app, path, offline):
    app.config['SECRET_KEY'] = None
    assert app.test_client().get(path).status_code == 503
    offline.assert_not_called()

@pytest.mark.parametrize('role', ['SHIPPER', 'CARRIER', 'VIEWER'])
@pytest.mark.parametrize('number', range(1, 7))
def test_roles_dispatch_and_empty(app, monkeypatch, role, number):
    conn = connect(monkeypatch)
    report = service.REPORTS[number-1]
    function = MagicMock(return_value=[])
    monkeypatch.setattr(queries, report.function, function)
    client = app.test_client(); login(client, role)
    response = client.get(f'/queries/{number}?shipment_id=42')
    assert response.status_code == 200
    assert report.empty.encode() in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert function.call_args.args[1:] == ((42,) if number == 3 else ())
    assert isinstance(function.call_args.args[0], service.ReadOnlyConnection)
    conn.rollback.assert_called_once(); conn.close.assert_called_once()
    conn.commit.assert_not_called()

@pytest.mark.parametrize('number', range(1, 7))
def test_original_sql_and_cleanup(monkeypatch, number):
    conn = connect(monkeypatch, [(1,)])
    assert service.execute_report(number, '42') == [(1,)]
    calls = conn.cursor.return_value.execute.call_args_list
    assert calls[0].args == ('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY',)
    assert calls[1].args[0].strip().startswith('SELECT')
    assert calls[1].args[1] == ((42,) if number == 3 else ())
    if number == 3:
        assert 'shipment_id = %s' in calls[1].args[0]
    assert conn.cursor.return_value.close.call_count == 2
    conn.rollback.assert_called_once(); conn.close.assert_called_once()
    conn.commit.assert_not_called()

@pytest.mark.parametrize('value', ['', '0', '-1', '1.5', '1 OR 1=1', '4294967296', '9'*100, '<script>alert(1)</script>', '١'])
def test_invalid_id(client, offline, value):
    response = client.get('/queries/3', query_string={'shipment_id': value})
    assert response.status_code == 400
    assert b'Enter a shipment ID' in response.data
    assert b'<script>alert(1)</script>' not in response.data
    offline.assert_not_called()

@pytest.mark.parametrize('value,expected', [('1', 1), (' 42 ',42), ('4294967295',4294967295)])
def test_valid_id(value, expected):
    assert service.parse_shipment_id(value) == expected


def test_catalog_and_initial_form(client, offline):
    page = client.get('/queries')
    assert page.status_code == 200
    positions = [page.data.index(f'href="/queries/{n}"'.encode()) for n in range(1,7)]
    assert positions == sorted(positions)
    assert b'View Queries' in client.get('/').data
    assert b'Shipment ID' in client.get('/queries/3').data
    offline.assert_not_called()

@pytest.mark.parametrize('number', [0,7,999])
def test_unknown(client, offline, number):
    assert client.get(f'/queries/{number}').status_code == 404
    offline.assert_not_called()

@pytest.mark.parametrize('method', ['post','put','patch','delete'])
@pytest.mark.parametrize('path', PATHS)
def test_no_write_routes(client, offline, method, path):
    assert getattr(client, method)(path, data={'csrf_token':'test-csrf'}).status_code == 405
    offline.assert_not_called()

@pytest.mark.parametrize('failure', ['connect','transaction','fetch','rollback'])
def test_database_errors_generic(monkeypatch, client, failure):
    conn = connect(monkeypatch)
    error = pymysql.OperationalError(999, 'PRIVATE DATABASE DETAIL')
    if failure == 'connect':
        monkeypatch.setattr(db, 'get_connection', MagicMock(side_effect=error))
    elif failure == 'transaction':
        conn.cursor.return_value.execute.side_effect = error
    elif failure == 'fetch':
        conn.cursor.return_value.fetchall.side_effect = error
    else:
        conn.rollback.side_effect = error
    response = client.get('/queries/1')
    assert response.status_code == 503
    assert b'PRIVATE' not in response.data
    if failure != 'connect':
        conn.close.assert_called_once()
        conn.rollback.assert_called_once()


def test_adapter_blocks_writes(monkeypatch):
    conn = connect(monkeypatch)
    def bad_query(connection):
        connection.cursor().execute('DELETE FROM shipment')
    monkeypatch.setattr(queries, service.REPORTS[0].function, bad_query)
    with pytest.raises(RuntimeError):
        service.execute_report(1)
    assert conn.cursor.return_value.execute.call_count == 1
    conn.rollback.assert_called_once(); conn.close.assert_called_once()


def test_precision_and_escaping(monkeypatch, client):
    connect(monkeypatch, [(1, 2, '<script>bad</script>', datetime(2030,1,1), Decimal('123.450'), Decimal('1000.000'), Decimal('12.35'), 1)])
    response = client.get('/queries/2')
    assert response.status_code == 200
    for text in [b'123.450', b'1000.000', b'12.35', b'Lane rank', b'Utilization (%)', b'&lt;script&gt;bad&lt;/script&gt;']:
        assert text in response.data
    assert b'<script>bad</script>' not in response.data


def test_scan_first_and_consecutive(monkeypatch, client):
    connect(monkeypatch, [(42,1,'RECEIVED',datetime(2030,1,1),None,None), (42,2,'IN_TRANSIT',datetime(2030,1,1,1),datetime(2030,1,1),60)])
    response = client.get('/queries/3?shipment_id=42')
    assert response.status_code == 200
    assert b'No previous scan' in response.data and b'>60<' in response.data
    assert response.data.index(b'RECEIVED') < response.data.index(b'IN_TRANSIT')

@pytest.mark.parametrize('role', ['INVALID', None])
def test_invalid_session(client, offline, role):
    login(client, role)
    assert client.get('/queries').status_code == 302
    offline.assert_not_called()


def test_expired_session(client, offline):
    with client.session_transaction() as session:
        session['expires_at'] = 1
    assert client.get('/queries').status_code == 302
    offline.assert_not_called()
