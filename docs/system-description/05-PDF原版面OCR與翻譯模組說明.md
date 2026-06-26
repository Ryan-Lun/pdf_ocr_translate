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
