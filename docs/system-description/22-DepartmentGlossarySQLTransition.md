# 附錄 G. Department Glossary SQL Transition 操作指引

## 目標

本指引用於 SQL-backed Department Glossary transition。目標是讓正式翻譯流程改用 SQL Server 中的 Department Glossary，並保留可驗證、可回退、可追查的操作步驟。

Department Glossary SQL-first 代表：

- 正式詞彙來源預期為 SQL Server。
- 每個翻譯 job 使用一個 Department Glossary。
- 現階段預設 Department Glossary 是 `法規文管部`。
- 既有 JSON glossary 只作為 migration source 或 transition fallback，不是正式長期來源。

Glossary 與 Translation Memory 必須分開：

- Glossary 管理「術語 -> 核准譯詞」，例如 `刻印 -> Laser Marking`。
- Translation Memory 管理「完整 segment -> 已確認譯文」。
- TM Reference 不可以覆蓋 Department Glossary。若兩者衝突，Department Glossary 的 required term 是較強約束。
- 不要把 glossary 匯入 Translation Memory，也不要因 glossary 調整自動建立 TM entry。

## 正式設定

正式環境建議維持 SQL-first：

```env
TRANSLATION_GLOSSARY_SOURCE=sql
```

`TRANSLATION_GLOSSARY_SOURCE=sql` 會讓翻譯流程透過 glossary facade 讀取預設 Department Glossary 的 active entries。舊 job 沒有 department glossary trace 欄位仍可讀取，不需要補寫舊 job metadata 才能啟動系統。

transition 期間可暫時切回 JSON fallback：

```env
TRANSLATION_GLOSSARY_SOURCE=json
```

`TRANSLATION_GLOSSARY_SOURCE=json` 只適合短期 rollback 或比對問題。若切回 JSON，需確認 JSON 檔案仍是部署主機上的預期版本，並記錄切換原因與切回 SQL 的時間。

詞彙庫 trace artifact 預設不要開啟：

```env
GLOSSARY_CONTEXT_ARTIFACT_ENABLED=0
```

只有排查「本次 job 到底載入哪些 Department Glossary entries」時，才暫時設為 `true`。開啟後每個翻譯 job 會輸出完整 `glossary_context.json` snapshot，可能讓 artifact 變大；日常人工驗收應以 `glossary_hits.json` 和 job payload 內的 `department_glossary_*` 欄位為主。

## JSON 匯入 SQL

舊 JSON glossary data 應匯入到預設 Department Glossary：`法規文管部`。

匯入前先確認已完成 Department Glossary schema migration，包含：

- `department_glossary_libraries`
- `department_glossary_entries`

dry-run 不會寫入 SQL，也不會修改 JSON 檔案：

```bash
PYTHONPATH=. .venv/bin/python scripts/import_department_glossary.py glossary/system_glossary.json --source-lang zh --target-lang en --work-id NE025
```

確認 dry-run 輸出摘要：

```text
department_glossary_import dry_run=1 library_id= scanned=... created=0 updated=0 unchanged=... would_create=... would_update=... invalid=... duplicates=...
```

每筆明細會以 `department_glossary_import_detail` 輸出。若 `invalid` 或 `duplicates` 不為 0，CLI 會回傳非 0 exit code；應先修正 JSON 來源或確認重複詞處理策略，不要直接 apply。

確認 dry-run 結果後再 apply：

```bash
PYTHONPATH=. .venv/bin/python scripts/import_department_glossary.py glossary/system_glossary.json --apply --source-lang zh --target-lang en --work-id NE025
```

apply 成功後，重跑同一個 apply 應該是 idempotent：

```text
department_glossary_import dry_run=0 ... unchanged=... created=0 updated=0 ...
```

如果 JSON 內同一 source term 的 target term 後續有更新，重新 apply 會更新既有 active entry，不應建立重複 active entry。

## API 驗證

SQL transition 後，舊 glossary API shape 必須仍可用，同時可看到 library-aware payload。

人工驗證：

1. 登入系統。
2. 打開詞彙庫管理頁 `/workspace/glossary`。
3. 確認舊欄位仍存在：`system_glossary`、`user_glossary`、`effective_glossary`。
4. 確認新欄位可看到：`libraries`、`selected_library`、`entries`。
5. 確認 `selected_library.name` 是 `法規文管部`，或符合本次部署選定的 Department Glossary。
6. 新增、更新、停用詞彙後，重新查詢 API，確認 active entries 與畫面一致。

若 API payload 看不到 library-aware 欄位，先確認部署版本、資料庫 migration、`TRANSLATION_GLOSSARY_SOURCE=sql` 與 Web/Worker 是否已重啟。

## 翻譯行為驗證

建議準備一份包含下列內容的 PDF、Word 或 Markdown 測試文件：

- 會命中 Department Glossary 的來源詞。
- 至少一組 overlapping terms，用來確認 longest-match。
- 一段可命中 Translation Memory fuzzy/reference 的相似句，但 glossary term 與 TM reference 不同。
- 一段需要 Stage 2 post-edit 的自然度檢查內容。

驗證重點：

1. 翻譯結果必須使用 Department Glossary 指定譯詞。
2. Required Glossary Term validation 仍會阻止 synonym 取代核准譯詞。
3. longest-match 行為維持：較長、較具體的 source term 優先。
4. TM Reference 不可以覆蓋 Department Glossary。
5. Stage 2 可以改善 translationese，但不可以改掉 required glossary terms。
6. `glossary_hits.json` 持續輸出，內容要能看出實際命中的 source term 與 approved target term。
7. job trace 中應保留 `department_glossary_*` 欄位，例如 `department_glossary_library_id`、`department_glossary_library_code`、`department_glossary_entry_count`。

若需要排查載入的完整詞彙 snapshot，暫時設定：

```env
GLOSSARY_CONTEXT_ARTIFACT_ENABLED=true
```

重啟 Web / Worker 後重新跑 job，檢查 `glossary_context.json`。排查完成後應改回 `0` 或移除此設定。

## Production rollout checklist

部署前：

1. 確認 migration 已套用到正式 SQL Server。
2. 確認 `.env` 設定 `TRANSLATION_GLOSSARY_SOURCE=sql`。
3. 執行 JSON import dry-run，確認 `invalid=0` 且 `duplicates=0`。
4. 將舊 JSON glossary data apply 到 `法規文管部`。
5. 重跑 apply，確認匯入具 idempotency。
6. 重啟 Web 與 Worker。
7. 驗證 `/workspace/glossary` 與 glossary API payload。
8. 跑一份 PDF 或 Word 測試文件，確認翻譯結果、`glossary_hits.json` 與 job trace。
9. 確認 `GLOSSARY_CONTEXT_ARTIFACT_ENABLED` 沒有在日常正式環境長期開啟。

部署後：

1. 監看 Web / Worker log 是否有 Department Glossary、startup validation 或 database schema 錯誤。
2. 抽查新的翻譯 job 是否記錄 `department_glossary_*`。
3. 抽查 glossary 管理頁新增/更新後，翻譯流程是否讀到 SQL active entries。

## Rollback / fallback

rollback 優先順序：

1. 若只是特定匯入資料錯誤，優先在 SQL Department Glossary 停用或修正錯誤 entry。
2. 若 SQL glossary 讀取流程異常，可暫時改回：

```env
TRANSLATION_GLOSSARY_SOURCE=json
```

3. 重啟 Web 與 Worker。
4. 跑同一份驗收文件，比對 glossary term 是否回到 JSON 行為。
5. 建立修復 ticket，修復 SQL glossary 問題後再切回 `TRANSLATION_GLOSSARY_SOURCE=sql`。

rollback 期間不要刪除 SQL glossary tables，除非要執行完整資料庫復原。一般情況下，切換 source setting 即可降低風險。

## Versioning reminder

任何會部署到正式環境的 Department Glossary transition 變更，都要先決定是否 bump 系統版本。

維護者應檢查：

1. `pyproject.toml` 的 `[project].version` 是否已更新。
2. `CHANGELOG.md` 是否有對應版本紀錄。
3. changelog 是否寫明 migration、設定變更、rollback/fallback 與人工驗收結果。

文件、設定、migration、CLI 或 user-visible 行為變更都應在 release note 中清楚記錄。
