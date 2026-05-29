from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import job_store, operations_service
from app.services.operations_service import register_operations_cli


@pytest.fixture
def ops_app(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    job_store.Base.metadata.create_all(bind=engine, checkfirst=True)
    monkeypatch.setattr(job_store, "_engine", engine)
    monkeypatch.setattr(
        job_store,
        "_session_factory",
        sessionmaker(bind=engine, future=True, expire_on_commit=False),
    )

    app = Flask(__name__)
    app.config.update(
        AUTH_ENABLED=True,
        AUTO_SCHEMA_MANAGEMENT=False,
        BOOTSTRAP_ADMIN="admin1",
    )
    register_operations_cli(app)
    return app


def test_schema_preflight_fails_when_required_tables_missing(ops_app, monkeypatch):
    monkeypatch.setattr(
        operations_service,
        "required_schema_groups",
        lambda _app: {"ops": ("__missing_table__",)},
    )

    runner = ops_app.test_cli_runner()
    result = runner.invoke(args=["schema-preflight"])

    assert result.exit_code != 0
    assert "__missing_table__" in result.output


def test_seed_bootstrap_can_skip_auth(ops_app):
    runner = ops_app.test_cli_runner()
    result = runner.invoke(args=["seed-bootstrap", "--skip-auth"])

    assert result.exit_code == 0
    assert "auth=0" in result.output


def test_seed_bootstrap_populates_auth_defaults(ops_app):
    runner = ops_app.test_cli_runner()
    result = runner.invoke(args=["seed-bootstrap"])

    assert result.exit_code == 0
    assert "auth=1" in result.output
    assert "roles=2" in result.output
    assert "admins=1" in result.output
