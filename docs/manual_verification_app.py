from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("APP_RUNTIME_ROLE", "web")
os.environ["APP_ENV"] = "testing"
os.environ["AUTH_ENABLED"] = "0"
os.environ["AUTO_SCHEMA_MANAGEMENT"] = "1"
os.environ["OWNER_ACCESS_ENABLED"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.config import TestingConfig

TestingConfig.OWNER_ACCESS_ENABLED = False

app = create_app("testing")


if __name__ == "__main__":
    app.run(port=5011, debug=False, threaded=True)
