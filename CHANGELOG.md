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

## 0.2.0 - 2026-09-14

### Added

- 新增 Teams Alert service 與異常通知設定，支援外部服務與 worker/background process 異常警報。
- 新增 Translation Memory SQL-first 功能，支援人工匯入、Exact Match 直接套用、Fuzzy Match 作為 LLM reference，並保留後續 semantic retrieval 擴充位置。
- 新增 Department Glossary SQL-first 架構，支援多部門詞彙庫、selected library job flow、管理頁 lifecycle、entry 管理、匯入/匯出、audit trail 與 job traceability。
- 新增 Stage 2 post-edit 翻譯潤飾流程，用於降低 translationese，同時保留原始語意、技術資訊、數字、component names 與 glossary 指定術語。
- 新增 Word 原版面翻譯選項：可保留原文並將譯文置於下方，可控制表格翻譯與頁首頁尾翻譯行為。
- 新增一次性地端模型 Word 批次雙語翻譯 runner，支援 OpenAI-compatible local model endpoint、部門詞彙庫、表格排除與 Stage 2 選項。
- 新增離線 `pp_json` / opendataloader JSON 數字標題中英文詞彙候選抽取腳本，可輸出人工審查用 CSV，並以 `source_file` / `source_format` 標記來源。

### Changed

- 翻譯流程改由 SQL-backed Department Glossary facade 供應詞彙，保留 legacy JSON glossary mode 作為明確 fallback。
- PDF 原版面翻譯、PDF 翻譯重建、Word 原版面翻譯、Markdown 翻譯、editor retranslation 與 worker 執行流程會使用 job 選定的 Department Glossary。
- Glossary protection 改為讓 Required Translation Term 以模型可理解的 target term 參與翻譯，鎖定 lexical choice 但不限制周邊句法自然重組。
- Stage 2 post-edit 增加拼字檢查、glossary validation、受控安全詞形變體驗證與 debug artifacts。
- 系統靜態資源以 app version cache busting，降低部署後瀏覽器沿用舊 CSS/JS 的風險。
- `GLOSSARY_CONTEXT_ARTIFACT_ENABLED` 改為 opt-in debug artifact；日常查核以 `glossary_hits.json` 為主。

### Fixed

- 修正 production startup validation 與設定檢查，避免不安全 cookie、錯誤模型部署名稱或 development endpoint 在正式環境靜默啟動。
- 修正 Word 翻譯小節編號被截斷、譯文段落延續 source numbering、頁首頁尾跨段術語未命中與完成任務殘留錯誤等問題。
- 修正 Department Glossary default library 更新保留、停用後重新啟用、非管理員誤操作顯示、entry 更新不應新增重複 active row 等問題。
- 修正 Translation Memory exact match 重複寫入與 debug artifact 命名不一致問題。
- 改善 Teams Alert 錯誤摘要，保留敏感資訊防護，避免 traceback、credential、raw request body 或完整 URL query 外洩。

### Configuration

- 正式部署需確認 `.env` 中 production 安全設定、Teams Alert、Translation Memory、Department Glossary、Stage 2 與 local model 相關參數。
- 若要關閉每個任務的 glossary context artifact，設定 `GLOSSARY_CONTEXT_ARTIFACT_ENABLED=false`。
- 版本號來源為 `pyproject.toml` 的 `[project].version`，本版同步更新為 `0.2.0`。

### Migration

- 正式部署前需確認 SQL Server schema 已包含 Translation Memory、Department Glossary libraries/entries、glossary audit events、job traceability 等資料表與欄位。
- 舊 JSON glossary 可使用既有 import CLI 匯入 Department Glossary SQL；既有 JSON 檔不會被刪除或改寫。

### Validation

- 已執行多輪 focused pytest，涵蓋 Translation Memory、Department Glossary SQL/API/UI、Selected Department Glossary workers/editor、Stage 2 post-edit、Word 翻譯、Teams Alert、app version 與 #93 離線抽取腳本。
- 已執行 `PYTHONPATH=. .venv/bin/pytest -q tests/test_app_version.py tests/test_extract_numbered_heading_glossary_candidates.py`，結果為 10 passed。
- 已執行 `PYTHONPATH=. .venv/bin/pytest -q tests/test_extract_numbered_heading_glossary_candidates.py`，結果為 6 passed。
- 已用 `output2/UQP-02-2040rev14_專案作業管制程序.json` 實測 opendataloader JSON 抽取，排除第 1、7 頁後輸出 20 筆候選。
- 已執行 `PYTHONPATH=. .venv/bin/pytest -q tests`，結果為 627 passed、8 failed；失敗集中於既有 `tests/test_app.py` 與 `tests/test_operations_cli.py` baseline。
- 已執行完整 `PYTHONPATH=. .venv/bin/pytest -q`，collection 階段會誤收 `PaddleX/api_examples/pipelines/test_*` 範例測試，因缺少 PaddleX optional dependencies 或 `paddle` module 失敗，未指向本版變更。

## 0.1.0 - 2026-09-03

### Added

- 建立初始系統版本號管理規則。
- 以 `pyproject.toml` 的 `[project].version` 作為單一版本來源。
- 系統畫面顯示目前版本，例如 `v0.1.0`。
