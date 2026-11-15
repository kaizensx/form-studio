#!/bin/sh
# FORM from a source checkout. Creates the environment on first run.
# ./run.sh            bench on http://127.0.0.1:4173
# ./run.sh mcp        MCP server over stdio
# ./run.sh state <p>  any CLI command
set -e
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo "FORM needs uv (https://docs.astral.sh/uv/). Install it with: brew install uv" >&2
  exit 1
fi
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install --quiet --python .venv/bin/python -r requirements.lock
uv pip install --quiet --python .venv/bin/python --no-deps -e .   # puts `form` and `form-mcp` in .venv/bin
exec .venv/bin/python -m form "${@:-serve}"
