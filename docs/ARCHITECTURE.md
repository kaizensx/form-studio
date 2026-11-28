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
| Recipes | `form/recipes/`, `form/recipe_lib.py`, `form/recipe_share.py` | Internal building blocks for agents and designs written as code (Python or OpenSCAD); installed recipes, verified by SHA-256; `.formrecipe` packages |
| Purpose | `form/purpose.py` | For 3D printing or just a 3D model, the process a model is made with, and which checks apply |
| Canonical form and edits | `form/canon.py`, `form/edits.py` | A plain Recipe lifted into one method per feature (kernel-checked to be the same solid); edits as ops on one feature, helper or parameter: one build, one revision |
| Contract and proof | `form/contract.py`, `form/proving.py`, `form/preflight.py` | The brief as kernel-checkable assertions with tolerance and provenance, the audit of its numbers, each assertion owed by one feature, the proof sheet per revision and the claim gate; what is wrong with a source that needs no kernel to find |
| Checks and analysis | `form/checks.py`, `form/analysis.py`, `form/fit.py`, `form/selection.py` | Checks on the solid, analysis maps, the fit model, statics, selections and annotations |
| Appearance | `form/materials.py` | Colours and materials per design or part, the 3MF with colours, material-aware checks |
| Assemblies | `form/recipes/assembly.py`, `form/assembly.py`, `form/collide.py` | Parts, kinematic chains and fits as data; interference, fit and joint-sweep checks on meshes with B-rep refinement, in their own time budget |
| Slicer adapters | `form/adapters/`, `form/printers.py`, `form/plates.py` | Find the slicer and every printer set up in it, resolve presets, lay parts out on one or more plates, slice, parse the G-code |
| Print simulation | `form/toolpath.py`, `form/simulate.py` | Per-layer toolpaths by line type, timed by the slicer's estimate |
| Agents | `form/agents/`, `form/chat.py`, `form/ask.py` | Run an agent CLI, or talk to a model API, a local model or a provider added by URL with Form Studio's tools (`form/agents/mcp_client.py`); questions and measurements the agent asks wait for the person's answer |
| Standard parts and the parts list | `form/catalog.py`, `form/placement.py`, `form/bom.py` | Part families generated from cited tables (bd_warehouse's data files read as CSV, and tables kept with their sources), importable without OCCT; placements as a block in the design's source that cuts each mating feature and lists the part as purchased; snap and fit as kernel ops; the grouped parts list, supplier references beside the project, and the catalogue provider interface (off, none shipped) |
| Blender modelling bridge | `form/adapters/blender_model.py`, `form/adapters/blender_ops.py`, `form/meshsource.py` | An agent's declarative op list, schema-checked, run in Blender by a fixed runner; streams a preview per op; returns cage data (points, quads, creases, named regions) for a design's source |
| Sheet metal | `form/sheet/` | Sheet-metal features, the B-rep unfold proved by folding back, flat pattern DXF, the cut-file checker, bend order on a press-brake model, flat profiles with kerf, service preflight |
| Manufacturability | `form/dfm/` | Rules per process with their sources (`form/dfm/rules/`), measured on the B-rep; fixes written into the source and proved by checking again |
| CAM | `form/cam/` | 3-axis toolpaths by Form Studio's own drop-cutter, speeds and feeds from a cited table (`form/cam/feeds.toml`), five posts read back, a stock simulation that measures gouge and leftover |
| Strength studies | `form/fea/` | Static, modal, buckling and thermal studies meshed from the B-rep and solved in an engine of their own (`engines.build("fea")`), refined until converged, with the error stated |
| Engineering calculators | `form/calc/` | Snap fits, hinges, springs, bolted joints, gears, cams and fits at temperature by a named standard's equations, written as a design that keeps its calculation |
| Drawings | `form/drawing/`, `form/iso286.py` | Hidden-line views, sections and details, dimensions bound to parameters, ISO 286 fits (the one ISO 286 module), GD&T, AP242 PMI, the drawing check |
| Motion and robot files | `form/motion.py`, `form/robot.py`, `form/sequence.py` | Mechanisms played over time, URDF/SRDF/MJCF with inertia from the B-rep, assembly order and insertion directions |
| Boards and enclosures | `form/board/` | KiCad and IDF boards read by Form Studio's own parsers, the enclosure made around them, the fit proved on the solids; KiCad's DRC/ERC and fab files through the person's own KiCad |
| Print physics | `form/printphys/` | Print orientation as a Pareto front over support, time, strength, surface and tip-over, checked against real slices; strength as printed with a layered material (solved by `form/fea/`); a warp-risk indicator from a cited model |
| The Bench | `form/studies.py` | Every study, route and document of a design with its state from the head revision's keys; each wave registers through `PROVIDERS` |
| MCP server | `form/mcp_server.py` | 129 tools over stdio |
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

**A solid is built once.** A (design source, values) pair is built once, whatever tolerance, operation or process
asks for it: the kernel keeps the B-rep with its face-to-feature map (by face index, attributed on a 0.05 mm mesh) and
derives each tessellation from it. `form/brepstore.py` keeps it on disk under `.cache/brep/<content key>` (the design's
code, the values, the code that builds and attributes solids, the kernel, label text and imported parts), so another
worker, MCP server or the CLI loads it instead of building; a `.building` marker makes a second process wait for the
first instead of building the same key. A draft and the revision it becomes share one geometry key
(`Studio.geometry_key`). Kernel call deadlines follow the design's predicted build cost (`Studio.deadline`), not a fixed
minute. `scripts/bench_replay.py` replays logged tool calls on a copy of a project and counts builds, seconds and
restarts.

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

## Proof-carrying build

A build that returns a valid solid is done; it is not thereby correct. Four pieces close that gap, each small.

**Canonical form.** `form/canon.py` rewrites a plain Recipe as a FeatureDesign: `build()` is cut after every statement
that makes a Stage, and each piece becomes a method that takes the body the piece before it staged. What a piece
reads from earlier pieces is replayed inside it only when that is arithmetic (or the design's own numeric helpers);
a piece that would need geometry or a value measured on an earlier body is merged with the pieces before it, and a
build that cannot be cut is one skeleton feature. The lift is accepted for a project only after it is built once and
has the head's volume, face count and bounding box (`form/edits.py` `canonical`), and that build leaves the
checkpoints the next edit starts from.

**Edit protocol.** `edit_design(ops=[replace | insert | delete | set_param], expect_head)` applies ops to the canonical
source: a feature, a function or a parameter by name, or text found exactly once. All ops are checked before any is
applied; the result is one build and one revision, and it reports the features that were built again, not the file.

**Contract and obligations.** `design_brief` compiles the brief into typed assertions (`form/contract.py`): read from
its words where the words carry numbers, passed as typed assertions otherwise. The audit is arithmetic on those
numbers (missing, conflicting, impossible) and blocks planning and building until they can all hold. Each assertion
is assigned to the feature that must discharge it. `@feature(..., expects=[...])` makes it a postcondition measured
when that feature is built (`form/proving.py` `expects`); a miss is that feature's failure. `op_prove` measures every
assertion on the finished solid and, for a failure, on the solid as each feature left it, so the row says where it was
never met or at which later feature it was lost.

**Proof sheet.** One row per requirement: measured, tolerance, evidence class (computed, heuristic or none) and PASS,
FAIL or UNPROVEN. It is stored under a key made of the solid's key and the contract's fingerprint, so it is current
exactly while both are. `get_project` and every commit return it, a FAIL blocks release, and
`contract.claim_gate(st, p)` returns what a summary may claim (the PASS rows), what it must not (FAIL and UNPROVEN,
with the measurement) and the audit's open items.

**Preflight.** `form/preflight.py` reads a source twice without the kernel: its syntax tree against a snapshot of the
real API (`form/preflight_api.json`, written by `scripts/gen_preflight_api.py`), and a dry run in which the design's
own code executes with every geometry module replaced by ghosts, so its numbers are the ones the kernel would get.
It imports neither build123d nor OCCT. Errors refuse a create or an edit before any kernel time, all at once, and an
edit is refused only for what it introduces.

## Blender modelling bridge

An agent models a subdivision cage in Blender by sending ops, never code: `cage_new`, `extrude_region`, `loop_cut`,
`move`, `crease`, `name_region`, `mirror`, `geonodes_array`, `geonodes_scatter`, `sculpt_ops` (Form's own bounded,
deterministic brushes) and `remesh` (voxel or QuadriFlow). `form/adapters/blender_model.py` checks every op, field,
type and range before Blender starts and refuses anything else. `form/adapters/blender_ops.py` is the fixed script
Blender runs: it maps each op name to its own function, imports nothing that opens a network connection or starts a
process (a test reads its syntax tree), and puts points and faces in a geometry-only order after every op, so a replay
of the same op list gives the same cage (the hash of its rounded points and faces).

After each op the runner writes the cage at subdivision level 2 to a stage file and prints `FORM_STAGE <path.bin>`.
The bridge turns it into the same stage event a kernel build streams (`form/meshsource.py`, `stage_event`), so
`Studio._draft_sink` puts it in `.cache/drafts/<draft>.json`, where `/api/drafts` and `Store.showStage` show it.

The result is cage data, kept in the design's source (`meshsource.cage(...)`) and built by a `FeatureDesign` feature
with `form/craft/subd.py`; Blender edits, the design source stays the geometry authority. Op lists and their cages are
cached under `.cache/model_mesh/<key>`, keyed by the canonical ops, the runner version and Blender's major.minor.

Blender runs as `blender -b --factory-startup -noaudio -Y` (scripts inside .blend files never run automatically), with
`--offline-mode` from Blender 4.2, a scrubbed environment, a temporary working directory and a watchdog that kills its
whole process group at the time limit. Nothing is written until Blender has finished, so a failed or stopped run leaves
the project as it was. **Network access is not isolated by the operating system:** `--offline-mode` is Blender's own
switch and the runner has no network code, but nothing outside Blender stops a Blender process from connecting.

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
