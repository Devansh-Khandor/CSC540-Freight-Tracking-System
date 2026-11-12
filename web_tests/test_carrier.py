"""Offline carrier tests. SQL scripts assert ordering/parameters, not MariaDB execution."""
from datetime import datetime, date
from decimal import Decimal as D
from html.parser import HTMLParser
import time
from unittest.mock import MagicMock

import pymysql
import pytest

from app import db, web, carrier_service as service

VEHICLE = dict(vehicle_id=11, home_hub_id=1, region="Northeast", box_id=11,
               van_id=None, rail_id=None, cargo_volume=D('20'), gross_weight_rating=D('5000'),
               temperature_range=None, payload_limit=None, axle_count=None, track_gauge=None, kind="BOX_TRUCK")
DEPARTURE = dict(departure_id=21, vehicle_id=11, origin_hub_id=1, destination_hub_id=2,
                 departure_datetime=datetime(2030, 2, 20, 10), max_total_weight_kg=D('100'),
                 booking_count=1, booked_weight=D('60'), utilization=D('60'))
SHIPMENT = dict(shipment_id=41, departure_id=21, vehicle_id=11, origin_hub_id=1, destination_hub_id=2,
                weight_kg=D('60'), promised_delivery_date=date(2030, 2, 22), current_status=None, delivery_outcome=None)
HUBS = [dict(hub_id=1, region="Northeast"), dict(hub_id=2, region="West")]
LANES = [dict(origin_hub_id=1, destination_hub_id=2, origin_region="Northeast", destination_region="West")]
VEHICLE_FORM = dict(kind="BOX_TRUCK", home_hub_id="1", cargo_volume="20", gross_weight_rating="5000")
DEPARTURE_FORM = dict(vehicle_id="11", lane="1:2", departure_datetime="2030-02-20T10:00:00", max_total_weight_kg="100")
SCAN_FORM = dict(status="RECEIVED", hub_id="1", scan_timestamp="2030-02-20T10:00:00")
GETS = ['/carrier', '/carrier/vehicles', '/carrier/vehicles/new', '/carrier/vehicles/11/edit',
        '/carrier/departures', '/carrier/departures/new', '/carrier/departures/21/edit',
        '/carrier/shipments', '/carrier/shipments/41/scans', '/carrier/reports']
WRITES = [GETS[i] for i in (2, 3, 5, 6, 8)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(web, 'load_dotenv', lambda *a, **k: None)
    blocked = MagicMock(side_effect=AssertionError('Live database forbidden'))
    monkeypatch.setattr(db, 'get_connection', blocked)
    return blocked


@pytest.fixture
def app():
    return web.create_app({'TESTING': True, 'SECRET_KEY': 'test-only-secret-' * 3, 'SESSION_COOKIE_SECURE': False})


def sign_in(client, role='CARRIER'):
    with client.session_transaction() as session:
        session.update(account_id=7, role=role, csrf_token='test-csrf', expires_at=time.time() + 1800, _permanent=True)


@pytest.fixture
def client(app):
    client = app.test_client()
    sign_in(client)
    return client


class ScriptedConnection:
    def __init__(self, steps, commit_error=None):
        self.steps = list(steps)
        self.events = []
        self.result = None
        self.lastrowid = 91
        self.commit_error = commit_error

    def cursor(self, cursorclass):
        assert cursorclass == pymysql.cursors.DictCursor
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.events.append('cursor-close')

    def execute(self, sql, params=None):
        sql = ' '.join(sql.split())
        self.events.append((sql, params))
        if sql.startswith('SET SESSION'):
            return
        assert self.steps, f'Unexpected SQL: {sql}'
        fragment, expected, result = self.steps.pop(0)
        assert fragment in sql
        assert params == expected
        if isinstance(result, Exception):
            raise result
        self.result = result

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def begin(self):
        self.events.append('begin')

    def commit(self):
        self.events.append('commit')
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.events.append('rollback')

    def close(self):
        self.events.append('close')
        assert not self.steps


def connect(monkeypatch, *scripts, commit_error=None):
    connections = [ScriptedConnection(s, commit_error) for s in scripts]
    factory = MagicMock(side_effect=connections)
    monkeypatch.setattr(db, 'get_connection', factory)
    return connections, factory


def vehicle_steps(lock=False, row=None):
    return [('carrier_account_id = %s' + (' FOR UPDATE' if lock else ''), (11, 7), {'vehicle_id': 11}),
            ('AND v.vehicle_id = %s', (7, 11), dict(VEHICLE if row is None else row))]


def hub_step():
    return ('SELECT hub_id FROM hub WHERE hub_id = %s', (1,), {'hub_id': 1})


def lane_step():
    return ('SELECT origin_hub_id FROM lane', (1, 2), LANES[0])


def departure_lock(row=DEPARTURE):
    return ('FOR UPDATE', (21, 7), row)


def load_step(weight='60', count=1):
    return ('COALESCE(SUM(s.weight_kg), 0)', (21,), {'booking_count': count, 'booked_weight': D(weight)})


def assigned(row=SHIPMENT):
    return ('AND s.shipment_id = %s', (7, 41), row)


def scan_prefix():
    return [assigned(), ('SELECT shipment_id FROM shipment WHERE shipment_id = %s FOR UPDATE', (41,), {'shipment_id': 41}), assigned()]


def assert_transaction(connection, committed=True):
    assert connection.events[0] == ('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED', None)
    assert connection.events[1][0].startswith('SET SESSION sql_mode')
    assert connection.events[2] == 'begin'
    assert ('commit' in connection.events) == committed
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('path', GETS)
def test_anonymous_redirect(app, path, offline):
    response = app.test_client().get(path)
    assert response.status_code == 302 and response.location == '/login'
    assert response.headers['Cache-Control'] == 'no-store'
    offline.assert_not_called()


@pytest.mark.parametrize('role', ['SHIPPER', 'VIEWER'])
@pytest.mark.parametrize('path', GETS)
def test_wrong_role(app, path, role, offline):
    client = app.test_client()
    sign_in(client, role)
    assert client.get(path).status_code == 403
    offline.assert_not_called()


@pytest.mark.parametrize('path', WRITES)
def test_writes_require_csrf(client, path, offline):
    assert client.post(path).status_code == 400
    assert client.post(path, data={'csrf_token': 'bad'}).status_code == 400
    offline.assert_not_called()


@pytest.mark.parametrize('role', ['SHIPPER', 'VIEWER', None])
@pytest.mark.parametrize('path', WRITES)
def test_write_role_guard(app, path, role, offline):
    client = app.test_client()
    if role:
        sign_in(client, role)
    else:
        with client.session_transaction() as session:
            session['csrf_token'] = 'test-csrf'
    response = client.post(path, data={'csrf_token': 'test-csrf'})
    assert response.status_code == (403 if role else 302)
    offline.assert_not_called()


@pytest.mark.parametrize('path', GETS)
def test_missing_secret_fails_closed(app, path, offline):
    app.config['SECRET_KEY'] = None
    assert app.test_client().get(path).status_code == 503
    offline.assert_not_called()


@pytest.mark.parametrize('kind,extra,table,params', [
    ('BOX_TRUCK', {'cargo_volume':'20', 'gross_weight_rating':'5000'}, 'box_truck', (91, D('20'), D('5000'))),
    ('REFRIGERATED_VAN', {'temperature_range':'-10 to 5 C', 'payload_limit':'100'}, 'refrigerated_van', (91, '-10 to 5 C', D('100'))),
    ('RAIL_CAR', {'axle_count':'4', 'track_gauge':'1435'}, 'rail_car', (91, 4, D('1435'))),
])
def test_create_vehicle_atomic_and_owned(monkeypatch, kind, extra, table, params):
    connections, _ = connect(monkeypatch, [
        ("BINARY a.role = 'CARRIER'", (7,), {'account_id': 7}), hub_step(),
        ('INSERT INTO vehicle (carrier_account_id, home_hub_id)', (7, 1), None),
        ('INSERT INTO ' + table, params, None)])
    assert service.create_vehicle(7, {'kind':kind, 'home_hub_id':'1', 'carrier_account_id':'999', **extra}) == 91
    assert_transaction(connections[0])
    sql = connections[0].events[3][0]
    assert 'NOT EXISTS (SELECT 1 FROM shipper' in sql and 'NOT EXISTS (SELECT 1 FROM viewer' in sql


@pytest.mark.parametrize('field,value', [('kind','AIRPLANE'), ('home_hub_id','0'), ('cargo_volume','0'),
    ('cargo_volume','NaN'), ('cargo_volume','1e2'), ('cargo_volume','1.001'), ('gross_weight_rating','100000000')])
def test_bad_vehicle_input_before_database(field, value, offline):
    with pytest.raises(service.ValidationError):
        service.create_vehicle(7, {**VEHICLE_FORM, field:value})
    offline.assert_not_called()


@pytest.mark.parametrize('kind,form', [('RAIL_CAR', {'axle_count':'1.5','track_gauge':'1'}),
    ('RAIL_CAR', {'axle_count':'4','track_gauge':'10000'}),
    ('REFRIGERATED_VAN', {'temperature_range':'x'*51, 'payload_limit':'1'}),
    ('REFRIGERATED_VAN', {'temperature_range':' ', 'payload_limit':'1'})])
def test_invalid_subtype_fields(kind, form):
    with pytest.raises(service.ValidationError):
        service.subtype_values(kind, form)


def test_vehicle_subtype_insert_failure_rolls_back_parent(monkeypatch):
    connections, _ = connect(monkeypatch, [("BINARY a.role = 'CARRIER'", (7,), {'account_id':7}), hub_step(),
        ('INSERT INTO vehicle', (7,1), None),
        ('INSERT INTO box_truck', (91,D('20'),D('5000')), pymysql.IntegrityError(4025,'private'))])
    with pytest.raises(pymysql.IntegrityError):
        service.create_vehicle(7, VEHICLE_FORM)
    assert_transaction(connections[0], False)


def test_invalid_carrier_membership_rejected(monkeypatch):
    connections, _ = connect(monkeypatch, [("BINARY a.role = 'CARRIER'", (7,), None)])
    with pytest.raises(service.ValidationError):
        service.create_vehicle(7, VEHICLE_FORM)
    assert_transaction(connections[0], False)


def test_update_vehicle_preserves_identity_owner_and_subtype(monkeypatch):
    connections, _ = connect(monkeypatch, vehicle_steps(True) + [hub_step(),
        ('UPDATE vehicle SET home_hub_id', (1,11,7), None),
        ('UPDATE box_truck SET cargo_volume', (D('20'),D('5000'),11), None)])
    service.update_vehicle(7,11,{**VEHICLE_FORM, 'carrier_account_id':'999', 'vehicle_id':'999'})
    assert_transaction(connections[0])


def test_vehicle_subtype_change_rejected(monkeypatch):
    connections, _ = connect(monkeypatch, vehicle_steps(True))
    with pytest.raises(service.ValidationError, match='subtype cannot'):
        service.update_vehicle(7,11,{**VEHICLE_FORM, 'kind':'RAIL_CAR'})
    assert_transaction(connections[0], False)


def test_multiple_vehicle_subtypes_rejected(monkeypatch):
    connect(monkeypatch, vehicle_steps(True, {**VEHICLE,'van_id':11}))
    with pytest.raises(service.ValidationError, match='inconsistent'):
        service.update_vehicle(7,11,VEHICLE_FORM)


def test_base_only_vehicle_home_hub_update(monkeypatch):
    connections, _ = connect(monkeypatch, vehicle_steps(True, {**VEHICLE,'box_id':None}) + [hub_step(),
        ('UPDATE vehicle SET home_hub_id', (1,11,7), None)])
    service.update_vehicle(7,11,{'home_hub_id':'1'})
    assert_transaction(connections[0])


@pytest.mark.parametrize('operation', ['get', 'update', 'departure_create'])
def test_foreign_vehicle_rejected(monkeypatch, operation):
    connect(monkeypatch, [('carrier_account_id = %s', (11,7), None)])
    with pytest.raises(service.NotFound):
        if operation == 'get': service.get_vehicle(7,11)
        elif operation == 'update': service.update_vehicle(7,11,VEHICLE_FORM)
        else: service.create_departure(7,DEPARTURE_FORM)


def test_create_departure_uses_owned_vehicle_and_existing_lane(monkeypatch):
    connections, _ = connect(monkeypatch, vehicle_steps() + [lane_step(),
        ('INSERT INTO departure', (11,1,2,datetime(2030,2,20,10),D('100')), None)])
    assert service.create_departure(7,DEPARTURE_FORM) == 91
    assert_transaction(connections[0])


@pytest.mark.parametrize('field,value', [('vehicle_id','0'), ('lane','1'), ('lane','1:0'),
    ('max_total_weight_kg','0'), ('max_total_weight_kg','-1'), ('max_total_weight_kg','1.001'),
    ('departure_datetime','2030-02-30T10:00'), ('departure_datetime','2030-01-01T10:00Z')])
def test_invalid_departure_input(field, value, offline):
    with pytest.raises(service.ValidationError):
        service.create_departure(7,{**DEPARTURE_FORM,field:value})
    offline.assert_not_called()


@pytest.mark.parametrize('value', ['2030-03-10T02:30', '2030-11-03T01:30', '0999-01-01T10:00', '2030-01-01T10:00:00.1'])
def test_invalid_or_ambiguous_wall_time(value):
    with pytest.raises(service.ValidationError):
        service.local_datetime(value)


@pytest.mark.parametrize('capacity', ['60','70','110'])
def test_booked_departure_capacity_change_under_lock(monkeypatch, capacity):
    connections, _ = connect(monkeypatch, [departure_lock(),load_step()] + vehicle_steps() + [lane_step(),
        ('UPDATE departure SET', (11,1,2,datetime(2030,2,20,10),D(capacity),21), None)])
    service.update_departure(7,21,{**DEPARTURE_FORM,'max_total_weight_kg':capacity})
    assert_transaction(connections[0])
    assert 'FOR UPDATE' in connections[0].events[3][0]


def test_departure_capacity_below_booked_load_rejected(monkeypatch):
    connections, _ = connect(monkeypatch,[departure_lock(),load_step()])
    with pytest.raises(service.ValidationError, match='lower'):
        service.update_departure(7,21,{**DEPARTURE_FORM,'max_total_weight_kg':'59.99'})
    assert_transaction(connections[0],False)


@pytest.mark.parametrize('field,value', [('vehicle_id','12'),('lane','2:1'),('departure_datetime','2030-02-21T10:00')])
def test_booked_departure_logistics_immutable(monkeypatch,field,value):
    connections, _ = connect(monkeypatch,[departure_lock(),load_step()])
    with pytest.raises(service.ValidationError,match='cannot be changed'):
        service.update_departure(7,21,{**DEPARTURE_FORM,field:value})
    assert_transaction(connections[0],False)


def test_unbooked_departure_can_change_lane_time_vehicle(monkeypatch):
    connections, _ = connect(monkeypatch,[departure_lock(),load_step('0',0),
        ('carrier_account_id = %s', (12,7), {'vehicle_id':12}),
        ('AND v.vehicle_id = %s',(7,12),{**VEHICLE,'vehicle_id':12}),
        ('SELECT origin_hub_id FROM lane',(2,1),LANES[0]),
        ('UPDATE departure SET',(12,2,1,datetime(2030,2,21,10),D('100'),21),None)])
    service.update_departure(7,21,{**DEPARTURE_FORM,'vehicle_id':'12','lane':'2:1','departure_datetime':'2030-02-21T10:00'})
    assert_transaction(connections[0])


def test_departure_replacement_vehicle_must_be_owned(monkeypatch):
    connect(monkeypatch,[departure_lock(),load_step('0',0),('carrier_account_id = %s',(11,7),None)])
    with pytest.raises(service.NotFound):
        service.update_departure(7,21,DEPARTURE_FORM)


@pytest.mark.parametrize('operation', ['get','update'])
def test_foreign_departure_rejected(monkeypatch,operation):
    connect(monkeypatch,[(('AND d.departure_id = %s' if operation == 'get' else 'FOR UPDATE'),
                         ((7,21) if operation == 'get' else (21,7)),None)])
    with pytest.raises(service.NotFound):
        if operation == 'get': service.get_departure(7,21)
        else: service.update_departure(7,21,DEPARTURE_FORM)


def test_assigned_shipments_full_owner_chain(monkeypatch):
    connections, _ = connect(monkeypatch,[('WHERE v.carrier_account_id = %s',(7,),[SHIPMENT])])
    assert service.assigned_shipments(7) == [SHIPMENT]
    sql = connections[0].events[0][0]
    for relation in ('JOIN booking b','JOIN departure d','JOIN vehicle v'):
        assert relation in sql


def test_scan_prelock_sequence_insert_and_commit(monkeypatch):
    connections, _ = connect(monkeypatch,scan_prefix()+[hub_step(),
        ('COALESCE(MAX(scan_sequence), 0) + 1',(41,),{'next_sequence':3}),
        ('INSERT INTO scan_event',(41,3,datetime(2030,2,20,10),'ARRIVED_AT_HUB',1),None)])
    service.post_scan(7,41,{**SCAN_FORM,'status':'ARRIVED_AT_HUB','scan_sequence':'999','current_status':'DELIVERED'})
    assert_transaction(connections[0])
    statements = [event[0] for event in connections[0].events if isinstance(event,tuple)]
    assert sum(s.startswith('INSERT INTO scan_event') for s in statements) == 1
    assert not any(s.startswith('UPDATE shipment') for s in statements)
    assert statements.index('SELECT shipment_id FROM shipment WHERE shipment_id = %s FOR UPDATE') < next(i for i,s in enumerate(statements) if 'MAX(scan_sequence)' in s)


def test_unauthorized_scan_does_not_lock_or_insert(monkeypatch):
    connections, _ = connect(monkeypatch,[assigned(None)])
    with pytest.raises(service.NotFound): service.post_scan(7,41,SCAN_FORM)
    assert_transaction(connections[0],False)


def test_scan_rechecks_ownership_after_prelock(monkeypatch):
    connect(monkeypatch,[assigned(),('FOR UPDATE',(41,),{'shipment_id':41}),assigned(None)])
    with pytest.raises(service.NotFound): service.post_scan(7,41,SCAN_FORM)


@pytest.mark.parametrize('field,value',[('status','delivered'),('status','CANCELLED'),('hub_id','0'),('scan_timestamp','2030-02-30T10:00')])
def test_invalid_scan_input_rolls_back(monkeypatch,field,value):
    connections, _ = connect(monkeypatch,scan_prefix())
    with pytest.raises(service.ValidationError): service.post_scan(7,41,{**SCAN_FORM,field:value})
    assert_transaction(connections[0],False)


@pytest.mark.parametrize('code',[1644,1062,1452])
def test_failed_scan_rolls_back_without_retry(monkeypatch,code):
    connections, factory = connect(monkeypatch,scan_prefix()+[hub_step(),
        ('MAX(scan_sequence)',(41,),{'next_sequence':1}),
        ('INSERT INTO scan_event',(41,1,datetime(2030,2,20,10),'RECEIVED',1),pymysql.IntegrityError(code,'private'))])
    with pytest.raises(pymysql.MySQLError): service.post_scan(7,41,SCAN_FORM)
    assert_transaction(connections[0],False)
    assert factory.call_count == 1


@pytest.mark.parametrize('code',[1205,1213])
def test_scan_retries_entire_transaction_and_reallocates(monkeypatch,code):
    connections, factory = connect(monkeypatch,
        [assigned(),('FOR UPDATE',(41,),pymysql.OperationalError(code,'private'))],
        scan_prefix()+[hub_step(),('MAX(scan_sequence)',(41,),{'next_sequence':2}),
                      ('INSERT INTO scan_event',(41,2,datetime(2030,2,20,10),'IN_TRANSIT',1),None)])
    service.post_scan(7,41,{**SCAN_FORM,'status':'IN_TRANSIT'})
    assert factory.call_count == 2
    assert_transaction(connections[0],False)
    assert_transaction(connections[1])


def test_retry_limit(monkeypatch):
    connections,factory = connect(monkeypatch,*[[('FOR UPDATE',(21,7),pymysql.OperationalError(1213,'private'))] for _ in range(3)])
    with pytest.raises(service.ValidationError,match='busy'): service.update_departure(7,21,DEPARTURE_FORM)
    assert factory.call_count == 3
    for connection in connections: assert_transaction(connection,False)


def test_uncertain_commit_not_retried(monkeypatch):
    connections,factory = connect(monkeypatch,scan_prefix()+[hub_step(),('MAX(scan_sequence)',(41,),{'next_sequence':1}),
        ('INSERT INTO scan_event',(41,1,datetime(2030,2,20,10),'RECEIVED',1),None)],
        commit_error=pymysql.OperationalError(2013,'private'))
    with pytest.raises(pymysql.OperationalError): service.post_scan(7,41,SCAN_FORM)
    assert factory.call_count == 1
    assert connections[0].events[-2:] == ['rollback','close']


@pytest.mark.parametrize('on_time,late,rate',[(0,0,None),(3,1,D('75.00')),(0,2,D('0.00'))])
def test_reports_owned_delivered_denominator(monkeypatch,on_time,late,rate):
    connections,_ = connect(monkeypatch,[("AND s.current_status = 'DELIVERED'",(7,),{'on_time':on_time,'late':late})],
                             [('WHERE v.carrier_account_id = %s',(7,),[DEPARTURE])])
    summary, departures = service.reports(7)
    assert summary['rate'] == rate and departures == [DEPARTURE]
    assert 'ROUND(100 *' in connections[1].events[0][0]


@pytest.fixture
def page_data(monkeypatch):
    monkeypatch.setattr(service,'dashboard',lambda owner: {'vehicles':[VEHICLE],'departures':[DEPARTURE],'shipments':[SHIPMENT]})
    monkeypatch.setattr(service,'list_vehicles',lambda owner: [VEHICLE])
    monkeypatch.setattr(service,'get_vehicle',lambda owner,vid: VEHICLE)
    monkeypatch.setattr(service,'list_departures',lambda owner: [DEPARTURE])
    monkeypatch.setattr(service,'get_departure',lambda owner,did: DEPARTURE)
    monkeypatch.setattr(service,'assigned_shipments',lambda owner: [SHIPMENT])
    monkeypatch.setattr(service,'tracking',lambda owner,sid: (SHIPMENT,[]))
    monkeypatch.setattr(service,'reports',lambda owner: ({'on_time':3,'late':1,'rate':D('75')},[DEPARTURE]))
    monkeypatch.setattr(service,'hubs',lambda: HUBS)
    monkeypatch.setattr(service,'lanes',lambda: LANES)


class Elements(HTMLParser):
    def __init__(self,html):
        super().__init__()
        self.elements=[]
        self.feed(html)
    def handle_starttag(self,tag,attrs):
        self.elements.append((tag,dict(attrs)))


@pytest.mark.parametrize('path',GETS)
def test_templates_navigation_and_security_headers(client,page_data,path):
    response=client.get(path)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Frame-Options'] == 'DENY'
    elements=Elements(response.get_data(as_text=True)).elements
    for tag,attrs in elements:
        if tag=='a' and attrs.get('href','').startswith('/carrier'):
            assert client.get(attrs['href']).status_code == 200
    if path in WRITES:
        assert any(t=='input' and a.get('name')=='csrf_token' for t,a in elements)


@pytest.mark.parametrize('path,operation,form',[(WRITES[0],'create_vehicle',VEHICLE_FORM),
    (WRITES[1],'update_vehicle',VEHICLE_FORM),(WRITES[2],'create_departure',DEPARTURE_FORM),
    (WRITES[3],'update_departure',DEPARTURE_FORM),(WRITES[4],'post_scan',SCAN_FORM)])
def test_successful_writes_prg_and_session_owner(client,page_data,monkeypatch,path,operation,form):
    mock=MagicMock(return_value=91)
    monkeypatch.setattr(service,operation,mock)
    response=client.post(path,data={**form,'csrf_token':'test-csrf','carrier_account_id':'999'})
    assert response.status_code == 303
    assert mock.call_args.args[0] == 7


@pytest.mark.parametrize('path,operation',[(WRITES[0],'create_vehicle'),(WRITES[1],'update_vehicle'),
    (WRITES[2],'create_departure'),(WRITES[3],'update_departure'),(WRITES[4],'post_scan')])
def test_form_validation_feedback(client,page_data,monkeypatch,path,operation):
    monkeypatch.setattr(service,operation,MagicMock(side_effect=service.ValidationError('Check the supplied value.')))
    response=client.post(path,data={'csrf_token':'test-csrf'})
    assert response.status_code == 400 and b'Check the supplied value.' in response.data


@pytest.mark.parametrize('path,operation',[(WRITES[1],'get_vehicle'),(WRITES[3],'get_departure'),(WRITES[4],'tracking')])
@pytest.mark.parametrize('method',['get','post'])
def test_foreign_record_routes_404(client,monkeypatch,path,operation,method):
    monkeypatch.setattr(service,operation,MagicMock(side_effect=service.NotFound))
    response=getattr(client,method)(path,data={'csrf_token':'test-csrf'})
    assert response.status_code == 404


@pytest.mark.parametrize('code,status',[(1644,409),(1062,409),(1452,409),(2003,503),(2013,503)])
def test_safe_errors(client,page_data,monkeypatch,caplog,code,status):
    monkeypatch.setattr(service,'post_scan',MagicMock(side_effect=pymysql.OperationalError(code,'PRIVATE details')))
    response=client.post(WRITES[-1],data={**SCAN_FORM,'csrf_token':'test-csrf'})
    assert response.status_code == status
    assert b'PRIVATE' not in response.data and 'PRIVATE' not in caplog.text


def test_booked_departure_form_disables_logistics(client,page_data):
    controls=Elements(client.get(WRITES[3]).get_data(as_text=True)).elements
    for field in ('vehicle_id','lane','departure_datetime'):
        assert any(a.get('name')==field and 'disabled' in a for t,a in controls)
        assert any(t=='input' and a.get('type')=='hidden' and a.get('name')==field for t,a in controls)
    assert any(a.get('name')=='max_total_weight_kg' and 'disabled' not in a for t,a in controls)


def test_dashboard_empty_states(client,page_data,monkeypatch):
    monkeypatch.setattr(service,'dashboard',lambda owner:{'vehicles':[],'departures':[],'shipments':[]})
    response=client.get('/carrier')
    assert response.status_code==200
    for text in (b'No vehicles yet',b'No departures to display',b'No shipments are booked'):
        assert text in response.data


def test_terminal_scan_history_has_no_post_form(client,page_data,monkeypatch):
    monkeypatch.setattr(service,'tracking',lambda owner,sid:({**SHIPMENT,'current_status':'DELIVERED','delivery_outcome':'ON_TIME'},[]))
    response=client.get(WRITES[-1])
    assert b'Its scan history is complete' in response.data
    assert b'Record scan' not in response.data


def test_expired_session_cannot_write(client,offline):
    with client.session_transaction() as session: session['expires_at']=1
    assert client.post(WRITES[0],data={'csrf_token':'test-csrf'}).status_code==400
    offline.assert_not_called()


def test_missing_hub_rolls_back_vehicle_create(monkeypatch):
    connections, _ = connect(monkeypatch, [("BINARY a.role = 'CARRIER'", (7,), {'account_id':7}),
        ('SELECT hub_id FROM hub', (1,), None)])
    with pytest.raises(service.ValidationError, match='existing hub'):
        service.create_vehicle(7, VEHICLE_FORM)
    assert_transaction(connections[0], False)


def test_missing_lane_rolls_back_departure_create(monkeypatch):
    connections, _ = connect(monkeypatch, vehicle_steps() + [('SELECT origin_hub_id FROM lane', (1,2), None)])
    with pytest.raises(service.ValidationError, match='existing directed lane'):
        service.create_departure(7, DEPARTURE_FORM)
    assert_transaction(connections[0], False)


def test_vehicle_update_subtype_failure_rolls_back_home_hub(monkeypatch):
    connections, _ = connect(monkeypatch, vehicle_steps(True) + [hub_step(),
        ('UPDATE vehicle SET home_hub_id', (1,11,7), None),
        ('UPDATE box_truck', (D('20'),D('5000'),11), pymysql.IntegrityError(4025,'private'))])
    with pytest.raises(pymysql.MySQLError): service.update_vehicle(7,11,VEHICLE_FORM)
    assert_transaction(connections[0],False)


def test_departure_update_failure_rolls_back(monkeypatch):
    connections, _ = connect(monkeypatch, [departure_lock(),load_step()] + vehicle_steps() + [lane_step(),
        ('UPDATE departure', (11,1,2,datetime(2030,2,20,10),D('100'),21), pymysql.IntegrityError(1452,'private'))])
    with pytest.raises(pymysql.MySQLError): service.update_departure(7,21,DEPARTURE_FORM)
    assert_transaction(connections[0],False)


def test_tracking_is_owner_scoped_and_sequence_ordered(monkeypatch):
    connections,_ = connect(monkeypatch,[assigned(), ('ORDER BY e.scan_sequence',(7,41),[])])
    assert service.tracking(7,41) == (SHIPMENT,[])
    assert 'v.carrier_account_id = %s' in connections[0].events[1][0]


def test_vehicle_list_is_owner_scoped_and_classifies_subtypes(monkeypatch):
    rows=[dict(VEHICLE),{**VEHICLE,'box_id':None,'van_id':11},{**VEHICLE,'box_id':None,'rail_id':11},
          {**VEHICLE,'box_id':None},{**VEHICLE,'van_id':11}]
    connect(monkeypatch,[('WHERE v.carrier_account_id = %s',(7,),rows)])
    assert [row['kind'] for row in service.list_vehicles(7)] == [
        'BOX_TRUCK','REFRIGERATED_VAN','RAIL_CAR','UNCLASSIFIED','INVALID']


def test_dashboard_upcoming_uses_eastern_clock_and_session_owner(monkeypatch):
    owner_calls=[]
    monkeypatch.setattr(service,'list_vehicles',lambda owner: owner_calls.append(owner) or [VEHICLE])
    monkeypatch.setattr(service,'assigned_shipments',lambda owner: owner_calls.append(owner) or [SHIPMENT])
    monkeypatch.setattr(service,'list_departures',lambda owner: owner_calls.append(owner) or [
        {**DEPARTURE,'departure_datetime':datetime(2000,1,1)},
        {**DEPARTURE,'departure_datetime':datetime(9998,1,1)}])
    data=service.dashboard(7)
    assert owner_calls == [7,7,7]
    assert len(data['departures']) == 1 and data['departures'][0]['departure_datetime'].year == 9998
    assert data['vehicles'] == [VEHICLE] and data['shipments'] == [SHIPMENT]


@pytest.mark.parametrize('path',GETS)
def test_database_outage_get_pages_safe(client,monkeypatch,path,caplog):
    monkeypatch.setattr(db,'get_connection',MagicMock(side_effect=pymysql.OperationalError(2003,'PRIVATE')))
    response=client.get(path)
    assert response.status_code == 503
    assert b'PRIVATE' not in response.data and 'PRIVATE' not in caplog.text


@pytest.mark.parametrize('kind',['REFRIGERATED_VAN','RAIL_CAR','UNCLASSIFIED'])
def test_vehicle_edit_subtype_specific_controls(client,page_data,monkeypatch,kind):
    monkeypatch.setattr(service,'get_vehicle',lambda owner,vid:{**VEHICLE,'kind':kind})
    response=client.get(WRITES[1])
    assert response.status_code == 200
    names={attrs.get('name') for tag,attrs in Elements(response.get_data(as_text=True)).elements if tag=='input'}
    for subtype,(_,fields) in service.SUBTYPES.items():
        for field in fields:
            assert (field in names) == (subtype == kind)


def test_form_empty_reference_data(client,page_data,monkeypatch):
    monkeypatch.setattr(service,'hubs',lambda:[])
    monkeypatch.setattr(service,'lanes',lambda:[])
    assert b'No hubs are available' in client.get(WRITES[0]).data
    assert b'A vehicle and a directed lane are required' in client.get(WRITES[2]).data
    assert b'No hubs are available for scan posting' in client.get(WRITES[-1]).data
