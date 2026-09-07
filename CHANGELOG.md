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
