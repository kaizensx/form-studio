# Changelog

## 11.0.0

### One app, zero terminal
- **First start is three steps** (FORM itself, your printer and slicer, your AI) and installs what FORM needs from inside the app. Every command is shown first and nothing runs until you press the button. Installs were tested with stand-in commands, not real installers.
- **No example projects.** A new projects folder starts empty. Examples are one click away ("Open an example", or `form examples add`).
- **Settings** (gear, Ctrl/⌘ ,) edits everything that used to need `studio.toml`, with a backup of the file.
- **Claude sign-in** status and a sign-in link in the app.

### Conversations
- **Saved conversations** per design and free-standing: switch, search, pin, rename, delete. They live in `<data>/.conversations`.
- **Agent, model and effort per conversation:** Claude Code and Codex (Gemini CLI when installed). Models come from the agent's own list; FORM does not invent ids. Codex and Gemini have not been run live yet.
- **Attachments:** images, PDFs, STEP/STL by drop or paperclip. Replies stream as they are written, with the agent's steps folded into a group and the views it looked at shown inline.

### See it
- **Watch it print:** the slicer's G-code played back in 3D with a nozzle marker, line-type filters, a per-layer chart and the slicer's own time. Simulated, not a print.
- **Analysis on the model:** wall thickness, overhang, layer cross-section and small-feature maps, computed from the real geometry. Each legend says what the map does not tell you.
- **Measure tool** (M): distance, face area and tilt, hole diameter (exact from the solid).
- **Find the best orientation,** with the numbers behind the ranking.

### Design tools
- **Revision timeline** you can scrub and play as a morph; export as GIF/WebP.
- **Variants** and a variants board.
- **Text, revision stamps and vent/grip patterns** for any design (`form.marks`, `form.patterns`).
- **Cost:** filament, electricity and machine time from the slice and your prices. FORM never guesses a price.
- **Copies on a plate:** does N fit?
- **Share card,** right-click quick actions, viewport keys (`?`).

### Headless
- New commands: `form chat`, `conversations`, `install`, `config`, `examples`, `simulate`, `cost`, `pack`, `analyze`, `measure`, `orient`, `variants`, `share`, `history`, `mark`.
- 41 MCP tools.

### Website
- https://kaizensx.github.io/form-studio/ (source in `site/`; the docs pages are generated from `docs/*.md`).

## 10.0.0

### Works with the tools you already have
- **Slicers:** OrcaSlicer and PrusaSlicer (and SuperSlicer, QIDISlicer) join Bambu Studio. `[slicer].kind = "auto"` uses the first one installed; the Slicer sheet switches between them. Only Bambu Studio was run for real on the release machine; the others are tested against fixtures written from their source.
- **Import a real part:** bring in a STEP or STL (a board, a device, a motor). It is drawn in blueprint around your design, and a design can cut clearance from it with `self.reference("pi5.step")`.
- **OpenSCAD designs:** `create_design(..., language="openscad")`. Customizer range comments become FORM parameters. Mesh designs say clearly which checks and exports do not apply.
- **FreeCAD:** open the STEP in FreeCAD, an optional re-import check when FreeCAD is installed, and a `.FCMacro` with every parameter in a spreadsheet. Not run against a real FreeCAD yet.
- **Blender:** illustrative renders of the current revision (studio, desk, dark; matte PLA, PETG, silk), cached like every other artifact. Blender's 3D-Print Toolbox checks run when the add-on is installed.

### Designs with real hardware
- **`form.parts`:** screw clearances (ISO 273), heat-set insert pockets, nut traps, magnet pockets, bearing seats, printable threads and spur gears, each with its dimensions and their source.
- **New recipes:** electronics enclosure, gear pair, control knob, hinged box.

### Assemblies
- **Assembled / Exploded / Print layout** in the viewport, with hinge and slide joints you can move.
- **Checks from the solids:** overlap when assembled, the smallest gap, each joint swept at sampled positions, and screwdriver access. The check text says that sampled motion does not prove the motion is free between samples.
- **Maker documents on release:** `BOM.csv`, `ASSEMBLY.md` (an exploded image per step), `PRINT_REPORT.md`, `MEASUREMENT_PLAN.md`, `MOTION_CHECKS.csv`.

### The app sets itself up
- **First-run welcome:** what FORM found on this computer, and what it can set up. Nothing is installed until you tick it and press Apply, and every command is shown first.
- **Update notices:** FORM checks GitHub's latest release at most once a day and tells you when one exists. It never downloads or installs anything itself. Turn it off with `[updates] check = false`.

### Expertise
- **Claude Code plugin:** 13 skills (intake, parametric design, FDM engineering, fit calibration, hardware, assemblies, industrial design, design review, release and more) plus the MCP server, in `plugins/form`.
- **Start from a brief:** six brief templates (remote holder, desk accessory, organizer, bathroom mount, enclosure, car accessory) with the questions worth answering; your answers go to Claude.
- **Design review on demand** from the Release stage.

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
