"""Display metadata and read-only execution for the six existing query functions."""
from dataclasses import dataclass
import re

from app import db, queries
from analytics_checks.safety import ReadOnlyConnection


@dataclass(frozen=True)
class Report:
    number: int
    title: str
    description: str
    function: str
    columns: tuple
    empty: str


REPORTS = (
    Report(1, "Vehicle counts by carrier", "Count box trucks, refrigerated vans, and rail cars for every carrier, including carriers with no vehicles.",
           "get_vehicle_counts_by_carrier", ("Carrier ID", "Box trucks", "Refrigerated vans", "Rail cars"), "No carriers are available to report."),
    Report(2, "Departure utilization rankings", "Rank departures by booked weight as a percentage of capacity within each directed lane. Equal utilization shares a rank.",
           "get_departure_utilization_ranking", ("Departure ID", "Origin hub", "Destination hub", "Departure time (ET)", "Booked weight (kg)", "Capacity (kg)", "Utilization (%)", "Lane rank"), "No departures are available to rank."),
    Report(3, "Time between consecutive scans", "Choose a shipment to see its scan sequence and elapsed minutes since each previous scan.",
           "get_scan_time_intervals", ("Shipment ID", "Sequence", "Status", "Scan time (ET)", "Previous scan time (ET)", "Elapsed minutes"), "No scans were found for this shipment ID. The shipment may not exist or may have no recorded scans."),
    Report(4, "Cumulative delivered weight by carrier", "Show each delivered shipment and the running total of delivered kilograms for its carrier, ordered by delivery time and shipment ID.",
           "get_running_delivered_weight_by_carrier", ("Carrier ID", "Shipment ID", "Delivered at (ET)", "Delivered weight (kg)", "Cumulative weight (kg)"), "No delivered shipments are available to report."),
    Report(5, "Departures serving multiple shippers", "Find departures carrying shipments from at least two distinct shippers.",
           "get_departures_with_multiple_shippers", ("Departure ID", "Origin hub", "Destination hub", "Distinct shippers"), "No departures carry shipments from two or more shippers."),
    Report(6, "Shipments without scans", "List shipments with no scan events, including their owning shipper, route, weight, and promised delivery date.",
           "get_shipments_without_scans", ("Shipment ID", "Shipper ID", "Origin hub", "Destination hub", "Weight (kg)", "Promised delivery date"), "No shipments without scans were found."),
)


class InvalidShipmentID(ValueError):
    pass


def parse_shipment_id(value):
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,10}", value) or not 1 <= int(value) <= 4294967295:
        raise InvalidShipmentID("Enter a shipment ID from 1 to 4294967295.")
    return int(value)


def execute_report(number, shipment_id=None):
    if type(number) is not int or not 1 <= number <= len(REPORTS):
        raise ValueError("Unknown report")
    report = REPORTS[number - 1]
    args = (parse_shipment_id(shipment_id),) if number == 3 else ()
    connection = db.get_connection()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        finally:
            cursor.close()
        # Reuse the analytics runner's SELECT-only adapter and the original SQL.
        return getattr(queries, report.function)(ReadOnlyConnection(connection), *args)
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()
