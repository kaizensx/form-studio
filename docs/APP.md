# The desktop app

Form Studio is a native desktop app for macOS, Windows and Linux, written in Qt Quick on PySide6. The interface and
the 3D viewport are drawn on the GPU by Qt; the CAD engine runs in the same process, with the geometry kernel in an
isolated worker. There is no browser and no web view.

## Install

Download the bundle for your system from the [latest release](https://github.com/kaizensx/form-studio/releases/latest):

| System | File | First launch |
|---|---|---|
| macOS, Apple Silicon | `FORM-macos-arm64.zip` | Unzip, then right-click **FORM.app** › **Open** |
| macOS, Intel | `FORM-macos-x64.zip` | The same |
| Windows 10 and 11 | `FORM-windows-x64.zip` | Unzip and run `FORM.exe`; in SmartScreen choose **More info** › **Run anyway** |
| Linux x64 | `FORM-linux-x64.tar.gz` | Unpack and run `FORM/FORM` |

On first start Form Studio checks what it needs and installs the rest from inside the app: the standard-parts
libraries, a slicer, an agent and its sign-in. Every command is shown before it runs.

### From Python

```bash
curl -LsSf https://raw.githubusercontent.com/kaizensx/form-studio/main/install.sh | sh    # macOS and Linux
form app
```

The script installs [uv](https://docs.astral.sh/uv/) if it is missing (after asking), then Form Studio with its own
Python 3.12, then runs `form setup`. On Windows, or to manage the install yourself:

```bash
uv tool install --python 3.12 "form-studio[all] @ git+https://github.com/kaizensx/form-studio"
```

## The window

![The workspace: conversation, viewport and stages](images/app-prove.webp)

| Area | What it holds |
|---|---|
| **Top bar** | The design and its revision, release state, the printer, search (Ctrl/⌘ K) and Settings |
| **Conversation** (left) | The agent conversation for this design: messages, the agent's steps, the views it looked at, attachments. Resizable; Ctrl/⌘ J hides it |
| **Viewport** (centre) | The kernel's geometry, one mesh per feature, with dimensions on the plate. The tool rail on its left edge holds Select, Measure, Section, Analyze, History, Assembly, Print simulation and Render |
| **Stages** (right) | Brief, Shape, Fit, Prove and Release. Each tab shows where it stands: measured values, features, fit yield, checks to review, release readiness |
| **Pipeline** (bottom) | Parameters › Solid › Exports › Checks › Slice › Release. A node is current only when it describes the revision on screen |

### The five stages

| Stage | What you do there |
|---|---|
| **Brief** | What the part is for, the dimensions you measured with their provenance, reference photos and imported parts |
| **Shape** | Features in build order and their parameters. Select a feature on the model or in the list and change it; the draft shows its computed impact before you commit |
| **Fit** | The fit model for each interface: a section, the clearance, the chance of fitting and how to raise it |
| **Prove** | Every check with its evidence, print orientation, and the slice: time, filament, layers, Watch it print |
| **Release** | The release gate, approval, the released files with their hashes, and the revision history |

### Home

Home is where a design starts. One composer takes whatever you have: words (typed, or spoken with your system's
dictation), a photo (with a bank card, a coin or a ruler in it, the agent estimates sizes from it and labels them
"estimated from the photo"), a sketch drawn on the sketch pad, a STEP, STL or 3MF part, a PDF drawing, or a link (a
model page is passed to the agent as a link; a direct STL, STEP, 3MF, PDF or picture link is downloaded and shown on
the composer). Drop files anywhere on Home or paste them. Under the composer: **For my printer** or **Just a 3D
model** (no slicing, no print checks), and **Start blank** (an empty design in the workspace, no agent).

Sending opens the workspace at once in a "being designed" state with what the agent is doing; the design is attached
the moment it exists and builds up feature by feature in the viewport, each feature named as it arrives. For a new idea
the agent proposes three or four concepts as real CAD, side by side and turning, with a line on each and their computed
size and volume: continue with one, or ask in words for a mix ("the base of A with the hook of C"). When it needs a
real number, a **Measure this** card shows where to measure on a picture or a diagram, the tolerance that matters and
what the design assumes now; the number you type is committed with how you measured it, and the part updates.

Below: concepts waiting for a pick, recent conversations, and every design as a live 3D card, filtered by released and
in progress and sorted by name or date. Right-click a card to rename, duplicate, export or move it to the trash.

**Sketch pad.** Lines, rectangles, circles, arcs (centre, start, end), freehand strokes and dimensions, snapped to a
5 mm grid and to the points already drawn (Alt draws freely), with undo and redo. A typed dimension is "stated" and
overrides the drawn length. The agent receives the shapes as structured geometry in millimetres and the picture.

![Home](images/app-home.webp)

## Keys

| Key | Does |
|---|---|
| Ctrl/⌘ K | Search and commands: every action and every design |
| Ctrl/⌘ N | New design: Home, with the composer ready |
| Ctrl/⌘ Shift O | New conversation |
| Ctrl/⌘ J | Show or hide the conversation |
| Ctrl/⌘ Shift H | All designs (Home) |
| Ctrl/⌘ , | Settings |
| Ctrl/⌘ 1 to 5 | Brief, Shape, Fit, Prove, Release |
| Ctrl/⌘ Return | Commit the draft |
| ? | All keys |

In the viewport:

| Key | Does |
|---|---|
| V | Select: click a feature, drag to orbit |
| M | Measure distances, faces and diameters |
| X | Section cut on or off |
| A | Analyze: thickness, overhang and other maps |
| E | Assembly views and joints |
| T | History: the revision timeline |
| F | Frame the selected feature, or the whole part |
| 1 to 5 | Iso, front, side, top and underside views |
| . | Reset the view |
| H / Shift H | Hide the selected feature / show all |
| Esc | Leave the tool or clear the selection |

Drag to orbit, right-drag or Shift-drag to pan, scroll or pinch to zoom. Right-click a feature for quick actions.

In the conversation: Return sends, Shift Return adds a line, Up brings back your last message.

## Settings

Settings (Ctrl/⌘ ,) edits `studio.toml` for you, with a backup of the file.

| Tab | Holds |
|---|---|
| General | Project folder, daily update check, opening Form Studio when an agent starts working |
| Printer and slicer | The slicer; its printer, process and filament presets; bed size, edge margin and slice time limit |
| Chat | The default agent, model and effort; web lookups; a spending limit per message; API keys, stored privately and never shown again |
| Other apps | Where Blender, OpenSCAD and FreeCAD are; which programs files open in |
| Software | Everything Form Studio uses, what is installed, and an Install button for the rest |

## Rules the app keeps

- It never starts a print and never uploads a design.
- A slice is labelled **simulated**, a fit yield **modelled**, a strength figure a **model** with its assumptions.
- Only a person approves a release, with a deliberate action in the Release stage.
- The app, the CLI and the MCP server can work on the same project folder at the same time.

## Build from source

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[all]" pyinstaller
.venv/bin/python -m form.app                          # run from source
.venv/bin/pyinstaller packaging/form.spec --noconfirm # build the bundle into dist/
```

The bundle is about 800 MB unpacked, because it carries the OpenCascade kernel and Qt. Notes for working on the
interface: [form/app/qml/CONTRIBUTING-UI.md](../form/app/qml/CONTRIBUTING-UI.md).
