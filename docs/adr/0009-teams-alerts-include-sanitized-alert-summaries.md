# Teams alerts include sanitized alert summaries

Status: accepted

Teams Alerts should include an Alert Summary so operators can understand the likely failure without opening logs first. The summary may come from an explicitly supplied operational summary or, as a fallback, a sanitized and truncated exception message; it is also appended to the alert message because some Teams workflows display only the message field. It must continue to exclude traceback details, credentials, raw request bodies, and full URLs with query data.
