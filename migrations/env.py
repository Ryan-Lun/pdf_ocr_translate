from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import BaseConfig, CONFIG_BY_NAME
from app.services import auth_store, job_store  # noqa: F401
from app.services.state import normalize_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = job_store.Base.metadata


def _resolve_config_class():
    config_name = (
        os.environ.get("ALEMBIC_CONFIG_NAME")
        or os.environ.get("APP_ENV")
        or os.environ.get("FLASK_ENV")
        or "default"
    )
    return CONFIG_BY_NAME.get(str(config_name).lower(), BaseConfig)


def _database_url() -> str:
    config_cls = _resolve_config_class()
    database_url = normalize_database_url(os.environ.get("ALEMBIC_DATABASE_URL") or getattr(config_cls, "DATABASE_URL", ""))
    if not database_url:
        raise RuntimeError("Database URL is required for Alembic. Set ALEMBIC_DATABASE_URL or DATABASE_URL.")
    config.set_main_option("sqlalchemy.url", str(database_url))
    return str(database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
