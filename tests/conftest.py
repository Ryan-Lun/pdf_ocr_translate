import pytest
from sqlalchemy import create_engine, text

from app import create_app
from app.services import job_store, state
from sqlalchemy import delete


@pytest.fixture
def app():
    engine = create_engine(state.DATABASE_URL, future=True, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("IF OBJECT_ID(N'dbo.document_template_boxes', N'U') IS NOT NULL DROP TABLE dbo.document_template_boxes;"))
        conn.execute(text("IF OBJECT_ID(N'dbo.document_template_pages', N'U') IS NOT NULL DROP TABLE dbo.document_template_pages;"))
        conn.execute(text("IF OBJECT_ID(N'dbo.document_templates', N'U') IS NOT NULL DROP TABLE dbo.document_templates;"))
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
def clean_document_templates(app, monkeypatch, tmp_path):
    monkeypatch.setattr(state, "DOCUMENT_TEMPLATES_PATH", tmp_path / "document_templates.json")
    with job_store.session_scope() as session:
        session.execute(delete(job_store.DocumentTemplateRecord))
    yield
    with job_store.session_scope() as session:
        session.execute(delete(job_store.DocumentTemplateRecord))
