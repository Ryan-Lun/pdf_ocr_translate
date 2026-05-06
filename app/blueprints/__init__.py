from __future__ import annotations

from .api import api_bp
from .editor import editor_bp
from .jobs import jobs_bp
from .main import main_bp


def register_blueprints(app) -> None:
    app.register_blueprint(main_bp)
    app.register_blueprint(editor_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(jobs_bp)
