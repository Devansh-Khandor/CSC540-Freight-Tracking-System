-- CSC 540 Deliverable 2 / Task 3A -- MariaDB 10.5.22
-- Review before execution. Run once in the EXISTING assigned schema selected
-- by the client. No CREATE DATABASE, DROP, replacement, or sample data.
-- This is an installation script, not a migration of preliminary tables.
-- DDL implicitly commits: a failed installation must be inspected, not rerun
-- blindly. Do not use the client's --force option.
-- Exactly 14 tables, one procedure, and two scan INSERT triggers.
-- See schema_design_notes.md for the REQUIRED write/transaction policy.
-- In particular: no direct booking DML, logistics updates only through the
-- documented locking protocol, no scan UPDATE/DELETE, and READ COMMITTED +
-- prelocked shipment for scans. Application permissions are not DB privileges.

SET @csc540_previous_sql_mode = @@SESSION.sql_mode;
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ZERO_DATE,NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION';

-- ACCOUNT - Stores all application user accounts and their roles.
CREATE TABLE account (
    account_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(10) NOT NULL,

    CONSTRAINT pk_account
        PRIMARY KEY (account_id),
    CONSTRAINT chk_account_role
        CHECK (BINARY role IN ('SHIPPER', 'CARRIER', 'VIEWER'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- SHIPPER - Stores accounts that are shippers.
CREATE TABLE shipper (
    account_id INT UNSIGNED NOT NULL,

    CONSTRAINT pk_shipper
        PRIMARY KEY (account_id),
    CONSTRAINT fk_shipper_account
        FOREIGN KEY (account_id)
        REFERENCES account(account_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- CARRIER - Stores accounts that are carriers.
CREATE TABLE carrier (
    account_id INT UNSIGNED NOT NULL,

    CONSTRAINT pk_carrier
        PRIMARY KEY (account_id),
    CONSTRAINT fk_carrier_account
        FOREIGN KEY (account_id)
        REFERENCES account(account_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- VIEWER - Stores accounts that have read-only viewer access.
CREATE TABLE viewer (
    account_id INT UNSIGNED NOT NULL,

    CONSTRAINT pk_viewer
        PRIMARY KEY (account_id),
    CONSTRAINT fk_viewer_account
        FOREIGN KEY (account_id)
        REFERENCES account(account_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- HUB - Stores logistics hubs and their regions.
CREATE TABLE hub (
    hub_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    region VARCHAR(20) NOT NULL,

    CONSTRAINT pk_hub
        PRIMARY KEY (hub_id),
    CONSTRAINT chk_hub_region
        CHECK (BINARY region IN ('Northeast', 'Southeast', 'Midwest', 'Southwest', 'West'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- LANE - Stores valid origin-to-destination hub routes.
-- MariaDB 10.5 disallows cascading updates to columns used by this CHECK.
-- Hub IDs are immutable by application policy; referenced IDs are RESTRICTed.
CREATE TABLE lane (
    origin_hub_id INT UNSIGNED NOT NULL,
    destination_hub_id INT UNSIGNED NOT NULL,

    INDEX idx_lane_destination (destination_hub_id),

    CONSTRAINT pk_lane
        PRIMARY KEY (origin_hub_id, destination_hub_id),
    CONSTRAINT fk_lane_origin
        FOREIGN KEY (origin_hub_id)
        REFERENCES hub(hub_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT fk_lane_destination
        FOREIGN KEY (destination_hub_id)
        REFERENCES hub(hub_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT chk_lane_different_hubs
        CHECK (origin_hub_id <> destination_hub_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- SHIPMENT - Stores shipments, their routes, weight, delivery promise, and status.
CREATE TABLE shipment (
    shipment_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    shipper_account_id INT UNSIGNED NOT NULL,
    origin_hub_id INT UNSIGNED NOT NULL,
    destination_hub_id INT UNSIGNED NOT NULL,
    weight_kg DECIMAL(10,2) NOT NULL,
    promised_delivery_date DATE NOT NULL,
    current_status VARCHAR(20) NULL,
    delivery_outcome VARCHAR(10) NULL,

    INDEX idx_shipment_shipper_promise (shipper_account_id, promised_delivery_date),
    INDEX idx_shipment_lane (origin_hub_id, destination_hub_id),
    INDEX idx_shipment_status_promise (current_status, promised_delivery_date),

    CONSTRAINT pk_shipment
        PRIMARY KEY (shipment_id),
    CONSTRAINT fk_shipment_shipper
        FOREIGN KEY (shipper_account_id)
        REFERENCES shipper(account_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_shipment_lane
        FOREIGN KEY (origin_hub_id, destination_hub_id)
        REFERENCES lane(origin_hub_id, destination_hub_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_shipment_weight
        CHECK (weight_kg > 0),
    CONSTRAINT chk_shipment_current_status
        CHECK (current_status IS NULL OR BINARY current_status IN
            ('RECEIVED', 'IN_TRANSIT', 'ARRIVED_AT_HUB', 'OUT_FOR_DELIVERY', 'DELIVERED')),
    CONSTRAINT chk_shipment_status_outcome
        CHECK (
            (current_status IS NULL AND delivery_outcome IS NULL)
            OR (current_status IS NOT NULL AND (
                (BINARY current_status <> 'DELIVERED' AND delivery_outcome IS NULL)
                OR (BINARY current_status = 'DELIVERED' AND delivery_outcome IS NOT NULL)
            ))
        ),
    CONSTRAINT chk_shipment_delivery_outcome
        CHECK (delivery_outcome IS NULL OR BINARY delivery_outcome IN ('ON_TIME', 'LATE'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- VEHICLE - Stores vehicles owned by carriers and their home hubs.
CREATE TABLE vehicle (
    vehicle_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    carrier_account_id INT UNSIGNED NOT NULL,
    home_hub_id INT UNSIGNED NOT NULL,

    INDEX idx_vehicle_carrier (carrier_account_id),
    INDEX idx_vehicle_home_hub (home_hub_id),

    CONSTRAINT pk_vehicle
        PRIMARY KEY (vehicle_id),
    CONSTRAINT fk_vehicle_carrier
        FOREIGN KEY (carrier_account_id)
        REFERENCES carrier(account_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_vehicle_home_hub
        FOREIGN KEY (home_hub_id)
        REFERENCES hub(hub_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- BOX_TRUCK - Stores attributes specific to box truck vehicles.
CREATE TABLE box_truck (
    vehicle_id INT UNSIGNED NOT NULL,
    cargo_volume DECIMAL(10,2) NOT NULL,
    gross_weight_rating DECIMAL(10,2) NOT NULL,

    CONSTRAINT pk_box_truck
        PRIMARY KEY (vehicle_id),
    CONSTRAINT fk_box_truck_vehicle
        FOREIGN KEY (vehicle_id)
        REFERENCES vehicle(vehicle_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT chk_box_truck_cargo_volume
        CHECK (cargo_volume > 0),
    CONSTRAINT chk_box_truck_gross_weight_rating
        CHECK (gross_weight_rating > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- REFRIGERATED_VAN - Stores attributes specific to refrigerated van vehicles.
CREATE TABLE refrigerated_van (
    vehicle_id INT UNSIGNED NOT NULL,
    temperature_range VARCHAR(50) NOT NULL,
    payload_limit DECIMAL(10,2) NOT NULL,

    CONSTRAINT pk_refrigerated_van
        PRIMARY KEY (vehicle_id),
    CONSTRAINT fk_refrigerated_van_vehicle
        FOREIGN KEY (vehicle_id)
        REFERENCES vehicle(vehicle_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT chk_refrigerated_van_payload_limit
        CHECK (payload_limit > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- RAIL_CAR - Stores attributes specific to rail car vehicles.
CREATE TABLE rail_car (
    vehicle_id INT UNSIGNED NOT NULL,
    axle_count INT UNSIGNED NOT NULL,
    track_gauge DECIMAL(6,2) NOT NULL,

    CONSTRAINT pk_rail_car
        PRIMARY KEY (vehicle_id),
    CONSTRAINT fk_rail_car_vehicle
        FOREIGN KEY (vehicle_id)
        REFERENCES vehicle(vehicle_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT chk_rail_car_axle_count
        CHECK (axle_count > 0),
    CONSTRAINT chk_rail_car_track_gauge
        CHECK (track_gauge > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- DEPARTURE - Stores scheduled vehicle departures between hubs.
CREATE TABLE departure (
    departure_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    vehicle_id INT UNSIGNED NOT NULL,
    origin_hub_id INT UNSIGNED NOT NULL,
    destination_hub_id INT UNSIGNED NOT NULL,
    departure_datetime DATETIME NOT NULL,
    max_total_weight_kg DECIMAL(10,2) NOT NULL,

    INDEX idx_departure_vehicle_time (vehicle_id, departure_datetime),
    INDEX idx_departure_lane_time (origin_hub_id, destination_hub_id, departure_datetime),

    CONSTRAINT pk_departure
        PRIMARY KEY (departure_id),
    CONSTRAINT fk_departure_vehicle
        FOREIGN KEY (vehicle_id)
        REFERENCES vehicle(vehicle_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_departure_lane
        FOREIGN KEY (origin_hub_id, destination_hub_id)
        REFERENCES lane(origin_hub_id, destination_hub_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_departure_max_total_weight
        CHECK (max_total_weight_kg > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- BOOKING - Stores which shipments are booked onto which departures.
CREATE TABLE booking (
    shipment_id INT UNSIGNED NOT NULL,
    departure_id INT UNSIGNED NOT NULL,

    INDEX idx_booking_departure (departure_id),

    CONSTRAINT pk_booking
        PRIMARY KEY (shipment_id, departure_id),
    CONSTRAINT uq_booking_shipment
        UNIQUE (shipment_id),
    CONSTRAINT fk_booking_shipment
        FOREIGN KEY (shipment_id)
        REFERENCES shipment(shipment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_booking_departure
        FOREIGN KEY (departure_id)
        REFERENCES departure(departure_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- SCAN_EVENT - Stores the ordered movement and status history of shipments.
CREATE TABLE scan_event (
    shipment_id INT UNSIGNED NOT NULL,
    scan_sequence INT UNSIGNED NOT NULL,
    scan_timestamp DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL,
    hub_id INT UNSIGNED NOT NULL,

    INDEX idx_scan_event_hub (hub_id),
    INDEX idx_scan_event_shipment_time (shipment_id, scan_timestamp),
    INDEX idx_scan_event_status_time (status, scan_timestamp, shipment_id),

    CONSTRAINT pk_scan_event
        PRIMARY KEY (shipment_id, scan_sequence),
    CONSTRAINT fk_scan_event_shipment
        FOREIGN KEY (shipment_id)
        REFERENCES shipment(shipment_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_scan_event_hub
        FOREIGN KEY (hub_id)
        REFERENCES hub(hub_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_scan_event_sequence
        CHECK (scan_sequence >= 1),
    CONSTRAINT chk_scan_event_status
        CHECK (BINARY status IN
            ('RECEIVED', 'IN_TRANSIT', 'ARRIVED_AT_HUB', 'OUT_FOR_DELIVERY', 'DELIVERED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

DELIMITER $$

-- Owns its transaction. Call on an idle connection, never inside a caller's
-- transaction. SERIAL ORDER: departure first, then the candidate shipment.
CREATE PROCEDURE book_shipment (
    IN p_shipment_id INT UNSIGNED,
    IN p_departure_id INT UNSIGNED
)
MODIFIES SQL DATA
SQL SECURITY DEFINER
BEGIN
    -- Outside the handler block: rejection must not roll back caller work.
    IF @@SESSION.in_transaction = 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'book_shipment requires an idle connection; finish the current transaction';
    END IF;

    BEGIN
        DECLARE v_departure_found BOOLEAN DEFAULT TRUE;
        DECLARE v_shipment_found BOOLEAN DEFAULT TRUE;
        DECLARE v_departure_origin INT UNSIGNED;
        DECLARE v_departure_destination INT UNSIGNED;
        DECLARE v_capacity DECIMAL(10,2);
        DECLARE v_shipment_origin INT UNSIGNED;
        DECLARE v_shipment_destination INT UNSIGNED;
        DECLARE v_weight DECIMAL(10,2);
        DECLARE v_booking_count BIGINT UNSIGNED;
        DECLARE v_booked_weight DECIMAL(32,2);

        DECLARE EXIT HANDLER FOR SQLEXCEPTION
        BEGIN
            ROLLBACK;
            RESIGNAL;
        END;

        -- One-transaction setting; does not change the session default.
        -- Each aggregate/duplicate check sees commits preceding that read,
        -- including a competing booking that released our departure lock.
        SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
        START TRANSACTION;

        IF p_shipment_id IS NULL OR p_shipment_id = 0
            OR p_departure_id IS NULL OR p_departure_id = 0 THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Shipment ID and departure ID must be positive';
        END IF;

        BEGIN
            DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_departure_found = FALSE;
            SELECT origin_hub_id, destination_hub_id, max_total_weight_kg
              INTO v_departure_origin, v_departure_destination, v_capacity
              FROM departure
             WHERE departure_id = p_departure_id
             FOR UPDATE;
        END;
        IF NOT v_departure_found THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Departure does not exist';
        END IF;

        BEGIN
            DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_shipment_found = FALSE;
            SELECT origin_hub_id, destination_hub_id, weight_kg
              INTO v_shipment_origin, v_shipment_destination, v_weight
              FROM shipment
             WHERE shipment_id = p_shipment_id
             FOR UPDATE;
        END;
        IF NOT v_shipment_found THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Shipment does not exist';
        END IF;

        IF v_shipment_origin <> v_departure_origin
            OR v_shipment_destination <> v_departure_destination THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Shipment lane does not match the ordered departure lane';
        END IF;

        SELECT COUNT(*) INTO v_booking_count
          FROM booking WHERE shipment_id = p_shipment_id;
        IF v_booking_count <> 0 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Shipment is already booked';
        END IF;

        -- Required aggregate, not a cached weight counter.
        -- All supported booking writers hold this same departure row lock.
        -- Supported weight/capacity edits also take this departure lock before
        -- validating SUM and writing. Arbitrary owner DML bypasses the policy.
        SELECT COALESCE(SUM(s.weight_kg), 0.00) INTO v_booked_weight
          FROM booking AS b
          JOIN shipment AS s ON s.shipment_id = b.shipment_id
         WHERE b.departure_id = p_departure_id;

        IF v_booked_weight + v_weight > v_capacity THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Departure weight capacity would be exceeded';
        END IF;

        INSERT INTO booking (shipment_id, departure_id)
        VALUES (p_shipment_id, p_departure_id);
        COMMIT;
    END;
END$$

-- REQUIRED caller protocol (see notes): SET SESSION isolation READ COMMITTED
-- before START TRANSACTION; lock this shipment in a separate SELECT ... FOR
-- UPDATE BEFORE issuing a single-row INSERT ... VALUES. No one-shot isolation
-- overrides, INSERT ... SELECT, REPLACE, IGNORE, or ON DUPLICATE KEY UPDATE.
-- The prelock ensures the INSERT starts after any competing scan commits.
-- Reading scan_event here is nonlocking; no unsupported self-table mutation.
CREATE TRIGGER trg_scan_event_before_insert
BEFORE INSERT ON scan_event
FOR EACH ROW
BEGIN
    DECLARE v_shipment_found BOOLEAN DEFAULT TRUE;
    DECLARE v_shipment_id INT UNSIGNED;
    DECLARE v_last_sequence BIGINT UNSIGNED DEFAULT 0;
    DECLARE v_last_timestamp DATETIME;
    DECLARE v_last_status VARCHAR(20);

    -- MariaDB 10.5 uses tx_isolation. This checks the session default only;
    -- the caller must not override the isolation for an individual transaction.
    IF @@SESSION.tx_isolation <> 'READ-COMMITTED' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Scan inserts require READ COMMITTED and the documented shipment prelock';
    END IF;

    IF NEW.scan_sequence IS NULL OR NEW.scan_sequence < 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'scan_sequence must be positive';
    END IF;
    IF NEW.scan_timestamp IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'scan_timestamp is required';
    END IF;
    IF NEW.status IS NULL OR BINARY NEW.status NOT IN
        ('RECEIVED', 'IN_TRANSIT', 'ARRIVED_AT_HUB', 'OUT_FOR_DELIVERY', 'DELIVERED') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid scan status';
    END IF;

    BEGIN
        DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_shipment_found = FALSE;
        SELECT shipment_id INTO v_shipment_id
          FROM shipment WHERE shipment_id = NEW.shipment_id
          FOR UPDATE;
    END;
    IF NOT v_shipment_found THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Scan shipment does not exist';
    END IF;

    BEGIN
        DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_last_sequence = 0;
        SELECT scan_sequence, scan_timestamp, status
          INTO v_last_sequence, v_last_timestamp, v_last_status
          FROM scan_event
         WHERE shipment_id = NEW.shipment_id
         ORDER BY scan_sequence DESC
         LIMIT 1;
    END;

    IF NEW.scan_sequence <> v_last_sequence + 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'scan_sequence must be 1 initially, then exactly previous sequence plus 1';
    END IF;

    IF v_last_sequence = 0 THEN
        IF BINARY NEW.status <> 'RECEIVED' THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The first scan must be RECEIVED';
        END IF;
    ELSE
        IF NEW.scan_timestamp < v_last_timestamp THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Scan timestamps cannot move backward';
        END IF;
        -- IN_TRANSIT and ARRIVED_AT_HUB share the line-haul stage. Cycling
        -- between them supports intermediate hubs without returning to RECEIVED
        -- or moving backward from last-mile delivery. DELIVERED is terminal.
        IF NOT (
            (BINARY v_last_status = 'RECEIVED' AND BINARY NEW.status = 'IN_TRANSIT')
            OR (BINARY v_last_status = 'IN_TRANSIT'
                AND BINARY NEW.status IN (
                    'IN_TRANSIT',
                    'ARRIVED_AT_HUB',
                    'OUT_FOR_DELIVERY'
                ))
            OR (BINARY v_last_status = 'ARRIVED_AT_HUB'
                AND BINARY NEW.status IN ('ARRIVED_AT_HUB', 'IN_TRANSIT', 'OUT_FOR_DELIVERY'))
            OR (BINARY v_last_status = 'OUT_FOR_DELIVERY'
                AND BINARY NEW.status IN ('OUT_FOR_DELIVERY', 'DELIVERED'))
        ) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid or regressing scan status transition';
        END IF;
    END IF;
END$$

CREATE TRIGGER trg_scan_event_after_insert
AFTER INSERT ON scan_event
FOR EACH ROW
BEGIN
    -- DATETIME and promised DATE use the same application calendar (ET).
    -- Both fields change in one statement so their CHECK constraint holds.
    UPDATE shipment
       SET current_status = NEW.status,
           delivery_outcome = CASE
               WHEN BINARY NEW.status = 'DELIVERED' THEN
                   CASE WHEN DATE(NEW.scan_timestamp) <= promised_delivery_date
                       THEN 'ON_TIME' ELSE 'LATE' END
               ELSE NULL
           END
     WHERE shipment_id = NEW.shipment_id;
END$$

DELIMITER ;

SET SESSION sql_mode = @csc540_previous_sql_mode;

