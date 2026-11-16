# The FORM desktop app

FORM's app is a native program for macOS, Windows and Linux. It is written in Qt Quick (PySide6) and shares one
process with the CAD engine. There is no browser and no web view: the interface and the 3D viewport are drawn on the GPU by Qt.

## Run it

**From a download.** Each push builds the app for every platform in the *Desktop app* workflow. Download the bundle for your
system from the workflow run (or from a release), unpack it and open FORM.

| System | File | First launch |
|---|---|---|
| macOS, Apple Silicon | `FORM-macos-arm64.zip` | Right-click FORM → Open (the build is not notarized) |
| macOS, Intel | `FORM-macos-x64.zip` | Same |
| Windows 10/11 | `FORM-windows-x64.zip` | "More info" → "Run anyway" (the build is not signed) |
| Linux x64 | `FORM-linux-x64.tar.gz` | Run `FORM/FORM` |

**From Python.** If you already use FORM's CLI:

```bash
uv tool install --force --python 3.12 "form-studio[app] @ git+https://github.com/kaizensx/form-studio"
```

```bash
form app
```

The app, `form serve`, the MCP server and the CLI all work on the same project folder (`~/FORM` by default), at the same time.

## What you see

- **Claude, on the left.** Describe a part or a change. Each message runs Claude Code on your own account with FORM's tools.
  The same column shows what any other agent (Claude Code, Codex, the CLI) is doing to your designs, live.
- **The part, in the middle.** The kernel's real geometry, one mesh per feature. Click a feature to select it. Overall
  dimensions are drawn on the plate as dimension lines. Cut X/Y/Z shows a section with solid cut faces.
- **The question, on the right.** Five stages: Brief, Shape, Fit, Prove, Release. Each tab says where it stands.
- **The pipeline, along the bottom.** Parameters → Solid → Exports → Checks → Slice → Release. A node is only shown as
  current when it describes the revision on screen.
- **Home.** Every design as a live 3D card.

## Keys

| Key | Does |
|---|---|
| Ctrl/⌘ K | Command palette: every action and every design |
| Ctrl/⌘ 1–5 | Brief, Shape, Fit, Prove, Release |
| Ctrl/⌘ Enter | Commit the draft |
| Ctrl/⌘ J | Show or hide Claude |
| Ctrl/⌘ N | New design from a recipe |
| Esc | Close the sheet, leave the layer view, or deselect |

In the viewport: drag to orbit, right-drag or Shift-drag to pan, scroll or pinch to zoom, click to select a feature.

## What it will not do

The app keeps every rule of the engine. It does not start a print or upload a design. A slice is labelled *simulated*,
a fit yield *modelled*, and only you can approve a release, with a deliberate button in the Release stage.

## Build it yourself

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[app]" pyinstaller
.venv/bin/python -m form.app            # run from source
.venv/bin/pyinstaller packaging/form.spec --noconfirm
```

The bundle lands in `dist/`. It is large (about 800 MB unpacked) because it carries the OpenCascade CAD kernel and Qt.
Notes for working on the interface are in [form/app/qml/CONTRIBUTING-UI.md](../form/app/qml/CONTRIBUTING-UI.md).
