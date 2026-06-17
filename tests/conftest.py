import pytest
from sqlalchemy import text

from app import create_app
from app.services import job_store, state
from sqlalchemy import delete
from tests.db_safety import configure_test_database


@pytest.fixture
def app(monkeypatch):
    engine = configure_test_database(monkeypatch)
    schema = job_store.current_database_schema()
    with engine.begin() as conn:
        for table_name in ("document_template_boxes", "document_template_pages", "document_templates"):
            conn.execute(
                text(
                    f"IF OBJECT_ID(N'{schema}.{table_name}', N'U') IS NOT NULL "
                    f"DROP TABLE {job_store.qualified_table_name(table_name, engine)};"
                )
            )
    job_store.Base.metadata.create_all(
        engine,
        tables=[
            job_store.DocumentTemplateRecord.__table__,
        ],
        checkfirst=True,
    )
    app = create_app("testing")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_document_templates(request, monkeypatch, tmp_path):
    if "app" not in request.fixturenames:
        yield
        return

    request.getfixturevalue("app")
    monkeypatch.setattr(state, "DOCUMENT_TEMPLATES_PATH", tmp_path / "document_templates.json")
    with job_store.session_scope() as session:
        session.execute(delete(job_store.EditorPresenceRecord))
        session.execute(delete(job_store.DocumentTemplateRecord))
    yield
    with job_store.session_scope() as session:
        session.execute(delete(job_store.EditorPresenceRecord))
        session.execute(delete(job_store.DocumentTemplateRecord))
