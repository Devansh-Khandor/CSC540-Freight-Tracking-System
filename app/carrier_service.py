"""Carrier-owned operations against the canonical schema; no schema or booking writes."""

import re
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
from zoneinfo import ZoneInfo

import pymysql

from app.shipper_service import connection_cursor, lanes, ValidationError

EASTERN = ZoneInfo("America/New_York")
STATUSES = ("RECEIVED", "IN_TRANSIT", "ARRIVED_AT_HUB", "OUT_FOR_DELIVERY", "DELIVERED")
# Identifiers below are fixed application constants, never supplied by a form.
SUBTYPES = {
    "BOX_TRUCK": ("box_truck", ("cargo_volume", "gross_weight_rating")),
    "REFRIGERATED_VAN": ("refrigerated_van", ("temperature_range", "payload_limit")),
    "RAIL_CAR": ("rail_car", ("axle_count", "track_gauge")),
}


class NotFound(Exception):
    """Missing and foreign-owned records have the same response."""


def retry_locks(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        for attempt in range(3):
            try:
                return operation(*args, **kwargs)
            except pymysql.MySQLError as exc:
                if not exc.args or exc.args[0] not in (1205, 1213):
                    raise  # Never replay an uncertain commit or connection failure.
                if attempt == 2:
                    raise ValidationError("The record is busy. Refresh it and try again.") from None
    return run


def identifier(value):
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,10}", value) or not 1 <= int(value) <= 4294967295:
        raise ValidationError("Select a valid record identifier.")
    return int(value)


def decimal_value(value, label, digits=8):
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]{1," + str(digits) + r"}(\.[0-9]{1,2})?", value) or Decimal(value) <= 0:
        raise ValidationError(f"{label} must be positive, with at most {digits} whole digits and two decimal places.")
    return Decimal(value)


def local_datetime(value):
    """Canonical DATETIME uses Eastern wall time, with seconds and no offset."""
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?", value):
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.year < 1000:
            raise ValueError
        # Do not silently normalize nonexistent spring-forward or ambiguous fall-back times.
        first, second = (parsed.replace(tzinfo=EASTERN, fold=fold) for fold in (0, 1))
        if first.utcoffset() != second.utcoffset():
            raise ValueError
        if first.astimezone(timezone.utc).astimezone(EASTERN).replace(tzinfo=None) != parsed:
            raise ValueError
        return parsed
    except (ValueError, OverflowError):
        raise ValidationError("Enter a valid Eastern date and time (year 1000–9999). Ambiguous or skipped daylight-saving times are not accepted.") from None


def hubs():
    with connection_cursor() as (_, cursor):
        cursor.execute("SELECT hub_id, region FROM hub ORDER BY hub_id")
        return cursor.fetchall()


def valid_hub(cursor, hub_id):
    cursor.execute("SELECT hub_id FROM hub WHERE hub_id = %s", (hub_id,))
    if cursor.fetchone() is None:
        raise ValidationError("Select an existing hub.")


def valid_lane(cursor, origin, destination):
    cursor.execute("SELECT origin_hub_id FROM lane WHERE origin_hub_id = %s AND destination_hub_id = %s",
                   (origin, destination))
    if cursor.fetchone() is None:
        raise ValidationError("Select an existing directed lane.")


VEHICLES_SQL = """
SELECT v.vehicle_id, v.home_hub_id, h.region,
       bt.vehicle_id AS box_id, rv.vehicle_id AS van_id, rc.vehicle_id AS rail_id,
       bt.cargo_volume, bt.gross_weight_rating, rv.temperature_range, rv.payload_limit,
       rc.axle_count, rc.track_gauge
FROM vehicle v JOIN hub h ON h.hub_id = v.home_hub_id
LEFT JOIN box_truck bt ON bt.vehicle_id = v.vehicle_id
LEFT JOIN refrigerated_van rv ON rv.vehicle_id = v.vehicle_id
LEFT JOIN rail_car rc ON rc.vehicle_id = v.vehicle_id
WHERE v.carrier_account_id = %s
"""


def vehicle_kind(row):
    kinds = [kind for kind, key in zip(SUBTYPES, ("box_id", "van_id", "rail_id")) if row[key] is not None]
    return kinds[0] if len(kinds) == 1 else ("INVALID" if kinds else "UNCLASSIFIED")


def list_vehicles(owner):
    with connection_cursor() as (_, cursor):
        cursor.execute(VEHICLES_SQL + " ORDER BY v.vehicle_id", (owner,))
        rows = cursor.fetchall()
        for row in rows:
            row["kind"] = vehicle_kind(row)
        return rows


def owned_vehicle(cursor, owner, vehicle_id, lock=False):
    # Lock just the parent before reading specialization; membership is immutable.
    cursor.execute("SELECT vehicle_id FROM vehicle WHERE vehicle_id = %s AND carrier_account_id = %s"
                   + (" FOR UPDATE" if lock else ""), (vehicle_id, owner))
    if cursor.fetchone() is None:
        raise NotFound
    cursor.execute(VEHICLES_SQL + " AND v.vehicle_id = %s", (owner, vehicle_id))
    row = cursor.fetchone()
    if row is None:
        raise NotFound
    row["kind"] = vehicle_kind(row)
    if row["kind"] == "INVALID":
        raise ValidationError("This vehicle has inconsistent subtype records. Ask the data administrator to review it.")
    return row


def get_vehicle(owner, vehicle_id):
    with connection_cursor() as (_, cursor):
        return owned_vehicle(cursor, owner, vehicle_id)


def subtype_values(kind, form):
    if kind not in SUBTYPES:
        raise ValidationError("Select a supported vehicle subtype.")
    result = []
    for field in SUBTYPES[kind][1]:
        value = form.get(field, "")
        if field == "temperature_range":
            value = value.strip()
            if not 1 <= len(value) <= 50:
                raise ValidationError("Temperature range must contain 1 to 50 characters.")
        elif field == "axle_count":
            value = identifier(value)
        else:
            value = decimal_value(value, field.replace("_", " ").capitalize(), 4 if field == "track_gauge" else 8)
        result.append(value)
    return result


@retry_locks
def create_vehicle(owner, form):
    hub_id, kind = identifier(form.get("home_hub_id", "")), form.get("kind", "")
    values = subtype_values(kind, form)
    table, fields = SUBTYPES[kind]
    with connection_cursor(write=True) as (connection, cursor):
        cursor.execute("""SELECT c.account_id FROM carrier c JOIN account a ON a.account_id = c.account_id
            WHERE c.account_id = %s AND BINARY a.role = 'CARRIER'
            AND NOT EXISTS (SELECT 1 FROM shipper s WHERE s.account_id = c.account_id)
            AND NOT EXISTS (SELECT 1 FROM viewer w WHERE w.account_id = c.account_id)""", (owner,))
        if cursor.fetchone() is None:
            raise ValidationError("The carrier account setup must be reviewed before creating vehicles.")
        valid_hub(cursor, hub_id)
        cursor.execute("INSERT INTO vehicle (carrier_account_id, home_hub_id) VALUES (%s, %s)", (owner, hub_id))
        vehicle_id = cursor.lastrowid
        cursor.execute(f"INSERT INTO {table} (vehicle_id, {', '.join(fields)}) VALUES (%s, %s, %s)",
                       (vehicle_id, *values))
        connection.commit()
        return vehicle_id


@retry_locks
def update_vehicle(owner, vehicle_id, form):
    with connection_cursor(write=True) as (connection, cursor):
        vehicle = owned_vehicle(cursor, owner, vehicle_id, lock=True)
        kind = vehicle["kind"]
        if form.get("kind", kind) != kind:
            raise ValidationError("A vehicle's subtype cannot be changed.")
        hub_id = identifier(form.get("home_hub_id", ""))
        values = subtype_values(kind, form) if kind in SUBTYPES else []
        valid_hub(cursor, hub_id)
        cursor.execute("UPDATE vehicle SET home_hub_id = %s WHERE vehicle_id = %s AND carrier_account_id = %s",
                       (hub_id, vehicle_id, owner))
        if kind in SUBTYPES:
            table, fields = SUBTYPES[kind]
            cursor.execute(f"UPDATE {table} SET {fields[0]} = %s, {fields[1]} = %s WHERE vehicle_id = %s",
                           (*values, vehicle_id))
        connection.commit()


DEPARTURES_SQL = """
SELECT d.departure_id, d.vehicle_id, d.origin_hub_id, d.destination_hub_id,
       d.departure_datetime, d.max_total_weight_kg,
       COALESCE(loads.booked_weight, 0) AS booked_weight, COALESCE(loads.booking_count, 0) AS booking_count,
       ROUND(100 * COALESCE(loads.booked_weight, 0) / d.max_total_weight_kg, 2) AS utilization
FROM departure d JOIN vehicle v ON v.vehicle_id = d.vehicle_id
LEFT JOIN (SELECT b.departure_id, SUM(s.weight_kg) AS booked_weight, COUNT(*) AS booking_count
           FROM booking b JOIN shipment s ON s.shipment_id = b.shipment_id GROUP BY b.departure_id) loads
       ON loads.departure_id = d.departure_id
WHERE v.carrier_account_id = %s
"""


def list_departures(owner):
    with connection_cursor() as (_, cursor):
        cursor.execute(DEPARTURES_SQL + " ORDER BY d.departure_datetime, d.departure_id", (owner,))
        return cursor.fetchall()


def get_departure(owner, departure_id):
    with connection_cursor() as (_, cursor):
        cursor.execute(DEPARTURES_SQL + " AND d.departure_id = %s", (owner, departure_id))
        row = cursor.fetchone()
        if row is None:
            raise NotFound
        return row


def departure_values(form):
    lane = form.get("lane", "").split(":")
    if len(lane) != 2:
        raise ValidationError("Select an existing directed lane.")
    return (identifier(form.get("vehicle_id", "")), *map(identifier, lane),
            local_datetime(form.get("departure_datetime", "")),
            decimal_value(form.get("max_total_weight_kg", ""), "Capacity"))


@retry_locks
def create_departure(owner, form):
    values = departure_values(form)
    with connection_cursor(write=True) as (connection, cursor):
        owned_vehicle(cursor, owner, values[0])
        valid_lane(cursor, values[1], values[2])
        cursor.execute("""INSERT INTO departure (vehicle_id, origin_hub_id, destination_hub_id,
            departure_datetime, max_total_weight_kg) VALUES (%s, %s, %s, %s, %s)""", values)
        departure_id = cursor.lastrowid
        connection.commit()
        return departure_id


@retry_locks
def update_departure(owner, departure_id, form):
    with connection_cursor(write=True) as (connection, cursor):
        # Lock departure only, with an ownership predicate, before inspecting its bookings.
        cursor.execute("""SELECT d.vehicle_id, d.origin_hub_id, d.destination_hub_id, d.departure_datetime
            FROM departure d WHERE d.departure_id = %s
            AND EXISTS (SELECT 1 FROM vehicle v WHERE v.vehicle_id = d.vehicle_id AND v.carrier_account_id = %s)
            FOR UPDATE""", (departure_id, owner))
        row = cursor.fetchone()
        if row is None:
            raise NotFound
        values = departure_values(form)
        cursor.execute("""SELECT COUNT(*) AS booking_count, COALESCE(SUM(s.weight_kg), 0) AS booked_weight
            FROM booking b JOIN shipment s ON s.shipment_id = b.shipment_id WHERE b.departure_id = %s""", (departure_id,))
        load = cursor.fetchone()
        if load["booked_weight"] > values[4]:
            raise ValidationError("Capacity cannot be lower than the booked weight.")
        if load["booking_count"] and values[:4] != tuple(row[key] for key in
                ("vehicle_id", "origin_hub_id", "destination_hub_id", "departure_datetime")):
            raise ValidationError("A booked departure's vehicle, lane, and date/time cannot be changed.")
        owned_vehicle(cursor, owner, values[0])
        valid_lane(cursor, values[1], values[2])
        cursor.execute("""UPDATE departure SET vehicle_id = %s, origin_hub_id = %s, destination_hub_id = %s,
            departure_datetime = %s, max_total_weight_kg = %s WHERE departure_id = %s""", (*values, departure_id))
        connection.commit()


ASSIGNED_FROM = """FROM shipment s JOIN booking b ON b.shipment_id = s.shipment_id
JOIN departure d ON d.departure_id = b.departure_id JOIN vehicle v ON v.vehicle_id = d.vehicle_id
WHERE v.carrier_account_id = %s"""
ASSIGNED_SQL = """SELECT s.shipment_id, s.origin_hub_id, s.destination_hub_id, s.weight_kg,
    s.promised_delivery_date, s.current_status, s.delivery_outcome, d.departure_id, d.vehicle_id """ + ASSIGNED_FROM


def assigned_shipments(owner):
    with connection_cursor() as (_, cursor):
        cursor.execute(ASSIGNED_SQL + " ORDER BY d.departure_id, s.shipment_id", (owner,))
        return cursor.fetchall()


def assigned(cursor, owner, shipment_id):
    cursor.execute(ASSIGNED_SQL + " AND s.shipment_id = %s", (owner, shipment_id))
    row = cursor.fetchone()
    if row is None:
        raise NotFound
    return row


def tracking(owner, shipment_id):
    with connection_cursor() as (_, cursor):
        shipment = assigned(cursor, owner, shipment_id)
        cursor.execute("""SELECT e.scan_sequence, e.scan_timestamp, e.status, e.hub_id
            FROM scan_event e JOIN shipment s ON s.shipment_id = e.shipment_id
            JOIN booking b ON b.shipment_id = s.shipment_id JOIN departure d ON d.departure_id = b.departure_id
            JOIN vehicle v ON v.vehicle_id = d.vehicle_id
            WHERE v.carrier_account_id = %s AND s.shipment_id = %s ORDER BY e.scan_sequence""", (owner, shipment_id))
        return shipment, cursor.fetchall()


@retry_locks
def post_scan(owner, shipment_id, form):
    with connection_cursor(write=True) as (connection, cursor):
        # Early ownership check avoids locking unrelated shipments. Recheck after prelock.
        assigned(cursor, owner, shipment_id)
        cursor.execute("SELECT shipment_id FROM shipment WHERE shipment_id = %s FOR UPDATE", (shipment_id,))
        if cursor.fetchone() is None:
            raise NotFound
        assigned(cursor, owner, shipment_id)
        status = form.get("status", "")
        if status not in STATUSES:
            raise ValidationError("Select a supported scan status.")
        timestamp = local_datetime(form.get("scan_timestamp", ""))
        hub_id = identifier(form.get("hub_id", ""))
        valid_hub(cursor, hub_id)
        cursor.execute("SELECT COALESCE(MAX(scan_sequence), 0) + 1 AS next_sequence FROM scan_event WHERE shipment_id = %s",
                       (shipment_id,))
        sequence = cursor.fetchone()["next_sequence"]
        if sequence > 4294967295:
            raise ValidationError("This shipment's scan sequence is exhausted.")
        cursor.execute("""INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id)
            VALUES (%s, %s, %s, %s, %s)""", (shipment_id, sequence, timestamp, status, hub_id))
        # Triggers alone enforce chronology/transitions and maintain derived state.
        connection.commit()


def reports(owner):
    with connection_cursor() as (_, cursor):
        cursor.execute("""SELECT COALESCE(SUM(s.delivery_outcome = 'ON_TIME'), 0) AS on_time,
            COALESCE(SUM(s.delivery_outcome = 'LATE'), 0) AS late """ + ASSIGNED_FROM +
            " AND s.current_status = 'DELIVERED'", (owner,))
        summary = cursor.fetchone()
    delivered = summary["on_time"] + summary["late"]
    summary["rate"] = round(Decimal(summary["on_time"]) * 100 / Decimal(delivered), 2) if delivered else None
    return summary, list_departures(owner)


def dashboard(owner):
    vehicles = list_vehicles(owner)
    departures = list_departures(owner)
    shipments = assigned_shipments(owner)
    now = datetime.now(EASTERN).replace(tzinfo=None)
    return {"vehicles": vehicles, "departures": [d for d in departures if d["departure_datetime"] >= now],
            "shipments": shipments}
