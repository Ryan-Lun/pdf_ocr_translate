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
