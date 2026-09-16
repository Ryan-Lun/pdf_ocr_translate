from __future__ import annotations

from pathlib import Path


def test_typed_glossary_validation_guide_is_indexed_and_complete():
    guide_path = Path("docs/system-description/25-TypedGlossaryValidation操作與Release指引.md")
    guide = guide_path.read_text(encoding="utf-8")
    index = Path("docs/system-description/README.md").read_text(encoding="utf-8")

    required_fragments = [
        "Typed Glossary Validation",
        "strict_required",
        "lexical_required",
        "reference_only",
        "strict_required` missing 仍是 blocking failure",
        "soft_matches",
        "soft_misses",
        "reference_only_hits",
        "scripts/export_department_glossary_validation_review.py",
        "scripts/apply_department_glossary_validation_review.py",
        "dry-run 不會寫 SQL",
        "--apply",
        "reviewed_validation_type",
        "glossary_validation.json",
        "word_translation_lifecycle.json",
        "pdf_batch_stage_2_post_edit.json",
        "pdf_markdown_stage_2_post_edit.json",
        "CONTEXT.md",
        "docs/adr/0012-department-glossary-validation-is-typed.md",
        "docs/adr/0007-required-glossary-terms-preserve-lexical-choice-only.md",
        "pyproject.toml",
        "CHANGELOG.md",
    ]
    for fragment in required_fragments:
        assert fragment in guide

    assert "25-TypedGlossaryValidation操作與Release指引.md" in index
    assert "Typed Glossary Validation 操作與 Release 指引" in index


def test_department_glossary_acceptance_doc_covers_typed_validation_release_checks():
    guide = Path(
        "docs/system-description/23-DepartmentGlossaryRegressionAcceptance.md"
    ).read_text(encoding="utf-8")

    required_fragments = [
        "Typed Glossary Validation",
        "strict_required",
        "lexical_required",
        "reference_only",
        "tests/test_typed_glossary_validation_docs.py",
        "scripts/export_department_glossary_validation_review.py",
        "scripts/apply_department_glossary_validation_review.py",
        "current_validation_type",
        "reviewed_validation_type",
        "glossary_validation.json",
        "strict_missing",
        "soft_matches",
        "soft_misses",
        "reference_only_hits",
        "lexical_required` soft miss 錯誤中斷 job",
        "reference_only` 被包成 Required Glossary Term",
    ]
    for fragment in required_fragments:
        assert fragment in guide
