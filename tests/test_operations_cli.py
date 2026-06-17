from __future__ import annotations

import contextlib
from pathlib import Path
import re

import pytest
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services import auth_store, job_store, operations_service
from app.services.operations_service import register_operations_cli

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
SCHEMA_TABLE_NAMES = (
    "jobs",
    "job_artifacts",
    "job_events",
    "editor_presence",
    "document_templates",
    "users",
    "roles",
    "user_roles",
)
RAW_SQL_TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|ALTER\s+TABLE)\s+"
    rf"(?:{'|'.join(SCHEMA_TABLE_NAMES)})\b",
    re.IGNORECASE,
)


@pytest.fixture
def ops_app(monkeypatch):
    job_store.configure_database_schema("translation")
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS translation"))
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


def test_configure_database_schema_updates_metadata_schema():
    original_schema = job_store.current_database_schema()
    try:
        schema = job_store.configure_database_schema("translation")

        assert schema == "translation"
        assert job_store.JobRecord.__table__.schema == "translation"
        assert auth_store.UserRecord.__table__.schema == "translation"
        assert job_store.qualified_table_name("jobs") == "[translation].[jobs]"
    finally:
        job_store.configure_database_schema(original_schema)


def test_ensure_database_schema_accepts_active_connection():
    original_schema = job_store.current_database_schema()
    executed: list[str] = []

    class FakeDialect:
        name = "mssql"

    class FakeConnection:
        dialect = FakeDialect()

        def execute(self, statement):
            executed.append(str(statement))

        def begin(self):
            raise AssertionError("active Alembic connections must not begin a nested transaction")

    try:
        job_store.configure_database_schema("translation")
        job_store.ensure_database_schema(FakeConnection())
    finally:
        job_store.configure_database_schema(original_schema)

    assert executed == ["IF SCHEMA_ID(N'translation') IS NULL EXEC(N'CREATE SCHEMA [translation]');"]

def test_schema_preflight_reports_current_schema(ops_app):
    runner = ops_app.test_cli_runner()
    result = runner.invoke(args=["schema-preflight"])

    assert result.exit_code == 0
    assert "schema=translation" in result.output


def test_claim_next_job_uses_configured_schema(monkeypatch):
    original_schema = job_store.current_database_schema()
    captured: dict[str, str] = {}

    class FakeDialect:
        name = "mssql"

    class FakeBind:
        dialect = FakeDialect()

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def get_bind(self):
            return FakeBind()

        def execute(self, statement, parameters):
            captured["sql"] = str(statement)
            captured["worker_id"] = parameters["worker_id"]
            return FakeResult()

    @contextlib.contextmanager
    def fake_session_scope():
        yield FakeSession()

    try:
        job_store.configure_database_schema("translation")
        monkeypatch.setattr(job_store, "session_scope", fake_session_scope)

        assert job_store.claim_next_job("worker-test") is None
    finally:
        job_store.configure_database_schema(original_schema)

    assert captured["worker_id"] == "worker-test"
    assert "[translation].[jobs]" in captured["sql"]
    assert "FROM jobs" not in captured["sql"]
    assert "UPDATE jobs" not in captured["sql"]


def test_app_raw_sql_does_not_reference_schema_tables_unqualified():
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in RAW_SQL_TABLE_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{line_no}: {match.group(0)}")

    assert offenders == []
