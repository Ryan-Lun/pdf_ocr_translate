# PDF OCR Translate

This context defines the operational language used by the PDF OCR translation system. It keeps domain terms stable across code, operations, and architecture discussions.

## Language

**Alert**:
A runtime operational signal sent to administrators when a system-level error or external-service retry exhaustion needs attention. Alerts are distinct from normal user-facing job status updates.
_Avoid_: Notification, Incident, Message

**Alert Summary**:
A safe, human-readable description inside an Alert that helps administrators quickly understand the likely failure. It is distinct from raw traceback data or unfiltered exception details.
_Avoid_: Raw exception, Traceback, Debug log

**System Error**:
An operational error record for failures that need administrator visibility, including external-service retry exhaustion and background-process failures. System Errors are the eligibility boundary for Alerts.
_Avoid_: Job failure, Debug error, User error

**External-Service Retry Exhaustion**:
A final failure state reached after retryable calls to an external dependency can no longer recover within the current job or operation. Single retry attempts are not System Errors unless the operation ultimately fails.
_Avoid_: Single timeout, Transient warning

**Background-Process Failure**:
A worker or background job orchestration failure that prevents queued work from being claimed, recovered, dispatched, or completed correctly. It is distinct from a user-facing validation failure or cancellation.
_Avoid_: User cancellation, Upload error

**Required Glossary Term**:
An approved glossary translation that must appear exactly as the chosen target-language term while allowing the surrounding sentence syntax to be translated naturally.
_Avoid_: Hint, synonym, protected content

**Required Glossary Variant**:
A controlled inflection of a Required Glossary Term that may be accepted only during Stage 2 post-edit validation when grammatically necessary, without changing the approved lexical family. It is not a synonym, replacement term, or relaxation for Exact Protected Content.
_Avoid_: Synonym, free rewrite, glossary override

**Glossary Validation Type**:
The approved validation policy assigned to a Department Glossary entry, deciding whether that entry is enforced as strict terminology, checked as lexical terminology, or shown only as reference terminology. It is part of glossary governance, not a model-generated runtime guess.
_Avoid_: AI classification, prompt hint, glossary priority

**Strict Required Glossary Term**:
A Required Glossary Term whose approved target-language term must be present under the existing hard validation behavior. It is used for official titles, organization names, product families, and other terms where omission should remain a blocking glossary failure.
_Avoid_: Soft term, lexical hint, reference term

**Lexical Required Glossary Term**:
A Required Glossary Term whose approved lexical choice must be preserved, while deterministic case and inflection matches may be accepted without blocking the translation job. It is not permission to replace the term with a synonym or change the technical meaning.
_Avoid_: Synonym, reference-only term, exact protected content

**Reference-Only Glossary Term**:
A Department Glossary entry shown to the translator as preferred terminology but not wrapped as a Required Glossary Term and not validated as required output. It remains part of the Effective Glossary for traceability.
_Avoid_: Required term, soft failure, ignored glossary entry

**Glossary Soft Match**:
A non-blocking validation result where a Lexical Required Glossary Term did not appear exactly but was matched by an allowed deterministic case or inflection rule. It must be recorded for review rather than treated as a missing required term.
_Avoid_: Accepted synonym, exact match, hard pass

**Glossary Soft Miss**:
A non-blocking validation result where a Lexical Required Glossary Term did not appear exactly and no allowed deterministic soft match was found. It is a review signal, not a job-stopping failure.
_Avoid_: Missing required glossary term, hard failure, system error

**Department Glossary**:
A glossary library scoped to a department's approved terminology, selected so terms from different departments are not mixed in the same translation job.
_Avoid_: System glossary, global glossary, personal glossary

**Selected Department Glossary**:
The one Department Glossary explicitly chosen for a new user-facing translation job. Editor retranslation and background processing for that job must keep using this selected glossary so document terminology remains consistent.
_Avoid_: Default glossary, merged department glossaries, current UI option

**Department Glossary Library Code**:
A stable, non-editable identifier for a Department Glossary once the library has been created. Display names may change, but historical job traceability must not depend on changing this code.
_Avoid_: Display name, department label, mutable title

**Glossary Audit Event**:
An append-only record of a Department Glossary library or entry change, including actor, action, target, timestamp, and before/after values for traceability.
_Avoid_: Job usage log, debug artifact, changelog

**Effective Glossary**:
The set of glossary entries actually applied to a translation job after the selected Department Glossary and any allowed override rules are resolved.
_Avoid_: All glossary entries, Translation Memory, glossary database

**Exact Protected Content**:
Source content that must remain byte-for-byte unchanged in the translated output, such as user-defined do-not-translate terms, identifiers, model numbers, URLs, and email addresses.
_Avoid_: Required glossary term, terminology preference

**Translation Memory**:
Approved source-to-target segment translations that can be reused or referenced by later translation jobs with the same language direction.
_Avoid_: Glossary, Translation cache, Draft translation history

**Approved Translation**:
A human-confirmed or otherwise formally accepted translation that is eligible to become Translation Memory.
_Avoid_: AI draft, Raw model output, Unreviewed translation

**TM Exact Match**:
A Translation Memory match where the current source segment matches a stored approved source segment closely enough to reuse its target translation without calling the language model.
_Avoid_: Fuzzy match, Reference match

**TM Reference**:
A similar approved Translation Memory entry shown to the language model for consistency guidance while translating the current source segment.
_Avoid_: Exact match, Required glossary term, Automatic replacement
