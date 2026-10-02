from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_mysqldb import MySQL
from config import Config
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import os
import re


mysql = MySQL()
jwt = JWTManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Do not wait until the first successful login to discover this required
    # production setting is missing.
    if not app.config.get("JWT_SECRET_KEY"):
        raise RuntimeError("JWT_SECRET_KEY must be set in revela_backend/.env")

    # Init extensions
    mysql.init_app(app)
    jwt.init_app(app)

    # Load CORS origins from environment
    cors_origins = os.getenv("CORS_ORIGINS")
    if cors_origins:
        allowed_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
    else:
        allowed_origins = [
            re.compile(r"http://localhost:\d+"),
            re.compile(r"http://127\.0\.0\.1:\d+"),
            "http://10.0.2.2:5000",
        ]

    CORS(app, resources={
        r"/api/*": {
            "origins": allowed_origins,
            "allow_headers": ["Content-Type", "Authorization"],
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "supports_credentials": True
        }
    })

    # Register blueprints
    from api.auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")

    from api.registry.routes import registry_bp
    app.register_blueprint(registry_bp, url_prefix="/api/registry")

    from api.flags.routes import flags_bp
    app.register_blueprint(flags_bp, url_prefix="/api/flags")

    from api.users.routes import users_bp
    app.register_blueprint(users_bp, url_prefix="/api/users")

    from api.inspections.routes import inspections_bp
    app.register_blueprint(inspections_bp, url_prefix="/api/inspections")

    from api.analytics.routes import analytics_bp
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")

    from api.geospatial.routes import geospatial_bp
    app.register_blueprint(geospatial_bp, url_prefix="/api/geospatial")

    from api.notifications.routes import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    # Intercept all exceptions to ensure CORS headers are preserved on 500 errors
    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return e
        # Avoid leaking database, JWT, and password-hash details in production.
        app.logger.exception("Unhandled application exception", exc_info=e)
        return jsonify({"error": "Internal Server Error"}), 500

    # ── Background scheduler ──────────────────────────────────────────────────
    # check_and_expire_old_permits is a write operation (expires stale permits,
    # updates map flags, sends admin notifications).  Running it inside every
    # read request added latency to every registry list and analytics page load.
    # Instead, schedule it to run:
    #   1. Once at startup (with a short delay to let DB connections settle).
    #   2. Daily at midnight so year-rollover is caught automatically.
    _start_permit_expiry_scheduler(app)

    return app


def _start_permit_expiry_scheduler(app):
    """Configure and start the APScheduler background job for permit expiry."""
    import atexit
    from datetime import datetime, timedelta
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    def _run_expiry_check():
        """Execute permit expiry check inside a Flask application context."""
        with app.app_context():
            try:
                from api.registry.service import check_and_expire_old_permits
                check_and_expire_old_permits()
            except Exception as exc:
                app.logger.warning(f"[Scheduler] Permit expiry check failed: {exc}")

    scheduler = BackgroundScheduler(daemon=True)

    # Daily midnight run — catches year-rollover automatically
    scheduler.add_job(
        _run_expiry_check,
        CronTrigger(hour=0, minute=0),
        id="permit_expiry_daily",
        replace_existing=True,
    )

    # One-time startup run — fires 10 s after the server is ready so DB
    # connections are fully initialised before the first query runs.
    scheduler.add_job(
        _run_expiry_check,
        "date",
        run_date=datetime.now() + timedelta(seconds=10),
        id="permit_expiry_startup",
        replace_existing=True,
    )

    def _run_places_refresh():
        """Refresh aging Google coordinates to comply with 30-day cache limits."""
        with app.app_context():
            try:
                from api.registry.places_resolver import refresh_expired_coords, purge_expired_coords
                # Automatically refresh coords older than 20 days (stays within 30-day limit)
                res = refresh_expired_coords()
                app.logger.info(f"[Scheduler] Map Pins Refresh: {res}")
                
                # Safety net: clear Google coords older than 28 days that failed to refresh
                # Default is dry_run=True, so it just logs for now.
                purge_res = purge_expired_coords(dry_run=True)
                app.logger.info(f"[Scheduler] Map Pins Purge: {purge_res}")
            except Exception as exc:
                app.logger.error(f"[Scheduler] Map Pins Refresh failed: {exc}")

    # I-schedule itong tumakbo araw-araw (e.g. tuwing 3:00 AM)
    scheduler.add_job(
        _run_places_refresh,
        CronTrigger(hour=3, minute=0),
        id="refresh_places_daily",
        replace_existing=True,
    )

    scheduler.start()
    # Ensure the scheduler stops cleanly when the process exits.
    atexit.register(lambda: scheduler.shutdown(wait=False))


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
