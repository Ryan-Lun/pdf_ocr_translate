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
