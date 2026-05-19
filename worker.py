from __future__ import annotations

import os

os.environ["APP_RUNTIME_ROLE"] = "worker"

from app import create_app
from app.services.worker import run_worker_loop

app = create_app()


if __name__ == "__main__":
    with app.app_context():
        run_worker_loop()
