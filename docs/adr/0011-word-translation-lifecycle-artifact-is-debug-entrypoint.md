# Word translation lifecycle artifact is the debug entrypoint

Word translation manual debugging should start from `word_translation_lifecycle.json` in the job root. This artifact links each item id to Stage 1 output, Stage 2 result or fallback, final translation provenance, writeback ids, glossary summary, Translation Memory summary, fixed header/footer translations, post-process actions, and discarded items.

**Decision**

Use the job-root `word_translation_lifecycle.json` as the first artifact for Word translation troubleshooting. Treat `word_stage_2_post_edit.json` as Stage 2 post-edit debug output only, not as the final source of truth. Canonical Word debug artifacts live in `out/word_overlay/<job_id>/`; `output/` is reserved for produced deliverables and should not be used as a mirrored debug artifact location.

**Rationale**

Word translation can produce several related records for the same source text: Stage 1 draft, Stage 2 post-edit output, final translation after fallback or repair, and one or more writebacks when repeated source/core text appears in the document. Stage 2 may be disabled, skipped by TM exact match, rejected by validation, superseded by fixed header/footer rules, or repaired before writeback. A Stage 2 artifact alone cannot explain these cases, and using it as final truth makes manual debugging misleading.

**Consequences**

Manual checks should follow the lifecycle artifact first, then drill into `word_writeback_map.json`, `word_final_translations.json`, `word_stage_1_translations.json`, `word_stage_2_post_edit.json`, and `realtime_debug/` only when needed. This adds one canonical summary artifact but avoids duplicating debug artifacts under `output/`. It does not change translation quality, prompt behavior, Translation Memory priority, Glossary enforcement, or Word layout semantics.
