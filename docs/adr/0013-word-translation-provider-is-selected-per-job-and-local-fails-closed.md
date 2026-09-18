# Word translation provider is selected per job and local fails closed

Word original-layout translation jobs select either the Cloud Translation Provider or the Local Translation Provider at submission time, with cloud remaining the default. The job stores only the selected provider and model snapshot; endpoint and credentials remain server-managed configuration resolved by the worker. We chose per-job selection over a global switch so cloud and quality-document workflows can coexist without queued jobs changing behavior when deployment settings change.

The first phase applies only to Word original-layout translation. A local job uses the same Local Translation Provider for Stage 1 and Stage 2, is limited to the validated Traditional Chinese-to-English direction, and must not fall back automatically to cloud when the local service fails. This fail-closed boundary prevents documents selected for local processing from leaving the approved environment without explicit user action.

Local configuration completeness is validated at production startup, but endpoint reachability is checked through normal job execution so a temporary local outage does not prevent the web application or worker from starting. Local retry exhaustion is recorded through the existing System Error and Alert boundary, while a Stage 2-only failure may retain the valid Stage 1 translation with a warning.
