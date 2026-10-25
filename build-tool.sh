#!/bin/sh
# Starts the Kobe by Daylight Builder. First run creates build/venv (Python + PySide6).
#   ./build-tool.sh                          builder window
#   ./build-tool.sh --build linux windows    build from the terminal
set -e
cd "$(dirname "$0")"
VENV=build/venv
if [ ! -x "$VENV/bin/python" ]; then
    echo "First start: creating $VENV ..."
    python3 -m venv "$VENV"
fi
if ! "$VENV/bin/python" -c "import PySide6" 2>/dev/null; then
    echo "Installing PySide6 for the builder ..."
    mkdir -p build/tmp
    TMPDIR="$PWD/build/tmp" "$VENV/bin/python" -m pip install --disable-pip-version-check -q PySide6
fi
exec "$VENV/bin/python" -m builder "$@"
