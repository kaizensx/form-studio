# Architecture

```
  You, in the desktop app             Agents: Claude Code · Codex · Gemini CLI · Cursor · model APIs · local models
  (Qt Quick, form/app)                (chat inside the app, or MCP over stdio from their own window)
          |                                      |                          |
          +------------- local HTTP -------------+------- MCP (form-mcp) ---+---- JSON CLI (form)
                                                 |
                              Studio (form/studio.py): one project state, cross-process locks,
                              parameters and provenance, hashed artifact graph, revisions, release
                    |                  |                    |                     |
           kernel worker         slicer adapters        renderers            bridges
           build123d / OCCT      form/adapters/          form/render.py       FreeCAD, OpenSCAD,
           form/worker.py        Bambu · Orca · Prusa ·  (numpy, headless)    Blender
                                 SuperSlicer · QIDI ·    Blender (photo)
                                 Elegoo · Snapmaker
```

**Form Studio is a layer, not a CAD program or a slicer.** Agents supply the intelligence; established software supplies
the geometry kernel and the slicing. Form Studio owns what neither does: parameters with provenance, hashed staleness,
computed change impact, checks with evidence classes, the fit model, printer calibration and the release record.

## Components

| Component | Module | Role |
|---|---|---|
| Desktop app | `form/app/` | Qt Quick interface and Qt Quick 3D viewport; talks to the engine in-process through a local HTTP bridge |
| Engine | `form/studio.py` | Projects, revisions, keys, pipeline jobs, release gate |
| Kernel worker | `form/worker.py`, `form/kernel.py` | build123d on OpenCascade in a separate process; a crash or timeout restarts it without touching project state |
| Starting a design | `form/start.py`, `form/sketch.py`, `form/photo.py`, `form/concepts.py` | Home's composer as one message (words, photos, files, a sketch as structured geometry, links), blank designs, concept groups and the pick |
| Recipes | `form/recipes/`, `form/recipe_lib.py`, `form/recipe_share.py` | Parametric families and designs written as code (Python or OpenSCAD); installed and community recipes, verified by SHA-256; `.formrecipe` packages and submissions |
| Purpose | `form/purpose.py` | For 3D printing or just a 3D model, the process a model is made with, and which checks apply |
| Checks and analysis | `form/checks.py`, `form/analysis.py`, `form/fit.py`, `form/selection.py` | Checks on the solid, analysis maps, the fit model, statics, selections and annotations |
| Appearance | `form/materials.py` | Colours and materials per design or part, the 3MF with colours, material-aware checks |
| Assemblies | `form/recipes/assembly.py`, `form/assembly.py`, `form/collide.py` | Parts, kinematic chains and fits as data; interference, fit and joint-sweep checks on meshes with B-rep refinement, in their own time budget |
| Slicer adapters | `form/adapters/`, `form/printers.py`, `form/plates.py` | Find the slicer and every printer set up in it, resolve presets, lay parts out on one or more plates, slice, parse the G-code |
| Print simulation | `form/toolpath.py`, `form/simulate.py` | Per-layer toolpaths by line type, timed by the slicer's estimate |
| Agents | `form/agents/`, `form/chat.py`, `form/ask.py` | Run an agent CLI, or talk to a model API, a local model or a provider added by URL with Form Studio's tools (`form/agents/mcp_client.py`); questions and measurements the agent asks wait for the person's answer |
| MCP server | `form/mcp_server.py` | 91 tools over stdio |
| CLI | `form/__main__.py` | Every capability as a JSON-printing command |
| Archives | `form/bundle.py` | `.formstudio` files: a project, its conversations and the code it was built from, checked before anything is written |
| Installer | `form/installer.py`, `form/setup.py` | Finds and installs slicers, agents and libraries, with consent; hands-free on first start |

## Principles

**Agents propose, a person releases.** Every engine action is an MCP tool except approval, which exists only in the
app. `commit_change` takes `expect_head`; a stale head is refused with the current one, so an agent never overwrites a
newer human edit. Revisions record their origin (`agent:<client>`, `cli`, `user`).

**Agents can see.** `render` rasterises the kernel's tessellation in the server process (z-buffer, flat shading,
visible edges, colour by feature, scale bar) and returns a PNG, with no GPU or browser.

**Concurrency.** The app, any number of MCP servers and the CLI can share one project folder. `Studio.lock(pid)` is an
in-process lock plus a file lock on `<data>/.locks/<pid>.lock`, and every mutation reloads the project under the lock.
The app watches a cheap stamp and follows changes made elsewhere.

## Decisions

**build123d is the only geometry authority.** A recipe builds a B-rep solid as an ordered list of feature stages. STEP
is the exchange format for other CAD programs; STL is derived for slicing. Other programs receive STEP; none of them
is a second editable source.

**Staleness is derived, never flagged.** `Studio.keys()` hashes each artifact's inputs:

| Artifact | Key covers |
|---|---|
| Solid | recipe source hash, kernel version, parameter values |
| STEP, STL, OBJ and GLB | solid key, print orientation, mesh tolerance |
| Checks | export key, build volume, nozzle, checks version, fit window, calibration fingerprint, provenance of the mating dimension |
| Slice | export key, content hash of each flattened preset, slicer version, the plate plan |

An artifact is current when a file exists under its expected key. A clearance change stales all four; an orientation
change keeps the solid; a new coupon measurement stales only the checks; another process preset in the slicer stales
only the slice. Reverting an input makes the earlier artifact current again, with no rebuild.

**Feature attribution is geometric.** After each stage the kernel keeps the solid's faces. A final face belongs to the
last stage that created the surface under it. This is what makes click-to-select, colour by feature and "features
touched" real rather than declared.

**Purpose decides what applies.** A design for 3D printing runs every check and is sliced. A design that is just a 3D
model skips the print-only checks (build volume, nozzle walls, overhangs, bridges, plate contact, the fit model) and the
slice; its thinnest feature is compared with the process it names. The release says what it does not cover.

**Assemblies are data.** A recipe's `assembly()` returns parts, joints and mates. Parts form a tree: fixed to a parent
(`attach`) or moving on a joint mounted on one (`parent`), so a joint carries everything below it. Interference,
declared fits and joint sweeps are computed on meshes first and booleaned on the B-rep only where parts meet, inside a
time budget (`[assembly].budget_s`); a partial result names the range that was checked.

**Evidence classes.** *computed* (measured on the kernel's geometry), *heuristic* (a rule of thumb on computed values),
*model* (statistics or statics with stated assumptions), *simulated* (from the slicer), *physical* (entered from a real
print). Coupon measurements calibrate the printer profile; only a result from the part itself is physical evidence for
a revision.

## Fit model

Total gap = (nominal cavity + printer bias) − object dimension, with independent normal errors. The object's spread
comes from its provenance; the printer's bias and spread from pooled coupon and part measurements for the profile
(printer and filament), or an assumed ±0.15 mm prior labelled as assumed. The yield is the probability that the gap
lands in your acceptance window.

## Slicers

`form/slicer.py` dispatches to the adapter for `[slicer].kind` (`auto` uses the first one installed): Bambu Studio,
OrcaSlicer, PrusaSlicer, SuperSlicer, QIDISlicer, ElegooSlicer or Snapmaker Orca. A printer chosen for a design or as
the default (`form/printers.py`) picks the slicer and presets. An adapter reads
the presets selected in the slicer or pinned in `studio.toml`, flattens their inheritance chain into self-contained
files, and runs the slicer's command line on the oriented STL. Time, filament and supports come from the produced 3MF
and G-code, and the G-code is parsed into per-layer paths by line type. When the parts do not fit one plate,
`form/plates.py` packs them, each in its own orientation, onto as many plates as needed (one material per plate) and
each plate is sliced on its own. OrcaSlicer 2.5's packed vendor profiles
(`.opc`, format version 2) are decoded directly; any other format version is refused by name.
