"""Offline viewer checks; no live MariaDB access or authentication bypass in production."""
from datetime import date, datetime
from html.parser import HTMLParser
import time
from unittest.mock import MagicMock

import pymysql
import pytest

from app import db, web, viewer_service as service

PATHS = ('/viewer', '/viewer/track', '/viewer/track?shipment_id=41', '/viewer/reports')
SHIPMENT = dict(shipment_id=41, origin_hub_id=1, destination_hub_id=2,
                origin_region='Northeast', destination_region='West', current_status='IN_TRANSIT',
                promised_delivery_date=date(2030,2,22), delivery_outcome=None,
                departure_id=21, vehicle_id=11, departure_datetime=datetime(2030,2,20,10),
                departure_origin=1, departure_destination=2)
SCANS = [dict(scan_sequence=1, scan_timestamp=datetime(2030,2,20,10), status='RECEIVED', hub_id=1, region='Northeast'),
         dict(scan_sequence=2, scan_timestamp=datetime(2030,2,20,10), status='IN_TRANSIT', hub_id=1, region='Northeast')]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(web, 'load_dotenv', lambda *a, **k: None)
    blocked = MagicMock(side_effect=AssertionError('Live database forbidden'))
    monkeypatch.setattr(db, 'get_connection', blocked)
    return blocked


@pytest.fixture
def app():
    return web.create_app({'TESTING': True, 'SECRET_KEY': 'test-only-secret-' * 3, 'SESSION_COOKIE_SECURE': False})


def sign_in(client, role='VIEWER'):
    with client.session_transaction() as session:
        session.update(account_id=7, role=role, csrf_token='test-csrf', expires_at=time.time()+1800, _permanent=True)


@pytest.fixture
def client(app):
    client=app.test_client()
    sign_in(client)
    return client


def connection(monkeypatch, rows=(), lists=()):
    conn=MagicMock()
    cursor=conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect=list(rows)
    cursor.fetchall.side_effect=list(lists)
    def select_only(sql, params=None):
        assert sql.lstrip().startswith('SELECT ')
        assert 'FOR UPDATE' not in sql and 'CALL ' not in sql
    cursor.execute.side_effect=select_only
    monkeypatch.setattr(db,'get_connection',lambda:conn)
    return conn,cursor


def assert_closed_read(conn):
    conn.commit.assert_not_called()
    conn.begin.assert_not_called()
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()


@pytest.mark.parametrize('path',PATHS)
def test_anonymous_redirect(app,path,offline):
    response=app.test_client().get(path)
    assert response.status_code==302 and response.location=='/login'
    assert response.headers['Cache-Control']=='no-store'
    offline.assert_not_called()


@pytest.mark.parametrize('role',['SHIPPER','CARRIER'])
@pytest.mark.parametrize('path',PATHS)
def test_strict_role_separation(app,role,path,offline):
    client=app.test_client(); sign_in(client,role)
    assert client.get(path).status_code==403
    offline.assert_not_called()


@pytest.mark.parametrize('path',PATHS)
def test_missing_secret_closed(app,path,offline):
    app.config['SECRET_KEY']=None
    assert app.test_client().get(path).status_code==503
    offline.assert_not_called()


def test_dashboard_statistics_reads_only(monkeypatch,client):
    conn,cursor=connection(monkeypatch,[dict(total=3,in_transit=1,delivered=1)])
    response=client.get('/viewer')
    assert response.status_code==200 and b'Total shipments' in response.data
    assert response.headers['Cache-Control']=='no-store'
    assert response.headers['X-Frame-Options']=='DENY'
    assert cursor.execute.call_args.args[1]==('IN_TRANSIT','ARRIVED_AT_HUB','OUT_FOR_DELIVERY','DELIVERED')
    assert_closed_read(conn)


def test_lookup_initial_form_without_database(client,offline):
    response=client.get('/viewer/track')
    assert response.status_code==200
    assert b'<label for="shipment_id">Shipment ID</label>' in response.data
    assert b'method="get"' in response.data
    offline.assert_not_called()


def test_tracking_parameterization_order_and_cross_shipper_visibility(monkeypatch,client):
    conn,cursor=connection(monkeypatch,[SHIPMENT],[SCANS])
    response=client.get('/viewer/track?shipment_id=00041')
    assert response.status_code==200
    queries=cursor.execute.call_args_list
    assert len(queries)==2 and all(call.args[1]==(41,) for call in queries)
    assert 'WHERE s.shipment_id = %s' in queries[0].args[0]
    assert 'ORDER BY e.scan_sequence ASC' in queries[1].args[0]
    assert 'shipper_account_id' not in queries[0].args[0]
    assert 'password' not in queries[0].args[0].lower()
    html=response.get_data(as_text=True)
    assert html.index('RECEIVED') < html.index('<td>IN_TRANSIT</td>')
    for text in ('Departure #21','Vehicle #11','2030-02-22','Northeast','West'):
        assert text in html
    assert_closed_read(conn)


def test_missing_shipment_no_scan_query(monkeypatch,client):
    conn,cursor=connection(monkeypatch,[None])
    response=client.get('/viewer/track?shipment_id=41')
    assert response.status_code==404 and b'No shipment was found' in response.data
    assert cursor.execute.call_count==1
    assert_closed_read(conn)


def test_empty_history_and_unbooked_shipment(monkeypatch,client):
    conn,_=connection(monkeypatch,[{**SHIPMENT,'current_status':None,'departure_id':None}],[[]])
    response=client.get('/viewer/track?shipment_id=41')
    for message in (b'Not yet scanned',b'not yet booked',b'No scan events'):
        assert message in response.data
    assert_closed_read(conn)


@pytest.mark.parametrize('value',['','0','-1','4294967296','1 OR 1=1','1.5','1e2','９','1'*100])
def test_invalid_id_does_not_query(monkeypatch,client,offline,value):
    response=client.get('/viewer/track',query_string={'shipment_id':value})
    assert response.status_code==400
    assert b'Enter a shipment ID' in response.data
    offline.assert_not_called()


def test_input_escaped(client):
    response=client.get('/viewer/track',query_string={'shipment_id':'"><script>alert(1)</script>'})
    assert response.status_code==400 and b'<script>' not in response.data


@pytest.mark.parametrize('method',['POST','PUT','PATCH','DELETE'])
@pytest.mark.parametrize('path',PATHS)
def test_all_viewer_routes_reject_writes(client,offline,method,path):
    response=client.open(path,method=method,data={'csrf_token':'test-csrf','status':'DELIVERED'})
    assert response.status_code==405
    offline.assert_not_called()


def test_viewer_routes_only_allow_safe_methods(app):
    rules=[rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith('viewer.')]
    assert len(rules)==3
    assert all(rule.methods <= {'GET','HEAD','OPTIONS'} for rule in rules)


@pytest.mark.parametrize('path',['/shipper','/shipper/shipments','/shipper/shipments/new',
    '/carrier','/carrier/vehicles','/carrier/departures','/carrier/shipments/41/scans'])
def test_viewer_cannot_enter_management(client,offline,path):
    assert client.get(path).status_code==403
    offline.assert_not_called()


@pytest.mark.parametrize('path',['/shipper/shipments/new','/shipper/shipments/41/edit','/shipper/shipments/41/book',
    '/carrier/vehicles/new','/carrier/vehicles/11/edit','/carrier/departures/new',
    '/carrier/departures/21/edit','/carrier/shipments/41/scans'])
def test_viewer_cannot_write_through_other_roles(client,offline,path):
    assert client.post(path,data={'csrf_token':'test-csrf'}).status_code==403
    offline.assert_not_called()


def test_reports_delivered_only_denominator_and_no_account_secrets(monkeypatch,client):
    lane=dict(origin_hub_id=1,destination_hub_id=2,origin_region='Northeast',destination_region='West',delivered=4,on_time=3,late=1,rate=75)
    carrier=dict(carrier_id=7,delivered=0,on_time=0,late=0,rate=None)
    conn,cursor=connection(monkeypatch,lists=[[lane],[carrier]])
    response=client.get('/viewer/reports')
    assert response.status_code==200 and b'75%' in response.data and b'No deliveries yet' in response.data
    for call in cursor.execute.call_args_list:
        sql,params=call.args
        assert params==('DELIVERED',)
        assert 's.current_status = %s' in sql
        assert 'NULLIF(COUNT(s.shipment_id), 0)' in sql
        assert 'password' not in sql.lower() and 'JOIN account' not in sql
    assert 'LEFT JOIN booking' in cursor.execute.call_args_list[1].args[0]
    assert_closed_read(conn)


def test_empty_reports(monkeypatch,client):
    connection(monkeypatch,lists=[[],[]])
    response=client.get('/viewer/reports')
    assert response.status_code==200 and b'No lanes are available' in response.data and b'No carriers are available' in response.data


def test_empty_dashboard(monkeypatch,client):
    connection(monkeypatch,[dict(total=0,in_transit=0,delivered=0)])
    assert b'No shipments are recorded yet' in client.get('/viewer').data


@pytest.mark.parametrize('path',['/viewer','/viewer/track?shipment_id=41','/viewer/reports'])
@pytest.mark.parametrize('error',[db.ConfigurationError('PRIVATE'),pymysql.OperationalError(2003,'PRIVATE'),OSError('PRIVATE')])
def test_outages_safe(monkeypatch,client,path,error,caplog):
    monkeypatch.setattr(db,'get_connection',MagicMock(side_effect=error))
    response=client.get(path)
    assert response.status_code==503 and b'Tracking service unavailable' in response.data
    assert b'PRIVATE' not in response.data and 'PRIVATE' not in caplog.text


def test_query_failure_cleanup(monkeypatch,client):
    conn,cursor=connection(monkeypatch)
    cursor.execute.side_effect=pymysql.OperationalError(2013,'PRIVATE')
    assert client.get('/viewer/reports').status_code==503
    assert_closed_read(conn)


class Links(HTMLParser):
    def __init__(self,html):
        super().__init__(); self.links=[]; self.forms=[]; self.feed(html)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a': self.links.append(attrs.get('href',''))
        if tag=='form': self.forms.append(attrs)


def test_navigation_and_forms_are_read_only(monkeypatch,client):
    monkeypatch.setattr(service,'statistics',lambda:dict(total=1,in_transit=1,delivered=0))
    monkeypatch.setattr(service,'tracking',lambda value:(SHIPMENT,SCANS))
    monkeypatch.setattr(service,'reports',lambda:([],[]))
    for path in PATHS:
        response=client.get(path)
        assert response.status_code==200
        parsed=Links(response.get_data(as_text=True))
        for link in parsed.links:
            if link.startswith('/viewer'): assert client.get(link).status_code==200
            assert not link.startswith(('/shipper','/carrier'))
        for form in parsed.forms:
            assert form.get('method')=='get' or form.get('action')=='/logout'


def test_expired_viewer_session_redirects(client,offline):
    with client.session_transaction() as session: session['expires_at']=1
    assert client.get('/viewer/track?shipment_id=41').location=='/login'
    offline.assert_not_called()
