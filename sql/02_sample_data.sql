
-- ============================================================
-- CSC 540: Freight Tracking and Delivery Management
-- File: 02_sample_data.sql
-- Purpose: Load professor-provided demonstration dataset
-- SAFETY: Fresh-schema-only seed. Do not run against a populated/shared schema.
-- Explicit primary keys and stored-procedure bookings make this script non-rerunnable.
-- ============================================================

-- HUB ID MAPPING:
-- RDU = 1, ATL = 2, MIA = 3, JFK = 4, BOS = 5
-- ORD = 6, STL = 7, DFW = 8, PHX = 9, LAX = 10, SEA = 11

-- ============================================================
-- SECTION 1: HUBS
-- ============================================================

INSERT INTO hub (hub_id, region) VALUES
(1, 'Southeast'),  -- RDU
(2, 'Southeast'),  -- ATL
(3, 'Southeast'),  -- MIA
(4, 'Northeast'),  -- JFK
(5, 'Northeast'),  -- BOS
(6, 'Midwest'),    -- ORD
(7, 'Midwest'),    -- STL
(8, 'Southwest'),  -- DFW
(9, 'Southwest'),  -- PHX
(10, 'West'),      -- LAX
(11, 'West');      -- SEA


-- ============================================================
-- SECTION 2: LANES
-- ============================================================

-- Only the directional lanes present in the provided departures
-- are inserted.

INSERT INTO lane (origin_hub_id, destination_hub_id) VALUES
(1, 2),   -- RDU -> ATL
(2, 3),   -- ATL -> MIA
(4, 5),   -- JFK -> BOS
(6, 8),   -- ORD -> DFW
(8, 10);  -- DFW -> LAX


-- ============================================================
-- SECTION 3: ACCOUNTS
-- ============================================================

-- Passwords must be initialized using app/bootstrap_accounts.py
-- Do not use these placeholder values for application login.

INSERT INTO account (account_id, password, role) VALUES
(1, 'BOOTSTRAP_REQUIRED', 'CARRIER'),
(2, 'BOOTSTRAP_REQUIRED', 'CARRIER'),
(3, 'BOOTSTRAP_REQUIRED', 'CARRIER'),
(4, 'BOOTSTRAP_REQUIRED', 'SHIPPER'),
(5, 'BOOTSTRAP_REQUIRED', 'SHIPPER'),
(6, 'BOOTSTRAP_REQUIRED', 'SHIPPER'),
(7, 'BOOTSTRAP_REQUIRED', 'SHIPPER'),
(8, 'BOOTSTRAP_REQUIRED', 'VIEWER');

-- ============================================================
-- SECTION 4: ACCOUNT ROLE TABLES
-- ============================================================

INSERT INTO carrier (account_id) VALUES
(1), (2), (3);

INSERT INTO shipper (account_id) VALUES
(4), (5), (6), (7);

INSERT INTO viewer (account_id) VALUES
(8);


-- ============================================================
-- SECTION 5: VEHICLES
-- ============================================================

-- Vehicle ID mapping:
-- V101 = 101
-- V102 = 102
-- V103 = 103
-- V201 = 201
-- V202 = 202
-- V203 = 203
-- V301 = 301

INSERT INTO vehicle (vehicle_id, carrier_account_id, home_hub_id) VALUES
(101, 1, 1),  -- V101: C1, RDU
(102, 1, 2),  -- V102: C1, ATL
(103, 1, 1),  -- V103: C1, RDU
(201, 2, 4),  -- V201: C2, JFK
(202, 2, 6),  -- V202: C2, ORD
(203, 2, 6),  -- V203: C2, ORD
(301, 3, 8);  -- V301: C3, DFW


-- ============================================================
-- SECTION 6: BOX TRUCKS
-- ============================================================

INSERT INTO box_truck
(vehicle_id, cargo_volume, gross_weight_rating) VALUES
(101, 45.0, 12000),
(103, 30.0, 8000),
(201, 40.0, 10000),
(202, 50.0, 14000);


-- ============================================================
-- SECTION 7: REFRIGERATED VANS
-- ============================================================

INSERT INTO refrigerated_van
(vehicle_id, temperature_range, payload_limit) VALUES
(102, '-18.0 to 4.0 C', 4000),
(203, '-25.0 to -10.0 C', 3000);


-- ============================================================
-- SECTION 8: RAIL CARS
-- ============================================================

INSERT INTO rail_car
(vehicle_id, axle_count, track_gauge) VALUES
(301, 4, 1435.00);


-- ============================================================
-- SECTION 9: DEPARTURES
-- ============================================================

-- Departure ID mapping:
-- D1  = 1
-- D2  = 2
-- D3  = 3
-- D4  = 4
-- D5  = 5
-- D6  = 6
-- D7  = 7
-- D8  = 8
-- D9  = 9
-- D10 = 10

INSERT INTO departure
(departure_id, vehicle_id, origin_hub_id, destination_hub_id,
 departure_datetime, max_total_weight_kg)
VALUES
(1, 101, 1, 2, '2026-03-01 22:00:00', 10000),
(2, 102, 2, 3, '2026-03-04 06:00:00', 4000),
(3, 201, 4, 5, '2026-03-02 09:00:00', 8000),
(4, 202, 6, 8, '2026-03-02 20:00:00', 12000),
(5, 301, 8, 10, '2026-03-03 08:00:00', 9000),
(6, 101, 1, 2, '2026-03-07 22:00:00', 10000),
(7, 103, 1, 2, '2026-10-29 09:00:00', 2000),
(8, 101, 1, 2, '2026-10-30 09:00:00', 8000),
(9, 101, 1, 2, '2026-01-10 09:00:00', 10000),
(10, 101, 1, 2, '2026-02-10 09:00:00', 10000);


-- ============================================================
-- SECTION 10: SHIPMENTS
-- ============================================================

-- Shipment ID mapping:
-- S1 = 1, S2 = 2, ... S23 = 23
--
-- Shipper account mapping:
-- SH1 = 4
-- SH2 = 5
-- SH3 = 6
-- SH4 = 7
--
-- Hub mapping:
-- RDU = 1, ATL = 2, MIA = 3, JFK = 4, BOS = 5
-- ORD = 6, STL = 7, DFW = 8, PHX = 9, LAX = 10, SEA = 11

INSERT INTO shipment
(shipment_id, shipper_account_id, origin_hub_id,
 destination_hub_id, weight_kg, promised_delivery_date)
VALUES
(1,  4, 1,  2, 3000, '2026-03-04'), -- S1
(2,  5, 4,  5, 2500, '2026-03-02'), -- S2
(3,  6, 1,  2, 2000, '2026-03-02'), -- S3
(4,  4, 4,  5, 1500, '2026-03-05'), -- S4
(5,  5, 2,  3, 2000, '2026-03-07'), -- S5
(6,  6, 2,  3, 1700, '2026-03-06'), -- S6
(7,  6, 6,  8, 3000, '2026-03-05'), -- S7
(8,  6, 6,  8, 4000, '2026-03-03'), -- S8
(9,  4, 1,  2, 2500, '2026-03-05'), -- S9
(10, 6, 1,  2, 2800, '2026-03-11'), -- S10
(11, 5, 8, 10, 3500, '2026-03-05'), -- S11
(12, 4, 1,  2, 1000, '2026-11-02'), -- S12
(13, 4, 1,  2, 1000, '2026-11-02'), -- S13
(14, 4, 1,  2,  500, '2026-11-03'), -- S14
(15, 4, 1,  2,  500, '2026-11-02'), -- S15
(16, 4, 1,  2,  500, '2026-10-30'), -- S16
(17, 4, 1,  2, 1000, '2026-10-31'), -- S17
(18, 4, 1,  2, 1000, '2026-11-02'), -- S18
(19, 4, 1,  2, 1000, '2026-11-03'), -- S19
(20, 4, 1,  2, 1000, '2026-01-11'), -- S20
(21, 4, 1,  2, 1000, '2026-01-12'), -- S21
(22, 4, 1,  2, 1000, '2026-02-11'), -- S22
(23, 4, 1,  2, 1000, '2026-02-12'); -- S23


-- ============================================================
-- SECTION 11: BOOKINGS
-- ============================================================

-- Use the required stored procedure for every booking.
-- Source mapping: S1-S23 = shipment IDs 1-23.
-- Source mapping: D1-D10 = departure IDs 1-10.
--
-- Commit reference data and shipments before booking transactions
COMMIT;
-- S14 is intentionally left unbooked.

CALL book_shipment(1, 1);    -- S1  -> D1
CALL book_shipment(2, 3);    -- S2  -> D3
CALL book_shipment(3, 1);    -- S3  -> D1
CALL book_shipment(4, 3);    -- S4  -> D3
CALL book_shipment(5, 2);    -- S5  -> D2
CALL book_shipment(6, 2);    -- S6  -> D2
CALL book_shipment(7, 4);    -- S7  -> D4
CALL book_shipment(8, 4);    -- S8  -> D4
CALL book_shipment(9, 1);    -- S9  -> D1
CALL book_shipment(10, 6);   -- S10 -> D6
CALL book_shipment(11, 5);   -- S11 -> D5
CALL book_shipment(12, 7);   -- S12 -> D7
CALL book_shipment(13, 7);   -- S13 -> D7

-- S14 intentionally unbooked

CALL book_shipment(15, 8);   -- S15 -> D8
CALL book_shipment(16, 8);   -- S16 -> D8
CALL book_shipment(17, 8);   -- S17 -> D8
CALL book_shipment(18, 8);   -- S18 -> D8
CALL book_shipment(19, 8);   -- S19 -> D8
CALL book_shipment(20, 9);   -- S20 -> D9
CALL book_shipment(21, 9);   -- S21 -> D9
CALL book_shipment(22, 10);  -- S22 -> D10
CALL book_shipment(23, 10);  -- S23 -> D10



-- ============================================================
-- SECTION 12: SCAN EVENTS
-- ============================================================

SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- Each shipment's scan history is inserted in its own transaction.
-- The shipment row is locked before inserting scan events.
-- Each scan is inserted using a separate INSERT statement.

-- S1: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 1 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (1, 1, '2026-03-01 21:00:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (1, 2, '2026-03-01 22:05:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (1, 3, '2026-03-02 08:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (1, 4, '2026-03-02 12:30:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (1, 5, '2026-03-02 14:00:00', 'DELIVERED', 2);
COMMIT;

-- S2: JFK -> BOS
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 2 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (2, 1, '2026-03-01 15:00:00', 'RECEIVED', 4);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (2, 2, '2026-03-02 09:10:00', 'IN_TRANSIT', 4);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (2, 3, '2026-03-03 06:00:00', 'ARRIVED_AT_HUB', 5);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (2, 4, '2026-03-03 08:00:00', 'OUT_FOR_DELIVERY', 5);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (2, 5, '2026-03-03 11:30:00', 'DELIVERED', 5);
COMMIT;

-- S3: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 3 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (3, 1, '2026-03-01 19:15:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (3, 2, '2026-03-01 22:05:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (3, 3, '2026-03-02 15:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (3, 4, '2026-03-02 18:00:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (3, 5, '2026-03-02 20:45:00', 'DELIVERED', 2);
COMMIT;

-- S4: JFK -> BOS (incomplete journey)
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 4 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (4, 1, '2026-03-01 16:00:00', 'RECEIVED', 4);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (4, 2, '2026-03-02 09:10:00', 'IN_TRANSIT', 4);
COMMIT;

-- S5: ATL -> MIA
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 5 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (5, 1, '2026-03-03 15:00:00', 'RECEIVED', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (5, 2, '2026-03-04 06:10:00', 'IN_TRANSIT', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (5, 3, '2026-03-06 06:00:00', 'ARRIVED_AT_HUB', 3);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (5, 4, '2026-03-06 08:00:00', 'OUT_FOR_DELIVERY', 3);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (5, 5, '2026-03-06 12:15:00', 'DELIVERED', 3);
COMMIT;

-- S6: ATL -> MIA
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 6 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (6, 1, '2026-03-03 16:30:00', 'RECEIVED', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (6, 2, '2026-03-04 06:10:00', 'IN_TRANSIT', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (6, 3, '2026-03-07 06:00:00', 'ARRIVED_AT_HUB', 3);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (6, 4, '2026-03-07 09:00:00', 'OUT_FOR_DELIVERY', 3);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (6, 5, '2026-03-07 16:20:00', 'DELIVERED', 3);
COMMIT;

-- S7: ORD -> DFW
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 7 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (7, 1, '2026-03-02 11:00:00', 'RECEIVED', 6);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (7, 2, '2026-03-02 20:15:00', 'IN_TRANSIT', 6);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (7, 3, '2026-03-04 06:00:00', 'ARRIVED_AT_HUB', 8);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (7, 4, '2026-03-04 07:30:00', 'OUT_FOR_DELIVERY', 8);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (7, 5, '2026-03-04 11:00:00', 'DELIVERED', 8);
COMMIT;

-- S8: ORD -> DFW
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 8 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (8, 1, '2026-03-02 12:30:00', 'RECEIVED', 6);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (8, 2, '2026-03-02 20:15:00', 'IN_TRANSIT', 6);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (8, 3, '2026-03-05 06:00:00', 'ARRIVED_AT_HUB', 8);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (8, 4, '2026-03-05 07:00:00', 'OUT_FOR_DELIVERY', 8);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (8, 5, '2026-03-05 09:45:00', 'DELIVERED', 8);
COMMIT;

-- S9: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 9 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (9, 1, '2026-03-01 18:40:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (9, 2, '2026-03-01 22:05:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (9, 3, '2026-03-03 06:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (9, 4, '2026-03-03 09:00:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (9, 5, '2026-03-03 12:00:00', 'DELIVERED', 2);
COMMIT;

-- S10: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 10 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (10, 1, '2026-03-07 15:00:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (10, 2, '2026-03-07 22:10:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (10, 3, '2026-03-10 06:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (10, 4, '2026-03-10 08:00:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (10, 5, '2026-03-10 10:30:00', 'DELIVERED', 2);
COMMIT;

-- S11: DFW -> LAX
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 11 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (11, 1, '2026-03-02 19:00:00', 'RECEIVED', 8);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (11, 2, '2026-03-03 08:30:00', 'IN_TRANSIT', 8);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (11, 3, '2026-03-07 05:00:00', 'ARRIVED_AT_HUB', 10);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (11, 4, '2026-03-07 06:00:00', 'OUT_FOR_DELIVERY', 10);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (11, 5, '2026-03-07 08:30:00', 'DELIVERED', 10);
COMMIT;

-- S12: received only
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 12 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (12, 1, '2026-10-28 16:00:00', 'RECEIVED', 1);
COMMIT;

-- S13: received only
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 13 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (13, 1, '2026-10-28 16:30:00', 'RECEIVED', 1);
COMMIT;

-- S14 intentionally has no scan events.

-- S15: received only
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 15 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (15, 1, '2026-10-29 16:00:00', 'RECEIVED', 1);
COMMIT;

-- S16: in transit
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 16 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (16, 1, '2026-10-29 17:00:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (16, 2, '2026-10-30 09:10:00', 'IN_TRANSIT', 1);
COMMIT;

-- S17: in transit
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 17 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (17, 1, '2026-10-29 17:15:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (17, 2, '2026-10-30 09:10:00', 'IN_TRANSIT', 1);
COMMIT;

-- S18: in transit
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 18 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (18, 1, '2026-10-29 17:30:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (18, 2, '2026-10-30 09:10:00', 'IN_TRANSIT', 1);
COMMIT;

-- S19: in transit
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 19 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (19, 1, '2026-10-29 17:45:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (19, 2, '2026-10-30 09:10:00', 'IN_TRANSIT', 1);
COMMIT;

-- S20: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 20 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (20, 1, '2026-01-09 16:00:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (20, 2, '2026-01-10 09:10:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (20, 3, '2026-01-11 06:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (20, 4, '2026-01-11 08:00:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (20, 5, '2026-01-11 10:00:00', 'DELIVERED', 2);
COMMIT;

-- S21: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 21 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (21, 1, '2026-01-09 16:30:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (21, 2, '2026-01-10 09:10:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (21, 3, '2026-01-11 06:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (21, 4, '2026-01-11 08:15:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (21, 5, '2026-01-11 11:00:00', 'DELIVERED', 2);
COMMIT;

-- S22: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 22 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (22, 1, '2026-02-09 16:00:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (22, 2, '2026-02-10 09:10:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (22, 3, '2026-02-11 06:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (22, 4, '2026-02-11 08:00:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (22, 5, '2026-02-11 10:00:00', 'DELIVERED', 2);
COMMIT;

-- S23: RDU -> ATL
START TRANSACTION;
SELECT shipment_id FROM shipment WHERE shipment_id = 23 FOR UPDATE;
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (23, 1, '2026-02-09 16:30:00', 'RECEIVED', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (23, 2, '2026-02-10 09:10:00', 'IN_TRANSIT', 1);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (23, 3, '2026-02-13 06:00:00', 'ARRIVED_AT_HUB', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (23, 4, '2026-02-13 08:00:00', 'OUT_FOR_DELIVERY', 2);
INSERT INTO scan_event (shipment_id, scan_sequence, scan_timestamp, status, hub_id) VALUES (23, 5, '2026-02-13 11:00:00', 'DELIVERED', 2);
COMMIT;
