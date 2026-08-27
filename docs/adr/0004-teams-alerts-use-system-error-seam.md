# Teams alerts use the system error seam

Status: accepted

Runtime operational alerts should be emitted from the existing system error recording seam instead of being posted from every exception handler. Teams alerts are a side effect of `record_system_error(...)`: they use a short synchronous webhook call, in-memory deduplication, and a whitelist payload so alert delivery cannot dominate the failing request or leak traceback details.

## Considered Options

- Post Teams messages directly from each `except` block. This is simple locally but creates duplicated policy, inconsistent payloads, and a higher risk of repeated alerts.
- Attach Teams delivery to logging. This catches broad failures but makes deduplication and domain fields such as `job_id`, `stage`, and `component` less explicit.
- Emit Teams alerts from `record_system_error(...)`. This keeps alert policy centralized and matches the system's existing web, worker, and pipeline error flow.

## Consequences

Only errors that are recorded as system errors are eligible for Teams alerts in the first implementation. `TEAMS_ALERT_ENABLED=true` without `TEAMS_ALERT_WEBHOOK_URL` is treated as disabled with a startup warning rather than a startup failure, because alert delivery must not prevent the translation system from starting. A CLI test command should bypass deduplication so operators can verify the Teams workflow on demand.
