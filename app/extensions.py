from __future__ import annotations

from flask_login import LoginManager

from .logging_config import configure_app_logging
from .services import (
    audit_service,
    document_templates,
    job_store,
    startup_warmup,
    translation_memory,
)

login_manager = LoginManager()


def init_app(app) -> None:
    configure_app_logging(app, role="web")
    login_manager.init_app(app)
    job_store.init_app(app)
    audit_service.register_audit_cli(app)
    document_templates.register_template_cli(app)
    translation_memory.register_translation_memory_cli(app)
    startup_warmup.init_startup_warmup()
