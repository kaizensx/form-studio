# MCP reference

Form Studio's engine is an [MCP](https://modelcontextprotocol.io) server. Any MCP client (Claude Code, Codex,
Gemini CLI, Cursor, Claude Desktop and others) can design, check, slice, simulate and prepare a release through it,
with the same engine, project folder and rules as the desktop app. The app follows those changes live.

This page is generated from the server's own tool definitions by `scripts/gen_mcp_docs.py`.

## Connect

The server speaks MCP over stdio. Its command is `form-mcp` (or `form mcp`).

```bash
claude mcp add --scope user form -- form-mcp      # Claude Code
codex mcp add form -- form-mcp                    # Codex
```

Clients configured with a JSON file (Gemini CLI, Cursor, Claude Desktop and most others) use:

```json
{ "mcpServers": { "form": { "command": "form-mcp" } } }
```

`form setup` finds the agents installed on this computer and adds the entry for the ones you select.

## Workflow and rules

Every client receives these instructions when it connects:

```
Form Studio designs 3D-printable parts from parametric recipes and keeps an honest record of what is known.

Workflow: form_overview -> describe_recipe -> create_project (or get_project) -> preview_change ->
render (look at it) -> commit_change -> run_pipeline -> get_project (gate, checks, next actions) ->
request_release (a person approves in Form Studio).

Rules:
- Units are mm, degrees, grams. Only change parameters that describe_recipe lists.
- Always preview_change before commit_change; pass expect_head so you never overwrite a newer revision.
- Provenance is evidence. Mark a value "measured" only when the user measured it and told you the number.
  Never invent physical results; record_physical_result is only for what the user reports.
- A slice is a simulation, not a print. Fit yield is a model. Say so when you report them.
- You cannot approve a release. request_release returns a link that opens the release in Form Studio for the user.
- Nothing here starts a print or sends files anywhere.
- Ask the person only what changes fit, load or safety and you cannot look up: ask_user, one question at a time,
  at most three per task. Outside Form Studio's chat it tells you to ask in your own interface. For a dimension the
  person can measure, use ask_measurement (where to measure, tolerance, a diagram); it updates the design with how
  it was measured.
- A new idea that is not already a precise specification: propose_concepts with 3-4 genuinely different structural
  approaches as real designs (not size variants), a one-line rationale each; then stop and let the person pick.
  Refine the picked one with update_design. Recipes may be used as building blocks; do not offer them to the person.
- Photos: find the scale from a reference object (bank card 85.60 x 53.98 mm, a coin's official diameter, a ruler);
  dimensions read off a photo are "estimated from the photo (scale from <reference>)" and stay assumed until measured.
  Sketches from Form Studio carry structured JSON: it is authoritative over the picture; stated dimensions override
  drawn lengths. STEP/STL: import_reference. PDF drawings: read_document. Download only files the person gave you.
- If the message has a "Purpose:" line, respect it: "just a 3D model" means no slicing and no print talk.
```

## Tools at a glance

66 tools. Read-only tools never change a project.

| Tool | Access | What it does |
|---|---|---|
| [`form_overview`](#form_overview) | read-only | Start here. Engine, slicer, printer, available recipes, existing projects and the bench URL. |
| [`setup_status`](#setup_status) | read-only | What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap. |
| [`install_software`](#install_software) | changes | Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude", "slicer.orca". |
| [`describe_recipe`](#describe_recipe) | read-only | Parameters (unit, range, group, the feature each one drives), features and what the recipe checks. |
| [`design_guide`](#design_guide) | read-only | Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter, holder, mechanism...). |
| [`read_document`](#read_document) | read-only | Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). |
| [`create_design`](#create_design) | changes | Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass, built with build123d. |
| [`update_design`](#update_design) | changes | Replace a design's code as a new revision (history keeps every version). |
| [`get_design_source`](#get_design_source) | read-only | The exact code a revision was built from (built-in recipes return their recipe file). |
| [`create_project`](#create_project) | changes | Create a project from a built-in recipe (form_overview lists them: gridfinity_bin, storage_box, pegboard, device_stand, ...). |
| [`get_project`](#get_project) | read-only | Current revision with every parameter and its provenance, output status (current/stale/failed/missing), checks, fit model, next best actions, simulated slice, file paths, release gate and bench link. |
| [`preview_change`](#preview_change) | read-only | Build a candidate change for real and report what it would touch, without saving anything: changed features, interface dimensions, stability, fit yield, which outputs it would invalidate. |
| [`commit_change`](#commit_change) | changes | Save a change as a new revision (history is never rewritten). |
| [`run_pipeline`](#run_pipeline) | changes | Regenerate whatever is not current: solid -> STEP+STL -> checks -> slice. |
| [`get_job`](#get_job) | read-only | Status of a pipeline job started by run_pipeline/commit_change; waits up to wait_s for it to finish. |
| [`render`](#render) | read-only | Look at the part. Returns a PNG rendered from the real kernel geometry, coloured by feature. |
| [`animate`](#animate) | read-only | Make motion from real geometry. |
| [`compare_revisions`](#compare_revisions) | read-only | What changed between two revisions: parameters, features, interfaces, stability, fit. |
| [`checkout_revision`](#checkout_revision) | changes | Make an earlier revision the head again (nothing is deleted). |
| [`set_print_setup`](#set_print_setup) | changes | Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from suggest_orientation), the acceptable total fit gap window, and whether the pipeline slices automatically. |
| [`explore_alternatives`](#explore_alternatives) | read-only | Build a small grid of real variants (1-2 parameters, up to 5 values each) and rank them. |
| [`optimize`](#optimize) | read-only | Goal seek: search parameter ranges for the best design that meets constraints. |
| [`slice_test_piece`](#slice_test_piece) | changes | Cut a thin ring through the fit interface of this revision and slice it, so a cheap test print can check the fit before the whole part. |
| [`record_physical_result`](#record_physical_result) | changes | Record what the USER observed after a real print. |
| [`request_release`](#request_release) | read-only | Check whether the head revision can be released and hand the decision to the user. |
| [`verify_release`](#verify_release) | read-only | Re-hash every file of a release against its manifest and say whether it still matches the head revision. |
| [`open_in`](#open_in) | changes | Open a current output in the user's own software: what = step \| stl \| 3mf \| gcode \| folder. |
| [`open_bench`](#open_bench) | changes | The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases. |
| [`brief_presets`](#brief_presets) | read-only | Brief templates for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure, car accessory): the questions worth asking, environment defaults (temperature, humidity, UV, load), a material to start from and the checks to plan for. |
| [`import_reference`](#import_reference) | changes | Import an existing part (STEP or STL, e.g. a Raspberry Pi 5 STEP from the manufacturer) into a project's references. |
| [`freecad_macro`](#freecad_macro) | read-only | Write a FreeCAD macro (.FCMacro) next to the current STEP export. |
| [`analyze`](#analyze) | read-only | An analysis map of the part, computed from the real geometry: a picture with its legend, and the statistics. |
| [`measure`](#measure) | read-only | Measure the part. Points are [x, y, z] in millimetres in the design frame. |
| [`analyze_selection`](#analyze_selection) | read-only | Analyse a selection on the CAD solid without saving it. |
| [`list_annotations`](#list_annotations) | read-only | The selections the person named and kept on this design (annotations): name, note, the revision they were made on, the picked items and their computed analysis, and `text` describing each. |
| [`annotate`](#annotate) | changes | Keep a selection on the head revision with a name and a note (for example a place you want the person to look at, or one you changed). |
| [`set_appearance`](#set_appearance) | changes | Colour (#rrggbb) and material of the whole design (part="") or of one part (an assembly part id from get_project / render). |
| [`suggest_orientation`](#suggest_orientation) | read-only | Rank the ways the part can lie on the plate: the six axis orientations plus every flat face on its convex hull. |
| [`print_simulation`](#print_simulation) | read-only | Look at the sliced print as it would stand at the end of `layer` (1-based; default: finished). |
| [`estimate_cost`](#estimate_cost) | read-only | Filament, electricity and machine-time cost of the current slice, per plate and for `copies`, plus the same volume in the other materials the slicer has presets for. |
| [`plate_plan`](#plate_plan) | read-only | How the design's printed parts go onto plates: each part as it lies on its own (orientation, size, material), the plates they are packed onto when the design does not fit one plate (or its parts differ in material), parts too big for the plate, and per plate the slicer's time and filament when it has been sliced. |
| [`set_part_print`](#set_part_print) | changes | Print settings for one printed part of a multi-part design (part ids from plate_plan): orientation (a named one, a "down:x,y,z" id, or "auto" for the best-ranked way for that part alone), material (PLA, PETG, TPU, ...; parts in different materials go on different plates, each sliced with its own filament), color ("#rrggbb"). |
| [`pack_plate`](#pack_plate) | read-only | Do `copies` of this design fit on one plate? |
| [`render_photo`](#render_photo) | changes | A realistic-looking render of the current revision's exported STL, made by Blender headless (if installed). |
| [`save_variant`](#save_variant) | changes | Save a named variant of the design ("Travel version", "Thick walls"): a complete set of parameter values kept in the project next to the revisions. |
| [`list_variants`](#list_variants) | read-only | The head and every saved variant side by side: size and volume (computed), print time and grams (simulated, only when the variant is a revision with a current slice), fit yield (modelled), checks, and each variant's differences from the head. |
| [`share_card`](#share_card) | read-only | A 1600 x 900 share image of the head revision: the part with dimension lines, its name, size and volume (computed), print time and grams (simulated; only if the slice is current), checks, the revision and "Designed with FORM". |
| [`rename_project`](#rename_project) | changes | Change a project's display name (up to 80 characters). |
| [`duplicate_project`](#duplicate_project) | changes | Copy a project with its revisions, variants and built outputs under a new id (from the new name; default "<old name> copy"). |
| [`delete_project`](#delete_project) | changes | Delete a project by moving its whole folder to the trash folder inside the projects folder (<projects folder>/.trash/<id>-<UTC time>). |
| [`list_printers`](#list_printers) | read-only | Every printer set up in every installed slicer (the user's own presets and the system printers they enabled), with slicer, bed size and nozzle, plus the default printer. |
| [`choose_printer`](#choose_printer) | changes | Use a printer for one design (`project`) or as the default for designs without their own choice (`default=True`, written to studio.toml after a backup). |
| [`ask_user`](#ask_user) | read-only | Ask the person one question and wait for the answer. |
| [`ask_measurement`](#ask_measurement) | changes | Ask the person to measure one dimension of the design, and wait. |
| [`propose_concepts`](#propose_concepts) | changes | For a new idea: build 2-4 genuinely different concepts as real designs, so the person can pick one. |
| [`pick_concept`](#pick_concept) | changes | The person picked a concept (in words; in the app they pick on the board). |
| [`list_concepts`](#list_concepts) | read-only | Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>. |
| [`suggest_replies`](#suggest_replies) | read-only | Offer up to 3 short follow-up messages the person might send next (each under 80 characters, written as the person would say it, e.g. "Make the walls 2 mm"). |
| [`list_starters`](#list_starters) | read-only | The starting points Home offers, ranked from what this person designs (their projects' recipes and briefs, their printer and material, what they pinned or used): {prompts: [{id, text, source, pinned}], briefs: [...]}. |
| [`recipe_library`](#recipe_library) | read-only | Search the recipe library: built-in recipes, recipes the person installed ("mine") and the community index on the project website. |
| [`export_recipe`](#export_recipe) | changes | Write an installed ("mine") recipe as one .formrecipe file: its code, meta.json (parameters, author, tags, the code's SHA-256) and preview.png drawn from a real build at its defaults. |
| [`prepare_recipe_submission`](#prepare_recipe_submission) | changes | Prepare an installed recipe for the community gallery: the community/recipes/<id>/ folder (written into `folder` when given), what the gallery's checks would refuse, and the link to GitHub's recipe issue form with the fields filled in. |
| [`design_as_recipe`](#design_as_recipe) | changes | Turn a design's current code into a recipe whose defaults are the design's values; ranges narrow a parameter's range ({key: [min, max]}, never wider than the code's own). |
| [`export_project`](#export_project) | changes | Write the project, its conversations and the code its revisions were built from to one .formstudio file (default: <projects folder>/<project>.formstudio). |
| [`import_project`](#import_project) | changes | Import a .formstudio or .formproj archive (or a conversation .json) from an absolute path. |
| [`export_conversation`](#export_conversation) | read-only | A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again). |

## Tools

### `form_overview`

*Read-only.*

Start here. Engine, slicer, printer, available recipes, existing projects and the bench URL.

### `setup_status`

*Read-only.*

What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap.
Never run a fix without asking the user; the simplest path is to ask them to run `form setup` in a terminal.

### `install_software`

Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude",
"slicer.orca". Without confirm=True nothing runs: you get the exact commands to show the user. Ask the user
first, then call again with confirm=True. Never asks for a password; sign-in is not an install.

| Argument | Type | Required |
|---|---|---|
| `id` | string | yes |
| `confirm` | boolean |  |
| `method` | string \| null |  |

### `describe_recipe`

*Read-only.*

Parameters (unit, range, group, the feature each one drives), features and what the recipe checks.

| Argument | Type | Required |
|---|---|---|
| `recipe` | string | yes |

### `design_guide`

*Read-only.*

Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter,
holder, mechanism...). Returns the contract for a design written as code, the rules, and a complete example
that builds. Then call create_design.

### `read_document`

*Read-only.*

Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). PDF pages come
back as images, because a drawing's dimensions are graphics that text extraction loses, plus any text on the page.
pages: "1", "1-3", "2,5" (at most 4). Use this for official dimensions of boards, devices and hardware.

| Argument | Type | Required |
|---|---|---|
| `source` | string | yes |
| `pages` | string |  |

### `create_design`

Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass,
built with build123d. FORM builds it, and with run=True exports, checks and slices it. Load or build errors come
back with the line and a hint; fix and call again. Then render(view="sheet") and look at it.
language="openscad": source is an OpenSCAD file; parameters come from Customizer comments (`w = 40; // [20:1:120]`).
OpenSCAD output is a mesh: no STEP, no B-rep checks (reported as not available, never faked).
references: absolute paths of STEP/STL parts to import first, so a Python design can use self.reference("name.step").

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `source` | string | yes |
| `brief` | string |  |
| `values` | object \| null |  |
| `run` | boolean |  |
| `language` | string |  |
| `references` | array \| null |  |

### `update_design`

Replace a design's code as a new revision (history keeps every version). Existing parameter values carry over;
changing a default does not change a saved value, so pass values={...} to change them. New parameters start at
their defaults. Use preview_change/commit_change instead when only values change. language defaults to the
project's current one ("python" or "openscad").

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `source` | string | yes |
| `note` | string |  |
| `values` | object \| null |  |
| `expect_head` | integer \| null |  |
| `run` | boolean |  |
| `language` | string \| null |  |

### `get_design_source`

*Read-only.*

The exact code a revision was built from (built-in recipes return their recipe file).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `rev` | integer \| null |  |

### `create_project`

Create a project from a built-in recipe (form_overview lists them: gridfinity_bin, storage_box, pegboard, device_stand, ...).
For anything else, write a design: design_guide, then create_design. values override recipe defaults (all start as 'assumed').
With run=True the solid, exports and checks are built (and sliced if a slicer is available).

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `recipe` | string | yes |
| `brief` | string |  |
| `values` | object \| null |  |
| `run` | boolean |  |

### `get_project`

*Read-only.*

Current revision with every parameter and its provenance, output status (current/stale/failed/missing),
checks, fit model, next best actions, simulated slice, file paths, release gate and bench link.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `preview_change`

*Read-only.*

Build a candidate change for real and report what it would touch, without saving anything:
changed features, interface dimensions, stability, fit yield, which outputs it would invalidate.
Invalid candidates come back as an error naming the feature, parameters and a fix.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `values` | object | yes |

### `commit_change`

Save a change as a new revision (history is never rewritten). Pass expect_head from get_project/preview_change
so a concurrent edit is refused instead of overwritten.
provenance: {param: {"source": "measured"|"specified"|"calibrated"|"assumed", "sigma": mm, "instrument": str, "note": str}}.
Use "measured" only for numbers the user measured and gave you. With run=True outputs are regenerated.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `values` | object | yes |
| `note` | string |  |
| `expect_head` | integer \| null |  |
| `provenance` | object \| null |  |
| `run` | boolean |  |

### `run_pipeline`

Regenerate whatever is not current: solid -> STEP+STL -> checks -> slice. Cached outputs are reused unless
force=True. Returns when done or after wait_s; then poll get_job.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `force` | boolean |  |
| `wait_s` | number |  |

### `get_job`

*Read-only.*

Status of a pipeline job started by run_pipeline/commit_change; waits up to wait_s for it to finish.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `job` | string | yes |
| `wait_s` | number |  |

### `render`

*Read-only.*

Look at the part. Returns a PNG rendered from the real kernel geometry, coloured by feature.
view: iso, iso_back, front, back, left, right, top, bottom, or "sheet" (four views at once).
highlight: a feature id to pick out. values: render an uncommitted candidate (same as preview_change).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `view` | string |  |
| `highlight` | string \| null |  |
| `rev` | integer \| null |  |
| `values` | object \| null |  |

### `animate`

*Read-only.*

Make motion from real geometry. kind="turntable" spins the head revision. kind="morph" builds every in-between
design from from_rev (default: head) to to_rev or to_values, so you can show how a change transforms the part.
Returns the file path and a still. fmt: gif or webp.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `kind` | string |  |
| `from_rev` | integer \| null |  |
| `to_rev` | integer \| null |  |
| `to_values` | object \| null |  |
| `frames` | integer |  |
| `fmt` | string |  |

### `compare_revisions`

*Read-only.*

What changed between two revisions: parameters, features, interfaces, stability, fit.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `a` | integer | yes |
| `b` | integer | yes |

### `checkout_revision`

Make an earlier revision the head again (nothing is deleted). Outputs for it are reused if still cached.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `rev` | integer | yes |

### `set_print_setup`

Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from
suggest_orientation), the acceptable total fit gap
window, and whether the pipeline slices automatically. The checks include an orientation comparison table.
design_only=True: the design is not sliced (checks, exports and release still work; the release says it was
not sliced). material: PLA, PETG, ABS, ASA, TPU, PA, PC, ... for the whole design ("" clears): the slice uses the
printer's filament preset for it and the checks add notes for that material. Ask the user before changing either.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `orientation` | string \| null |  |
| `fit_gap_min_mm` | number \| null |  |
| `fit_gap_max_mm` | number \| null |  |
| `auto_slice` | boolean \| null |  |
| `design_only` | boolean \| null |  |
| `material` | string \| null |  |

### `explore_alternatives`

*Read-only.*

Build a small grid of real variants (1-2 parameters, up to 5 values each) and rank them.
axes: [{"key": "depth", "values": [78, 85, 92]}]. weights over objectives: material, stability, fit, footprint.
Nothing is saved; commit the one you choose.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `axes` | array | yes |
| `weights` | object \| null |  |

### `optimize`

*Read-only.*

Goal seek: search parameter ranges for the best design that meets constraints. Every candidate is built by the kernel.
vary: [{"key": "arm_t", "min": 4, "max": 20}] (1-4 parameters).
objective: {"minimize": "solid_mass_g"} or {"maximize": "statics.safety_factor"}.
constraints: ["statics.safety_factor >= 3", "overhang_mm2 <= 1", "derived.usable_depth >= 30", "fit_yield >= 0.9"].
Metrics: volume_cm3, solid_mass_g, width, depth, height, overhang_mm2, contact_mm2, min_wall_mm, fit_yield,
derived.<key>, statics.<key>. Nothing is saved: preview_change/render the best, then commit_change.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `vary` | array | yes |
| `objective` | object | yes |
| `constraints` | array \| null |  |
| `budget` | integer |  |

### `slice_test_piece`

Cut a thin ring through the fit interface of this revision and slice it, so a cheap test print can check the fit
before the whole part. Returns its STL path and simulated time and material.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `record_physical_result`

Record what the USER observed after a real print. Never call this with values the user did not report.
kind="fit": result is too_tight | good | too_loose for this revision.
kind="widths": measured pairs [{"nominal": mm, "measured": mm}] from a coupon (source="coupon") or this part
(source="part"); they calibrate this printer profile for every future design.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `kind` | string | yes |
| `result` | string \| null |  |
| `widths` | array \| null |  |
| `source` | string |  |
| `note` | string |  |

### `request_release`

*Read-only.*

Check whether the head revision can be released and hand the decision to the user.
Agents cannot approve: approval happens in Form Studio, where the user reviews checks and acknowledges warnings.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `open_browser` | boolean |  |

### `verify_release`

*Read-only.*

Re-hash every file of a release against its manifest and say whether it still matches the head revision.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `release` | string | yes |

### `open_in`

Open a current output in the user's own software: what = step | stl | 3mf | gcode | folder.
app overrides studio.toml [apps] (e.g. "BambuStudio"); app="freecad" finds FreeCAD. Uses the system's open command;
nothing is uploaded.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `what` | string |  |
| `app` | string |  |

### `open_bench`

The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases.

| Argument | Type | Required |
|---|---|---|
| `project` | string \| null |  |
| `open_browser` | boolean |  |

### `brief_presets`

*Read-only.*

Brief templates for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure,
car accessory): the questions worth asking, environment defaults (temperature, humidity, UV, load), a material to
start from and the checks to plan for. Defaults are assumptions to confirm with the user, never measurements.

| Argument | Type | Required |
|---|---|---|
| `preset` | string |  |

### `import_reference`

Import an existing part (STEP or STL, e.g. a Raspberry Pi 5 STEP from the manufacturer) into a project's
references. FORM copies it, measures it in the kernel (bounding box, volume: computed) and draws it in the 3D
view as a blueprint companion, in its own coordinates. A Python design can then read it with
self.reference("<name>") for clearance cuts. path: absolute local path. Re-importing a name replaces it.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `path` | string | yes |
| `name` | string \| null |  |

### `freecad_macro`

*Read-only.*

Write a FreeCAD macro (.FCMacro) next to the current STEP export. Run it in FreeCAD to rebuild the part
from the STEP (hash-checked) with a spreadsheet of FORM's parameters and their provenance. Not for mesh designs.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `analyze`

*Read-only.*

An analysis map of the part, computed from the real geometry: a picture with its legend, and the statistics.
map: thickness (opposing-wall distance by ray, the same ray as the Thinnest-wall check; colours follow the nozzle),
overhang (angle past vertical in the print orientation; plate contact and bridged ceilings are separate classes),
section (area of each layer's slice by height, with the weakest neck: computed geometry, NOT a strength analysis),
features (walls and gaps under one nozzle width, holes too small to print true).
Every result is `computed` on the stated tessellation and says what it does not tell you; repeat that caveat.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `map` | string |  |
| `view` | string |  |
| `rev` | integer \| null |  |

### `measure`

*Read-only.*

Measure the part. Points are [x, y, z] in millimetres in the design frame.
from_point + to_point: straight-line distance with dX/dY/dZ, and how far each point is from the surface.
at: what is at that point: the nearest face (type, area, tilt to the bed), the nearest edge, and for a hole or
round boss the diameter: exact from the CAD solid, or "fitted" to mesh edges for a mesh design (with its residual).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `from_point` | array \| null |  |
| `to_point` | array \| null |  |
| `at` | array \| null |  |
| `rev` | integer \| null |  |

### `analyze_selection`

*Read-only.*

Analyse a selection on the CAD solid without saving it. items: up to 24 of
{"kind": "point" | "edge" | "face", "at": [x, y, z]} or {"kind": "region", "points": [[x, y, z], ...], "radius": mm}
in design millimetres with each part as printed (the frame measure uses). Per item: feature, face type, area,
normal and tilt to the bed, overhang, local wall thickness along the inward normal, gap in front, curvature radii,
height above the bed; an edge's length, radius and the angle its faces meet at; a region's painted area, overhang
share, features touched and thinnest sampled wall. Returns the numbers and `text`, the same in sentences.
Evidence class: computed.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `items` | array | yes |
| `rev` | integer \| null |  |

### `list_annotations`

*Read-only.*

The selections the person named and kept on this design (annotations): name, note, the revision they were
made on, the picked items and their computed analysis, and `text` describing each. An annotation from an older
revision describes that revision; reanalyse it with analyze_selection(items=...) to see the head.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `annotate`

Keep a selection on the head revision with a name and a note (for example a place you want the person to look
at, or one you changed). items as in analyze_selection. Shown as a pin in Form Studio's viewport and listed in
its Annotations panel.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `items` | array | yes |
| `name` | string |  |
| `note` | string |  |

### `set_appearance`

Colour (#rrggbb) and material of the whole design (part="") or of one part (an assembly part id from
get_project / render). Materials: PLA, PETG, ABS, ASA, TPU, PA (nylon), PC, PLA-CF, PETG-CF, PA-CF. Form Studio draws the
colour, writes it into its 3MF and adds material notes to the checks (heat, sunlight, warping, flexible, fibre-filled);
stored in the same fields set_part_print uses (project material, parts.<id>.material), so the slicer picks the matching filament. Leave an argument out to keep it; clear=True removes both.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `part` | string |  |
| `color` | string \| null |  |
| `material` | string \| null |  |
| `clear` | boolean |  |

### `suggest_orientation`

*Read-only.*

Rank the ways the part can lie on the plate: the six axis orientations plus every flat face on its convex hull.
Returns a picture of the top three as printed and, for each candidate, the numbers behind its score (support
volume, overhang area, plate contact, height, smallest layer cross-section through the structure features) and
each term's contribution. The score formula is in the result. It ranks computed geometry; it does not predict
print success. Apply one with set_print_setup(project, orientation=<id>).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `print_simulation`

*Read-only.*

Look at the sliced print as it would stand at the end of `layer` (1-based; default: finished). Returns a
picture drawn from the slicer's G-code toolpaths, coloured by line type, plus statistics: z, line types in
that layer, whether it has bridges or overhang walls, slicer time elapsed and remaining, and the list of
bridge and overhang layers. only: draw just these line types (e.g. ["Bridge", "Overhang wall"]).
plate: which plate (1-based) when the design was sliced on several (plate_plan). Needs a current slice
(run_pipeline). This is a simulation of the slice, not a print: say so.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `layer` | integer \| null |  |
| `only` | array \| null |  |
| `plate` | integer \| null |  |

### `estimate_cost`

*Read-only.*

Filament, electricity and machine-time cost of the current slice, per plate and for `copies`, plus the same
volume in the other materials the slicer has presets for. Grams and hours are the slicer's simulation; prices
are the user's (saved ones are used when you pass none). Never invent a price: when a cost is null, "needs"
says which number to ask the user for. No currency is assumed.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `price_per_kg` | number \| null |  |
| `kwh_price` | number \| null |  |
| `watts` | number \| null |  |
| `machine_rate_per_h` | number \| null |  |
| `copies` | integer |  |

### `plate_plan`

*Read-only.*

How the design's printed parts go onto plates: each part as it lies on its own (orientation, size, material),
the plates they are packed onto when the design does not fit one plate (or its parts differ in material), parts
too big for the plate, and per plate the slicer's time and filament when it has been sliced. Computed by FORM from
bounding boxes; each plate is sliced on its own. Needs current checks (run_pipeline).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `set_part_print`

Print settings for one printed part of a multi-part design (part ids from plate_plan): orientation (a named
one, a "down:x,y,z" id, or "auto" for the best-ranked way for that part alone), material (PLA, PETG, TPU, ...;
parts in different materials go on different plates, each sliced with its own filament), color ("#rrggbb").
"" clears a setting. Checks and slice go stale; the pipeline runs again.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `part` | string | yes |
| `orientation` | string \| null |  |
| `material` | string \| null |  |
| `color` | string \| null |  |

### `pack_plate`

*Read-only.*

Do `copies` of this design fit on one plate? Bounding-box packing with a gap (default 6 mm) and 90° turns,
on the selected printer's bed. Returns the layout and the most copies this packer can place. Computed by FORM;
the slicer arranges again when it slices, and FORM's export stays one plate.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `copies` | integer |  |
| `spacing_mm` | number \| null |  |

### `render_photo`

A realistic-looking render of the current revision's exported STL, made by Blender headless (if installed).
preset: studio (soft box, light backdrop) | desk (wooden desk) | dark (graphite, rim light).
material: matte (PLA) | petg (gloss) | silk (silk PLA). color: hex, e.g. "#3d6fb6".
layer_lines draws faint lines at the slicer's layer height when a process preset is selected.
fast=True uses EEVEE instead of Cycles. Cached per geometry and settings. This is an illustration with
invented light and material, not a photo of a print: never present it as evidence of anything.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `preset` | string |  |
| `material` | string |  |
| `color` | string |  |
| `fast` | boolean |  |
| `layer_lines` | boolean |  |

### `save_variant`

Save a named variant of the design ("Travel version", "Thick walls"): a complete set of parameter values kept
in the project next to the revisions. values are changes on top of the head (or of rev); leave them out to save
the head (or rev) as it is. The candidate is built before it is saved; saving a name again replaces it. Nothing
is committed: promote a variant in Form Studio or with `form variants promote`.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `name` | string | yes |
| `values` | object \| null |  |
| `rev` | integer \| null |  |
| `note` | string |  |

### `list_variants`

*Read-only.*

The head and every saved variant side by side: size and volume (computed), print time and grams (simulated,
only when the variant is a revision with a current slice), fit yield (modelled), checks, and each variant's
differences from the head.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `share_card`

*Read-only.*

A 1600 x 900 share image of the head revision: the part with dimension lines, its name, size and volume
(computed), print time and grams (simulated; only if the slice is current), checks, the revision and
"Designed with FORM". picture: "model" (kernel geometry) or "photo" (the newest current Blender render, an
illustration). The card states only what FORM knows; it is not evidence of a print.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `picture` | string |  |

### `rename_project`

Change a project's display name (up to 80 characters). The project id stays the same, so links, files and
releases keep working. Returns the project's summary: id, name, recipe, head, revisions, updated, approved_rev.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `name` | string | yes |

### `duplicate_project`

Copy a project with its revisions, variants and built outputs under a new id (from the new name; default
"<old name> copy"). The copy is not approved: approvals and release folders belong to the original and are not
copied. Returns the new project's summary; use its id from then on.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `name` | string \| null |  |

### `delete_project`

Delete a project by moving its whole folder to the trash folder inside the projects folder
(<projects folder>/.trash/<id>-<UTC time>). Nothing is erased, and moving the folder back restores it, but the
project disappears from FORM. Ask the user first and only call this after they said yes to deleting this
project. Returns {ok, id, trash}: tell the user the trash path.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `list_printers`

*Read-only.*

Every printer set up in every installed slicer (the user's own presets and the system printers they enabled),
with slicer, bed size and nozzle, plus the default printer. With `project`: which printer that design uses and
why (its own choice, the default, or the slicer's selection). With `printer` ("<kind>:<printer name>", the id from
this list): the filaments and processes that printer can use.

| Argument | Type | Required |
|---|---|---|
| `project` | string \| null |  |
| `printer` | string \| null |  |

### `choose_printer`

Use a printer for one design (`project`) or as the default for designs without their own choice
(`default=True`, written to studio.toml after a backup). `printer` is an id from list_printers ("bambu:Bambu Lab
A1 mini 0.4 nozzle"); "" with a project clears its choice. Filament and process default to what the slicer would
pick for that printer. Slicing and the bed-size and nozzle checks follow the choice; the slice goes stale.
Ask the user which printer before calling this.

| Argument | Type | Required |
|---|---|---|
| `printer` | string | yes |
| `project` | string \| null |  |
| `filament` | string |  |
| `process` | string |  |
| `default` | boolean |  |

### `ask_user`

*Read-only.*

Ask the person one question and wait for the answer. Use it only when the answer changes the design
and you cannot find it yourself: a measurement that sets a fit or a load, or an intent you cannot tell
apart (which device, which side opens). At most a few questions per task; ask them one at a time.
choices: up to 8 short options shown as buttons (multi_select lets the person pick several);
allow_text lets them type their own answer; why: one line on what the answer changes.
kind="confirm" shows an approval card (choices default to Yes / No) before an action the person
should agree to. Returns {answered, answer, choices, text} or, when nobody answered, {answered: false,
reason, note}: then continue with safe assumptions marked assumed. Outside Form Studio's chat nobody
can answer here and the result tells you to ask in your own interface.

| Argument | Type | Required |
|---|---|---|
| `question` | string | yes |
| `choices` | array \| null |  |
| `multi_select` | boolean |  |
| `allow_text` | boolean |  |
| `why` | string |  |
| `kind` | string |  |

### `ask_measurement`

Ask the person to measure one dimension of the design, and wait. Form Studio shows a measurement card:
the question, where to measure (where, e.g. "across the widest part of the phone, without the case"), the
precision that matters (tolerance_mm), a diagram ({"shape": "box"|"cylinder"|"hole"|"gap"|"thickness",
"axis": "x"|"y"|"z"|"d"}) and optionally a picture: image is an absolute path to a PNG or JPEG (a render, or
the person's photo) with mark = [x0, y0, x1, y1] (0..1) outlining where to measure. The person types the
number and says how they measured it (calipers, ruler, tape, or estimate). The answer becomes a new revision
of the design with provenance measured (calipers sigma 0.05 mm, ruler 0.5, tape 1.0) or, for an estimate,
assumed. One question at a time. Returns {answered, value, unit, method, source, rev}; when nobody answered,
{answered: false, reason, note}. Outside Form Studio's chat it tells you to ask in your own interface.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `param` | string | yes |
| `question` | string | yes |
| `where` | string |  |
| `unit` | string |  |
| `tolerance_mm` | number \| null |  |
| `diagram` | object \| null |  |
| `image` | string \| null |  |
| `mark` | array \| null |  |

### `propose_concepts`

For a new idea: build 2-4 genuinely different concepts as real designs, so the person can pick one.
concepts: [{"title": short name, "rationale": one line on the approach, "source": design code as for
create_design (see design_guide), "language": "python", "values": {...} or null}]. Make them different
structural approaches (how it holds, mounts, opens), not size variants. Each becomes its own project
("<name> · A", "· B", ...). A concept that fails to build comes back in "failed" with its error; the others are
kept. group: an open group's id to add concepts to (at most 6 in a group), e.g. one mixed concept when the
person asks for "the base of A with the hook of C". With run=True each is exported and checked.
Returns the board: {id, name, state, members: [{project, letter, title, rationale, numbers}], failed}.

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `concepts` | array | yes |
| `brief` | string |  |
| `group` | string \| null |  |
| `run` | boolean |  |

### `pick_concept`

The person picked a concept (in words; in the app they pick on the board). The picked project takes the
group's name and records the choice; the other concepts move to the trash (recoverable) unless keep_others.
Then refine the picked design with update_design. Only call this when the person said which one.

| Argument | Type | Required |
|---|---|---|
| `group` | string | yes |
| `project` | string | yes |
| `keep_others` | boolean |  |

### `list_concepts`

*Read-only.*

Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>.

| Argument | Type | Required |
|---|---|---|
| `group` | string |  |

### `suggest_replies`

*Read-only.*

Offer up to 3 short follow-up messages the person might send next (each under 80 characters, written
as the person would say it, e.g. "Make the walls 2 mm"). Form Studio's chat shows them as buttons under
your reply. Call it at most once, at the end of a reply, and only with useful next steps.

| Argument | Type | Required |
|---|---|---|
| `options` | array | yes |

### `list_starters`

*Read-only.*

The starting points Home offers, ranked from what this person designs (their projects' recipes and briefs,
their printer and material, what they pinned or used): {prompts: [{id, text, source, pinned}], briefs: [...]}.
Use them to suggest what to design next; the person edits them in the app or with `form starters`.

### `recipe_library`

*Read-only.*

Search the recipe library: built-in recipes, recipes the person installed ("mine") and the community index
on the project website. section: builtin | mine | community. Installing code is the person's decision and
happens only in the app or with `form recipes install` after they review the source and its SHA-256.

| Argument | Type | Required |
|---|---|---|
| `q` | string |  |
| `section` | string |  |
| `tag` | string |  |

### `export_recipe`

Write an installed ("mine") recipe as one .formrecipe file: its code, meta.json (parameters, author, tags,
the code's SHA-256) and preview.png drawn from a real build at its defaults. Returns {file, bytes, sha256}.
Nothing is uploaded; the person shares the file however they like.

| Argument | Type | Required |
|---|---|---|
| `recipe` | string | yes |
| `path` | string \| null |  |

### `prepare_recipe_submission`

Prepare an installed recipe for the community gallery: the community/recipes/<id>/ folder (written into
`folder` when given), what the gallery's checks would refuse, and the link to GitHub's recipe issue form with
the fields filled in. Never open or post it: give the link to the person, who submits it themselves.

| Argument | Type | Required |
|---|---|---|
| `recipe` | string | yes |
| `folder` | string \| null |  |

### `design_as_recipe`

Turn a design's current code into a recipe whose defaults are the design's values; ranges narrow a
parameter's range ({key: [min, max]}, never wider than the code's own). It is built once and compared with the
design (check.same_volume). Returns the code and its SHA-256 for the person to review; installing it is their
decision, in the app or with `form recipes derive <project> --install --sha256 <hex>`.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `title` | string |  |
| `summary` | string |  |
| `ranges` | object \| null |  |

### `export_project`

Write the project, its conversations and the code its revisions were built from to one .formstudio file
(default: <projects folder>/<project>.formstudio). Returns {file, bytes}. Nothing is uploaded.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `path` | string \| null |  |
| `conversations` | boolean |  |

### `import_project`

Import a .formstudio or .formproj archive (or a conversation .json) from an absolute path. The archive is
checked first; a project or conversation id that already exists gets a new one. Returns the new ids.

| Argument | Type | Required |
|---|---|---|
| `path` | string | yes |

### `export_conversation`

*Read-only.*

A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again).

| Argument | Type | Required |
|---|---|---|
| `conversation` | string | yes |
| `format` | string |  |

## Prompts

### `design_part(goal)`

A guided session: measure first, look at renders, preview before commit, hand the release to the user.
