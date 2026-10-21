"""Actual application routes/CORS, with startup jobs disabled for isolated tests."""
from unittest.mock import patch


ORIGIN = "https://www.revelasys.site"


def create_http_app(cors_origins=ORIGIN, *, blueprint_only=False):
    secret = "isolated-green-link-http-secret-32-characters"
    if blueprint_only:
        # The disposable-MySQL runner deliberately forbids application startup.
        # Exercise the same views/auth/CORS policy without any startup hooks.
        from flask import Flask
        from flask_jwt_extended import JWTManager
        from api.utils import cors_config
        from api.inspections.routes import inspections_bp

        app = Flask(__name__)
        app.config.update(TESTING=True, JWT_SECRET_KEY=secret)
        JWTManager(app)
        cors_config.init_app(app, cors_origins)
        app.register_blueprint(inspections_bp, url_prefix="/api/inspections")
        return app

    import app as app_module
    from config import Config
    from api.analytics import routes as analytics

    with (
        patch.object(Config, "JWT_SECRET_KEY", secret),
        patch.dict("os.environ", {"CORS_ORIGINS": cors_origins}),
        patch.object(app_module, "_start_permit_expiry_scheduler"),
        patch.object(analytics, "start_analytics_cache_warmup"),
        patch.object(analytics, "init_analytics_cache_invalidation"),
    ):
        app = app_module.create_app()
    app.config.update(TESTING=True)
    return app
