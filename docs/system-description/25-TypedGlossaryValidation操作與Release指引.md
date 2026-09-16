# 附錄 J. Typed Glossary Validation 操作與 Release 指引

## 目標

Typed Glossary Validation 用來把 Department Glossary entry 的驗證策略明確分成三種，避免所有詞彙都被同一種 hard required 規則處理。這個機制只改變 glossary term 的 validation policy，不改變 Selected Department Glossary、longest-match、overlapping term handling、Translation Memory priority 或既有翻譯 pipeline。

本功能遵循 `CONTEXT.md` 的 Domain Vocabulary，並由 `docs/adr/0012-department-glossary-validation-is-typed.md` 記錄決策。`docs/adr/0007-required-glossary-terms-preserve-lexical-choice-only.md` 仍是 glossary 限制 lexical choice、不限制自然句法的基礎原則。

## Validation Type

Department Glossary entry 的 `validation_type` 只能是以下三種：

| validation_type | 用途 | Runtime 行為 |
|---|---|---|
| `strict_required` | 官方名稱、產品系列、組織名稱、標準文件名稱、不可被詞形變化取代的術語。 | 會包成 Required Glossary Term。翻譯結果必須出現指定 target term；缺少時維持 hard validation failure / retry / fallback 行為。 |
| `lexical_required` | 一般專業詞彙，需要保留核准 lexical choice，但英文可因語法產生大小寫或詞形變化。 | 會包成 Required Glossary Term。Exact match 會通過；允許的 deterministic case / inflection match 記為 `soft_matches`；未命中記為 `soft_misses`，不阻斷 job。 |
| `reference_only` | 只想提示模型偏好的用詞或背景，但不適合強制輸出指定字面形式的詞。 | 不包成 Required Glossary Term，不列入 missing required term；仍可進入 prompt reference 與 trace artifact，記為 `reference_only_hits`。 |

`lexical_required` 不是 synonym whitelist，也不是允許模型任意換詞。它只接受系統定義的 deterministic case / inflection 變體，用來降低 `records` / `record`、大小寫等英文語法造成的誤擋。

## Database 與 Default

`translation.department_glossary_entries.validation_type` 是 SQL 中的正式 governance 欄位。新增或既有未分類 entry 預設為：

```text
strict_required
```

正式環境需確認已套用 migration：

```text
migrations/versions/0007_add_department_glossary_validation_type.py
```

或 SQL Server init script 已包含：

```text
validation_type varchar(30) NOT NULL ... DEFAULT ('strict_required')
```

## CSV Review Workflow

分類 review 採兩階段 CLI。系統可以匯出目前 Department Glossary entries；AI 或人工可在 CSV 中補 `suggested_validation_type`、`classification_reason`、`confidence`，但正式套用只讀取人工確認後的 `reviewed_validation_type`。

匯出指定 library：

```bash
PYTHONPATH=. .venv/bin/python scripts/export_department_glossary_validation_review.py glossary_classification_review.csv --library-id 2
```

也可以使用 stable library code：

```bash
PYTHONPATH=. .venv/bin/python scripts/export_department_glossary_validation_review.py glossary_classification_review.csv --library-code regulatory-document-control
```

CSV 欄位包含：

```text
entry_id,library_id,source_lang,target_lang,source_term,target_term,current_validation_type,suggested_validation_type,classification_reason,confidence,reviewed_validation_type,review_note
```

套用前先 dry-run；dry-run 不會寫 SQL：

```bash
PYTHONPATH=. .venv/bin/python scripts/apply_department_glossary_validation_review.py glossary_classification_reviewed.csv --library-id 2 --work-id NE025
```

確認 `invalid=0`、`would_update` 符合預期後才 apply：

```bash
PYTHONPATH=. .venv/bin/python scripts/apply_department_glossary_validation_review.py glossary_classification_reviewed.csv --library-id 2 --work-id NE025 --apply
```

apply CLI 會檢查 `entry_id`、`library_id`、entry identity 與 `reviewed_validation_type`。空白 `reviewed_validation_type` 會 skipped，不會改資料；invalid row 會讓 CLI 以非 0 exit code 結束。

## Runtime 行為

Word、PDF batch、PDF realtime 與 Markdown / PDF rebuild 共用 typed glossary validation contract：

1. 建立翻譯請求前，先載入 Selected Department Glossary active entries。
2. `reference_only` entry 不產生 `<term>...</term>` required wrapper。
3. `strict_required` 與 `lexical_required` entry 仍會依 glossary lookup、priority、longest-match 與 overlapping term handling 產生 Required Glossary Term。
4. Stage 1 / Stage 2 後會執行 glossary validation。
5. `strict_required` missing 仍是 blocking failure。
6. `lexical_required` soft match / soft miss 只進 artifact，供人工 review。
7. `reference_only` 命中只進 reference trace，不阻擋翻譯。

Glossary 優先權仍高於 Translation Memory。TM Reference 可以提供句型、語氣與既有翻譯習慣，但不能覆蓋 Department Glossary 的 validation type 或 target term。

## Artifact

日常排查以 job root 的 artifact 為準：

| Flow | 主要 artifact |
|---|---|
| Word 原版面翻譯 | `word_translation_lifecycle.json`、`word_final_translations.json`、`word_stage_2_post_edit.json`、`glossary_hits.json` |
| PDF batch / PDF 原版面翻譯 | `batch_key_map.json`、`glossary_hits.json`、`glossary_validation.json`、`pdf_batch_stage_2_post_edit.json` |
| PDF realtime | `glossary_hits.json`、`glossary_validation.json` |
| Markdown / PDF rebuild | `glossary_hits.json`、`glossary_validation.json`、`pdf_markdown_stage_2_post_edit.json` |

Word job 的 final truth 是 `word_translation_lifecycle.json`、`word_final_translations.json` 與 writeback map。`word_stage_2_post_edit.json` 只是 Stage 2 debug output，不應單獨當作最終譯文來源。

`glossary_validation.json` 與 Stage 2 artifact 會記錄：

- `strict_missing`
- `soft_matches`
- `soft_misses`
- `reference_only_hits`

## Regression Acceptance

正式 release 前至少確認：

1. DB schema 與 init script 都包含 `validation_type`，既有資料 default 為 `strict_required`。
2. CSV export 可以輸出指定 Department Glossary 的 review 欄位。
3. CSV apply dry-run 不寫 SQL，`--apply` 才更新 `reviewed_validation_type`。
4. Word flow 中 `strict_required` missing 仍會 fallback 或 fail；`lexical_required` soft miss 不會阻斷 job。
5. PDF batch / PDF realtime / Markdown flow 與 Word 使用同一套 typed validation 語意。
6. `reference_only` 不會被包成 Required Glossary Term，也不會造成 missing required glossary failure。
7. Artifact 能看出 `strict_missing`、`soft_matches`、`soft_misses` 與 `reference_only_hits`。
8. Glossary 與 TM 衝突時，仍以 Department Glossary target term 與 validation type 為準。

建議 regression command：

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py tests/test_department_glossary_import_cli.py tests/test_word_translate.py tests/test_translation_post_edit.py tests/test_batch_dedup.py tests/test_markdown_translate_html.py tests/test_typed_glossary_validation_docs.py -q
```

release 前仍應跑完整專案測試：

```bash
PYTHONPATH=. .venv/bin/pytest -q tests
```

若 full suite 有 known baseline failures，需在 `CHANGELOG.md` 的 Validation 記錄失敗數量、失敗範圍，以及是否與 typed glossary validation 無關。

## Release Note 要求

發布 typed glossary validation 時，需同步更新：

1. `pyproject.toml` 的 `[project].version`。
2. `CHANGELOG.md` 的版本紀錄。
3. `docs/system-description/README.md` 的文件索引。
4. 相關 ADR / Domain Vocabulary cross-reference。

`CHANGELOG.md` 至少要寫明：

- 新增 `strict_required`、`lexical_required`、`reference_only`。
- CSV review export / dry-run / apply 工作流。
- Word、PDF、Markdown、realtime runtime validation 行為。
- migration 或正式部署前需確認 DB schema。
- 已執行的自動測試與人工驗收結果。
