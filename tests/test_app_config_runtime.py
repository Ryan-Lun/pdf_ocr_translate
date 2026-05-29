from __future__ import annotations

from app import create_app
from app.config import ProductionConfig
from app.services import auth_service, job_store


def test_production_config_disables_startup_schema_management():
    assert ProductionConfig.APP_ENV == "production"
    assert ProductionConfig.AUTO_SCHEMA_MANAGEMENT is False


def test_production_does_not_run_startup_schema_mutations(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(ProductionConfig, "DATABASE_URL", "mssql+pyodbc://unit-test")
        scoped.setattr(ProductionConfig, "AUTH_ENABLED", True)

        class FakeEngine:
            pass

        scoped.setattr(job_store, "create_engine", lambda *args, **kwargs: FakeEngine())
        scoped.setattr(job_store, "sessionmaker", lambda *args, **kwargs: lambda: None)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("startup schema mutation should not run in production")

        scoped.setattr(job_store.Base.metadata, "create_all", fail_if_called)
        scoped.setattr(job_store, "_ensure_compatible_columns", fail_if_called)
        scoped.setattr(auth_service.auth_store, "bootstrap_auth_store", fail_if_called)

        app = create_app("production")

        assert app.config["AUTO_SCHEMA_MANAGEMENT"] is False
