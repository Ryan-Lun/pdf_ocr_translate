from __future__ import annotations

import logging

from flask_login import LoginManager

from .services import job_store, startup_warmup

login_manager = LoginManager()



def init_app(app) -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
        )
    app.logger.setLevel(logging.INFO)
    login_manager.init_app(app)
    job_store.init_app(app)
    startup_warmup.init_startup_warmup()
