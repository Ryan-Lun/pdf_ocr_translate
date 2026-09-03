# Stage 2 兩階段翻譯設定與驗收指引

## 目的

本指引用於安全啟用、關閉與驗收 Stage 2 兩階段翻譯。Stage 2 的目標是降低英文翻譯的 AI 直譯感與 translationese，使輸出更接近專業人士直接以英文撰寫，同時不得破壞原始語意、技術資訊、Glossary 指定術語、protected content、數字事實值與 must / should / may 等語意強度。

Stage 2 不是新的翻譯 pipeline。它接在既有 Stage 1 翻譯之後，將 Stage 1 draft 交給 translation post-edit service 檢查，只在必要時修正不自然英文。

## 設定參數

Stage 2 設定由 `.env` 載入，並透過 `app/services/state.py` 與 Flask config 暴露；feature flag 預設為關閉。

| 參數 | 預設值 | 說明 | 建議 |
|---|---:|---|---|
| `TRANSLATION_POST_EDIT_ENABLED` | `0` | Stage 2 feature flag。接受 `1`、`true`、`yes`、`on` 為啟用，其餘值視為關閉。 | production 初期先維持關閉，完成抽樣驗收後再開啟。 |
| `TRANSLATION_POST_EDIT_MODEL` | `WORD_TRANSLATE_MODEL` | Stage 2 使用的模型或 Azure deployment 名稱。若未設定，會沿用 Word 翻譯模型。 | 建議使用穩定且成本可接受的翻譯/編輯模型。 |
| `TRANSLATION_POST_EDIT_DEPLOYMENT` | 空值 | `TRANSLATION_POST_EDIT_MODEL` 的替代名稱。 | 若團隊用 deployment 命名管理 Azure OpenAI，可用此參數。 |
| `TRANSLATION_POST_EDIT_TEMPERATURE` | `0.0` | Stage 2 post-edit temperature。 | 建議 production 使用 `0.0`，降低不必要改寫。 |
| `TRANSLATION_POST_EDIT_MAX_TOKENS` | `6000` | Stage 2 回應 token 上限。 | 文件 segment 較長時才調高。 |

設定範例：

```env
TRANSLATION_POST_EDIT_ENABLED=true
TRANSLATION_POST_EDIT_MODEL=<your-post-edit-deployment>
TRANSLATION_POST_EDIT_TEMPERATURE=0
TRANSLATION_POST_EDIT_MAX_TOKENS=6000
```

注意：`true` 必須拼對。若誤寫成 `ture`，系統會視為關閉。

## Production rollout 建議

1. 第一階段先在測試環境啟用 `TRANSLATION_POST_EDIT_ENABLED=true`。
2. 使用固定 Word、PDF batch、PDF Markdown 測試文件各跑一次。
3. 檢查 artifact 中的 Stage 1 draft、Stage 2 revised、changed status、fallback reason 與 validation warning。
4. 抽樣確認 Stage 2 只改善 translationese，沒有改變技術事實或語意強度。
5. production 先對小批量文件開啟，保留人工比對紀錄。
6. 若出現過度改寫、術語被替換或 validation fallback 比例偏高，先關閉 flag，保留 artifact 回報問題。

## 關閉時行為

Stage 2 關閉時系統會維持既有單階段翻譯行為：

```text
Source Segment
↓
Glossary / protected content / Translation Memory reference
↓
Stage 1 LLM Translation
↓
Final Translation
```

此時不會呼叫 Stage 2 model，也不會產生 Stage 2 post-edit artifact。

## 啟用時流程

Stage 2 啟用後，會在既有 Stage 1 翻譯後執行：

```text
Source Segment
↓
Stage 1 Faithful Translation
↓
Stage 1 draft
↓
Stage 2 Translationese / Naturalness Revision
↓
Validation
├─ pass: 使用 Stage 2 revised
└─ fail: fallback 到 Stage 1 draft
↓
Final Translation
```

Stage 2 的輸入包含 original source、Stage 1 draft、Required Glossary Term 與 Exact Protected Content。Stage 2 的輸出必須是 JSON object，不能改 id、合併 segment、拆分 segment 或加入說明。

## 套用範圍

目前 Stage 2 套用於：

| 流程 | 套用時機 | Artifact |
|---|---|---|
| Word 翻譯 | Word Stage 1 翻譯完成後、寫回 DOCX 前 | `word_stage_2_post_edit.json` |
| PDF 原版面 batch 翻譯 | Azure batch 結果解析後、合併到 PDF editor payload 前 | `pdf_batch_stage_2_post_edit.json` |
| PDF 重建 / Markdown 翻譯 | Markdown/HTML text node 翻譯後、寫入輸出前 | `pdf_markdown_stage_2_post_edit.json` |

Quick 模式是否套用 Stage 2 另由獨立 issue 評估，尚未列入本指引的正式 production 驗收。

## Translation Memory 關係

TM Exact Match 代表系統找到已核准的 Approved Translation，可直接作為正式翻譯使用。這類 segment 會直接套用 TM，不會再送 Stage 1，也不會再送 Stage 2。

原因是 TM Exact Match 的來源是人工確認或正式匯入的翻譯記憶，不應再被模型改寫。

Fuzzy / Semantic TM reference 只會作為 Stage 1 參考，不會直接當成最終翻譯。若該 segment 最後進入 Stage 1 LLM 翻譯，才會接續進入 Stage 2。

Stage 2 輸出不會自動寫入 Translation Memory。TM 仍需人工確認或正式匯入，避免 AI 產生或 Stage 2 改寫後的錯誤翻譯被自動累積。

## Artifact 位置

Word job 完成後檢查：

```text
out/word_overlay/<job_id>/word_stage_2_post_edit.json
```

PDF 原版面 batch job 完成後檢查：

```text
out/pdf_overlay/<job_id>/pdf_batch_stage_2_post_edit.json
```

PDF 重建 / Markdown job 完成後檢查：

```text
<job_dir>/pdf_markdown_stage_2_post_edit.json
```

常見預設位置是：

```text
out/jobs/<job_id>/pdf_markdown_stage_2_post_edit.json
```

實際 job root 可能依部署設定不同，請以該 job 的 `job_dir` 為準。Artifact 位於 job 目錄根層，不在 `output/` 子目錄內。

## Artifact 欄位

每個 artifact 會包含 per-segment records：

| 欄位 | 說明 |
|---|---|
| `id` | Segment id 或 batch custom id。 |
| `source_text` | 原文 segment。 |
| `stage_1_draft` | Stage 1 LLM 產生的 faithful translation draft。 |
| `stage_2_revised` | Stage 2 回傳的 revised translation。若 Stage 2 沒有修改，可能與 Stage 1 相同。 |
| `final_text` | 實際寫入輸出的翻譯。validation pass 時通常等於 `stage_2_revised`；fallback 時等於 `stage_1_draft`。 |
| `changed` | Stage 2 是否提出不同於 Stage 1 的文字。 |
| `used_fallback` | 是否 fallback 到 Stage 1。 |
| `fallback_reason` | fallback 原因，例如 missing required term、protected text 被改、semantic force 改變、Stage 2 模型失敗。 |
| `validation_warnings` | validation 發現的警告或阻擋原因。 |

人工檢查時優先看：

1. `changed=true` 的 segment 是否真的降低 translationese。
2. `used_fallback=true` 的 segment 是否合理保護 Accuracy 邊界。
3. `validation_warnings` 是否指出 Required Glossary Term、Exact Protected Content、numbers、dates、units、factual values 或 must / should / may 問題。

## Validation guardrails

Stage 2 revised 會再次驗證以下項目。任何 unsafe revision 都會 fallback 到 Stage 1 draft。

| Guardrail | 驗證目的 | 常見 fallback reason |
|---|---|---|
| Required Glossary Term | 指定術語不得被 synonym 取代，也需保留命中次數。 | `missing_required_glossary_term:<term>` |
| Exact Protected Content | URL、email、mask token、model number、project code 等不可修改字串需保留。 | `missing_protected_text:<value>` |
| Protected order | 多個 protected token 不可被重排到不合法順序。 | `protected_text_order_changed:<value>` |
| numbers、dates、units、factual values | 數字、日期、單位、版本號、貨幣等事實值需保留。 | `missing_protected_text:<value>` |
| must / should / may | obligation / permission / prohibition 不可被弱化或強化。 | `semantic_force_changed:<marker>` |
| JSON/id structure | Stage 2 不可缺 id、增加未知 id、回空值或非 JSON。 | `missing_output_id`、`unexpected_output_id:<id>`、`empty_output`、`post_edit_error:<type>` |

## 人工驗收案例

### Case 1: technically accurate but translationese draft 被改善

Source：

```text
執行雷射刻印前，操作員必須確認首件半成品尺寸是否符合製程規範。
```

Stage 1 draft 可能為：

```text
Before performing Laser Marking, operators must confirm whether the dimensions of the first semi-finished product conform to the process specification.
```

可接受的 Stage 2 revised：

```text
Before performing Laser Marking, operators must confirm that the dimensions of the first semi-finished product comply with the process specification.
```

驗收重點：語意與 must 保持不變，但 `confirm whether ... conform to` 這類直譯感被改善。

### Case 2: already-natural draft 不應被 stylistic variety 改寫

Source：

```text
操作員必須穿戴乾淨棉手套。
```

Stage 1 draft：

```text
Operators must wear clean cotton gloves.
```

預期 Stage 2 revised 應維持相同或只有必要微調。若只是為了風格變化改成完全不同句型，應視為不理想。Artifact 中 `changed=false` 是可接受結果。

### Case 3: Required Glossary Term 不可被 synonym 取代

Glossary：

```text
外觀 -> Appearance
```

Source：

```text
確認外觀是否符合規範。
```

若 Stage 2 將 `Appearance` 改成 `look`、`visual condition` 或其他 synonym，validation 應 fallback 到 Stage 1，並在 `validation_warnings` 顯示 `missing_required_glossary_term:Appearance`。

### Case 4: Exact Protected Content / model number / project code 不可被修改

Source：

```text
確認 ABC-123 與 PROJECT-X9 標示是否清楚。
```

預期：`ABC-123`、`PROJECT-X9` 必須完整保留，不得變成 `ABC123`、`Project X9` 或被翻譯。

### Case 5: numbers、dates、units、factual values 不可被修改

Source：

```text
2026-09-02 檢查 10 mm 間隙，費用為 NT$1,200，版本為 v1.2。
```

預期：`2026-09-02`、`10 mm`、`NT$1,200`、`v1.2` 必須保留。若 Stage 2 改為 `12 mm`、`2026/09/02` 或移除貨幣值，應 fallback 到 Stage 1。

### Case 6: must / should / may 不可改變

Source：

```text
操作員必須確認設備狀態。
```

Stage 1 draft：

```text
Operators must confirm the equipment status.
```

若 Stage 2 改成：

```text
Operators should confirm the equipment status.
```

應 fallback 到 Stage 1，因為 must 被弱化為 should。

另需測試 prohibition：

```text
Operators must not remove this label.
```

不得被改成：

```text
Operators must remove this label.
```

### Case 7: Stage 2 failure 或 validation failure 時 fallback 到 Stage 1

可用以下方式人工測試：

1. 暫時將 `TRANSLATION_POST_EDIT_MODEL` 設為不存在的 deployment，或讓 Stage 2 model request timeout。
2. 執行一個小型 Word job。
3. 確認輸出仍使用 Stage 1 draft。
4. 檢查 `word_stage_2_post_edit.json` 中：

```json
{
  "used_fallback": true,
  "fallback_reason": "post_edit_error:<ErrorType>"
}
```

若是 validation failure，`fallback_reason` 應顯示實際 guardrail，例如 `missing_protected_text:10 mm` 或 `semantic_force_changed:must`。

## 回報問題時需附上的資訊

回報 Stage 2 問題時，請至少提供：

1. job id 與流程類型：Word、PDF batch 或 PDF Markdown。
2. `.env` 中 Stage 2 相關設定，但不得貼出 API key。
3. 對應 artifact 中該 segment 的 `source_text`、`stage_1_draft`、`stage_2_revised`、`final_text`、`used_fallback`、`fallback_reason`、`validation_warnings`。
4. 若問題是過度改寫，標出哪個 technical information、component name、factual value 或 semantic force 被改變。
5. 若問題是沒有改善 translationese，提供你認為較自然且仍保留 accuracy 的建議譯文。

## 失敗判定

以下情況視為驗收失敗：

- Stage 2 開啟且 segment 有進入 LLM 翻譯，但沒有產生對應 artifact。
- `stage_2_revised` 改善自然度的同時新增、刪除或泛化 technical details。
- Required Glossary Term 被 synonym 取代但沒有 fallback。
- Exact Protected Content、model number、project code、URL、email、mask token 被修改但沒有 fallback。
- numbers、dates、units、factual values 被修改但沒有 fallback。
- must / should / may、obligation、permission、prohibition 被改變但沒有 fallback。
- Stage 2 model failure 導致 job 失敗，而不是 fallback 到 Stage 1。

## 對應自動化測試

主要測試位於：

```text
tests/test_translation_post_edit.py
tests/test_word_translate.py
tests/test_batch_dedup.py
tests/test_markdown_translate_html.py
tests/test_stage_2_manual.py
```

測試涵蓋 artifact 寫入、validation success、validation failure fallback、semantic-force fallback、Word/PDF/Markdown artifact 與文件內容檢查。
