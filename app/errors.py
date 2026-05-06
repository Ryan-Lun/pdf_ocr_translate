from __future__ import annotations

from werkzeug.exceptions import HTTPException


def register_error_handlers(app) -> None:
    def handle_http_exception(error: HTTPException):
        return error

    app.register_error_handler(HTTPException, handle_http_exception)
