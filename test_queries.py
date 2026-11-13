"""Integration tests for the six freight analytics queries.

These tests are read-only. They require an explicitly selected analytics schema
and refuse to run against the shared dkhando schema.
"""

import os

from app.db import get_connection
from app import queries


EXPECTED_STATUSES_SHIPMENT_1 = (
    "RECEIVED",
    "IN_TRANSIT",
    "ARRIVED_AT_HUB",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
)
EXPECTED_ELAPSED_MINUTES_SHIPMENT_1 = (None, 65, 595, 270, 90)


def _require_test_schema(connection):
    expected_schema = os.environ.get("ANALYTICS_TEST_SCHEMA", "").strip()
    if not expected_schema:
        raise RuntimeError(
            "Set ANALYTICS_TEST_SCHEMA to the dedicated schema containing "
            "the analytics sample dataset before running these tests."
        )
    if expected_schema.lower() == "dkhando":
        raise RuntimeError(
            "Refusing to run analytics tests against shared schema dkhando."
        )

    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE()")
        actual_schema = cursor.fetchone()[0]
    finally:
        cursor.close()

    if actual_schema != expected_schema:
        raise RuntimeError(
            f"Connected to schema {actual_schema!r}, but "
            f"ANALYTICS_TEST_SCHEMA={expected_schema!r}. "
            "Set DB_NAME to the same dedicated schema."
        )
    return actual_schema


def run_tests():
    connection = get_connection()
    try:
        schema = _require_test_schema(connection)
        print(f"Testing database: {schema}")

        # Q1: exactly three carriers and seven vehicles across all subtypes.
        q1 = queries.get_vehicle_counts_by_carrier(connection)
        assert len(q1) == 3, f"Expected 3 carriers, got {len(q1)}"
        assert sum(sum(row[1:4]) for row in q1) == 7, (
            "Expected 7 vehicles across the three carrier rows"
        )
        assert [row[0] for row in q1] == [1, 2, 3]
        print("PASS Q1: 3 carriers and 7 total vehicles verified")

        # Q2: ten departures; the known 7,500 / 10,000 kg departure is 75%.
        q2 = queries.get_departure_utilization_ranking(connection)
        assert len(q2) == 10, f"Expected 10 departures, got {len(q2)}"
        assert all(0 <= float(row[6]) <= 100 for row in q2), (
            "Utilization must be between 0 and 100 percent"
        )
        departure_1 = next(row for row in q2 if row[0] == 1)
        assert float(departure_1[6]) == 75.0, (
            f"Departure 1 should be 75% utilized, got {departure_1[6]}"
        )
        for lane in {(row[1], row[2]) for row in q2}:
            lane_rows = [row for row in q2 if (row[1], row[2]) == lane]
            percentages = [float(row[6]) for row in lane_rows]
            assert percentages == sorted(percentages, reverse=True), (
                f"Utilization ranking is not descending for lane {lane}"
            )
        print("PASS Q2: 10 departures and utilization rankings verified")

        # Q3: shipment 1 must have the full five-stage canonical scan history.
        q3 = queries.get_scan_time_intervals(connection, 1)
        assert len(q3) == 5, f"Expected 5 scans for shipment 1, got {len(q3)}"
        assert all(row[0] == 1 for row in q3), "Query 3 returned another shipment"
        assert tuple(row[2] for row in q3) == EXPECTED_STATUSES_SHIPMENT_1, (
            f"Unexpected shipment 1 status sequence: {[row[2] for row in q3]}"
        )
        assert tuple(row[5] for row in q3) == EXPECTED_ELAPSED_MINUTES_SHIPMENT_1, (
            f"Unexpected elapsed-minute sequence: {[row[5] for row in q3]}"
        )
        assert q3[0][4] is None, "First scan should have no previous timestamp"
        print(
            "PASS Q3: 5 scans, canonical statuses, and elapsed intervals "
            "(65, 595, 270, 90 minutes) verified"
        )

        # Q4: 14 delivered shipments and cumulative totals by carrier.
        q4 = queries.get_running_delivered_weight_by_carrier(connection)
        assert len(q4) == 14, f"Expected 14 delivered shipments, got {len(q4)}"
        final_totals = {}
        for row in q4:
            carrier_id, _, _, weight, running_total = row
            assert float(running_total) >= float(weight)
            final_totals[carrier_id] = float(running_total)
        assert final_totals == {1: 18000.0, 2: 9500.0, 3: 3500.0}, (
            f"Unexpected final carrier totals: {final_totals}"
        )
        print("PASS Q4: 14 delivered shipments and running totals verified")

        # Q5: three departures each contain at least two distinct shippers.
        q5 = queries.get_departures_with_multiple_shippers(connection)
        assert len(q5) == 3, f"Expected 3 qualifying departures, got {len(q5)}"
        assert all(row[3] >= 2 for row in q5), (
            "A departure has fewer than 2 distinct shippers"
        )
        print("PASS Q5: 3 departures with multiple shippers verified")

        # Q6: shipment 14 is the only shipment without scans.
        q6 = queries.get_shipments_without_scans(connection)
        assert len(q6) == 1, f"Expected 1 shipment without scans, got {len(q6)}"
        assert q6[0][0] == 14, f"Expected shipment 14, got {q6[0][0]}"
        print("PASS Q6: Shipment 14 is the only shipment without scans")

        print("\nAll six analytics integration tests passed!")

    finally:
        connection.close()


if __name__ == "__main__":
    run_tests()
