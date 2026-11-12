"""Owner-scoped raw SQL and transaction protocols for shipper workflows."""

import re
from contextlib import contextmanager, suppress
from datetime import date
from decimal import Decimal

import pymysql

from app import db


class ShipmentNotFound(Exception):
    """Missing and foreign-owned resources are deliberately indistinguishable."""


class ValidationError(Exception):
    """Safe, application-authored feedback only."""


class RetryUpdate(Exception):
    """Booking changed while acquiring locks; restart in the correct order."""


@contextmanager
def connection_cursor(write=False):
    """Each operation owns a fresh connection; failed work always rolls back."""
    connection = db.get_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            if write:
                cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cursor.execute("SET SESSION sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ZERO_DATE,NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION'")
                connection.begin()
            yield connection, cursor
    finally:
        # Also ends read-only transactions. Never mask the original failure.
        with suppress(pymysql.MySQLError, OSError):
            connection.rollback()
        with suppress(pymysql.MySQLError, OSError):
            connection.close()


def positive_id(value):
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,10}", value) or not 1 <= int(value) <= 4294967295:
        raise ValidationError("Select a valid shipment, lane, or departure.")
    return int(value)


def shipment_input(form):
    """Reject rounding, non-finite decimals, overflow, and non-ISO dates."""
    weight = form.get("weight_kg", "").strip()
    if not re.fullmatch(r"[0-9]{1,8}(\.[0-9]{1,2})?", weight) or Decimal(weight) <= 0:
        raise ValidationError("Enter a weight from 0.01 to 99999999.99 kg, with at most two decimal places.")
    promise = form.get("promised_delivery_date", "")
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", promise):
            raise ValueError
        promised_date = date.fromisoformat(promise)
        if promised_date.year < 1000:
            raise ValueError
    except ValueError:
        raise ValidationError("Enter a valid promised date in YYYY-MM-DD format (year 1000 or later).") from None
    lane = form.get("lane", "").split(":")
    if len(lane) != 2:
        raise ValidationError("Select an existing directed lane.")
    origin, destination = map(positive_id, lane)
    return {"origin": origin, "destination": destination,
            "weight": Decimal(weight), "promise": promised_date}


SHIPMENT_SELECT = """
SELECT s.shipment_id, s.weight_kg, s.origin_hub_id, s.destination_hub_id,
       s.promised_delivery_date, s.current_status, s.delivery_outcome,
       o.region AS origin_region, d.region AS destination_region, b.departure_id
FROM shipment s
JOIN hub o ON o.hub_id = s.origin_hub_id
JOIN hub d ON d.hub_id = s.destination_hub_id
LEFT JOIN booking b ON b.shipment_id = s.shipment_id
WHERE s.shipper_account_id = %s
"""


def list_shipments(owner):
    with connection_cursor() as (_, cursor):
        cursor.execute(SHIPMENT_SELECT + " ORDER BY s.shipment_id DESC", (owner,))
        return cursor.fetchall()


def _owned(cursor, owner, shipment_id):
    cursor.execute(SHIPMENT_SELECT + " AND s.shipment_id = %s", (owner, shipment_id))
    row = cursor.fetchone()
    if row is None:
        raise ShipmentNotFound
    return row


def get_shipment(owner, shipment_id):
    with connection_cursor() as (_, cursor):
        return _owned(cursor, owner, shipment_id)


def tracking(owner, shipment_id):
    with connection_cursor() as (_, cursor):
        shipment = _owned(cursor, owner, shipment_id)
        cursor.execute("""
            SELECT e.scan_sequence, e.scan_timestamp, e.status, e.hub_id, h.region
            FROM scan_event e JOIN shipment s ON s.shipment_id = e.shipment_id
            JOIN hub h ON h.hub_id = e.hub_id
            WHERE s.shipment_id = %s AND s.shipper_account_id = %s
            ORDER BY e.scan_sequence ASC
        """, (shipment_id, owner))
        return shipment, cursor.fetchall()


def lanes():
    with connection_cursor() as (_, cursor):
        cursor.execute("""SELECT l.origin_hub_id, l.destination_hub_id,
            o.region AS origin_region, d.region AS destination_region
            FROM lane l JOIN hub o ON o.hub_id = l.origin_hub_id
            JOIN hub d ON d.hub_id = l.destination_hub_id
            ORDER BY l.origin_hub_id, l.destination_hub_id""")
        return cursor.fetchall()


def _valid_lane(cursor, data):
    cursor.execute("SELECT origin_hub_id FROM lane WHERE origin_hub_id = %s AND destination_hub_id = %s",
                   (data["origin"], data["destination"]))
    if cursor.fetchone() is None:
        raise ValidationError("Select an existing directed lane.")


def create_shipment(owner, form):
    data = shipment_input(form)
    with connection_cursor(write=True) as (connection, cursor):
        _valid_lane(cursor, data)
        cursor.execute("""INSERT INTO shipment
            (shipper_account_id, origin_hub_id, destination_hub_id, weight_kg, promised_delivery_date)
            VALUES (%s, %s, %s, %s, %s)""",
                       (owner, data["origin"], data["destination"], data["weight"], data["promise"]))
        shipment_id = cursor.lastrowid
        connection.commit()
        return shipment_id


def _booking(cursor, owner, shipment_id):
    cursor.execute("""SELECT s.shipment_id, b.departure_id FROM shipment s
        LEFT JOIN booking b ON b.shipment_id = s.shipment_id
        WHERE s.shipment_id = %s AND s.shipper_account_id = %s""", (shipment_id, owner))
    row = cursor.fetchone()
    if row is None:
        raise ShipmentNotFound
    return row["departure_id"]


def _update_once(owner, shipment_id, data):
    with connection_cursor(write=True) as (connection, cursor):
        departure_id = _booking(cursor, owner, shipment_id)
        departure = None
        if departure_id is not None:
            cursor.execute("SELECT max_total_weight_kg FROM departure WHERE departure_id = %s FOR UPDATE",
                           (departure_id,))
            departure = cursor.fetchone()
            if departure is None:
                raise RetryUpdate
        cursor.execute("""SELECT origin_hub_id, destination_hub_id, weight_kg FROM shipment
            WHERE shipment_id = %s AND shipper_account_id = %s FOR UPDATE""", (shipment_id, owner))
        shipment = cursor.fetchone()
        if shipment is None:
            raise ShipmentNotFound
        if _booking(cursor, owner, shipment_id) != departure_id:
            raise RetryUpdate
        cursor.execute("""SELECT e.scan_sequence FROM scan_event e
            JOIN shipment s ON s.shipment_id = e.shipment_id
            WHERE s.shipment_id = %s AND s.shipper_account_id = %s LIMIT 1""", (shipment_id, owner))
        if cursor.fetchone() is not None:
            raise ValidationError("Shipments cannot be edited after their first scan.")
        if departure_id is not None:
            if (data["origin"], data["destination"]) != (shipment["origin_hub_id"], shipment["destination_hub_id"]):
                raise ValidationError("A booked shipment's lane cannot be changed.")
            # Aggregate all booked weights, but never expose other owners' data.
            cursor.execute("""SELECT COALESCE(SUM(s.weight_kg), 0) AS total
                FROM booking b JOIN shipment s ON s.shipment_id = b.shipment_id
                WHERE b.departure_id = %s""", (departure_id,))
            total = cursor.fetchone()["total"]
            if total - shipment["weight_kg"] + data["weight"] > departure["max_total_weight_kg"]:
                raise ValidationError("The new weight would exceed the booked departure's capacity.")
        _valid_lane(cursor, data)
        cursor.execute("""UPDATE shipment SET origin_hub_id = %s, destination_hub_id = %s,
            weight_kg = %s, promised_delivery_date = %s
            WHERE shipment_id = %s AND shipper_account_id = %s""",
                       (data["origin"], data["destination"], data["weight"], data["promise"], shipment_id, owner))
        connection.commit()


def update_shipment(owner, shipment_id, form):
    data = shipment_input(form)
    for attempt in range(3):
        try:
            return _update_once(owner, shipment_id, data)
        except RetryUpdate:
            pass
        except pymysql.MySQLError as exc:
            if not exc.args or exc.args[0] not in (1205, 1213):
                raise
        if attempt == 2:
            raise ValidationError("The shipment changed or is busy. Refresh it and try again.") from None


DEPARTURES_SQL = """
SELECT d.departure_id, d.departure_datetime, d.vehicle_id, d.max_total_weight_kg,
       d.max_total_weight_kg - COALESCE(loads.total, 0) AS remaining_weight
FROM shipment s
JOIN departure d ON d.origin_hub_id = s.origin_hub_id AND d.destination_hub_id = s.destination_hub_id
LEFT JOIN (SELECT b.departure_id, SUM(booked.weight_kg) AS total
           FROM booking b JOIN shipment booked ON booked.shipment_id = b.shipment_id
           GROUP BY b.departure_id) loads ON loads.departure_id = d.departure_id
WHERE s.shipment_id = %s AND s.shipper_account_id = %s
  AND NOT EXISTS (SELECT 1 FROM booking existing WHERE existing.shipment_id = s.shipment_id)
  AND d.max_total_weight_kg - COALESCE(loads.total, 0) >= s.weight_kg
ORDER BY d.departure_datetime, d.departure_id
"""


def bookable_departures(owner, shipment_id):
    with connection_cursor() as (_, cursor):
        shipment = _owned(cursor, owner, shipment_id)
        cursor.execute(DEPARTURES_SQL, (shipment_id, owner))
        return shipment, cursor.fetchall()


BOOKING_ERRORS = {
    "Shipment is already booked": "This shipment is already booked. Refresh its details.",
    "Departure weight capacity would be exceeded": "There is no longer enough capacity on this departure. Choose another departure.",
    "Shipment lane does not match the ordered departure lane": "The departure no longer matches this shipment's lane.",
    "Departure does not exist": "That departure is no longer available.",
    "Shipment does not exist": "That shipment is no longer available.",
}


def book_shipment(owner, shipment_id, departure_id):
    departure_id = positive_id(departure_id)
    for attempt in range(3):
        try:
            with connection_cursor() as (connection, cursor):
                _owned(cursor, owner, shipment_id)
                # get_connection uses autocommit=False; the authorization SELECT
                # starts a transaction. End only this dedicated read transaction.
                connection.rollback()
                # Ownership is immutable under the schema's application policy.
                cursor.execute("CALL book_shipment(%s, %s)", (shipment_id, departure_id))
                while cursor.nextset():
                    pass
                # Procedure owns COMMIT; no caller BEGIN/COMMIT or booking DML.
                return
        except pymysql.MySQLError as exc:
            code = exc.args[0] if exc.args else None
            if code in (1205, 1213):
                if attempt < 2:
                    continue
                raise ValidationError("Booking is busy. Refresh the shipment and try again.") from None
            if code == 1062:
                raise ValidationError("This shipment is already booked. Refresh its details.") from None
            if code == 1644:
                message = BOOKING_ERRORS.get(exc.args[1] if len(exc.args) > 1 else "",
                                             "Booking was rejected. Refresh the shipment and choose an eligible departure.")
                raise ValidationError(message) from None
            # Unknown connection/commit failures are NOT retried: outcome may be
            # committed. Routes ask the user to check current state first.
            raise


def reports(owner):
    with connection_cursor() as (_, cursor):
        cursor.execute("""SELECT
            COALESCE(SUM(delivery_outcome = 'ON_TIME'), 0) AS on_time,
            COALESCE(SUM(delivery_outcome = 'LATE'), 0) AS late
            FROM shipment WHERE shipper_account_id = %s""", (owner,))
        summary = cursor.fetchone()
        cursor.execute(SHIPMENT_SELECT + " AND s.current_status IN ('IN_TRANSIT', 'ARRIVED_AT_HUB', 'OUT_FOR_DELIVERY') ORDER BY s.shipment_id", (owner,))
        return summary, cursor.fetchall()
