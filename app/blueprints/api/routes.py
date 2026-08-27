from __future__ import annotations

from .shared import (
    api_bp,
    auth_store,
    authz_service,
    batch,
    glossary,
    ocr,
)

# Import route modules for blueprint registration side effects.
from . import job_routes, template_routes, glossary_routes, editor_routes, download_routes, stream_routes  # noqa: F401,E501

__all__ = [
    "api_bp",
    "auth_store",
    "authz_service",
    "batch",
    "glossary",
    "ocr",
]
