from __future__ import annotations

from flask import jsonify, redirect, request, url_for
from flask_login import current_user

from .authz_service import sanitize_next_url


_PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.logout",
    "static",
}


def register_auth_context(app) -> None:
    @app.context_processor
    def inject_auth_context():
        return {
            "auth_enabled": app.config.get("AUTH_ENABLED", False),
            "current_user": current_user if current_user.is_authenticated else None,
        }



def enforce_login_for_request(app):
    if not app.config.get("AUTH_ENABLED", False):
        return None

    if request.endpoint in _PUBLIC_ENDPOINTS or request.endpoint is None:
        return None

    if current_user.is_authenticated:
        return None

    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Authentication required."}), 401

    return redirect(url_for("auth.login", next=sanitize_next_url(request.full_path)))
