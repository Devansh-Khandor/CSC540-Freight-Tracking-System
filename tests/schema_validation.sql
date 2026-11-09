-- Read-only structural inspection for MariaDB 10.5; no DDL/DML or CALL.
-- Run in the intended existing schema after reviewing/applying 01_schema.sql.
-- PASS/FAIL are result values, not process exit codes. Inspect every result.
-- Missing metadata privileges can look like missing objects: use the installer
-- account for this inspection. Unrelated objects are listed, never modified.

SELECT VERSION() AS actual_server_version, DATABASE() AS selected_schema,
       @@SESSION.foreign_key_checks AS foreign_key_checks_must_be_1,
       @@SESSION.check_constraint_checks AS check_constraint_checks_must_be_1,
       @@GLOBAL.log_bin AS binary_logging_enabled,
       @@SESSION.binlog_format AS binary_logging_format,
       @@SESSION.sql_mode AS session_sql_mode,
       @@SESSION.tx_isolation AS session_isolation;

WITH expected AS (
    SELECT 'account' AS table_name UNION ALL SELECT 'shipper'
    UNION ALL SELECT 'carrier' UNION ALL SELECT 'viewer'
    UNION ALL SELECT 'hub' UNION ALL SELECT 'lane'
    UNION ALL SELECT 'shipment' UNION ALL SELECT 'vehicle'
    UNION ALL SELECT 'box_truck' UNION ALL SELECT 'refrigerated_van'
    UNION ALL SELECT 'rail_car' UNION ALL SELECT 'departure'
    UNION ALL SELECT 'booking' UNION ALL SELECT 'scan_event'
)
SELECT e.table_name, t.engine, t.table_collation,
       CASE WHEN t.table_type = 'BASE TABLE' AND t.engine = 'InnoDB'
            AND t.table_collation = 'utf8mb4_bin' THEN 'PASS' ELSE 'FAIL' END AS result
  FROM expected AS e
  LEFT JOIN information_schema.tables AS t
    ON t.table_schema = DATABASE() AND t.table_name = e.table_name
 ORDER BY e.table_name;

-- In a dedicated project schema expect 14 base tables, one procedure, two triggers.
SELECT 'base_tables' AS object_kind, COUNT(*) AS actual_count, 14 AS expected_count
  FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
UNION ALL
SELECT 'procedures', COUNT(*), 1 FROM information_schema.routines
 WHERE routine_schema = DATABASE() AND routine_type = 'PROCEDURE'
UNION ALL
SELECT 'triggers', COUNT(*), 2 FROM information_schema.triggers
 WHERE trigger_schema = DATABASE();

WITH expected AS (
    SELECT 'account' AS table_name, 'account_id' AS columns_in_order
    UNION ALL SELECT 'shipper', 'account_id'
    UNION ALL SELECT 'carrier', 'account_id'
    UNION ALL SELECT 'viewer', 'account_id'
    UNION ALL SELECT 'hub', 'hub_id'
    UNION ALL SELECT 'lane', 'origin_hub_id,destination_hub_id'
    UNION ALL SELECT 'shipment', 'shipment_id'
    UNION ALL SELECT 'vehicle', 'vehicle_id'
    UNION ALL SELECT 'box_truck', 'vehicle_id'
    UNION ALL SELECT 'refrigerated_van', 'vehicle_id'
    UNION ALL SELECT 'rail_car', 'vehicle_id'
    UNION ALL SELECT 'departure', 'departure_id'
    UNION ALL SELECT 'booking', 'shipment_id,departure_id'
    UNION ALL SELECT 'scan_event', 'shipment_id,scan_sequence'
), actual AS (
    SELECT table_name,
           GROUP_CONCAT(column_name ORDER BY ordinal_position SEPARATOR ',') AS columns_in_order
      FROM information_schema.key_column_usage
     WHERE constraint_schema = DATABASE() AND constraint_name = 'PRIMARY'
     GROUP BY table_name
)
SELECT e.table_name, e.columns_in_order AS expected_pk, a.columns_in_order AS actual_pk,
       CASE WHEN a.columns_in_order = e.columns_in_order THEN 'PASS' ELSE 'FAIL' END AS result
  FROM expected AS e LEFT JOIN actual AS a ON a.table_name = e.table_name
 ORDER BY e.table_name;

WITH expected AS (
    SELECT 'shipper' AS table_name, 'account_id' AS child_columns,
           'account' AS parent_table, 'account_id' AS parent_columns, 'CASCADE' AS delete_rule, 'CASCADE' AS update_rule
    UNION ALL SELECT 'carrier', 'account_id', 'account', 'account_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'viewer', 'account_id', 'account', 'account_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'lane', 'origin_hub_id', 'hub', 'hub_id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'lane', 'destination_hub_id', 'hub', 'hub_id', 'RESTRICT', 'RESTRICT'
    UNION ALL SELECT 'shipment', 'shipper_account_id', 'shipper', 'account_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'shipment', 'origin_hub_id,destination_hub_id', 'lane', 'origin_hub_id,destination_hub_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'vehicle', 'carrier_account_id', 'carrier', 'account_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'vehicle', 'home_hub_id', 'hub', 'hub_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'box_truck', 'vehicle_id', 'vehicle', 'vehicle_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'refrigerated_van', 'vehicle_id', 'vehicle', 'vehicle_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'rail_car', 'vehicle_id', 'vehicle', 'vehicle_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'departure', 'vehicle_id', 'vehicle', 'vehicle_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'departure', 'origin_hub_id,destination_hub_id', 'lane', 'origin_hub_id,destination_hub_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'booking', 'shipment_id', 'shipment', 'shipment_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'booking', 'departure_id', 'departure', 'departure_id', 'RESTRICT', 'CASCADE'
    UNION ALL SELECT 'scan_event', 'shipment_id', 'shipment', 'shipment_id', 'CASCADE', 'CASCADE'
    UNION ALL SELECT 'scan_event', 'hub_id', 'hub', 'hub_id', 'RESTRICT', 'CASCADE'
), actual AS (
    SELECT k.table_name, k.constraint_name, k.referenced_table_name AS parent_table,
           GROUP_CONCAT(k.column_name ORDER BY k.ordinal_position SEPARATOR ',') AS child_columns,
           GROUP_CONCAT(k.referenced_column_name ORDER BY k.ordinal_position SEPARATOR ',') AS parent_columns,
           r.update_rule, r.delete_rule
      FROM information_schema.key_column_usage AS k
      JOIN information_schema.referential_constraints AS r
        ON r.constraint_schema = k.constraint_schema
       AND r.table_name = k.table_name AND r.constraint_name = k.constraint_name
     WHERE k.constraint_schema = DATABASE() AND k.referenced_table_schema = DATABASE()
     GROUP BY k.table_name, k.constraint_name, k.referenced_table_name, r.update_rule, r.delete_rule
)
SELECT e.table_name, e.child_columns, e.parent_table, e.parent_columns,
       a.constraint_name, e.update_rule AS expected_update_rule, a.update_rule, a.delete_rule,
       CASE WHEN a.update_rule = e.update_rule AND a.delete_rule = e.delete_rule
            THEN 'PASS' ELSE 'FAIL' END AS result
  FROM expected AS e LEFT JOIN actual AS a
    ON a.table_name = e.table_name AND a.child_columns = e.child_columns
   AND a.parent_table = e.parent_table AND a.parent_columns = e.parent_columns
 ORDER BY e.table_name, e.child_columns;

-- Verify that every child FK has a complete left-prefix BTREE index.
SELECT f.table_name, f.constraint_name,
       CASE WHEN EXISTS (
           SELECT 1 FROM information_schema.statistics AS candidate
            WHERE candidate.table_schema = f.constraint_schema
              AND candidate.table_name = f.table_name
              AND candidate.seq_in_index = 1 AND candidate.index_type = 'BTREE'
              AND NOT EXISTS (
                  SELECT 1 FROM information_schema.key_column_usage AS k
                   WHERE k.constraint_schema = f.constraint_schema
                     AND k.table_name = f.table_name AND k.constraint_name = f.constraint_name
                     AND NOT EXISTS (
                         SELECT 1 FROM information_schema.statistics AS s
                          WHERE s.table_schema = k.constraint_schema AND s.table_name = k.table_name
                            AND s.index_name = candidate.index_name
                            AND s.seq_in_index = k.ordinal_position
                            AND s.column_name = k.column_name AND s.sub_part IS NULL
                     )
              )
       ) THEN 'PASS' ELSE 'FAIL' END AS child_fk_index
  FROM information_schema.referential_constraints AS f
 WHERE f.constraint_schema = DATABASE()
 ORDER BY f.table_name, f.constraint_name;

WITH expected AS (
    SELECT 'lane' AS table_name, 'idx_lane_destination' AS index_name,
           'destination_hub_id' AS columns_in_order, 1 AS non_unique
    UNION ALL SELECT 'shipment', 'idx_shipment_shipper_promise', 'shipper_account_id,promised_delivery_date', 1
    UNION ALL SELECT 'shipment', 'idx_shipment_lane', 'origin_hub_id,destination_hub_id', 1
    UNION ALL SELECT 'shipment', 'idx_shipment_status_promise', 'current_status,promised_delivery_date', 1
    UNION ALL SELECT 'vehicle', 'idx_vehicle_carrier', 'carrier_account_id', 1
    UNION ALL SELECT 'vehicle', 'idx_vehicle_home_hub', 'home_hub_id', 1
    UNION ALL SELECT 'departure', 'idx_departure_vehicle_time', 'vehicle_id,departure_datetime', 1
    UNION ALL SELECT 'departure', 'idx_departure_lane_time', 'origin_hub_id,destination_hub_id,departure_datetime', 1
    UNION ALL SELECT 'booking', 'uq_booking_shipment', 'shipment_id', 0
    UNION ALL SELECT 'booking', 'idx_booking_departure', 'departure_id', 1
    UNION ALL SELECT 'scan_event', 'idx_scan_event_hub', 'hub_id', 1
    UNION ALL SELECT 'scan_event', 'idx_scan_event_shipment_time', 'shipment_id,scan_timestamp', 1
    UNION ALL SELECT 'scan_event', 'idx_scan_event_status_time', 'status,scan_timestamp,shipment_id', 1
), actual AS (
    SELECT table_name, index_name, non_unique,
           GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',') AS columns_in_order
      FROM information_schema.statistics WHERE table_schema = DATABASE()
     GROUP BY table_name, index_name, non_unique
)
SELECT e.table_name, e.index_name, a.columns_in_order,
       CASE WHEN a.columns_in_order = e.columns_in_order AND a.non_unique = e.non_unique
            THEN 'PASS' ELSE 'FAIL' END AS result
  FROM expected AS e LEFT JOIN actual AS a
    ON a.table_name = e.table_name AND a.index_name = e.index_name
 ORDER BY e.table_name, e.index_name;

WITH expected AS (
    SELECT 'chk_account_role' AS constraint_name UNION ALL SELECT 'chk_hub_region'
    UNION ALL SELECT 'chk_lane_different_hubs' UNION ALL SELECT 'chk_shipment_weight'
    UNION ALL SELECT 'chk_shipment_current_status' UNION ALL SELECT 'chk_shipment_status_outcome'
    UNION ALL SELECT 'chk_shipment_delivery_outcome' UNION ALL SELECT 'chk_box_truck_cargo_volume'
    UNION ALL SELECT 'chk_box_truck_gross_weight_rating' UNION ALL SELECT 'chk_refrigerated_van_payload_limit'
    UNION ALL SELECT 'chk_rail_car_axle_count' UNION ALL SELECT 'chk_rail_car_track_gauge'
    UNION ALL SELECT 'chk_departure_max_total_weight' UNION ALL SELECT 'chk_scan_event_sequence'
    UNION ALL SELECT 'chk_scan_event_status'
)
SELECT e.constraint_name, c.check_clause,
       CASE WHEN c.constraint_name IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS present
  FROM expected AS e LEFT JOIN information_schema.check_constraints AS c
    ON c.constraint_schema = DATABASE() AND c.constraint_name = e.constraint_name
 ORDER BY e.constraint_name;
-- Inspect printed CHECK clauses as well as presence; this does not execute them.

WITH expected AS (
    SELECT 'current_status' AS column_name UNION ALL SELECT 'delivery_outcome'
)
SELECT e.column_name, c.column_type, c.is_nullable,
       CASE WHEN c.is_nullable = 'YES' THEN 'PASS' ELSE 'FAIL' END AS result
  FROM expected AS e LEFT JOIN information_schema.columns AS c
    ON c.table_schema = DATABASE() AND c.table_name = 'shipment' AND c.column_name = e.column_name;

SELECT CASE WHEN COUNT(*) = 1 THEN 'PASS' ELSE 'FAIL' END AS booking_procedure
  FROM information_schema.routines
 WHERE routine_schema = DATABASE() AND routine_name = 'book_shipment'
   AND routine_type = 'PROCEDURE' AND security_type = 'DEFINER'
   AND sql_data_access = 'MODIFIES SQL DATA';

SELECT parameter_name, parameter_mode, dtd_identifier, ordinal_position
  FROM information_schema.parameters
 WHERE specific_schema = DATABASE() AND specific_name = 'book_shipment'
 ORDER BY ordinal_position;
-- Expect IN p_shipment_id INT UNSIGNED, then IN p_departure_id INT UNSIGNED.

WITH expected AS (
    SELECT 'trg_scan_event_before_insert' AS trigger_name, 'BEFORE' AS timing
    UNION ALL SELECT 'trg_scan_event_after_insert', 'AFTER'
)
SELECT e.trigger_name, t.event_object_table, t.action_timing, t.event_manipulation,
       CASE WHEN t.event_object_table = 'scan_event' AND t.action_timing = e.timing
            AND t.event_manipulation = 'INSERT' AND t.action_orientation = 'ROW'
            THEN 'PASS' ELSE 'FAIL' END AS result
  FROM expected AS e LEFT JOIN information_schema.triggers AS t
    ON t.trigger_schema = DATABASE() AND t.trigger_name = e.trigger_name;

-- Read-only definitions for review. These statements fail if objects are absent.
SHOW CREATE PROCEDURE book_shipment;
SHOW CREATE TRIGGER trg_scan_event_before_insert;
SHOW CREATE TRIGGER trg_scan_event_after_insert;
