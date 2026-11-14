#!/usr/bin/env bash
set -e
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$HERE/.venv/bin/python" ]]; then
  PY="$HERE/.venv/bin/python"
else
  PY="$(command -v python3)"
fi
exec "$PY" "$HERE/conv_gui.py" "$@"
