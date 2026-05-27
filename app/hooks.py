from __future__ import annotations

from .services.auth_hooks_service import enforce_login_for_request



def register_before_request(app) -> None:
    @app.before_request
    def _enforce_login():
        return enforce_login_for_request(app)
