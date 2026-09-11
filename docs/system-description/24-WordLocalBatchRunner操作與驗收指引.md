# Word Local Batch Runner 操作與驗收指引

## 適用範圍

`scripts/word_local_batch_translate.py` 是一次性批次工具，供特定資料夾中的 Word 文件使用地端 OpenAI-compatible 模型進行中翻英。此工具固定使用 Word 原版面翻譯流程，輸出模式為「保留原文，譯文置於下方」，並要求每次執行都明確選定一個 Department Glossary。

此工具不會修改正式 `.env`，也不會改變一般 UI 上傳、背景 worker 或雲端模型的預設行為。地端模型 endpoint、API key、model name、併發與頁首頁尾規則都只透過本次 CLI 參數傳入。

## 前置條件

執行前需確認：

- `.venv` 已完成安裝，並在 repo 根目錄執行。
- `DATABASE_URL` 可連線，且 Department Glossary SQL schema 已建置。
- 指定的 `--glossary-library-id` 存在、啟用，且內容已匯入。
- 地端模型提供 OpenAI-compatible `/v1/chat/completions` API。
- local model base URL 應包含 `/v1`，例如 `http://192.168.12.63:8000/v1`。
- `.doc` 檔案會先轉為 `.docx` 後再進入 Word 翻譯流程；正式大量執行前應先用少量樣本確認轉檔後版面可接受。
- 若輸入本來就是 `.docx`，runner 會直接納入掃描並輸出為 `.docx`。

## 必要參數

| 參數 | 說明 |
|---|---|
| `input_dir` | 要掃描的來源資料夾，會遞迴處理 `.doc` 與 `.docx`。 |
| `output_dir` | 輸出資料夾，會保留相對路徑。 |
| `--base-url` | 地端模型 OpenAI-compatible endpoint，例如 `http://host:8000/v1`。 |
| `--api-key` | 地端模型 API key；若服務不檢查，可使用約定值如 `sk-local`。 |
| `--model` | 地端模型名稱，必須與 endpoint 支援的 model 名稱一致。 |
| `--glossary-library-id` | 本次批次唯一使用的 Department Glossary ID。 |

## 常用選項

| 參數 | 預設 | 說明 |
|---|---:|---|
| `--translate-tables true|false` | `true` | 是否翻譯表格內容。 |
| `--stage-2-enabled true|false` | `true` | 是否啟用 Stage 2 post-edit。 |
| `--disable-stage-2` | 關閉 | 快速關閉 Stage 2，等同本次不做 post-edit smoke test 與 Stage 2。 |
| `--overwrite` | 關閉 | 已存在輸出檔時仍重新產生。 |
| `--file-concurrency` | `1` | 同時處理幾個 Word 檔。地端模型資源有限時建議維持 `1`。 |
| `--word-request-concurrency` | `1` | 單一 Word job 對模型的請求併發。顯存有限時建議維持 `1`。 |
| `--word-requests-per-minute` | `60` | 單一 Word job 請求節流。 |
| `--header-footer-exclude-pattern` | 無 | 用 regex 排除頁首頁尾指定文字，可重複傳入。 |
| `--header-footer-font-size` | 繼承原文 | 指定頁首頁尾譯文字體大小。 |
| `--header-footer-term` | 無 | 固定頁首頁尾欄位翻譯，格式為 `來源=譯文`，例如 `號碼=No.`。 |
| `--exclude-table-index` | 無 | 排除第 N 個 body top-level table，可重複傳入。 |
| `--report-dir` | `output_dir` | 指定報表輸出資料夾。 |

## Smoke-test-first 流程

大量執行前先用一個小資料夾做 smoke test：

```bash
uv run scripts/word_local_batch_translate.py sample_input sample_output \
  --base-url http://192.168.12.63:8000/v1 \
  --api-key sk-local \
  --model minicpm5-1b \
  --glossary-library-id 2 \
  --translate-tables true \
  --stage-2-enabled true \
  --file-concurrency 1 \
  --word-request-concurrency 1 \
  --word-requests-per-minute 30 \
  --header-footer-font-size 8 \
  --header-footer-term "號碼=No." \
  --header-footer-term "頁次=Page"
```

Smoke test 會先檢查：

- Stage 1 翻譯模型可以回應。
- Stage 2 post-edit 模型可以回應；若 `--disable-stage-2` 或 `--stage-2-enabled false`，則不檢查 Stage 2。
- Department Glossary ID 存在且為啟用狀態。

若 smoke test 失敗，runner 會在執行任何 Word 檔案前停止。

## `.doc` 轉檔預檢

`.doc` 是舊式二進位 Word 格式，實際翻譯前會轉成 `.docx`。因 `.doc` 轉 `.docx` 可能影響頁首、頁尾、表格或定位，建議先執行一份樣本：

1. 選一份具有頁首頁尾、表格與代表性章節編號的 `.doc`。
2. 只放入 `sample_input`。
3. 執行 smoke-test-first 指令。
4. 開啟輸出的 `.docx`，確認頁首頁尾位置、表格、字距、換行與雙語段落可接受。
5. 若版面不可接受，先人工轉成 `.docx` 後再交給 runner。

若要檢查巢狀表格，可先執行：

```bash
uv run scripts/check_word_nested_tables.py sample_input --include-header-footer
```

## 大量執行範例

```bash
uv run scripts/word_local_batch_translate.py input_docs output_docs \
  --base-url http://192.168.12.63:8000/v1 \
  --api-key sk-local \
  --model qwen3.6-35b-a3b \
  --glossary-library-id 2 \
  --translate-tables true \
  --stage-2-enabled true \
  --file-concurrency 1 \
  --word-request-concurrency 1 \
  --word-requests-per-minute 30 \
  --header-footer-exclude-pattern "^U[A-Z]+-[0-9]+$" \
  --header-footer-font-size 8 \
  --header-footer-term "號碼=No." \
  --header-footer-term "頁次=Page"
```

若某份文件第一個 body 表格是封面或頁首樣式容器，不希望翻譯該表格，可加入：

```bash
--exclude-table-index 1
```

## 報表解讀

執行完成後，runner 會輸出：

- `word_batch_report.json`
- `word_batch_report.csv`

報表中的重點欄位：

| 欄位 | 說明 |
|---|---|
| `scanned` | 掃描到的 `.doc` / `.docx` 數量。 |
| `planned` | 實際排入執行的檔案數。 |
| `skipped` | 因輸出檔已存在而略過的數量。 |
| `failed` | 失敗檔案數。 |
| `status` | 單檔狀態，例如 `completed`、`failed`、`skipped_existing`。 |
| `job_id` | 對應 Word job ID，可用來回查 job 目錄。 |
| `error` | 單檔失敗原因。 |
| `glossary_*` | 本次使用的 Department Glossary metadata。 |
| `layout_mode` | 固定為 `bilingual_below`。 |
| `translate_tables` | 本次是否翻譯表格。 |
| `stage_2_enabled` | 本次是否啟用 Stage 2。 |

單檔失敗不會中斷整批；runner 會繼續處理下一個檔案，並在報表中保留失敗原因。

## 輸出與 job 目錄檢查

輸出檔命名規則：

```text
來源檔名_en.docx
```

例如：

```text
procedure.doc -> procedure_en.docx
procedure.docx -> procedure_en.docx
```

每個成功或失敗的檔案都有對應 `job_id`。可依 `job_id` 檢查 `out/word_overlay/<job_id>/`，常用檢查項目包含：

- `output.docx`
- `source.doc` 或 `source.docx`
- `*.converted.docx`
- `word_stage_2_post_edit.json`
- `realtime_debug/chunks/*`
- job state / metadata 檔案

## 單份樣本人工驗收清單

大量執行前，至少用一份代表性文件完成以下人工驗收：

- 開啟輸出 `.docx`，確認原文仍保留，譯文位於原文下方。
- 確認中文與既有英文混合段落沒有被不必要地重翻。
- 確認表格內容依 `--translate-tables` 設定處理。
- 確認頁首頁尾是否依設定翻譯、排除或套用固定詞。
- 確認頁首頁尾譯文字體大小與間距不造成跑版。
- 確認章節編號如 `3.1`、`(1)`、`A.` 不會在譯文段落中重複或接續編號。
- 確認 Department Glossary 指定術語有被套用，且沒有被 Stage 2 改成 synonym 或拼錯。
- 確認地端模型沒有產生中文夾雜、空白異常、錯字或明顯 hallucination。
- 確認 `word_stage_2_post_edit.json` 中 `stage_1_draft`、`stage_2_revised`、`fallback_reason` 與 `validation_warnings` 符合預期。
- 確認 `word_batch_report.json` / `.csv` 的 scanned、planned、skipped、failed 與實際檔案數一致。

## 失敗處理

常見處理方式：

- `local model smoke test returned an empty response`：確認 model 名稱、endpoint、`enable_thinking` 支援與模型回應格式。
- Stage 2 smoke 失敗：可先用 `--disable-stage-2` 驗證 Stage 1 與 Word 寫回流程，再評估是否開啟 Stage 2。
- Glossary preflight 失敗：確認 `--glossary-library-id` 是否存在、啟用，並已匯入詞彙。
- `.doc` 轉檔跑版：先人工或 LibreOffice 轉成 `.docx`，再重新執行 runner。
- 部分表格未翻譯：檢查是否為巢狀表格，或是否被 `--exclude-table-index` 排除。
- 單檔失敗：先從 `word_batch_report.json` 找出 `job_id` 與 `error`，再檢查對應 job 目錄。
