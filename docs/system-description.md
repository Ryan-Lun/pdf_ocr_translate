# 1. 系統架構設計

## 主要依據檔案

- `SYSTEM_DEPLOYMENT.md`
- `ENVIRONMENT.md`
- `app/__init__.py`
- `app/blueprints/__init__.py`
- `app/config.py`
- `app/services/worker.py`
- `app/services/pipeline.py`
- `app/services/batch.py`
- `app/services/realtime_translate.py`
- `app/services/doc_workspace.py`
- `app/services/word_translate.py`
- `ocr_pipeline/*`

## 架構概述

本系統為 Flask 架構之文件 OCR 與翻譯工作站，主要提供 PDF 原版面 OCR 與翻譯、PDF 重建翻譯、Word 文件翻譯、翻譯結果人工校訂、詞彙庫與文件模板管理。系統以伺服器端渲染頁面作為主要操作介面，並透過 JSON API 支援編輯器、工作狀態輪詢、詞彙庫匯入匯出、模板套用與批次下載。

正式部署採用 Nginx、Gunicorn、Flask App、背景 Worker 與 Microsoft SQL Server 分層架構。使用者透過瀏覽器連線至 Nginx，Nginx 提供 `static/` 靜態資源並將動態請求轉發至 Gunicorn Unix Socket。背景 Worker 由 `worker.py` 常駐執行，處理 OCR、翻譯、文件重建與 Word 翻譯等耗時工作。

## 主要組成

| 層級 | 組成 | 說明 |
|---|---|---|
| Web 層 | `app/__init__.py`、`app/blueprints/*` | 建立 Flask App、註冊 Blueprint、處理登入保護、錯誤頁與頁面/API 路由。 |
| 前端層 | `app/templates/*`、`app/blueprints/*/templates/*`、`static/*` | 提供首頁、PDF 工作區、Word 工作區、編輯器、詞彙庫、模板與管理頁面。 |
| 服務層 | `app/services/*` | 封裝 OCR、翻譯、工作狀態、文件模板、詞彙庫、權限、稽核與系統設定邏輯。 |
| OCR/文件處理層 | `ocr_pipeline/*`、`app/services/ocr.py`、`app/services/docx_export.py` | 執行 OCR 結果合併、段落對齊、表格處理、PDF/Word 輸出與 DOCX 匯出。 |
| 背景工作層 | `worker.py`、`app/services/worker.py`、`app/services/job_store.py` | 從資料庫 claim queued job，依 job type 執行處理並更新狀態。 |
| 資料層 | `scripts/init_sqlserver_schema.sql`、`migrations/`、`app/services/job_store.py` | 使用 SQL Server 保存使用者、角色、工作、事件、稽核、錯誤與文件模板。 |
| 檔案儲存 | `out/`、`logs/`、`backups/templates/` | 保存上傳檔、job 輸出、模板來源檔、翻譯記憶、log 與模板備份。 |

## 資料流與處理流程

主要資料流為：使用者在工作區上傳 PDF 或 Word 文件，系統建立 job 目錄與 `jobs` 資料表紀錄，背景 Worker 取得待處理 job 後執行 OCR、翻譯、文件重建或 Word 翻譯。處理過程中系統更新 `status`、`stage`、`progress`、`job_events` 與輸出檔，前端透過 API 或事件串流查詢狀態。工作完成後，使用者可進入編輯器校訂、套用詞彙規則、重新翻譯區塊、下載翻譯文件或批次下載結果。

依程式碼推測，PDF 原版面翻譯支援 batch 與 realtime 兩種翻譯模式；batch 模式由 `app/services/batch.py` 處理 Azure/OpenAI batch 輪詢，realtime 模式由 `app/services/realtime_translate.py` 直接分段翻譯。PDF 重建翻譯與 Word 翻譯則分別由 `doc_workspace.py` 與 `word_translate.py` 建立輸出文件。

## Blueprint 與主要路由群組

| Blueprint | URL 範圍 | 主要責任 |
|---|---|---|
| `auth_bp` | `/auth/login`、`/auth/logout` | 使用者登入、登出與登入稽核。 |
| `admin_bp` | `/admin/*` | 使用者管理、稽核紀錄與系統錯誤紀錄。 |
| `main_bp` | `/`、`/workspace/*`、`/upload*` | 首頁、工作區頁面與檔案上傳入口。 |
| `editor_bp` | `/editor/job/*`、`/editor/template/job/*` | OCR/翻譯結果編輯器與模板來源編輯器。 |
| `api_bp` | `/api/*` | job 查詢、翻譯操作、詞彙庫、模板、批次下載、狀態串流與取消/重試。 |
| `jobs_bp` | `/jobs/<job_id>/<path:filename>` | job 產物檔案下載與權限檢查。 |

## 執行時序

1. `create_app()` 載入設定、初始化 log、資料庫、認證、Blueprint、錯誤頁與 CLI。
2. 使用者請求受登入 hook 檢查；未登入且 `AUTH_ENABLED=True` 時導向 `/auth/login`。
3. 使用者在工作區上傳檔案後，系統建立 job 資料列與本機 job 目錄。
4. `worker.py` 呼叫 `run_worker_loop()`，依併發限制取得 queued job。
5. Worker 依 `job_type` 執行 `ocr_overlay`、`template_source`、`doc_workspace` 或 `word_translate`。
6. 前端透過 `/api/jobs/stream`、`/api/doc-jobs/stream`、`/api/word-jobs/stream` 或 job 查詢 API 更新畫面。
7. 使用者下載輸出檔，或進入編輯器進行人工校訂與局部重翻。

## 待補充項目

- 此處需補充正式部署環境中的實際主機、網域、Port 與防火牆設定。
- 此處需補充論文或交付文件需要的系統架構圖。

# 2. 系統環境與部署架構

## 主要依據檔案

- `ENVIRONMENT.md`
- `SYSTEM_DEPLOYMENT.md`
- `OPERATIONS.md`
- `deploy.sh`
- `deploy/nginx-site.conf.template`
- `scripts/install_systemd_units.sh`
- `scripts/install_nginx_site.sh`
- `pyproject.toml`

## 系統執行環境

| 項目 | 說明 |
|---|---|
| 作業系統 | Ubuntu 24.04.3 |
| Python 版本 | `>=3.10,<3.12` |
| 套件管理 | `uv`、`pyproject.toml`、`uv.lock` |
| Web Server | Nginx |
| WSGI Server | Gunicorn |
| Web Framework | Flask |
| 背景任務 | `worker.py` 常駐 worker |
| 資料庫 | Microsoft SQL Server |
| 資料庫連線方式 | SQLAlchemy + pyodbc |
| 服務管理 | systemd |
| Gunicorn Socket | `/home/NE025/pdf_ocr_translate/uo_regulations_translate.sock` |
| 環境變數檔案 | `/home/NE025/pdf_ocr_translate/.env` |

## 部署架構

```text
使用者瀏覽器
    |
    v
Nginx
    |-- /static/ -> static/
    |
    v
Gunicorn Unix Socket
    |
    v
Flask App
    |-- SQLAlchemy / pyodbc -> MSSQL
    |-- OpenAI / Azure OpenAI -> 翻譯模型
    |-- Triton / PP-Structure -> OCR 或版面服務
    |-- out/ -> 上傳、任務、輸出、模板與翻譯記憶
    |-- logs/ -> 應用程式 log

systemd
    |-- uo_regulations_translate.service
    |-- uo_regulations_translate_worker.service
    |-- uo_regulations_translate_log_cleanup.timer
    |-- uo_regulations_translate_template_backup.timer
```

## 必要外部服務與軟體

| 軟體或服務 | 用途 | 備註 |
|---|---|---|
| Microsoft SQL Server | 保存 job、使用者、角色、稽核、錯誤與模板資料 | 正式環境需設定 `DATABASE_URL`。 |
| OpenAI / Azure OpenAI | 執行 PDF、文件與 Word 翻譯 | 需設定 API key、base URL 與 deployment。 |
| Nginx | HTTP 入口、靜態檔與反向代理 | 預設 listen port 依部署參數設定。 |
| Gunicorn | WSGI 應用程式服務 | 預設以 Unix Socket 對接 Nginx。 |
| Microsoft ODBC Driver 18 | pyodbc 連線 SQL Server | 正式部署必要。 |
| Poppler | PDF 轉圖與解析輔助 | `pdf2image` 相關流程可能使用。 |
| Triton / PP-Structure | OCR、表格或版面解析外部服務 | 依 `.env` 設定 endpoint。 |

## 主要環境變數

| 參數 | 用途 | 正式環境注意事項 |
|---|---|---|
| `APP_ENV` | 應用環境 | 正式環境設為 `production`。 |
| `AUTO_SCHEMA_MANAGEMENT` | 是否由 app 啟動時自動建表或補欄位 | production 預設為 `0`。 |
| `SECRET_KEY` | Flask session 簽章 | 正式環境必須使用高強度隨機值。 |
| `DATABASE_URL` | SQL Server 連線字串 | 缺少時正式部署不可用。 |
| `DATABASE_SCHEMA` | SQL Server schema | 現有文件建議使用 `translation`。 |
| `AUTH_ENABLED` | 是否啟用登入保護 | 正式環境應設為 `1`。 |
| `AUTH_STUB_ENABLED` | 是否啟用 stub 登入 | 正式環境應設為 `0`。 |
| `AUTHZ_MODE` | 授權模式 | 常用值為 `ad_all_users`。 |
| `OPENAI_API_KEY` | OpenAI / Azure OpenAI API key | 不得提交至 Git。 |
| `OPENAI_BASE_URL` | OpenAI / Azure OpenAI endpoint | 正式環境需明確設定。 |
| `DOC_TRANSLATE_DEPLOYMENT` | 文件翻譯 deployment | 正式環境需明確設定。 |
| `WORD_TRANSLATE_DEPLOYMENT` | Word 翻譯 deployment | 正式環境需明確設定。 |
| `WORKER_*_MAX_RUNNING` | Worker 各類任務併發上限 | 依機器資源與 API 限制調整。 |

## 部署流程摘要

1. 確認 `.env` 包含資料庫、OpenAI/Azure、LDAP/AD 與 session 必要設定。
2. 使用 `uv sync --frozen` 同步 Python 虛擬環境。
3. 執行 Alembic migration，例如 `alembic upgrade head`。
4. 執行 `flask --app app.py schema-preflight` 檢查必要資料表與欄位。
5. 執行 `flask --app app.py seed-bootstrap` 初始化角色與初始管理員。
6. 使用 `bash deploy.sh` 安裝或更新 systemd unit、Nginx site 並重啟服務。
7. 透過 `systemctl status`、`journalctl` 與瀏覽器頁面確認服務狀態。

## 待補充項目

- 此處需補充正式機器 CPU、記憶體、磁碟空間與 GPU/推論資源需求。
- 此處需補充正式憑證、HTTPS 與網路存取限制。

# 3. 權限控管說明

## 主要依據檔案

- `app/blueprints/auth/routes.py`
- `app/blueprints/admin/routes.py`
- `app/services/auth_service.py`
- `app/services/authz_service.py`
- `app/services/auth_policy.py`
- `app/services/auth_store.py`
- `app/services/auth_hooks_service.py`
- `scripts/init_sqlserver_schema.sql`

## 登入與授權概述

系統可透過 `AUTH_ENABLED` 啟用登入保護。當登入保護啟用時，除登入、登出與靜態資源外，系統頁面與 API 需由已登入使用者存取。登入流程支援 stub 模式與 LDAP/AD 驗證模式；正式環境依既有環境文件建議關閉 stub 登入。

登入成功後，系統會建立 Flask-Login session，並將使用者工號、顯示名稱、角色、Email 與 DN 等資訊保存於登入使用者物件。登入、登出與登入失敗會寫入稽核紀錄。

## 使用者角色

| 角色 | 可使用功能 | 權限限制 | 備註 |
|---|---|---|---|
| `editor` | 使用翻譯工作區、上傳文件、查詢與編輯本人可存取 job、下載輸出、使用詞彙與模板功能 | 無法進入管理後台；若 `OWNER_ACCESS_ENABLED=True`，一般 job 受 owner 隔離限制 | 預設一般角色。 |
| `admin` | 具備 editor 功能，並可進入管理後台管理使用者、角色、稽核紀錄與系統錯誤紀錄 | 仍需通過登入驗證 | `is_admin` 或有效角色包含 `admin` 時成立。 |

## 授權模式

| 設定 | 說明 |
|---|---|
| `AUTH_STUB_ENABLED=True` | 使用表單輸入的工號或名稱建立 stub 使用者，主要供開發或測試使用。 |
| `AUTH_STUB_ENABLED=False` | 使用 LDAP/AD 驗證帳號與密碼。 |
| `AUTHZ_MODE=ad_all_users` | 依程式碼與文件，常用於 AD 使用者登入後同步本機使用者資料。 |
| `AUTH_REQUIRE_LOCAL_USER` | 可要求使用者必須已存在本機 `users` 表才可登入。 |
| `LDAP_GROUP_GATE_ENABLED` / `ALLOWED_GROUP_DN` | 可限制只有指定 AD 群組成員能登入。 |
| `OWNER_ACCESS_ENABLED` | 啟用一般 job owner 隔離；admin 不受此限制。 |

## 管理後台

管理後台路徑為 `/admin/*`，進入前由 `admin_bp.before_request` 檢查目前使用者是否為 admin。管理功能包含：

| 功能 | 路徑 | 說明 |
|---|---|---|
| 使用者列表 | `/admin/users` | 查詢本機使用者、角色與啟用狀態。 |
| 新增使用者 | `/admin/users/create` | 在非 `ad_all_users` 模式下可手動新增使用者。 |
| 啟用/停用使用者 | `/admin/users/<work_id>/active` | 不允許停用自己或最後一個 active admin。 |
| 更新使用者角色 | `/admin/users/<work_id>/role` | 角色限制為 `editor` 或 `admin`；不允許移除最後一個 admin。 |
| 稽核紀錄 | `/admin/audit-logs` | 依關鍵字、動作、job、日期查詢操作紀錄。 |
| 系統錯誤紀錄 | `/admin/system-error-logs` | 依關鍵字、component、level、job、日期查詢錯誤紀錄。 |

## 登入與登出流程

1. 使用者進入 `/auth/login`。
2. 若為 stub 模式，使用者輸入工號或使用者名稱；若為 LDAP/AD 模式，使用者輸入工號與密碼。
3. 系統呼叫 `authenticate_login()` 完成身份驗證、授權檢查、本機使用者同步與角色解析。
4. 登入成功後，系統寫入 `auth_login` 稽核紀錄並導向原本的 `next` URL 或首頁。
5. 登入失敗時，系統顯示錯誤訊息並寫入 `auth_login_failed` 稽核紀錄。
6. 使用者進入 `/auth/logout` 後，系統寫入 `auth_logout` 稽核紀錄並清除 session。

## 待補充項目

- 此處需補充正式 AD 網域、允許登入群組與管理員開通流程。
- 此處需補充角色異動申請與審核程序。

# 4. 首頁與工作區導覽

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/templates/layout.html`
- `app/templates/_global_nav.html`
- `app/blueprints/main/templates/main/index.html`
- `app/blueprints/main/templates/main/overlay_workspace.html`
- `app/blueprints/main/templates/main/doc_workspace.html`
- `app/blueprints/main/templates/main/word_workspace.html`
- `app/blueprints/main/templates/main/glossary_manager.html`
- `app/blueprints/main/templates/main/overlay_templates.html`

## 導覽概述

系統首頁路徑為 `/`，主要提供各工作區入口。依路由與模板檔案確認，系統包含 PDF 原版面工作區、PDF 重建翻譯工作區、Word 翻譯工作區、詞彙管理頁面與 PDF 原版面模板頁面。全域導覽列由 `_global_nav.html` 提供。

## 主要頁面

| 頁面 | 路徑 | 說明 |
|---|---|---|
| 首頁 | `/` | 顯示主要工作區入口。 |
| PDF 原版面工作區 | `/workspace/pdf-overlay` | 上傳 PDF，執行 OCR、原版面翻譯與後續校訂。 |
| PDF 原版面模板 | `/workspace/pdf-overlay/templates` | 管理或使用 PDF 原版面模板來源。 |
| 詞彙管理 | `/workspace/glossary` | 管理全域與系統詞彙庫，支援匯入預覽與套用。 |
| PDF 重建翻譯工作區 | `/workspace/pdf-doc` | 將 PDF 轉換並翻譯為可下載文件。 |
| Word 翻譯工作區 | `/workspace/word` | 上傳 Word 文件並產生翻譯後 DOCX。 |

## 共用操作元素

| 類型 | 說明 |
|---|---|
| 上傳表單 | 由各工作區呼叫 `/upload`、`/upload-doc-workspace`、`/upload-word-workspace` 或 `/upload-template-source`。 |
| 工作列表 | 透過 `/api/jobs`、`/api/doc-jobs`、`/api/word-jobs` 或串流 API 更新。 |
| 狀態顯示 | 依 job 的 `status`、`stage` 與 `progress` 顯示處理狀態。 |
| 下載按鈕 | job 完成後由 API 或 `/jobs/<job_id>/<filename>` 提供輸出檔。 |
| 取消與重試 | 部分 job 可透過 API 取消或重試。 |

## 操作注意事項

- 若 `AUTH_ENABLED=True`，使用者需先登入才能進入工作區。
- 若 `OWNER_ACCESS_ENABLED=True`，一般使用者只能存取自己建立或有權限的 job；admin 可存取所有 job。
- 大型 PDF、OCR 與翻譯任務由背景 Worker 執行，使用者應以畫面狀態為準，不需重複提交同一檔案。

## 待補充項目

- 此處建議補充畫面截圖：首頁、PDF 原版面工作區、PDF 重建工作區、Word 工作區。

# 5. PDF 原版面 OCR 與翻譯模組說明

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/services/pipeline.py`
- `app/services/ocr.py`
- `app/services/batch.py`
- `app/services/realtime_translate.py`
- `app/services/translation_memory.py`
- `ocr_pipeline/pipeline.py`
- `ocr_pipeline/merge_logic.py`
- `ocr_pipeline/paragraph_align.py`

## 功能目的

PDF 原版面 OCR 與翻譯模組用於上傳 PDF，將頁面轉為影像、執行 OCR、合併文字框與段落，並依使用者選擇執行翻譯。完成後，使用者可在編輯器檢視原始框、翻譯框、頁面圖片與輸出結果，並進行人工修正或局部重翻。

## 操作路徑

| 操作 | 路徑 |
|---|---|
| 工作區頁面 | `/workspace/pdf-overlay` |
| PDF 上傳 | `POST /upload` |
| job 資料查詢 | `GET /api/job/<job_id>` |
| 批次翻譯 | `POST /api/job/<job_id>/batch-translate` |
| 批次狀態 | `GET /api/job/<job_id>/batch-status` |
| 還原批次輸出 | `POST /api/job/<job_id>/batch-restore` |
| 編輯器 | `/editor/job/<job_id>` |

## 操作步驟

1. 使用者進入 `/workspace/pdf-overlay`。
2. 使用者選擇 PDF 檔案，並依畫面欄位設定頁碼範圍、翻譯來源語言、目標語言、翻譯模式、文件模式與是否啟用翻譯。
3. 系統呼叫 `/upload` 建立 `ocr_overlay` job。
4. Worker 執行 OCR pipeline，更新 job 狀態為 `running`、`ocr`。
5. 若啟用翻譯，系統依設定進入 `translate` 階段，使用 batch 或 realtime 翻譯流程。
6. 處理完成後，使用者可開啟編輯器檢視結果、重新翻譯個別區塊或下載輸出。

## 欄位說明

| 欄位名稱 | 必填 | 說明 | 格式或限制 |
|---|---|---|---|
| PDF 檔案 | 是 | 上傳來源文件 | 路由驗證缺少檔案時回傳 `Missing PDF file.`。 |
| 頁碼範圍 | 否 | 限制處理頁碼 | 支援逗號與範圍格式；錯誤時回傳 `Invalid page selection.`。 |
| 來源語言 | 否 | 翻譯來源語言 | 預設 `auto`。 |
| 目標語言 | 否 | 翻譯目標語言 | 預設 `en`。 |
| 翻譯模式 | 否 | batch 或 realtime | 依程式碼推測，batch 為預設流程。 |
| 文件模式 | 否 | 表單或文件版面處理模式 | 預設 `form`。 |
| 是否啟用翻譯 | 否 | OCR 完成後是否進入翻譯 | 未啟用時僅產生 OCR 結果。 |

## 系統回應

系統建立 job 後會保存來源 PDF、job metadata 與資料庫 `jobs` 紀錄。處理中更新 `status`、`stage`、`progress`；完成後產生可供編輯、下載或後續翻譯的輸出資料。若 batch 翻譯尚未完成，系統會透過輪詢更新狀態。

## 注意事項

- 頁碼欄位格式錯誤會中止上傳。
- OCR 與翻譯可能耗時，應由背景 Worker 處理。
- 若設定使用 OpenAI/Azure OpenAI，需確認 deployment 與 API key 設定完整。
- 若啟用 translation memory，翻譯記憶會依 `TRANSLATION_MEMORY_PATH` 與 TTL 設定保存。

## 錯誤處理

| 錯誤情境 | 可能原因 | 處理方式 |
|---|---|---|
| `Missing PDF file.` | 未附上 PDF 檔 | 重新選擇檔案後提交。 |
| `Invalid page selection.` | 頁碼格式錯誤或範圍不合法 | 使用如 `1,3,5-7` 的格式。 |
| `No OCR text lines found to translate.` | OCR 未產生可翻譯文字 | 檢查 PDF 品質、頁碼與 OCR 服務。 |
| 翻譯請求連續失敗 | OpenAI/Azure API 逾時或回傳錯誤 | 使用者稍後重試；管理者檢查 API 設定與系統錯誤紀錄。 |

# 6. PDF 重建翻譯工作區說明

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/services/doc_workspace.py`
- `app/services/markdown_translate.py`
- `app/services/docx_export.py`
- `app/blueprints/main/templates/main/doc_workspace.html`

## 功能目的

PDF 重建翻譯工作區用於將 PDF 內容抽取、翻譯並輸出為文件型態結果。此流程與 PDF 原版面翻譯不同，重點在產生可下載的 DOCX 或重建後文件，而非維持 PDF 頁面中的原框位置。

## 操作路徑

| 操作 | 路徑 |
|---|---|
| 工作區頁面 | `/workspace/pdf-doc` |
| 上傳 PDF | `POST /upload-doc-workspace` |
| job 資料查詢 | `GET /api/doc-job/<job_id>` |
| job 列表 | `GET /api/doc-jobs` |
| 狀態串流 | `GET /api/doc-jobs/stream` |
| 批次下載 DOCX | `POST /api/doc-jobs/download-docx` |

## 操作步驟

1. 使用者進入 `/workspace/pdf-doc`。
2. 使用者選擇 PDF 檔案，並設定來源語言、目標語言與系統提示詞。
3. 系統呼叫 `/upload-doc-workspace` 建立 `doc_workspace` job。
4. Worker 執行抽取、HTML 或中間格式建立、翻譯與 DOCX 產出。
5. 使用者透過工作列表檢視狀態，完成後下載 DOCX。

## 處理階段

| 階段 | 說明 |
|---|---|
| `queued` | job 已建立，等待 Worker 處理。 |
| `extract` | 抽取 PDF 內容與版面資料。 |
| `html` | 依程式碼推測，建立可翻譯或預覽的 HTML/中間結果。 |
| `translate` | 呼叫翻譯模型進行文字翻譯。 |
| `docx` | 產生 DOCX 輸出。 |
| `completed` | job 完成。 |
| `failed` | job 失敗並保存錯誤訊息。 |
| `cancelled` | 使用者取消或系統中止。 |

## 欄位說明

| 欄位名稱 | 必填 | 說明 | 格式或限制 |
|---|---|---|---|
| PDF 檔案 | 是 | 來源 PDF | 缺少時回傳 `Missing PDF file.`。 |
| 來源語言 | 否 | 翻譯來源語言 | 預設 `auto`。 |
| 目標語言 | 否 | 翻譯目標語言 | 預設 `en`。 |
| 系統提示詞 | 否 | 控制翻譯風格或特殊要求 | 文字欄位。 |

## 待補充項目

- 此處需補充 PDF 重建翻譯工作區的正式畫面截圖。
- 此處需補充重建輸出格式與頁面版面保留限制的使用者說明。

# 7. Word 翻譯工作區說明

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/services/word_translate.py`
- `app/blueprints/main/templates/main/word_workspace.html`

## 功能目的

Word 翻譯工作區提供 DOCX 文件翻譯，保留可處理的段落、表格與文件結構，並輸出翻譯後 DOCX。此流程由 `word_translate` job 執行，適用於來源本身即為 Word 文件的翻譯情境。

## 操作路徑

| 操作 | 路徑 |
|---|---|
| 工作區頁面 | `/workspace/word` |
| 上傳 Word | `POST /upload-word-workspace` |
| job 列表 | `GET /api/word-jobs` |
| 狀態串流 | `GET /api/word-jobs/stream` |
| 取消 Word job | `POST /api/job/<job_id>/cancel-word` |
| 批次下載 DOCX | `POST /api/word-jobs/download-docx` |

## 操作步驟

1. 使用者進入 `/workspace/word`。
2. 使用者上傳 Word 檔案，並設定來源語言、目標語言、保留詞彙與系統提示詞。
3. 系統建立 `word_translate` job，狀態為 `queued`。
4. Worker 依序執行準備、翻譯與儲存階段。
5. 工作完成後，使用者下載翻譯後 DOCX。

## 處理階段

| 階段 | 說明 |
|---|---|
| `prepare` | 準備來源檔與處理資料。 |
| `translate` | 對文件文字進行翻譯。 |
| `save` | 保存翻譯結果與輸出 DOCX。 |
| `completed` | 工作完成。 |
| `failed` | 工作失敗。 |
| `cancelled` | 工作取消。 |

## 欄位說明

| 欄位名稱 | 必填 | 說明 | 格式或限制 |
|---|---|---|---|
| Word 檔案 | 是 | 來源 Word 文件 | 缺少時回傳 `Missing Word file.`。 |
| 來源語言 | 否 | 翻譯來源語言 | 預設 `auto`。 |
| 目標語言 | 否 | 翻譯目標語言 | 預設 `en`。 |
| 保留詞彙 | 否 | 不翻譯或需固定保留的詞彙 | 依畫面輸入格式處理。 |
| 系統提示詞 | 否 | 控制翻譯風格或特殊要求 | 文字欄位。 |

## 注意事項

- 系統處理來源檔時，非 DOCX 來源可能轉換為 `.converted.docx` 後再處理；依程式碼推測，此行為用於支援可轉換的 Word 類檔案。
- 若 OpenAI/Azure OpenAI 設定不完整，翻譯階段會失敗。

## 錯誤處理

| 錯誤情境 | 可能原因 | 處理方式 |
|---|---|---|
| `Missing Word file.` | 未上傳 Word 檔 | 重新選擇檔案後提交。 |
| job 顯示 failed | 翻譯 API、檔案讀取或輸出保存失敗 | 使用者可重試；管理者檢查 `system_error_logs` 與 app log。 |

# 8. 文件編輯器與人工校訂說明

## 主要依據檔案

- `app/blueprints/editor/routes.py`
- `app/blueprints/editor/templates/editor/editor.html`
- `app/blueprints/api/routes.py`
- `app/services/ocr.py`
- `app/services/realtime_translate.py`
- `app/services/document_terms.py`
- `app/services/translation_debug.py`

## 功能目的

文件編輯器用於檢視與校訂 PDF 原版面 OCR 與翻譯結果。使用者可調整文字框內容、套用一致性修正、套用段落術語規則、進行區域 OCR、重新翻譯單一框、多框或指定區域，並保存校訂後的 job 資料。

## 操作路徑

| 操作 | 路徑 |
|---|---|
| 一般編輯器 | `/editor/job/<job_id>` |
| 模板來源編輯器 | `/editor/template/job/<job_id>` |
| job 資料 | `GET /api/job/<job_id>` |
| 保存 job | `POST /api/job/<job_id>/save` |
| 單框重翻 | `POST /api/job/<job_id>/retranslate-box` |
| 多框重翻 | `POST /api/job/<job_id>/retranslate-boxes` |
| 區域重翻 | `POST /api/job/<job_id>/retranslate-region` |
| 區域 OCR 預覽 | `POST /api/job/<job_id>/region-ocr-preview` |
| 套用一致性 | `POST /api/job/<job_id>/apply-consistency` |
| 套用段落術語 | `POST /api/job/<job_id>/apply-paragraph-term` |
| 詞彙重翻 | `POST /api/job/<job_id>/glossary-retranslate` |

## 操作步驟

1. 使用者從 PDF 原版面工作區或 job 列表開啟編輯器。
2. 系統載入 job metadata、頁面影像、OCR box、翻譯結果與相關上下文。
3. 使用者修改文字框、選取區域或套用詞彙/一致性功能。
4. 系統透過 API 更新 job 資料，必要時重新呼叫翻譯或 OCR 服務。
5. 使用者保存結果並下載輸出。

## 編輯器權限

一般編輯器會檢查 job 是否存在、是否為允許的 job type，以及使用者是否可存取該 job。若 `OWNER_ACCESS_ENABLED=True`，非 admin 使用者只能存取自己擁有的 job。

## 常見錯誤

| 錯誤訊息 | 發生原因 | 處理方式 |
|---|---|---|
| `Forbidden.` | 使用者無權存取指定 job 或模板 | 使用正確帳號登入，或請 admin 檢查 owner。 |
| `Invalid page index.` | 指定頁碼索引不合法 | 重新選取有效頁面。 |
| `Invalid region bbox.` | 區域座標不合法 | 重新框選區域。 |
| `Missing source text.` | 指定翻譯目標缺少來源文字 | 檢查 OCR 結果或重新執行 OCR。 |
| `Translation result count mismatch.` | 翻譯回傳數量與請求不一致 | 重新翻譯；若持續發生，管理者檢查模型回應。 |

## 待補充項目

- 此處需補充編輯器主要按鈕、快捷鍵與畫面截圖。

# 9. 詞彙庫與術語管理說明

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/services/glossary.py`
- `app/services/document_terms.py`
- `static/glossary_manager.js`
- `glossary/global_glossary.json`
- `glossary/system_glossary.json`

## 功能目的

詞彙庫模組用於管理翻譯時需固定處理的術語、保留詞或標準譯法。系統包含全域詞彙庫與系統詞彙庫，並提供詞彙查詢、儲存、匯出、Excel 匯入預覽與套用功能。編輯器可依詞彙規則進行重翻或校訂。

## 操作路徑

| 操作 | 路徑 |
|---|---|
| 詞彙管理頁 | `/workspace/glossary` |
| 全域詞彙讀寫 | `GET,POST /api/glossary` |
| 詞彙庫查詢 | `GET /api/glossary/library` |
| 系統詞彙匯出 | `GET /api/glossary/system-export` |
| 系統詞彙匯入預覽 | `POST /api/glossary/system-import-preview` |
| 系統詞彙匯入套用 | `POST /api/glossary/system-import-apply` |
| 編輯器詞彙重翻 | `POST /api/job/<job_id>/glossary-retranslate` |

## 操作步驟

1. 使用者進入 `/workspace/glossary`。
2. 使用者查詢或編輯詞彙資料。
3. 若需批次匯入，使用者上傳 `.xlsx` 檔進行預覽。
4. 系統檢查檔案格式、重複詞彙列與無效列。
5. 使用者確認後套用匯入結果。
6. 使用者可在編輯器依詞彙來源詞進行局部重翻。

## 欄位與限制

| 欄位名稱 | 必填 | 說明 | 格式或限制 |
|---|---|---|---|
| 詞彙 payload | 是 | 詞彙資料 JSON | 格式錯誤時回傳 `Invalid glossary payload.`。 |
| Excel 檔 | 匯入時必填 | 系統詞彙匯入來源 | 僅支援 `.xlsx`。 |
| 來源詞 | 詞彙重翻時必填 | 用於尋找符合框的詞彙 | 缺少時回傳 `Missing glossary source term.`。 |

## 錯誤處理

| 錯誤情境 | 可能原因 | 處理方式 |
|---|---|---|
| `Missing Excel file.` | 未附上匯入檔 | 重新選擇 `.xlsx` 檔。 |
| `Only .xlsx files are supported.` | 檔案格式不符 | 轉存為 `.xlsx` 後再匯入。 |
| `請先排除重複詞彙列，再確認合併。` | 預覽發現重複列 | 修正 Excel 或在匯入介面排除。 |
| `請先排除無效列，再確認合併。` | 預覽發現無效資料 | 補齊欄位或刪除無效列。 |
| `No matching boxes found for glossary term.` | 編輯器內找不到來源詞 | 確認來源詞與 OCR 文字是否一致。 |

## 待補充項目

- 此處需補充詞彙 Excel 欄位格式範本。

# 10. 文件模板模組說明

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/services/document_templates.py`
- `TEMPLATE_BACKUP_RESTORE.md`
- `app/blueprints/main/templates/main/overlay_templates.html`
- `app/blueprints/main/templates/main/template_editor.html`

## 功能目的

文件模板模組用於保存 PDF 原版面處理所需的模板資料。使用者可上傳模板來源 PDF，透過模板來源編輯器建立或保存模板，並在目標 job 上套用模板設定。模板 metadata 儲存於 `document_templates` 資料表，來源 job 與相關檔案保存在 `out/templates/jobs/`。

## 操作路徑

| 操作 | 路徑 |
|---|---|
| 模板頁面 | `/workspace/pdf-overlay/templates` |
| 上傳模板來源 | `POST /upload-template-source` |
| 模板來源編輯器 | `/editor/template/job/<job_id>` |
| 模板列表/新增 | `GET,POST /api/document-templates` |
| 刪除模板 | `DELETE /api/document-templates/<template_id>` |
| 重新命名模板 | `POST /api/document-templates/<template_id>/rename` |
| 套用模板 | `POST /api/document-templates/<template_id>/apply` |
| 模板來源 job | `GET /api/document-templates/source-jobs` |

## 操作步驟

1. 使用者進入 `/workspace/pdf-overlay/templates`。
2. 使用者上傳模板來源 PDF，系統建立 `template_source` job。
3. Worker 對模板來源執行 OCR 或必要處理。
4. 使用者進入模板來源編輯器校訂頁面與框線。
5. 使用者保存文件模板，系統寫入 `document_templates`。
6. 使用者於目標 job 選擇模板並套用，系統依模板資料調整目標頁面或框資料。

## 欄位說明

| 欄位名稱 | 必填 | 說明 | 格式或限制 |
|---|---|---|---|
| 模板名稱 | 是 | 模板顯示或識別名稱 | 缺少時回傳 `Template name is required.`。 |
| 來源 job | 是 | 建立模板所依據的 template_source job | 不合法時回傳 `Invalid job id.`。 |
| 模板 payload | 是 | 模板頁面、框線與套用設定 | 格式錯誤時回傳錯誤訊息。 |

## 備份範圍

依 `TEMPLATE_BACKUP_RESTORE.md`，模板備份包含：

| 路徑 | 來源 | 用途 |
|---|---|---|
| `export/document_templates.json` | 從 DB `document_templates` 匯出 | 模板 metadata 與 DB 內保存內容。 |
| `out/templates/jobs/` | 本機檔案系統 | 模板來源 PDF、OCR、編輯檔與模板來源 job 檔案。 |
| `out/templates/document_templates.json` | 本機檔案系統，若存在才納入 | 舊版或備用 JSON 檔。 |

## 錯誤處理

| 錯誤情境 | 可能原因 | 處理方式 |
|---|---|---|
| `Template not found.` | 模板不存在或使用者無權存取 | 重新整理列表或確認權限。 |
| `Template name is required.` | 未填模板名稱 | 補上名稱後重試。 |
| `Invalid job id.` | 套用或建立模板時來源 job 不合法 | 確認來源 job 是否存在。 |
| `Template has no matching target pages.` | 目標 job 無可套用頁面 | 確認模板頁面與目標文件頁面。 |

## 待補充項目

- 此處需補充模板套用規則與頁面匹配邏輯的使用者範例。

# 11. 背景工作與處理記錄

## 主要依據檔案

- `worker.py`
- `app/services/worker.py`
- `app/services/job_store.py`
- `app/services/jobs.py`
- `app/services/pipeline.py`
- `app/services/doc_workspace.py`
- `app/services/word_translate.py`
- `app/services/batch.py`
- `scripts/init_sqlserver_schema.sql`

## 設計概述

系統以資料庫 `jobs` 表作為背景工作佇列。使用者上傳檔案或觸發翻譯後，系統建立 job record 與 job 目錄。Worker 透過 `claim_next_job()` 取得 queued job，根據 `job_type` 執行不同處理流程，並更新 `status`、`stage`、`progress`、`error_message`、`started_at`、`completed_at` 與 `updated_at`。

## Job 類型

| job_type | 用途 | 主要處理服務 |
|---|---|---|
| `ocr_overlay` | PDF 原版面 OCR 與翻譯 | `pipeline.py`、`batch.py`、`realtime_translate.py` |
| `template_source` | PDF 原版面模板來源處理 | `pipeline.py`、`document_templates.py` |
| `doc_workspace` | PDF 重建翻譯工作區 | `doc_workspace.py` |
| `word_translate` | Word 文件翻譯 | `word_translate.py` |

## Job 狀態與階段

| 欄位 | 可能值 | 說明 |
|---|---|---|
| `status` | `queued` | 等待 Worker 處理。 |
| `status` | `running` | Worker 正在處理。 |
| `status` | `completed` | 工作完成。 |
| `status` | `failed` | 工作失敗，通常會記錄 `error_message`。 |
| `status` | `cancelled` | 工作已取消。 |
| `stage` | `queued`、`ocr`、`translate`、`extract`、`html`、`docx`、`prepare`、`save`、`completed`、`failed`、`cancelled` | 依 job type 表示處理階段。 |

## Worker 併發限制

| 設定 | 控制範圍 |
|---|---|
| `WORKER_OCR_MAX_RUNNING` | OCR 與 template source 非翻譯階段併發。 |
| `WORKER_PDF_TRANSLATE_MAX_RUNNING` | PDF 翻譯階段併發。 |
| `WORKER_DOC_MAX_RUNNING` | PDF 重建翻譯 job 併發。 |
| `WORKER_WORD_MAX_RUNNING` | Word 翻譯 job 併發。 |
| `WORKER_POLL_SECONDS` | 無工作時的輪詢間隔。 |

## 處理記錄

| 資料表 | 用途 |
|---|---|
| `jobs` | 工作主檔、狀態、進度、owner、payload 與錯誤訊息。 |
| `job_artifacts` | 工作產物檔案路徑與類型。 |
| `job_events` | 工作事件、警告與階段訊息。 |
| `audit_logs` | 使用者操作與管理操作稽核。 |
| `system_error_logs` | 系統錯誤紀錄。 |

## 取消與重試

使用者可透過 API 取消部分 job。取消時系統會更新 `cancel_requested`，Worker 透過取消監控 thread 偵測並中止工作。重試功能會依 job 狀態與服務邏輯重新排入佇列或清除錯誤欄位。

## 待補充項目

- 此處需補充正式環境保留 job 歷史資料與輸出檔的清理政策。

# 12. 資料庫設計

## 主要依據檔案

- `scripts/init_sqlserver_schema.sql`
- `app/services/job_store.py`
- `app/services/auth_store.py`
- `app/services/audit_service.py`
- `app/services/document_templates.py`
- `migrations/`

## 設計概述

系統正式資料庫為 Microsoft SQL Server，建議 schema 為 `translation`。資料表主要分為認證授權、背景工作、編輯 presence、稽核與錯誤紀錄、文件模板五類。正式環境 `AUTO_SCHEMA_MANAGEMENT` 預設為 false，應透過 Alembic migration、`scripts/init_sqlserver_schema.sql` 或維運流程建立 schema，再以 `schema-preflight` 驗證必要資料表與欄位。

## 主要資料表

| 資料表名稱 | 用途 | 主要欄位 | 備註 |
|---|---|---|---|
| `users` | 本機使用者資料 | `id`, `work_id`, `display_name`, `email`, `is_active`, `last_login_at` | `work_id` 唯一。 |
| `roles` | 角色主檔 | `id`, `name` | 角色包含 `admin`、`editor`。 |
| `user_roles` | 使用者角色 | `user_id`, `role_id` | 一位使用者限制一個角色。 |
| `jobs` | 背景工作主檔 | `job_id`, `job_type`, `status`, `stage`, `progress`, `owner_work_id`, `payload_json`, `error_message` | job queue 與狀態查詢核心。 |
| `job_artifacts` | 工作產物 | `id`, `job_id`, `artifact_type`, `file_path` | 與 `jobs.job_id` 關聯。 |
| `job_events` | 工作事件 | `id`, `job_id`, `event_type`, `stage`, `message` | 記錄警告、階段與事件。 |
| `editor_presence` | 編輯器 presence | `job_id`, `work_id`, `display_name`, `last_seen_at` | 用於追蹤正在編輯者。 |
| `audit_logs` | 稽核紀錄 | `id`, `action`, `work_id`, `detail_json`, `job_id`, `request_path` | 管理後台可查詢。 |
| `system_error_logs` | 系統錯誤 | `id`, `level`, `component`, `message`, `error_type`, `detail_json`, `job_id` | 管理後台可查詢。 |
| `document_templates` | 文件模板 | `template_id`, `name`, `display_name`, `owner_work_id`, `source_job_id`, `status`, `payload_json` | 保存模板 metadata 與設定。 |

## 索引設計

| 資料表 | 索引重點 | 用途 |
|---|---|---|
| `jobs` | `status, created_at`、`job_type, updated_at`、`owner_work_id`、`cancel_requested, status` | 支援 Worker claim、列表查詢、owner 隔離與取消查詢。 |
| `job_artifacts` | `job_id` | 查詢指定 job 產物。 |
| `job_events` | `job_id, created_at DESC` | 查詢 job 事件歷程。 |
| `editor_presence` | `last_seen_at DESC` | 清理或顯示活躍編輯者。 |
| `audit_logs` | `created_at DESC`、`work_id, created_at`、`job_id, created_at` | 支援管理後台查詢。 |
| `system_error_logs` | `created_at DESC`、`component, created_at`、`job_id, created_at` | 支援錯誤查詢與排除。 |
| `document_templates` | `source_job_id`、`owner_work_id`、`updated_at DESC` | 支援模板列表與來源 job 查詢。 |

## 資料生命週期

使用者登入時同步或建立 `users` 資料，角色由 `roles` 與 `user_roles` 控制。使用者上傳文件後建立 `jobs`，處理過程追加 `job_events`，完成後可保存 `job_artifacts` 或本機輸出檔。編輯器 presence 依使用者 heartbeat 更新。稽核與系統錯誤紀錄可依 retention CLI 清理。文件模板可由備份腳本匯出與還原。

## 待補充項目

- 此處需補充正式 ERD。
- 此處需補充完整 Alembic migration 版本與資料庫備份政策。

# 13. 系統維護與備份還原

## 主要依據檔案

- `SYSTEM_DEPLOYMENT.md`
- `ENVIRONMENT.md`
- `OPERATIONS.md`
- `TEMPLATE_BACKUP_RESTORE.md`
- `scripts/backup_templates.sh`
- `scripts/restore_templates.sh`
- `deploy.sh`

## 維護項目

| 項目 | 說明 |
|---|---|
| Web 服務 | `uo_regulations_translate.service`，啟動 Gunicorn 與 Flask App。 |
| Worker 服務 | `uo_regulations_translate_worker.service`，處理 OCR、翻譯與文件輸出。 |
| Log 清理 | `uo_regulations_translate_log_cleanup.timer` 定期執行系統錯誤與稽核清理。 |
| 模板備份 | `uo_regulations_translate_template_backup.timer` 定期執行模板備份。 |
| Nginx | 提供 HTTP 入口、靜態檔與反向代理。 |
| SQL Server | 保存正式資料，需由維運策略進行備份。 |

## 常用維護指令

| 操作 | 指令 |
|---|---|
| 重新部署 | `bash deploy.sh` |
| 重啟 Web | `sudo systemctl restart uo_regulations_translate` |
| 重啟 Worker | `sudo systemctl restart uo_regulations_translate_worker` |
| 查看 Web log | `journalctl -u uo_regulations_translate --no-pager -n 100` |
| 查看 Worker log | `journalctl -u uo_regulations_translate_worker --no-pager -n 100` |
| 檢查 timer | `systemctl list-timers | grep uo_regulations_translate` |
| Schema 檢查 | `.venv/bin/flask --app app.py schema-preflight` |
| 初始化角色與管理員 | `.venv/bin/flask --app app.py seed-bootstrap` |

## 模板備份

模板備份由 `scripts/backup_templates.sh` 執行，備份範圍包含 `document_templates` DB 匯出、`out/templates/jobs/` 與舊版備用 JSON 檔。備份檔預設輸出至 `backups/templates/`，命名格式如下：

```text
<hostname>_templates_<YYYY-MM-DD_HHMMSS>.tar.gz
<hostname>_templates_<YYYY-MM-DD_HHMMSS>.tar.gz.sha256
```

預設最多保留最新 3 份備份，可由 `TEMPLATE_BACKUP_MAX_FILES` 調整。

## 模板還原

標準還原流程：

```bash
cd /home/NE025/pdf_ocr_translate
APP_ROOT=/home/NE025/pdf_ocr_translate \
ENV_FILE=/home/NE025/pdf_ocr_translate/.env \
bash scripts/restore_templates.sh /path/to/<backup-file>.tar.gz --yes
```

還原會覆蓋目前模板資料。依既有文件，還原前應先確認備份檔與 checksum，並暫停使用者對模板的新增、編輯與刪除操作。

## 備份限制

模板備份不包含：

- `.env`、API key、DB 連線字串或 LDAP 密碼。
- 整個 MSSQL database。
- 一般使用者上傳檔、一般 OCR / 翻譯 job 輸出。
- `logs/`、`.venv/`、`PaddleX/` 或其他大型 runtime 目錄。

## 待補充項目

- 此處需補充完整 SQL Server database 備份、還原與災難復原程序。
- 此處需補充正式環境監控、告警與容量清理政策。

# 14. 錯誤代碼列表及處理說明

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/blueprints/auth/routes.py`
- `app/blueprints/admin/routes.py`
- `app/services/auth_service.py`
- `app/services/openai_config.py`
- `app/services/realtime_translate.py`
- `app/services/ocr.py`
- `app/services/worker.py`

## 錯誤代碼說明

程式碼未定義集中式業務錯誤代碼表。以下以 HTTP 狀態、API `error` 欄位、表單訊息與系統例外整理可追蹤的錯誤清單；錯誤代碼欄標示「程式未定義」者，表示目前只能由訊息文字或 HTTP 狀態辨識。

| 錯誤代碼 | 錯誤訊息 | 發生原因 | 使用者處理方式 | 管理者處理方式 |
|---|---|---|---|---|
| `HTTP-401` | `Authentication required.` | 未登入即呼叫受保護 API | 重新登入後操作 | 檢查登入設定與 session cookie。 |
| `HTTP-403` | `Forbidden.` | 無權存取 job、模板或管理頁面 | 使用有權限帳號登入 | 檢查角色、owner 與 `OWNER_ACCESS_ENABLED`。 |
| `HTTP-404` | Not Found | job、檔案、模板或頁面不存在 | 重新整理或確認連結 | 檢查 DB 紀錄與檔案系統是否一致。 |
| `HTTP-500` | Internal Server Error | 未處理例外 | 回報管理者 | 查詢 `system_error_logs`、journal 與 app log。 |
| 程式未定義 | `請輸入工號或使用者名稱。` | 登入缺少 username | 補上工號或使用者名稱 | 檢查登入表單與認證設定。 |
| 程式未定義 | `請輸入密碼。` | LDAP 模式缺少密碼 | 輸入密碼 | 檢查登入表單。 |
| 程式未定義 | `帳號或密碼錯誤。` | LDAP 找不到帳號或 bind 失敗 | 確認帳密 | 檢查 LDAP 主機與 bind 設定。 |
| 程式未定義 | `LDAP 設定不完整，請確認主機、Base DN 與 Bind 帳號。` | LDAP 必要設定缺少 | 聯絡管理者 | 補齊 `.env` 中 LDAP 設定。 |
| 程式未定義 | `Missing PDF file.` | PDF 上傳未附檔案 | 重新選擇 PDF | 檢查前端欄位名稱與上傳限制。 |
| 程式未定義 | `Missing Word file.` | Word 上傳未附檔案 | 重新選擇 Word 檔 | 檢查前端欄位名稱與上傳限制。 |
| 程式未定義 | `Invalid page selection.` | 頁碼格式錯誤 | 使用 `1,3,5-7` 格式 | 檢查頁碼解析邏輯。 |
| 程式未定義 | `Invalid glossary payload.` | 詞彙 JSON 格式錯誤 | 重新整理或修正資料 | 檢查前端送出格式。 |
| 程式未定義 | `Only .xlsx files are supported.` | 匯入詞彙非 `.xlsx` | 轉存 `.xlsx` 後匯入 | 檢查檔案驗證。 |
| 程式未定義 | `Template not found.` | 模板不存在或不可存取 | 重新整理模板列表 | 檢查 `document_templates` 與權限。 |
| 程式未定義 | `Template name is required.` | 模板重新命名缺少名稱 | 補上模板名稱 | 檢查前端驗證。 |
| 程式未定義 | `No authorized job IDs selected.` | 批次下載包含無權限 job | 只選擇可存取 job | 檢查 owner 隔離與 admin 權限。 |
| 程式未定義 | `OPENAI_API_KEY is not configured.` | API key 未設定 | 聯絡管理者 | 補齊 `.env`。 |
| 程式未定義 | `OPENAI_BASE_URL is not configured.` | OpenAI endpoint 未設定 | 聯絡管理者 | 補齊 `.env`。 |
| 程式未定義 | `Unsupported job type` | Worker 取得未知 job type | 回報管理者 | 檢查資料庫 job 資料與程式版本。 |

## 待補充項目

- 此處需補充正式錯誤代碼命名規範；目前程式碼未集中定義錯誤碼。
- 此處需補充管理者故障排除 SOP 與截圖。

# 15. 程式設計

## 主要依據檔案

- `app/`
- `ocr_pipeline/`
- `tests/`
- `pyproject.toml`
- `AGENTS.md`

## 程式結構

| 路徑 | 說明 |
|---|---|
| `app/blueprints/` | Flask Blueprint，依功能分為 auth、admin、main、editor、api、jobs。 |
| `app/services/` | 服務層，包含 OCR、翻譯、job、詞彙、模板、權限、稽核與維運邏輯。 |
| `app/templates/` | 共用模板與錯誤頁。 |
| `app/blueprints/*/templates/` | 各 Blueprint 專屬頁面模板。 |
| `ocr_pipeline/` | OCR merge、段落對齊、表格合併與 pipeline 底層邏輯。 |
| `static/` | 前端 JavaScript、CSS 與圖示資源。 |
| `scripts/` | SQL schema、systemd/nginx 安裝、備份還原與維運腳本。 |
| `tests/` | pytest 測試，涵蓋上傳、job store、OCR、詞彙、翻譯、權限與維運 CLI。 |

## 設計原則

系統採用 Blueprint 分離路由，將耗時或可重用的業務邏輯放入 `app/services/`。上傳路由主要負責驗證表單與建立 job，實際 OCR、翻譯與文件輸出由 Worker 執行。資料庫存取集中於 `job_store.py`、`auth_store.py`、`audit_service.py` 與 `document_templates.py` 等服務。

## 主要服務

| 服務 | 責任 |
|---|---|
| `pipeline.py` | 建立與執行 PDF 原版面 OCR job。 |
| `batch.py` | 管理 batch 翻譯流程與輪詢。 |
| `realtime_translate.py` | 執行 PDF 即時分段翻譯。 |
| `doc_workspace.py` | 執行 PDF 重建翻譯與 DOCX 產出。 |
| `word_translate.py` | 執行 Word 翻譯與輸出。 |
| `job_store.py` | 管理 SQL Server job queue、事件與資料表檢查。 |
| `jobs.py` | 管理 job 目錄、metadata、列表、下載與狀態顯示。 |
| `glossary.py` | 管理詞彙庫讀寫、匯入與匯出。 |
| `document_templates.py` | 管理文件模板、來源 job、備份匯出與還原資料。 |
| `auth_service.py` / `authz_service.py` | 管理登入、LDAP、角色解析與 owner 權限。 |
| `audit_service.py` | 記錄與查詢稽核、系統錯誤。 |

## 測試

專案使用 pytest。常用指令如下：

```bash
pytest
pytest tests/test_app.py -k upload
```

測試涵蓋 Flask route、OCR score filtering、PDF overlay、docx export、job store、詞彙管理、OpenAI 設定、auth、audit logging、operations CLI 與 timeout 設定。

## 待補充項目

- 此處需補充正式程式碼審查規範與版本發布流程。

# 附錄 A. API 與路由清單

## 主要依據檔案

- `app/blueprints/main/routes.py`
- `app/blueprints/api/routes.py`
- `app/blueprints/editor/routes.py`
- `app/blueprints/jobs/routes.py`
- `app/blueprints/auth/routes.py`
- `app/blueprints/admin/routes.py`

## 路由清單

當 `AUTH_ENABLED=True` 時，除登入、登出與 static asset 外，受保護頁面與 API 需登入。部分 API 另依 job owner 或 admin 角色檢查權限。

| 方法 | 路徑 | Endpoint 或功能 |
|---|---|---|
| `GET` | `/` | 首頁。 |
| `GET` | `/workspace/pdf-overlay` | PDF 原版面工作區。 |
| `GET` | `/workspace/pdf-overlay/templates` | PDF 原版面模板頁面。 |
| `GET` | `/workspace/glossary` | 詞彙管理頁。 |
| `GET` | `/workspace/pdf-doc` | PDF 重建翻譯工作區。 |
| `GET` | `/workspace/word` | Word 翻譯工作區。 |
| `POST` | `/upload` | 上傳 PDF 原版面 OCR/翻譯 job。 |
| `POST` | `/upload-template-source` | 上傳模板來源 PDF。 |
| `POST` | `/upload-doc-workspace` | 上傳 PDF 重建翻譯 job。 |
| `POST` | `/upload-word-workspace` | 上傳 Word 翻譯 job。 |
| `GET,POST` | `/auth/login` | 登入。 |
| `GET` | `/auth/logout` | 登出。 |
| `GET` | `/admin/users` | 使用者列表。 |
| `GET,POST` | `/admin/users/create` | 新增使用者。 |
| `POST` | `/admin/users/<work_id>/active` | 更新使用者啟用狀態。 |
| `POST` | `/admin/users/<work_id>/role` | 更新使用者角色。 |
| `GET` | `/admin/audit-logs` | 稽核紀錄。 |
| `GET` | `/admin/system-error-logs` | 系統錯誤紀錄。 |
| `GET` | `/editor/job/<job_id>` | 一般編輯器。 |
| `GET` | `/editor/template/job/<job_id>` | 模板來源編輯器。 |
| `GET` | `/jobs/<job_id>/<path:filename>` | job 檔案下載。 |
| `GET` | `/api/job/<job_id>` | 讀取 job 資料。 |
| `POST` | `/api/job/<job_id>/batch-translate` | 啟動 batch 翻譯。 |
| `GET` | `/api/job/<job_id>/batch-status` | 查詢 batch 狀態。 |
| `POST` | `/api/job/<job_id>/batch-restore` | 還原 batch 輸出。 |
| `POST` | `/api/job/<job_id>/system-prompt` | 保存 job 系統提示詞。 |
| `GET,POST` | `/api/glossary` | 全域詞彙讀寫。 |
| `GET` | `/api/glossary/library` | 詞彙庫查詢。 |
| `GET` | `/api/glossary/system-export` | 系統詞彙匯出。 |
| `POST` | `/api/glossary/system-import-preview` | 系統詞彙匯入預覽。 |
| `POST` | `/api/glossary/system-import-apply` | 系統詞彙匯入套用。 |
| `GET,POST` | `/api/document-templates` | 文件模板列表與新增。 |
| `DELETE` | `/api/document-templates/<template_id>` | 刪除文件模板。 |
| `POST` | `/api/document-templates/<template_id>/rename` | 重新命名文件模板。 |
| `POST` | `/api/document-templates/<template_id>/apply` | 套用文件模板。 |
| `GET` | `/api/document-templates/source-jobs` | 模板來源 job 清單。 |
| `GET` | `/api/jobs` | PDF 原版面 job 列表。 |
| `GET` | `/api/template-jobs` | 模板來源 job 列表。 |
| `GET` | `/api/doc-jobs` | PDF 重建 job 列表。 |
| `GET` | `/api/word-jobs` | Word job 列表。 |
| `GET` | `/api/editor-presence` | 編輯 presence 索引。 |
| `POST` | `/api/job/<job_id>/editor-presence` | 更新指定 job presence。 |
| `POST` | `/api/job/<job_id>/cancel` | 取消 job。 |
| `POST` | `/api/job/<job_id>/cancel-word` | 取消 Word job。 |
| `POST` | `/api/job/<job_id>/retry` | 重試 job。 |
| `GET` | `/api/doc-job/<job_id>` | PDF 重建 job 資料。 |
| `GET,POST` | `/api/jobs/download-translated` | 批次下載 PDF 原版面翻譯結果。 |
| `POST` | `/api/doc-jobs/download-docx` | 批次下載 PDF 重建 DOCX。 |
| `POST` | `/api/word-jobs/download-docx` | 批次下載 Word DOCX。 |
| `GET` | `/api/jobs/stream` | PDF 原版面 job 狀態串流。 |
| `GET` | `/api/doc-jobs/stream` | PDF 重建 job 狀態串流。 |
| `GET` | `/api/word-jobs/stream` | Word job 狀態串流。 |
| `GET` | `/api/template-jobs/stream` | 模板來源 job 狀態串流。 |
| `DELETE` | `/api/job/<job_id>` | 刪除 job。 |
| `POST` | `/api/job/<job_id>/save` | 保存 job 編輯結果。 |
| `POST` | `/api/job/<job_id>/apply-consistency` | 套用一致性修正。 |
| `POST` | `/api/job/<job_id>/apply-paragraph-term` | 套用段落術語修正。 |
| `POST` | `/api/job/<job_id>/region-ocr-preview` | 區域 OCR 預覽。 |
| `POST` | `/api/job/<job_id>/retranslate-box` | 單框重翻。 |
| `POST` | `/api/job/<job_id>/retranslate-boxes` | 多框重翻。 |
| `POST` | `/api/job/<job_id>/retranslate-region` | 區域重翻。 |
| `POST` | `/api/job/<job_id>/glossary-retranslate` | 詞彙重翻。 |
| `POST` | `/api/upload-cancel` | 取消上傳或建立中的工作。 |

## 待補充項目

- 此處需補充各 POST API 的 request/response schema。

# 附錄 B. 資料表欄位字典

## 主要依據檔案

- `scripts/init_sqlserver_schema.sql`
- `app/services/job_store.py`

## `users`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | int identity | 使用者流水號。 |
| `work_id` | nvarchar(100) | 工號或登入識別，唯一。 |
| `display_name` | nvarchar(200) | 顯示名稱。 |
| `email` | nvarchar(200) | Email。 |
| `is_active` | bit | 是否啟用。 |
| `created_at` | datetime2 | 建立時間。 |
| `last_login_at` | datetime2 | 最近登入時間。 |

## `roles` 與 `user_roles`

| 資料表 | 欄位 | 型別 | 說明 |
|---|---|---|---|
| `roles` | `id` | int identity | 角色流水號。 |
| `roles` | `name` | nvarchar(50) | 角色名稱，唯一。 |
| `user_roles` | `user_id` | int | 使用者 ID。 |
| `user_roles` | `role_id` | int | 角色 ID。 |

## `jobs`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `job_id` | char(32) | job ID，主鍵。 |
| `job_type` | varchar(50) | job 類型，例如 `ocr_overlay`、`doc_workspace`。 |
| `status` | varchar(30) | job 狀態。 |
| `stage` | varchar(50) | job 階段。 |
| `progress` | float | 處理進度。 |
| `job_name` | nvarchar(255) | job 顯示名稱。 |
| `owner_work_id` | nvarchar(100) | job 擁有者工號。 |
| `target_lang` | varchar(20) | 目標語言。 |
| `document_mode` | varchar(20) | 文件模式。 |
| `payload_json` | nvarchar(max) | job payload JSON。 |
| `error_message` | nvarchar(max) | 錯誤訊息。 |
| `cancel_requested` | bit | 是否要求取消。 |
| `retry_count` | int | 重試次數。 |
| `worker_id` | varchar(100) | 處理 worker 識別。 |
| `started_at` | datetime2 | 開始時間。 |
| `completed_at` | datetime2 | 完成時間。 |
| `created_at` | datetime2 | 建立時間。 |
| `updated_at` | datetime2 | 更新時間。 |

## `job_artifacts` 與 `job_events`

| 資料表 | 欄位 | 型別 | 說明 |
|---|---|---|---|
| `job_artifacts` | `id` | bigint identity | 產物流水號。 |
| `job_artifacts` | `job_id` | char(32) | 對應 job。 |
| `job_artifacts` | `artifact_type` | varchar(50) | 產物類型。 |
| `job_artifacts` | `file_path` | nvarchar(1000) | 產物檔案路徑。 |
| `job_artifacts` | `created_at` | datetime2 | 建立時間。 |
| `job_events` | `id` | bigint identity | 事件流水號。 |
| `job_events` | `job_id` | char(32) | 對應 job。 |
| `job_events` | `event_type` | varchar(50) | 事件類型。 |
| `job_events` | `stage` | varchar(50) | 發生階段。 |
| `job_events` | `message` | nvarchar(max) | 事件訊息。 |
| `job_events` | `created_at` | datetime2 | 建立時間。 |

## 其他資料表

| 資料表 | 欄位摘要 | 說明 |
|---|---|---|
| `editor_presence` | `job_id`, `work_id`, `display_name`, `remote_addr`, `user_agent`, `created_at`, `last_seen_at` | 編輯器在線狀態。 |
| `audit_logs` | `id`, `created_at`, `action`, `work_id`, `detail_json`, `job_id`, `request_path`, `remote_addr` | 稽核紀錄。 |
| `system_error_logs` | `id`, `created_at`, `level`, `component`, `message`, `error_type`, `detail_json`, `job_id`, `request_path`, `remote_addr` | 系統錯誤紀錄。 |
| `document_templates` | `template_id`, `name`, `display_name`, `owner_work_id`, `source_job_id`, `status`, `payload_json`, `created_at`, `updated_at` | 文件模板資料。 |

## 待補充項目

- 此處需補充欄位長度調整歷程與 migration 版本對照。

# 附錄 C. 驗收項目對照表

## 主要依據檔案

- `docs/system-description.md`
- `app/blueprints/*`
- `app/services/*`
- `scripts/init_sqlserver_schema.sql`
- `ENVIRONMENT.md`
- `SYSTEM_DEPLOYMENT.md`
- `TEMPLATE_BACKUP_RESTORE.md`
- `tests/`

## 對照原則

本表依翻譯系統已確認之功能模組整理。若項目可由目前程式碼或文件確認，列出對應章節、主要程式與說明；若無法確認完整設計或驗收範圍，標示「此處需補充」。

| 驗收項目 | 對應章節 | 主要程式或資料來源 | 說明 | 待補充 |
|---|---|---|---|---|
| 系統架構與部署環境 | 第 1、2、13、15 章 | `SYSTEM_DEPLOYMENT.md`、`ENVIRONMENT.md`、`deploy.sh`、`app/__init__.py`、`app/config.py` | 系統採用 Nginx、Gunicorn、Flask App、背景 Worker 與 SQL Server 分層部署，並以 `.env` 管理資料庫、OpenAI/Azure、LDAP 與 worker 參數。 | 此處需補充正式網域、主機規格、網路拓撲與 HTTPS 設定。 |
| 權限控管與管理後台 | 第 3、12、14、16、17 章 | `app/blueprints/auth/routes.py`、`app/blueprints/admin/routes.py`、`app/services/auth_service.py`、`app/services/authz_service.py`、`app/services/auth_store.py` | 系統支援登入、登出、LDAP/AD 驗證、admin/editor 角色、owner access、使用者管理、稽核紀錄與系統錯誤查詢。 | 此處需補充正式 AD 群組、角色申請流程與管理員名單。 |
| PDF 原版面 OCR 與翻譯 | 第 4、5、8、11、14、16 章 | `app/blueprints/main/routes.py`、`app/blueprints/api/routes.py`、`app/services/pipeline.py`、`app/services/ocr.py`、`app/services/batch.py`、`app/services/realtime_translate.py`、`ocr_pipeline/*` | 使用者可上傳 PDF 建立 `ocr_overlay` job，系統執行 OCR、框線合併、batch 或 realtime 翻譯，並提供編輯器校訂與下載。 | 此處需補充正式支援的 PDF 類型、頁數限制、檔案大小限制與翻譯品質驗收標準。 |
| PDF 重建翻譯工作區 | 第 4、6、11、14、16 章 | `app/blueprints/main/routes.py`、`app/services/doc_workspace.py`、`app/services/markdown_translate.py`、`app/services/docx_export.py`、`app/blueprints/main/templates/main/doc_workspace.html` | 使用者可上傳 PDF 建立 `doc_workspace` job，系統執行抽取、翻譯與 DOCX 輸出。 | 此處需補充重建文件版面保留範圍、輸出格式限制與測試樣本。 |
| Word 翻譯工作區 | 第 4、7、11、14、16 章 | `app/blueprints/main/routes.py`、`app/services/word_translate.py`、`app/blueprints/main/templates/main/word_workspace.html`、`tests/test_word_translate.py` | 使用者可上傳 Word 文件建立 `word_translate` job，系統執行準備、翻譯與 DOCX 輸出，並支援取消與批次下載。 | 此處需補充正式支援副檔名、格式保留範圍與品質驗收標準。 |
| 文件編輯器與人工校訂 | 第 5、8、9、10、14、16 章 | `app/blueprints/editor/routes.py`、`app/blueprints/editor/templates/editor/editor.html`、`app/blueprints/api/routes.py`、`app/services/document_terms.py`、`app/services/translation_debug.py` | 編輯器支援讀取 job 資料、保存校訂、區域 OCR、單框/多框/區域重翻、一致性修正、段落術語修正與詞彙重翻。 | 此處需補充正式操作截圖、校訂流程與多人編輯規則。 |
| 詞彙庫與術語管理 | 第 8、9、14、16 章 | `app/blueprints/api/routes.py`、`app/services/glossary.py`、`app/services/document_terms.py`、`static/glossary_manager.js`、`glossary/global_glossary.json`、`glossary/system_glossary.json` | 系統支援全域詞彙讀寫、詞彙庫查詢、系統詞彙匯出、`.xlsx` 匯入預覽與套用，並可在編輯器依詞彙進行重翻。 | 此處需補充詞彙 Excel 正式欄位規格、匯入審核流程與詞彙維護責任人。 |
| 文件模板管理與套用 | 第 4、8、10、13、14、16、17 章 | `app/services/document_templates.py`、`app/blueprints/api/routes.py`、`app/blueprints/main/templates/main/overlay_templates.html`、`TEMPLATE_BACKUP_RESTORE.md` | 系統支援上傳模板來源 PDF、建立模板、重新命名、刪除、套用模板，並提供模板 DB 與來源 job 檔案備份還原。 | 此處需補充模板頁面匹配規則、模板命名規範與還原演練紀錄。 |
| 背景工作與處理記錄 | 第 5、6、7、11、12、14、17 章 | `worker.py`、`app/services/worker.py`、`app/services/job_store.py`、`app/services/jobs.py`、`scripts/init_sqlserver_schema.sql` | 系統以 `jobs` 資料表作為 job queue，支援 `ocr_overlay`、`template_source`、`doc_workspace`、`word_translate`，並記錄狀態、階段、進度、事件、產物與錯誤。 | 此處需補充正式 job 保留天數、輸出檔清理政策與併發容量測試。 |
| 資料庫設計與欄位字典 | 第 12、17 章 | `scripts/init_sqlserver_schema.sql`、`app/services/job_store.py`、`app/services/auth_store.py`、`app/services/audit_service.py`、`app/services/document_templates.py` | 已整理 `users`、`roles`、`user_roles`、`jobs`、`job_artifacts`、`job_events`、`editor_presence`、`audit_logs`、`system_error_logs`、`document_templates` 等資料表。 | 此處需補充正式 ERD、migration 版本對照與資料庫備份政策。 |
| 錯誤處理與稽核追蹤 | 第 3、11、12、14、16、17 章 | `app/services/audit_service.py`、`app/blueprints/admin/routes.py`、`app/services/auth_hooks_service.py`、`app/services/openai_config.py`、`app/services/worker.py` | 系統記錄登入、登出、登入失敗、管理操作與系統錯誤；API 以 HTTP 狀態與 `error` 欄位回傳常見錯誤。 | 此處需補充正式錯誤代碼命名規範與管理者故障排除 SOP。 |
| 系統維護、部署與備份還原 | 第 2、13、15 章 | `SYSTEM_DEPLOYMENT.md`、`OPERATIONS.md`、`TEMPLATE_BACKUP_RESTORE.md`、`scripts/backup_templates.sh`、`scripts/restore_templates.sh`、`deploy/systemd/*` | 系統提供 deploy 腳本、systemd Web/Worker 服務、log 清理 timer、模板備份 timer、schema preflight 與模板備份還原程序。 | 此處需補充 SQL Server 完整備份還原、監控告警、容量管理與災難復原程序。 |
| 測試與驗證資料 | 第 15 章 | `tests/test_app.py`、`tests/test_job_store.py`、`tests/test_glossary_management.py`、`tests/test_word_translate.py`、`tests/test_auth_phase1.py`、`tests/test_audit_logging.py`、`tests/test_operations_cli.py` | 測試涵蓋上傳、job store、OCR、詞彙、Word 翻譯、權限、稽核、OpenAI 設定與維運 CLI。 | 此處需補充正式驗收執行紀錄、測試資料、截圖與簽核結果。 |

## 待補充項目

- 此處需補充驗收項目的正式文字版本與驗收判定標準。
- 此處需補充每個驗收項目是否需要程式碼、畫面、文件、測試紀錄或實機操作作為佐證。
