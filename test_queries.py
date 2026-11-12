
from app.db import get_connection
from app import queries

test_cases = [
    ("Query 1: Vehicle counts by carrier", queries.get_vehicle_counts_by_carrier),
    ("Query 2: Departure utilization ranking", queries.get_departure_utilization_ranking),
    ("Query 3: Scan time intervals", queries.get_scan_time_intervals),
    ("Query 4: Running delivered weight", queries.get_running_delivered_weight_by_carrier),
    ("Query 5: Departures with multiple shippers", queries.get_departures_with_multiple_shippers),
    ("Query 6: Shipments without scans", queries.get_shipments_without_scans),
]

connection = get_connection()

try:
    for title, function in test_cases:
        results = function(connection)
        print(f"\n{title}")
        print(f"Rows returned: {len(results)}")
        for row in results[:5]:
            print(row)
finally:
    connection.close()
