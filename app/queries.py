
from app.db import get_connection
from app import queries


def run_tests():
    connection = get_connection()

    try:
        # Query 1: Vehicle counts by carrier
        q1 = queries.get_vehicle_counts_by_carrier(connection)
        assert len(q1) == 3, f"Expected 3 carriers, got {len(q1)}"
        print("Query 1 passed: Vehicle counts by carrier")

        # Query 2: Departure utilization ranking
        q2 = queries.get_departure_utilization_ranking(connection)
        assert len(q2) == 10, f"Expected 10 departures, got {len(q2)}"
        print("Query 2 passed: Departure utilization ranking")

        # Query 3: Scan intervals for one shipment
        q3 = queries.get_scan_time_intervals(connection, 1)
        assert len(q3) == 4, f"Expected 4 scans for shipment 1, got {len(q3)}"
        assert all(row[0] == 1 for row in q3), "Query 3 returned another shipment"
        assert q3[0][4] is None, "First scan should have no previous timestamp"
        print("Query 3 passed: Scan intervals for shipment 1")

        # Query 4: Running delivered weight
        q4 = queries.get_running_delivered_weight_by_carrier(connection)
        assert len(q4) == 10, f"Expected 10 delivered shipments, got {len(q4)}"
        print("Query 4 passed: Running delivered weight")

        # Query 5: Departures with multiple shippers
        q5 = queries.get_departures_with_multiple_shippers(connection)
        assert len(q5) == 3, f"Expected 3 qualifying departures, got {len(q5)}"
        assert all(row[3] >= 2 for row in q5), "A departure has fewer than 2 shippers"
        print("Query 5 passed: Multiple shippers")

        # Query 6: Shipments without scans
        q6 = queries.get_shipments_without_scans(connection)
        assert len(q6) == 1, f"Expected 1 shipment without scans, got {len(q6)}"
        assert q6[0][0] == 14, f"Expected shipment 14, got {q6[0][0]}"
        print("Query 6 passed: Shipments without scans")

        print("\nAll analytical query tests passed!")

    finally:
        connection.close()


if __name__ == "__main__":
    run_tests()
