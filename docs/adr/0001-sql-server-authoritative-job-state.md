# SQL Server is the authoritative job state source

Status: accepted

Job queue ownership, access control, auditability, and worker coordination already depend on SQL Server, so job status must converge on SQL Server as the authoritative source. Filesystem JSON status files remain useful as debug snapshots and legacy fallback, but new job behavior should not treat them as the source of truth.

## Considered Options

- Keep SQL Server and filesystem JSON as equal sources of truth. This preserves current behavior but allows drift between job lists, job detail pages, worker state, and downloaded artifacts.
- Make filesystem JSON authoritative and use SQL Server only as an index. This conflicts with the existing SQL-backed queue claim, owner access checks, audit records, and worker recovery behavior.
- Make SQL Server authoritative and demote JSON to snapshots or legacy fallback. This matches the existing queue and authorization architecture while allowing old jobs to remain recoverable.

## Consequences

State-writing code should update SQL Server first, then write JSON snapshots second. A failed snapshot write must not invalidate the authoritative SQL state. Legacy JSON fallback may exist as a read-only compatibility path, but it should not be extended as the normal path for new jobs.
