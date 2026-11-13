"""Reusable analytical queries for the freight tracking application.

All functions accept an open PyMySQL-compatible connection and return rows
as tuples. Query 3 is parameterized by shipment_id.
"""


def _fetch_all(connection, sql, params=None):
    """Execute a read-only query and return all rows."""
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or ())
        return cursor.fetchall()
    finally:
        cursor.close()


def get_vehicle_counts_by_carrier(connection):
    """Count each vehicle subtype for every carrier, including zero counts."""
    sql = """
        SELECT
            c.account_id AS carrier_account_id,
            COUNT(DISTINCT bt.vehicle_id) AS box_truck_count,
            COUNT(DISTINCT rv.vehicle_id) AS refrigerated_van_count,
            COUNT(DISTINCT rc.vehicle_id) AS rail_car_count
        FROM carrier c
        LEFT JOIN vehicle v ON c.account_id = v.carrier_account_id
        LEFT JOIN box_truck bt ON v.vehicle_id = bt.vehicle_id
        LEFT JOIN refrigerated_van rv ON v.vehicle_id = rv.vehicle_id
        LEFT JOIN rail_car rc ON v.vehicle_id = rc.vehicle_id
        GROUP BY c.account_id
        ORDER BY c.account_id
    """
    return _fetch_all(connection, sql)


def get_departure_utilization_ranking(connection):
    """Rank departures by booked-weight utilization within each directed lane."""
    sql = """
        SELECT
            d.departure_id,
            d.origin_hub_id,
            d.destination_hub_id,
            d.departure_datetime,
            COALESCE(SUM(s.weight_kg), 0) AS total_shipment_weight_kg,
            d.max_total_weight_kg,
            ROUND(
                COALESCE(SUM(s.weight_kg), 0) * 100.0
                / NULLIF(d.max_total_weight_kg, 0),
                2
            ) AS utilization_percentage,
            RANK() OVER (
                PARTITION BY d.origin_hub_id, d.destination_hub_id
                ORDER BY
                    COALESCE(SUM(s.weight_kg), 0) * 100.0
                    / NULLIF(d.max_total_weight_kg, 0) DESC
            ) AS utilization_rank
        FROM departure d
        LEFT JOIN booking b ON d.departure_id = b.departure_id
        LEFT JOIN shipment s ON b.shipment_id = s.shipment_id
        GROUP BY
            d.departure_id,
            d.origin_hub_id,
            d.destination_hub_id,
            d.departure_datetime,
            d.max_total_weight_kg
        ORDER BY
            d.origin_hub_id,
            d.destination_hub_id,
            utilization_rank
    """
    return _fetch_all(connection, sql)


def get_scan_time_intervals(connection, shipment_id):
    """Return consecutive scan intervals for one shipment ID."""
    if isinstance(shipment_id, bool) or not isinstance(shipment_id, int) or shipment_id <= 0:
        raise ValueError("shipment_id must be a positive integer")

    sql = """
        SELECT
            shipment_id,
            scan_sequence,
            status,
            scan_timestamp,
            previous_scan_timestamp,
            TIMESTAMPDIFF(
                MINUTE,
                previous_scan_timestamp,
                scan_timestamp
            ) AS elapsed_minutes
        FROM (
            SELECT
                shipment_id,
                scan_sequence,
                status,
                scan_timestamp,
                LAG(scan_timestamp) OVER (
                    ORDER BY scan_sequence
                ) AS previous_scan_timestamp
            FROM scan_event
            WHERE shipment_id = %s
        ) AS scan_intervals
        ORDER BY scan_sequence
    """
    return _fetch_all(connection, sql, (shipment_id,))


def get_running_delivered_weight_by_carrier(connection):
    """Return each delivered shipment and its carrier's cumulative delivered weight."""
    sql = """
        SELECT
            carrier_account_id,
            shipment_id,
            delivered_timestamp,
            weight_kg,
            SUM(weight_kg) OVER (
                PARTITION BY carrier_account_id
                ORDER BY delivered_timestamp, shipment_id
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_total_weight_kg
        FROM (
            SELECT
                v.carrier_account_id,
                s.shipment_id,
                MIN(se.scan_timestamp) AS delivered_timestamp,
                s.weight_kg
            FROM shipment s
            JOIN booking b ON s.shipment_id = b.shipment_id
            JOIN departure d ON b.departure_id = d.departure_id
            JOIN vehicle v ON d.vehicle_id = v.vehicle_id
            JOIN scan_event se ON s.shipment_id = se.shipment_id
            WHERE se.status = 'DELIVERED'
            GROUP BY
                v.carrier_account_id,
                s.shipment_id,
                s.weight_kg
        ) AS delivered_shipments
        ORDER BY carrier_account_id, delivered_timestamp, shipment_id
    """
    return _fetch_all(connection, sql)


def get_departures_with_multiple_shippers(connection):
    """Return departures carrying freight for at least two distinct shippers."""
    sql = """
        SELECT
            d.departure_id,
            d.origin_hub_id,
            d.destination_hub_id,
            COUNT(DISTINCT s.shipper_account_id) AS distinct_shippers
        FROM departure d
        JOIN booking b ON d.departure_id = b.departure_id
        JOIN shipment s ON b.shipment_id = s.shipment_id
        GROUP BY
            d.departure_id,
            d.origin_hub_id,
            d.destination_hub_id
        HAVING COUNT(DISTINCT s.shipper_account_id) >= 2
        ORDER BY d.departure_id
    """
    return _fetch_all(connection, sql)


def get_shipments_without_scans(connection):
    """Return shipments that do not yet have any scan events."""
    sql = """
        SELECT
            s.shipment_id,
            s.shipper_account_id,
            s.origin_hub_id,
            s.destination_hub_id,
            s.weight_kg,
            s.promised_delivery_date
        FROM shipment s
        LEFT JOIN scan_event se ON s.shipment_id = se.shipment_id
        WHERE se.shipment_id IS NULL
        ORDER BY s.shipment_id
    """
    return _fetch_all(connection, sql)
