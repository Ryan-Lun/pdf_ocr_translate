from __future__ import annotations

import click
from flask import current_app
from sqlalchemy import func, select

from . import auth_store, job_store
from .schema_control import missing_columns, missing_schema_groups, required_schema_groups


def run_schema_preflight(app) -> dict[str, object]:
    with app.app_context():
        groups = required_schema_groups(app)
        missing_tables = missing_schema_groups(app, groups)
        missing_table_columns = missing_columns(groups)
        return {
            "ok": not missing_tables and not missing_table_columns,
            "groups": groups,
            "missing": missing_tables,
            "missing_columns": missing_table_columns,
        }


def run_seed_bootstrap(app, *, include_auth: bool | None = None) -> dict[str, object]:
    with app.app_context():
        if include_auth is None:
            include_auth = bool(app.config.get("AUTH_ENABLED", False))
        requested_groups: dict[str, tuple[str, ...]] = {}
        if include_auth:
            requested_groups["auth"] = required_schema_groups(app).get("auth", ())
        missing = missing_schema_groups(app, requested_groups)
        if missing:
            raise click.ClickException(
                "Missing required tables for seed bootstrap: "
                + ", ".join(f"{group}=[{', '.join(tables)}]" for group, tables in sorted(missing.items()))
            )

        result: dict[str, object] = {"auth_enabled": bool(include_auth)}
        if include_auth:
            auth_store.seed_roles()
            auth_store.bootstrap_admins(app.config)
            with job_store.session_scope() as session:
                result["role_count"] = int(session.scalar(select(func.count()).select_from(auth_store.RoleRecord)) or 0)
            result["admin_count"] = auth_store.count_users_with_role(auth_store.ROLE_ADMIN)
        return result


def register_operations_cli(app) -> None:
    @app.cli.command("schema-preflight")
    def schema_preflight_command() -> None:
        result = run_schema_preflight(current_app._get_current_object())
        if not result["ok"]:
            parts: list[str] = []
            missing_tables = result["missing"]
            if missing_tables:
                parts.append(
                    "tables="
                    + " ".join(
                        f"{group}=[{', '.join(tables)}]" for group, tables in sorted(missing_tables.items())  # type: ignore[arg-type]
                    )
                )
            missing_table_columns = result["missing_columns"]
            if missing_table_columns:
                parts.append(
                    "columns="
                    + " ".join(
                        f"{table}=[{', '.join(columns)}]"
                        for table, columns in sorted(missing_table_columns.items())  # type: ignore[arg-type]
                    )
                )
            raise click.ClickException("Missing required schema: " + "; ".join(parts))
        click.echo(
            "schema_preflight "
            f"ok=1 groups={len(result['groups'])} "
            f"auto_schema_management={'1' if current_app.config.get('AUTO_SCHEMA_MANAGEMENT') else '0'}"
        )

    @app.cli.command("seed-bootstrap")
    @click.option("--skip-auth", is_flag=True, help="Skip auth role/admin bootstrap.")
    def seed_bootstrap_command(skip_auth: bool) -> None:
        result = run_seed_bootstrap(
            current_app._get_current_object(),
            include_auth=False if skip_auth else None,
        )
        click.echo(
            "seed_bootstrap "
            f"auth={'1' if result['auth_enabled'] else '0'} "
            f"roles={result.get('role_count', 0)} "
            f"admins={result.get('admin_count', 0)}"
        )
