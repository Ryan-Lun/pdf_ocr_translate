from __future__ import annotations


def register_before_request(app) -> None:
    @app.before_request
    def _noop_before_request():
        return None
