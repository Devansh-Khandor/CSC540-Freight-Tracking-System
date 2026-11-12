"""Flask application; run with flask --app app.web:create_app run."""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template

from app import db
from app.auth import init_auth
from app.shipper import bp as shipper_bp
from app.carrier import bp as carrier_bp
from app.viewer import bp as viewer_bp


def database_available():
    """Probe connectivity without reading application data or returning details."""
    try:
        with db.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
                return row == (1,)
    except Exception:
        # This diagnostic intentionally suppresses driver/configuration details,
        # including errors during cursor or connection cleanup.
        return False


def create_app(test_config=None):
    """Create the web app without opening a database connection."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env",
                override=False, interpolate=False)
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or None,
        DEBUG=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=os.environ.get("APP_ENV", "development") == "production",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config is not None:
        app.config.update(test_config)

    init_auth(app)
    app.register_blueprint(shipper_bp)
    app.register_blueprint(carrier_bp)
    app.register_blueprint(viewer_bp)

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, heading="Request could not be verified",
                               message="Reload the form and try again."), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", code=403, heading="Access denied",
                               message="Your account cannot access this dashboard."), 403

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.get("/status")
    def status():
        connected = database_available()
        return (render_template("status.html", connected=connected),
                200 if connected else 503,
                {"Cache-Control": "no-store"})

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404,
                               heading="Page not found",
                               message="This page is not available. Return home to explore the project."), 404

    @app.errorhandler(500)
    def server_error(error):
        return render_template("error.html", code=500,
                               heading="Something went wrong",
                               message="We could not load this page. Please try again later."), 500

    return app
