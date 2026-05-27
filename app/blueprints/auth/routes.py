from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from ...services import auth_service
from ...services.authz_service import sanitize_next_url
from .blueprint import auth_bp


@auth_bp.route("/login", methods=["GET", "POST"], endpoint="login")
def login():
    if not current_app.config.get("AUTH_ENABLED", False):
        return redirect(url_for("main.index"))

    if current_user.is_authenticated:
        next_url = sanitize_next_url(request.args.get("next"))
        return redirect(next_url or url_for("main.index"))

    error = ""
    username = ""
    display_name = ""
    next_url = sanitize_next_url(request.args.get("next"))
    stub_enabled = bool(current_app.config.get("AUTH_STUB_ENABLED", True))

    if request.method == "POST":
        username = " ".join(str(request.form.get("username") or "").split()).strip()
        display_name = " ".join(str(request.form.get("display_name") or "").split()).strip()
        password = str(request.form.get("password") or "")
        next_url = sanitize_next_url(request.form.get("next")) or next_url

        try:
            user = auth_service.authenticate_login(
                current_app.config,
                username=username,
                password=password,
                display_name=display_name or None,
            )
        except auth_service.AuthenticationError as exc:
            error = str(exc)
        else:
            login_user(user)
            flash(f"已登入 {user.display_name}", "info")
            return redirect(next_url or url_for("main.index"))

    return render_template(
        "auth/login.html",
        error=error,
        username=username,
        display_name=display_name,
        next_url=next_url or "",
        stub_enabled=stub_enabled,
    )


@auth_bp.get("/logout", endpoint="logout")
def logout():
    if current_user.is_authenticated:
        flash(
            f"已登出 {getattr(current_user, 'display_name', '') or getattr(current_user, 'work_id', '')}",
            "info",
        )
    logout_user()
    return redirect(url_for("auth.login"))
