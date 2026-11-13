"""Single-use audited seed loader. Default operation is read-only preflight.

Execution requires separate user approval, a verified-backup receipt, and a
new durable journal. Never retries. Never prints SQL, credentials or errors
containing driver text. Do not use while application writers are active.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from app.db import get_connection
from analytics_checks.fixture import KEYS, ROOT, SEED, verify_manifest


EXPECTED_BASELINE = {
    'account': [(540001, 'SHIPPER'), (540002, 'CARRIER'), (540003, 'VIEWER')],
    'shipper': [(540001,)], 'carrier': [(540002,)], 'viewer': [(540003,)],
}


def check_baseline(connection):
    """Require the audited three-account-only baseline, not just free IDs."""
    verify_manifest()
    with connection.cursor() as cur:
        cur.execute('SELECT DATABASE(), VERSION()')
        schema, version = cur.fetchone()
        if schema != 'dkhando' or not version.startswith('10.5.'):
            raise RuntimeError('Target must be dkhando on reviewed MariaDB 10.5')
        cur.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
        if dict(cur.fetchall()) != {t: 'InnoDB' for t in KEYS}:
            raise RuntimeError('Table inventory differs from reviewed schema')
        for table in KEYS:
            columns = 'account_id, role' if table == 'account' else ', '.join(KEYS[table])
            cur.execute(f'SELECT {columns} FROM {table} ORDER BY {columns}')
            if list(cur.fetchall()) != EXPECTED_BASELINE.get(table, []):
                raise RuntimeError(f'Baseline changed or partial seed exists: {table}; stop and re-audit')
        cur.execute("SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_TYPE='PROCEDURE'")
        if ('book_shipment',) not in cur.fetchall():
            raise RuntimeError('Missing booking procedure')
        cur.execute("SELECT TRIGGER_NAME, ACTION_TIMING, EVENT_MANIPULATION, EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()")
        if set(cur.fetchall()) != {
                ('trg_scan_event_before_insert', 'BEFORE', 'INSERT', 'scan_event'),
                ('trg_scan_event_after_insert', 'AFTER', 'INSERT', 'scan_event')}:
            raise RuntimeError('Scan trigger inventory changed')


def statements():
    # Valid only for the hash-pinned seed, which has no delimiter blocks or
    # semicolons inside literals. Changing the seed requires manifest review.
    verify_manifest()
    text = re.sub(r'--[^\n]*', '', SEED.read_text())
    return [s.strip() for s in text.split(';') if s.strip()]


def verify_receipt(path):
    receipt = json.loads(path.read_text())
    required = ('schema', 'backup_path', 'sha256', 'restore_test_schema',
                'restore_verified', 'writers_paused', 'schema_definitions_verified')
    if any(k not in receipt for k in required):
        raise RuntimeError('Incomplete backup receipt')
    if (receipt['schema'] != 'dkhando' or receipt['restore_verified'] is not True
            or receipt['writers_paused'] is not True
            or receipt['schema_definitions_verified'] is not True
            or not receipt['restore_test_schema']
            or receipt['restore_test_schema'].lower() == 'dkhando'):
        raise RuntimeError('Backup/maintenance prerequisites not confirmed')
    backup = Path(receipt['backup_path'])
    if backup.resolve().is_relative_to(ROOT):
        raise RuntimeError('Backups must be stored outside the repository')
    if not backup.is_absolute() or not backup.is_file() or backup.stat().st_size == 0:
        raise RuntimeError('Backup file is missing or empty')
    if backup.stat().st_mode & 0o077:
        raise RuntimeError('Backup must have owner-only permissions')
    digest = hashlib.sha256()
    with backup.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != receipt['sha256']:
        raise RuntimeError('Backup checksum mismatch')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approval')
    parser.add_argument('--backup-receipt', type=Path)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args(argv)
    if args.execute:
        if (args.approval != 'LOAD-DKHANDO-ONCE' or not args.backup_receipt
                or not args.journal or not args.journal.is_absolute()):
            parser.error('Execution requires --approval LOAD-DKHANDO-ONCE, --backup-receipt, and an absolute --journal path')
        if args.journal.resolve().is_relative_to(ROOT) or args.backup_receipt.resolve().is_relative_to(ROOT):
            raise RuntimeError('Journal and receipt must be outside the repository')
        verify_receipt(args.backup_receipt)
    connection = get_connection()
    journal = None
    try:
        with connection.cursor() as cur:
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        check_baseline(connection)
        connection.rollback()
        if not args.execute:
            print('Read-only baseline checks passed; no seed statements executed')
            return
        # O_EXCL prevents accidental reuse, including after a failed run.
        fd = os.open(args.journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        journal = os.fdopen(fd, 'w')
        def record(event):
            journal.write(json.dumps(event) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
        record({'event': 'started', 'schema': 'dkhando',
                'seed_sha256': hashlib.sha256(SEED.read_bytes()).hexdigest()})
        # Reference rows commit at the seed's explicit COMMIT. Procedure calls
        # require idle connections. Each scan block starts its own transaction.
        with connection.cursor() as cur:
            for number, sql in enumerate(statements(), 1):
                record({'event': 'attempt', 'statement': number})
                cur.execute(sql)
                while cur.nextset():
                    pass
                record({'event': 'completed', 'statement': number})
        record({'event': 'finished'})
        print('Seed completed once. Run read-only validation before reopening writers.')
    finally:
        connection.rollback()
        connection.close()
        if journal is not None:
            journal.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Driver exceptions can contain account or SQL data. Never print them.
        print(f'Stopped ({type(exc).__name__}). Do not retry; inspect the journal and perform read-only inventory.', file=sys.stderr)
        sys.exit(1)
