"""Fixture preservation plus independent full-dataset report expectations.

Additional records are permitted. They participate in lane ranks and carrier
running totals; filtering those window outputs after execution is not treated
as an isolated-fixture result.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from app import queries
from analytics_checks.fixture import fixture, KEYS, PROTECTED, verify_manifest


def read_rows(connection, table, columns):
    cursor = connection.cursor()
    try:
        cursor.execute(f"SELECT {', '.join(columns)} FROM {table}")
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def normalize(value):
    if isinstance(value, (date, datetime)):
        return str(value)
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    return value


def validate_combined(connection):
    if not __debug__:
        raise RuntimeError("Validation requires assertions enabled; do not use python -O")
    verify_manifest()
    expected = fixture()
    live = {}
    for table, rows in expected.items():
        columns = list(rows[0])
        live[table] = read_rows(connection, table, columns)
        actual = {tuple(r[k] for k in KEYS[table]): r for r in live[table]}
        for row in rows:
            key = tuple(row[k] for k in KEYS[table])
            assert key in actual, f'Missing fixture row: {table} {key}'
            assert all(normalize(actual[key][k]) == normalize(v) for k, v in row.items()), (
                f'Changed fixture row: {table} {key}')

    accounts = {r['account_id']: r['role'] for r in live['account']}
    for account_id, role in PROTECTED.items():
        assert accounts.get(account_id) == role, f'Protected account role changed: {account_id}'
        for subtype in ('shipper', 'carrier', 'viewer'):
            member = any(r['account_id'] == account_id for r in live[subtype])
            assert member == (subtype.upper() == role), f'Protected subtype changed: {account_id}'

    q1 = queries.get_vehicle_counts_by_carrier(connection)
    carriers = {r['account_id'] for r in live['carrier']}
    counts = {c: [0, 0, 0] for c in carriers}
    for vehicle in live['vehicle']:
        for i, subtype in enumerate(('box_truck', 'refrigerated_van', 'rail_car')):
            counts[vehicle['carrier_account_id']][i] += any(
                r['vehicle_id'] == vehicle['vehicle_id'] for r in live[subtype])
    assert list(q1) == [(c, *counts[c]) for c in sorted(carriers)]
    known = {r[0]: tuple(r[1:]) for r in q1 if r[0] in (1, 2, 3, 540002)}
    assert known == {1: (2, 1, 0), 2: (2, 1, 0), 3: (0, 0, 1), 540002: (0, 0, 0)}
    assert not any(v['carrier_account_id'] == 540002 for v in live['vehicle'])
    # Exactly four known carriers; unrelated future carriers are allowed.

    shipments = {r['shipment_id']: r for r in live['shipment']}
    departures = {r['departure_id']: r for r in live['departure']}
    vehicles = {r['vehicle_id']: r for r in live['vehicle']}
    booked = defaultdict(list)
    for b in live['booking']:
        booked[b['departure_id']].append(shipments[b['shipment_id']])
    weights = {d: sum((s['weight_kg'] for s in booked[d]), Decimal(0)) for d in departures}
    ratios = {i: weights[i] / d['max_total_weight_kg'] for i, d in departures.items()}
    q2 = queries.get_departure_utilization_ranking(connection)
    assert len(q2) == len(departures)
    for row in q2:
        i, origin, destination, timestamp, weight, capacity, percent, rank = row
        d = departures[i]
        lane = (d['origin_hub_id'], d['destination_hub_id'])
        expected_rank = 1 + sum(ratios[j] > ratios[i] for j, other in departures.items()
                                if (other['origin_hub_id'], other['destination_hub_id']) == lane)
        assert (origin, destination, timestamp, weight, capacity, percent, rank) == (
            *lane, d['departure_datetime'], weights[i], d['max_total_weight_kg'],
            (ratios[i] * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), expected_rank)
        assert 0 <= percent <= 100
    assert len({r[0] for r in q2}) == len(departures)
    order = [(r[1], r[2], r[7]) for r in q2]
    assert order == sorted(order)
    for i, weight in enumerate((7500, 3700, 4000, 7000, 3500, 2800, 2000, 4000, 2000, 2000), 1):
        assert weights[i] == weight, f'Fixture departure {i} load changed'

    q3 = queries.get_scan_time_intervals(connection, 1)
    assert len(q3) == 4
    assert tuple(r[0] for r in q3) == (1,) * 4
    assert tuple(r[1] for r in q3) == (1, 2, 3, 4)
    assert tuple(r[2] for r in q3) == ('RECEIVED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED')
    assert tuple(r[5] for r in q3) == (None, 65, 865, 90)
    assert tuple(str(r[3]) for r in q3) == tuple(
        r['scan_timestamp'] for r in expected['scan_event'] if r['shipment_id'] == 1)
    assert q3[0][4] is None
    for previous, current in zip(q3, q3[1:]):
        assert current[4] == previous[3]

    delivered = {}
    for scan in live['scan_event']:
        if scan['status'] == 'DELIVERED':
            sid = scan['shipment_id']
            delivered[sid] = min(delivered.get(sid, scan['scan_timestamp']), scan['scan_timestamp'])
    base = []
    for b in live['booking']:
        sid = b['shipment_id']
        if sid in delivered:
            carrier = vehicles[departures[b['departure_id']]['vehicle_id']]['carrier_account_id']
            base.append((carrier, sid, delivered[sid], shipments[sid]['weight_kg']))
    totals = defaultdict(Decimal)
    expected_q4 = []
    fixture_totals = defaultdict(Decimal)
    for carrier, sid, timestamp, weight in sorted(base, key=lambda r: (r[0], r[2], r[1])):
        totals[carrier] += weight
        expected_q4.append((carrier, sid, timestamp, weight, totals[carrier]))
        if 1 <= sid <= 23:
            fixture_totals[carrier] += weight
    assert list(queries.get_running_delivered_weight_by_carrier(connection)) == expected_q4
    assert sum(1 <= r[1] <= 23 for r in expected_q4) == 14
    assert dict(fixture_totals) == {1: 18000, 2: 9500, 3: 3500}

    expected_q5 = []
    for i, d in sorted(departures.items()):
        count = len({s['shipper_account_id'] for s in booked[i]})
        if count >= 2:
            expected_q5.append((i, d['origin_hub_id'], d['destination_hub_id'], count))
    assert list(queries.get_departures_with_multiple_shippers(connection)) == expected_q5
    assert [r for r in expected_q5 if 1 <= r[0] <= 10] == [(1, 1, 2, 2), (2, 2, 3, 2), (3, 4, 5, 2)]

    scanned = {r['shipment_id'] for r in live['scan_event']}
    expected_q6 = [tuple(s[k] for k in ('shipment_id', 'shipper_account_id', 'origin_hub_id',
                                       'destination_hub_id', 'weight_kg', 'promised_delivery_date'))
                   for sid, s in sorted(shipments.items()) if sid not in scanned]
    assert list(queries.get_shipments_without_scans(connection)) == expected_q6
    assert [r[0] for r in expected_q6 if 1 <= r[0] <= 23] == [14]
    print('PASS Q1–Q6: fixture values, full-dataset aggregates, and protected memberships')
