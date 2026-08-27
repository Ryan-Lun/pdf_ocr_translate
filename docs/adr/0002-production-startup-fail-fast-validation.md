# Production startup validates required configuration and fails fast

Status: accepted

Production web and worker processes must refuse to start when required security settings or external service settings are missing or unsafe. The app has development-friendly defaults, including stub authentication, insecure cookie defaults, and default external OCR/layout endpoints, so production needs an explicit startup validation boundary rather than relying on operators to notice warnings.

## Considered Options

- Keep permissive defaults in all environments and document the risks. This makes deployments easy to start but allows unsafe production instances to run silently.
- Log warnings for unsafe production configuration. This is easier to bypass operationally and does not protect users when logs are missed.
- Fail fast in production with a shared validation service called by both web and worker startup paths. This makes incomplete deployments fail early and consistently.

## Consequences

Production validation should cover the secret key, authentication mode, cookie security, SQL Server configuration, OpenAI/Azure OpenAI configuration, OCR endpoint configuration, and PP-Structure endpoint configuration. There should be no insecure production bypass flag; non-production development and testing can keep lighter defaults.
