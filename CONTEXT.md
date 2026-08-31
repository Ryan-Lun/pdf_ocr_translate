# PDF OCR Translate

This context defines the operational language used by the PDF OCR translation system. It keeps domain terms stable across code, operations, and architecture discussions.

## Language

**Alert**:
A runtime operational signal sent to administrators when a system-level error or external-service retry exhaustion needs attention. Alerts are distinct from normal user-facing job status updates.
_Avoid_: Notification, Incident, Message

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

**Exact Protected Content**:
Source content that must remain byte-for-byte unchanged in the translated output, such as user-defined do-not-translate terms, identifiers, model numbers, URLs, and email addresses.
_Avoid_: Required glossary term, terminology preference
