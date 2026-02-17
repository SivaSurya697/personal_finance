#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: $PYTHON_BIN not found in PATH" >&2
  exit 1
fi

echo "Creating virtual environment at $VENV_DIR using $PYTHON_BIN"
"$PYTHON_BIN" -m venv "$VENV_DIR"

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "Upgrading pip/setuptools/wheel"
python -m pip install --upgrade pip setuptools wheel

echo "Installing project dependencies from requirements.txt"
pip install -r requirements.txt

echo "Done. Activate with: source $VENV_DIR/bin/activate"
