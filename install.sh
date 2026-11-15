#!/bin/sh
# FORM installer: uv (if missing, with your OK) -> FORM with its own Python 3.12 -> `form setup`.
#   curl -LsSf https://raw.githubusercontent.com/kaizensx/form-studio/main/install.sh | sh
# Set FORM_SOURCE to install from somewhere else (a local checkout, a wheel, a fork).
set -eu
SOURCE="${FORM_SOURCE:-git+https://github.com/kaizensx/form-studio}"
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
has_tty() { (exec </dev/tty) 2>/dev/null; }
ask() {  # ask "question" -> 0 for yes; reads the terminal even when piped from curl
  printf '%s [Y/n] ' "$1"
  if has_tty; then read -r a </dev/tty || a=""; else a="${FORM_YES:-n}"; echo "$a (no terminal)"; fi
  case "$a" in n|N|no|No) return 1 ;; *) return 0 ;; esac
}

bold "FORM installer"
case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "FORM supports macOS and Linux. On Windows, use WSL."; exit 1 ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  echo "FORM installs with uv (Astral's Python package manager). It is not on this machine."
  if ask "Install uv now from https://astral.sh/uv?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; export PATH
  else
    echo "Install uv yourself (https://docs.astral.sh/uv/), then run this again."; exit 1
  fi
fi

bold "Installing FORM (first time: about 200 MB for the CAD kernel)"
uv tool install --force --python 3.12 "$SOURCE"
BIN="$(uv tool dir --bin)"
case ":$PATH:" in *":$BIN:"*) ;; *)
  echo "Note: $BIN is not on your PATH. Run: uv tool update-shell"; PATH="$BIN:$PATH" ;;
esac

bold "Checking this machine"
if has_tty; then "$BIN/form" setup </dev/tty; else "$BIN/form" setup --check; fi
