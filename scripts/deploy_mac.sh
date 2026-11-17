#!/bin/sh
# Build Form Studio for this Mac, check the built app, and install it in /Applications.
#
#   scripts/deploy_mac.sh                 # build, smoke test, install (keeps a backup of the installed app)
#   BACKUP_DIR=~/somewhere scripts/deploy_mac.sh
#
# The installed app is replaced only when every smoke step passes. The previous one is moved to BACKUP_DIR
# (default: ~/Library/Caches/form-studio/previous-apps), so going back is one move.
set -eu
cd "$(dirname "$0")/.."
PY=.venv/bin/python
"$PY" -m pip --version >/dev/null 2>&1 || true
"$PY" -c "import PyInstaller" 2>/dev/null || uv pip install --python "$PY" pyinstaller
VER=$("$PY" -c "import form; print(form.__version__)")
echo "Building Form Studio $VER"
"$PY" -m PyInstaller packaging/form.spec --noconfirm >.dev/deploy-build.log 2>&1 || { tail -40 .dev/deploy-build.log; exit 1; }
echo "Checking the built app"
"$PY" scripts/smoke_packaged.py dist/FORM.app
BACKUP_DIR=${BACKUP_DIR:-"$HOME/Library/Caches/form-studio/previous-apps"}
mkdir -p "$BACKUP_DIR"
if [ -d /Applications/FORM.app ]; then
  OLD=$(defaults read /Applications/FORM.app/Contents/Info.plist CFBundleShortVersionString 2>/dev/null || echo old)
  DEST="$BACKUP_DIR/FORM-$OLD-$(date +%Y%m%d-%H%M%S).app"
  mv /Applications/FORM.app "$DEST"
  echo "Previous app moved to $DEST"
fi
ditto dist/FORM.app /Applications/FORM.app
echo "Installed Form Studio $VER in /Applications"
command -v uv >/dev/null && uv tool install --force --python 3.12 "form-studio[all] @ $PWD" >/dev/null 2>&1 && echo "form command updated" || true
