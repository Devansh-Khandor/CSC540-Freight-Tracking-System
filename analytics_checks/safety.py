"""SQL allowlist for the analytics runner; no write interface is exposed."""
import re


class SelectCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        # Current reports use plain SELECT only. Reject comments, multiple
        # statements, file output and locking reads. The server READ ONLY
        # transaction also rejects persistent writes by stored functions.
        normalized = sql.strip()
        if (not re.match(r'^SELECT\b', normalized, re.I)
                or re.search(r';|--|/\*|\b(INTO|FOR\s+UPDATE|LOCK|SLEEP|BENCHMARK)\b',
                             normalized, re.I)):
            raise RuntimeError('Analytics runner permits plain SELECT statements only')
        return self._cursor.execute(sql, params or ())

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()


class ReadOnlyConnection:
    """Use only after starting a server-enforced READ ONLY transaction."""
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return SelectCursor(self._connection.cursor())
