"""Authenticated VIEWER pages expose GET-only database reads."""

import pymysql
from flask import Blueprint, render_template, request

from app.auth import role_required
from app.db import ConfigurationError
from app import viewer_service as service

bp = Blueprint("viewer", __name__, url_prefix="/viewer")


@bp.before_request
@role_required("VIEWER")
def require_viewer():
    pass


@bp.errorhandler(pymysql.MySQLError)
@bp.errorhandler(ConfigurationError)
@bp.errorhandler(OSError)
def unavailable(error):
    return render_template("error.html", code=503, heading="Tracking service unavailable",
                           message="Tracking and performance summaries are temporarily unavailable. Please try again later."), 503


@bp.get("")
def dashboard():
    return render_template("viewer/dashboard.html", statistics=service.statistics())


@bp.get("/track")
def track():
    value = request.args.get("shipment_id", "")
    shipment, scans, error, status = None, [], None, 200
    if "shipment_id" in request.args:
        try:
            shipment, scans = service.tracking(value)
        except service.InvalidShipmentID as exc:
            error, status = str(exc), 400
        except service.NotFound:
            error, status = "No shipment was found with that ID. Check the ID and try again.", 404
    return render_template("viewer/track.html", shipment=shipment, scans=scans,
                           value=value, error=error), status


@bp.get("/reports")
def reports():
    lanes, carriers = service.reports()
    return render_template("viewer/reports.html", lanes=lanes, carriers=carriers)
