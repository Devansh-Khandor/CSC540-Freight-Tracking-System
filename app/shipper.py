"""Shipper pages: authorization and forms, with SQL in shipper_service."""

import pymysql
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.auth import role_required
from app.db import ConfigurationError
from app import shipper_service as service

bp = Blueprint("shipper", __name__, url_prefix="/shipper")


@bp.before_request
@role_required("SHIPPER")
def require_shipper():
    pass


@bp.errorhandler(service.ShipmentNotFound)
def not_found(error):
    return render_template("error.html", code=404, heading="Shipment not found",
                           message="This shipment is not available in your account."), 404


@bp.errorhandler(service.ValidationError)
def rejected(error):
    return render_template("error.html", code=409, heading="Shipment action unavailable",
                           message=str(error)), 409


@bp.errorhandler(pymysql.MySQLError)
@bp.errorhandler(ConfigurationError)
@bp.errorhandler(OSError)
def unavailable(error):
    # Deliberately no exception strings or submitted data in HTML/logs.
    code = error.args[0] if error.args else None
    if isinstance(error, pymysql.MySQLError) and code in (1048, 1062, 1264, 1292, 1406, 1451, 1452, 4025):
        return render_template("error.html", code=409, heading="Shipment could not be saved",
                               message="The supplied values conflict with the current database records. Refresh the shipment and check its lane, weight, and date."), 409
    return render_template("error.html", code=503, heading="Shipment service unavailable",
                           message="We could not confirm this operation. Check your shipment list before retrying a write."), 503


@bp.get("/shipments")
def index():
    return render_template("shipper/list.html", shipments=service.list_shipments(session["account_id"]))


@bp.route("/shipments/new", methods=["GET", "POST"])
def create():
    error = None
    if request.method == "POST":
        try:
            shipment_id = service.create_shipment(session["account_id"], request.form)
        except service.ValidationError as exc:
            error = str(exc)
        else:
            flash("Shipment created successfully.")
            return redirect(url_for("shipper.detail", shipment_id=shipment_id), code=303)
    return render_template("shipper/form.html", shipment=None, lanes=service.lanes(),
                           values=request.form, error=error), 400 if error else 200


@bp.get("/shipments/<int:shipment_id>")
def detail(shipment_id):
    shipment, scans = service.tracking(session["account_id"], shipment_id)
    return render_template("shipper/detail.html", shipment=shipment, scans=scans)


@bp.route("/shipments/<int:shipment_id>/edit", methods=["GET", "POST"])
def edit(shipment_id):
    owner = session["account_id"]
    shipment = service.get_shipment(owner, shipment_id)
    error = None
    if request.method == "POST":
        try:
            service.update_shipment(owner, shipment_id, request.form)
        except service.ValidationError as exc:
            error = str(exc)
        else:
            flash("Shipment updated successfully.")
            return redirect(url_for("shipper.detail", shipment_id=shipment_id), code=303)
    values = request.form if request.method == "POST" else {
        "lane": f"{shipment['origin_hub_id']}:{shipment['destination_hub_id']}",
        "weight_kg": shipment["weight_kg"], "promised_delivery_date": shipment["promised_delivery_date"]}
    return render_template("shipper/form.html", shipment=shipment, lanes=service.lanes(),
                           values=values, error=error), 400 if error else 200


@bp.route("/shipments/<int:shipment_id>/book", methods=["GET", "POST"])
def book(shipment_id):
    owner = session["account_id"]
    # Also authorizes POST before validating its submitted departure ID.
    shipment, departures = service.bookable_departures(owner, shipment_id)
    error = None
    if request.method == "POST":
        try:
            service.book_shipment(owner, shipment_id, request.form.get("departure_id", ""))
        except service.ValidationError as exc:
            error = str(exc)
        else:
            flash("Shipment booked successfully.")
            return redirect(url_for("shipper.detail", shipment_id=shipment_id), code=303)
    return render_template("shipper/book.html", shipment=shipment, departures=departures,
                           error=error), 409 if error else 200


@bp.get("/reports")
def reports():
    summary, shipments = service.reports(session["account_id"])
    return render_template("shipper/reports.html", summary=summary, shipments=shipments)
