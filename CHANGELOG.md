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

## 0.1.0 - 2026-09-03

### Added

- 建立初始系統版本號管理規則。
- 以 `pyproject.toml` 的 `[project].version` 作為單一版本來源。
- 系統畫面顯示目前版本，例如 `v0.1.0`。
