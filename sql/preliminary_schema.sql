-- ACCOUNT - Stores all application user accounts and their roles.
CREATE TABLE account (
    account_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(10) NOT NULL,

    CONSTRAINT pk_account
        PRIMARY KEY (account_id),
    CONSTRAINT chk_account_role
        CHECK (BINARY role IN ('SHIPPER', 'CARRIER', 'VIEWER'))
);

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
);

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
);

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
);

-- HUB - Stores logistics hubs and their regions.
CREATE TABLE hub (
    hub_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    region VARCHAR(20) NOT NULL,

    CONSTRAINT pk_hub
        PRIMARY KEY (hub_id),
    CONSTRAINT chk_hub_region
        CHECK (BINARY region IN ('Northeast', 'Southeast', 'Midwest', 'Southwest', 'West'))
);

-- LANE - Stores valid origin-to-destination hub routes.
CREATE TABLE lane (
    origin_hub_id INT UNSIGNED NOT NULL,
    destination_hub_id INT UNSIGNED NOT NULL,

    CONSTRAINT pk_lane
        PRIMARY KEY (origin_hub_id, destination_hub_id),
    CONSTRAINT fk_lane_origin
        FOREIGN KEY (origin_hub_id)
        REFERENCES hub(hub_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_lane_destination
        FOREIGN KEY (destination_hub_id)
        REFERENCES hub(hub_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_lane_different_hubs
        CHECK (origin_hub_id <> destination_hub_id)
);

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
    CONSTRAINT chk_shipment_delivery_outcome
        CHECK (delivery_outcome IS NULL OR BINARY delivery_outcome IN ('ON_TIME', 'LATE'))
);

-- VEHICLE - Stores vehicles owned by carriers and their home hubs.
CREATE TABLE vehicle (
    vehicle_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    carrier_account_id INT UNSIGNED NOT NULL,
    home_hub_id INT UNSIGNED NOT NULL,

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
);

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
);

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
);

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
);

-- DEPARTURE - Stores scheduled vehicle departures between hubs.
CREATE TABLE departure (
    departure_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    vehicle_id INT UNSIGNED NOT NULL,
    origin_hub_id INT UNSIGNED NOT NULL,
    destination_hub_id INT UNSIGNED NOT NULL,
    departure_datetime DATETIME NOT NULL,
    max_total_weight_kg DECIMAL(10,2) NOT NULL,

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
);

-- BOOKING - Stores which shipments are booked onto which departures.
CREATE TABLE booking (
    shipment_id INT UNSIGNED NOT NULL,
    departure_id INT UNSIGNED NOT NULL,

    CONSTRAINT pk_booking
        PRIMARY KEY (shipment_id, departure_id),
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
);

-- SCAN_EVENT - Stores the ordered movement and status history of shipments.
CREATE TABLE scan_event (
    shipment_id INT UNSIGNED NOT NULL,
    scan_sequence INT UNSIGNED NOT NULL,
    scan_timestamp DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL,
    hub_id INT UNSIGNED NOT NULL,

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
    CONSTRAINT chk_scan_event_status_not_blank
        CHECK (CHAR_LENGTH(TRIM(status)) > 0)
);

-- INDEXES - Improve performance for booking and shipment tracking queries.
CREATE INDEX idx_booking_departure
    ON booking (departure_id);

CREATE INDEX idx_scan_event_shipment_time
    ON scan_event (shipment_id, scan_timestamp);