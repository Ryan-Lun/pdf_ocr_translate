from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from flask_login import UserMixin
from ldap3 import ALL, BASE, LEVEL, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars

from ..extensions import login_manager
from .auth_hooks_service import register_auth_context


@dataclass
class AuthUser(UserMixin):
    work_id: str
    display_name: str
    role_names: tuple[str, ...] = ("editor",)
    email: str | None = None

    def get_id(self) -> str:
        return json.dumps(
            {
                "work_id": self.work_id,
                "display_name": self.display_name,
                "role_names": list(self.role_names),
                "email": self.email,
            },
            ensure_ascii=False,
        )

    @property
    def is_admin(self) -> bool:
        return "admin" in self.role_names


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LDAPSettings:
    host: str
    port: int
    use_ssl: bool
    base_dn: str
    bind_dn: str
    bind_password: str
    login_attr: str
    object_filter: str
    display_attr: str
    email_attr: str
    search_scope: Any


_SCOPE_MAP = {
    "BASE": BASE,
    "LEVEL": LEVEL,
    "SUBTREE": SUBTREE,
}


def _normalize_value(value: object, fallback: str = "") -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned or fallback


def build_stub_user(*, username: str, display_name: str | None = None) -> AuthUser:
    normalized_work_id = _normalize_value(username)
    normalized_display_name = _normalize_value(display_name, fallback=normalized_work_id)
    return AuthUser(
        work_id=normalized_work_id,
        display_name=normalized_display_name,
    )


def _build_ldap_settings(config: Any) -> LDAPSettings:
    host = _normalize_value(config.get("LDAP_HOST"))
    base_dn = _normalize_value(config.get("LDAP_BASE_DN"))
    bind_dn = _normalize_value(config.get("LDAP_BIND_DN"))
    bind_password = str(config.get("LDAP_BIND_PASSWORD") or "")
    if not host or not base_dn or not bind_dn or not bind_password:
        raise AuthenticationError("LDAP 設定不完整，請確認主機、Base DN 與 Bind 帳號。")
    search_scope = _SCOPE_MAP.get(str(config.get("LDAP_USER_SEARCH_SCOPE") or "SUBTREE").upper(), SUBTREE)
    return LDAPSettings(
        host=host,
        port=int(config.get("LDAP_PORT") or (636 if config.get("LDAP_USE_SSL") else 389)),
        use_ssl=bool(config.get("LDAP_USE_SSL", False)),
        base_dn=base_dn,
        bind_dn=bind_dn,
        bind_password=bind_password,
        login_attr=_normalize_value(config.get("LDAP_USER_LOGIN_ATTR"), fallback="sAMAccountName"),
        object_filter=_normalize_value(
            config.get("LDAP_USER_OBJECT_FILTER"),
            fallback="(&(objectClass=user)(!(objectClass=computer)))",
        ),
        display_attr=_normalize_value(config.get("LDAP_USER_DISPLAY_ATTR"), fallback="displayName"),
        email_attr=_normalize_value(config.get("LDAP_USER_EMAIL_ATTR"), fallback="mail"),
        search_scope=search_scope,
    )


def authenticate_login(
    config: Any,
    *,
    username: str,
    password: str = "",
    display_name: str | None = None,
) -> AuthUser:
    if config.get("AUTH_STUB_ENABLED", True):
        if not _normalize_value(username):
            raise AuthenticationError("請輸入工號或使用者名稱。")
        return build_stub_user(username=username, display_name=display_name)
    return authenticate_ldap_user(config, username=username, password=password)


def authenticate_ldap_user(config: Any, *, username: str, password: str) -> AuthUser:
    normalized_username = _normalize_value(username)
    if not normalized_username:
        raise AuthenticationError("請輸入工號或使用者名稱。")
    if not str(password or ""):
        raise AuthenticationError("請輸入密碼。")

    settings = _build_ldap_settings(config)
    server = Server(settings.host, port=settings.port, use_ssl=settings.use_ssl, get_info=ALL)
    search_filter = (
        f"(&{settings.object_filter}({settings.login_attr}={escape_filter_chars(normalized_username)}))"
    )
    attributes = [settings.login_attr, settings.display_attr, settings.email_attr, "cn", "name"]

    search_conn: Connection | None = None
    user_conn: Connection | None = None
    try:
        search_conn = Connection(
            server,
            user=settings.bind_dn,
            password=settings.bind_password,
            auto_bind=True,
        )
        search_conn.search(
            search_base=settings.base_dn,
            search_filter=search_filter,
            search_scope=settings.search_scope,
            attributes=attributes,
        )
        if not search_conn.entries:
            raise AuthenticationError("帳號或密碼錯誤。")

        entry = search_conn.entries[0]
        entry_data = entry.entry_attributes_as_dict
        user_dn = str(entry.entry_dn or "").strip()
        if not user_dn:
            raise AuthenticationError("帳號或密碼錯誤。")

        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)

        work_id = _normalize_value(entry_data.get(settings.login_attr), fallback=normalized_username)
        display_name = _normalize_value(
            entry_data.get(settings.display_attr)
            or entry_data.get("cn")
            or entry_data.get("name"),
            fallback=work_id,
        )
        email = _normalize_value(entry_data.get(settings.email_attr)) or None
        return AuthUser(
            work_id=work_id,
            display_name=display_name,
            email=email,
        )
    except LDAPBindError as exc:
        raise AuthenticationError("帳號或密碼錯誤。") from exc
    except LDAPException as exc:
        raise AuthenticationError(f"LDAP 驗證失敗：{exc}") from exc
    finally:
        if user_conn is not None:
            try:
                user_conn.unbind()
            except Exception:
                pass
        if search_conn is not None:
            try:
                search_conn.unbind()
            except Exception:
                pass


def register_auth_handlers() -> None:
    @login_manager.user_loader
    def load_user(raw_user: str):
        if not raw_user:
            return None
        try:
            payload = json.loads(raw_user)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        work_id = _normalize_value(payload.get("work_id"))
        display_name = _normalize_value(payload.get("display_name"), fallback=work_id)
        role_names = payload.get("role_names") or ["editor"]
        email = _normalize_value(payload.get("email")) or None
        if not work_id:
            return None
        return AuthUser(
            work_id=work_id,
            display_name=display_name,
            role_names=tuple(str(role).strip() for role in role_names if str(role).strip()) or ("editor",),
            email=email,
        )


def init_auth(app) -> None:
    login_manager.login_view = "auth.login"
    register_auth_handlers()
    register_auth_context(app)
