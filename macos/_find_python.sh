#!/usr/bin/env bash
# Shared helper to locate Python 3.10+ with working Tcl/Tk on macOS

find_mac_python_tk() {
  local candidates=(
    "${PYTHON_BIN:-}"
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
    "/opt/homebrew/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.11"
    "/usr/local/bin/python3"
    "$(command -v python3 2>/dev/null || true)"
  )
  for py in "${candidates[@]}"; do
    [[ -n "$py" && -x "$py" ]] || continue
    if "$py" -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >/dev/null 2>&1; then
      echo "$py"
      return 0
    fi
  done
  return 1
}

require_mac_python_tk() {
  local found=""
  if found="$(find_mac_python_tk)"; then
    echo "$found"
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    echo "Installing python@3.12 and python-tk@3.12 via Homebrew..." >&2
    brew install python@3.12 python-tk@3.12 >&2 || true
    if found="$(find_mac_python_tk)"; then
      echo "$found"
      return 0
    fi
  fi

  echo "" >&2
  echo "ERROR: Python 3.10+ with Tkinter is required on macOS." >&2
  echo "Download & install the official macOS installer from: https://www.python.org/downloads/macos/" >&2
  echo "(or run: brew install python@3.12 python-tk@3.12)" >&2
  osascript -e 'display alert "Python with Tkinter Required" message "Please install Python 3 from python.org/downloads/macos (or run: brew install python@3.12 python-tk@3.12), then run SoulsLights again."' >/dev/null 2>&1 || true
  return 1
}
