from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...services import audit_service, auth_policy, auth_service, auth_store, authz_service
from .blueprint import admin_bp


ROLE_CHOICES = (auth_store.ROLE_EDITOR, auth_store.ROLE_ADMIN)
LOGS_PER_PAGE = 10


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_active(value: object, *, default: bool = True) -> bool:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return default
    return cleaned in {"1", "true", "yes", "on"}


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_short_job_id(value: object) -> str:
    cleaned = _normalize_text(value)
    return cleaned[:8] if cleaned else "-"


def _parse_page() -> int:
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1


def _format_detail(value: object) -> str:
    if not value:
        return "-"
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(value)


def _format_detail_summary(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return _normalize_text(value) or "-"
    items = []
    for key, item_value in value.items():
        if str(key).startswith("_"):
            continue
        if item_value in (None, ""):
            continue
        if isinstance(item_value, (dict, list)):
            display_value = json.dumps(item_value, ensure_ascii=False, default=str)
        else:
            display_value = str(item_value)
        items.append(f"{key}: {display_value}")
        if len(items) >= 3:
            break
    if items:
        return " · ".join(items)
    return f"{len(value)} 個欄位"


def _require_admin() -> None:
    if not authz_service.user_is_admin(current_user):
        abort(403)


def _is_last_active_admin(work_id: str) -> bool:
    entry = auth_store.get_local_user_admin_entry(work_id)
    if entry is None:
        return False
    if entry.role_name != auth_store.ROLE_ADMIN or not entry.is_active:
        return False
    return auth_store.count_users_with_role(auth_store.ROLE_ADMIN) <= 1


@admin_bp.before_request
def enforce_admin_access() -> None:
    _require_admin()


@admin_bp.get("/users", endpoint="users")
def users():
    query = _normalize_text(request.args.get("q"))
    users = auth_store.list_local_users(query)
    departments = auth_service.lookup_ldap_departments(
        current_app.config,
        [user.work_id for user in users],
    )
    return render_template(
        "admin/users.html",
        users=users,
        ldap_departments=departments,
        query=query,
        role_choices=ROLE_CHOICES,
        format_dt=_format_dt,
    )


@admin_bp.route("/users/create", methods=["GET", "POST"], endpoint="create_user")
def create_user():
    if auth_policy.get_authz_mode(current_app.config) == auth_policy.AUTHZ_MODE_AD_ALL_USERS:
        flash("ad_all_users 模式下不需要手動新增使用者；請讓使用者先完成一次 AD 登入。", "info")
        return redirect(url_for("admin.users"))

    form = {
        "work_id": "",
        "display_name": "",
        "email": "",
        "role_name": auth_store.ROLE_EDITOR,
        "is_active": True,
    }

    if request.method == "POST":
        form["work_id"] = _normalize_text(request.form.get("work_id"))
        form["display_name"] = _normalize_text(request.form.get("display_name"))
        form["email"] = _normalize_text(request.form.get("email"))
        form["role_name"] = _normalize_text(request.form.get("role_name")).lower() or auth_store.ROLE_EDITOR
        form["is_active"] = _parse_active(request.form.get("is_active"), default=False)
        current_work_id = authz_service.current_work_id(current_user)
        existing_entry = auth_store.get_local_user_admin_entry(form["work_id"])

        if not form["work_id"]:
            flash("請輸入工號。", "error")
        elif form["role_name"] not in ROLE_CHOICES:
            flash("角色設定無效。", "error")
        elif existing_entry is not None and not form["is_active"] and current_work_id == existing_entry.work_id:
            flash("不能停用自己的帳號。", "error")
        elif existing_entry is not None and not form["is_active"] and _is_last_active_admin(existing_entry.work_id):
            flash("不能停用最後一個 admin。", "error")
        elif (
            existing_entry is not None
            and existing_entry.role_name == auth_store.ROLE_ADMIN
            and form["role_name"] != auth_store.ROLE_ADMIN
            and _is_last_active_admin(existing_entry.work_id)
        ):
            flash("不能移除最後一個 admin。", "error")
        else:
            snapshot = auth_store.upsert_local_user(
                work_id=form["work_id"],
                display_name=form["display_name"] or None,
                email=form["email"] or None,
                active=form["is_active"],
            )
            auth_store.update_user_role(snapshot.work_id, form["role_name"])
            audit_service.record_audit(
                "user_admin_save",
                detail={
                    "work_id": snapshot.work_id,
                    "display_name": snapshot.display_name,
                    "email": snapshot.email,
                    "role": form["role_name"],
                    "active": form["is_active"],
                    "mode": "update" if existing_entry is not None else "create",
                },
            )
            flash(f"已儲存使用者 {snapshot.work_id}。", "info")
            return redirect(url_for("admin.users"))

    return render_template(
        "admin/user_form.html",
        form=form,
        role_choices=ROLE_CHOICES,
    )


@admin_bp.post("/users/<work_id>/active", endpoint="update_user_active")
def update_user_active(work_id: str):
    target_work_id = _normalize_text(work_id)
    target_entry = auth_store.get_local_user_admin_entry(target_work_id)
    if target_entry is None:
        abort(404)

    requested_active = _parse_active(request.form.get("active"), default=target_entry.is_active)
    current_work_id = authz_service.current_work_id(current_user)

    if not requested_active and current_work_id == target_work_id:
        flash("不能停用自己的帳號。", "error")
        return redirect(url_for("admin.users"))

    if not requested_active and _is_last_active_admin(target_work_id):
        flash("不能停用最後一個 admin。", "error")
        return redirect(url_for("admin.users"))

    auth_store.update_user_active(target_work_id, requested_active)
    audit_service.record_audit(
        "user_admin_active_update",
        detail={
            "work_id": target_work_id,
            "active": requested_active,
            "previous_active": target_entry.is_active,
        },
    )
    flash(
        f"已將 {target_work_id} 設為{'啟用' if requested_active else '停用'}。",
        "info",
    )
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<work_id>/role", endpoint="update_user_role")
def update_user_role(work_id: str):
    target_work_id = _normalize_text(work_id)
    target_entry = auth_store.get_local_user_admin_entry(target_work_id)
    if target_entry is None:
        abort(404)

    requested_role = _normalize_text(request.form.get("role_name")).lower()
    if requested_role not in ROLE_CHOICES:
        flash("角色設定無效。", "error")
        return redirect(url_for("admin.users"))

    if target_entry.role_name == auth_store.ROLE_ADMIN and requested_role != auth_store.ROLE_ADMIN:
        if _is_last_active_admin(target_work_id):
            flash("不能移除最後一個 admin。", "error")
            return redirect(url_for("admin.users"))

    auth_store.update_user_role(target_work_id, requested_role)
    audit_service.record_audit(
        "user_admin_role_update",
        detail={
            "work_id": target_work_id,
            "role": requested_role,
            "previous_role": target_entry.role_name,
        },
    )
    flash(f"已將 {target_work_id} 角色更新為 {requested_role}。", "info")
    return redirect(url_for("admin.users"))


@admin_bp.get("/audit-logs", endpoint="audit_logs")
def audit_logs():
    q = _normalize_text(request.args.get("q"))
    action = _normalize_text(request.args.get("action"))
    job_id = _normalize_text(request.args.get("job_id"))
    start_date = _normalize_text(request.args.get("start_date"))
    end_date = _normalize_text(request.args.get("end_date"))
    entries, pagination = audit_service.list_audit_logs(
        page=_parse_page(),
        per_page=LOGS_PER_PAGE,
        q=q,
        action=action,
        job_id=job_id,
        start_date=start_date,
        end_date=end_date,
    )
    return render_template(
        "admin/audit_logs.html",
        entries=entries,
        pagination=pagination,
        q=q,
        action=action,
        job_id=job_id,
        start_date=start_date,
        end_date=end_date,
        format_dt=_format_dt,
        format_short_job_id=_format_short_job_id,
        format_detail=_format_detail,
        format_detail_summary=_format_detail_summary,
    )


@admin_bp.get("/system-error-logs", endpoint="system_error_logs")
def system_error_logs():
    q = _normalize_text(request.args.get("q"))
    component = _normalize_text(request.args.get("component"))
    level = _normalize_text(request.args.get("level")).upper()
    job_id = _normalize_text(request.args.get("job_id"))
    start_date = _normalize_text(request.args.get("start_date"))
    end_date = _normalize_text(request.args.get("end_date"))
    entries, pagination = audit_service.list_system_error_logs(
        page=_parse_page(),
        per_page=LOGS_PER_PAGE,
        q=q,
        component=component,
        level=level,
        job_id=job_id,
        start_date=start_date,
        end_date=end_date,
    )
    return render_template(
        "admin/system_error_logs.html",
        entries=entries,
        pagination=pagination,
        q=q,
        component=component,
        level=level,
        job_id=job_id,
        start_date=start_date,
        end_date=end_date,
        format_dt=_format_dt,
        format_short_job_id=_format_short_job_id,
        format_detail=_format_detail,
    )
