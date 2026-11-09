"""Environment-based PyMySQL connectivity for the assigned MariaDB schema."""

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Database environment variables are missing or invalid."""


def get_connection() -> pymysql.connections.Connection:
    """Open a connection; the caller owns closing it. Never create a schema."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False,
                interpolate=False)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ConfigurationError("Missing environment variables: " + ", ".join(missing))

    try:
        port = int(os.environ["DB_PORT"])
    except ValueError:
        raise ConfigurationError("DB_PORT must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise ConfigurationError("DB_PORT must be an integer from 1 to 65535.")

    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=port,
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        charset="utf8mb4",
        ssl_disabled=True,
        connect_timeout=10,
        read_timeout=10,
        write_timeout=10,
        autocommit=False,
    )
