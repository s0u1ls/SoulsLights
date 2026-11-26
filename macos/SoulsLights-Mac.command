#!/usr/bin/env bash
# Double-click in macOS Finder (Right-Click -> Open on first run) to run SoulsLights
set -euo pipefail
cd "$(dirname "$0")/.."
source "macos/_find_python.sh"

PY="$(require_mac_python_tk)"

if [[ ! -d ".venv_mac" ]]; then
  echo "First-time setup: creating macOS environment & installing dependencies..."
  "$PY" -m venv .venv_mac
  source .venv_mac/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements-mac.txt
else
  source .venv_mac/bin/activate
fi

echo "Launching SoulsLights..."
python main.py
