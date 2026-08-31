# Glossary 自然語法人工驗收指引

## 目的

本指引用於驗證 Required Glossary Term 流程：Glossary 指定譯詞必須穩定出現在輸出中，但不應限制模型依目標語言自然調整詞序、介系詞、冠詞或周邊句法。

## 測試前準備

1. 進入 `/workspace/glossary`。
2. 新增或確認以下詞彙：

| 來源詞 | 指定譯詞 | 驗收目的 |
|---|---|---|
| 外觀 | Appearance | 單一術語與自然詞序 |
| 製程規範 | Process Specification | 多術語同句 |
| 檢查項目 | Inspection Item | heading、table cell、fragment |

3. 準備測試文件，內容至少包含：

```text
外觀形狀
外觀與製程規範
檢查項目
外觀 shape
外觀 ABC-123
```

其中 `ABC-123` 可作為 model number / project code / identifier 類型的 Exact Protected Content 檢查。

## Word 翻譯驗收

1. 從 Word 翻譯工作區上傳測試 `.docx`。
2. 目標語言選英文。
3. 執行翻譯。
4. 下載翻譯後 Word 檔。
5. 檢查輸出：

| Case | 預期 |
|---|---|
| `外觀形狀` | 必須包含 `Appearance`，但允許自然語序，例如 `shape of Appearance` 或其他不改變語意的寫法。 |
| `外觀與製程規範` | 必須同時包含 `Appearance` 與 `Process Specification`。 |
| `檢查項目` | 應保持 concise label，不應被展開成說明句。 |
| `外觀 ABC-123` | 必須包含 `Appearance`，且 `ABC-123` 不得被翻譯、改寫或拆開。 |

最終 Word 輸出不可出現 `<term id="...">` 或 `[[[GLOSSARY_TERM_...]]]`。

## PDF 原版面 OCR / Batch 翻譯驗收

1. 從 PDF 原版面 OCR 與翻譯流程上傳測試 PDF。
2. 啟用翻譯，目標語言選英文。
3. 若系統允許選擇翻譯模式，分別測 `batch` 與 `realtime`。
4. 翻譯完成後開啟 editor 或下載結果 PDF。
5. 檢查最終輸出：

- 命中的指定譯詞必須出現。
- `外觀 shape` 這類中英相鄰內容允許調整成自然英文詞序。
- `ABC-123`、URL、email、專案代碼、型號等真正不可修改字串必須保持原樣。
- 不可殘留 `<term id="...">` 或 `[[[GLOSSARY_TERM_...]]]`。

## Markdown / PDF 重建工作區驗收

1. 從 PDF 重建翻譯工作區上傳測試 PDF，或使用含相同文字的 markdown/html 測試文件。
2. 執行翻譯。
3. 檢查輸出 markdown/html/docx：

- heading、table cell、fragment 中的 glossary term 應保持簡潔標籤形式。
- 指定譯詞必須精確出現，不得改成 synonym。
- 最終輸出不可殘留 `<term id="...">` 或 legacy glossary token。

## Debug Payload 檢查

翻譯流程若有 debug artifact，檢查以下路徑：

```text
<job_dir>/realtime_debug/chunks/<chunk_id>/payload.txt
<job_dir>/realtime_debug/chunks/<chunk_id>/system_prompt.txt
<job_dir>/realtime_debug/chunks/<chunk_id>/parsed_translations.json
<job_dir>/output/realtime_debug/chunks/<chunk_id>/payload.txt
<job_dir>/output/realtime_debug/chunks/<chunk_id>/parsed_translations.json
```

驗收重點：

1. `payload.txt` 應可看到類似：

```text
<term id="0001">Appearance</term>形狀
```

2. `payload.txt` 不應再看到新的 glossary 命中被寫成：

```text
[[[GLOSSARY_TERM_0001::Appearance]]]
```

3. `system_prompt.txt` 應包含 Required Glossary Term 規則：

```text
The approved glossary term must be used exactly as written.
You may reposition the entire required glossary term when natural target-language syntax requires it.
Preserving the term does not require preserving its source-language position or surrounding source-language structure.
```

4. `parsed_translations.json` 不可殘留 `<term>` wrapper 或 legacy glossary token。

## 失敗判定

以下任一情況視為驗收失敗：

- 指定譯詞被改成 synonym，例如 `Appearance` 被改成 `Look`。
- 最終輸出缺少本次命中的 approved target。
- 最終輸出仍包含 `<term id="...">`。
- 最終輸出仍包含 `[[[GLOSSARY_TERM_...]]]`。
- 型號、代碼、URL、email 等 Exact Protected Content 被翻譯或改寫。
- heading、table cell、fragment 被不必要地展開成完整說明句。

## 對應自動化測試

主要回歸測試位於：

```text
tests/test_required_glossary_natural_syntax.py
```

相關既有測試位於：

```text
tests/test_glossary_cache.py
tests/test_word_translate.py
tests/test_batch_dedup.py
tests/test_markdown_translate_html.py
tests/test_realtime_translate.py
```
