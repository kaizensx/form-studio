# Changelog

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
