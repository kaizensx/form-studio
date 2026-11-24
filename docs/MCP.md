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
Form Studio is an AI CAD studio: it designs parts, products and mechanisms as real, editable CAD (a parametric kernel)
and keeps an honest record of what is known. 3D printing is one optional way to make a design; it is off unless the
person turned it on (form_overview: has_printer).

Workflow: form_overview -> create_design from your own code (design_guide; design_brief first for a complex
design), or create_project from a recipe (describe_recipe) -> render (look at it) -> preview_change ->
commit_change, or update_design -> get_project (checks, next actions). Only for a design whose purpose is "print":
run_pipeline (exports, print checks, a slice) -> request_release (a person approves in Form Studio).

Rules:
- Units are mm, degrees, grams. Only change parameters that describe_recipe lists.
- Always preview_change before commit_change; pass expect_head so you never overwrite a newer revision.
- Provenance is evidence. Mark a value "measured" only when the user measured it and told you the number.
  Never invent physical results; record_physical_result is only for what the user reports.
- For a print design: a slice is a simulation, not a print, and fit yield is a model. Say so when you report them.
- You cannot approve a release. request_release returns a link that opens the release in Form Studio for the user.
- Nothing here starts a print or sends files anywhere.
- Every design has a purpose: "print" (for 3D printing) or "model" (just a 3D model: rendering, CAD exchange, CNC,
  laser cutting, moulding). get_project reports it. For a model never ask about a printer, slicer, filament or
  orientation; print checks and slicing do not apply. Pass purpose to create_project/create_design when the person
  says what it is for; otherwise Form Studio uses their default (form_overview: purpose_default).
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
  drawn lengths. STEP/STL/3MF: import_reference. PDF drawings: read_document. Download only files the person gave you.
- A link the person gives (a file, a Printables/MakerWorld/Thingiverse page, a signed download link): fetch_link,
  never a shell. A large mesh: mesh_preflight before analysing it.
- Meshes to make editable or understand: never embed them as the design. design_guide(topic="reference_parts"):
  analyze_reference (and analyze_assembly for several parts) -> plan named features -> build123d with Params ->
  compare_to_reference -> refine until within tolerance (0.1 mm by default for a remodel).
- One request makes one design. Several files of one product are one design with several parts: reconstruct(files=[...])
  for meshes, create_design(relation="part_of") to add a part to the design in front. A second create_design in a
  conversation that has a design says its relation (replaces, part_of, alternative, new). One brief serves the request.
- If the message has a "Purpose:" line, respect it: "just a 3D model" means no slicing and no print talk.
- Complex designs (mechanisms, organic or styled forms, textures, several parts) are staged: design_brief ->
  design_guide(topic=...) and design_examples -> plan_design -> create_design(plan=...) -> look at the sheet and
  section -> critique -> update_design. Analyse like a top engineer and designer before writing code.
```

## Tools at a glance

95 tools. Read-only tools never change a project.

| Tool | Access | What it does |
|---|---|---|
| [`form_overview`](#form_overview) | read-only | Start here. Engine, slicer, printer, available recipes, existing projects and the bench URL. |
| [`setup_status`](#setup_status) | read-only | What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap. |
| [`install_software`](#install_software) | changes | Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude", "slicer.orca". |
| [`describe_recipe`](#describe_recipe) | read-only | Parameters (unit, range, group, the feature each one drives), features and what the recipe checks. |
| [`design_guide`](#design_guide) | read-only | Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter, holder, mechanism...). |
| [`design_brief`](#design_brief) | changes | Stage 1 of a complex design: store the structured brief before any geometry. |
| [`plan_design`](#plan_design) | changes | Stage 2: store the feature plan for a brief (the id design_brief returned, or a project id). |
| [`design_examples`](#design_examples) | read-only | Complete, high-quality example designs (build123d + form.craft) to learn construction from, over 40 of them: mechanical parts (linear slide, shaft coupler, pillow block, cam follower, gearbox), consumer products (mouse, earbud case, bottle and cap, game controller), organic forms (horn, handle), textured parts (knurl, hex relief, woven, fluted), assemblies (hinged case, ratchet wrench, robot head), helmets (full-face, open-face) and enclosures (electronics box with bosses, sliding battery box, handheld shell). |
| [`critique`](#critique) | changes | Stage 5: look closely and measure. |
| [`read_document`](#read_document) | read-only | Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). |
| [`fetch_link`](#fetch_link) | changes | Download what a link the person gave points to, from Form Studio's engine (use this instead of a shell: it works where your sandbox has no network). |
| [`resolve_model_page`](#resolve_model_page) | read-only | What a model link is, without downloading files: site, title, author, licence, pictures and the file list (Printables, Thingiverse with an app token), or why the files cannot be fetched and how the person gets them (MakerWorld, Thingiverse without a token). |
| [`mesh_preflight`](#mesh_preflight) | read-only | Before working on a large mesh (STL, OBJ, 3MF): triangles, vertices, bounds, closed or not, its class (light, medium, heavy, very heavy), estimated seconds for reading and analysing it, and a decimated display proxy for a heavy one. |
| [`create_design`](#create_design) | changes | Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass, built with build123d. |
| [`update_design`](#update_design) | changes | Replace a design's code as a new revision (history keeps every version). |
| [`build_candidates`](#build_candidates) | changes | Build 2-6 versions of a risky design or step at the same time (one kernel worker each), verify and score every one, and keep the best. |
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
| [`geometry_diff`](#geometry_diff) | changes | What changed in the solid between revision a and b (default the head): material added (b minus a) and removed (a minus b), each with its volume in mm³, number of separate regions and bounding box, computed with booleans on the B-rep. |
| [`add_text`](#add_text) | changes | Put raised (or, with sunk, cut-in) lettering on a flat face of a Python design, as a real feature of its source: a new revision whose build adds a stage text_N with Form Studio's bundled font. |
| [`add_feature`](#add_feature) | changes | Add a feature to a Python design as a new revision. |
| [`remove_feature`](#remove_feature) | changes | Remove a feature as a new revision: a standard feature added with add_feature ("boss_1", "hook_1"), or any feature of a FeatureDesign (its method goes; the features before it load from their checkpoints). |
| [`compare_printers`](#compare_printers) | read-only | Slice the head revision's exported model for real on every printer set up in every installed slicer (the selected printers first, up to limit; or only the printer ids given, from list_printers) and return each one's simulated print time, filament grams and cost from the user's prices, with the fastest, least filament and cheapest. |
| [`make_lighter`](#make_lighter) | read-only | Make it lighter: search changes that reduce mass while every check that passes now still passes. |
| [`apply_lighter`](#apply_lighter) | changes | Keep a make_lighter candidate: changes (parameter values) are committed as a new revision; settings ({"infill": percent, "walls": count}) become this design's print settings over the slicer's process. |
| [`replace_part_guide`](#replace_part_guide) | read-only | How to design a replacement for a broken part from the person's photo: find the scale from a reference object in the photo and estimate sizes (assumed), ask_measurement for each fit-critical size (at most three), then create_design with the measured values and strengthen where it broke. |
| [`turntable`](#turntable) | read-only | Render a turntable of the head revision from the kernel's mesh. |
| [`remove_text`](#remove_text) | changes | Remove lettering added with add_text (mark_id like "text_1"; get_design_source shows the block). |
| [`assembly_instructions`](#assembly_instructions) | changes | Assembly instructions as a PDF from the design's assembly declaration: a parts page with computed volumes, then one page per part going on (in the declaration's parent order, at its explode offset, with arrows). |
| [`checkout_revision`](#checkout_revision) | changes | Make an earlier revision the head again (nothing is deleted). |
| [`set_print_setup`](#set_print_setup) | changes | Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from suggest_orientation), the acceptable total fit gap window, and whether the pipeline slices automatically. |
| [`explore_alternatives`](#explore_alternatives) | read-only | Build a small grid of real variants (1-2 parameters, up to 5 values each) and rank them. |
| [`optimize`](#optimize) | read-only | Goal seek: search parameter ranges for the best design that meets constraints. |
| [`slice_test_piece`](#slice_test_piece) | changes | Cut a thin ring through the fit interface of this revision and slice it, so a cheap test print can check the fit before the whole part. |
| [`record_physical_result`](#record_physical_result) | changes | Record what the USER observed after a real print. |
| [`request_release`](#request_release) | read-only | Check whether the head revision can be released and hand the decision to the user. |
| [`verify_release`](#verify_release) | read-only | Re-hash every file of a release against its manifest and say whether it still matches the head revision. |
| [`open_in`](#open_in) | changes | Open a current output in the user's own software: what = step \| stl \| 3mf \| gcode \| folder. |
| [`open_in_slicer`](#open_in_slicer) | changes | Open the design in the user's slicer, sliced with settings chosen for this part on this printer: orientation (the orientation finder's first choice), layer height, walls, top/bottom layers, infill and pattern, supports (only where overhangs need them), brim, seam, filament for the design's material and the speed profile (one of the printer's own process presets). |
| [`open_bench`](#open_bench) | changes | The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases. |
| [`brief_presets`](#brief_presets) | read-only | Intake guidance for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure, car accessory): the questions worth asking the person, environment defaults (temperature, humidity, UV, load), a material to start from and the checks to plan for. |
| [`import_reference`](#import_reference) | changes | Import an existing part (STEP or STL, e.g. a Raspberry Pi 5 STEP from the manufacturer) into a project's references. |
| [`reconstruct`](#reconstruct) | changes | Turn a mesh (STL, OBJ or 3MF) into editable CAD as a new design. |
| [`analyze_reference`](#analyze_reference) | read-only | Read an imported mesh (STL, OBJ, 3MF) like an engineer before modelling it again as clean CAD (design_guide topic "reference_parts"). |
| [`analyze_assembly`](#analyze_assembly) | read-only | How several imported meshes go together and move, measured in the positions they were given. |
| [`compare_to_reference`](#compare_to_reference) | read-only | Compare the design (or one part of its assembly) with an imported mesh, to iterate a remodel until it is within tolerance (default 0.1 mm for a remodel; say which you used). |
| [`reference_residual`](#reference_residual) | read-only | What is left to build in a remodel: the volume difference between the design (or one part) and an imported mesh as a named work list. |
| [`fit_params`](#fit_params) | changes | Tune the design's declared Params so it lies closer to an imported mesh: bounded least squares over those Params only (each inside its own min and max and at most max_change mm from its value), every evaluation a real build. |
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
| [`dismiss_concepts`](#dismiss_concepts) | changes | The person wants none of the concepts picked: close the group without a pick. |
| [`list_concepts`](#list_concepts) | read-only | Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>. |
| [`suggest_replies`](#suggest_replies) | read-only | Offer up to 3 short follow-up messages the person might send next (each under 80 characters, written as the person would say it, e.g. "Make the walls 2 mm"). |
| [`list_starters`](#list_starters) | read-only | Ideas for what this person might design next, ranked from what they already design (the building blocks and kinds of part in their projects, their printer and material, what they pinned or used): {prompts: [{id, text, source, pinned}], briefs: [...]}. |
| [`recipe_library`](#recipe_library) | read-only | Search the recipe library: built-in recipes, recipes the person installed ("mine") and the community index on the project website, to find a building block to start a design from. |
| [`export_recipe`](#export_recipe) | changes | Write an installed ("mine") recipe as one .formrecipe file: its code, meta.json (parameters, author, tags, the code's SHA-256) and preview.png drawn from a real build at its defaults. |
| [`prepare_recipe_submission`](#prepare_recipe_submission) | changes | Prepare an installed recipe for the community gallery: the community/recipes/<id>/ folder (written into `folder` when given), what the gallery's checks would refuse, and the link to GitHub's recipe issue form with the fields filled in. |
| [`design_as_recipe`](#design_as_recipe) | changes | Turn a design's current code into a recipe whose defaults are the design's values; ranges narrow a parameter's range ({key: [min, max]}, never wider than the code's own). |
| [`export_project`](#export_project) | changes | Write the project, its conversations and the code its revisions were built from to one .formstudio file (default: <projects folder>/<project>.formstudio). |
| [`import_project`](#import_project) | changes | Import a .formstudio or .formproj archive (or a conversation .json) from an absolute path. |
| [`export_conversation`](#export_conversation) | read-only | A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again). |
| [`model_mesh`](#model_mesh) | changes | Model a subdivision cage in Blender with declarative ops (never code), e.g. [{"op":"cage_new","primitive":"cube","size":[40,30,20]}, {"op":"name_region","name":"top", "faces":{"normal":[0,0,1],"within_deg":10}}, {"op":"extrude_region","faces":{"region":"top"},"offset":8}]. |
| [`game_asset`](#game_asset) | changes | Make a design a game asset: LOD0-LOD3 at triangle budgets (from subdivision cage levels first; decimated LODs are automatic retopology), UVs (region seams or Smart UV, packed), materials from the design's zones, Cycles-baked base colour, normal, ORM and AO maps (texture_px 1024\|2048\|4096; bake fast\|quality), convex-hull collision per part (collision="coacd" when CoACD is installed), pivot and scale. |

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
holder, mechanism...). topic="core" (default) returns the contract for a design written as code, the rules,
the staged workflow and a complete example that builds; it leads with skeleton first, one validated feature
at a time (a FeatureDesign, 2 retries per feature, then defer). Other topics, for complex designs: surfacing,
mechanisms, organic, texture, aesthetics, dfm (design for printing; not applicable when purpose="model"),
reference_parts (meshes to rebuild as clean editable CAD: analyze, plan, write, compare, refine),
hybrid (a construction route per feature: kernel, subd_cage, sculpt_recon or procedural, and when to model a
cage in Blender with model_mesh), game (purpose "game": budgets, LODs, UVs, bakes, collision and engine
presets, built with game_asset).
They document form.craft, the helper library for lofts, shells, hinges, snaps, gears, organic bodies and
textures. Then design_examples for a close exemplar, and create_design.

| Argument | Type | Required |
|---|---|---|
| `topic` | string |  |
| `purpose` | string \| null |  |

### `design_brief`

Stage 1 of a complex design: store the structured brief before any geometry. goal: what it is and does.
requirements: what it must do. dimensions: {name: {value, unit, source}} where source is measured, specified
(datasheet, standard) or assumed. constraints: limits (bed size, material, process). unknowns: what you could
not settle; list them, never guess them (ask_user / ask_measurement for ones that change fit, load or
safety). style: the design language. project: attach to an existing project instead of a new design.
Returns the brief id, whether it is complex (heuristic), which design_guide topics and exemplars to read, and
the route (prismatic, revolve, skin+features or mechanism) with how its skeleton is built.

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `goal` | string | yes |
| `requirements` | array \| null |  |
| `dimensions` | object \| null |  |
| `constraints` | array \| null |  |
| `unknowns` | array \| null |  |
| `style` | string |  |
| `purpose` | string \| null |  |
| `references` | array \| null |  |
| `project` | string \| null |  |

### `plan_design`

Stage 2: store the feature plan for a brief (the id design_brief returned, or a project id).
features: [{id, label, how, part?, dims?}] in build order; id becomes the Feature id in the code, how names
the construction (e.g. "craft.loft_sections through 9 superellipse sections", "craft.pin_hinge 0.35 mm").
parts: [{id, label, material?}]. key_dimensions: {name: value or {value, unit, why}}. mechanisms: each with its
clearance and motion. textures: each with its tier (B-rep or mesh texture). risks: what could make it fail and
how you will check it. A complex brief needs at least 3 features and named risks. Every craft.x, parts.x and
patterns.x a how names must exist (an unknown one is refused with the closest real names). Several parts
(magnets, a lid, a faceplate, separate parts): parts, clearances ({"faceplate/shell": 0.3}, mm per side) and
magnets ([{stock: "8x3", count, retention: press|glue|printed}]) are required.
Returns the plan as ordered steps: the skeleton first (create_design with that feature only), then one
add_feature(kind="code") per feature, each with its risk class, a fallback and the retry cap.
Each feature may name its construction route (route: kernel | subd_cage | sculpt_recon | procedural); without
one it is read from the feature's words (heuristic, said so). feature_routes gives each with the words that
chose it; a mechanical interface on a mesh-only route is warned about; mesh routes point at model_mesh.
product_class: what critique compares the silhouette with (helmet_fullface, helmet_open, mouse, bottle);
empty: detected from the brief's words, or none. The design faces +X with Z up for the comparison.
Then create_design(..., plan=<brief id>).

| Argument | Type | Required |
|---|---|---|
| `brief` | string | yes |
| `features` | array | yes |
| `parts` | array \| null |  |
| `key_dimensions` | object \| null |  |
| `mechanisms` | array \| null |  |
| `textures` | array \| null |  |
| `risks` | array \| null |  |
| `approach` | string |  |
| `references_used` | array \| null |  |
| `product_class` | string |  |
| `clearances` | object \| null |  |
| `magnets` | array \| null |  |

### `design_examples`

*Read-only.*

Complete, high-quality example designs (build123d + form.craft) to learn construction from, over 40 of
them: mechanical parts (linear slide, shaft coupler, pillow block, cam follower, gearbox), consumer products
(mouse, earbud case, bottle and cap, game controller), organic forms (horn, handle), textured parts
(knurl, hex relief, woven, fluted), assemblies (hinged case, ratchet wrench, robot head), helmets (full-face,
open-face) and enclosures (electronics box with bosses, sliding battery box, handheld shell).
query: words to search (ranked); name: one exemplar with its full source; technique: just the code block that
does one thing ("hollow a lofted shell", "snap-fit lid", "two-view opening"); category: mechanical, consumer,
organic, textured, assembly, helmet or enclosure. They are references for you, never projects, and never
shown to the person as designs.

| Argument | Type | Required |
|---|---|---|
| `query` | string |  |
| `name` | string |  |
| `technique` | string |  |
| `category` | string |  |

### `critique`

Stage 5: look closely and measure. Returns a close-up render of each feature, computed metrics (smallest
fillet, sharp-edge fraction, symmetry, proportions, surface mix, sliver faces, planned features missing, folds
in lofted skins, wall thickness by rays with break-through spots, silhouette kinks) and a checklist to answer
by looking. When the brief names a product class (helmet_fullface, helmet_open, mouse, bottle; or pass
product_class), the side, front and top silhouettes are compared with the class outline, the proportions
with the class range (with sources) and its signature is checked (an eye port, a neck opening, a palm hump...);
the design must face +X with Z up. Then look at the views and answer "does it read as a <class>?" in
reads_as (what makes it read as one, what gives it away); the checklist keeps asking until you do.
aesthetic: after render_photo from three angles, your 0-5 scores for silhouette, proportion, continuity,
radius_hierarchy, break_up, detail_rhythm, material, would_sell. The rubric caps each by what the geometry and
the appearance() zones support and reports the gate (mean >= 4, none under 3); run it on every request for
something beautiful, at least twice.
All of it is heuristic evidence: numbers to prompt a look, not a verdict. Records one critique pass for the
head revision (with your notes: what you saw, what you will change); a briefed or planned design cannot be
released before its head revision has one.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `notes` | string |  |
| `reads_as` | string |  |
| `product_class` | string |  |
| `aesthetic` | object \| null |  |

### `read_document`

*Read-only.*

Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). PDF pages come
back as images, because a drawing's dimensions are graphics that text extraction loses, plus any text on the page.
pages: "1", "1-3", "2,5" (at most 4). Use this for official dimensions of boards, devices and hardware.

| Argument | Type | Required |
|---|---|---|
| `source` | string | yes |
| `pages` | string |  |

### `fetch_link`

Download what a link the person gave points to, from Form Studio's engine (use this instead of a shell: it
works where your sandbox has no network). A file link (STL, 3MF, OBJ, STEP, PDF, image; also a signed
MakerWorld download link, fetched at once before it expires) is downloaded; a Printables model page has its
part files downloaded with title, author and licence; a Thingiverse or MakerWorld page returns why its files
cannot be fetched and what the person can do; any other page is not read (resolve_model_page reads its title).
In a Form Studio chat the files are attached to the conversation; otherwise they are saved under the data
folder. Each mesh comes with its preflight (triangles, size, closed or not, class). Only fetch links the
person gave you.

| Argument | Type | Required |
|---|---|---|
| `url` | string | yes |
| `conversation` | string |  |

### `resolve_model_page`

*Read-only.*

What a model link is, without downloading files: site, title, author, licence, pictures and the file list
(Printables, Thingiverse with an app token), or why the files cannot be fetched and how the person gets them
(MakerWorld, Thingiverse without a token). Any other page: its OpenGraph title, description and pictures as a
visual reference. Then fetch_link(url) downloads what can be downloaded.

| Argument | Type | Required |
|---|---|---|
| `url` | string | yes |

### `mesh_preflight`

*Read-only.*

Before working on a large mesh (STL, OBJ, 3MF): triangles, vertices, bounds, closed or not, its class
(light, medium, heavy, very heavy), estimated seconds for reading and analysing it, and a decimated display
proxy for a heavy one. The proxy is for display only; analysis and import always use the file itself.
path: absolute local path. Cached by path, size and time, so asking again is instant.

| Argument | Type | Required |
|---|---|---|
| `path` | string | yes |

### `create_design`

Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass,
built with build123d. Form Studio builds it and returns a six-view sheet and a section to look at; with
run=True it also exports STEP and STL and runs the checks (and, for a design whose purpose is "print", the
print checks and a slice). Load errors come back with the line and a hint; fix and call again.
Skeleton first: create the main body, then add one feature per call. partial=True (default): when a later
feature fails, the stages that built before it are saved as a partial revision (flagged, release blocked)
and shown, and the result names the failed feature with its diagnosis; fix it with update_design. partial=False
refuses the whole design instead. Each stage is shown in Form Studio as it builds. A FeatureDesign
(`from form.featureprog import FeatureDesign, feature`; one `@feature("Label")` method per feature,
`def eyes(self, v, body): return body_after`, the first gets body=None) skips a failing feature and goes on,
and keeps a checkpoint per feature, so update_design(feature=, code=) rebuilds only that feature and later ones.
Several parts: declare assembly() (design_guide, ASSEMBLIES): parts with attach=, joints with parent= (chains: a
joint moves everything attached below it), Mate() for pins and threads. A declaration that cannot be used
(unknown part, a loop, two parents) is refused with the reason; the assembly checks then run in their own time
budget and say which joint ranges they reached.
language="openscad": source is an OpenSCAD file; parameters come from Customizer comments (`w = 40; // [20:1:120]`).
OpenSCAD output is a mesh: no STEP, no B-rep checks (reported as not available, never faked).
references: absolute paths of STEP/STL parts to import first, so a Python design can use self.reference("name.step").
purpose: "print" (for 3D printing) or "model" (just a 3D model; not sliced, no print checks). Omitted: the
person's default. process (models only): cnc, laser, injection, casting, sheet_metal, render, cad, other.
plan: the brief id from design_brief/plan_design. A complex brief (a mechanism, an organic or styled form, a
texture, several parts) is refused without one; one brief serves every design of the request.
relation: in Form Studio's chat, when the conversation already has a design in front, say what this code is to
it: "replaces" (a new revision of that design), "part_of" (one more part of that design, e.g. the lid of a
box), "alternative" (a separate design in its family) or "new" (an unrelated design). One request makes one
design: use part_of for the parts of one product. Returns the project, a six-view sheet and a section: look.

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `source` | string | yes |
| `brief` | string |  |
| `values` | object \| null |  |
| `run` | boolean |  |
| `language` | string |  |
| `references` | array \| null |  |
| `purpose` | string \| null |  |
| `process` | string \| null |  |
| `plan` | string |  |
| `relation` | string |  |
| `partial` | boolean |  |

### `update_design`

Replace a design's code as a new revision (history keeps every version). Existing parameter values carry over;
changing a default does not change a saved value, so pass values={...} to change them. New parameters start at
their defaults. Use preview_change/commit_change instead when only values change. language defaults to the
project's current one ("python" or "openscad"). An unusable assembly() declaration is refused with the reason,
and no revision is made. Returns the result with a six-view sheet and a section of the new revision: look.
One feature of a FeatureDesign: feature="eyes", code="def eyes(self, v, body): ..." (no source) replaces that
method only; features before it load from their checkpoints. A feature that fails makes no revision (the head
stays) and returns its diagnosis, unless partial=True, which saves the revision with it left out (release
blocked). result.build_log says per feature whether it was built, loaded from its checkpoint or skipped.
For a briefed design, critique(project) the revision before asking for release.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `source` | string |  |
| `note` | string |  |
| `values` | object \| null |  |
| `expect_head` | integer \| null |  |
| `run` | boolean |  |
| `language` | string \| null |  |
| `feature` | string |  |
| `code` | string |  |
| `partial` | boolean |  |

### `build_candidates`

Build 2-6 versions of a risky design or step at the same time (one kernel worker each), verify and score
every one, and keep the best. candidates: [{label, source}] or, after the first, {label, values} to try other
values on the first one's source. Use it when there are two or three plausible constructions (a loft or a
sweep, one shell or two halves, a thick or a thin wall) instead of trying them one by one.
One risky feature of a FeatureDesign: {label, feature, code} entries are versions of that one method on the
project's head source (project=...) or on a first {label, source}; they share the checkpoints of the
features before it, so only the feature under test is built per version.
Scores (0-100, heuristic, the parts are returned): builds (a valid solid with the declared count; a failure
carries its diagnosis), brief (targets: {"size_mm": [x, y, z], "tolerance_mm": 1, "solids": n,
"derived": {key: value}}), quality (critique metrics; the product class silhouette with product_class),
robust (fewer form.craft fallbacks) and editable (the share of parameters that still build at both ends of
their range). keep="best": create the design `name` from the winner (or a new revision of `project`, with
expect_head); keep="none": only compare. A candidate that fails never sinks the others. Returns the ranking
and, when a design was kept, its six-view sheet: look.

| Argument | Type | Required |
|---|---|---|
| `candidates` | array | yes |
| `name` | string |  |
| `project` | string |  |
| `brief` | string |  |
| `targets` | object \| null |  |
| `product_class` | string |  |
| `keep` | string |  |
| `purpose` | string \| null |  |
| `plan` | string |  |
| `expect_head` | integer \| null |  |
| `sweep` | boolean |  |

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
With run=True the solid, exports and checks are built (and sliced if a slicer is available and it is for printing).
purpose: "print" or "model" (just a 3D model); omitted: the person's default. process: see create_design.

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `recipe` | string | yes |
| `brief` | string |  |
| `values` | object \| null |  |
| `run` | boolean |  |
| `purpose` | string \| null |  |
| `process` | string \| null |  |

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
view: iso, iso_back, front, back, left, right, top, bottom, "sheet" (four views at once), or for a design with
several parts "assembled" (put together) and "exploded" (pulled apart along its explode offsets).
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

### `geometry_diff`

What changed in the solid between revision a and b (default the head): material added (b minus a) and removed
(a minus b), each with its volume in mm³, number of separate regions and bounding box, computed with booleans on
the B-rep. Also writes a picture (added green, removed red, the rest grey); look at it with the returned path.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `a` | integer | yes |
| `b` | integer \| null |  |

### `add_text`

Put raised (or, with sunk, cut-in) lettering on a flat face of a Python design, as a real feature of its source:
a new revision whose build adds a stage text_N with Form Studio's bundled font. at: a point on the face and
normal: its outward normal, both in design millimetres (analyze_selection on a face returns them). height is the
cap height, depth how far the letters stand out or sink in. Returns the new head, the marks and printability
(stroke width against the nozzle, computed on the glyphs). Remove one with remove_text.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `text` | string | yes |
| `at` | array | yes |
| `normal` | array | yes |
| `height` | number |  |
| `depth` | number |  |
| `sunk` | boolean |  |
| `up` | array \| null |  |
| `expect_head` | integer \| null |  |

### `add_feature`

Add a feature to a Python design as a new revision. kind="code" (a FeatureDesign): feature = its id, code = one
method `def <feature>(self, v, body): return body_after`, label/role for the feature list, after = the feature
it goes after (default: last). Only it is built: the features before it load from their checkpoints, and the
stage is shown in Form Studio as it builds. Returns the head, build_log (per feature: built, checkpoint or
skipped, with seconds, solids and volume change) and a six-view sheet and a section: look. A feature that adds
parts says so in the code (`@feature("Lenses", parts=2)`); while parts are still to come the revision is
saved as partial (release blocked). If it fails, no revision is made and the diagnosis comes back
(partial=True saves it left out, release blocked).
Standard features: on a flat face of a Python design, written into its source as a feature block and built
in the kernel as a new revision. kind="boss": a screw boss (size M2..M5; hole tapped = ISO tap drill, clearance =
ISO 273, insert = a typical heat-set insert hole; height, outer_d, hole_d, hole_depth in mm). kind="snap_hook":
a cantilever snap-fit hook (length, thickness, width, lip = undercut, lip_height; up = the lip's direction).
at / normal: a point on the face and its outward normal (analyze_selection gives them). Returns the new head, the
features and check rows: boss wall vs the nozzle; hook strain 1.5·t·y/L² vs allow_strain (a rule of thumb when
not given). Remove one with remove_feature.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `kind` | string | yes |
| `at` | array \| null |  |
| `normal` | array \| null |  |
| `size` | string |  |
| `hole` | string |  |
| `height` | number \| null |  |
| `outer_d` | number \| null |  |
| `hole_d` | number \| null |  |
| `hole_depth` | number \| null |  |
| `length` | number \| null |  |
| `thickness` | number \| null |  |
| `width` | number \| null |  |
| `lip` | number \| null |  |
| `lip_height` | number \| null |  |
| `up` | array \| null |  |
| `allow_strain` | number \| null |  |
| `expect_head` | integer \| null |  |
| `feature` | string |  |
| `code` | string |  |
| `label` | string |  |
| `role` | string |  |
| `after` | string |  |
| `partial` | boolean |  |

### `remove_feature`

Remove a feature as a new revision: a standard feature added with add_feature ("boss_1", "hook_1"), or any
feature of a FeatureDesign (its method goes; the features before it load from their checkpoints).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `feature_id` | string | yes |
| `expect_head` | integer \| null |  |

### `compare_printers`

*Read-only.*

Slice the head revision's exported model for real on every printer set up in every installed slicer (the
selected printers first, up to limit; or only the printer ids given, from list_printers) and return each one's
simulated print time, filament grams and cost from the user's prices, with the fastest, least filament and
cheapest. A printer whose bed is too small is reported without slicing; a failed slice says why. Each slice is a
simulation, not a print. Slices are cached per model and presets.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `limit` | integer |  |
| `printers` | array \| null |  |

### `make_lighter`

*Read-only.*

Make it lighter: search changes that reduce mass while every check that passes now still passes. Tries the
design's wall, thickness and lightening-pocket parameters (never interface parameters; a candidate that moves an
interface dimension is dropped), building a ladder of values in the kernel, then takes the lightest few (builds)
through the real checks and slicer. Also slices lower infill and one wall fewer over the slicer's process. Returns
the baseline and candidates (id, changes and/or settings, computed mass_g, slicer slice_g, every check before and
after) and what was rejected and why. Nothing is committed: keep one with apply_lighter.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `builds` | integer |  |

### `apply_lighter`

Keep a make_lighter candidate: changes (parameter values) are committed as a new revision; settings
({"infill": percent, "walls": count}) become this design's print settings over the slicer's process. Pass the
candidate's own changes and settings exactly. Then run_pipeline.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `changes` | object \| null |  |
| `settings` | object \| null |  |
| `expect_head` | integer \| null |  |

### `replace_part_guide`

*Read-only.*

How to design a replacement for a broken part from the person's photo: find the scale from a reference
object in the photo and estimate sizes (assumed), ask_measurement for each fit-critical size (at most three),
then create_design with the measured values and strengthen where it broke. In Form Studio this flow starts from
Home › Replace a broken part.

### `turntable`

*Read-only.*

Render a turntable of the head revision from the kernel's mesh. fmt: webp or gif (one animated file), png (a
numbered PNG sequence, zipped), mp4 (H.264; needs ffmpeg installed, refused with the reason otherwise). Returns a
still and the file path.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `fmt` | string |  |
| `frames` | integer |  |
| `elevation` | number |  |

### `remove_text`

Remove lettering added with add_text (mark_id like "text_1"; get_design_source shows the block). A new revision.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `mark_id` | string | yes |
| `expect_head` | integer \| null |  |

### `assembly_instructions`

Assembly instructions as a PDF from the design's assembly declaration: a parts page with computed volumes, then
one page per part going on (in the declaration's parent order, at its explode offset, with arrows). Step text is
the part's note, or what the declaration says. Returns the PDF path, page images and the steps. A design without
an assembly() has none.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `rev` | integer \| null |  |

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
purpose: "print" or "model" (just a 3D model, never sliced); process: for a model, how it will be made.
With 3D printing off only purpose="model" and process are accepted.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `orientation` | string \| null |  |
| `fit_gap_min_mm` | number \| null |  |
| `fit_gap_max_mm` | number \| null |  |
| `auto_slice` | boolean \| null |  |
| `design_only` | boolean \| null |  |
| `material` | string \| null |  |
| `purpose` | string \| null |  |
| `process` | string \| null |  |

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

### `open_in_slicer`

Open the design in the user's slicer, sliced with settings chosen for this part on this printer: orientation
(the orientation finder's first choice), layer height, walls, top/bottom layers, infill and pattern, supports
(only where overhangs need them), brim, seam, filament for the design's material and the speed profile (one of
the printer's own process presets). Each decision has a one-line reason labelled "computed" or "heuristic".
It starts from the slicer's own preset and overrides only those keys, slices for real (time and grams are the
slicer's simulation), writes a project 3MF with the plate, the oriented part, the settings and the filament,
checks the settings are in that file, and opens it in the slicer's app. printer: an id from list_printers
(default: the design's printer). open_app=false writes the file without opening it. Nothing is printed or sent.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `printer` | string |  |
| `open_app` | boolean |  |

### `open_bench`

The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases.

| Argument | Type | Required |
|---|---|---|
| `project` | string \| null |  |
| `open_browser` | boolean |  |

### `brief_presets`

*Read-only.*

Intake guidance for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure,
car accessory): the questions worth asking the person, environment defaults (temperature, humidity, UV, load), a
material to start from and the checks to plan for. Use it while gathering requirements; the defaults are
assumptions to confirm with the person, never measurements.

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

### `reconstruct`

Turn a mesh (STL, OBJ or 3MF) into editable CAD as a new design. project_or_file: an absolute path to the
mesh, or a project id whose imported mesh reference to use (reference: which one; default the first mesh).
Several meshes of ONE product (a base, a slider and a lid): pass them all at once, as files=[absolute paths]
(or project_or_file=<project id> with references=[names]); they become ONE design with one part per mesh, in
the positions the files give (parts that fail are listed in "failed", the others are kept). Never call this
once per part: that makes unrelated designs.
Layer 0 is always built: the mesh as an exact solid (Hausdorff at float precision). Layer 1 (beta) replaces
facets with planes, cylinders, cones, spheres and tori where they fit within `tolerance` mm, and smooth
organic regions with fitted B-spline surfaces ("freeform"); the rest stay frozen facets. Layer 2 (beta)
writes a build123d recipe with Params as a feature tree: a base (extrusion stack with steps and pockets, a
revolution, or the reconstructed solid itself) then fillets, chamfers and holes (counterbores, countersinks,
holes on any axis, snapped to standard sizes, patterns); a spur gear becomes a parametric gear (teeth, module,
pressure angle). A feature that does not verify stays in the base and is reported; the recipe is used only
if its rebuild is within the limit. Before any of these, the program route reads the part as sketches
extruded and lofted between levels, and keeps what does not read as a sketch as the mesh's own slices.
Returns the new project and the verification, led by summary.headline: editable_pct (the share of Params
that are real dimensions, lengths, diameters, radii, angles and levels rather than positions of sketch
corners, and that move 0.5 mm with the design still building) and the two-sided Hausdorff distance to
the mesh; then feature_area_pct (the share of the surface parametric features make), the volume delta and
the parametric, freeform and frozen area. Tell the person the editable share first and never call a result
with 0% editable "editable". Values are computed from the mesh; nothing is decimated and every repair is
listed. Large meshes take minutes.

| Argument | Type | Required |
|---|---|---|
| `project_or_file` | string |  |
| `tolerance` | number |  |
| `layer` | integer |  |
| `name` | string \| null |  |
| `reference` | string \| null |  |
| `files` | array \| null |  |
| `references` | array \| null |  |

### `analyze_reference`

*Read-only.*

Read an imported mesh (STL, OBJ, 3MF) like an engineer before modelling it again as clean CAD
(design_guide topic "reference_parts"). Returns pictures of dimensioned sections in the three principal
planes at several levels (look at them), and JSON: principal axes, levels of the flat faces (steps), section
loops with sizes and vector outlines, and features with sizes: holes, bosses, openings (pockets, slots,
cutouts, with count and pitch when repeated), plates, walls, ribs, rails and grooves, ramps with angles,
draft, fillets and chamfers with radii and widths, round edges, detail areas (text, embossing, knurls),
symmetry and wall thicknesses. reference: the mesh's file name in the project (import_reference first).
tolerance (mm): how far a surface may be from the mesh to count as a plane, cylinder... levels: extra section
levels per axis, e.g. {"z": [3.2, 6.5], "y": [-40]}. Evidence: computed on the mesh as given. Never embed
the mesh as the design: plan features from this, write build123d with Params, then compare_to_reference.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `reference` | string | yes |
| `tolerance` | number |  |
| `levels` | object \| null |  |

### `analyze_assembly`

*Read-only.*

How several imported meshes go together and move, measured in the positions they were given. references:
the mesh files (the part that stays still first, or name it in fixed). Returns mating surfaces (facing,
area, gap, where), clearances per pair, each part's travel against the fixed one along +/-X, Y, Z and about
the axes of round faces they share (free distance before touching, distance past bumps such as detents and
flexing arms, the obstacles met and where), the joints this implies (slide axis and range, hinge axis,
origin and range) and couplings between moving parts (a slide meshing with a part that turns: rack and gear
or cam with the ratio; a slide on a leaning face: a ramp with the lift per mm), plus a one-paragraph summary.
Rigid parts: it does not know springs or gravity; say so. near (mm): gaps up to this count as mating.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `references` | array | yes |
| `fixed` | string \| null |  |
| `near` | number |  |

### `compare_to_reference`

*Read-only.*

Compare the design (or one part of its assembly) with an imported mesh, to iterate a remodel until it is
within tolerance (default 0.1 mm for a remodel; say which you used). Returns a picture (the design coloured
by its distance to the mesh, and the mesh by its distance to the design) and JSON: two-sided Hausdorff, mean,
99th percentile, the worst regions by where they are (words and coordinates, the nearest feature of the
reference analysis, and whether the design has extra or missing material there) and per-feature
differences (the design's diameter or radius next to the mesh's). part: a part id or label of the design's
assembly, so a multi-part design is compared part by part. Run analyze_reference first for feature names.
Evidence: computed on the design's tessellation against the mesh.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `reference` | string | yes |
| `part` | string \| null |  |
| `tolerance` | number |  |
| `rev` | integer \| null |  |

### `reference_residual`

*Read-only.*

What is left to build in a remodel: the volume difference between the design (or one part) and an imported
mesh as a named work list. missing: bodies the mesh has and the design lacks (add them); extra: bodies the
design has and the mesh lacks (cut them). Each body has its volume, centre, principal axis, size, shape
(cylinder with diameter and length along an axis, box, or body), where it is in words, and its angle and
radius about an axis, so bodies around a circle read as one polar pattern at equal angles. patterns groups
alike bodies (polar: count, pitch, radius, start angle; linear: pitch and direction; grid: pitches).
work_list: one line per feature to build, patterns first. residual_pct: missing plus extra volume as a share
of the mesh's volume, the number to drive down. axis: "x", "y", "z" (default) or a direction; center: a point
on it (default the mesh's centre of volume). voxel (mm): grid size (default about 1/240 of the part).
Build one item, run this again, keep the change only if residual_pct drops (design_guide topic
"reference_parts"). Evidence: computed (voxels; manifold3d's exact boolean for volumes when installed).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `reference` | string | yes |
| `part` | string \| null |  |
| `rev` | integer \| null |  |
| `voxel` | number \| null |  |
| `axis` | string \| array \| null |  |
| `center` | array \| null |  |

### `fit_params`

Tune the design's declared Params so it lies closer to an imported mesh: bounded least squares over those
Params only (each inside its own min and max and at most max_change mm from its value), every evaluation a
real build. params: which (default every Param in mm, at most 8). The result is kept, as a new revision with
provenance "mesh", only if the mean distance drops and the largest does not grow; otherwise nothing changes
(kept: false), so it never makes the deviation worse. commit=false reports the fitted values without saving.
It cannot add a missing feature: use reference_residual for what is missing or extra, then this for sizes,
then compare_to_reference for the tolerance. budget_s (default 120, 1 to 3600): the whole fit's time; when
it is up the best values found so far are used (stopped says why it ended). Evidence: computed on the
design's tessellation.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `reference` | string | yes |
| `params` | array \| null |  |
| `part` | string \| null |  |
| `max_change` | number |  |
| `commit` | boolean |  |
| `expect_head` | integer \| null |  |
| `max_builds` | integer |  |
| `budget_s` | number |  |

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
material: matte (PLA) | petg (gloss) | silk (silk PLA) | gloss (paint, clear coat) | carbon (carbon twill,
clear coat) | smoke (smoked polycarbonate) | rubber | metal. color: hex, e.g. "#3d6fb6".
view: iso | front | back | left | right | top | three_quarter | three_quarter_back, or azimuth/elevation in
degrees (azimuth from +X toward +Y, as in render: "front" looks from -Y, so a product facing +X shows its face
at azimuth 0). Render a styled product from at least three angles before you judge it.
zones: when the design declares appearance() (material zones: a smoked visor, rubber trim, a carbon shell),
each zone gets its own material; the rest takes material/color.
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
| `view` | string |  |
| `azimuth` | number \| null |  |
| `elevation` | number \| null |  |
| `zones` | boolean |  |

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

### `dismiss_concepts`

The person wants none of the concepts picked: close the group without a pick. keep="all" keeps every
concept as an ordinary design; keep="none" moves them all to the trash (recoverable). Only call this when
the person said so.

| Argument | Type | Required |
|---|---|---|
| `group` | string | yes |
| `keep` | string |  |

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

Ideas for what this person might design next, ranked from what they already design (the building blocks
and kinds of part in their projects, their printer and material, what they pinned or used):
{prompts: [{id, text, source, pinned}], briefs: [...]}. Offer them as suggestions when the person asks what to
make; they edit the list with `form starters`.

### `recipe_library`

*Read-only.*

Search the recipe library: built-in recipes, recipes the person installed ("mine") and the community index
on the project website, to find a building block to start a design from. section: builtin | mine | community.
Installing code is the person's decision and happens only with `form recipes install`, after they review the
source and its SHA-256.

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

### `model_mesh`

Model a subdivision cage in Blender with declarative ops (never code), e.g.
[{"op":"cage_new","primitive":"cube","size":[40,30,20]}, {"op":"name_region","name":"top",
"faces":{"normal":[0,0,1],"within_deg":10}}, {"op":"extrude_region","faces":{"region":"top"},"offset":8}].
Ops: cage_new, extrude_region, loop_cut, move, crease, name_region, mirror, geonodes_array,
geonodes_scatter, sculpt_ops, remesh, and the detail vocabulary bevel, support_loops, inset, panel_line,
trim_strip, solidify, bridge, kit_place (original parametric parts: bolts, rivets, vents, hinges, straps,
buckles, grips, pommels, greebles; a refused call lists them). Any op but cage_new may say high_only: true
(last in the list): it details only the bake source, returned as the cage's `high`, never the LODs.
Each op streams a level-2 preview to the app. Returns the cage (points, quads, creases, named regions) as
design source for update_design; the project is not changed.
Needs Blender 4.2+. Blender is not network-isolated by the OS.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `ops` | array | yes |
| `expect_head` | integer | yes |

### `game_asset`

Make a design a game asset: LOD0-LOD3 at triangle budgets (from subdivision cage levels first; decimated
LODs are automatic retopology), UVs (region seams or Smart UV, packed), materials from the design's zones,
Cycles-baked base colour, normal, ORM and AO maps (texture_px 1024|2048|4096; bake fast|quality), convex-hull
collision per part (collision="coacd" when CoACD is installed), pivot and scale.
preset: gltf | godot (GLB, metres, +Y up) | unity (FBX metres) | unreal (FBX cm, Z up; collision hulls
UCX_<asset>_LOD0_NN, named after the LOD0 render mesh as Unreal pairs them).
formats: extra fbx/usd. action: build | validate (re-check the GLB) | export (list every file).
budgets: four triangle ceilings, LOD0 first (default 12000, 6000, 2500, 800).
materials (cage designs): {region name | "default": {finish, color "#rrggbb", pattern none|wood|noise|brushed}}.
Reads the project, never changes it. Every check is computed from the written GLB. Needs Blender 4.2+.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `action` | string |  |
| `preset` | string |  |
| `budgets` | array \| null |  |
| `texture_px` | integer |  |
| `bake` | string |  |
| `pivot` | string |  |
| `uv` | string |  |
| `collision` | string |  |
| `retopo` | string |  |
| `formats` | array \| null |  |
| `materials` | object \| null |  |

## Prompts

### `design_part(goal)`

A guided session: measure first, look at renders, preview before commit, hand the release to the user.
