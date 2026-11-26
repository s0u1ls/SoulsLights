#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script must run on macOS (Darwin)."
  exit 1
fi

source "macos/_find_python.sh"
PY="$(require_mac_python_tk)"

if [[ ! -d ".venv_mac" ]]; then
  "$PY" -m venv .venv_mac
fi
source .venv_mac/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements-mac.txt

python macos/make_icons.py
python build_mac.py

echo ""
echo "Done! Built:"
echo "  App: dist/SoulsLights.app"
echo "  DMG: dist/SoulsLights-macOS.dmg"
open dist/ || true
