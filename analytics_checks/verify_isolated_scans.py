"""Explicit write checks for an already-installed disposable LOCAL schema only.

Never imported by Flask or the offline test suite. Each scenario rolls back its
own temporary shipment and scans; the sample fixture remains unchanged.
Run: python -m analytics_checks.verify_isolated_scans --schema csc540_scan69_NAME
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import re

import pymysql
from dotenv import dotenv_values


def run_checks(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE(), VERSION()')
        schema, version = cursor.fetchone()
        if (connection.host != '127.0.0.1' or connection.port != 3307
                or not re.fullmatch(r'csc540_scan69_[a-z0-9]+', schema or '')
                or not version.startswith('10.5.')):
            raise RuntimeError('Refusing non-isolated target')
    connection.rollback()
    cases = 0
    base = datetime(2030, 3, 1, 8)
    four = ['RECEIVED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED']
    five = ['RECEIVED', 'IN_TRANSIT', 'ARRIVED_AT_HUB', 'OUT_FOR_DELIVERY', 'DELIVERED']

    def scenario(history, bad=None, late=False):
        nonlocal cases
        try:
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')
                connection.begin()
                cursor.execute('''INSERT INTO shipment (shipper_account_id,origin_hub_id,
                    destination_hub_id,weight_kg,promised_delivery_date)
                    VALUES (4,1,2,10,%s)''', ('2030-02-28' if late else '2030-03-01',))
                sid = cursor.lastrowid

                def insert(sequence, status, timestamp):
                    cursor.execute('SELECT shipment_id FROM shipment WHERE shipment_id=%s FOR UPDATE', (sid,))
                    cursor.execute('''INSERT INTO scan_event
                        (shipment_id,scan_sequence,scan_timestamp,status,hub_id)
                        VALUES (%s,%s,%s,%s,2)''', (sid, sequence, timestamp, status))

                for sequence, status in enumerate(history, 1):
                    insert(sequence, status, base + timedelta(minutes=sequence))
                    cursor.execute('SELECT current_status,delivery_outcome FROM shipment WHERE shipment_id=%s', (sid,))
                    expected = ('LATE' if late else 'ON_TIME') if status == 'DELIVERED' else None
                    if cursor.fetchone() != (status, expected):
                        raise AssertionError('AFTER trigger state mismatch')
                if bad:
                    sequence, status, timestamp, message = bad
                    try:
                        insert(sequence, status, timestamp)
                    except pymysql.MySQLError as exc:
                        if exc.args[0] != 1644 or exc.args[1] != message:
                            raise AssertionError('Unexpected rejection reason') from None
                    else:
                        raise AssertionError('Invalid scan was accepted')
                    cursor.execute('SELECT COUNT(*) FROM scan_event WHERE shipment_id=%s', (sid,))
                    if cursor.fetchone()[0] != len(history):
                        raise AssertionError('Rejected scan changed history')
                    cursor.execute('SELECT current_status,delivery_outcome FROM shipment WHERE shipment_id=%s', (sid,))
                    last = history[-1] if history else None
                    expected = ('LATE' if late else 'ON_TIME') if last == 'DELIVERED' else None
                    if cursor.fetchone() != (last, expected):
                        raise AssertionError('Rejected scan changed shipment')
            cases += 1
        finally:
            connection.rollback()

    scenario(four)
    scenario(five)
    scenario(four, late=True)
    scenario(five, late=True)
    scenario(['RECEIVED','IN_TRANSIT','IN_TRANSIT','ARRIVED_AT_HUB',
              'ARRIVED_AT_HUB','IN_TRANSIT','OUT_FOR_DELIVERY','OUT_FOR_DELIVERY','DELIVERED'])
    for status in ('IN_TRANSIT','ARRIVED_AT_HUB','OUT_FOR_DELIVERY','DELIVERED'):
        scenario([], (1,status,base,'The first scan must be RECEIVED'))
    for sequence in (0,2):
        message = 'scan_sequence must be positive' if sequence == 0 else 'scan_sequence must be 1 initially, then exactly previous sequence plus 1'
        scenario([], (sequence,'RECEIVED',base,message))
    scenario(['RECEIVED'], (3,'IN_TRANSIT',base+timedelta(minutes=3),
             'scan_sequence must be 1 initially, then exactly previous sequence plus 1'))
    scenario(['RECEIVED','IN_TRANSIT'], (3,'OUT_FOR_DELIVERY',base,
             'Scan timestamps cannot move backward'))
    for prefix, invalid in [
        (['RECEIVED'], ['RECEIVED','ARRIVED_AT_HUB','OUT_FOR_DELIVERY','DELIVERED']),
        (four[:2], ['RECEIVED','DELIVERED']),
        (five[:3], ['RECEIVED','DELIVERED']),
        (four[:3], ['RECEIVED','IN_TRANSIT','ARRIVED_AT_HUB']),
        (four, five),
    ]:
        for status in invalid:
            scenario(prefix, (len(prefix)+1,status,base+timedelta(hours=1),
                     'Invalid or regressing scan status transition'))
    print(f'PASS: {cases} isolated trigger scenarios; temporary rows rolled back.')
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'csc540_scan69_[a-z0-9]+', args.schema):
        parser.error('Only csc540_scan69_* disposable schemas are permitted')
    config = dotenv_values(Path(__file__).resolve().parents[1] / '.env', interpolate=False)
    if (config.get('DB_HOST'), config.get('DB_PORT')) != ('127.0.0.1', '3307'):
        raise RuntimeError('Local endpoint required')
    connection = pymysql.connect(host='127.0.0.1', port=3307, database=args.schema,
        user=config['DB_USER'], password=config['DB_PASSWORD'], charset='utf8mb4',
        autocommit=False, connect_timeout=10, read_timeout=10, write_timeout=10)
    try:
        run_checks(connection)
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Isolated scan verification failed: ' + type(exc).__name__) from None
