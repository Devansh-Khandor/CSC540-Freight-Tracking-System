"""Pytest fixtures for the functional database tests (schema sshett24 only)."""

from __future__ import annotations

import uuid

import pytest

from db_helpers import (FixtureWorld, ScanSession, assert_expected_schema,
                        open_test_connection, safe_close)

# Unique per pytest run; embedded in every test account's dummy password so
# leftover rows (e.g. after a killed process) are identifiable.
RUN_TAG = f"PYTEST-CSC540-{uuid.uuid4().hex[:12]}"

_WORLDS: list[FixtureWorld] = []


class Harness:
    """Per-test bundle: fixture world plus dedicated connections.

    Teardown order: close (and roll back) every test connection first so no
    row locks are held, then delete this test's rows on a fresh connection.
    """

    def __init__(self):
        self._connections = []
        self.world: FixtureWorld | None = None

    def setup(self):
        self.writer = self.connect()   # fixture creation (autocommit + explicit txns)
        self.reader = self.connect()   # state inspection; never writes
        self.booker = self.connect()   # idle connection for CALL book_shipment
        self.scanner = ScanSession(self.connect())  # READ COMMITTED scan session
        self.world = FixtureWorld(self.writer, RUN_TAG)
        _WORLDS.append(self.world)
        self.world.build()

    def connect(self, lock_wait_timeout: int = 5):
        conn = open_test_connection(lock_wait_timeout)
        self._connections.append(conn)
        return conn

    def close(self):
        for conn in self._connections:
            safe_close(conn)
        self._connections.clear()
        if self.world is not None:
            self.world.cleanup()


@pytest.fixture(scope="session", autouse=True)
def schema_guard():
    """Abort the whole run unless SELECT DATABASE() is sshett24 (before any write)."""
    conn = open_test_connection()  # raises SchemaGuardError on mismatch
    try:
        assert_expected_schema(conn)
    finally:
        conn.close()
    yield


@pytest.fixture
def db():
    harness = Harness()
    try:
        harness.setup()
        yield harness
    finally:
        harness.close()


def pytest_sessionfinish(session, exitstatus):
    """Safety net: retry cleanup for any world whose per-test cleanup failed."""
    for world in _WORLDS:
        if not world.cleaned:
            try:
                world.cleanup()
            except Exception as exc:  # report, never hide
                print(f"\nWARNING: cleanup for run tag {world.tag} failed: "
                      f"{type(exc).__name__}: {exc}")
