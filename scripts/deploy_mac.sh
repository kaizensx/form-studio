#!/bin/sh
# Build Form Studio for this Mac, check the built app, and install it in /Applications as "Form Studio.app".
#
#   scripts/deploy_mac.sh                 # build, smoke test, install (keeps a zipped backup of the installed app)
#   BACKUP_DIR=~/somewhere scripts/deploy_mac.sh
#
# The installed app is replaced only when every smoke step passes. The previous one is zipped into BACKUP_DIR
# (default: ~/Library/Caches/form-studio/previous-apps). Backups are zips, not .app folders, so Spotlight and
# Launchpad never show them as a second Form Studio; the newest three are kept.
# Installations from before 1.1 were called FORM.app: it is retired the same way, and agents registered with its
# path (Claude Code, Codex) are pointed at the new one.
set -eu
cd "$(dirname "$0")/.."
PY=.venv/bin/python
APP="Form Studio.app"
DEST_APP="/Applications/$APP"
OLD_APP=/Applications/FORM.app
"$PY" -m pip --version >/dev/null 2>&1 || true
"$PY" -c "import PyInstaller" 2>/dev/null || uv pip install --python "$PY" pyinstaller
VER=$("$PY" -c "import form; print(form.__version__)")
echo "Building Form Studio $VER"
rm -rf dist/FORM.app
"$PY" -m PyInstaller packaging/form.spec --noconfirm >.dev/deploy-build.log 2>&1 || { tail -40 .dev/deploy-build.log; exit 1; }
echo "Checking the built app"
"$PY" scripts/smoke_packaged.py "dist/$APP"
BACKUP_DIR=${BACKUP_DIR:-"$HOME/Library/Caches/form-studio/previous-apps"}
mkdir -p "$BACKUP_DIR"
running() { pgrep -f "$DEST_APP/Contents/MacOS/FORM" >/dev/null 2>&1 || pgrep -f "$OLD_APP/Contents/MacOS/FORM" >/dev/null 2>&1; }
# A running copy must not have its app replaced under it: it reads parts of its own code from the bundle when it first
# needs them, and once the files are swapped it reads the new bundle at the old offsets ("Error -3 while decompressing
# data"). Quit it first (it saves as it goes), and open the new one afterwards.
WAS_RUNNING=0
if running; then
  WAS_RUNNING=1
  echo "Quitting the running Form Studio so it is not replaced while open"
  osascript -e 'tell application id "net.form-studio.app" to quit' >/dev/null 2>&1 || true
  i=0
  while running && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done
  if running; then
    echo "Form Studio did not quit within 30 s; close it and run this again. Nothing was replaced."; exit 1
  fi
fi
retire() {   # zip an installed app into BACKUP_DIR, then remove it
  OLD=$(defaults read "$1/Contents/Info.plist" CFBundleVersion 2>/dev/null || echo old)
  ZIP="$BACKUP_DIR/Form Studio-$OLD-$(date +%Y%m%d-%H%M%S).zip"
  ditto -c -k --keepParent "$1" "$ZIP"
  rm -rf "$1"
  echo "Previous app saved as $ZIP"
}
[ -d "$DEST_APP" ] && retire "$DEST_APP"
[ -d "$OLD_APP" ] && retire "$OLD_APP"
ditto "dist/$APP" "$DEST_APP"
rm -rf "dist/$APP"     # the build copy would show in Spotlight as a second app; dist/FORM stays for the next build
echo "Installed Form Studio $VER in $DEST_APP"
# Keep the newest three backups.
ls -1t "$BACKUP_DIR"/*.zip 2>/dev/null | tail -n +4 | while IFS= read -r z; do rm -f "$z"; done
# Agents registered with the old FORM.app path: point them at the new app.
NEW_BIN="$DEST_APP/Contents/MacOS/FORM"
if command -v claude >/dev/null && claude mcp get form 2>/dev/null | grep -q "$OLD_APP/"; then
  claude mcp remove --scope user form >/dev/null 2>&1 || true
  claude mcp add --scope user form -- "$NEW_BIN" -m form.mcp_server >/dev/null && echo "Claude Code now uses $DEST_APP"
fi
if command -v codex >/dev/null && codex mcp get form 2>/dev/null | grep -q "$OLD_APP/"; then
  codex mcp remove form >/dev/null 2>&1 || true
  codex mcp add form -- "$NEW_BIN" -m form.mcp_server >/dev/null && echo "Codex now uses $DEST_APP"
fi
[ "$WAS_RUNNING" = 1 ] && open -a "$DEST_APP" && echo "Opened the new Form Studio"
command -v uv >/dev/null && uv tool install --force --python 3.12 "form-studio[all] @ $PWD" >/dev/null 2>&1 && echo "form command updated" || true
