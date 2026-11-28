# Beyond Studio: parity audit and plan

Date: 2026-11-27. Branch `dev`, version 1.2.0-dev. Status: plan only; no product code changed.

The goal is the owner's: Form Studio is to be the best at everything an AI CAD app for engineers does, not at most
of it. This page measures Form Studio against one named competitor, capability by capability, says where it is
already ahead, and lays out the work, in waves that ship on their own, to be ahead everywhere.

- [The reference](#the-reference)
- [How this was audited](#how-this-was-audited)
- [Parity matrix](#parity-matrix)
- [Where Form Studio is already ahead](#where-form-studio-is-already-ahead)
- [Principles for every wave](#principles-for-every-wave)
- [The waves](#the-waves)
- [Order](#order)
- [What not to do](#what-not-to-do)
- [Owner decisions](#owner-decisions)

## The reference

**text-to-cad Studio** (site `texttocad.studio`, repo `amywork777/studio`), read on 2026-11-27 at commit `8c0c60e`.

| Fact | Value | Source |
|---|---|---|
| What it is | An Electron desktop app (Mac and Windows) for mechanical engineers: chat, a feature tree, a CAD ribbon, a model view and a Toolbox of 32 tools in four tabs | their site and README |
| Built on | T3 Code (the app shell), text-to-cad (the CAD skills, a git submodule), FreeCAD (CAM), CalculiX and Netgen (strength), KiCad through `kicode` (boards), Blender (renders) | their README, `STUDIO.md`, `skills/fea/SKILL.md` |
| Licence | **MIT** for Studio (`LICENSE`, copyright T3 Tools Inc.), MIT for T3 Code, MIT for text-to-cad (copyright Thompson Labs LLC) | the three `LICENSE` files |
| Install | About 5 GB | their site |
| Agents | Claude and ChatGPT (Codex) accounts | their site |
| Usage data | Anonymous feature counts, on after a first-launch notice, sent to their own receiver; searches for bought parts go to the `step.parts` service | their README |
| Limits they state | Strength is linear static only (no vibration, buckling, heat, fatigue, impact or sliding contact); drawings need review | their site, `skills/fea/SKILL.md` |

Their licence would allow reuse with the notice kept. This plan does not use it: every wave is an original
implementation in Form Studio's own engine and design language. Only behaviour was learned, from public pages.

Capabilities found in their repo beyond the site's list: job skills for resin printing and metal printing (`resin`,
`metal-print`), playing a motion back (`play-motion`), project Sync with backups and a GitHub connection, a CAM job
view and a board view inside the model viewer, and a notice "Part changed since this check" on a stale result.

## How this was audited

- Read: `AGENTS.md`, `docs/NORTH_STAR.md`, `docs/FEATURES.md`, `docs/APP.md`, `docs/MCP.md`, `README.md`, and the
  source under `form/`.
- Ran, on a temporary `FORM_DATA` (never `~/FORM`): `form tool` (lists **97** tools), `form_overview`,
  `create_design` (a plate with a bore and four holes, purpose `model`, process `cnc`; built and checked in 5.8 s),
  `analyze`, `critique`.
- Searched the source for each capability (FEA, drawings, HLR, PMI, DXF, unfolding, draft, undercuts, CAM, URDF,
  MuJoCo, KiCad, Gerber, SLS and MJF, suppress and rollback, telemetry).
- The competitor was read, not run: its README, `STUDIO.md`, licence files, skill and job lists and the FEA skill
  text. Its site was summarised by the owner. Grades of *their* quality are therefore from their own description.

Grades: **missing** (nothing in the product), **partial** (some of it, or the engine without the interface),
**equal**, **better**.

## Parity matrix

### The window and the work

| # | Their capability | Form Studio today | Evidence | Grade |
|---|---|---|---|---|
| 1 | From a brief to a model | Words, photo, sketch, files, links, PDF; staged brief and plan; the brief as a contract with a proof sheet | `form/start.py`, `form/staged.py`, `form/contract.py`; tools `design_brief`, `plan_design`, `create_design` | better |
| 2 | Draw it in the chat | Sketch pad: lines, arcs, circles, stated dimensions; the agent receives structured geometry in mm | `SketchSheet.qml`, `Sketch.js`, `form/sketch.py` | better |
| 3 | Point and ask | Annotate: faces, edges, points, brush and lasso, with computed numbers; kept as pins; sent to the agent | `form/selection.py`; `analyze_selection`, `annotate` | better |
| 4 | Feature tree | The Program pane: features in build order, select, hide, parameters. No suppress, no reorder, no rename, no rollback bar | `Workspace.qml`, `FeatureSheet.qml`, `form/featureprog.py` | partial |
| 5 | CAD ribbon: sketch, extrude, fillet, hole by hand | By hand today: parameter sliders, drag a face, text on a face, a screw boss or snap hook where clicked. No sketch-on-face, extrude, cut, revolve, fillet or chamfer by picking edges, hole wizard, pattern or shell | `FaceDrag.qml`, `form/dragface.py`, `form/engrave.py`, `form/feature_helpers.py`; `add_feature` kinds `boss`, `snap_hook`, `code` | partial |
| 6 | Change a sketch | The solver exists (`form.sketch2d`: 30 entities and 40 constraints in about 1 ms) and designs use it; the app has no editor for a design's sketch | `form/sketch2d/solver.py` | partial |
| 7 | Step back in time (rollback) | Revisions scrub and morph; per-feature checkpoints exist in the engine. No rollback to a feature inside one revision | `Timeline.qml`, `form/brepstore.py` | partial |
| 8 | Every version saved | Revisions with origin, branches, variants, compare, a boolean diff of the solids | `form/geomdiff.py`, `form/variants.py`; `geometry_diff`, `compare_revisions` | better |
| 9 | Model view: turn, measure, section | Orbit, Measure with snapping and exact hole diameters, Section with filled faces, analysis maps | `MeasureLayer.qml`, `form/analysis.py`; `measure`, `analyze` | better |
| 10 | All projects | Home: live 3D cards grouped by family, filters, import and export as one file | `Home.qml`, `form/bundle.py` | better |
| 11 | A Toolbox: one place for every job | Tools are spread over the tool dock, the stages and the palette. No single surface that lists every study, route and document with its state | `Workspace.qml`, `Palette.qml` | partial |

### Design

| # | Their capability | Form Studio today | Evidence | Grade |
|---|---|---|---|---|
| 12 | Brainstorm 4 concepts with mass and material | 3 or 4 concepts as real kernel builds, in parallel, with size and volume; mix in words. Mass and material are not on the card | `form/concepts.py`; `propose_concepts`, `pick_concept` | equal |
| 13 | Off-the-shelf parts to buy (ISO 4762 and so on) | Screws, nuts, washers, heat-set inserts, bearings, threads, gears, sprockets, pipe; every dimension with its source; `BOM.csv` with a standard reference and a link column. No catalogue browser, no supplier part numbers | `form/parts.py` (bd_warehouse), `form/maker_docs.py:bom` | partial |

### Check

| # | Their capability | Form Studio today | Evidence | Grade |
|---|---|---|---|---|
| 14 | Strength: linear FEA, MPa against a limit | Closed-form models only, per building block (bracket bending, tip-over, snap strain). A design written as code gets **no** strength result. No mesher, no solver, no load or fixture picking | `form/checks.py:156`, `form/recipes/shelf_bracket.py`; the test design above returned no strength row | partial (close to missing) |
| 15 | Against a drawing: every dimension | The brief's numbers become assertions measured on the solid (the proof sheet). A PDF is read as pictures by the agent; dimensions are not extracted and compared one by one | `form/contract.py`, `form/documents.py`; `design_brief`, `read_document` | partial |
| 16 | Fit and clearance | Assembly overlap, smallest gap, declared fits (`Mate`), ISO 286 limits, and a statistical fit model with a printer's bias and spread | `form/assembly.py`, `form/collide.py`, `form/fit.py`, `form/craft/fits.py` | better |
| 17 | Range of motion | Joint chains swept through their range with everything they carry, the first contact angle, ratchet positions, screwdriver reach, a time budget with a stated partial result | `form/assembly.py:analyse`, `tests/test_assembly.py` | better |
| 18 | Weight and centre of mass | Volume always; mass as volume times a typical density, or the slicer's grams; centre of mass only inside the tip-over model of some building blocks. No inertia, no per-part table, no tool | `form/material_library.py:mass`, `form/checks.py:162` | partial |
| 19 | CNC machining check | A minimum feature size for the named process (0.8 mm), labelled heuristic. No tool access, corner radius, depth ratio or setups | `form/purpose.py:43`; the test design above: "Thinnest feature: 3.75 mm [heuristic]" | partial (close to missing) |
| 20 | Injection moulding check | The same minimum feature size only. No draft, undercuts, wall uniformity or sink | `form/purpose.py:47` | partial (close to missing) |
| 21 | Sheet metal check | A process label and a minimum feature size only | `form/purpose.py:51` | missing |
| 22 | Powder printing (SLS, MJF); resin; metal printing | Nothing beyond FDM | no source match | missing |
| 23 | KiCad board checks; board review | Nothing | no source match | missing |

### Make

| # | Their capability | Form Studio today | Evidence | Grade |
|---|---|---|---|---|
| 24 | G-code for CNC (CAM) | Nothing. A G-code reader and a layer-by-layer player exist for prints | `form/toolpath.py`, `form/simulate.py` | missing |
| 25 | Slice and print (OrcaSlicer or Bambu) | Seven slicers, every printer set up in each, per-design settings with reasons, several plates, a played-back simulation, every printer compared. Never sends a print, by rule | `form/adapters/*.py`, `form/slicer_open.py`, `form/slicecompare.py`, `tests/test_slicers.py` | better |
| 26 | Flat pattern DXF | DXF is read, not written. No unfolding | `form/formats.py` | missing |
| 27 | SendCutSend preflight | Nothing | no source match | missing |
| 28 | Export STEP, STL, 3MF, zip | STEP, STL, OBJ, GLB, 3MF with colours, a release zip with SHA-256 hashes and a manifest, the whole design as one `.formstudio` file | `form/kernel.py:987`, `form/maker_docs.py:release_files_zip`, `form/bundle.py` | better |
| 29 | Board fab files (Gerbers); board STEP | Nothing | no source match | missing |

### Document

| # | Their capability | Form Studio today | Evidence | Grade |
|---|---|---|---|---|
| 30 | Drawing with ISO 286 fits | No drawings. A six-view render sheet (a picture) and ISO 286 numbers in `craft.fits` | `form/render.py`, `form/craft/fits.py` | missing |
| 31 | 3D PMI | STEP is written without PMI | `form/kernel.py:987` | missing |
| 32 | Parts list | `BOM.csv` in every release: printed parts and bought hardware, grams with their evidence | `form/maker_docs.py:bom` | equal |
| 33 | Assembly steps PDF | A parts page, then one page per part in attach order with an arrow to where it seats | `form/instructions.py`; `assembly_instructions` | equal |
| 34 | Exploded view | Exploded offsets relative to the parent, in the viewport, the renders and the instructions | `form/craft/assemble.py`, `Viewport.qml` | equal |
| 35 | Pictures | Engine renders, a four- or six-view sheet, a share card with evidence labels | `form/render.py`, `form/share.py` | equal |
| 36 | Motion (a film of the mechanism) | Joint sliders in the viewport; `animate` makes turntables and parameter morphs only. No joint motion over time, no export of it | `form/animate.py` | partial |
| 37 | Photoreal render | Blender scenes, nine materials, material zones per part, layer lines at the slicer's height, turntable video | `form/adapters/blender.py`; `render_photo`, `turntable` | equal |
| 38 | Test plan | `MEASUREMENT_PLAN.md`: what to measure on the made part. Not a test plan for the requirements | `form/maker_docs.py:measurement_plan` | partial |
| 39 | Results write-up | `record_physical_result` keeps what the person reports; a print report. No written report of tests against requirements | `form/maker_docs.py:print_report` | partial |
| 40 | Robot files: URDF, SRDF | Nothing (joints and parts exist to write them from) | no source match | missing |
| 41 | MuJoCo model | Nothing | no source match | missing |

### Platform

| # | Their capability | Form Studio today | Evidence | Grade |
|---|---|---|---|---|
| 42 | Runs on your own Claude or ChatGPT account | Seven agent apps, eight model APIs, local models, any provider by address | `form/agents/`, `form/router.py` | better |
| 43 | Mac and Windows | macOS, Windows and Linux; native Qt Quick, no web view | `docs/APP.md`, `form/app/` | better |
| 44 | Project sync, backups, GitHub | One-file export and import. No sync, no scheduled backup | `form/bundle.py` | partial |
| 45 | A stale result says so | Every artifact is current only under the key of the head revision's inputs | `Studio.keys` in `form/studio.py` | better |
| 46 | Install size about 5 GB | About 0.8 GB unpacked; optional engines are separate and opt-in | `docs/APP.md`, `form/engines.py` | better |

**Count over 46 rows:** better 14, equal 6, partial 15, missing 11. The gap is concentrated in three places:
modelling by hand (rows 4 to 7), engineering checks other than printing (14, 18 to 23), and manufacturing and
documentation other than printing (24, 26, 27, 29 to 31, 40, 41).

## Where Form Studio is already ahead

Each claim was checked against the source or a run.

| Claim | Verdict | Evidence |
|---|---|---|
| Real slicers on every printer | True | Seven adapters (`bambu`, `orca`, `prusa`, `superslicer`, `qidi`, `elegoo`, `snapmaker`); `list_printers`, `compare_printers`; the competitor lists OrcaSlicer and Bambu |
| Provenance of every number | True | The test design's parameters came back as "60 mm (assumed)"; every check row carries `[computed]` or `[heuristic]` |
| A release approval with hashes | True | `request_release`, `verify_release`; only a person approves; SHA-256 per file (`form/studio.py`) |
| Triage of any input | True | `form/triage.py` routes meshes, scans, CAD, drawings, zips, photos, PDFs, links and words; `tests/test_triage.py` |
| Mesh and scan to CAD with measured deviation | True | `form/recon/`, `docs/RECON_BENCH.md`: 100 % editable on six of seven mechanical fixtures, deviation 0.001 to 0.012 mm. The competitor has no equivalent. One correction to our own wording: the bench times are 15 to 207 s, so "in seconds" holds only for the simplest route |
| The joint sweep | True | `form/assembly.py:analyse` step 3; chains, first contact angle, budget |
| The native app | True | Qt Quick on PySide6, no web view; the competitor is Electron |
| The Lightdesk interface | True | `docs/design/DIRECTION.md`, `Theme.qml`, `Glass.qml` |
| 97 MCP tools | True | `form tool` listed 97; `tests/test_tool_counts.py` |
| Headless parity | True | `form tool NAME '{json}'` ran every call of this audit with no window |
| No usage data leaves the machine | True, and not yet said anywhere | No telemetry code in `form/`; the competitor counts usage by default |
| Install size | True | About 0.8 GB against about 5 GB |

Also ahead and absent from their list: the brief as a contract with a proof sheet, the design critique against
product classes, concepts and candidates built in parallel, goal seek on real kernel builds, sculpted bodies as
exact NURBS, game assets, per-feature face attribution, and edits by named operation rather than by file.

## Principles for every wave

1. **Exceed, do not copy.** Each wave names the point where it passes the reference, and that point is measured.
2. **Every number says how it is known.** New evidence wording is fixed here: `simulated (FEA, linear static,
   converged to N %)`, `simulated (stock removal, cell N mm)`, `computed (B-rep)`, `rule (source, date)`.
   A result that did not converge, or a rule that could not be evaluated, is shown as such and never as a pass.
3. **A study is an artifact.** Each new result is stored under a key from `Studio.keys` (geometry, material, loads,
   mesh settings, engine version). A newer revision makes it stale by construction.
4. **Verified against known answers.** Each solver ships with a verification suite of textbook or published cases
   in `tests/`, with the reference value and the accepted error in the test.
5. **Headless parity.** Each capability is an MCP tool and a `form` command first; the window calls the same code.
6. **Engines are opt-in.** Each new library is an entry in `form/engines.py` with its size and licence, installed
   from the launcher or Settings with one click of consent, never bundled into the core download. The kernel
   worker (`form/worker.py`) is the only process that imports OCCT; solvers run in workers too.
7. **By hand and by agent write the same source.** A feature made with a tool in the window becomes a method in
   the design's code, as `add_text` and `add_feature` do today, so the agent reads and edits it like its own.
8. **Lightdesk.** New surfaces are panes of glass over the room. Results appear on the part (a map, a marker) and
   as mono numbers with units. No ribbon, no four-tab grid, no dividers.
9. **Licences.** MIT stays the licence of Form Studio. LGPL libraries are used as unmodified wheels; GPL programs
   run only as separate processes the person installs. Each is recorded in `THIRD_PARTY_NOTICES.md`. The licences
   below are to be confirmed at integration against each project's own file.

## The waves

Sizes are agent-days for one agent, including tests, documentation, screenshots and the site. Total: 79.

| Wave | Outcome | Size | Closes rows |
|---|---|---|---|
| A | The Bench: one surface for every study, route and document | 3 | 11, 45 |
| B | Modelling by hand, with the agent in the loop | 12 | 4, 5, 6, 7 |
| C | Mass properties and engineering materials | 2 | 12, 18 |
| D | Strength studies with a stated error | 10 | 14 |
| E | Manufacturability with fixes the agent applies | 8 | 19, 20, 22 |
| F | Drawings, GD&T and PMI from the B-rep | 10 | 15, 30, 31 |
| G | Standard parts and a buyable parts list | 4 | 13, 32 |
| H | Sheet metal and cut parts | 5 | 21, 26, 27 |
| I | Motion studies and robot files | 5 | 36, 40, 41 |
| J | CAM with a stock simulation | 11 | 24 |
| K | Board and enclosure loop | 5 | 23, 29 |
| L | Test plan, results report, backups | 4 | 38, 39, 44 |

### Wave A. The Bench (3 days)

**Outcome.** One pane lists everything that can be asked of the open design, in three groups that follow the
stages: **Studies** (Review), **Routes** and **Documents** (Make). Each line has a state dot (never run, current,
stale, failed), its headline number with evidence, and a run action. A stale study says which revision it describes.

- **Engine.** `form/studies.py`: a registry (id, group, needs, inputs, key function, runner, evidence class) and a
  store beside the revision. Existing work registers first: assembly checks, thickness, fit, slice, print
  simulation, BOM, instructions, renders. `Studio.keys` gains one key per study.
- **Interface.** `Bench.qml` in the Program pane of Review and Make, as a listing in the Program's own style (line,
  name, mono number, role). The palette (Ctrl/⌘ K) finds every entry. A running study uses the existing activity bar.
- **Tools and CLI.** `list_studies`, `run_study`, `get_study`; `form study list|run|show <project> [id]`.
- **Tests.** Registry round trip; a commit makes every study of the old revision stale; the palette lists all.
- **Accepted when.** Every existing check, route and document is reachable from the Bench and from `form study`;
  no study can show as current for a revision it was not computed from.
- **Beyond the reference.** Their Toolbox is a launcher of chat prompts. The Bench is a record: state, evidence and
  staleness per entry, the same over MCP.

### Wave B. Modelling by hand, with the agent in the loop (12 days)

**Outcome.** A person can build and change a part without the agent, and the agent sees every step as source.

Three parts, each shippable:

- **B1. The tree (3 days).** In the Program pane: a rollback bar (drag to build up to a feature; the viewport shows
  that state from the feature checkpoints, in milliseconds), suppress and restore, reorder by drag (refused with
  the reason when a later feature loses what it reads), rename, and "what does this depend on" from the values each
  feature reads. Engine: `edit_design` ops `suppress`, `restore`, `move`, `rename`; `render(upto=feature)`.
- **B2. Picked features (3 days).** Fillet and chamfer on picked edges; a hole wizard on a picked face (plain,
  counterbore, countersink, tapped; sizes from `form.parts`, ISO 273 and tap drills with their source); linear and
  polar pattern of a feature; shell with a picked open face. Each previews as a draft with computed impact and is
  written as a feature method. `add_feature` gains kinds `fillet`, `chamfer`, `hole`, `pattern`, `shell`. Edges are
  referenced by a stable query (the owning features and geometry class), not by index; when a rebuild cannot find
  the edge the feature says so and is left out, as the engine's fillet fallback does today.
- **B3. Sketch on a face (6 days).** Pick a planar face or a datum plane; the sketch pad opens in place on the part,
  backed by `form.sketch2d`: draw, constrain, dimension, see degrees of freedom left, drag with the solver live.
  Then extrude, cut, revolve or sweep. An existing feature built from a `sketch2d` profile opens in the same editor;
  changing a dimension is a parameter change. New tools `get_sketch`, `edit_sketch` (ops on entities, constraints
  and dimensions); `add_feature` kinds `extrude`, `cut`, `revolve`.

- **Interface.** The tools live in the tool dock as one more capsule group, with their options beside the active
  tool; no ribbon. The sketch is drawn in the datum colour on the face, dimensions in mono.
- **Agent in the loop.** Every hand edit posts a revision card in the conversation ("You added Fillet 2: 4 edges,
  r 2 mm"). A failed hand feature has **Fix with your agent**. The agent can be asked to "make this sketch
  symmetric" and answers with `edit_sketch` ops, visible as they apply.
- **Tests.** Each kind builds, appears in the source, survives a parameter sweep (the editability measure the mesh
  bench already uses), and round-trips through `get_design_source`. Sketch solver cases for under- and
  over-constraint. UI journeys in `scripts/headless`.
- **Accepted when.** The audit's bracket can be made from Start blank with no agent in under two minutes; rollback
  to any feature shows in under 100 ms from checkpoints; every hand feature is one named method in the source.
- **Beyond the reference.** Their hand edits and the agent's script are two things kept in step. Here there is one
  source, so a hand edit is reviewable, diffable (`geometry_diff`), revertible and optimisable (`optimize` can vary
  a hand-made fillet).

### Wave C. Mass properties and engineering materials (2 days)

**Outcome.** Mass, centre of mass and the inertia tensor of every part and of the assembly in any pose, in the
size line, on concept cards and in the parts list. Materials carry mechanical properties with sources.

- **Engine.** `form/massprops.py` on OCCT `GProp` (exact on the B-rep; on a mesh body from the closed mesh, labelled
  so). `form/material_library.py` gains `E`, Poisson's ratio, yield and ultimate strength, thermal expansion,
  each with a source and a spread; printed plastics carry a stated knock-down by orientation, labelled *modelled*.
  A value nobody sourced is absent, never a default.
- **Tools and CLI.** `mass_properties`; `form mass <project> [--part P] [--pose JSON]`.
- **Interface.** The centre of mass as a marker in the viewport (a toggle in Analyze); mass on the size line with
  its evidence ("412 g, computed: volume × 2700 kg/m³, typical").
- **Tests.** Analytic solids (box, cylinder, hollow sphere) to 1e-6 relative; assembly in two poses.
- **Beyond the reference.** Inertia and pose-dependent centre of mass, and every material number with its source.
  This wave is the foundation of D, I and L.

### Wave D. Strength studies with a stated error (10 days)

**Outcome.** "Will it hold?" answered on any design: pick fixed faces and loaded faces on the part, get stress,
displacement and a safety factor, with the discretisation error stated and the result refused when it did not
converge.

- **Engine and libraries.** `form/fea/` in a worker.
  - Meshing: `netgen-mesher` (LGPL-2.1, wheels for the three platforms), quadratic tetrahedra from the B-rep.
    Gmsh (GPL-2 or later) only as an optional separate process if Netgen fails on a shape.
  - Solving: `scikit-fem` (BSD-3) with `scipy` (BSD-3) sparse solvers, in process, deterministic. Linear static
    first; then modal (natural frequencies) and linear buckling (a load factor), which are eigenproblems on the
    same matrices; then steady heat and thermal stress.
  - Cross-check: CalculiX (GPL-2) as an optional engine run as a separate program. When installed, the same deck is
    solved twice and the difference is reported. Never required.
- **What makes it honest, and past the reference.**
  - **Mesh convergence, automatic.** At least three refinements driven by an a-posteriori error estimator; the
    result is the extrapolated value with "discretisation error ≤ N %", and the convergence curve is kept.
  - **Singularities are named.** Where stress grows without bound under refinement (a sharp re-entrant corner, a
    point load, a fixed edge), the study says "not converged here: sharp corner; add a fillet or read the stress
    1 mm away" and offers the fix. It never reports a peak that depends on the mesh.
  - **Equilibrium is checked.** Reactions against applied loads, to a stated residual; a failed balance fails the
    study.
  - **A hand estimate beside it.** Where the geometry reads as a beam or a plate with a hole, the closed-form value
    is shown next to the result.
  - **Assemblies.** Bonded at declared mates first; bolted joints with preload from `form.parts.bolted_joint` as a
    modelled connector. Sliding contact only through CalculiX, labelled as such.
  - **Printed parts.** Anisotropy and infill are not simulated; the result is for a solid isotropic part, and the
    knock-down applied is named.
- **Tools and CLI.** `strength_study` (define, run, read; fixtures and loads by face reference from
  `analyze_selection`), `get_study`; `form strength <project> --fix FACE --load FACE:N:DIR --material M`.
  `optimize` and `make_lighter` accept `fea.safety_factor >= 2`.
- **Interface.** In Review: pick faces with the Annotate tool, typed loads in a small glass card with units; the
  stress map on the part with a legend that says what it does not tell you; deformed shape with a scale control; a
  convergence chart; the verdict as one line on the Bench.
- **Tests (verification suite).** A cantilever against beam theory; a plate with a hole against a stress
  concentration of 3; NAFEMS LE1 and LE10; a free-free bar's first frequencies; Euler buckling of a column. Each
  within its stated error. A sharp-corner case must return "not converged here".
- **Accepted when.** The suite passes on the three platforms; no result without an error statement; the study is a
  stale artifact after any geometry change; engine download under 150 MB (to be measured).

### Wave E. Manufacturability with fixes the agent applies (8 days)

**Outcome.** For the process the design names, every problem is shown on the part with the rule, its source and a
fix. **Fix** applies the change as a revision and the check runs again, so the fix is proved.

- **Engine.** `form/dfm/`, one module per process, all on the B-rep with rays for visibility:
  - **Moulding:** draft per face against a pull direction (exact from face normals), undercuts, a proposed parting
    line and pull direction (the one with least undercut area), wall uniformity (from `form/thickness.py`), rib to
    wall ratio, sink risk at bosses and thick junctions.
  - **CNC:** reachability per setup direction for a 3-axis machine and a stated tool, internal corner radius against
    the tool, pocket depth to tool diameter, thin walls and floors, the minimum number of setups, holes off standard
    drill sizes.
  - **Powder, resin and metal printing:** minimum wall and feature, trapped volumes and escape holes, part size
    against a stated machine, engraving depth.
- **Rules as data.** `form/dfm/rules/*.toml`: each rule has a value, a source and a date. A rule with no source is
  labelled *rule of thumb*. People can override a rule for their shop; the override is recorded as *specified*.
- **Fixes.** Each finding names an operation from `form/refine` or a parameter change (add 1° draft to these faces,
  raise this fillet to the tool radius, thicken this wall to 1.0 mm). Applied through `edit_design`, never silently.
- **Tools and CLI.** `manufacturability` (process, options), `apply_fix`; `form dfm <project> --process injection`.
- **Interface.** A draft map and an access map join the Analyze maps; findings list in Review with **Fix** and
  **Fix all with your agent**.
- **Tests.** Fixture parts with a known count of undercuts, a known draft, an unreachable pocket; each fix makes its
  finding pass.
- **Beyond the reference.** They report and advise. Form Studio proposes the parting line, applies the fix and
  proves it with the same check, and every rule shows its source.

### Wave F. Drawings, GD&T and PMI from the B-rep (10 days)

**Outcome.** A shop drawing made from the solid, complete by measurement rather than by review; the same
tolerances carried in the STEP file; and a drawing someone else made checked against the part.

- **Engine.** `form/drawing/`:
  - Views by OCCT hidden-line removal in the kernel worker: three views and an isometric, sections through chosen
    planes, detail views, first or third angle, scale chosen for the sheet.
  - Dimensions from what the design knows: each parameter of each feature is dimensioned once in the view where it
    is true length; hole callouts from the hole wizard and `form.parts`; fits from `Mate` as ISO 286 classes with
    their limits; centre marks and centre lines.
  - **GD&T** from declared datums and the brief's contract: feature control frames (position of a bolt circle,
    flatness of a mounting face, perpendicularity of a bore) only where the design or the person states them.
  - A title block with the revision, material, mass (wave C), general tolerance and the release hash.
  - Output: vector PDF and SVG (drawn by Qt, already in the app), DXF with `ezdxf` (MIT).
- **PMI.** STEP AP242 with semantic dimensions, tolerances and datums through OCCT's XCAF document; the file is
  read back and each annotation compared with what was written.
- **Check against a drawing.** `check_drawing` reads a DXF's dimensions exactly, or a PDF's by the agent with each
  value located on the page, and measures each on the solid: PASS, FAIL or UNREAD per dimension, never a summary.
- **Completeness, computed.** The drawing reports "N of N parameters dimensioned, 0 twice" and lists any size that
  cannot be shown in the views it has.
- **Tools and CLI.** `drawing`, `check_drawing`, `export_pmi`; `form drawing <project> --sheet A3 --out part.pdf`.
- **Interface.** A Documents entry on the Bench; the sheet opens as a light pane (paper is the one bright thing on
  that screen), dimensions selectable and tied to the feature they came from; dragging a dimension moves its
  placement only, and the placement is kept in the design.
- **Tests.** View geometry against known projections; every parameter of the exemplar designs dimensioned once;
  PMI read-back; DXF read-back with Form Studio's own reader.
- **Beyond the reference.** They say their drawings need review. Here dimension coverage is proved, tolerances come
  from the declared fits, the drawing carries the release hash, and the STEP carries the same PMI.

### Wave G. Standard parts and a buyable parts list (4 days)

**Outcome.** Put a real screw, nut, bearing or insert in the design by picking a hole, and get a parts list that a
buyer can order from.

- **Engine.** `form/catalog.py` over `bd_warehouse` and `form.parts`: full standard designations (ISO 4762 M3×10,
  class and finish when stated), preferred lengths, mass (wave C), and the mating feature (clearance, counterbore,
  insert pocket) cut with it. The parts list groups by designation with quantity.
- **Supplier references.** Kept as data the person or the agent supplies with a link (`fetch_link`), each stamped
  with its source and date. No supplier number is ever generated. See the owner decision on catalogue services.
- **Tools and CLI.** `standard_part` (find, place), `bom` (CSV, and a PDF page for the drawing set).
- **Interface.** A part picker as a searchable listing in a sheet; placed hardware in the Program as its own lines.
- **Tests.** Designation strings against the standards' tables; the cut feature fits the part (assembly check).
- **Beyond the reference.** The hole, the part, the fit check and the parts list line are one action; nothing is
  sent to a third party to find a screw.

### Wave H. Sheet metal and cut parts (5 days)

**Outcome.** A bent part designed as sheet metal, checked, unfolded, and exported as a flat pattern DXF; flat parts
for laser, waterjet or router exported as clean profiles.

- **Engine.** `form/sheet/`: recognise constant-thickness parts (planes and cylindrical bends), unfold with a bend
  table (K-factor per material and thickness, each with its source), reliefs, bend lines and directions on their
  own layers. Checks: minimum flange, hole to bend, bend radius against thickness, collisions in the flat. DXF by
  `ezdxf`; kerf and nesting are left to the shop.
- **Verification.** The flat is folded back numerically and compared with the solid (developed length to
  0.01 mm); the DXF is read back and its outline compared with the unfolded face.
- **Service preflight.** Rule tables per service (minimum hole, minimum bridge, maximum size per material), each
  with the page and date it came from; a table older than 90 days says so. Nothing is uploaded.
- **Tools and CLI.** `flat_pattern`, `export_dxf`, `service_preflight`; `form flat <project> --out part.dxf`.
- **Interface.** The Assembly tool's view switch gains **Flat**; the fold animates between bent and flat.
- **Beyond the reference.** The unfold is verified by folding it back, and the K-factor is a sourced number the
  person can replace with their shop's.

### Wave I. Motion studies and robot files (5 days)

**Outcome.** A mechanism played over time, checked along the whole motion, exported as a film and as robot files.

- **Engine.** `form/motion.py`: a timeline of joint targets and couplings (gear ratios, rack and pinion, cams from
  `craft.mechanisms`), clearance along the motion (the sweep engine in `form/collide.py`), holding torque per joint
  under gravity from wave C. `form/robot.py`: URDF, SRDF and MJCF written from the assembly's joints, limits,
  masses and inertias, with meshes exported per link.
- **Simulation.** MuJoCo (Apache-2.0) as an optional engine: the written model is loaded and stepped, and what it
  reports (it loads, it settles, joint ranges reached) is labelled *simulated*. Without it the files are written
  and labelled *not loaded in a simulator*.
- **Tools and CLI.** `motion_study`, `robot_files`; `animate` gains `kind="motion"`.
- **Interface.** The History timeline's scrubber is reused for motion: keyframes as ticks, a clearance trace under
  it, the first contact marked.
- **Tests.** A four-bar against its closed-form coupler curve; URDF and MJCF parsed back; inertia against wave C.
- **Beyond the reference.** Contact found along the whole motion with the angle it happens at, torque per joint,
  and robot files whose inertias are computed from the B-rep and a sourced density.

### Wave J. CAM with a stock simulation (11 days)

**Outcome.** Toolpaths for a 3-axis mill or router from the design, played in the viewport, with the material that
would be left or wrongly cut measured before any G-code is released.

- **Engine and libraries.** `form/cam/`, no FreeCAD:
  - Operations from the features the design already names: face, 2.5D pocket and contour (offsets with
    `pyclipper`, MIT wrapper over Clipper, Boost licence), drilling cycles from the hole wizard, 3D roughing and
    finishing with `opencamlib` (LGPL-2.1).
  - A tool library and feeds and speeds as data with sources; a value the person did not confirm is *assumed* and
    blocks release.
  - Posts for grbl, LinuxCNC, Mach and a generic Fanuc dialect; the posted file is parsed back and replayed.
  - **Stock simulation:** a height field (3-axis) at a stated cell size removes the swept tool from the stock.
    The result is compared with the target solid: maximum gouge, maximum leftover, a map of both, rapid moves
    through material, holder collisions. Machining time from the feeds, labelled *simulated*.
- **Release.** G-code enters a release only after the simulation is current and a person approves; the release
  says "simulated, not proven on a machine". See the owner decision.
- **Tools and CLI.** `cam_plan`, `cam_simulate`, `cam_post`; `form cam <project> --machine grbl --tool 6mm-flat`.
- **Interface.** The print simulation's player (`PrintSimView.qml`) is generalised: the same scrubber, line-type
  filters and time chart; the stock is drawn as clay being cut.
- **Tests.** A pocket with a known volume removed; a deliberate gouge is found; posted G-code replays to the same
  path; leftover in a corner equals the tool radius geometry.
- **Beyond the reference.** Their CAM is FreeCAD's, with a multi-gigabyte install and no stated check of the
  result. Here the cut is simulated and measured against the design, and the engine is a few megabytes.

### Wave K. Board and enclosure loop (5 days)

**Outcome.** Bring a circuit board and get an enclosure that provably fits it; when the board changes, the
enclosure's checks say what no longer lines up.

- **Engine.** `form/board.py`: read a `.kicad_pcb` (an S-expression parser of our own, no KiCad needed) or a board
  STEP or IDF: outline, mounting holes, component bodies and heights, connectors with their opening direction.
  These become contract assertions on the enclosure: standoffs on the holes, cutouts aligned with connectors,
  clearance over the tallest part, each measured on the solids.
- **The person's own KiCad.** An adapter over `kicad-cli` when KiCad is installed: design-rule and electrical-rule
  checks, Gerbers and drill files, board STEP. Form Studio reports KiCad's own results and never claims them.
- **Tools and CLI.** `board_import`, `board_check`, `board_fab`; `form board <project> FILE`.
- **Interface.** The board as a blueprint companion (already how references are drawn), connectors labelled.
- **Tests.** A fixture board; a moved connector fails the cutout assertion; adapter tests skip without KiCad.
- **Beyond the reference.** They have boards and parts side by side. Here the board is a constraint the enclosure
  is proved against at every revision.

### Wave L. Test plan, results report and backups (4 days)

**Outcome.** A test plan written from what the design claims, a report written only from what was measured, and
designs backed up where the person chooses.

- **Engine.** `form/maker_docs.py` gains `TEST_PLAN` (one test per contract requirement and per study: method,
  instrument, acceptance, sample count) and `RESULTS` (each `record_physical_result` against its test, pass or
  fail, and what remains untested, stated). Backups: a scheduled `.formstudio` export to a folder the person
  picks; nothing leaves the machine unless that folder does.
- **Tools and CLI.** `test_plan`, `results_report`; `form backup`.
- **Beyond the reference.** The report cannot contain a number nobody measured, and it lists what is still unproven.

## Order

Highest impact first for an app whose first promise is creation.

1. **A, the Bench** (3). Small, and every later wave plugs into it.
2. **B, modelling by hand** (12). The largest gap in the creation promise and the first thing an engineer tries.
   B1, then B2, then B3.
3. **C, mass and materials** (2). Cheap, visible at once, and D, I and L need it.
4. **D, strength** (10). The check engineers ask for first, and the clearest place to pass the reference.
5. **F, drawings and PMI** (10). What a part needs to leave the building.
6. **E, manufacturability with fixes** (8).
7. **G, standard parts** (4).
8. **H, sheet metal** (5).
9. **I, motion and robot files** (5).
10. **J, CAM** (11).
11. **K, board and enclosure** (5).
12. **L, test plan, report, backups** (4).

Three tracks can run side by side after A: modelling (B), analysis (C, D, E), documents and making (F, G, H). With
three agents the first eight waves take about four weeks; I, J, K and L follow.

**To start now:** A; B1 with B2; C; the core of D with its verification suite; the views of F.

## What not to do

- **No ribbon and no four-tab Toolbox.** That is their layout. The dock, the stages and the Bench carry the tools.
- **No bundling of FreeCAD, KiCad or a 5 GB install.** Engines stay opt-in and small; KiCad is used only when the
  person already has it.
- **No circuit design.** Schematics, placement and routing are a different product. Form Studio's place is the
  board as a constraint on the mechanical design.
- **No strength result without a stated error,** no safety factor at a singularity, no fatigue, impact or
  nonlinear material claims. What is out of scope is said on the result.
- **No G-code presented as safe to run.** It is simulated and approved by a person; Form Studio never talks to a
  machine, as it never talks to a printer.
- **No invented supplier numbers, prices or stock,** no scraping of supplier sites, no buying.
- **No uploads to fabrication services** and no search terms sent to third-party part services by default.
- **No usage telemetry.**
- **No copying of their code, skills or assets,** although their licence would allow it with notice. Behaviour was
  learned from public pages; the implementation and the design are Form Studio's own.
- **No certification language.** A drawing, a study or a check is evidence with a class, never a sign-off.
- **No tool-count race.** Capabilities are added as few tools with clear arguments; the count is not a goal.

## Owner decisions

Decided by the owner on 2026-11-27: Form Studio is to be the best open-source app in this field at all of it.

1. **Boards: the full loop.** Wave K covers the board and enclosure loop and the person's own KiCad first. A later
   wave K2 adds schematic capture and routing inside Form Studio (on KiCad's file formats, with its rule checks), so
   a product's board and its enclosure are designed together.
2. **Supplier data: both.** Standard designations always, and supplier numbers from the person or a link (wave G).
   An optional catalogue service is added as an opt-in in Settings, off by default, which says before each search
   what is sent and to whom.
3. **CNC G-code in a release: simulated and approved.** G-code goes into a release after a current stock simulation
   and a person's approval, labelled "simulated, not proven on a machine" until a physical result is recorded
   (wave J).
4. **Pace: three tracks at once.** Agents work in separate worktrees in the order of this plan. Each wave is tested,
   reviewed and installed on the Mac before it merges into `dev`.

## Added on 2026-11-28 from the niche sweep

The sweep of the whole niche (`docs/research/2026-11-28-niche-sweep.md`) adds these waves, about 44 agent-days.
Each has its detail, sources and acceptance in that document.

| Wave | Days | Outcome |
|---|---|---|
| M | 5 | Viewport craft: matcap and studio shading presets, zebra, curvature and draft maps, X-ray, a view cube, a picker for overlapping selections, a before/after toggle |
| N | 4 | Direct manipulation: gizmos with typed values, edge drag handles, edit dimensions on the model, draggable numbers |
| O | 4 | A chat that proves itself: sources under each reply, live status, notes of hand edits, author marks, a plan card to approve, saved prompts, commands on the selection |
| P | 4 | Project knowledge: overview, templates, search across everything, local search by description, 30-day recently deleted |
| Q | 7 | Image or words to a mesh, split into parts, rebuilt as features with a deviation map |
| R | 3 | Competing mesh-to-CAD results shown side by side; concept cards with mass and checks |
| S | 3 | One-click print-ready generators (tags, reliefs, trays, knobs) as editable recipes |
| T | 2 | First run with three parts to try and a short tour |
| U | 4 | A code pane that follows the feature list and the viewport |
| V | 3 | Parametric CAD Bench v3 and our own suites run and published |
| W | 2 | A theme from three colour settings with high contrast, and a polish pass every release |
| D2 | 3 | Thermal and natural-frequency studies after strength |

Decided by the owner's standing instruction ("the best at all of it"):

5. **Mesh generators: both.** TRELLIS.2 running locally, and hosted generators (Meshy, Tripo, Hunyuan) on the
   person's own key as an opt-in that says what is sent before each run.
6. **Code pane: read-only by default, editable by a switch.** Edits go through the same edit protocol and proof as
   every other change.
7. **Benchmark: published in full, failures included,** with the commit, the model and how to reproduce it.

Order after this addition: A; O and M beside B1; B2 with N; C; D; F; then E, G, H, I, J, K, L, with P, Q, R, S, T, U,
V, W and D2 placed where they unblock the most.
