# Word translation removes LLM quality assessment

Status: accepted

Word translation no longer uses a second LLM call to assess translation quality, and Word jobs no longer produce or display quality-score metadata. The runtime retry boundary is now limited to concrete translation failures: request exceptions, blank responses, and invalid translation responses. The `WORD_QUALITY_MODEL` configuration remains accepted for now so existing deployment environments can keep their current configuration without blocking startup or rollback.

## Considered Options

- Keep LLM quality assessment and quality-based retry. This preserves automatic quality scores, but it adds cost, latency, another model dependency, and a second prompt/runtime path that can fail independently of translation.
- Remove LLM quality assessment entirely from Word translation runtime. This lowers cost and latency, simplifies the flow, and removes quality-evaluator failures, but it also removes automatic quality scores and quality-threshold retry.
- Remove runtime quality assessment while temporarily accepting `WORD_QUALITY_MODEL`. This gives the simpler runtime behavior now while avoiding unnecessary deployment churn for environments that already define the setting.

## Consequences

Word translation should return translated text rather than a translation plus quality score. Word batch translation should expose source-to-translation mappings, not per-item quality scores. New Word job metadata and workspace rendering should not introduce `avg_quality` or `品質: x/40`, while legacy jobs that already contain old quality metadata may remain readable for compatibility.

Retries should not be driven by subjective quality scoring. A Word translation retry should happen only when the translation request fails, the model returns blank content, or the translated content matches the invalid-response guard. Prompt and test cleanup should remove the remaining quality-prompt surface without reintroducing runtime quality evaluation.
