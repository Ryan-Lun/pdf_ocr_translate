# 系統環境說明

本文說明翻譯系統執行所需的作業系統、Python 環境、第三方軟體、環境變數、資料庫與路徑設定。實際部署流程請參考 [SYSTEM_DEPLOYMENT.md](./SYSTEM_DEPLOYMENT.md)。

## 1. 系統執行環境

| 項目 | 說明 |
| --- | --- |
| 作業系統 | Ubuntu 24.04.3 |
| Python 版本 | `>=3.10,<3.12` |
| 套件管理 | uv、pyproject.toml、uv.lock |
| Web Server | Nginx |
| WSGI Server | Gunicorn |
| Web Framework | Flask |
| 背景任務 | `worker.py` 常駐 worker |
| 資料庫 | Microsoft SQL Server |
| 資料庫連線方式 | SQLAlchemy + pyodbc |
| 服務管理 | systemd |
| Gunicorn Socket | `/home/NE025/pdf_ocr_translate/uo_regulations_translate.sock` |
| 環境變數檔案 | `/home/NE025/pdf_ocr_translate/.env` |

## 2. Python 套件

本專案以 `pyproject.toml` 宣告依賴，並以 `uv.lock` 固定部署版本。主要 Python 套件如下：

- `Flask`：Web 應用程式、登入與 session 管理。
- `Gunicorn`：WSGI Server，用於正式環境啟動 Flask App。
- `SQLAlchemy`：ORM 與資料庫操作。
- `pyodbc`：MSSQL ODBC 連線。
- `python-dotenv`：載入 `.env` 環境變數。
- `openai`：OpenAI / Azure OpenAI API 呼叫。
- `pymupdf`、`pikepdf`、`pdfplumber`、`pdf2image`、`pdftext`：PDF 解析、轉換與版面處理。
- `python-docx`：Word 文件產生與處理。
- `paddlex`、`chandra-ocr`、`img2table`、`opencv-contrib-python`：OCR、版面、表格與影像處理。
- `sentence-transformers`、`torch`、`torchvision`、`torchaudio`：語意向量、模型推論與相關暖機流程。
- `jieba`、`spacy`：文字處理與斷詞。

## 3. 第三方軟體

系統需安裝下列第三方軟體或系統套件。

| 軟體 | 用途 | 檢查指令 |
| --- | --- | --- |
| Nginx | HTTP 入口、靜態檔案服務、反向代理至 Gunicorn Unix Socket。 | `nginx -v`、`sudo nginx -t` |
| uv | 建立與同步 Python 虛擬環境。 | `uv --version` |
| Microsoft ODBC Driver 18 for SQL Server | 提供 pyodbc 連線 MSSQL 所需 driver。 | `odbcinst -q -d \| grep "ODBC Driver 18 for SQL Server"` |
| sqlcmd / mssql-tools18 | 首次 schema 建立、資料庫連線檢查或維運查詢。 | `which sqlcmd`、`sqlcmd -?` |
| unixodbc / unixodbc-dev | 提供 ODBC runtime、開發元件與 `libodbc.so.2`。 | `ldconfig -p \| grep libodbc.so.2` |
| Poppler | `pdf2image` 轉圖時可能需要 `pdftoppm` / `pdfinfo`。 | `pdftoppm -v`、`pdfinfo -v` |
| 字體套件 | PDF / Word 輸出與預覽時顯示中文。 | `fc-match "Noto Sans CJK TC"` |

## 4. 本機目錄與權限

首次部署前建議建立或確認下列目錄：

```bash
mkdir -p /home/NE025/pdf_ocr_translate/out
mkdir -p /home/NE025/pdf_ocr_translate/out/jobs
mkdir -p /home/NE025/pdf_ocr_translate/out/pdf_overlay
mkdir -p /home/NE025/pdf_ocr_translate/out/pdf_rebuild
mkdir -p /home/NE025/pdf_ocr_translate/out/word_overlay
mkdir -p /home/NE025/pdf_ocr_translate/out/templates/jobs
mkdir -p /home/NE025/pdf_ocr_translate/out/uploads
mkdir -p /home/NE025/pdf_ocr_translate/out/doc_workspace
mkdir -p /home/NE025/pdf_ocr_translate/logs
mkdir -p /home/NE025/pdf_ocr_translate/backups/templates
```

若服務使用者或群組有調整，需同步確認 owner 與 group：

```bash
sudo chown -R NE025:www-data /home/NE025/pdf_ocr_translate/out
sudo chown -R NE025:www-data /home/NE025/pdf_ocr_translate/logs
sudo chown -R NE025:www-data /home/NE025/pdf_ocr_translate/backups
```

常用檢查：

```bash
test -d /home/NE025/pdf_ocr_translate && echo "APP_ROOT ok"
test -w /home/NE025/pdf_ocr_translate/out && echo "out writable"
test -w /home/NE025/pdf_ocr_translate/logs && echo "logs writable"
test -w /home/NE025/pdf_ocr_translate/backups/templates && echo "template backup writable"
```

## 5. 環境變數設定原則

系統設定與機敏資料透過 `.env` 注入，檔案位置預設為 `/home/NE025/pdf_ocr_translate/.env`。機密值例如密碼、API key、資料庫連線字串不應寫入文件或提交到 Git。

`.env` 檔案應限制讀取權限：

```bash
chmod 600 /home/NE025/pdf_ocr_translate/.env
```

調整 `.env` 後，需重啟相關 systemd 服務：

```bash
sudo systemctl restart uo_regulations_translate
sudo systemctl restart uo_regulations_translate_worker
```

若修改 timer 排程，需重新 render systemd units：

```bash
bash deploy.sh
systemctl list-timers | grep uo_regulations_translate
```

本文環境變數表格中的「必要性」分為：

| 必要性 | 意義 |
| --- | --- |
| 必填 | 缺少後會造成系統無法部署、無法啟動，或核心功能不可用。 |
| 正式環境建議 | 程式有預設值，但正式環境建議明確設定，避免預設行為不符合部署情境。 |
| 選填 | 有合理預設值，通常不用放進 `.env`。 |
| 進階調校 | 只有要調整效能、速率限制、路徑或特殊流程時才設定。 |

正式環境最小必要設定範例：

```env
APP_ENV=production
AUTO_SCHEMA_MANAGEMENT=0
DATABASE_SCHEMA=translation
DATABASE_URL='mssql+pyodbc://user:password@host/database?driver=ODBC Driver 18 for SQL Server&TrustServerCertificate=yes'

AUTH_ENABLED=1
AUTH_STUB_ENABLED=0
AUTHZ_MODE=ad_all_users
SECRET_KEY=replace-with-strong-secret

OPENAI_API_KEY=replace-with-api-key
OPENAI_BASE_URL=https://your-azure-openai-endpoint
BATCH_TRANSLATE_DEPLOYMENT=your-batch-deployment
DOC_TRANSLATE_DEPLOYMENT=your-doc-deployment
WORD_TRANSLATE_DEPLOYMENT=your-word-deployment
WORD_QUALITY_DEPLOYMENT=your-quality-deployment
```

## 6. 必填參數

| 參數 | 必要性 | 預設值 | 功能 |
| --- | --- | --- | --- |
| `APP_ENV` | 必填 | `development` | 應用程式環境。正式部署應設為 `production`。 |
| `AUTO_SCHEMA_MANAGEMENT` | 必填 | development 為 `1`，production 為 `0` | 是否讓 app 啟動時自動建立或補齊 schema。正式環境應設 `0`。 |
| `SECRET_KEY` | 必填 | `dev-secret` | Flask session 簽章密鑰。正式環境必須設定高強度隨機值。 |
| `DATABASE_URL` | 必填 | 空字串 | SQL Server 連線字串。缺少時 `deploy.sh` 會中止。 |
| `DATABASE_SCHEMA` | 必填 | `dbo` | SQL Server schema 名稱。正式環境目前使用 `translation`。 |
| `AUTH_ENABLED` | 必填 | `0` | 是否啟用登入保護。正式環境應設 `1`。 |
| `AUTH_STUB_ENABLED` | 必填 | `1` | 是否啟用 stub 登入。正式環境應設 `0`。 |
| `AUTHZ_MODE` | 必填 | 空字串 | 登入後授權模式。目前常用 `ad_all_users`。 |
| `OPENAI_API_KEY` | 必填 | 空字串 | OpenAI / Azure OpenAI API key。也可用 `AZURE_OPENAI_API_KEY` 或 `UO_AZURE_OPENAI_API_KEY` 作為 fallback。 |
| `OPENAI_BASE_URL` | 必填 | 空字串 | OpenAI / Azure OpenAI endpoint。也可用 `AZURE_OPENAI_ENDPOINT` 或 `AZURE_OPENAI_BASE_URL` 作為 fallback。 |
| `BATCH_TRANSLATE_DEPLOYMENT` | 必填 | `batch-o3-mini` | PDF batch 翻譯使用的 deployment。正式環境應明確指定。 |
| `DOC_TRANSLATE_DEPLOYMENT` | 必填 | 空字串 | 文件翻譯使用的 deployment。正式環境必須明確指定，不會 fallback 到預設模型名稱。 |
| `WORD_TRANSLATE_DEPLOYMENT` | 必填 | `gpt-4o-mini` | Word 翻譯使用的 deployment。正式環境應明確指定。 |
| `WORD_QUALITY_DEPLOYMENT` | 必填 | `gpt-4o` | Word 品質檢查或修正使用的 deployment。正式環境應明確指定。 |

## 7. 正式環境建議明確設定

這些參數不是全部必填，但正式環境建議寫進 `.env`，讓部署行為清楚可預期。

| 參數 | 必要性 | 預設值 | 功能 |
| --- | --- | --- | --- |
| `SESSION_COOKIE_NAME` | 正式環境建議 | `pdf_ocr_translate_session` | Flask session cookie 名稱。同一 host 上有多個 Flask 服務時應使用不同名稱。 |
| `SESSION_COOKIE_SECURE` | 正式環境建議 | production config 為 `1`，state 預設為 `0` | 是否只允許 HTTPS 傳送 session cookie。若目前只用 HTTP port 81 測試，應設 `0`；HTTPS 環境應設 `1`。 |
| `OWNER_ACCESS_ENABLED` | 正式環境建議 | `1` | 是否啟用一般 job owner 隔離。 |
| `INITIAL_ADMIN_WORK_IDS` | 正式環境建議 | 空字串 | 初始管理員工號清單。`seed-bootstrap` 會依此建立或補齊 admin 角色。 |
| `LDAP_USE_SSL` | 正式環境建議 | `0` | 是否使用 LDAPS。建議與 AD 實際設定一致。 |
| `LDAP_PORT` | 正式環境建議 | `LDAP_USE_SSL=1` 時 `636`，否則 `389` | LDAP port。正式環境建議明確設定。 |
| `LDAP_HOST` | 正式環境建議 | 空字串 | LDAP 或 AD 伺服器主機。啟用 AD 登入時需設定。 |
| `LDAP_BASE_DN` | 正式環境建議 | 空字串 | 搜尋使用者的 Base DN。啟用 AD 登入時需設定。 |
| `LDAP_BIND_DN` | 正式環境建議 | 空字串 | 用於查詢 AD 的服務帳號 DN 或網域帳號。啟用 AD 登入時需設定。 |
| `LDAP_BIND_PASSWORD` | 正式環境建議 | 空字串 | `LDAP_BIND_DN` 的密碼。不可提交到 Git。 |
| `LDAP_USER_LOGIN_ATTR` | 正式環境建議 | `sAMAccountName` | 使用者登入識別欄位。 |
| `LDAP_USER_OBJECT_FILTER` | 正式環境建議 | `(&(objectClass=user)(!(objectClass=computer)))` | LDAP 使用者搜尋 filter。 |
| `LDAP_USER_SEARCH_SCOPE` | 正式環境建議 | `SUBTREE` | LDAP 搜尋範圍。 |
| `LDAP_GROUP_GATE_ENABLED` | 正式環境建議 | `0` | 是否啟用 AD 群組 gate。 |
| `ALLOWED_GROUP_DN` | 正式環境建議 | 空字串 | 啟用群組 gate 時允許登入的 AD 群組 DN。 |
| `TRITON_URL` | 正式環境建議 | 程式內建示範 URL | 表格辨識或 OCR 相關外部服務 endpoint。正式環境應明確設定。 |
| `PP_STRUCTURE_URL` | 正式環境建議 | 讀取 `TRITON_LAYOUT_URL`，再 fallback 到程式內建示範 URL | PP-Structure / layout parsing endpoint。正式環境建議使用此主參數。 |
| `APP_LOG_DIR` | 正式環境建議 | `/home/NE025/pdf_ocr_translate/logs` | app log 檔案輸出目錄。 |
| `APP_LOG_LEVEL` | 正式環境建議 | `INFO` | log level。 |
| `APP_LOG_TO_FILE` | 正式環境建議 | `1` | 是否寫入檔案 log。 |
| `APP_LOG_STDOUT` | 正式環境建議 | `1` | 是否輸出到 stdout，方便 systemd journal 收集。 |
| `CLEANUP_ON_CALENDAR` | 正式環境建議 | `deploy.sh` 預設 `*-*-* 03:30:00` | log / audit 清理 timer 排程。 |
| `TEMPLATE_BACKUP_ON_CALENDAR` | 正式環境建議 | `deploy.sh` 預設 `*-*-* 02:30:00` | 模板備份 timer 排程。 |
| `TEMPLATE_BACKUP_ROOT` | 正式環境建議 | `backups/templates` | 模板備份檔輸出目錄。 |
| `TEMPLATE_BACKUP_MAX_FILES` | 正式環境建議 | `3` | 模板備份使用輪詢保留機制，最多保留的備份 archive 數量。 |

正式環境應執行 `.venv/bin/flask --app app.py seed-bootstrap`，以建立或補齊初始管理員與必要預設資料。

## 8. 選填參數

這些參數都有預設值，通常不用放進 `.env`；只有需要覆寫預設行為時才設定。

| 參數 | 必要性 | 預設值 | 功能 |
| --- | --- | --- | --- |
| `FLASK_ENV` | 選填 | 無 | `APP_ENV` 未設定時的備用來源。不建議正式環境依賴。 |
| `ALEMBIC_DATABASE_URL` | 選填 | `DATABASE_URL` | Alembic migration 使用的資料庫連線。 |
| `ALEMBIC_CONFIG_NAME` | 選填 | `production` | `deploy.sh` 使用的 Alembic 設定名稱。 |
| `AUTH_REQUIRE_LOCAL_USER` | 選填 | `0` | 是否要求使用者必須已存在本機 `users` 表才可登入。 |
| `LDAP_USER_DISPLAY_ATTR` | 選填 | `displayName` | AD 顯示名稱欄位。 |
| `LDAP_USER_EMAIL_ATTR` | 選填 | `mail` | AD Email 欄位。 |
| `PDF_REALTIME_TRANSLATE_DEPLOYMENT` | 選填 | `DOC_TRANSLATE_DEPLOYMENT`，再 fallback 到 `DOC_TRANSLATE_MODEL`，最後為空字串 | PDF 即時翻譯使用的 deployment。若與文件翻譯共用模型可不設定；未設定文件翻譯 deployment 時不會 fallback 到預設模型名稱。 |
| `AZURE_OPENAI_TIMEOUT_SECONDS` | 選填 | `OPENAI_TIMEOUT_SECONDS`，再 fallback 到 `120` | OpenAI / Azure OpenAI 請求逾時秒數，影響 PDF 即時翻譯、PDF 翻譯重建、Word 翻譯與其他 OpenAI client。錯誤訊息中的 `(read timeout=...s)` 會依此值顯示。 |
| `OPENAI_TIMEOUT_SECONDS` | 選填 | `120` | OpenAI 請求逾時秒數 fallback。 |
| `AZURE_OPENAI_API_KEY_ENV` | 選填 | `OPENAI_API_KEY` | 指定程式讀取哪個環境變數作為 Azure API key。 |
| `AZURE_BATCH_POLL_SECONDS` | 選填 | `60` | Azure batch job 輪詢間隔秒數。 |
| `AZURE_BATCH_COMPLETION_WINDOW` | 選填 | `24h` | Azure batch completion window。 |
| `DOC_TRANSLATE_MAX_CHARS` | 選填 | `4000` | 文件翻譯單次處理最大字元數。 |
| `DOC_TRANSLATE_USE_AZURE` | 選填 | `0` | 文件翻譯是否使用 Azure 流程。 |
| `PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY` | 選填 | `0` | PDF 原版面翻譯是否啟用 translation memory。 |
| `TABLE_RECOGNTION_V2TIMEOUT_SECONDS` | 選填 | `OCR_API_TIMEOUT_SECONDS`，再 fallback 到 `120` | TABLE RECOGNTION V2 / PDF 原版面 OCR 表格辨識 API 請求逾時秒數。 |
| `OCR_API_TIMEOUT_SECONDS` | 選填 | `120` | OCR API 逾時秒數 fallback。 |
| `PP_STRUCTURE_TIMEOUT_SECONDS` | 選填 | `300` | PP-Structure / PDF 翻譯重建版面解析 API 請求逾時秒數。 |
| `OCR_MIN_LINE_SCORE` | 選填 | `0.8` | OCR 行文字最低信心分數。 |
| `STARTUP_WARMUP_ENABLED` | 選填 | `1` | 是否啟用啟動暖機。 |
| `STARTUP_WARMUP_BLOCKING` | 選填 | `1` | 是否讓 Web / Worker 啟動時等待暖機完成。 |
| `STARTUP_WARMUP_BGE` | 選填 | `1` | 是否暖機 BGE / sentence-transformers 相關模型。 |
| `STARTUP_WARMUP_TRITON` | 選填 | `0` | 是否暖機 Triton / OCR 服務。 |
| `STARTUP_WARMUP_OPENAI_CLIENTS` | 選填 | `1` | 是否初始化 OpenAI client。 |
| `STARTUP_WARMUP_TIMEOUT_SECONDS` | 選填 | `30` | 暖機逾時秒數。 |
| `APP_LOG_MAX_MB` | 選填 | `10` | 單一 log 檔輪替大小，單位 MB。 |
| `APP_LOG_BACKUP_COUNT` | 選填 | `10` | 保留的輪替 log 檔數量。 |
| `SYSTEM_ERROR_DB_MIN_LEVEL` | 選填 | `ERROR` | 寫入 `system_error_logs` 資料表的最低 level。 |
| `AUDIT_LOG_RETENTION_DAYS` | 選填 | `180` | `audit_logs` 保留天數。 |
| `SYSTEM_ERROR_LOG_RETENTION_DAYS` | 選填 | `180` | `system_error_logs` 保留天數。 |
| `TRANSLATION_MEMORY_PATH` | 選填 | `out/translation_memory.json` | 翻譯記憶儲存檔。 |
| `TRANSLATION_MEMORY_TTL_DAYS` | 選填 | `7` | 翻譯記憶保留天數。 |
| `GLOSSARY_INSPECTION_PATH` | 選填 | `glossary/inspection_terminology.json` | 稽核 / 檢驗相關詞彙表。 |
| `GLOSSARY_PROCESS_PATH` | 選填 | `glossary/process_terminology.json` | 流程相關詞彙表。 |
| `GLOBAL_GLOSSARY_PATH` | 選填 | `glossary/global_glossary.json` | 全域詞彙表。 |
| `SYSTEM_GLOSSARY_PATH` | 選填 | `glossary/system_glossary.json` | 系統詞彙表。 |
| `DOCUMENT_TEMPLATES_PATH` | 選填 | `out/templates/document_templates.json` | 文件模板 JSON 備用路徑。 |

## 9. 進階調校參數

這些參數用於效能、併發與速率限制調整。除非已觀察到瓶頸、API 限流或特定任務排程需求，否則可沿用預設值。

| 參數 | 必要性 | 預設值 | 功能 |
| --- | --- | --- | --- |
| `WORKER_POLL_SECONDS` | 進階調校 | `3` | Worker 查詢待處理任務的輪詢間隔秒數。 |
| `WORKER_ID` | 進階調校 | `<COMPUTERNAME 或 worker>-<pid>` | Worker 識別字。 |
| `WORKER_OCR_MAX_RUNNING` | 進階調校 | `1` | OCR 類任務同時執行上限。 |
| `WORKER_PDF_TRANSLATE_MAX_RUNNING` | 進階調校 | `1` | PDF 翻譯任務同時執行上限。 |
| `WORKER_DOC_MAX_RUNNING` | 進階調校 | `1` | 文件重建 / doc workspace 任務同時執行上限。 |
| `WORKER_WORD_MAX_RUNNING` | 進階調校 | `1` | Word 翻譯任務同時執行上限。 |
| `PDF_REALTIME_JOB_CONCURRENCY` | 進階調校 | `4` | 單一 PDF 即時翻譯 job 內部併發。 |
| `PDF_REALTIME_GLOBAL_CONCURRENCY` | 進階調校 | `8` | PDF 即時翻譯全域併發。 |
| `PDF_REALTIME_RPM_LIMIT` | 進階調校 | `300` | PDF 即時翻譯每分鐘請求限制。 |
| `PDF_REALTIME_MAX_SEGMENTS_PER_REQUEST` | 進階調校 | `30` | PDF 即時翻譯單次請求最大段落數。 |
| `PDF_REALTIME_MAX_CHARS_PER_REQUEST` | 進階調校 | `8000` | PDF 即時翻譯單次請求最大字元數。 |
| `PDF_REALTIME_RATE_LIMIT_RPM` | 進階調校 | `2500` | PDF 即時翻譯 OpenAI rate limit RPM。 |
| `PDF_REALTIME_RATE_LIMIT_TPM` | 進階調校 | `250000` | PDF 即時翻譯 OpenAI rate limit TPM。 |
| `PDF_REALTIME_RATE_LIMIT_HEADROOM` | 進階調校 | `0.8` | PDF 即時翻譯 rate limit 保留比例。 |
| `DEFAULT_OPENAI_RATE_LIMIT_RPM` | 進階調校 | `300` | 一般 OpenAI 呼叫 RPM。 |
| `DEFAULT_OPENAI_RATE_LIMIT_TPM` | 進階調校 | `120000` | 一般 OpenAI 呼叫 TPM。 |
| `DEFAULT_OPENAI_RATE_LIMIT_HEADROOM` | 進階調校 | `0.8` | 一般 OpenAI rate limit 保留比例。 |
| `USER_SUBMISSIONS_PER_MINUTE` | 進階調校 | `10` | 單一使用者每分鐘提交任務限制。 |
| `REALTIME_COMPLETION_TOKEN_BUDGET` | 進階調校 | `4000` | 即時翻譯 completion token 預算。 |

## 10. Prompt 類參數

這些參數可覆寫程式內建 prompt。一般部署不需要設定；只有需要更改翻譯策略時才放進 `.env`。

| 參數 | 必要性 | 預設值 | 功能 |
| --- | --- | --- | --- |
| `AZURE_BATCH_SYSTEM_PROMPT` | 選填 | 程式內建醫材法規翻譯 prompt | PDF batch 翻譯 system prompt。 |
| `DOC_TRANSLATE_SYSTEM_PROMPT` | 選填 | 程式內建 HTML 文件翻譯 prompt | 文件翻譯 system prompt。 |

## 11. Calendar 排程格式

`CLEANUP_ON_CALENDAR` 與 `TEMPLATE_BACKUP_ON_CALENDAR` 會被 render 到 systemd timer 的 `OnCalendar=`。

| 設定值 | 說明 |
| --- | --- |
| `*-*-* 02:30:00` | 每天 02:30 執行。 |
| `*-*-* 03:30:00` | 每天 03:30 執行。 |
| `Mon..Fri 03:00:00` | 週一到週五 03:00 執行。 |
| `Sun *-*-* 02:00:00` | 每週日 02:00 執行。 |
| `*-*-01 02:00:00` | 每月 1 號 02:00 執行。 |
| `hourly` | 每小時執行。 |
| `daily` | 每天執行一次，時間由 systemd 決定。 |


模板備份採輪詢保留機制：預設最多保留最新 3 份 `.tar.gz` 備份 archive，超過數量時會刪除較舊的 archive 與對應 `.sha256`。

修改排程後要重新 render 並 restart timer：

```bash
bash deploy.sh
systemctl cat uo_regulations_translate_log_cleanup.timer
systemctl cat uo_regulations_translate_template_backup.timer
systemctl list-timers | grep uo_regulations_translate
```
