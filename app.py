from __future__ import annotations

import os

os.environ.setdefault("APP_RUNTIME_ROLE", "web")

from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(port=5001, debug=True, threaded=True)
