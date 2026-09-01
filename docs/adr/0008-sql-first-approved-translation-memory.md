# SQL-first approved Translation Memory

Translation Memory entries should be stored as SQL-first approved source-to-target segment translations, not as an expanded JSON-file cache. Retrieval may directly reuse only exact matches for the same language direction and document mode, while fuzzy and future semantic matches are non-authoritative references for the language model; glossary terminology remains the stronger lexical constraint.

**Consequences**

AI-generated translations are not automatically promoted into reusable Translation Memory. First-phase TM writes come from explicit human-confirmation paths and controlled CSV import, with debug artifacts recording exact matches and references so skipped LLM calls can be audited.
