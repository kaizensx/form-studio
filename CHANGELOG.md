# Changelog

## 11.0.3

### Used on Windows and Linux, by the test suite
- **The interface journeys now run on Windows and Linux in CI** (`.github/workflows/ui.yml`): the real window, real mouse and key events, and a real PrusaSlicer installed on the runner, so designs are built, sliced, simulated and released there. Until now only a Mac had done that. No person has used those builds by hand yet.
- **Windows: `form run` failed on any design whose checks contain "Δ"**, because the console is not UTF-8. The CLI now writes UTF-8 everywhere. Found by the first real slice on a Windows runner.
- **Windows: a pipeline could fail right after the solid was built.** Windows refuses to replace a file that anything else has open (the window reading `project.json`, an antivirus scan). Every file FORM replaces is now retried for a moment. Found by the Windows interface run.
- **Windows: a PrusaSlicer installed with Chocolatey is found.**
- **Linux: PrusaSlicer 2.4.0** (Ubuntu's package) slices through FORM; presets come from the bundles it ships.

### OrcaSlicer, every vendor
- **Sliced a 20 mm cube for 496 printers from all 71 vendors OrcaSlicer 2.5.1 ships: 471 slice.** The other 25 fail the same way with OrcaSlicer's own preset files (for example a start G-code outside the printable area), so they are OrcaSlicer's to fix.
- **The build plate is the one OrcaSlicer's window would use.** Its command line defaulted to the Cool Plate: a Prusa CORE One came out with a 35 °C bed instead of 60 °C.
- **A refused slice says why**, in OrcaSlicer's own words, instead of "exit code 154".
- **macOS: no hang after a slicer crash** (the "reopen windows?" dialog used to block every later run).
- **A preset you made in OrcaSlicer works**: layer height, infill and wall overrides were confirmed in the G-code on three printers.

### Design and motion pass
- All 62 screens were re-shot and reviewed at two window sizes. The pipeline strip and stage tabs no longer cut their text; sheets with a subtitle have a proper header; recipe descriptions, model notes and scene notes wrap instead of ending in "…"; reply cost and time are readable.
- Motion: new messages fade in; tabs, rail buttons, pipeline nodes, rows and folds answer hover and press; every duration is a theme token; reduced motion is honoured in three places that ignored it.
- **Renaming a design on Home is instant**, keeps what you typed if the list refreshes, and is not cancelled when you switch to another app.

Left as they are, and known: the Variants sheet's empty state, phone companion lines that can leave the viewport, and Markdown list indent in replies.

## 11.0.2

- **OrcaSlicer 2.5 slices through FORM.** OrcaSlicer 2.5 stopped shipping its printer, process and filament presets as JSON files; each vendor is now one packed file (`.opc`). FORM reads that format (written from OrcaSlicer's own source, format version 2; any other version is refused by name, not guessed) and hands the slicer the presets it needs. Run for real with OrcaSlicer 2.5.1: the phone dock on a Bambu Lab A1 mini 0.4 nozzle, 0.20mm Standard, Generic PLA: 1 h 45 min, 59.04 g, 177 layers; layers, print simulation and cost all read its G-code.
- **Presets pinned in `studio.toml` work on an OrcaSlicer that was never opened**: FORM falls back to the profiles inside the program.
- **"Current selection"** follows OrcaSlicer's per-printer process and filament, and the Slicer sheet says exactly what is missing when the selection is incomplete.
- Not verified: OrcaSlicer on Windows and Linux (profile paths are fixture-tested only; AppImage and Flatpak locations are not covered), vendors other than Bambu Lab (their packed files decode, none was sliced), and a real user-made preset.

## 11.0.1

Run against the real programs for the first time, and fixed what that showed.

- **Codex works in the app.** FORM passed Claude's default model name to Codex, which refused it. The default model and effort now belong to the default agent only. In a live run Codex called FORM's `get_project` tool and answered correctly. Codex notices are shown quietly instead of as errors.
- **PrusaSlicer 2.9.7:** a real slice of the phone dock ran through FORM, and the layers, print simulation and cost all read its G-code. Presets pinned in `studio.toml` now resolve from the bundles PrusaSlicer ships, so it does not have to be opened first.
- **FreeCAD 1.1.4:** the re-import check and the generated macro both ran. The check now uses FreeCAD's exact bounding box; the default one is padded on curved faces and made the check warn.
- **OrcaSlicer 2.5.1** is found and reported. It keeps its printer profiles packed until its own first-run setup is done, so FORM says so and waits.
- **Installer:** the parts libraries, OrcaSlicer, PrusaSlicer and FreeCAD were installed for real through `form install`.
- **Every build launches the packaged app** on macOS, Windows and Linux and requires the interface to load and the CAD kernel to start (`--check` now reports the kernel).
- **Windows:** conversation times always move forward, so "most recent" is right on a coarse clock.

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

### Redesign
- **Workspace:** one tool rail and options bar for the viewport, docked legends that never cover the part, one strip for the pipeline and the history, cross-faded rebuilds, a camera that keeps the part clear of panels, focal stage panels (Prove opens with a pass / review / fail scoreboard).
- **Shell:** a design system with motion tokens, one sheet system for all 13 sheets, a one-line top bar, a resizable conversation column, a new Home with filters, sort and right-click actions, a grouped fuzzy command palette, a native menu bar, About with licences, remembered window size. Reduced motion is respected (`FORM_REDUCED_MOTION`).
- **Housekeeping:** rename, duplicate, export and trash designs from Home (`form rename|duplicate|delete`).

### Tested by clicking
- **Nine UI journeys** drive the real window with synthetic mouse and keyboard events (`python -m form.app --uitest`, `tests/journeys`). They found and fixed, among others: Enter creating a project twice, Tab leaving a sheet, viewport keys typing into the chat box, toasts restarting each other, Esc not closing the context menu.
- **Update now:** the update sheet installs the upgrade from the app (`form update --install`); the terminal instruction is gone.

### Headless
- New commands: `form chat`, `conversations`, `install`, `config`, `examples`, `simulate`, `cost`, `pack`, `analyze`, `measure`, `orient`, `variants`, `share`, `history`, `mark`, `rename`, `duplicate`, `delete`, `update --install`.
- 44 MCP tools.

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
