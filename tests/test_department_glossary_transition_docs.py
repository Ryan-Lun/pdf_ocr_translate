from __future__ import annotations

from pathlib import Path


def test_department_glossary_transition_guide_covers_operational_checklist():
    guide_path = Path("docs/system-description/22-DepartmentGlossarySQLTransition.md")
    guide = guide_path.read_text(encoding="utf-8")
    index = Path("docs/system-description/README.md").read_text(encoding="utf-8")
    env_doc = Path("系統環境說明文件.md").read_text(encoding="utf-8")

    required_fragments = [
        "Department Glossary SQL-first",
        "Glossary 與 Translation Memory 必須分開",
        "法規文管部",
        "TRANSLATION_GLOSSARY_SOURCE=sql",
        "TRANSLATION_GLOSSARY_SOURCE=json",
        "GLOSSARY_CONTEXT_ARTIFACT_ENABLED",
        "scripts/import_department_glossary.py",
        "--apply",
        "dry-run",
        "department_glossary_import",
        "glossary_hits.json",
        "department_glossary_*",
        "TM Reference 不可以覆蓋 Department Glossary",
        "rollback",
        "pyproject.toml",
        "CHANGELOG.md",
    ]
    for fragment in required_fragments:
        assert fragment in guide

    semantic_fragments = [
        "正式環境建議維持 SQL-first",
        "舊 JSON glossary data 應匯入到預設 Department Glossary：`法規文管部`",
        "dry-run 不會寫入 SQL，也不會修改 JSON 檔案",
        "確認 dry-run 結果後再 apply",
        "rollback 期間不要刪除 SQL glossary tables",
    ]
    for fragment in semantic_fragments:
        assert fragment in guide

    assert "22-DepartmentGlossarySQLTransition.md" in index
    assert "TRANSLATION_GLOSSARY_SOURCE" in env_doc
    assert "GLOSSARY_CONTEXT_ARTIFACT_ENABLED" in env_doc
