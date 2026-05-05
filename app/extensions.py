from __future__ import annotations

import logging

from .services import job_store, startup_warmup


def init_app(app) -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
        )
    app.logger.setLevel(logging.INFO)
    job_store.init_app(app)
    startup_warmup.init_startup_warmup()
