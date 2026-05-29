from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from flask import current_app, has_app_context
from flask_login import UserMixin
from ldap3 import ALL, BASE, LEVEL, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars

from ..extensions import login_manager
from . import auth_policy, auth_store
from .auth_hooks_service import register_auth_context


@dataclass
class AuthUser(UserMixin):
    work_id: str
    display_name: str
    role_names: tuple[str, ...] = ("editor",)
    email: str | None = None
    dn: str | None = None

    def get_id(self) -> str:
        return json.dumps(
            {
                "work_id": self.work_id,
                "display_name": self.display_name,
                "role_names": list(self.role_names),
                "email": self.email,
                "dn": self.dn,
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


def _build_auth_user(
    *,
    work_id: str,
    display_name: str,
    role_names: tuple[str, ...],
    email: str | None = None,
    dn: str | None = None,
) -> AuthUser:
    return AuthUser(
        work_id=work_id,
        display_name=display_name,
        role_names=role_names or (auth_store.ROLE_EDITOR,),
        email=email,
        dn=dn,
    )


def build_stub_user(*, username: str, display_name: str | None = None) -> AuthUser:
    normalized_work_id = _normalize_value(username)
    normalized_display_name = _normalize_value(display_name, fallback=normalized_work_id)
    return _build_auth_user(
        work_id=normalized_work_id,
        display_name=normalized_display_name,
        role_names=(auth_store.ROLE_EDITOR,),
    )


def authenticate_identity(
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


def authorize_login(config: Any, auth_user: AuthUser) -> None:
    auth_policy.authorize_login(
        config,
        auth_user,
        group_gate_checker=lambda user: is_allowed_group_member(config, user),
    )


def sync_local_user(config: Any, auth_user: AuthUser) -> auth_store.LocalUserSnapshot | None:
    mode = auth_policy.get_authz_mode(config)
    if mode == auth_policy.AUTHZ_MODE_LOCAL_ALLOWLIST and not auth_store.user_exists(auth_user.work_id):
        return None
    return auth_store.sync_authenticated_user(auth_user)


def resolve_effective_roles(config: Any, auth_user: AuthUser) -> tuple[str, ...]:
    return auth_policy.resolve_effective_roles(config, auth_user)


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
    auth_user = authenticate_identity(
        config,
        username=username,
        password=password,
        display_name=display_name,
    )

    try:
        authorize_login(config, auth_user)
        snapshot = sync_local_user(config, auth_user)
        role_names = resolve_effective_roles(config, auth_user)
    except auth_store.LocalAuthorizationError as exc:
        raise AuthenticationError(str(exc)) from exc

    return _build_auth_user(
        work_id=auth_user.work_id,
        display_name=snapshot.display_name if snapshot is not None else auth_user.display_name,
        role_names=role_names,
        email=(snapshot.email if snapshot is not None else auth_user.email),
        dn=auth_user.dn,
    )


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
        return _build_auth_user(
            work_id=work_id,
            display_name=display_name,
            role_names=(auth_store.ROLE_EDITOR,),
            email=email,
            dn=user_dn,
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
        email = _normalize_value(payload.get("email")) or None
        dn = _normalize_value(payload.get("dn")) or None
        if not work_id:
            return None

        try:
            snapshot = auth_store.get_local_user_snapshot(work_id)
        except Exception:
            snapshot = None

        authz_mode = auth_policy.AUTHZ_MODE_AD_ALL_USERS
        if has_app_context():
            authz_mode = auth_policy.get_authz_mode(current_app.config)

        if snapshot is not None:
            if not snapshot.is_active:
                return None
            return _build_auth_user(
                work_id=snapshot.work_id,
                display_name=snapshot.display_name,
                role_names=snapshot.role_names or (auth_store.ROLE_EDITOR,),
                email=snapshot.email,
                dn=dn,
            )

        if authz_mode == auth_policy.AUTHZ_MODE_LOCAL_ALLOWLIST:
            return None

        return _build_auth_user(
            work_id=work_id,
            display_name=display_name,
            role_names=(auth_store.ROLE_EDITOR,),
            email=email,
            dn=dn,
        )


def init_auth(app) -> None:
    login_manager.login_view = "auth.login"
    register_auth_handlers()
    register_auth_context(app)
    if not app.config.get("TESTING") and app.config.get("AUTO_SCHEMA_MANAGEMENT", True):
        auth_store.bootstrap_auth_store(app.config)


def is_allowed_group_member(config: Any, auth_user: AuthUser) -> bool:
    if not config.get("LDAP_GROUP_GATE_ENABLED", False):
        return True
    raise auth_store.LocalAuthorizationError("尚未實作 AD 群組授權檢查。")
