"""Minimal CLI entry point: check connectivity with SELECT VERSION()."""

import sys

import pymysql

from app.db import ConfigurationError, get_connection


def main() -> int:
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                row = cursor.fetchone()
                if not row or not row[0]:
                    print("Connectivity test failed: no server version returned.", file=sys.stderr)
                    return 1
        print(f"Connectivity test succeeded. Server version: {row[0]}")
        return 0
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    except pymysql.MySQLError as exc:
        # Avoid printing driver messages that may contain account details.
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else "unknown"
        print(
            f"Connectivity test failed (database error code: {code}). "
            "Check your environment variables, assigned schema access, and network connection.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
