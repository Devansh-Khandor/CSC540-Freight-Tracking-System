"""Read-only tracking and published summaries allowed by the final specification."""

import re

from app.shipper_service import connection_cursor


class InvalidShipmentID(ValueError):
    """Safe validation message; no user-controlled SQL."""


class NotFound(Exception):
    """The requested shipment does not exist."""


def shipment_id(value):
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,10}", value) or not 1 <= int(value) <= 4294967295:
        raise InvalidShipmentID("Enter a shipment ID from 1 to 4294967295.")
    return int(value)


def statistics():
    with connection_cursor() as (_, cursor):
        cursor.execute("""SELECT COUNT(*) AS total,
            COALESCE(SUM(current_status IN (%s, %s, %s)), 0) AS in_transit,
            COALESCE(SUM(current_status = %s), 0) AS delivered
            FROM shipment""", ("IN_TRANSIT", "ARRIVED_AT_HUB", "OUT_FOR_DELIVERY", "DELIVERED"))
        return cursor.fetchone()


def tracking(value):
    identifier = shipment_id(value)
    with connection_cursor() as (_, cursor):
        # Viewers may look up any shipment by ID. No account/password data is selected.
        cursor.execute("""SELECT s.shipment_id, s.origin_hub_id, s.destination_hub_id,
            o.region AS origin_region, dest.region AS destination_region,
            s.current_status, s.promised_delivery_date, s.delivery_outcome,
            d.departure_id, d.departure_datetime, d.vehicle_id,
            d.origin_hub_id AS departure_origin, d.destination_hub_id AS departure_destination
            FROM shipment s JOIN hub o ON o.hub_id = s.origin_hub_id
            JOIN hub dest ON dest.hub_id = s.destination_hub_id
            LEFT JOIN booking b ON b.shipment_id = s.shipment_id
            LEFT JOIN departure d ON d.departure_id = b.departure_id
            WHERE s.shipment_id = %s""", (identifier,))
        shipment = cursor.fetchone()
        if shipment is None:
            raise NotFound
        cursor.execute("""SELECT e.scan_sequence, e.scan_timestamp, e.status, e.hub_id, h.region
            FROM scan_event e JOIN hub h ON h.hub_id = e.hub_id
            WHERE e.shipment_id = %s ORDER BY e.scan_sequence ASC""", (identifier,))
        return shipment, cursor.fetchall()


# Published summaries are delivered-only, all-time rates, not the six global queries.
PERFORMANCE_COLUMNS = """COUNT(s.shipment_id) AS delivered,
    COALESCE(SUM(s.delivery_outcome = 'ON_TIME'), 0) AS on_time,
    COALESCE(SUM(s.delivery_outcome = 'LATE'), 0) AS late,
    ROUND(100 * COALESCE(SUM(s.delivery_outcome = 'ON_TIME'), 0)
          / NULLIF(COUNT(s.shipment_id), 0), 2) AS rate"""


def reports():
    with connection_cursor() as (_, cursor):
        cursor.execute("""SELECT l.origin_hub_id, l.destination_hub_id,
            o.region AS origin_region, dest.region AS destination_region, """ + PERFORMANCE_COLUMNS + """
            FROM lane l JOIN hub o ON o.hub_id = l.origin_hub_id
            JOIN hub dest ON dest.hub_id = l.destination_hub_id
            LEFT JOIN shipment s ON s.origin_hub_id = l.origin_hub_id
                AND s.destination_hub_id = l.destination_hub_id AND s.current_status = %s
            GROUP BY l.origin_hub_id, l.destination_hub_id, o.region, dest.region
            ORDER BY l.origin_hub_id, l.destination_hub_id""", ("DELIVERED",))
        lanes = cursor.fetchall()
        cursor.execute("SELECT c.account_id AS carrier_id, " + PERFORMANCE_COLUMNS + """
            FROM carrier c LEFT JOIN vehicle v ON v.carrier_account_id = c.account_id
            LEFT JOIN departure d ON d.vehicle_id = v.vehicle_id
            LEFT JOIN booking b ON b.departure_id = d.departure_id
            LEFT JOIN shipment s ON s.shipment_id = b.shipment_id AND s.current_status = %s
            GROUP BY c.account_id ORDER BY c.account_id""", ("DELIVERED",))
        return lanes, cursor.fetchall()
