"""Parse the reviewed seed format without executing SQL or reading passwords."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / 'sql/02_sample_data.sql'
KEYS = {
    'account': ('account_id',), 'carrier': ('account_id',),
    'shipper': ('account_id',), 'viewer': ('account_id',),
    'hub': ('hub_id',), 'lane': ('origin_hub_id', 'destination_hub_id'),
    'vehicle': ('vehicle_id',), 'box_truck': ('vehicle_id',),
    'refrigerated_van': ('vehicle_id',), 'rail_car': ('vehicle_id',),
    'departure': ('departure_id',), 'shipment': ('shipment_id',),
    'booking': ('shipment_id', 'departure_id'),
    'scan_event': ('shipment_id', 'scan_sequence'),
}
PROTECTED = {540001: 'SHIPPER', 540002: 'CARRIER', 540003: 'VIEWER'}


def fixture():
    source = re.sub(r'--[^\n]*', '', SEED.read_text())
    data = {table: [] for table in KEYS}
    for table, columns, values in re.findall(
            r'INSERT INTO (\w+)\s*\((.*?)\)\s*VALUES\s*(.*?);', source, re.S):
        names = [c.strip() for c in columns.split(',')]
        for literal in re.findall(r'\([^()]*\)', values):
            values_tuple = ast.literal_eval(literal)
            if not isinstance(values_tuple, tuple):
                values_tuple = (values_tuple,)
            row = dict(zip(names, values_tuple, strict=True))
            row.pop('password', None)
            data[table].append(row)
    data['booking'] = [dict(shipment_id=int(s), departure_id=int(d)) for s, d in
                       re.findall(r'CALL book_shipment\((\d+),\s*(\d+)\)', source)]
    return data


def manifest():
    return {'seed_sha256': hashlib.sha256(SEED.read_bytes()).hexdigest(),
            'protected_accounts': list(PROTECTED),
            'tables': {t: {'key_columns': list(KEYS[t]),
                          'keys': [[r[k] for k in KEYS[t]] for r in rows]}
                       for t, rows in fixture().items()}}


def verify_manifest():
    expected = json.loads((ROOT / 'analytics_checks/seed_manifest.json').read_text())
    if manifest() != expected:
        raise RuntimeError('Seed differs from reviewed manifest; re-audit before proceeding')
