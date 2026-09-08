from __future__ import annotations

import json
from pathlib import Path

from app.services import glossary, job_store


def _clear_department_glossary_with_audit() -> None:
    with job_store.session_scope() as session:
        session.query(job_store.GlossaryAuditEventRecord).delete()
        session.query(job_store.DepartmentGlossaryEntryRecord).delete()
        session.query(job_store.DepartmentGlossaryLibraryRecord).delete()


def test_glossary_library_lifecycle_records_append_only_audit_events(client):
    _clear_department_glossary_with_audit()

    library = glossary.create_department_glossary_library(
        name="品保部",
        department_code="QA",
        actor_work_id="NE025",
    )
    updated = glossary.update_department_glossary_library(
        library.library_id,
        name="品質保證部",
        department_code="QAD",
        actor_work_id="NE026",
    )
    disabled = glossary.disable_department_glossary_library(
        library.library_id,
        actor_work_id="NE027",
    )
    activated = glossary.activate_department_glossary_library(
        library.library_id,
        actor_work_id="NE028",
    )

    events = glossary.list_glossary_audit_events(target_type="library", target_id=library.library_id)

    assert [event["action"] for event in events] == ["activate", "disable", "update", "create"]
    assert [event["actor_work_id"] for event in events] == ["NE028", "NE027", "NE026", "NE025"]
    assert [event["target_type"] for event in events] == ["library"] * 4
    assert [event["target_id"] for event in events] == [library.library_id] * 4
    create_event = events[-1]
    assert create_event["before"] is None
    assert create_event["after"] == {
        "id": library.library_id,
        "code": library.code,
        "name": "品保部",
        "department_code": "QA",
        "is_default": False,
        "is_active": True,
    }
    update_event = events[-2]
    assert update_event["before"]["name"] == "品保部"
    assert update_event["after"]["name"] == updated.name
    assert "updated_at" not in update_event["before"]
    assert disabled.is_active is False
    assert activated.is_active is True


def test_glossary_entry_lifecycle_records_append_only_audit_events(client):
    _clear_department_glossary_with_audit()
    library = glossary.create_department_glossary_library(
        name="品保部",
        department_code="QA",
        actor_work_id="NE025",
    )

    entry_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
        created_by_work_id="CLI01",
    )
    entry = glossary.update_department_glossary_entry(
        entry_id,
        library_id=library.library_id,
        source_term="外觀",
        target_term="Appearance Updated",
        updated_by_work_id="CLI02",
    )
    glossary.disable_department_glossary_entry(entry_id, updated_by_work_id="CLI03")

    events = glossary.list_glossary_audit_events(target_type="entry", target_id=entry_id)

    assert [event["action"] for event in events] == ["disable", "update", "create"]
    assert [event["actor_work_id"] for event in events] == ["CLI03", "CLI02", "CLI01"]
    assert events[-1]["before"] is None
    assert events[-1]["after"]["source_term"] == "外觀"
    assert events[-2]["before"]["target_term"] == "Appearance"
    assert events[-2]["after"]["target_term"] == entry.target_term
    assert events[0]["before"]["status"] == glossary.STATUS_ACTIVE
    assert events[0]["after"]["status"] == glossary.STATUS_DISABLED
    assert "created_at" not in events[0]["after"]


def test_glossary_import_records_create_update_and_disable_events(client):
    _clear_department_glossary_with_audit()
    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    existing_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )
    removed_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="尺寸",
        target_term="Dimension",
    )

    glossary.sync_department_glossary_items(
        library.library_id,
        [{"cn": "外觀", "en": "Appearance Updated"}, {"cn": "製程規範", "en": "Process Specification"}],
        replace=True,
        updated_by_work_id="IMPORT01",
    )

    events = glossary.list_glossary_audit_events(actor_work_id="IMPORT01")
    actions_by_target = {(event["target_id"], event["action"]) for event in events}

    assert (existing_id, "update") in actions_by_target
    assert (removed_id, "disable") in actions_by_target
    assert any(event["action"] == "create" and event["after"]["source_term"] == "製程規範" for event in events)


def test_glossary_management_api_records_logged_in_actor_for_ui_changes(client, monkeypatch):
    _clear_department_glossary_with_audit()
    client.application.config["AUTH_ENABLED"] = True
    client.application.config["AUTH_STUB_ENABLED"] = True
    client.post("/auth/login", data={"username": "ADMIN01", "display_name": "Admin One"})
    monkeypatch.setattr("app.blueprints.api.glossary_routes.authz_service.user_is_admin", lambda _user: True)

    create_library = client.post(
        "/api/glossary/libraries",
        json={"name": "品保部", "department_code": "QA"},
    )
    library_id = create_library.get_json()["library"]["id"]
    client.patch(
        f"/api/glossary/libraries/{library_id}",
        json={"name": "品質保證部", "department_code": "QAD"},
    )
    create_entry = client.post(
        f"/api/glossary/libraries/{library_id}/entries",
        json={"cn": "外觀", "en": "Appearance"},
    )
    entry_id = create_entry.get_json()["entry"]["id"]
    client.patch(
        f"/api/glossary/libraries/{library_id}/entries/{entry_id}",
        json={"cn": "外觀", "en": "Appearance Updated"},
    )
    client.post(f"/api/glossary/libraries/{library_id}/entries/{entry_id}/disable")
    client.post(f"/api/glossary/libraries/{library_id}/disable")
    client.post(f"/api/glossary/libraries/{library_id}/activate")

    events = glossary.list_glossary_audit_events(actor_work_id="ADMIN01")

    assert {event["action"] for event in events} >= {"create", "update", "disable", "activate"}
    assert any(event["target_type"] == "library" and event["action"] == "activate" for event in events)
    assert any(event["target_type"] == "entry" and event["action"] == "disable" for event in events)


def test_glossary_import_apply_api_records_logged_in_actor(client, monkeypatch):
    _clear_department_glossary_with_audit()
    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )
    client.application.config["AUTH_ENABLED"] = True
    client.application.config["AUTH_STUB_ENABLED"] = True
    client.post("/auth/login", data={"username": "IMPORT01", "display_name": "Import Admin"})
    monkeypatch.setattr("app.blueprints.api.glossary_routes.authz_service.user_is_admin", lambda _user: True)

    resp = client.post(
        "/api/glossary/system-import-apply",
        json={
            "library_id": library.library_id,
            "items": [
                {"cn": "外觀", "en": "Appearance Updated"},
                {"cn": "製程規範", "en": "Process Specification"},
            ],
            "duplicates": [],
            "invalid_rows": [],
        },
    )

    assert resp.status_code == 200
    events = glossary.list_glossary_audit_events(actor_work_id="IMPORT01")
    assert any(event["action"] == "update" and event["before"]["target_term"] == "Appearance" for event in events)
    assert any(event["action"] == "create" and event["after"]["source_term"] == "製程規範" for event in events)


def test_glossary_audit_actor_defaults_to_system_and_migration_references_model(client):
    _clear_department_glossary_with_audit()

    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")

    events = glossary.list_glossary_audit_events(target_type="library", target_id=library.library_id)
    migration = Path("migrations/versions/0006_add_glossary_audit_events.py").read_text(encoding="utf-8")

    assert events[0]["actor_work_id"] == "system"
    assert "glossary_audit_events" in job_store.REQUIRED_TABLES
    assert "GlossaryAuditEventRecord.__table__" in migration
    assert "before_json" in migration
    assert "after_json" in migration


def test_get_or_create_department_glossary_library_records_system_audit_events(client):
    _clear_department_glossary_with_audit()

    library = glossary.get_or_create_department_glossary_library(
        code="qa",
        name="品保部",
        department_code="QA",
    )
    glossary.get_or_create_department_glossary_library(
        code="qa",
        name="品質保證部",
        department_code="QAD",
    )

    events = glossary.list_glossary_audit_events(target_type="library", target_id=library.library_id)

    assert [event["action"] for event in events] == ["update", "create"]
    assert [event["actor_work_id"] for event in events] == ["system", "system"]
    assert events[-1]["before"] is None
    assert events[0]["before"]["name"] == "品保部"
    assert events[0]["after"]["name"] == "品質保證部"

