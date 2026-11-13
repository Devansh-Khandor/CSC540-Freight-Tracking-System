
"""Read-only analytics integration tests for the freight tracking database.

Run with ANALYTICS_TEST_SCHEMA set to the exact schema being tested.
These tests do not insert, update, or delete database records.
"""

import os

from app.db import get_connection
from app import queries


EXPECTED_TEST_SCHEMA_ENV = "ANALYTICS_TEST_SCHEMA"


def run_tests():
    expected_schema = os.environ.get(EXPECTED_TEST_SCHEMA_ENV)

    if not expected_schema:
        raise RuntimeError(
            f"Set {EXPECTED_TEST_SCHEMA_ENV} to the exact database schema."
        )

    connection = get_connection()

    try:
        # Verify that the connection points to the intended schema.
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            actual_schema = cursor.fetchone()[0]

        if actual_schema != expected_schema:
            raise RuntimeError(
                f"Refusing to test schema {actual_schema!r}; "
                f"expected {expected_schema!r}."
            )

        print(f"Testing database: {actual_schema}")

        # Q1: Vehicle counts by carrier.
        q1 = queries.get_vehicle_counts_by_carrier(connection)

        assert len(q1) == 3, f"Expected 3 carriers, got {len(q1)}"
        assert [row[0] for row in q1] == [1, 2, 3]
        assert all(
            all(value >= 0 for value in row[1:])
            for row in q1
        )
        assert sum(sum(row[1:]) for row in q1) == 7

        print("PASS Q1: 3 carriers and 7 total vehicles verified")

        # Q2: Departure utilization ranking.
        q2 = queries.get_departure_utilization_ranking(connection)

        assert len(q2) == 10, f"Expected 10 departures, got {len(q2)}"
        assert all(
            0 <= float(row[6]) <= 100
            for row in q2
        )

        lane_ranks = {}

        for row in q2:
            lane = (row[1], row[2])
            lane_ranks.setdefault(lane, []).append(
                (row[7], row[6])
            )

        for ranked in lane_ranks.values():
            ranks = [rank for rank, _ in ranked]

            assert ranks == sorted(ranks)
            assert ranks[0] == 1

        assert any(
            abs(float(row[6]) - 75.0) < 0.01
            for row in q2
        )

        print("PASS Q2: 10 departures and utilization rankings verified")

        # Q3: Consecutive scan time intervals for shipment 1.
        q3 = queries.get_scan_time_intervals(connection, 1)

        expected_statuses = [
            "RECEIVED",
            "IN_TRANSIT",
            "OUT_FOR_DELIVERY",
            "DELIVERED"
        ]

        assert len(q3) == 4, (
            f"Expected 4 scans for shipment 1, got {len(q3)}"
        )
        assert all(row[0] == 1 for row in q3)
        assert q3[0][4] is None
        assert q3[0][5] is None
        assert [row[2] for row in q3] == expected_statuses
        assert all(
            row[5] is not None and row[5] >= 0
            for row in q3[1:]
        )

        print("PASS Q3: 4 scans and elapsed intervals verified")

        # Q4: Cumulative delivered weight by carrier.
        q4 = queries.get_running_delivered_weight_by_carrier(connection)

        assert len(q4) == 14, (
            f"Expected 14 delivered shipments, got {len(q4)}"
        )

        totals = {}

        for row in q4:
            carrier_id = row[0]
            shipment_id = row[1]
            weight = float(row[3])
            running_total = float(row[4])

            expected_total = totals.get(carrier_id, 0.0) + weight

            assert abs(running_total - expected_total) < 0.01, (
                f"Incorrect running total for carrier {carrier_id}, "
                f"shipment {shipment_id}"
            )

            totals[carrier_id] = expected_total

        print("PASS Q4: 14 delivered shipments and running totals verified")

        # Q5: Departures with multiple distinct shippers.
        q5 = queries.get_departures_with_multiple_shippers(connection)

        assert len(q5) == 3, (
            f"Expected 3 qualifying departures, got {len(q5)}"
        )
        assert all(row[3] >= 2 for row in q5)

        print("PASS Q5: 3 departures with multiple shippers verified")

        # Q6: Shipments without scan events.
        q6 = queries.get_shipments_without_scans(connection)

        assert len(q6) == 1, (
            f"Expected 1 shipment without scans, got {len(q6)}"
        )
        assert q6[0][0] == 14

        print("PASS Q6: Shipment 14 is the only shipment without scans")

        print("\nAll six analytics integration tests passed!")

    finally:
        connection.close()


if __name__ == "__main__":
    run_tests()
