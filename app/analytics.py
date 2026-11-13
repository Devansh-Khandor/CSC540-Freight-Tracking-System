"""Authenticated, GET-only global analytics for all three project roles."""
import pymysql
from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app.auth import ROLES
from app.db import ConfigurationError
from app import analytics_service as service

bp = Blueprint("analytics", __name__, url_prefix="/queries")


@bp.before_request
def require_login():
    if not session.get("account_id"):
        return redirect(url_for("auth.login"))
    if session.get("role") not in ROLES:
        abort(403)


@bp.errorhandler(pymysql.MySQLError)
@bp.errorhandler(ConfigurationError)
@bp.errorhandler(OSError)
def unavailable(error):
    return render_template("error.html", code=503, heading="Query service unavailable",
                           message="We could not load this report. Please try again later."), 503


@bp.get("")
def index():
    return render_template("analytics/index.html", reports=service.REPORTS)


@bp.get("/<int:number>")
def result(number):
    if not 1 <= number <= len(service.REPORTS):
        abort(404)
    report = service.REPORTS[number - 1]
    value = request.args.get("shipment_id", "")
    rows, error, status = None, None, 200
    if number != 3 or "shipment_id" in request.args:
        try:
            rows = service.execute_report(number, value)
        except service.InvalidShipmentID as exc:
            error, status = str(exc), 400
    return render_template("analytics/result.html", report=report, rows=rows,
                           error=error, value=value), status
