# Changelog

## 9.0.0

### A desktop app
- **FORM is now a native app** for macOS, Windows and Linux (`form app`, or the downloadable bundle). It is built with Qt Quick and runs in one process with the CAD engine. No browser, no web view.
- **Native 3D viewport:** the kernel's meshes and edges, feature picking, section cuts with solid cut faces, and overall dimensions drawn as dimension lines.
- **Home** shows every design as a live 3D card. **Claude** has its own column. A **command palette** (Ctrl/⌘ K) reaches every action and design.
- **All five stages** are in the app: Brief (with photo measuring), Shape, Fit, Prove (with the slice layer viewer) and Release.
- **Installers for every platform** are built by the *Desktop app* workflow. They are not signed or notarized yet.

### Engine
- Project locks now also work across processes on Windows.
- `form serve` no longer prints a traceback when FORM is already running.

## 8.0.0

### Design anything
- **Designs as code:** agents write designs (`design_guide`, `create_design`, `update_design`, `get_design_source`) that get the full pipeline. Every revision keeps its exact code.
- **Multi-part designs:** `solids = N`, so a base and lid print on one plate.
- **`read_document`:** renders datasheet and mechanical-drawing PDFs as images, so agents read real dimensions.
- **Declared provenance:** a design can mark a value `Param(..., provenance="specified")`.

### The page
- **Chat with Claude in the page.** It runs on your Claude Code account, with FORM tools and web lookup, and streams what Claude is writing.
- **The page follows any agent live:** it opens projects, shows drafts and views, and refreshes on commits.
- **It opens by itself** the first time an agent starts working.

### Fixes
- The `form-mcp` path broke when it contained spaces.
- Setup fixes no longer inherit the terminal.
- Registration is detected from config files.
- The installer always fetches the latest version.

## 7.0.0

### Installation
- **One-line installer** (`install.sh`). It installs uv if missing (after asking), installs FORM with its own Python 3.12, then runs `form setup`.
- **`form setup`** reports the kernel, project folder, slicer, printer size, and Claude Code, Codex, Gemini CLI, Cursor and Claude Desktop. You choose what to fix. Each fix shows its command, config files are backed up, and the result is verified afterwards. `--check`, `--yes` and `--dry-run` are available. The same report is available to agents as the `setup_status` tool.

### New recipes
- **`gridfinity`:** Gridfinity-style bin with magnet pockets, dividers, scoop, label shelf and a stacking lip truncated to two perimeters.
- **`hook`:** wall hook with a bending-stress model, screw pull-out estimate and screwdriver clearance.
- **`planter`:** twisted polygon planter with a drain-plug fit.

### New tools
- **Goal seek** (`optimize`): minimise or maximise any metric under constraints, with every candidate built by the kernel.
- **Motion** (`animate`): turntables and parameter morphs as GIF or WebP, from real builds.

### Fixes
- Recipe-specific model checks via `statics()["checks"]`, and a fit window per recipe.
- Change impact and alternatives no longer assume the dock's tip-over model.
- The renderer wraps long legends and supports fixed framing and free cameras.
- The repository's media, gallery, social card and animated session replay are all generated from real builds (`scripts/make_media.py`).
- Added CI workflow, issue and PR templates, `CONTRIBUTING.md`, `SECURITY.md` and [docs/RECIPES.md](docs/RECIPES.md).

## 6.0.0

- **MCP server:** stdio MCP server, JSON CLI, headless renders, cross-process project locks, `expect_head`, and agent-attributed revisions.
- **Bench:** deep links, and the bench follows agent edits live.
- **Slicer:** slicer adapter interface; slicer logs strip the home path.
- **Packaging:** installable package with first-run examples. The built-in model call is now off by default.

## 5.0.0

- **Single-user studio:** one CAD authority, a hashed artifact graph, fit under uncertainty, real slicing and a release gate.
