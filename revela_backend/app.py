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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
