"""Offline tests; SQLite is an SQL oracle, not a MariaDB compatibility claim."""
import contextlib
from datetime import date, datetime
from decimal import Decimal
import os
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

from app import queries
from analytics_checks.combined import validate_combined
from analytics_checks.fixture import fixture, manifest, verify_manifest, KEYS
from analytics_checks.load_seed import statements, check_baseline, EXPECTED_BASELINE, main as loader_main
from analytics_checks.safety import ReadOnlyConnection
from test_queries import _require_test_schema


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.db.cursor()
        self.special = None

    def execute(self, sql, params=()):
        self.special = None
        if sql.strip() == 'SELECT DATABASE()':
            self.special = [(self.connection.schema,)]
            return
        sql = sql.replace('TIMESTAMPDIFF(\n                MINUTE,', "TIMESTAMPDIFF(\n                'MINUTE',")
        self.cursor.execute(sql.replace('%s', '?'), params)

    def fetchall(self):
        if self.special is not None:
            return self.special
        names = [c[0] for c in self.cursor.description]
        output = []
        for row in self.cursor.fetchall():
            converted = []
            for name, value in zip(names, row):
                if value is not None:
                    if name.endswith('timestamp') or name == 'departure_datetime':
                        value = datetime.fromisoformat(value)
                    elif name == 'promised_delivery_date':
                        value = date.fromisoformat(value)
                    elif name in ('weight_kg', 'max_total_weight_kg', 'utilization_percentage'):
                        value = Decimal(str(value))
                converted.append(value)
            output.append(tuple(converted))
        return output

    def fetchone(self):
        return self.fetchall()[0]

    def close(self):
        self.cursor.close()


class Database:
    schema = 'dkhando'

    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.create_function('TIMESTAMPDIFF', 3, lambda unit, a, b: None if a is None else
                                int((datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds()/60))
        for table, rows in fixture().items():
            columns = list(rows[0])
            definitions = []
            for name in columns:
                value = rows[0][name]
                dtype = 'TEXT' if isinstance(value, str) else 'NUMERIC'
                definitions.append(f'{name} {dtype}')
            self.db.execute(f"CREATE TABLE {table} ({', '.join(definitions)})")
            self.db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in columns)})",
                                [tuple(row[c] for c in columns) for row in rows])
        self.db.executemany('INSERT INTO account VALUES (?,?)',
                            [(540001, 'SHIPPER'), (540002, 'CARRIER'), (540003, 'VIEWER')])
        for table, account in [('shipper',540001),('carrier',540002),('viewer',540003)]:
            self.db.execute(f'INSERT INTO {table} VALUES (?)', (account,))

    def cursor(self):
        return Cursor(self)


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.raw = Database()
        self.connection = ReadOnlyConnection(self.raw)

    def tearDown(self):
        self.raw.db.close()

    def validate(self):
        with contextlib.redirect_stdout(None):
            validate_combined(self.connection)

    def test_combined_fixture_all_six_queries(self):
        self.validate()

    def test_future_rows_affect_ranks_and_running_totals(self):
        db = self.raw.db
        db.execute("INSERT INTO carrier VALUES (999)")
        db.execute("INSERT INTO account VALUES (999, 'CARRIER')")
        db.execute("INSERT INTO departure VALUES (99,101,1,2,'2025-01-01 09:00:00',100)")
        db.execute("INSERT INTO shipment VALUES (99,4,1,2,100,'2025-01-03')")
        db.execute('INSERT INTO booking VALUES (99,99)')
        db.execute("INSERT INTO scan_event VALUES (99,1,'2025-01-02 10:00:00','DELIVERED',2)")
        db.execute("INSERT INTO shipment VALUES (100,4,1,2,100,'2027-01-03')")
        # Deliberately adds a same-lane rank tie and a prior carrier-1 delivery;
        # fixture totals still hold but global running totals must increase.
        self.validate()

    def test_missing_original_scan_fails(self):
        self.raw.db.execute('DELETE FROM scan_event WHERE shipment_id=1 AND scan_sequence=3')
        with self.assertRaises(AssertionError):
            self.validate()

    def test_original_scan_record_contract(self):
        # Provisional reference: original non-arrival records reviewed in the
        # repository. This digest is NOT a claim of comparison with the PDF.
        import hashlib
        import json
        from collections import Counter
        scans = fixture()['scan_event']
        self.assertEqual(len(scans), 69)
        self.assertEqual(Counter(r['status'] for r in scans),
                         {'RECEIVED': 22, 'IN_TRANSIT': 19,
                          'OUT_FOR_DELIVERY': 14, 'DELIVERED': 14})
        digest = hashlib.sha256(json.dumps(scans, sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, '6934d25fdc3e6e9dfeb920017e21385e34098ea44ebc8099cf9420021e74e845')
        last = {}
        for scan in scans:
            previous = last.get(scan['shipment_id'])
            self.assertEqual(scan['scan_sequence'], previous['scan_sequence'] + 1 if previous else 1)
            last[scan['shipment_id']] = scan
        self.assertEqual(Counter(r['status'] for r in last.values()),
                         {'DELIVERED': 14, 'IN_TRANSIT': 5, 'RECEIVED': 3})
        self.assertEqual({r['shipment_id'] for r in fixture()['shipment']} - last.keys(), {14})

    def test_shipment_one_original_timestamps_and_intervals(self):
        rows = queries.get_scan_time_intervals(self.connection, 1)
        self.assertEqual([str(r[3]) for r in rows],
                         ['2026-03-01 21:00:00', '2026-03-01 22:05:00',
                          '2026-03-02 12:30:00', '2026-03-02 14:00:00'])
        self.assertEqual([r[5] for r in rows], [None, 65, 865, 90])

    def test_protected_membership_change_fails(self):
        self.raw.db.execute('DELETE FROM viewer WHERE account_id=540003')
        with self.assertRaises(AssertionError):
            self.validate()

    def test_protected_carrier_untyped_vehicle_fails(self):
        self.raw.db.execute('INSERT INTO vehicle VALUES (999,540002,1)')
        with self.assertRaises(AssertionError):
            self.validate()

    def test_fixture_weight_change_fails(self):
        self.raw.db.execute('UPDATE shipment SET weight_kg=3001 WHERE shipment_id=1')
        with self.assertRaises(AssertionError):
            self.validate()

    def test_wrong_running_total_fails(self):
        with patch.object(queries, 'get_running_delivered_weight_by_carrier', return_value=[]):
            with self.assertRaises(AssertionError):
                self.validate()

    def test_read_only_allowlist(self):
        for sql in ('INSERT INTO account VALUES (1)', 'CALL book_shipment(1,1)',
                    'DELETE FROM account', 'SELECT 1; DELETE FROM account',
                    'SELECT * FROM account FOR UPDATE', "SELECT 1 INTO OUTFILE 'x'"):
            with self.assertRaises(RuntimeError):
                self.connection.cursor().execute(sql)

    def test_guard_requires_explicit_combined_opt_in(self):
        with patch.dict(os.environ, {'ANALYTICS_TEST_SCHEMA':'dkhando'}, clear=True):
            with self.assertRaises(RuntimeError):
                _require_test_schema(self.connection)
        with patch.dict(os.environ, {'ANALYTICS_TEST_SCHEMA':'dkhando',
                'ANALYTICS_TEST_MODE':'combined','ANALYTICS_ALLOW_COMBINED':'dkhando'}, clear=True):
            self.assertEqual(_require_test_schema(self.connection), 'dkhando')
            self.raw.schema = 'other'
            with self.assertRaises(RuntimeError):
                _require_test_schema(self.connection)

    def test_isolated_guard_retained(self):
        self.raw.schema = 'isolated_fixture'
        with patch.dict(os.environ, {'ANALYTICS_TEST_SCHEMA':'isolated_fixture'}, clear=True):
            self.assertEqual(_require_test_schema(self.connection), 'isolated_fixture')

    def test_manifest_and_statement_boundaries(self):
        verify_manifest()
        result = manifest()
        self.assertEqual(len(result['tables']['scan_event']['keys']), 69)
        self.assertEqual(len(result['tables']['booking']['keys']), 22)
        self.assertEqual(sum(s.startswith('CALL ') for s in statements()), 22)
        self.assertEqual(sum(s == 'COMMIT' for s in statements()), 23)
        self.assertTrue(set(result['protected_accounts']).isdisjoint(
            key[0] for key in result['tables']['account']['keys']))

    def baseline_connection(self, changed_table=None):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ('dkhando', '10.5.22-MariaDB')
        results = [list((t, 'InnoDB') for t in KEYS)]
        for table in KEYS:
            rows = list(EXPECTED_BASELINE.get(table, []))
            if table == changed_table:
                rows.append((1,))
            results.append(rows)
        results.extend([[('book_shipment',)], [
            ('trg_scan_event_before_insert', 'BEFORE', 'INSERT', 'scan_event'),
            ('trg_scan_event_after_insert', 'AFTER', 'INSERT', 'scan_event')]])
        cursor.fetchall.side_effect = results
        return connection

    def test_loader_baseline_accepts_only_empty_fixture_spaces(self):
        check_baseline(self.baseline_connection())
        for table in KEYS:
            with self.subTest(table=table), self.assertRaises(RuntimeError):
                check_baseline(self.baseline_connection(table))

    def test_loader_wrong_target_fails(self):
        connection = self.baseline_connection()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = ('other', '10.5.22-MariaDB')
        with self.assertRaises(RuntimeError):
            check_baseline(connection)

    def test_loader_default_is_read_only(self):
        connection = self.baseline_connection()
        with patch('analytics_checks.load_seed.get_connection', return_value=connection):
            with contextlib.redirect_stdout(None):
                loader_main([])
        cursor = connection.cursor.return_value.__enter__.return_value
        for call in cursor.execute.call_args_list:
            self.assertTrue(call.args[0].startswith(('SELECT ', 'START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')))
        connection.close.assert_called_once()

    def test_query3_invalid_ids(self):
        for value in (True, False, 0, -1, '1', None):
            with self.assertRaises(ValueError):
                queries.get_scan_time_intervals(self.connection, value)


if __name__ == '__main__':
    unittest.main()
