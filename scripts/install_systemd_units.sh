#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_DIR="$APP_ROOT/deploy/systemd"
OUTPUT_DIR=""
INSTALL_MODE=0
UNIT_TARGET_DIR="/etc/systemd/system"
APP_USER="${APP_USER:-}"
APP_USER_EXPLICIT=0
ENV_FILE="$APP_ROOT/.env"
ENV_FILE_EXPLICIT=0
WEB_BIND="${WEB_BIND:-}"
WEB_WORKERS="4"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/install_systemd_units.sh [options]

Options:
  --output-dir PATH      Render unit files into PATH. Default: ./build/systemd
  --install              Install rendered unit files into /etc/systemd/system
  --unit-target-dir PATH Override install directory. Default: /etc/systemd/system
  --app-root PATH        Application root. Default: repo root
  --app-user USER        systemd User=. Default: owner of app root
  --env-file PATH        EnvironmentFile=. Default: <app-root>/.env
  --web-bind TARGET      Gunicorn bind. Default: unix:<app-root>/uo_regulations_translate.sock
  --web-workers N        Gunicorn worker count. Default: 4
  --help                 Show this help

Examples:
  bash scripts/install_systemd_units.sh --output-dir /tmp/translate-systemd
  sudo bash scripts/install_systemd_units.sh --install --app-root /home/NE025/pdf_ocr_translate
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --install)
      INSTALL_MODE=1
      shift
      ;;
    --unit-target-dir)
      UNIT_TARGET_DIR="$2"
      shift 2
      ;;
    --app-root)
      APP_ROOT="$2"
      shift 2
      ;;
    --app-user)
      APP_USER="$2"
      APP_USER_EXPLICIT=1
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      ENV_FILE_EXPLICIT=1
      shift 2
      ;;
    --web-bind)
      WEB_BIND="$2"
      shift 2
      ;;
    --web-workers)
      WEB_WORKERS="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

TEMPLATE_DIR="$APP_ROOT/deploy/systemd"

if [[ "$APP_USER_EXPLICIT" -eq 0 && -z "$APP_USER" ]]; then
  APP_USER="$(stat -c '%U' "$APP_ROOT")"
fi

if [[ "$ENV_FILE_EXPLICIT" -eq 0 ]]; then
  ENV_FILE="$APP_ROOT/.env"
fi

if [[ -z "$WEB_BIND" ]]; then
  WEB_BIND="unix:$APP_ROOT/uo_regulations_translate.sock"
fi

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$APP_ROOT/build/systemd"
fi

require_path() {
  local path="$1"
  local label="$2"
  if [[ ! -e "$path" ]]; then
    echo "$label not found: $path" >&2
    exit 66
  fi
}

require_path "$TEMPLATE_DIR" "Template directory"
require_path "$APP_ROOT/.venv/bin/gunicorn" "Gunicorn executable"
require_path "$APP_ROOT/.venv/bin/flask" "Flask executable"
require_path "$APP_ROOT/.venv/bin/python" "Python executable"
require_path "$ENV_FILE" "Environment file"

mkdir -p "$OUTPUT_DIR"

export APP_ROOT APP_USER ENV_FILE WEB_BIND WEB_WORKERS TEMPLATE_DIR OUTPUT_DIR

python3 - <<'PY_RENDER'
from __future__ import annotations

import os
from pathlib import Path

template_dir = Path(os.environ["TEMPLATE_DIR"])
output_dir = Path(os.environ["OUTPUT_DIR"])
mapping = {
    "APP_ROOT": os.environ["APP_ROOT"],
    "APP_USER": os.environ["APP_USER"],
    "ENV_FILE": os.environ["ENV_FILE"],
    "WEB_BIND": os.environ["WEB_BIND"],
    "WEB_WORKERS": os.environ["WEB_WORKERS"],
}

for template_path in sorted(template_dir.glob("*.template")):
    content = template_path.read_text(encoding="utf-8")
    for key, value in mapping.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    target_name = template_path.name.removesuffix(".template")
    (output_dir / target_name).write_text(content, encoding="utf-8")
    print(output_dir / target_name)
PY_RENDER

if [[ "$INSTALL_MODE" -eq 1 ]]; then
  mkdir -p "$UNIT_TARGET_DIR"
  install -m 0644 "$OUTPUT_DIR"/uo_regulations_translate.service "$UNIT_TARGET_DIR"/uo_regulations_translate.service
  install -m 0644 "$OUTPUT_DIR"/uo_regulations_translate_worker.service "$UNIT_TARGET_DIR"/uo_regulations_translate_worker.service
  "$SYSTEMCTL_BIN" daemon-reload
  echo "Installed unit files into $UNIT_TARGET_DIR"
  echo "Rendered with:"
  echo "  APP_ROOT=$APP_ROOT"
  echo "  APP_USER=$APP_USER"
  echo "  ENV_FILE=$ENV_FILE"
  echo "Installed units:"
  echo "  uo_regulations_translate.service"
  echo "  uo_regulations_translate_worker.service"
  echo "Next:"
  echo "  sudo systemctl enable uo_regulations_translate uo_regulations_translate_worker"
  echo "  sudo systemctl start uo_regulations_translate uo_regulations_translate_worker"
else
  echo "Rendered unit files into $OUTPUT_DIR"
fi
