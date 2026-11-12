
DROP TRIGGER IF EXISTS trg_scan_event_before_insert;

DELIMITER //

CREATE TRIGGER trg_scan_event_before_insert
BEFORE INSERT ON scan_event
FOR EACH ROW
BEGIN
    DECLARE v_shipment_found BOOLEAN DEFAULT TRUE;
    DECLARE v_shipment_id INT UNSIGNED;
    DECLARE v_last_sequence BIGINT UNSIGNED DEFAULT 0;
    DECLARE v_last_timestamp DATETIME;
    DECLARE v_last_status VARCHAR(20);

    IF @@SESSION.tx_isolation <> 'READ-COMMITTED' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Scan inserts require READ COMMITTED and the documented shipment prelock';
    END IF;

    IF NEW.scan_sequence IS NULL OR NEW.scan_sequence < 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'scan_sequence must be positive';
    END IF;

    IF NEW.scan_timestamp IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'scan_timestamp is required';
    END IF;

    IF NEW.status IS NULL OR BINARY NEW.status NOT IN
        ('RECEIVED', 'IN_TRANSIT', 'ARRIVED_AT_HUB',
         'OUT_FOR_DELIVERY', 'DELIVERED') THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Invalid scan status';
    END IF;

    BEGIN
        DECLARE CONTINUE HANDLER FOR NOT FOUND
            SET v_shipment_found = FALSE;

        SELECT shipment_id INTO v_shipment_id
        FROM shipment
        WHERE shipment_id = NEW.shipment_id
        FOR UPDATE;
    END;

    IF NOT v_shipment_found THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Scan shipment does not exist';
    END IF;

    BEGIN
        DECLARE CONTINUE HANDLER FOR NOT FOUND
            SET v_last_sequence = 0;

        SELECT scan_sequence, scan_timestamp, status
        INTO v_last_sequence, v_last_timestamp, v_last_status
        FROM scan_event
        WHERE shipment_id = NEW.shipment_id
        ORDER BY scan_sequence DESC
        LIMIT 1;
    END;

    IF NEW.scan_sequence <> v_last_sequence + 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Invalid scan sequence';
    END IF;

    IF v_last_sequence = 0 THEN
        IF BINARY NEW.status <> 'RECEIVED' THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'The first scan must be RECEIVED';
        END IF;
    ELSE
        IF NEW.scan_timestamp < v_last_timestamp THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Scan timestamps cannot move backward';
        END IF;

        IF NOT (
            (BINARY v_last_status = 'RECEIVED'
                AND BINARY NEW.status = 'IN_TRANSIT')
            OR (BINARY v_last_status = 'IN_TRANSIT'
                AND BINARY NEW.status IN (
                    'IN_TRANSIT', 'ARRIVED_AT_HUB',
                    'OUT_FOR_DELIVERY'
                ))
            OR (BINARY v_last_status = 'ARRIVED_AT_HUB'
                AND BINARY NEW.status IN (
                    'ARRIVED_AT_HUB', 'IN_TRANSIT',
                    'OUT_FOR_DELIVERY'
                ))
            OR (BINARY v_last_status = 'OUT_FOR_DELIVERY'
                AND BINARY NEW.status IN (
                    'OUT_FOR_DELIVERY', 'DELIVERED'
                ))
        ) THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Invalid or regressing scan status transition';
        END IF;
    END IF;
END//

DELIMITER ;
