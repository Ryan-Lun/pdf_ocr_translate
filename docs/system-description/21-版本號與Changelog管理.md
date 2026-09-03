# 附錄 F. 版本號與 Changelog 管理

## 目標

系統從 `0.1.0` 起建立明確版本號，讓部署、驗收、問題回報與 release 管理可以對齊同一個版本基準。

## 單一版本來源

版本號以 `pyproject.toml` 的 `[project].version` 為單一來源。

程式端由 `app/version.py` 讀取版本資訊，並由 Flask template context 提供：

- `app_version`：純版本號，例如 `0.1.0`
- `app_version_label`：畫面顯示文字，例如 `v0.1.0`

不要在頁面、服務或文件中另行硬編碼第二份正式版本號。若要調整版本，應先更新 `pyproject.toml`，再同步更新 `CHANGELOG.md` 的 release 記錄。

## UI 顯示

系統畫面會顯示目前版本，例如 `v0.1.0`。此資訊用於使用者回報問題、部署驗收與維運確認。

## Semantic Versioning 規則

版本格式採用：

```text
MAJOR.MINOR.PATCH
```

遞增規則如下：

- PATCH：修 bug、不改使用方式，例如 `0.1.1`。
- MINOR：新增功能，但不破壞既有流程，例如 `0.2.0`。
- MAJOR：破壞性變更、資料庫 schema 或操作流程需要人工遷移，例如 `1.0.0`。

目前系統仍在快速演進，建議維持 `0.x.x`，直到主要翻譯流程、TM、Stage 2、權限與部署流程穩定後再升至 `1.0.0`。

## Changelog 規則

`CHANGELOG.md` 應隨每次版本發布更新，至少包含：

- 新增功能
- 修正問題
- 設定變更
- Migration 或人工操作注意事項
- 人工驗收結果

## 驗收方式

1. 確認 `pyproject.toml` 的 `[project].version` 是目前正式版本。
2. 啟動系統後確認畫面可看到版本文字，例如 `v0.1.0`。
3. 確認 `CHANGELOG.md` 有對應版本紀錄。
4. 若進行 PATCH、MINOR 或 MAJOR 版號調整，確認 changelog 內容同步更新。

## 不影響範圍

版本號顯示只讀取設定與渲染模板，不會改變登入、翻譯、Translation Memory、Stage 2 或 Teams Alert 的執行流程。
