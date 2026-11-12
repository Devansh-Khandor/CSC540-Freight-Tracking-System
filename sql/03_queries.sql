
-- ============================================================
-- CSC 540: Freight Tracking and Delivery Management
-- File: 03_queries.sql
-- Required analytical queries
-- ============================================================

-- ============================================================
-- QUERY 1: Number of vehicles of each type owned by each carrier
-- ============================================================

SELECT
    c.account_id AS carrier_account_id,
    COUNT(DISTINCT bt.vehicle_id) AS box_truck_count,
    COUNT(DISTINCT rv.vehicle_id) AS refrigerated_van_count,
    COUNT(DISTINCT rc.vehicle_id) AS rail_car_count
FROM carrier c
LEFT JOIN vehicle v
    ON c.account_id = v.carrier_account_id
LEFT JOIN box_truck bt
    ON v.vehicle_id = bt.vehicle_id
LEFT JOIN refrigerated_van rv
    ON v.vehicle_id = rv.vehicle_id
LEFT JOIN rail_car rc
    ON v.vehicle_id = rc.vehicle_id
GROUP BY c.account_id
ORDER BY c.account_id;


-- ============================================================
-- QUERY 2: Rank departures by weight utilization within each lane
-- ============================================================

SELECT
    d.departure_id,
    d.origin_hub_id,
    d.destination_hub_id,
    d.departure_datetime,
    COALESCE(SUM(s.weight_kg), 0) AS total_shipment_weight_kg,
    d.max_total_weight_kg,
    ROUND(
        COALESCE(SUM(s.weight_kg), 0) * 100.0
        / d.max_total_weight_kg,
        2
    ) AS utilization_percentage,
    RANK() OVER (
        PARTITION BY d.origin_hub_id, d.destination_hub_id
        ORDER BY
            COALESCE(SUM(s.weight_kg), 0) * 100.0
            / d.max_total_weight_kg DESC
    ) AS utilization_rank
FROM departure d
LEFT JOIN booking b
    ON d.departure_id = b.departure_id
LEFT JOIN shipment s
    ON b.shipment_id = s.shipment_id
GROUP BY
    d.departure_id,
    d.origin_hub_id,
    d.destination_hub_id,
    d.departure_datetime,
    d.max_total_weight_kg
ORDER BY
    d.origin_hub_id,
    d.destination_hub_id,
    utilization_rank;



-- Query 3: Time elapsed between consecutive scans
-- for a specific shipment.
-- Change 1 to the shipment ID you want to inspect.

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
    WHERE shipment_id = 1
) AS scan_intervals
ORDER BY scan_sequence;


-- ============================================================
-- QUERY 4: Running total of delivered shipment weight by carrier
-- ============================================================

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
        se.scan_timestamp AS delivered_timestamp,
        s.weight_kg
    FROM shipment s
    JOIN booking b
        ON s.shipment_id = b.shipment_id
    JOIN departure d
        ON b.departure_id = d.departure_id
    JOIN vehicle v
        ON d.vehicle_id = v.vehicle_id
    JOIN scan_event se
        ON s.shipment_id = se.shipment_id
    WHERE se.status = 'DELIVERED'
) AS delivered_shipments
ORDER BY carrier_account_id, delivered_timestamp, shipment_id;


-- ============================================================
-- QUERY 5: Departures carrying shipments from at least two
--          different shippers
-- ============================================================

SELECT
    d.departure_id,
    d.origin_hub_id,
    d.destination_hub_id,
    COUNT(DISTINCT s.shipper_account_id) AS distinct_shippers
FROM departure d
JOIN booking b
    ON d.departure_id = b.departure_id
JOIN shipment s
    ON b.shipment_id = s.shipment_id
GROUP BY
    d.departure_id,
    d.origin_hub_id,
    d.destination_hub_id
HAVING COUNT(DISTINCT s.shipper_account_id) >= 2
ORDER BY d.departure_id;



-- ============================================================
-- QUERY 6: Shipments with no scan events
-- ============================================================

SELECT
    s.shipment_id,
    s.shipper_account_id,
    s.origin_hub_id,
    s.destination_hub_id,
    s.weight_kg,
    s.promised_delivery_date
FROM shipment s
LEFT JOIN scan_event se
    ON s.shipment_id = se.shipment_id
WHERE se.shipment_id IS NULL
ORDER BY s.shipment_id;
