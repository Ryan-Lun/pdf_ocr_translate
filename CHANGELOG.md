# Changelog

本專案從 `0.1.0` 起採用 Semantic Versioning，格式為 `MAJOR.MINOR.PATCH`。

## 版本號規則

- PATCH：修 bug、不改使用方式，例如 `0.1.1`。
- MINOR：新增功能，但不破壞既有流程，例如 `0.2.0`。
- MAJOR：破壞性變更、資料庫 schema 或操作流程需要人工遷移，例如 `1.0.0`。

## Release 記錄格式

每次 release 建議記錄以下項目：

- 新增功能
- 修正問題
- 設定變更
- Migration 或人工操作注意事項
- 人工驗收結果

## 0.6.7 - 2026-09-07

### Added

- 詞彙庫管理頁新增 Department Glossary library lifecycle 管理區，可建立、更新與停用部門詞彙庫。
- 新增 Department Glossary library API，建立時由系統產生不可由 request 覆寫的穩定 code，更新時只允許修改顯示名稱與部門代碼。
- 停用 library 時會檢查 queued/running/cancel_requested jobs，若仍有任務引用會回傳清楚錯誤並阻擋停用。

### Changed

- 詞彙庫管理 payload 會列出 active 與 inactive libraries，讓歷史 trace 仍能顯示停用 library metadata；新任務上傳 selector 仍只列出 active libraries。
- 管理 UI 不提供 hard delete，停用後保留 SQL 記錄與歷史追溯能力。

### Fixed

- 修正 default 法規文管部 library 在管理 payload refresh 時被重設，保留管理員改名、部門代碼調整與停用結果。

### Validation

- 已執行 `PYTHONPATH=. .venv/bin/python -m py_compile app/services/glossary.py app/blueprints/api/glossary_routes.py tests/test_glossary_management.py`，結果通過。
- 已執行 `node --check static/glossary_manager.js`，結果通過。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_glossary_management.py -q`，結果為 21 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_app.py -k 'department_glossary_selector or upload_workspaces_show_blank_active_department_glossary_selector' -q`，結果為 1 passed、87 deselected。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py tests/test_api_route_registration.py -q`，結果為 17 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests -q`，結果為 545 passed、8 failed；8 個失敗仍集中於既有 `tests/test_app.py` 與 `tests/test_operations_cli.py` baseline，未出現在 #76 新增 Department Glossary library lifecycle tests。

## 0.6.6 - 2026-09-07

### Changed

- Editor 單框重翻、多框重翻與區域補翻改為沿用 job 的 Selected Department Glossary，在執行時從 job config/meta/SQL payload 解析 selected library 並載入目前 SQL active entries。
- Editor retranslation request 內即使帶入 `department_glossary_library_id`，也不會覆寫原 job 的 selected glossary，避免同一份文件術語來源不一致。
- Editor retranslation 會同步更新 job 的 Department Glossary trace metadata/context artifact，讓補翻後仍可追溯 glossary 來源。

### Validation

- 已執行 `PYTHONPATH=. .venv/bin/python -m py_compile app/services/job_glossary.py app/blueprints/api/shared.py app/services/__init__.py app/blueprints/api/editor_routes.py tests/test_editor_selected_department_glossary.py`，結果通過。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_editor_selected_department_glossary.py -q`，結果為 3 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_api_route_registration.py tests/test_api_timeout.py -q`，結果為 8 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_app.py -k 'retranslate_region or retranslate_box or retranslate_boxes or glossary_retranslate or region_ocr_preview' -q`，結果為 6 passed、63 deselected。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_glossary_job_traceability.py -q`，結果為 7 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests -q`，結果為 536 passed、8 failed；8 個失敗仍集中於既有 `tests/test_app.py` 與 `tests/test_operations_cli.py` baseline，未出現在 #75 新增 Editor Selected Department Glossary tests。

## 0.6.5 - 2026-09-07

### Changed

- PDF 原版面翻譯、PDF 翻譯重建與 Word 原版面翻譯 worker 改為在執行時依 job metadata/payload 載入 Selected Department Glossary 的 SQL active entries。
- Worker 遇到執行時已停用的 selected library 會讓 job 明確失敗，不再 fallback 到 `法規文管部`。
- Glossary 查詢在 `source_lang=auto` 時統一以 `zh` 查詢，並保留 Required Glossary Term validation、longest-match behavior 與 glossary priority over TM。

### Validation

- 已執行 `PYTHONPATH=. .venv/bin/python -m py_compile app/services/glossary.py app/services/batch.py app/services/realtime_translate.py app/services/word_translate.py app/services/doc_workspace.py app/services/markdown_translate.py tests/test_selected_department_glossary_workers.py`，結果通過。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_selected_department_glossary_workers.py -q`，結果為 8 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_glossary_job_traceability.py tests/test_department_glossary_sql.py tests/test_sql_glossary_translation_facade.py -q`，結果為 27 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_markdown_translate_html.py tests/test_translation_memory_regression.py -q`，結果為 18 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_word_translate.py tests/test_realtime_translate.py tests/test_batch_dedup.py -q`，結果為 148 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests -q`，結果為 533 passed、8 failed；8 個失敗仍集中於既有 `tests/test_app.py` 與 `tests/test_operations_cli.py` baseline，未出現在 #74 新增 Selected Department Glossary worker tests。

## 0.6.4 - 2026-09-07

### Added

- PDF 原版面翻譯、PDF 翻譯重建與 Word 原版面翻譯上傳表單新增空白預設的 Department Glossary selector，只列出 active libraries，顯示格式為 `name (department_code)`。
- 三個 user-facing job submission route 會使用 Selected Department Glossary contract 驗證 `department_glossary_library_id`，缺漏或不可用選擇會回傳 `請選擇部門詞彙庫` 等 400 validation message。
- 三種新 job 建立流程會把 selected Department Glossary metadata 寫入 job meta 與 SQL payload：library id、code、name、department code、creation-time active entry count。

### Validation

- 已執行 `PYTHONPATH=. .venv/bin/python -m py_compile app/blueprints/main/routes.py app/services/pipeline.py app/services/doc_workspace.py app/services/word_translate.py tests/test_app.py`，結果通過。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_app.py -k 'upload_workspaces or enqueue_user_facing_jobs_persist_department_glossary_metadata or upload_pdf_overlay or upload_word_workspace or upload_doc_workspace or upload_rejects_when_submit_quota' -q`，結果為 17 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_word_translate.py -q`，結果為 63 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py -q`，結果為 16 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests -q`，結果為 525 passed、8 failed；失敗集中於既有 `tests/test_app.py` 與 `tests/test_operations_cli.py` baseline，未出現在 #73 新增 Selected Department Glossary submission tests。

## 0.6.3 - 2026-09-07

### Added

- 新增 Selected Department Glossary request/validation contract，可解析 `department_glossary_library_id`、回傳 selected library metadata、允許 active empty library、拒絕 missing/invalid/unknown/inactive user-facing selections，並保留 legacy/internal fallback 到 `法規文管部`。
- Department Glossary context config 新增 `department_glossary_department_code`，讓後續 job submission、worker 與 editor selected glossary flow 可共用同一份 metadata contract。

### Validation

- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py -k selected_department_glossary -q`，結果為 4 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py tests/test_glossary_job_traceability.py tests/test_sql_glossary_translation_facade.py -q`，結果為 27 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest tests -q`，結果為 521 passed、8 failed；失敗集中於既有 `tests/test_app.py` 與 `tests/test_operations_cli.py` baseline，未出現在 #72 新增 Selected Department Glossary resolver 測試。

## 0.6.2 - 2026-09-07

### Added

- 新增 Department Glossary SQL-first 整體回歸測試與人工驗收案例，對應 SQL storage、JSON import、API compatibility、PDF/Word/Markdown 翻譯、TM priority、Stage 2 validation 與 job traceability。
- 新增 #70 可執行整合 regression 測試，涵蓋 SQL import/API/department isolation、PDF batch glossary/TM priority/glossary hits 與 Stage 2 Required Glossary validation。
- 新增文件回歸測試，鎖住 #70 acceptance checklist、建議 pytest 指令、人工驗收步驟與 known baseline failures 記錄要求。

### Validation

- 已執行 Department Glossary SQL-first targeted regression suite，結果為 65 passed。
- 已執行 full test suite：`PYTHONPATH=. .venv/bin/pytest -q`；collection 階段出現 27 個 known baseline errors，皆來自 `PaddleX/api_examples/pipelines/test_*` 範例測試缺少 PaddleX extra dependencies 或 `paddle` module，未進入本專案 `tests/` 回歸測試執行階段。
- 已補跑本專案測試目錄：`PYTHONPATH=. .venv/bin/pytest tests -q`；結果為 518 passed、7 failed。7 個 known baseline failures 為 `tests/test_app.py::test_upload_template_source_creates_draft`、`tests/test_app.py::test_editor_page_shows_template_entry`、`tests/test_app.py::test_ocr_retry_warning_is_visible_in_jobs_list`、`tests/test_app.py::test_doc_jobs_download_docx_returns_zip`、`tests/test_app.py::test_run_ocr_pipeline_job_skips_paragraph_align_for_general_force`、`tests/test_operations_cli.py::test_seed_bootstrap_populates_auth_defaults`、`tests/test_operations_cli.py::test_seed_bootstrap_uses_initial_admin_work_ids_config`；這些失敗不在 #70 新增 Department Glossary regression 測試範圍。

## 0.6.1 - 2026-09-07

### Added

- 新增 Department Glossary SQL transition 操作指引，涵蓋 SQL-first 模型、JSON dry-run/apply 匯入、API 與翻譯人工驗收、job trace、rollback/fallback 與版本更新提醒。

### Changed

- 補齊環境與 release 文件檢查，讓 `TRANSLATION_GLOSSARY_SOURCE`、`GLOSSARY_CONTEXT_ARTIFACT_ENABLED`、`glossary_hits.json` 與 `department_glossary_*` trace 的操作說明可被測試鎖住。

## 0.6.0 - 2026-09-07

### Added

- 新增 `GLOSSARY_CONTEXT_ARTIFACT_ENABLED` opt-in debug 開關；開啟後才會輸出 `glossary_context.json`，記錄 Department Glossary 來源、library id/code/name、entry count 與完整 entries snapshot。
- Job list payload 新增 `glossary_context_url`，讓已登記的 glossary context artifact 可被 job detail/API 取用。

### Changed

- PDF batch/realtime `batch_config.json` 與 Word/PDF rebuild job payload 會同步保存 `department_glossary_*` minimal trace 欄位；舊 job 沒有這些欄位仍可正常讀取。
- `glossary_context.json` 不再預設為每個 job 產生，日常人工查核以 `glossary_hits.json` 為主。

## 0.5.0 - 2026-09-04

### Changed

- 翻譯流程使用的 glossary facade 預設改讀 SQL-backed 預設 Department Glossary。
- 保留 legacy JSON glossary mode，可透過 `TRANSLATION_GLOSSARY_SOURCE=json` 明確切回舊來源；來源設定只允許 `sql` 或 `json`，避免拼字錯誤被靜默吞掉。
- Required Glossary Term wrapper、longest-match / overlap 處理、TM priority 與既有翻譯流程維持透過高階 facade 整合。

## 0.4.0 - 2026-09-04

### Changed

- Glossary 管理 API 改由預設「法規文管部」Department Glossary SQL 資料提供相容欄位。
- `/api/glossary/library` 保留 `system_glossary`、`user_glossary`、`effective_glossary`，並新增 `libraries`、`selected_library`、`entries` library-aware payload。
- 既有 `/api/glossary` 與 system glossary Excel import/apply/export endpoints 保留 request/response shape，但寫入與讀取預設 Department Glossary SQL 資料。
- AUTH_ENABLED 時，glossary 寫入路徑限定 admin 使用者。

## 0.3.0 - 2026-09-04

### Added

- 新增 Department Glossary JSON 匯入 CLI，支援 dry-run 與 apply 模式。
- 匯入既有 JSON glossary 到預設「法規文管部」詞彙庫，並回報新增、更新、未變更、無效項目與重複來源詞。
- 匯入流程可重複執行且不會建立重複 active entries；既有 JSON 檔不會被刪除或改寫。

### Migration

- 使用此 CLI 前需先具備 `0.2.0` 的 Department Glossary SQL schema。

## 0.2.0 - 2026-09-04

### Added

- 建立 Department Glossary SQL-first 基礎資料表與 Alembic migration，支援部門詞彙庫與詞彙 entries。
- 新增 Department Glossary service facade，可建立/取得預設「法規文管部」詞彙庫，並新增、更新、停用、列出詞彙。
- 保留既有 JSON-backed glossary 行為，尚未切換翻譯流程。

### Migration

- 新增 `department_glossary_libraries` 與 `department_glossary_entries` schema，正式部署前需套用 migration 或更新 SQL Server schema。

## 0.1.1 - 2026-09-04

### Fixed

- 改善 Teams Alert 警報內容，將清洗後的錯誤摘要附加到警報訊息，讓 OCR API timeout、資料庫連線等系統錯誤可直接從 Teams 判斷原因。
- 保留 Teams Alert 敏感資訊防護，避免 traceback、credential、raw request body、完整 URL query 等內容外洩。

## 0.1.0 - 2026-09-03

### Added

- 建立初始系統版本號管理規則。
- 以 `pyproject.toml` 的 `[project].version` 作為單一版本來源。
- 系統畫面顯示目前版本，例如 `v0.1.0`。
