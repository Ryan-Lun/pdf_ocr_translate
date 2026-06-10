# Environment Variables

這份文件整理目前 `.env` 中每個參數的用途。機密值例如密碼、API key、資料庫連線字串不應寫入文件或提交到 Git。

相關入口：
- [app/services/state.py](/home/NE025/pdf_ocr_translate/app/services/state.py)
- [app/config.py](/home/NE025/pdf_ocr_translate/app/config.py)
- [deploy.sh](/home/NE025/pdf_ocr_translate/deploy.sh)
- [scripts/install_systemd_units.sh](/home/NE025/pdf_ocr_translate/scripts/install_systemd_units.sh)

## 認證與授權

| 參數 | 功能 |
| --- | --- |
| `AUTH_ENABLED` | 是否啟用登入保護。`1` 代表需要登入，`0` 代表關閉登入保護。 |
| `AUTH_STUB_ENABLED` | 是否啟用 stub 登入。`1` 會略過 LDAP 密碼驗證，適合本機測試；正式環境應為 `0`。 |
| `AUTHZ_MODE` | 登入後的授權模式。目前常用 `ad_all_users`，代表有效 AD 使用者可登入，管理員權限由本機角色控制。 |
| `AUTH_REQUIRE_LOCAL_USER` | 是否要求使用者必須已存在本機 `users` 表才可登入。 |
| `SECRET_KEY` | Flask session 簽章密鑰。正式環境必須設定高強度隨機值。 |
| `OWNER_ACCESS_ENABLED` | 是否啟用一般 job owner 隔離。`1` 時一般使用者只能操作自己的 job；模板目前設計為全域可見、全域可編輯。 |
| `SESSION_COOKIE_NAME` | Flask session cookie 名稱。同一個 host 上有多個 Flask 服務時應使用不同名稱，避免 cookie 衝突。 |
| `INITIAL_ADMIN_WORK_IDS` | 初始管理員工號清單。`seed-bootstrap` 會依此建立或補齊 admin 角色。 |

## LDAP / AD

| 參數 | 功能 |
| --- | --- |
| `LDAP_HOST` | LDAP 或 AD 伺服器主機。 |
| `LDAP_BASE_DN` | 搜尋使用者的 Base DN。 |
| `LDAP_BIND_DN` | 用於查詢 AD 的服務帳號 DN 或網域帳號。 |
| `LDAP_BIND_PASSWORD` | `LDAP_BIND_DN` 的密碼。不可提交到 Git。 |
| `LDAP_USER_LOGIN_ATTR` | 使用者登入識別欄位，常見為 `sAMAccountName`。 |
| `LDAP_USER_SEARCH_SCOPE` | LDAP 搜尋範圍，例如 `SUBTREE`。 |
| `LDAP_USER_OBJECT_FILTER` | LDAP 使用者搜尋 filter，用來排除電腦帳號或限制物件類型。 |
| `LDAP_GROUP_GATE_ENABLED` | 是否啟用 AD 群組 gate。`0` 會略過群組限制。 |
| `ALLOWED_GROUP_DN` | 啟用群組 gate 時允許登入的 AD 群組 DN。 |

## 執行環境與 Schema

| 參數 | 功能 |
| --- | --- |
| `APP_ENV` | 應用程式環境。正式部署使用 `production`。 |
| `AUTO_SCHEMA_MANAGEMENT` | 是否讓 app 啟動時自動建立或補齊 schema。正式環境建議 `0`，由 Alembic / SQL script 控制 schema。 |
| `DATABASE_SCHEMA` | SQL Server schema 名稱，目前資料表位於此 schema 下，例如 `translation`。 |
| `DATABASE_URL` | SQL Server 連線字串。包含帳密與主機資訊，不可提交到 Git。 |

## Azure OpenAI / 模型

| 參數 | 功能 |
| --- | --- |
| `OPENAI_API_KEY` | Azure OpenAI API key。不可提交到 Git。 |
| `OPENAI_BASE_URL` | Azure OpenAI endpoint。 |
| `BATCH_TRANSLATE_DEPLOYMENT` | PDF batch 翻譯使用的部署名稱。 |
| `DOC_TRANSLATE_DEPLOYMENT` | 文件翻譯使用的部署名稱。 |
| `WORD_TRANSLATE_DEPLOYMENT` | Word 翻譯使用的部署名稱。 |
| `WORD_QUALITY_DEPLOYMENT` | Word 品質檢查或修正使用的部署名稱。 |

## OCR / 版面服務

| 參數 | 功能 |
| --- | --- |
| `TRITON_URL` | 表格辨識或 OCR 相關外部服務 endpoint。 |
| `PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY` | PDF 原版面翻譯是否啟用 translation memory。 |

## 啟動暖機

| 參數 | 功能 |
| --- | --- |
| `STARTUP_WARMUP_ENABLED` | 是否啟用啟動暖機。 |
| `STARTUP_WARMUP_BLOCKING` | 是否讓 web/worker 啟動時等待暖機完成。 |
| `STARTUP_WARMUP_BGE` | 是否暖機 BGE 相關模型或服務。 |
| `STARTUP_WARMUP_TRITON` | 是否暖機 Triton / OCR 服務。 |
| `STARTUP_WARMUP_OPENAI_CLIENTS` | 是否初始化 OpenAI client。 |
| `STARTUP_WARMUP_TIMEOUT_SECONDS` | 暖機逾時秒數。 |

## Worker 併發與輪詢

| 參數 | 功能 |
| --- | --- |
| `WORKER_POLL_SECONDS` | worker 查詢待處理任務的輪詢間隔秒數。 |
| `WORKER_OCR_MAX_RUNNING` | OCR 類任務同時執行上限。 |
| `WORKER_PDF_TRANSLATE_MAX_RUNNING` | PDF 翻譯任務同時執行上限。 |
| `WORKER_DOC_MAX_RUNNING` | 文件重建 / doc workspace 任務同時執行上限。 |
| `WORKER_WORD_MAX_RUNNING` | Word 翻譯任務同時執行上限。 |

## 應用程式 Log

| 參數 | 功能 |
| --- | --- |
| `APP_LOG_DIR` | app log 檔案輸出目錄。 |
| `APP_LOG_LEVEL` | log level，例如 `INFO`、`WARNING`、`ERROR`。 |
| `APP_LOG_TO_FILE` | 是否寫入檔案 log。 |
| `APP_LOG_STDOUT` | 是否輸出到 stdout，方便 systemd journal 收集。 |
| `APP_LOG_MAX_MB` | 單一 log 檔輪替大小，單位是 MB。 |
| `APP_LOG_BACKUP_COUNT` | 保留的輪替 log 檔數量。 |

## 系統錯誤與稽核清理

| 參數 | 功能 |
| --- | --- |
| `SYSTEM_ERROR_DB_MIN_LEVEL` | 寫入 `system_error_logs` 資料表的最低 level。設為 `ERROR` 時只記錄 error 以上。 |
| `CLEANUP_ON_CALENDAR` | systemd timer 的清理排程，格式使用 systemd `OnCalendar`。 |
| `AUDIT_LOG_RETENTION_DAYS` | `audit_logs` 保留天數，清理排程會刪除更舊資料。 |
| `SYSTEM_ERROR_LOG_RETENTION_DAYS` | `system_error_logs` 保留天數，清理排程會刪除更舊資料。 |

## 模板備份

| 參數 | 功能 |
| --- | --- |
| `TEMPLATE_BACKUP_ON_CALENDAR` | 模板備份 systemd timer 的排程，格式使用 systemd `OnCalendar`。 |
| `TEMPLATE_BACKUP_ROOT` | 模板備份檔輸出目錄。 |
| `TEMPLATE_BACKUP_RETENTION_DAYS` | 模板備份保留天數，備份腳本會刪除更舊的 `.tar.gz` 與 `.sha256`。 |

## Calendar 排程格式

`CLEANUP_ON_CALENDAR` 與 `TEMPLATE_BACKUP_ON_CALENDAR` 都會被 render 到 systemd timer 的 `OnCalendar=`。

常用範例：

| 設定值 | 說明 |
| --- | --- |
| `*-*-* 02:30:00` | 每天 02:30 執行。 |
| `*-*-* 03:30:00` | 每天 03:30 執行。 |
| `Mon..Fri 03:00:00` | 週一到週五 03:00 執行。 |
| `Sun *-*-* 02:00:00` | 每週日 02:00 執行。 |
| `*-*-01 02:00:00` | 每月 1 號 02:00 執行。 |
| `hourly` | 每小時執行。 |
| `daily` | 每天執行一次，時間由 systemd 決定。 |

修改排程後要重新 render 並 restart timer：

```bash
bash deploy.sh
systemctl cat uo_regulations_translate_log_cleanup.timer
systemctl cat uo_regulations_translate_template_backup.timer
systemctl list-timers | grep uo_regulations_translate
```

## 補充

- `APP_ENV=production` 且 `AUTO_SCHEMA_MANAGEMENT=0` 時，啟動 app 不會自動建立新表，應由 `alembic upgrade head` 或 `scripts/init_sqlserver_schema.sql` 管理 schema。
- `OWNER_ACCESS_ENABLED=1` 目前仍會隔離一般 job，但模板已調整為全域列表與全域編輯。
- 測試請使用 `TEST_DATABASE_SCHEMA` 指向獨立 schema，例如 `translation_test`，避免清到正式 schema。
- 模板備份會匯出 `document_templates` DB 內容，並打包 `out/templates/jobs` 內的模板來源檔案。
- 若要修改 log 清理或模板備份 timer 時間，請改 `.env` 內的 `CLEANUP_ON_CALENDAR` / `TEMPLATE_BACKUP_ON_CALENDAR`，再執行 `bash deploy.sh`。`scripts/install_systemd_units.sh` 內的預設值只有在沒有由 deploy 傳入參數時才會使用。
