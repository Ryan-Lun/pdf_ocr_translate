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
