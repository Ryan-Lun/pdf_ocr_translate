from __future__ import annotations

from app import create_app
from app.config import ProductionConfig
from app.services import auth_service, job_store


def test_production_config_disables_startup_schema_management():
    assert ProductionConfig.APP_ENV == "production"
    assert ProductionConfig.AUTO_SCHEMA_MANAGEMENT is False


def test_production_does_not_run_startup_schema_mutations(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(ProductionConfig, "SECRET_KEY", "production-secret-value")
        scoped.setattr(ProductionConfig, "DATABASE_URL", "mssql+pyodbc://unit-test")
        scoped.setattr(ProductionConfig, "AUTH_ENABLED", True)
        scoped.setattr(ProductionConfig, "AUTH_STUB_ENABLED", False)
        scoped.setattr(ProductionConfig, "SESSION_COOKIE_SECURE", True)
        scoped.setattr(ProductionConfig, "SESSION_COOKIE_HTTPONLY", True)
        scoped.setattr(ProductionConfig, "LDAP_HOST", "ldap.example.com")
        scoped.setattr(ProductionConfig, "LDAP_BASE_DN", "DC=example,DC=com")
        scoped.setattr(ProductionConfig, "LDAP_BIND_DN", "CN=bind,DC=example,DC=com")
        scoped.setattr(ProductionConfig, "LDAP_BIND_PASSWORD", "bind-password")
        scoped.setattr(
            ProductionConfig, "OPENAI_BASE_URL", "https://azure.example.com/openai/v1/"
        )
        scoped.setattr(ProductionConfig, "OPENAI_API_KEY", "test-key")
        scoped.setattr(ProductionConfig, "AZURE_BATCH_MODEL", "batch-prod-deployment")
        scoped.setattr(ProductionConfig, "DOC_TRANSLATE_MODEL", "doc-prod-deployment")
        scoped.setattr(
            ProductionConfig, "PDF_REALTIME_TRANSLATE_MODEL", "realtime-prod-deployment"
        )
        scoped.setattr(ProductionConfig, "WORD_TRANSLATE_MODEL", "word-prod-deployment")
        scoped.setattr(
            ProductionConfig,
            "TABLE_RECOGNTION_V2_URL",
            "https://ocr.example.com/table-recognition",
        )
        scoped.setattr(
            ProductionConfig, "PP_STRUCTURE_URL", "https://ocr.example.com/layout-parsing"
        )

        class FakeEngine:
            pass

        scoped.setattr(job_store, "create_engine", lambda *args, **kwargs: FakeEngine())
        scoped.setattr(job_store, "sessionmaker", lambda *args, **kwargs: lambda: None)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("startup schema mutation should not run in production")

        scoped.setattr(job_store.Base.metadata, "create_all", fail_if_called)
        scoped.setattr(job_store, "_ensure_compatible_columns", fail_if_called)
        scoped.setattr(job_store, "_assert_required_tables", lambda: None)
        scoped.setattr(auth_service.auth_store, "bootstrap_auth_store", fail_if_called)

        app = create_app("production")

        assert app.config["AUTO_SCHEMA_MANAGEMENT"] is False
