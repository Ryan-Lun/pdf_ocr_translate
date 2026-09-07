# Department Glossary SQL-first 整體回歸測試與人工驗收案例

本文件用來收斂 Department Glossary SQL-first migration 的最終回歸驗收。目標不是替代各模組測試，而是讓維護者能確認 SQL storage、JSON import、API compatibility、PDF / Word / Markdown translation flow、Translation Memory priority、Stage 2 validation 與 job traceability 已經被同一組 release checklist 覆蓋。

Glossary 仍只負責「來源詞 -> 指定譯詞」的 lexical choice。Translation Memory 負責「完整 segment -> 已確認譯文」的 reuse/reference。兩者不可混用，且 TM Reference 不可以覆蓋 Department Glossary。

## 自動回歸測試對照

| Acceptance area | Test coverage | 驗收重點 |
|---|---|---|
| SQL storage behavior | `tests/test_department_glossary_sql.py` | 建立預設 `法規文管部` library、active/disabled entries、department isolation、SQL-first facade、schema/migration/sql init 對齊。 |
| JSON import dry-run/apply/idempotency | `tests/test_department_glossary_import_cli.py` | `dry-run` 不寫入 SQL、不改 JSON；`--apply` 可 create/update；重跑 apply 要 idempotent；invalid/duplicate rows 要明確回報。 |
| old API compatibility fields | `tests/test_glossary_management.py` | `/api/glossary/library` 保留 `system_glossary`、`user_glossary`、`effective_glossary`，舊前端與舊 API consumer 不需立即改 payload。 |
| new library-aware fields | `tests/test_glossary_management.py` | API 同時輸出 `libraries`、`selected_library`、`entries`，讓未來多部門詞彙庫能透過明確 library context 擴充。 |
| PDF、Word、Markdown glossary application | `tests/test_sql_glossary_translation_facade.py`、`tests/test_batch_dedup.py`、`tests/test_word_translate.py`、`tests/test_markdown_translate_html.py` | SQL-backed Department Glossary 會進入 PDF batch/realtime、Word 原版面與 Markdown/PDF rebuild 翻譯請求。 |
| Required Glossary Terms are still enforced | `tests/test_required_glossary_natural_syntax.py`、`tests/test_word_translate.py`、`tests/test_markdown_translate_html.py`、`tests/test_batch_dedup.py` | Required Glossary Terms 必須保留指定譯詞，不可被 synonym 取代；missing term 需觸發 retry 或 validation failure。 |
| longest-match and overlapping terms | `tests/test_department_glossary_sql.py`、`tests/test_glossary_cache.py`、`tests/test_batch_dedup.py` | 較長 source term 優先，overlapping terms 不應造成短詞先吃掉長詞。 |
| TM Reference cannot override Department Glossary terminology | `tests/test_translation_memory_regression.py`、`tests/test_sql_glossary_translation_facade.py`、`tests/test_batch_dedup.py` | Fuzzy/Semantic TM references 只能作為 prompt context，不能直接取代 Required Glossary Terms。 |
| job glossary library traceability | `tests/test_glossary_job_traceability.py` | PDF、Word、PDF rebuild job payload/config 需保留 `department_glossary_library_id`、`department_glossary_library_code`、`department_glossary_entry_count`。 |
| `glossary_hits.json` output | `tests/test_glossary_job_traceability.py`、`tests/test_word_translate.py`、`tests/test_markdown_translate_html.py`、`tests/test_batch_dedup.py` | 每個 job 的 glossary hit artifact 應可追溯實際命中的 source term、approved term、count 與 location。 |

## 建議測試命令

先跑 Department Glossary SQL-first 相關回歸組：

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py tests/test_department_glossary_import_cli.py tests/test_glossary_management.py tests/test_sql_glossary_translation_facade.py tests/test_translation_memory_regression.py tests/test_glossary_job_traceability.py tests/test_markdown_translate_html.py -q
```

release 前再跑 Full test suite：

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

若 Full test suite 失敗，release note 必須記錄 known baseline failures。記錄時至少包含：

- 失敗測試名稱。
- 是否與 Department Glossary SQL-first migration 有關。
- 是否需要阻擋 deployment。
- 暫時接受失敗的原因與後續 issue。

## Manual acceptance checklist

人工驗收前，確認正式或 staging 環境已完成資料表 migration，且 `.env` 使用：

```text
TRANSLATION_GLOSSARY_SOURCE=sql
```

驗收步驟：

1. 使用 `scripts/import_department_glossary.py` 先 dry-run 舊 JSON glossary data，確認 `would_create`、`would_update`、`invalid`、`duplicates` 結果符合預期。
2. 確認 dry-run 後 SQL 沒有新增資料，JSON 檔案也沒有被修改。
3. 加上 `--apply` 匯入舊資料，確認預設 Department Glossary 是 `法規文管部`。
4. 重跑同一份 `--apply`，確認結果是 unchanged 或 0 created，避免重複寫入。
5. 開啟詞彙庫管理畫面或 API，確認 legacy 欄位 `system_glossary`、`user_glossary`、`effective_glossary` 仍存在。
6. 同一個 payload 內確認 library-aware 欄位 `libraries`、`selected_library`、`entries` 正確顯示目前選定 library。
7. 準備至少兩個 Department Glossary libraries，讓不同部門對同一 source term 設不同 target term；翻譯時只能套用選定或預設 library，確認不得跨部門混用。
8. 上傳 PDF 原版面翻譯測試文件，內容包含 glossary hits、longest-match、overlapping terms、model number/project code 與一段可命中 TM fuzzy reference 的句子。
9. 檢查 PDF job payload/config 是否含 `department_glossary_library_id`、`department_glossary_library_code`、`department_glossary_entry_count`。
10. 檢查 PDF job artifact 是否輸出 `glossary_hits.json`，且命中內容與 SQL glossary entries 對得上。
11. 上傳 Word 原版面翻譯測試文件，確認 Required Glossary Terms 仍被套用，且 stage 2 若啟用不可改掉指定譯詞。
12. 上傳 PDF rebuild / Markdown 測試文件，確認 Markdown translation flow 也使用 SQL-backed glossary。
13. 建立一筆 Translation Memory reference，其 target term 與 Department Glossary 不同，確認翻譯結果仍以 Department Glossary 指定譯詞為準。
14. 檢查 `glossary_hits.json`、`tm_references.json`、`stage_2_post_edit.json` 是否能共同說明本次翻譯使用了哪些 glossary、哪些 TM reference，以及 Stage 2 是否 fallback。
15. 確認 `GLOSSARY_CONTEXT_ARTIFACT_ENABLED=false` 時不會每個 job 都輸出 `glossary_context.json`；只有 debug 需要完整 snapshot 時才暫時開啟。

## 驗收失敗條件

以下任一情況視為 Department Glossary SQL-first migration 驗收失敗：

- Exact SQL glossary entry 沒有進入 PDF、Word 或 Markdown 翻譯 prompt。
- Required Glossary Terms 被 synonym 取代但沒有 retry、fallback 或 validation failure。
- overlapping terms 導致短詞覆蓋長詞。
- TM Reference 覆蓋 Department Glossary 指定譯詞。
- API 移除舊欄位，造成舊前端或舊 consumer 無法讀取 glossary。
- Job 缺少 `department_glossary_library_id` 或 `department_glossary_library_code`，導致無法追蹤本次翻譯用哪個 library。
- `glossary_hits.json` 缺失，或內容無法對應到實際命中的 source/target term。
- 不同部門 glossary 混用，導致非選定 department 的譯詞被套用。

## Release note 要求

關閉 #70 前，release note 或 `CHANGELOG.md` 應記錄：

- Department Glossary SQL-first 整體回歸測試已補齊。
- 本次跑過的 targeted regression command。
- Full test suite 結果，或已知 known baseline failures。
- 人工驗收是否涵蓋 `法規文管部` 匯入、PDF、Word、Markdown、TM priority、Stage 2 與 job traceability。
- 若要部署，需確認 `pyproject.toml` 版本號已 bump，並同步更新 `CHANGELOG.md`。
