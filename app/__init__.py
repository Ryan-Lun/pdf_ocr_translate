from __future__ import annotations

from flask import Flask, url_for

from .blueprints import register_blueprints
from .config import CONFIG_BY_NAME, BaseConfig
from .errors import register_error_handlers
from .extensions import init_app as init_extensions
from .hooks import register_before_request
from .services import alerts, state
from .services.auth_service import init_auth
from .services.startup_validation import validate_startup_config
from .services.operations_service import register_operations_cli
from .version import APP_VERSION, APP_VERSION_LABEL



def create_app(config_name: str | None = None) -> Flask:
    config_cls = CONFIG_BY_NAME.get(config_name, BaseConfig)
    app = Flask(
        __name__,
        template_folder=str(state.BASE_DIR / "app" / "templates"),
        static_folder=str(state.BASE_DIR / "static"),
        static_url_path="/static",
    )
    app.config.from_object(config_cls)
    alerts.log_startup_warning(app.config)
    validate_startup_config(app.config)

    init_extensions(app)
    register_operations_cli(app)
    init_auth(app)
    register_blueprints(app)
    register_error_handlers(app)
    register_before_request(app)

    @app.context_processor
    def inject_app_version():
        def static_asset_url(filename: str) -> str:
            return url_for("static", filename=filename, v=APP_VERSION)

        return {
            "app_version": APP_VERSION,
            "app_version_label": APP_VERSION_LABEL,
            "static_asset_url": static_asset_url,
        }

    return app


__all__ = ["create_app"]
