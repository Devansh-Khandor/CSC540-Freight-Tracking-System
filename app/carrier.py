"""Carrier forms and navigation; business rules and SQL live in carrier_service."""

import pymysql
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import role_required
from app.db import ConfigurationError
from app import carrier_service as service

bp = Blueprint("carrier", __name__, url_prefix="/carrier")


@bp.before_request
@role_required("CARRIER")
def require_carrier():
    pass


@bp.errorhandler(service.NotFound)
def not_found(error):
    return render_template("error.html", code=404, heading="Record not found",
                           message="This record is not available in your carrier account."), 404


@bp.errorhandler(service.ValidationError)
def rejected(error):
    return render_template("error.html", code=409, heading="Carrier action unavailable", message=str(error)), 409


@bp.errorhandler(pymysql.MySQLError)
@bp.errorhandler(ConfigurationError)
@bp.errorhandler(OSError)
def unavailable(error):
    code = error.args[0] if error.args else None
    if isinstance(error, pymysql.MySQLError) and code in (1048, 1062, 1264, 1292, 1406, 1451, 1452, 1644, 4025):
        return render_template("error.html", code=409, heading="Carrier action rejected",
                               message="The operation conflicts with current records. For scans, check the latest history, status order, timestamp, and hub before trying again."), 409
    return render_template("error.html", code=503, heading="Carrier service unavailable",
                           message="We could not confirm this operation. Check the vehicle, departure, or scan history before retrying a write."), 503


@bp.get("")
def dashboard():
    return render_template("carrier/dashboard.html", **service.dashboard(session["account_id"]))


@bp.get("/vehicles")
def vehicles():
    return render_template("carrier/vehicles.html", vehicles=service.list_vehicles(session["account_id"]))


@bp.route("/vehicles/new", methods=["GET", "POST"])
@bp.route("/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
def vehicle_form(vehicle_id=None):
    owner = session["account_id"]
    vehicle = service.get_vehicle(owner, vehicle_id) if vehicle_id is not None else None
    error = None
    if request.method == "POST":
        try:
            if vehicle is None:
                service.create_vehicle(owner, request.form)
            else:
                service.update_vehicle(owner, vehicle_id, request.form)
        except service.ValidationError as exc:
            error = str(exc)
        else:
            flash("Vehicle saved successfully.")
            return redirect(url_for("carrier.vehicles"), code=303)
    values = request.form if request.method == "POST" else (vehicle or {})
    return render_template("carrier/vehicle_form.html", vehicle=vehicle, values=values,
                           hubs=service.hubs(), subtypes=service.SUBTYPES, error=error), 400 if error else 200


@bp.get("/departures")
def departures():
    return render_template("carrier/departures.html", departures=service.list_departures(session["account_id"]))


@bp.route("/departures/new", methods=["GET", "POST"])
@bp.route("/departures/<int:departure_id>/edit", methods=["GET", "POST"])
def departure_form(departure_id=None):
    owner = session["account_id"]
    departure = service.get_departure(owner, departure_id) if departure_id is not None else None
    error = None
    if request.method == "POST":
        try:
            if departure is None:
                service.create_departure(owner, request.form)
            else:
                service.update_departure(owner, departure_id, request.form)
        except service.ValidationError as exc:
            error = str(exc)
        else:
            flash("Departure saved successfully.")
            return redirect(url_for("carrier.departures"), code=303)
    values = dict(request.form) if request.method == "POST" else dict(departure or {})
    if departure and (request.method == "GET" or departure["booking_count"]):
        values.update(vehicle_id=departure["vehicle_id"],
                      lane=f"{departure['origin_hub_id']}:{departure['destination_hub_id']}",
                      departure_datetime=departure["departure_datetime"].isoformat(timespec="seconds"))
    return render_template("carrier/departure_form.html", departure=departure, values=values,
                           vehicles=service.list_vehicles(owner), lanes=service.lanes(), error=error), 400 if error else 200


@bp.get("/shipments")
def shipments():
    return render_template("carrier/shipments.html", shipments=service.assigned_shipments(session["account_id"]))


@bp.route("/shipments/<int:shipment_id>/scans", methods=["GET", "POST"])
def scans(shipment_id):
    owner = session["account_id"]
    shipment, history = service.tracking(owner, shipment_id)
    error = None
    if request.method == "POST":
        try:
            service.post_scan(owner, shipment_id, request.form)
        except service.ValidationError as exc:
            error = str(exc)
        else:
            flash("Scan recorded successfully.")
            return redirect(url_for("carrier.scans", shipment_id=shipment_id), code=303)
    return render_template("carrier/scans.html", shipment=shipment, history=history,
                           hubs=service.hubs(), statuses=service.STATUSES, values=request.form,
                           error=error), 400 if error else 200


@bp.get("/reports")
def reports():
    summary, departures = service.reports(session["account_id"])
    return render_template("carrier/reports.html", summary=summary, departures=departures)
