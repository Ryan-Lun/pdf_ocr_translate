from __future__ import annotations

from flask import Flask

from .blueprints import register_blueprints
from .config import CONFIG_BY_NAME, BaseConfig
from .errors import register_error_handlers
from .extensions import init_app as init_extensions
from .hooks import register_before_request
from .services import state


def create_app(config_name: str | None = None) -> Flask:
    config_cls = CONFIG_BY_NAME.get(config_name, BaseConfig)
    app = Flask(
        __name__,
        template_folder=str(state.BASE_DIR / "app" / "templates"),
        static_folder=str(state.BASE_DIR / "static"),
        static_url_path="/static",
    )
    app.config.from_object(config_cls)

    init_extensions(app)
    register_blueprints(app)
    register_error_handlers(app)
    register_before_request(app)

    return app


__all__ = ["create_app"]
