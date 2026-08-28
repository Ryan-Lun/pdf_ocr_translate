# Alert eligibility focuses on external services and workers

Status: accepted

Teams Alert eligibility remains centered on `record_system_error(...)`, but the system should promote external-service retry exhaustion and worker/background process failures into that seam. The first expansion deliberately covers OpenAI/Azure OpenAI batch submit and poll final failures, realtime translation final failures, LDAP service failures, unsupported worker job types, and worker recovery/claim exceptions; it does not include user input errors, user cancellations, single retry attempts that later recover, startup warmup warnings, SQL persistence failures, or Teams webhook failures themselves.

## Consequences

Alert payloads should expose safe operational fields such as `external_service`, `deployment`, and `failure_kind` when they help operators route the problem, while continuing to exclude traceback details, credentials, and raw sensitive request data. External-service failures and worker failures should be ticketed separately because their seams and regression tests differ.
