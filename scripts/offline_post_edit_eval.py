#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import openai_config  # noqa: E402


POST_EDIT_PROMPT = "You are a professional English technical translation editor.\n\nYour task is NOT to retranslate the source from scratch.\n\nYour task is to revise the existing English translation only where necessary to remove translationese and make it read like naturally written professional English.\n\n# Priority\n\nFollow these priorities in order:\n\n1. Preserve the exact meaning of the source.\n2. Preserve technical information and semantic relationships.\n3. Preserve required terminology exactly.\n4. Preserve the source's degree of obligation, certainty, permission, and prohibition.\n5. Improve naturalness, English collocation, and professional readability.\n\nNaturalness must never override accuracy, terminology, or semantic force.\n\n# Revision Goal\n\nIdentify wording that is grammatically correct but still sounds:\n\n* literally translated from Chinese\n* influenced by Chinese word order\n* unnatural to a native professional English reader\n* awkward in technical or procedural English\n\nRevise only those parts.\n\nFocus especially on:\n\n* unnatural English collocations\n* literal phrase mappings from Chinese\n* Chinese-influenced noun structures\n* awkward preposition choices\n* unnatural verb-noun combinations\n* redundant wording\n* awkward participial constructions\n* unnecessarily indirect expressions\n* source-language word order that is unnatural in English\n\nPrefer conventional, concise professional English phrasing when it expresses exactly the same meaning.\n\nTranslate and revise phrases as semantic units rather than preserving Chinese phrase structure word by word.\n\n# Semantic Fidelity\n\nDo not:\n\n* add information\n* omit information\n* infer information\n* generalize technical details\n* simplify component names\n* replace specific technical concepts with broader ones\n* change logical relationships\n* change the subject or actor\n* change conditions, requirements, or scope\n\nPreserve all meaningful modifiers and qualifiers from the source.\n\nIf the source contains a specific technical noun or component name, preserve that information unless required terminology explicitly specifies otherwise.\n\n# Modal and Requirement Strength\n\nPreserve the exact level of obligation and certainty.\n\nDo NOT change:\n\n* must → should\n* must → may\n* shall → should\n* required → recommended\n* prohibited → discouraged\n\nor make any equivalent change that weakens or strengthens the source meaning.\n\nIf the existing translation correctly expresses mandatory language, preserve that mandatory force.\n\n# Required Terminology\n\nThe following terminology is mandatory.\n\nUse every required term exactly as specified, including spelling and capitalization.\n\nDo not:\n\n* translate it again\n* replace it with a synonym\n* change capitalization\n* shorten it\n* generalize it\n* omit it\n\nRequired terminology constrains lexical choice only.\n\nYou MAY reorganize the surrounding English sentence or phrase when necessary for natural English syntax.\n\nPreserving a required term does NOT require preserving its original Chinese word order or surrounding phrase structure.\n\nIntegrate required terminology naturally into the English sentence.\n\n# Natural English Requirement\n\nA translation is not considered satisfactory merely because it is grammatically correct and semantically understandable.\n\nIf an expression sounds translated or follows Chinese phrasing too closely, replace it with the natural professional English expression that conveys the same meaning.\n\nPrefer:\n\n* conventional English collocations\n* natural technical verb-noun combinations\n* direct procedural wording\n* concise English phrase structures\n\nAvoid preserving a literal phrase merely because each individual word has a valid English translation.\n\nFor example, when the same meaning can be expressed naturally without reproducing a Chinese nominal structure, use the natural English structure.\n\n# Revision Scope\n\nDo not rewrite the entire translation merely for stylistic variety.\n\nPreserve wording that is already:\n\n* accurate\n* natural\n* professional\n* terminologically correct\n\nRevise only phrases or clauses that materially improve naturalness or remove translationese.\n\nSentence restructuring or sentence splitting is allowed only when it improves English readability without changing meaning, semantic force, terminology, or logical relationships.\n\n# Final Verification\n\nBefore producing the final answer, silently compare the revised translation against the original source and verify that:\n\n* no source meaning was lost\n* no information was added\n* no technical detail was generalized\n* no component name was simplified\n* no required terminology was changed\n* no mandatory wording was weakened\n* no optional wording was strengthened\n* numbers and factual values remain unchanged\n* Chinese-influenced collocations and phrase structures have been removed where a natural English equivalent exists\n* the final English reads like professional technical writing rather than a literal translation\n\nIf improving naturalness would require changing or guessing the source meaning, keep the accurate wording instead.\n\nOutput ONLY the revised English translation.".strip()


@dataclass(frozen=True)
class EvalSample:
    sample_id: str
    source_text: str
    existing_translation: str
    glossary_terms: list[dict[str, str]]


def _read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON array or JSONL records.")
        return [item for item in data if isinstance(item, dict)]
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_no} is not a JSON object.")
        records.append(item)
    return records


def _normalize_glossary_terms(value: Any) -> list[dict[str, str]]:
    terms: list[dict[str, str]] = []
    if not isinstance(value, list):
        return terms
    for item in value:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_term") or item.get("source") or "").strip()
        target = str(item.get("approved_term") or item.get("target") or "").strip()
        if target:
            terms.append({"source_term": source, "approved_term": target})
    return terms


def _load_default_glossary_hits(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_glossary_terms(payload)


def load_samples(path: Path, default_glossary_terms: list[dict[str, str]]) -> list[EvalSample]:
    records = _read_json_or_jsonl(path)
    samples: list[EvalSample] = []
    for index, item in enumerate(records, start=1):
        source_text = str(item.get("source_text") or item.get("source") or "").strip()
        existing = str(
            item.get("existing_translation")
            or item.get("translation")
            or item.get("target_text")
            or ""
        ).strip()
        if not source_text or not existing:
            raise ValueError(
                f"Sample #{index} must include source_text and existing_translation."
            )
        sample_id = str(item.get("id") or item.get("sample_id") or f"sample_{index:04d}")
        glossary_terms = _normalize_glossary_terms(item.get("glossary_terms"))
        if not glossary_terms:
            glossary_terms = default_glossary_terms
        samples.append(
            EvalSample(
                sample_id=sample_id,
                source_text=source_text,
                existing_translation=existing,
                glossary_terms=glossary_terms,
            )
        )
    return samples


def glossary_terms_text(terms: list[dict[str, str]]) -> str:
    if not terms:
        return "None"
    lines = []
    seen: set[str] = set()
    for term in terms:
        target = term["approved_term"]
        if target in seen:
            continue
        seen.add(target)
        source = term.get("source_term") or ""
        if source:
            lines.append(f"- {source} => {target}")
        else:
            lines.append(f"- {target}")
    return "\n".join(lines)


def build_user_prompt(sample: EvalSample) -> str:
    return "\n\n".join(
        [
            "<ORIGINAL_SOURCE>\n" + sample.source_text + "\n</ORIGINAL_SOURCE>",
            "<EXISTING_TRANSLATION>\n" + sample.existing_translation + "\n</EXISTING_TRANSLATION>",
            "<REQUIRED_TERMINOLOGY>\n"
            + glossary_terms_text(sample.glossary_terms)
            + "\n</REQUIRED_TERMINOLOGY>",
        ]
    )


def post_edit(sample: EvalSample, *, model: str, temperature: float) -> str:
    client = openai_config.create_sync_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": POST_EDIT_PROMPT},
            {"role": "user", "content": build_user_prompt(sample)},
        ],
        temperature=temperature,
    )
    return str(response.choices[0].message.content or "").strip()


def validate_result(sample: EvalSample, revised: str) -> list[str]:
    warnings: list[str] = []
    for term in sample.glossary_terms:
        target = term["approved_term"]
        if target and target not in revised:
            warnings.append(f"missing glossary term: {target}")
    return warnings


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_markdown(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Offline Post-Edit Evaluation", ""]
    for record in records:
        lines.extend(
            [
                f"## {record['id']}",
                "",
                "### Source",
                "",
                record["source_text"],
                "",
                "### Existing Translation",
                "",
                record["existing_translation"],
                "",
                "### Revised Translation",
                "",
                record["revised_translation"],
                "",
                "### Glossary Terms",
                "",
                glossary_terms_text(record["glossary_terms"]),
                "",
                "### Validation Warnings",
                "",
                "\n".join(f"- {warning}" for warning in record["warnings"]) or "None",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_sample_template(path: Path) -> None:
    payload = [
        {
            "id": "case_0001",
            "source_text": "3.1外觀形狀需符合圖面要求。",
            "existing_translation": "3.1 Appearance shape must comply with drawing requirements.",
            "glossary_terms": [
                {"source_term": "外觀", "approved_term": "Appearance"}
            ],
        },
        {
            "id": "case_0002",
            "source_text": "ABC-123專案的製程規範需重新確認。",
            "existing_translation": "The Process Specification of ABC-123 project must be reconfirmed.",
            "glossary_terms": [
                {"source_term": "製程規範", "approved_term": "Process Specification"}
            ],
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run isolated post-edit evaluation for existing translations.",
    )
    parser.add_argument("--input", type=Path, help="Input JSON/JSONL samples.")
    parser.add_argument(
        "--glossary-hits",
        type=Path,
        help="Optional job glossary_hits.json used when a sample has no glossary_terms.",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("out/post_edit_eval/results.jsonl"),
        help="Output JSONL path.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("out/post_edit_eval/report.md"),
        help="Output Markdown report path.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model/deployment. Defaults to WORD_TRANSLATE_DEPLOYMENT fallback.",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call the API; output prompts and keep revised text equal to existing text.",
    )
    parser.add_argument(
        "--write-template",
        type=Path,
        help="Write a sample input template and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")

    if args.write_template:
        write_sample_template(args.write_template)
        print(f"Wrote sample template: {args.write_template}")
        return 0
    if not args.input:
        raise SystemExit("--input is required unless --write-template is used.")

    default_glossary_terms = _load_default_glossary_hits(args.glossary_hits)
    samples = load_samples(args.input, default_glossary_terms)
    model = args.model.strip() or openai_config.get_word_translate_deployment()
    records: list[dict[str, Any]] = []

    for sample in samples:
        if args.dry_run:
            revised = sample.existing_translation
        else:
            revised = post_edit(sample, model=model, temperature=args.temperature)
        record = {
            "id": sample.sample_id,
            "source_text": sample.source_text,
            "existing_translation": sample.existing_translation,
            "revised_translation": revised,
            "changed": revised != sample.existing_translation,
            "glossary_terms": sample.glossary_terms,
            "warnings": validate_result(sample, revised),
            "prompt": build_user_prompt(sample) if args.dry_run else "",
        }
        records.append(record)
        status = "changed" if record["changed"] else "unchanged"
        warnings = "; ".join(record["warnings"]) or "ok"
        print(f"{sample.sample_id}: {status}; {warnings}")

    write_jsonl(args.output_jsonl, records)
    write_markdown(args.output_md, records)
    print(f"Wrote JSONL: {args.output_jsonl}")
    print(f"Wrote Markdown: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
