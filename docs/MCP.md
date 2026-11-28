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
Form Studio is an AI CAD studio: it designs parts, products and mechanisms as real, editable CAD and keeps an honest
record of what is known. 3D printing is optional: off unless form_overview says has_printer.

Workflow: form_overview -> create_design from your own code (design_guide), or create_project from a recipe
(describe_recipe) -> render -> preview_change -> commit_change, or edit_design (ops on one feature or parameter;
update_design: a whole file) -> get_project (checks, the brief's proof sheet, next actions). Only for purpose "print":
run_pipeline (exports, print checks, a slice) -> request_release. After a build, background refinement lands as one
more revision (refine_design shows, undoes or turns it off). Long work answers with a job: get_job.

Rules:
- Units are mm, degrees, grams. Only change parameters that describe_recipe lists.
- preview_change before commit_change; pass expect_head so a newer revision is never overwritten.
- Provenance is evidence. Mark a value "measured" only when the user measured it and told you the number. Never invent
  physical results: record_physical_result is only for what the user reports.
- Printing: a slice is a simulation, not a print, and fit yield is a model. Say so.
- You cannot approve a release: request_release returns a link the user opens in Form Studio. Nothing here starts a
  print or sends files anywhere.
- Every design has a purpose, "print" or "model" (just a 3D model): get_project reports it. For a model never ask about
  a printer, slicer, filament or orientation. Pass purpose to create_project/create_design when the person says it. A
  "Purpose:" line in the message is binding.
- Ask the person only what changes fit, load or safety and you cannot look up: ask_user, one question at a time, at
  most three a task; ask_measurement for a dimension. If the person cannot be reached, the result says to ask in your
  own interface.
- A new idea that is not a precise specification: propose_concepts with 3-4 structurally different real designs, one
  line of rationale each; then stop: the person picks. Do not offer recipes.
- Anything the person brings (mesh, STEP, photo, sketch, PDF, link, words): triage(source) first. It classes the input,
  chooses the route and names the calls in order. Take that route. Ask the person only when triage returns "ask", and
  say what "cannot" lists.
- A mesh to make editable: reconstruct(path). It triages, repairs what is safe and takes the route (a mechanical part:
  sketches, holes and fillets verified against the mesh; a sculpt or scan: a surface or mesh body,
  design_guide(topic="organic"); several bodies: one design, a part each). Report its headline as it is: the measured
  distance, and what it is not.
- A refusal's hint names the next call. Never repeat a failed call with the same arguments. A design's exceptions are
  not a way to print: what a build says comes back in the result.
- Rebuilding a mechanical mesh by hand: never embed the mesh as the design. design_guide(topic="reference_parts"):
  analyze_reference (analyze_assembly for several parts) -> named features -> build123d with Params ->
  compare_to_reference until within tolerance (default 0.1 mm).
- Photos: scale from a reference object (bank card 85.60 x 53.98 mm, coin, ruler); photo dimensions stay assumed until
  measured. A Form Studio sketch's JSON overrides the picture. STEP: import_reference. PDF drawings: read_document.
  Their links: fetch_link, never a shell. Download only what they gave.
- One request makes one design. Several files of one product: one design, several parts (reconstruct files=[...],
  create_design relation="part_of"). A second create_design in a conversation says its relation: replaces, part_of,
  alternative or new.
- "Will it hold?": strength_study with supports and loads on picked faces and a material, then get_strength_study
  (design_guide(topic="strength")). Quote its evidence class and the lower safety factor. A study that did not converge
  has no safety factor; stress at a singularity it names is never the part's stress. Stale after any change: run again.
- Complex designs (mechanisms, organic or styled forms, textures, several parts) are staged: design_brief ->
  design_guide(topic=...), design_examples -> plan_design -> create_design(plan=...) -> look at the sheet -> critique
  -> update_design. The design_guide topics and this server's skills hold each workflow.
```

## Skills

Form Studio's design and engineering practice is also served as MCP skills (the `io.modelcontextprotocol/skills`
extension, MCP 2026-07-28): `skills/list` names each skill with a digest of every file it holds, and the files are
read with `resources/read` at `skill://<name>/SKILL.md`. Claude Code lists them as `form:<skill>`. Skills are not
available in headless runs (`claude -p`, the Agent SDK) or to clients without the extension, so the same guidance
stays reachable through the `design_guide` tool.

This build of the server offers the extensions `io.modelcontextprotocol/skills`, `io.modelcontextprotocol/tasks`.

## Questions to the person

A tool that needs the person asks, in this order: Form Studio's own chat (when the agent runs inside it); the
client's own form, when the client declared MCP elicitation (form mode); otherwise the result says so, as before.
Through the client's form:

| Tool | The form asks | Declined or dismissed |
|---|---|---|
| `ask_user` | the question, its choices (one, or several with `multi_select`) and a free answer | `{answered: false, reason}` |
| `ask_measurement` | the value (within the parameter's range), how it was got (calipers, ruler, datasheet), or skip | `{answered: false, reason}`, nothing committed |
| `delete_project` | to confirm, with the trash path | `{ok: false, refused}`, nothing moved |
| `install_software` | to install, with the commands and the licence (always for a non-commercial licence) | `{installed: false, refused}` |
| `fetch_link` | to download, for more than 100 MB | `{fetched: false, refused}` |

On MCP 2026-07-28 the tool answers with an `InputRequiredResult` holding one `elicitation/create` and a sealed
`requestState`, and the client calls it again with `inputResponses`; an answer without that state is not taken.
Earlier protocol versions get `elicitation/create` on the session. A client without elicitation, and
`install_software(confirm=True)` for a licence that needs no acceptance, work exactly as before.

## Tool search

Claude Code can defer MCP tools and find them with its ToolSearch tool. These tools carry
`_meta["anthropic/alwaysLoad"]: true` and are always loaded: `form_overview`, `get_project`, `create_design`, `update_design`, `render`, `preview_change`, `commit_change`, `design_guide`, `design_brief`, `ask_user`, `get_job`, `edit_design`, `triage`. Every tool's description opens with what it
does (a verb and its object), so a search finds it; descriptions and the instructions above stay within the 4,096
characters Claude Code reads. Form Studio's own chat runs Claude Code with `ENABLE_TOOL_SEARCH=auto` and ToolSearch
in its tools; `[chat] tool_search = "false"` in studio.toml (or `FORM_TOOL_SEARCH=false`) loads every tool up front
instead.

## Tools at a glance

109 tools. Read-only tools never change a project.

| Tool | Access | What it does |
|---|---|---|
| [`form_overview`](#form_overview) | read-only | Get an overview of Form Studio: engine, slicer, printer, available recipes, existing projects and the bench URL. |
| [`setup_status`](#setup_status) | read-only | Check this machine's setup. What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap. |
| [`install_software`](#install_software) | changes | Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude", "slicer.orca". |
| [`describe_recipe`](#describe_recipe) | read-only | Describe a recipe's parameters. |
| [`design_guide`](#design_guide) | read-only | Read the design guide for code designs. |
| [`design_brief`](#design_brief) | changes | Write a design brief. Stage 1 of a complex design: store the structured brief before any geometry. |
| [`plan_design`](#plan_design) | changes | Plan a design's features. Stage 2: store the feature plan for a brief (the id design_brief returned, or a project id). |
| [`design_examples`](#design_examples) | read-only | Search example designs and their code. |
| [`critique`](#critique) | changes | Critique a design with close-ups and metrics. |
| [`read_document`](#read_document) | read-only | Read a document such as a datasheet or drawing. |
| [`fetch_link`](#fetch_link) | changes | Download what a link the person gave points to, from Form Studio's engine (use this instead of a shell: it works where your sandbox has no network). |
| [`resolve_model_page`](#resolve_model_page) | read-only | Resolve a model page link. What a model link is, without downloading files: site, title, author, licence, pictures and the file list (Printables, Thingiverse with an app token), or why the files cannot be fetched and how the person gets them (MakerWorld, Thingiverse without a token). |
| [`triage`](#triage) | read-only | Assess anything the person brings and choose the route: call this first for a file, a link or a request in words. |
| [`mesh_preflight`](#mesh_preflight) | read-only | Preflight a mesh file. Before working on a large mesh or scan (any format triage reads): triangles, vertices, bounds, closed or not, its class (light, medium, heavy, very heavy), estimated seconds for reading and analysing it, and a decimated display proxy for a heavy one. |
| [`create_design`](#create_design) | changes | Create a project from your own design code (see design_guide): one Python file defining one Recipe subclass, built with build123d. |
| [`update_design`](#update_design) | changes | Replace a design's code as a new revision (history keeps every version). |
| [`edit_design`](#edit_design) | changes | Edit a design's code by naming what changes: one build, one revision. |
| [`build_candidates`](#build_candidates) | changes | Build 2-6 versions of a risky design or step at the same time (one kernel worker each), verify and score every one, and keep the best. |
| [`refine_design`](#refine_design) | changes | Show, rerun, undo or turn off design refinement of a project. |
| [`get_design_source`](#get_design_source) | read-only | Get a design's source code: the code a revision was built from (built-in recipes return their recipe file). |
| [`create_project`](#create_project) | changes | Create a project from a built-in recipe (form_overview lists them: gridfinity_bin, storage_box, pegboard, device_stand, ...). |
| [`get_project`](#get_project) | read-only | Get a project's state: current revision with every parameter and its provenance, output status (current/stale/failed/missing), checks, fit model, next best actions, simulated slice, file paths, release gate and bench link. |
| [`preview_change`](#preview_change) | read-only | Build a candidate change for real and report what it would touch, without saving anything: changed features, interface dimensions, stability, fit yield, which outputs it would invalidate. |
| [`commit_change`](#commit_change) | changes | Save a change as a new revision (history is never rewritten). |
| [`run_pipeline`](#run_pipeline) | changes | Regenerate whatever is not current: solid -> STEP+STL -> checks -> slice. |
| [`get_job`](#get_job) | read-only | Get a job's status: a pipeline job started by run_pipeline/commit_change; waits up to wait_s for it to finish. |
| [`render`](#render) | read-only | Render the part as an image. Look at the part. |
| [`animate`](#animate) | read-only | Animate a design. Make motion from real geometry. |
| [`compare_revisions`](#compare_revisions) | read-only | Compare two revisions. What changed between two revisions: parameters, features, interfaces, stability, fit. |
| [`geometry_diff`](#geometry_diff) | changes | Diff the geometry of two revisions. |
| [`add_text`](#add_text) | changes | Put raised (or, with sunk, cut-in) lettering on a flat face of a Python design, as a real feature of its source: a new revision whose build adds a stage text_N with Form Studio's bundled font. |
| [`add_feature`](#add_feature) | changes | Add a feature to a Python design as a new revision. |
| [`get_sketch`](#get_sketch) | read-only | Get the sketch of a feature made from one (extrude, cut, revolve): its plane, points, entities (line, circle, arc) and constraints, solved by form.sketch2d: point positions, the profile, degrees of freedom left, and the named dimensions with their values (each is a parameter "<feature>_<name>"). |
| [`edit_sketch`](#edit_sketch) | changes | Edit a feature's sketch with ops (or send the whole sketch), as one revision. |
| [`remove_feature`](#remove_feature) | changes | Remove a feature as a new revision: a standard feature added with add_feature ("boss_1", "hook_1"), or any feature of a FeatureDesign (its method goes; the features before it load from their checkpoints). |
| [`compare_printers`](#compare_printers) | read-only | Slice the head revision's exported model for real on every printer set up in every installed slicer (the selected printers first, up to limit; or only the printer ids given, from list_printers) and return each one's simulated print time, filament grams and cost from the user's prices, with the fastest, least filament and cheapest. |
| [`make_lighter`](#make_lighter) | read-only | Make it lighter: search changes that reduce mass while every check that passes now still passes. |
| [`apply_lighter`](#apply_lighter) | changes | Keep a make_lighter candidate: changes (parameter values) are committed as a new revision; settings ({"infill": percent, "walls": count}) become this design's print settings over the slicer's process. |
| [`replace_part_guide`](#replace_part_guide) | read-only | Guide a replacement part from a photo. |
| [`turntable`](#turntable) | read-only | Render a turntable of the head revision from the kernel's mesh. |
| [`remove_text`](#remove_text) | changes | Remove lettering added with add_text (mark_id like "text_1"; get_design_source shows the block). |
| [`assembly_instructions`](#assembly_instructions) | changes | Write assembly instructions. Assembly instructions as a PDF from the design's assembly declaration: a parts page with computed volumes, then one page per part going on (in the declaration's parent order, at its explode offset, with arrows). |
| [`checkout_revision`](#checkout_revision) | changes | Make an earlier revision the head again (nothing is deleted). |
| [`set_print_setup`](#set_print_setup) | changes | Set the print setup. Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from suggest_orientation), the acceptable total fit gap window, and whether the pipeline slices automatically. |
| [`explore_alternatives`](#explore_alternatives) | read-only | Build a small grid of real variants (1-2 parameters, up to 5 values each) and rank them. |
| [`optimize`](#optimize) | read-only | Optimize a design. Goal seek: search parameter ranges for the best design that meets constraints. |
| [`slice_test_piece`](#slice_test_piece) | changes | Cut a thin ring through the fit interface of this revision and slice it, so a cheap test print can check the fit before the whole part. |
| [`record_physical_result`](#record_physical_result) | changes | Record what the USER observed after a real print. |
| [`request_release`](#request_release) | read-only | Check whether the head revision can be released and hand the decision to the user. |
| [`verify_release`](#verify_release) | read-only | Re-hash every file of a release against its manifest and say whether it still matches the head revision. |
| [`open_in`](#open_in) | changes | Open a current output in the user's own software: what = step \| stl \| 3mf \| gcode \| folder. |
| [`open_in_slicer`](#open_in_slicer) | changes | Open the design in the user's slicer, sliced with settings chosen for this part on this printer: orientation (the orientation finder's first choice), layer height, walls, top/bottom layers, infill and pattern, supports (only where overhangs need them), brim, seam, filament for the design's material and the speed profile (one of the printer's own process presets). |
| [`open_bench`](#open_bench) | changes | Open the bench web page. The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases. |
| [`brief_presets`](#brief_presets) | read-only | List brief presets. Intake guidance for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure, car accessory): the questions worth asking the person, environment defaults (temperature, humidity, UV, load), a material to start from and the checks to plan for. |
| [`import_reference`](#import_reference) | changes | Import an existing part (e.g. a Raspberry Pi 5 STEP from the manufacturer) into a project's references: STEP, IGES, BREP, a mesh (STL, OBJ, 3MF, PLY, OFF, AMF, glTF/GLB, DAE, X3D, VRML, VTK) or a scan (XYZ, PTS, LAS, E57: made a surface first); a zip imports every part in it. |
| [`reconstruct`](#reconstruct) | changes | Turn a mesh or scan into a design, by the route its triage chooses (STL, OBJ, 3MF, PLY, OFF, AMF, glTF/GLB, DAE, X3D, VRML, VTK; XYZ, PTS, LAS, E57 point clouds become a surface first; a zip of meshes: one design, a part each; units of glTF, DAE, AMF, 3MF, LAS and E57 are converted). |
| [`analyze_reference`](#analyze_reference) | read-only | Read an imported mesh or scan like an engineer before modelling it again as clean CAD (design_guide topic "reference_parts"). |
| [`analyze_assembly`](#analyze_assembly) | read-only | Analyze an assembly of meshes. |
| [`compare_to_reference`](#compare_to_reference) | read-only | Compare the design (or one part of its assembly) with an imported mesh, to iterate a remodel until it is within tolerance (default 0.1 mm for a remodel; say which you used). |
| [`reference_residual`](#reference_residual) | read-only | List what remains of a remodel. |
| [`fit_params`](#fit_params) | changes | Tune the design's declared Params so it lies closer to an imported mesh: bounded least squares over those Params only (each inside its own min and max and at most max_change mm from its value), every evaluation a real build. |
| [`freecad_macro`](#freecad_macro) | read-only | Write a FreeCAD macro (.FCMacro) next to the current STEP export. |
| [`analyze`](#analyze) | read-only | Analyze the part as a map. An analysis map of the part, computed from the real geometry: a picture with its legend, and the statistics. |
| [`measure`](#measure) | read-only | Measure distances and features of the part. |
| [`mass_properties`](#mass_properties) | read-only | Mass, centre of mass, inertia tensor and principal axes, computed on the B-rep (OCCT), per part and for the whole. |
| [`analyze_selection`](#analyze_selection) | read-only | Analyse a selection on the CAD solid without saving it. |
| [`list_annotations`](#list_annotations) | read-only | List annotations. The selections the person named and kept on this design (annotations): name, note, the revision they were made on, the picked items and their computed analysis, and `text` describing each. |
| [`annotate`](#annotate) | changes | Keep a selection on the head revision with a name and a note (for example a place you want the person to look at, or one you changed). |
| [`set_appearance`](#set_appearance) | changes | Set the colour and material of a design. |
| [`suggest_orientation`](#suggest_orientation) | read-only | Rank the ways the part can lie on the plate: the six axis orientations plus every flat face on its convex hull. |
| [`print_simulation`](#print_simulation) | read-only | Simulate the print layer by layer. |
| [`estimate_cost`](#estimate_cost) | read-only | Estimate the print cost. Filament, electricity and machine-time cost of the current slice, per plate and for `copies`, plus the same volume in the other materials the slicer has presets for. |
| [`plate_plan`](#plate_plan) | read-only | Plan the plates. How the design's printed parts go onto plates: each part as it lies on its own (orientation, size, material), the plates they are packed onto when the design does not fit one plate (or its parts differ in material), parts too big for the plate (with their size against the bed and what would make them fit), and per plate the slicer's time and filament when it has been sliced. |
| [`set_part_print`](#set_part_print) | changes | Set one part's print settings. |
| [`pack_plate`](#pack_plate) | read-only | Pack copies on a plate. Do `copies` of this design fit on one plate? |
| [`render_photo`](#render_photo) | changes | Render a photo-real image. A realistic-looking render of the current revision's exported STL, made by Blender headless (if installed). |
| [`save_variant`](#save_variant) | changes | Save a named variant of the design ("Travel version", "Thick walls"): a complete set of parameter values kept in the project next to the revisions. |
| [`list_variants`](#list_variants) | read-only | List variants. The head and every saved variant side by side: size and volume (computed), print time and grams (simulated, only when the variant is a revision with a current slice), fit yield (modelled), checks, and each variant's differences from the head. |
| [`share_card`](#share_card) | read-only | Make a share card image. A 1600 x 900 share image of the head revision: the part with dimension lines, its name, size and volume (computed), print time and grams (simulated; only if the slice is current), checks, the revision and "Designed with FORM". |
| [`rename_project`](#rename_project) | changes | Change a project's display name (up to 80 characters). |
| [`duplicate_project`](#duplicate_project) | changes | Copy a project with its revisions, variants and built outputs under a new id (from the new name; default "<old name> copy"). |
| [`delete_project`](#delete_project) | changes | Delete a project by moving its whole folder to the trash folder inside the projects folder (<projects folder>/.trash/<id>-<UTC time>). |
| [`list_printers`](#list_printers) | read-only | List printers. Every printer set up in every installed slicer (the user's own presets and the system printers they enabled), with slicer, bed size and nozzle, plus the default printer. |
| [`choose_printer`](#choose_printer) | changes | Use a printer for one design (`project`) or as the default for designs without their own choice (`default=True`, written to studio.toml after a backup). |
| [`ask_user`](#ask_user) | read-only | Ask the person one question and wait for the answer. |
| [`ask_measurement`](#ask_measurement) | changes | Ask the person to measure one dimension of the design, and wait. |
| [`propose_concepts`](#propose_concepts) | changes | Propose concepts. For a new idea: build 2-4 genuinely different concepts as real designs, so the person can pick one. |
| [`pick_concept`](#pick_concept) | changes | Pick a concept. The person picked a concept (in words; in the app they pick on the board). |
| [`dismiss_concepts`](#dismiss_concepts) | changes | Dismiss concepts. The person wants none of the concepts picked: close the group without a pick. |
| [`list_concepts`](#list_concepts) | read-only | List concepts. Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>. |
| [`suggest_replies`](#suggest_replies) | read-only | Offer up to 3 short follow-up messages the person might send next (each under 80 characters, written as the person would say it, e.g. "Make the walls 2 mm"). |
| [`list_starters`](#list_starters) | read-only | List starter ideas. Ideas for what this person might design next, ranked from what they already design (the building blocks and kinds of part in their projects, their printer and material, what they pinned or used): {prompts: [{id, text, source, pinned}], briefs: [...]}. |
| [`recipe_library`](#recipe_library) | read-only | Search the recipe library: built-in recipes and recipes the person installed ("mine"), to find a building block to start a design from. |
| [`export_recipe`](#export_recipe) | changes | Write an installed ("mine") recipe as one .formrecipe file: its code, meta.json (parameters, author, tags, the code's SHA-256) and preview.png drawn from a real build at its defaults. |
| [`design_as_recipe`](#design_as_recipe) | changes | Turn a design's current code into a recipe whose defaults are the design's values; ranges narrow a parameter's range ({key: [min, max]}, never wider than the code's own). |
| [`export_project`](#export_project) | changes | Write the project, its conversations and the code its revisions were built from to one .formstudio file (default: <projects folder>/<project>.formstudio). |
| [`import_project`](#import_project) | changes | Import a .formstudio or .formproj archive (or a conversation .json) from an absolute path. |
| [`export_conversation`](#export_conversation) | read-only | Export a conversation. A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again). |
| [`model_mesh`](#model_mesh) | changes | Model a subdivision cage in Blender with declarative ops (never code), e.g. [{"op":"cage_new","primitive":"cube","size":[40,30,20]}, {"op":"name_region","name":"top", "faces":{"normal":[0,0,1],"within_deg":10}}, {"op":"extrude_region","faces":{"region":"top"},"offset":8}]. |
| [`game_asset`](#game_asset) | changes | Make a design a game asset: LOD0-LOD3 at triangle budgets (from subdivision cage levels first; decimated LODs are automatic retopology), UVs (region seams or Smart UV, packed), materials from the design's zones, Cycles-baked base colour, normal, ORM and AO maps (texture_px 1024\|2048\|4096; bake fast\|quality), convex-hull collision per part (collision="coacd" when CoACD is installed), pivot and scale. |
| [`list_studies`](#list_studies) | read-only | List every study, route and document of a design with its state: the Bench. |
| [`run_study`](#run_study) | changes | Run one Bench entry for the head revision (ids from list_studies). |
| [`get_study`](#get_study) | read-only | Read one Bench entry: its state, the revision it describes, its headline with evidence, its files and stored numbers, and the log of its runs. |
| [`strength_study`](#strength_study) | changes | Run a strength study on the design: will it hold? |
| [`get_strength_study`](#get_strength_study) | read-only | Read a strength study: its state (never, running with progress, current, stale with the revision the stored result describes, failed with why), and the result. |
| [`calculate`](#calculate) | changes | Size a part from requirements with a standard's equations, and write it as a design. |
| [`print_orient`](#print_orient) | changes | Find the print orientation over several objectives at once. |
| [`print_strength`](#print_strength) | changes | Strength of the part as printed, layer by layer. |
| [`print_warp`](#print_warp) | read-only | Warp risk of the part as printed: an indicator, never a predicted lift in millimetres. |

## Tools

### `form_overview`

*Read-only.*

Get an overview of Form Studio: engine, slicer, printer, available recipes, existing projects and the bench
URL. Start here.

### `setup_status`

*Read-only.*

Check this machine's setup. What FORM can use on this machine (kernel, slicer, printer, agents) and the exact command that fixes each gap.
Never run a fix without asking the user; the simplest path is to ask them to run `form setup` in a terminal.

### `install_software`

Install one thing from FORM's registry (ids come from setup_status → software), e.g. "parts", "claude",
"slicer.orca". Without confirm=True nothing runs: you get the exact commands to show the user. Ask the user
first, then call again with confirm=True. Never asks for a password; sign-in is not an install.
Outside Form Studio's chat, a client with its own forms (MCP elicitation) shows the command and the licence
and asks the person instead (always for a non-commercial licence, even with confirm=True).

| Argument | Type | Required |
|---|---|---|
| `id` | string | yes |
| `confirm` | boolean |  |
| `method` | string \| null |  |

### `describe_recipe`

*Read-only.*

Describe a recipe's parameters. Parameters (unit, range, group, the feature each one drives), features and what the recipe checks.

| Argument | Type | Required |
|---|---|---|
| `recipe` | string | yes |

### `design_guide`

*Read-only.*

Read the design guide for code designs. Read this before designing anything the built-in recipes do not cover (any enclosure, bracket, adapter,
holder, mechanism...). topic="core" (default) returns the contract for a design written as code, the rules,
the staged workflow and a complete example that builds; it leads with skeleton first, one validated feature
at a time (a FeatureDesign, 2 retries per feature, then defer). Other topics, for complex designs: surfacing,
mechanisms, organic, texture, aesthetics, dfm (design for printing; not applicable when purpose="model"),
reference_parts (meshes to rebuild as clean editable CAD: analyze, plan, write, compare, refine),
hybrid (a construction route per feature: kernel, subd_cage, sculpt_recon or procedural, and when to model a
cage in Blender with model_mesh), game (purpose "game": budgets, LODs, UVs, bakes, collision and engine
presets, built with game_asset), strength (strength studies: supports and loads on picked faces, reading
convergence, singularities and the safety factor).
They document form.craft, the helper library for lofts, shells, hinges, snaps, gears, organic bodies and
textures. Then design_examples for a close exemplar, and create_design.

| Argument | Type | Required |
|---|---|---|
| `topic` | string |  |
| `purpose` | string \| null |  |

### `design_brief`

Write a design brief. Stage 1 of a complex design: store the structured brief before any geometry. goal: what it is and does.
requirements: what it must do. dimensions: {name: {value, unit, source}} where source is measured, specified
(datasheet, standard) or assumed. constraints: limits (bed size, material, process). unknowns: what you could
not settle; list them, never guess them (ask_user / ask_measurement for ones that change fit, load or
safety). style: the design language. project: attach to an existing project instead of a new design.
The brief becomes a contract: requirements the kernel can check, each with a tolerance and where it came
from. Numbers in goal, requirements and constraints are read ("4 x Ø5.2 on a 60 mm bolt circle", "2.4 mm
wall", "80 x 60 x 20 mm", "M6 thread", "two-part", "Ø30 bore"); add what words cannot say as assertions:
[{"kind": "bolt_circle", "count": 4, "hole_d": 5.2, "circle_d": 60}] with kind bbox (size [x, y, z]),
volume (mm3, op), part_count (count), face_count (count, of), hole_count (count, d), cylinder (d, of
any|boss|bore), bolt_circle, pattern (count, pitch, hole_d), min_wall (t), thread (major, pitch); each may
carry tol (mm; 0.1 when not given, said to be assumed), axis and feature (the feature that must meet it).
Returns contract.assertions and contract.audit: what is missing, conflicting or impossible in the numbers
themselves (arithmetic, nothing measured). When audit.ask is there, put it to the person once with ask_user
before any code; a brief with conflicting or impossible numbers cannot be planned or built from.
After a build, get_project and every commit return the proof sheet: one row per requirement with what the
kernel measured, the tolerance, the evidence class and PASS, FAIL or UNPROVEN.
Also returns the brief id, whether it is complex (heuristic), which design_guide topics and exemplars to
read, and the route (prismatic, revolve, skin+features or mechanism) with how its skeleton is built.

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
| `assertions` | array \| null |  |

### `plan_design`

Plan a design's features. Stage 2: store the feature plan for a brief (the id design_brief returned, or a project id).
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

Search example designs and their code. Complete, high-quality example designs (build123d + form.craft) to learn construction from, over 40 of
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

Critique a design with close-ups and metrics. Stage 5: look closely and measure. Returns a close-up render of each feature, computed metrics (smallest
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

Read a document such as a datasheet or drawing. Look at a datasheet or mechanical drawing: an https URL or a local file (PDF, PNG, JPEG, WebP). PDF pages come
back as images, because a drawing's dimensions are graphics that text extraction loses, plus any text on the page.
pages: "1", "1-3", "2,5" (at most 4). Use this for official dimensions of boards, devices and hardware.

| Argument | Type | Required |
|---|---|---|
| `source` | string | yes |
| `pages` | string |  |

### `fetch_link`

Download what a link the person gave points to, from Form Studio's engine (use this instead of a shell: it
works where your sandbox has no network). A file link (any part, mesh, scan, drawing or zip triage reads, a PDF or
an image; also a signed
MakerWorld download link, fetched at once before it expires) is downloaded; a Printables model page has its
part files downloaded with title, author and licence; a Thingiverse or MakerWorld page returns why its files
cannot be fetched and what the person can do; any other page is not read (resolve_model_page reads its title).
In a Form Studio chat the files are attached to the conversation; otherwise they are saved under the data
folder. Each mesh comes with its preflight (triangles, size, closed or not, class). Only fetch links the
person gave you. Outside Form Studio's chat, a client with its own forms (MCP elicitation) asks the person
before a download over 100 MB; declined: {fetched: false, refused}.

| Argument | Type | Required |
|---|---|---|
| `url` | string | yes |
| `conversation` | string |  |

### `resolve_model_page`

*Read-only.*

Resolve a model page link. What a model link is, without downloading files: site, title, author, licence, pictures and the file list
(Printables, Thingiverse with an app token), or why the files cannot be fetched and how the person gets them
(MakerWorld, Thingiverse without a token). Any other page: its OpenGraph title, description and pictures as a
visual reference. Then fetch_link(url) downloads what can be downloaded.

| Argument | Type | Required |
|---|---|---|
| `url` | string | yes |

### `triage`

*Read-only.*

Assess anything the person brings and choose the route: call this first for a file, a link or a request
in words. source: an absolute file path, a link, or the person's words. Files: meshes (STL, OBJ, 3MF, PLY, OFF,
AMF, glTF/GLB, Collada DAE, X3D, VRML, VTK/VTP/VTU), scans (XYZ, PTS, LAS, E57, a PLY of vertices: a surface is
made from the points first, facts.surface_from_points), CAD (STEP, IGES, BREP), drawings (DXF, SVG: route
profile), a zip of these (route archive: unpacked safely, each file with its own route and path), a photo, a
PDF, a sketch; anything else gets one message naming what is read. For a mesh it reads the file, repairs a copy and measures it: triangles, size, a guess at
the units, open and non-manifold edges before and after the safe repairs, bodies, genus, and the share of the
surface that is flat or ruled (what CAD makes) against sculpted. It returns the class (mechanical, organic,
mixed), the route (parametric, surface_body, mesh_body, assembly, reference_only; cad_reference, profile,
archive, photo_reference, sketch, document, link, describe, concepts), why, the calls to make in order ("steps"),
what will be prepared first (repair, working_copy), "cannot" (what this route will not give: say it), and
"ask": one question, present only when the answer changes the result and is not in the file. Take the route
without asking the person to choose it. reconstruct runs this itself; call triage alone to explain or to
decide before a larger plan. Reads only; nothing is changed, moved or sent.

| Argument | Type | Required |
|---|---|---|
| `source` | string | yes |
| `intent` | string |  |
| `tolerance` | number |  |

### `mesh_preflight`

*Read-only.*

Preflight a mesh file. Before working on a large mesh or scan (any format triage reads): triangles, vertices, bounds, closed or not, its class
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
references: absolute paths of parts to import first (STEP, IGES, BREP, any mesh or scan triage reads), so a
Python design can use self.reference("name.step").
purpose: "print" (for 3D printing) or "model" (just a 3D model; not sliced, no print checks). Omitted: the
person's default. process (models only): cnc, laser, injection, casting, sheet_metal, render, cad, other.
plan: the brief id from design_brief/plan_design. A complex brief (a mechanism, an organic or styled form, a
texture, several parts) is refused without one; one brief serves every design of the request.
relation: in Form Studio's chat, when the conversation already has a design in front, say what this code is to
it: "replaces" (a new revision of that design), "part_of" (one more part of that design, e.g. the lid of a
box), "alternative" (a separate design in its family) or "new" (an unrelated design). One request makes one
design: use part_of for the parts of one product.
refine: "auto" (default): after the build, design refinement runs in the background and lands as one more
revision, "Refined: N changes", each change a named refine feature you can undo (refine_design); "off": not
for this design; "on": also for a game asset, which is not refined unless asked.
preflight: before the kernel is asked for anything, the source is checked without it and every problem comes
back at once (a constraint its own values violate, a name or keyword build123d and form.craft do not have,
a parameter that is read but not declared, a Polygon wound clockwise and extruded upward, a thread pair
that does not engage); "block" (default) refuses on errors, "warn" builds anyway, "off" skips it.
Returns the project (with the proof sheet when the brief has a contract), a six-view sheet and a section: look.

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
| `refine` | string |  |
| `preflight` | string |  |

### `update_design`

Replace a design's code as a new revision (history keeps every version). To change one feature, a helper or
a parameter, use edit_design: it sends only what changes. Existing parameter values carry over;
changing a default does not change a saved value, so pass values={...} to change them. New parameters start at
their defaults. Use preview_change/commit_change instead when only values change. language defaults to the
project's current one ("python" or "openscad"). An unusable assembly() declaration is refused with the reason,
and no revision is made. Returns the result with a six-view sheet and a section of the new revision: look.
One feature of a FeatureDesign: feature="eyes", code="def eyes(self, v, body): ..." (no source) replaces that
method only; features before it load from their checkpoints. A feature that fails makes no revision (the head
stays) and returns its diagnosis, unless partial=True, which saves the revision with it left out (release
blocked). result.build_log says per feature whether it was built, loaded from its checkpoint or skipped.
preflight: as create_design (an update is refused only for errors this source introduces).
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
| `preflight` | string |  |

### `edit_design`

Edit a design's code by naming what changes: one build, one revision. Send ops, not the file.
ops, applied in order, all checked before any is applied (every problem comes back at once):
{"op": "replace", "feature": "holes", "code": "def holes(self, v, body): ..."}  one feature method;
{"op": "replace", "def": "poly", "code": "def poly(pts, L): ..."}  a helper or another method (constraints,
derived, setup); {"op": "replace", "find": "exact text", "with": "new text"}  text found exactly once;
{"op": "insert", "feature": "ribs", "code": "...", "after": "body", "label": "Ribs", "role": "structure"};
{"op": "insert", "def": "ring", "code": "def ring(r): ..."}; {"op": "insert", "param": {"key": "rib_t",
"label": "Rib thickness", "default": 2, "min": 1, "max": 4}}; {"op": "delete", "feature" | "def" | "param": name};
{"op": "set_param", "param": "wall", "value": 2.4}  this revision's value; with default, min, max, step,
label or doc it changes the declaration too (a new default is also the value).
The feature tree: {"op": "suppress" | "restore", "feature": "ribs"} (kept in the source, not built);
{"op": "move", "feature": "ribs", "after" | "before": "body"} (refused when a feature would come before one it
reads); {"op": "rename", "feature": "ribs", "label": "Stiffeners", "id": "stiffeners"} (a new id is carried
to every place the source names it).
A design written as a plain Recipe is edited in its canonical form: its build() is lifted into one method
per Stage, built once and accepted only when volume, face count and bounding box are unchanged (computed);
get_design_source returns that form, and its feature ids are what ops name.
Only what changed is built: features before the first changed one load from their checkpoints. The source
is checked without the kernel first (preflight: "block" refuses on errors the edit introduces, "warn",
"off"); a feature that fails makes no revision unless partial=True. Pass expect_head.
Returns head, source_sha, changed (only the features built again: status, seconds, volume change), reused
(how many loaded from checkpoints), the proof sheet (requirement, measured, tolerance, evidence, status)
when the design has a contract or expects=, failing checks, and with look=True the six-view sheet.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `ops` | array | yes |
| `expect_head` | integer \| null |  |
| `note` | string |  |
| `run` | boolean |  |
| `partial` | boolean |  |
| `preflight` | string |  |
| `look` | boolean |  |

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

### `refine_design`

Show, rerun, undo or turn off design refinement of a project. It runs on its own after every build (create_design, update_design,
add_feature, a kept candidate): named, reversible refine features (fillet tiers, an edge break, a parting
line, a grip texture, a recessed panel, button pads, ribs; materials and contrast; for game assets cage ops
such as support loops, panel lines and silhouette breakers), each kept only when the function checks still
pass, the faces of fit, access, mechanism and interface features are unchanged and the walls hold. What it
keeps lands as one new revision, "Refined: N changes", each change with its reason and measured change.
action: "status" (the job's stage and events, and the refine changes the head carries; wait=s waits up to s
seconds for a running job), "rerun" (refine the head again now), "undo" (feature="refine_..." takes one change
out, no feature takes all of them out, as a new revision; expect_head guards it), "off" (no automatic
refinement for this design from now on; "on" turns it back on). Game assets (Beta) are not refined unless
asked: "on" or "rerun" for this design, or Settings › Refine game assets for all. Measures are computed
heuristics (form/refine/analyze.py); the checks are the kernel's.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `action` | string |  |
| `feature` | string |  |
| `wait` | number |  |
| `expect_head` | integer \| null |  |

### `get_design_source`

*Read-only.*

Get a design's source code: the code a revision was built from (built-in recipes return their recipe file).
Read it once; then change it with edit_design ops, which name features, and never send it back whole.
The head comes in canonical form, one method per feature: a FeatureDesign as it is, a plain Recipe lifted
(form: "features" when its build() split into feature methods, "skeleton" when it is one feature, "none"
with the reason when it stays as written), kernel-checked to be the same solid. features lists the ids
edit_design addresses; source_sha names this text. feature="holes" returns only that method (and the
parameters it reads). canonical=False, or a rev, returns the stored text. tree: per feature its place in the build order,
whether it is suppressed, and what it depends on (parameters it reads, features it names, helpers, members).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `rev` | integer \| null |  |
| `feature` | string |  |
| `canonical` | boolean |  |

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

Get a project's state: current revision with every parameter and its provenance, output status (current/stale/failed/missing),
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

Get a job's status: a pipeline job started by run_pipeline/commit_change; waits up to wait_s for it to finish.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `job` | string | yes |
| `wait_s` | number |  |

### `render`

*Read-only.*

Render the part as an image. Look at the part. Returns a PNG rendered from the real kernel geometry, coloured by feature.
view: iso, iso_back, front, back, left, right, top, bottom, "sheet" (four views at once), or for a design with
several parts "assembled" (put together) and "exploded" (pulled apart along its explode offsets).
highlight: a feature id to pick out. values: render an uncommitted candidate (same as preview_change).
upto: a feature id: the head as it stood after that feature (the rollback bar; the features up to it load from
their checkpoints, nothing is saved).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `view` | string |  |
| `highlight` | string \| null |  |
| `rev` | integer \| null |  |
| `values` | object \| null |  |
| `upto` | string |  |

### `animate`

*Read-only.*

Animate a design. Make motion from real geometry. kind="turntable" spins the head revision. kind="morph" builds every in-between
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

Compare two revisions. What changed between two revisions: parameters, features, interfaces, stability, fit.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `a` | integer | yes |
| `b` | integer | yes |

### `geometry_diff`

Diff the geometry of two revisions. What changed in the solid between revision a and b (default the head): material added (b minus a) and removed
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
Picked features (written as one named method plus its parameters, through the edit protocol; previewed in the
kernel first and refused with the reason when a feature would be left out; the checks then run again):
kind="fillet" (picks near edges, radius), "chamfer" (picks near edges, length), "hole" (one pick on a flat face;
standard clearance (size M2..M6, fit close|normal|loose: ISO 273), tapped (size: tap drill), iso286 (nominal and
fit such as H7: ISO 286, modelled at mid-tolerance) or plain (d); style plain|counterbore|countersink; depth
0 = through), "pattern" (of = a feature id; mode linear: axis x|y|z or [x,y,z], count, pitch mm; polar: axis,
origin, count, angle step degrees), "shell" (thickness; one pick on the face to leave open, or none).
picks: [{"at": [x, y, z]}] in design mm (analyze_selection gives points on edges and faces). Edges and faces
are kept as stable queries (the features that made them, their class, direction and place), not indexes;
a rebuild that cannot find one leaves the feature out and says which. preview=True builds and reports
(volume, box, faces, build log) and saves nothing. A pattern's direction can come from a picked edge (picks:
a line gives linear along it; a circle, polar about its axis).
From a sketch: kind="extrude" | "cut" | "revolve" with sketch = {plane, points, entities, constraints}
(get_sketch shows the form; plane {"datum": "XY"|"XZ"|"YZ", "offset"} or a picked face: give picks=[{"at": ...}]
on it), depth (mm; a cut with depth 0 goes through), angle and axis_entity (a line of the sketch) for revolve.
Named dimensions become parameters "<feature>_<name>"; the sketch must solve and close.

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
| `picks` | array \| null |  |
| `radius` | number \| null |  |
| `standard` | string |  |
| `fit` | string |  |
| `nominal` | number \| null |  |
| `d` | number \| null |  |
| `style` | string |  |
| `depth` | number \| null |  |
| `of` | string |  |
| `mode` | string |  |
| `count` | integer \| null |  |
| `pitch` | number \| null |  |
| `angle` | number \| null |  |
| `axis` |  |  |
| `origin` | array \| null |  |
| `preview` | boolean |  |
| `sketch` | object \| null |  |
| `axis_entity` | integer \| null |  |

### `get_sketch`

*Read-only.*

Get the sketch of a feature made from one (extrude, cut, revolve): its plane, points, entities (line, circle,
arc) and constraints, solved by form.sketch2d: point positions, the profile, degrees of freedom left, and the
named dimensions with their values (each is a parameter "<feature>_<name>"). Change it with edit_sketch.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `feature` | string | yes |

### `edit_sketch`

Edit a feature's sketch with ops (or send the whole sketch), as one revision. Ops, in order:
{"op": "add_point", "at": [x, y]}; {"op": "add_line", "from": i | [x, y], "to": ...};
{"op": "add_polyline", "points": [...], "close": true} (lines within 2 degrees of horizontal or vertical get that
constraint); {"op": "add_rect", "at": [x, y], "size": [w, h]}; {"op": "add_circle", "center": i | [x, y], "r": 5};
{"op": "add_arc", "center", "start", "end"}; {"op": "constrain", "kind": coincident|horizontal|vertical|parallel|
perpendicular|tangent|equal|midpoint|on|symmetric|fix, "entities": [...], "points": [...]};
{"op": "dimension", "kind": length|distance|hdist|vdist|radius|diameter|angle, "entities"|"points", "value",
"name"} (a name makes it a parameter; "" keeps it fixed); {"op": "set", "name": "w", "value": 70};
{"op": "move", "point": i, "to": [x, y]}; {"op": "delete", "constraint" | "entity": i};
{"op": "construction", "entity": i}. "Make it symmetric" is a symmetric constraint about a construction line.
Refused with the reason when the sketch would not solve (over-constrained, out of reach) or not close; nothing
is saved then. preview=True builds and reports. The checks run again on the saved revision.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `feature` | string | yes |
| `ops` | array \| null |  |
| `sketch` | object \| null |  |
| `expect_head` | integer \| null |  |
| `preview` | boolean |  |

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
require: strength constraints a lighter design must still meet, e.g. ["fea.safety_factor >= 2"], read from the
design's static strength_study (study="<id>" when it has several): the study is solved on each geometry
candidate that kept its checks, and one that fails is rejected with its numbers. With a strength requirement
the print-setting candidates (less infill, fewer walls) are not offered: the study is of a solid part.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `builds` | integer |  |
| `require` | array \| null |  |
| `study` | string |  |

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

Guide a replacement part from a photo. How to design a replacement for a broken part from the person's photo: find the scale from a reference
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

Write assembly instructions. Assembly instructions as a PDF from the design's assembly declaration: a parts page with computed volumes, then
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

Set the print setup. Print orientation (as_modelled, on_back, on_front, on_left, on_right, inverted, or a "down:x,y,z" id from
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

Optimize a design. Goal seek: search parameter ranges for the best design that meets constraints. Every candidate is built by the kernel.
vary: [{"key": "arm_t", "min": 4, "max": 20}] (1-4 parameters).
objective: {"minimize": "solid_mass_g"} or {"maximize": "statics.safety_factor"}.
constraints: ["statics.safety_factor >= 3", "overhang_mm2 <= 1", "derived.usable_depth >= 30", "fit_yield >= 0.9"].
Metrics: volume_cm3, solid_mass_g, width, depth, height, overhang_mm2, contact_mm2, min_wall_mm, fit_yield,
derived.<key>, statics.<key>. Nothing is saved: preview_change/render the best, then commit_change.
A strength study as a constraint: "fea.safety_factor >= 2" (also fea.peak_von_mises_MPa, fea.max_displacement_mm)
reads the design's static strength_study (study="<id>" when it has several). Each value is a full solve, so
the search runs first and the study is then solved on its candidates, best first, within 8 solves and 300 s:
"strength" in the result lists every candidate solved with its numbers and evidence, and only those count as
feasible. fea.safety_factor is the lower value (stated error applied); not an objective.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `vary` | array | yes |
| `objective` | object | yes |
| `constraints` | array \| null |  |
| `budget` | integer |  |
| `study` | string |  |

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
Parts that do not fit one plate (several parts, or `copies` of the design) go onto as many plates as it takes on
that printer's bed, never off it: Bambu Studio, OrcaSlicer and the Orca forks get one project with every plate,
each sliced by the program (plates[]: time and grams per plate, read from its own slice_info); PrusaSlicer and
its forks get one project per plate, each opened in its own window, plus one 3MF of all plates for PrusaSlicer
2.9+. A part larger than the plate however it lies is left out and listed in too_big with what would fit it.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `printer` | string |  |
| `open_app` | boolean |  |
| `copies` | integer |  |

### `open_bench`

Open the bench web page. The bench is the local web page where the user inspects the 3D model, compares revisions and approves releases.

| Argument | Type | Required |
|---|---|---|
| `project` | string \| null |  |
| `open_browser` | boolean |  |

### `brief_presets`

*Read-only.*

List brief presets. Intake guidance for common kinds of part (remote holder, desk accessory, organizer, bathroom mount, enclosure,
car accessory): the questions worth asking the person, environment defaults (temperature, humidity, UV, load), a
material to start from and the checks to plan for. Use it while gathering requirements; the defaults are
assumptions to confirm with the person, never measurements.

| Argument | Type | Required |
|---|---|---|
| `preset` | string |  |

### `import_reference`

Import an existing part (e.g. a Raspberry Pi 5 STEP from the manufacturer) into a project's references:
STEP, IGES, BREP, a mesh (STL, OBJ, 3MF, PLY, OFF, AMF, glTF/GLB, DAE, X3D, VRML, VTK) or a scan (XYZ, PTS, LAS,
E57: made a surface first); a zip imports every part in it. FORM copies it, measures it in the kernel (bounding box, volume: computed) and draws it in the 3D
view as a blueprint companion, in its own coordinates. A Python design can then read it with
self.reference("<name>") for clearance cuts. path: absolute local path. Re-importing a name replaces it.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `path` | string | yes |
| `name` | string \| null |  |

### `reconstruct`

Turn a mesh or scan into a design, by the route its triage chooses (STL, OBJ, 3MF, PLY, OFF, AMF, glTF/GLB,
DAE, X3D, VRML, VTK; XYZ, PTS, LAS, E57 point clouds become a surface first; a zip of meshes: one design, a
part each; units of glTF, DAE, AMF, 3MF, LAS and E57 are converted). project_or_file: an absolute
path to the mesh, or a project id whose imported mesh reference to use (reference: which one; default the
first mesh). It first repairs what is safe (sliver triangles hanging off an edge, wrong-way triangles, small
holes, flat openings; each listed under repairs) and then, with route="auto":
- a mechanical or mixed part: the parametric reconstruction. The program route reads sketches extruded and
  lofted between levels; Layer 0 is the mesh as an exact solid, Layer 1 (beta) replaces facets with planes,
  cylinders, cones, spheres, tori and fitted B-spline surfaces within `tolerance` mm, Layer 2 (beta) writes
  a build123d recipe with Params (a base, then fillets, chamfers, holes, patterns; a spur gear becomes a
  parametric gear). Returns summary.headline: editable_pct and the two-sided Hausdorff distance first. Never
  call a result with 0% editable "editable". A mesh above 300,000 triangles is simplified within a quarter
  of the tolerance first, with the measured deviation listed.
- an organic mesh (a sculpt, a scan, a figure): a surface body (one closed body without handles or sharp
  detail: NURBS faces over a cage you can edit, exports STEP; taken only when the measured distance is within
  0.1 % of its size or the tolerance) or else a mesh body (the repaired mesh, a lighter working copy when
  heavy with its measured distance from the file, with Scale and Flat base parameters; exact features are
  cut with MeshBody; exports STL and 3MF, not STEP). Takes well under a minute for 500,000 triangles.
- a file with several separate closed bodies: ONE design with one part per body.
- a surface that does not close after the repairs: refused, and the hint names the next call
  (import_reference: keep it as a reference). Do not call again with the same file.
If the parametric route fails on a mesh that closes, the mesh body is made instead (summary.fell_back_from).
route: "auto", or force "parametric", "surface_body" or "mesh_body". units: what the file's numbers are
("mm", "cm", "m", "in"); with "auto" they are millimetres, and a file whose size makes no sense in
millimetres (0.08 across) is not built on a guess: the refusal is the one question to put to the person,
then call again with units. scale: a plain factor instead. The result carries "triage" (class, route
taken, why, cannot).
Several meshes of ONE product (a base, a slider and a lid): pass them all at once, as files=[absolute paths]
(or project_or_file=<project id> with references=[names]); they become ONE design with one part per mesh, in
the positions the files give (parts that fail are listed in "failed", the others are kept). Never call this
once per part: that makes unrelated designs. Values are computed from the mesh and every repair is listed.

| Argument | Type | Required |
|---|---|---|
| `project_or_file` | string |  |
| `tolerance` | number |  |
| `layer` | integer |  |
| `name` | string \| null |  |
| `reference` | string \| null |  |
| `files` | array \| null |  |
| `references` | array \| null |  |
| `route` | string |  |
| `scale` | number |  |
| `units` | string |  |

### `analyze_reference`

*Read-only.*

Read an imported mesh or scan like an engineer before modelling it again as clean CAD
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

Analyze an assembly of meshes. How several imported meshes go together and move, measured in the positions they were given. references:
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

List what remains of a remodel. What is left to build in a remodel: the volume difference between the design (or one part) and an imported
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

Analyze the part as a map. An analysis map of the part, computed from the real geometry: a picture with its legend, and the statistics.
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

Measure distances and features of the part. Points are [x, y, z] in millimetres in the design frame.
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

### `mass_properties`

*Read-only.*

Mass, centre of mass, inertia tensor and principal axes, computed on the B-rep (OCCT), per part and for the
whole. Units: mm, g, g·mm² (also kg·m²); inertia is about the centre of mass in the design's axes, and about the
origin. A design that declares an assembly is reported assembled; pose={joint id: value} (degrees for a hinge,
mm for a slide) moves its joints; frame="as_built" gives the solids where the design builds them. Each part's
density comes from its material (set_appearance; the design's code may declare one per Part), with the
document it was read from; a part without a material has no mass (the volume centroid is given instead).
material= is a what-if for every part (or for `part`), nothing saved. library=True adds the full sourced
record of each material used (E, Poisson's ratio, yield, UTS, thermal, a printed filament's X-Y and Z values
and its Z knock-down; a value no source gives is listed as unsourced). Evidence class: computed (B-rep), or
computed (closed mesh) for a mesh design; a printed part is taken solid (100 % infill).

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `part` | string |  |
| `pose` | object \| null |  |
| `material` | string \| null |  |
| `frame` | string \| null |  |
| `rev` | integer \| null |  |
| `library` | boolean |  |

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

List annotations. The selections the person named and kept on this design (annotations): name, note, the revision they were
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

Set the colour and material of a design. Colour (#rrggbb) and material of the whole design (part="") or of one part (an assembly part id from
get_project / render). Filaments (a print design): PLA, PETG, ABS, ASA, TPU, PA (nylon), PC, PLA-CF, PETG-CF, PA-CF; Form Studio
adds their notes to the checks (heat, sunlight, warping, flexible, fibre-filled) and the slicer picks the matching filament.
Engineering materials (a model design: CNC, casting, rendering): AL-6061, AL-7075, STEEL, STAINLESS, BRASS, COPPER, TITANIUM,
STEEL-4140, OAK, OAK-WHITE, WALNUT, MAPLE, PINE, POM, PTFE, PEEK, PMMA, NYLON-PA6 ("aluminium 7075", "delrin" also work), with
their datasheet density (bd_materials' typical one where none is sourced) and look; mass_properties then gives mass, centre
of mass and inertia. The colour is drawn and written into the 3MF;
stored in the project's material fields (parts.<id>.material). Leave an argument out to keep it; clear=True removes both.

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
print success. Apply one with set_print_setup(project, orientation=<id>). print_orient searches every direction
over support, time, strength, surface and tip-over and returns the Pareto front.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `print_simulation`

*Read-only.*

Simulate the print layer by layer. Look at the sliced print as it would stand at the end of `layer` (1-based; default: finished). Returns a
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

Estimate the print cost. Filament, electricity and machine-time cost of the current slice, per plate and for `copies`, plus the same
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

Plan the plates. How the design's printed parts go onto plates: each part as it lies on its own (orientation, size, material),
the plates they are packed onto when the design does not fit one plate (or its parts differ in material), parts
too big for the plate (with their size against the bed and what would make them fit), and per plate the
slicer's time and filament when it has been sliced. Computed by FORM from bounding boxes, with the gap, the
brim's room and the bed's excluded zones; each plate is sliced on its own. Needs current checks (run_pipeline).
write_3mf=true also writes the plates (of `copies` of the design) as a 3MF in the form the design's slicer reads
as several plates (Bambu/Orca: one file; PrusaSlicer 2.9+: one file per 9 plates) under the project's folder:
export.files.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `write_3mf` | boolean |  |
| `copies` | integer |  |

### `set_part_print`

Set one part's print settings. Print settings for one printed part of a multi-part design (part ids from plate_plan): orientation (a named
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

Pack copies on a plate. Do `copies` of this design fit on one plate? Bounding-box packing with a gap (default 6 mm) and 90° turns,
on the selected printer's bed. Returns the layout, the most copies this packer can place, and `plates`: the
copies on as many plates as they take (never off a plate). Computed by FORM; plate_plan(write_3mf=true,
copies=N) writes them as a 3MF and open_in_slicer(copies=N) slices every plate.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `copies` | integer |  |
| `spacing_mm` | number \| null |  |

### `render_photo`

Render a photo-real image. A realistic-looking render of the current revision's exported STL, made by Blender headless (if installed).
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

List variants. The head and every saved variant side by side: size and volume (computed), print time and grams (simulated,
only when the variant is a revision with a current slice), fit yield (modelled), checks, and each variant's
differences from the head.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `share_card`

*Read-only.*

Make a share card image. A 1600 x 900 share image of the head revision: the part with dimension lines, its name, size and volume
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
project. Returns {ok, id, trash}: tell the user the trash path. Outside Form Studio's chat, a client with
its own forms (MCP elicitation) asks the person to confirm first; declined: {ok: false, refused}.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |

### `list_printers`

*Read-only.*

List printers. Every printer set up in every installed slicer (the user's own presets and the system printers they enabled),
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
reason, note}: then continue with safe assumptions marked assumed. Outside Form Studio's chat the question
is shown in your client's own form when it supports one (MCP elicitation); otherwise nobody can answer
here and the result tells you to ask in your own interface.

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
{answered: false, reason, note}. Outside Form Studio's chat it is asked in your client's own form when it
supports one (value, calipers / ruler / datasheet, or skipped; a datasheet value is recorded as specified);
otherwise it tells you to ask in your own interface.

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

Propose concepts. For a new idea: build 2-4 genuinely different concepts as real designs, so the person can pick one.
concepts: [{"title": short name, "rationale": one line on the approach, "source": design code as for
create_design (see design_guide), "language": "python", "values": {...} or null, "material": "PETG" | "AL-6061" | ...
(optional; set_appearance's keys)}]. Give each concept the material it would be made in: its card shows the mass
(computed on the B-rep in that material; without one a print concept is shown in PLA, marked assumed). Make them different
structural approaches (how it holds, mounts, opens), not size variants. Each becomes its own project
("<name> · A", "· B", ...). A concept that fails to build comes back in "failed" with its error; the others are
kept. group: an open group's id to add concepts to (at most 6 in a group), e.g. one mixed concept when the
person asks for "the base of A with the hook of C". With run=True each is exported and checked.
Returns the board: {id, name, state, members: [{project, letter, title, rationale, numbers}], failed};
numbers: size, volume, mass_g with its material and how it is known.

| Argument | Type | Required |
|---|---|---|
| `name` | string | yes |
| `concepts` | array | yes |
| `brief` | string |  |
| `group` | string \| null |  |
| `run` | boolean |  |

### `pick_concept`

Pick a concept. The person picked a concept (in words; in the app they pick on the board). The picked project takes the
group's name and records the choice; the other concepts move to the trash (recoverable) unless keep_others.
Then refine the picked design with update_design. Only call this when the person said which one.

| Argument | Type | Required |
|---|---|---|
| `group` | string | yes |
| `project` | string | yes |
| `keep_others` | boolean |  |

### `dismiss_concepts`

Dismiss concepts. The person wants none of the concepts picked: close the group without a pick. keep="all" keeps every
concept as an ordinary design; keep="none" moves them all to the trash (recoverable). Only call this when
the person said so.

| Argument | Type | Required |
|---|---|---|
| `group` | string | yes |
| `keep` | string |  |

### `list_concepts`

*Read-only.*

List concepts. Open concept groups ({groups: [...]}, newest first), or one group's board with group=<id>.

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

List starter ideas. Ideas for what this person might design next, ranked from what they already design (the building blocks
and kinds of part in their projects, their printer and material, what they pinned or used):
{prompts: [{id, text, source, pinned}], briefs: [...]}. Offer them as suggestions when the person asks what to
make; they edit the list with `form starters`.

### `recipe_library`

*Read-only.*

Search the recipe library: built-in recipes and recipes the person installed ("mine"), to find a building
block to start a design from. section: builtin | mine. Recipes are internal building blocks: use one when it
fits, but do not offer the library to the person. Installing code is the person's decision and happens only
with `form recipes install`, after they review the source and its SHA-256.

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

Export a conversation. A saved conversation as Markdown (format="md", to read or share) or JSON (format="json", to import again).

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
materials: {region or zone name | "default": {material, tint "#rrggbb", grain_mm, wear 0..1, roughness,
emission}}; material is one of wood, bare_metal, brushed_metal, painted_metal, leather, plastic, rubber, stone,
fabric, emissive (each with a baked height pattern; edge wear, cavity dirt and roughness breakup from the high
poly's curvature, AO and thickness). The older {finish, color, pattern} form is still read. Left out, the
design's own materials() method is used (a literal dict in its source, read without running it).
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

### `list_studies`

*Read-only.*

List every study, route and document of a design with its state: the Bench. group: study (Review), route
or document (Make). Each entry: id, label, state (never, current, stale, failed, running, unavailable, n/a),
rev (the revision its result describes; a stale entry names the revision its newest result was computed for),
headline with evidence, needs, inputs, and by whom it runs (engine; agent: call `tool` yourself; person: only
they do it, in Form Studio). Reads only; nothing is run.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `group` | string \| null |  |

### `run_study`

Run one Bench entry for the head revision (ids from list_studies). A current entry comes back as it is
unless force=True. Waits up to wait_s, then returns a job to poll with get_job. An entry the agent must do
(critique) returns the tool to call; one only a person does (release) is never done here.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `id` | string | yes |
| `force` | boolean |  |
| `wait_s` | number |  |

### `get_study`

*Read-only.*

Read one Bench entry: its state, the revision it describes, its headline with evidence, its files and
stored numbers, and the log of its runs. Reads only.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `id` | string | yes |

### `strength_study`

Run a strength study on the design: will it hold? Finite elements on the B-rep (quadratic tetrahedra, Netgen
mesh), refined until the answer stops changing, with the discretisation error stated. kind: "static" (stress,
displacement, safety factor against the material's yield), "modal" (natural frequencies; no supports = free
body; loads ignored), "buckling" (the factor on the loads at which it buckles), "thermal" (steady heat conduction:
temperatures and the heat through the part) or "thermal_stress" (the stress from that temperature field, with
any loads; reference_C is the temperature at which the part is stress free).
thermal: [{"type": "temperature", "faces": [...], "value_C": 80}, {"type": "convection", "faces": [...],
"h_W_m2K": 10, "ambient_C": 20}, {"type": "heat", "faces": [...], "value_W": 5}, {"type": "heat_flux", "faces":
[...], "value_W_m2": 2000}]; a face with none is insulated. A heat study needs the material's conductivity
("k_W_mK"), thermal stress also its expansion ("cte_per_K").
Faces are picked as points on the part, [x, y, z] in design millimetres, each part as printed (as for
analyze_selection, which shows the face a point lands on).
fixtures: [{"type": "fixed" | "roller" | "pin" | "hold", "faces": [[x, y, z], ...]}]. fixed: no movement. roller: slides
in the face, cannot leave it (a symmetry plane). pin: a cylindrical face that may turn about its axis. hold:
no movement along "directions": [[x, y, z], ...], free in the others.
loads: [{"type": "force", "faces": [...], "vector": [Fx, Fy, Fz]}] newtons, spread over the faces (or
"magnitude" and "direction"); {"type": "pressure", "faces": [...], "value_MPa": p}; {"type": "preload",
"faces": [under the head], "faces_b": [under the nut], "force_N": N} a bolt's clamping force as a modelled
connector; {"type": "gravity", "g": 1, "direction": [0, 0, -1]}.
material: a key of the materials library ("AL-6061", "PETG": E, Poisson's ratio, yield and density with their
sources), or values with where they are from: {"name", "E_GPa", "poisson", "yield_MPa", "density_kg_m3",
"source"}; left out: the design's material (set_appearance). materials: {part id: material} for several parts,
which are solved assembled and bonded where they touch. Nothing is assumed: without E or Poisson's ratio the
study is refused; without a yield strength there is no safety factor.
mesh: optional {"h0" start size mm, "levels_max", "dof_max", "budget_s", "tol_stress" 0.05, "tol_disp" 0.01,
"singular_radius" mm}. The study is saved in the project and runs in the background: read it with
get_strength_study(project, study, wait_s). study="<id>" alone runs a saved study again (after a change it is
stale); with a definition it replaces that study; remove=True deletes it. No arguments but project: the
design's studies with their states. Evidence class: simulated (FEA, <kind>, converged to N %), or "not
converged", which gives no safety factor. Stress at a sharp inside corner is named as singular and left out.
Linear elastic, small strain; a printed part is solved solid and isotropic. Needs the optional strength engine
(setup_status); without it nothing is computed and the call says so.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `kind` | string |  |
| `fixtures` | array \| null |  |
| `loads` | array \| null |  |
| `material` | string \| object \| null |  |
| `materials` | object \| null |  |
| `modes` | integer \| null |  |
| `mesh` | object \| null |  |
| `name` | string |  |
| `study` | string |  |
| `run_now` | boolean |  |
| `force` | boolean |  |
| `remove` | boolean |  |
| `thermal` | array \| null |  |
| `reference_C` | number |  |

### `get_strength_study`

*Read-only.*

Read a strength study: its state (never, running with progress, current, stale with the revision the
stored result describes, failed with why), and the result. Waits up to wait_s seconds for a running study.
The result gives the headline, the evidence class, the safety factor with its lower value under the stated
error and the source of the strength it is against, peak von Mises stress and where, largest displacement,
natural frequencies or the buckling load factor, the discretisation error, every singularity that was left
out (where, why, how the stress there grew with refinement), the balance of reactions and loads, the mesh, the
material's numbers with their sources and the assumptions. converged=false means the tolerance was not
reached: the numbers are reported with why, and no safety factor is given. full=True adds every refinement
level's record. field_file is the path of the field data for a viewer (per-vertex displacement, von Mises
stress and safety factor on the surface mesh; docs/STRENGTH.md); field=True returns it inline (large).
cancel=True stops a running study; nothing is stored for a cancelled run.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `study` | string | yes |
| `wait_s` | number |  |
| `full` | boolean |  |
| `field` | boolean |  |
| `cancel` | boolean |  |

### `calculate`

Size a part from requirements with a standard's equations, and write it as a design. calculator: "snapfit"
(cantilever or annular snap joints by permissible strain; Bayer's snap-fit guide), "hinge" (living hinge:
elastic by strain, or moulded PP/PE from cited practice), "spring" (compression, extension, torsion; EN
13906-1/-2/-3, with a printed-spring mode), "fastener" (screw size from the load, preload, tightening torque,
thread stripping, or a boss with a heat-set insert; VDI 2230 Part 1 simplified), "gear" (involute spur and
helical pairs with profile shift, internal pairs, rack and pinion; contact ratio, backlash, Lewis bending),
"cam" (plate cam from a motion law; pressure angle, undercut), "fit" (an ISO 286 fit over a temperature span
from the materials' sourced expansion). No calculator: the list, with every input and its unit.
inputs: plain numbers and words in mm, N, N·mm, degrees, MPa, °C; materials are keys of the materials library
(mass_properties library=True lists them). The result is a sheet: values (each with unit, evidence = computed,
specified or assumed, its equation and its source), checks (PASS, WARN, FAIL with why), equations (text and
source), sources (title, url), caveats, and not_computed (what was left out because an input has no source,
and what to give). Nothing is assumed silently: a missing material value leaves its result out.
build=True writes the geometry as a new design with a parameter per sized dimension (name= names it); every
later revision runs the calculation again on its values. project= with at=[x, y, z] and normal=[x, y, z] puts
a snap hook or an insert boss on that face of an existing design instead. project= alone (no calculator):
the sheet of a design a calculator wrote, for its head revision. fea=True with build=True also defines a
strength study that checks a cantilever hook's deflection by finite elements (needs the strength engine).

| Argument | Type | Required |
|---|---|---|
| `calculator` | string |  |
| `inputs` | object \| null |  |
| `build` | boolean |  |
| `name` | string |  |
| `project` | string |  |
| `at` | array \| null |  |
| `normal` | array \| null |  |
| `expect_head` | integer \| null |  |
| `purpose` | string \| null |  |
| `fea` | boolean |  |

### `print_orient`

Find the print orientation over several objectives at once. Returns the Pareto front: the orientations no
other one beats on everything. Objectives: support volume (mm3) and support contact on the part (mm2), both
computed from the facets that overhang past the critical angle, with each support column going down to the
plate or to the part below; print time by a layer-time model; strength along the load; surface quality on
the faces marked cosmetic; and the tilt at which the part tips off its plate contact.
cosmetic: points on the faces that show, [[x, y, z], ...] in design millimetres (stair height and support
marks on them become objectives). study: a static strength study whose stress field gives the tension across
the layers in every orientation, against the material's Z strength from its datasheet (left out: the design's
one current static study); or load_direction=[x, y, z] when only the direction of the load is known. Without
either, strength is not an objective and the result says so.
The search is the six axis orientations, every flat face the part can lie on, and a geodesic grid over all
directions (level 2: 162, about 16 degrees apart; 1: 42; 3: 642), then a local refinement down to 1 degree.
The front is taken over the orientations in which the part stands on the plate on its own (a flat face on it,
the centre of mass over it); free=True also admits orientations that rest on supports.
The front is ranked by weights you can change (weights={"support_mm3": 0.4, "time_s": 0.1, ...}); the ranking
is a convention, the front is not. Each row says how every number is known: computed, modelled, simulated.
Print time is uncalibrated unless a real slice exists: calibrate=True slices the current orientation once
(supports on) and scales the model by it, stating the factor; "auto" uses such a slice only if it is already
there. verify=N slices the N best-ranked candidates with the real slicer and reports the model's error in time
and in support filament per candidate (a slice each: about a minute).
Nothing is written to the print setup by a search. The person picks: pick="<id>" writes that orientation to
the design's print setup (ask before picking for them). A call with only the project repeats the last
search's inputs. critical_deg: the steepest overhang printed without support, from vertical (default: the
slicer preset's threshold, else 45). Not a print-success prediction: slice the pick to confirm.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `cosmetic` | array \| null |  |
| `study` | string |  |
| `load_direction` | array \| null |  |
| `weights` | object \| null |  |
| `level` | integer |  |
| `calibrate` | boolean \| string |  |
| `verify` | integer |  |
| `critical_deg` | number \| null |  |
| `pick` | string |  |
| `top` | integer |  |
| `free` | boolean |  |

### `print_strength`

Strength of the part as printed, layer by layer. A static strength study with a layered (transversely
isotropic) material, stiff and strong in the layers, weaker across them, turned to the print orientation. Gives the safety factor
in the weak direction (tension across the layers against the datasheet's Z strength, with its own stated
discretisation error), the in-plane one (von Mises against the X-Y strength), the lower of the two as the
verdict, and how they change with the orientation: the same mesh and loads solved for each other build
direction.
study: an existing static strength study whose supports, loads and material are reused (strength_study defines
them); or give fixtures, loads and material as for strength_study. orientation: "setup" (the design's print
setup; the result goes stale when the setup changes) or an orientation id (as_modelled, on_back, ..., or a
"down:x,y,z" id from print_orient). sweep: "auto" (the six axis orientations), a list of up to eight ids, or
[] for none.
The material: in-plane modulus and strength and the Z modulus and strength are the filament datasheet's
(X-Y and Z specimens, each with its document). Poisson's ratio is in no filament datasheet: a value measured
on printed specimens of the same polymer is used where a paper gives one, and named; otherwise give it
(material={"key": "PETG", "poisson": 0.38, "source": "..."}). Two constants no source has are assumed by a
stated rule unless you give them in assume: {"poisson_z": ..., "G_z_MPa": ..., "E_z_GPa": ..., "uts_z_MPa":
..., "uts_xy_MPa": ..., "shear_strength_MPa": ..., "source": "..."}; every assumed value is listed in
result.layers.material.assumed, and a study with assumed values says so in its evidence. Without a Z strength
there is no safety factor in the weak direction. No arguments but project: the design's layered studies.
It runs in the background like any strength study: read it with get_strength_study(project, study, wait_s);
the layered part is result.layers. Infill, walls, raster direction and voids are not modelled: the part is a
homogeneous solid with the datasheet's 100 % infill values. Needs the optional strength engine.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `study` | string |  |
| `fixtures` | array \| null |  |
| `loads` | array \| null |  |
| `material` | string \| object \| null |  |
| `orientation` | string |  |
| `sweep` | array \| string |  |
| `assume` | object \| null |  |
| `mesh` | object \| null |  |
| `name` | string |  |
| `run_now` | boolean |  |
| `force` | boolean |  |

### `print_warp`

*Read-only.*

Warp risk of the part as printed: an indicator, never a predicted lift in millimetres. It is the layer-
shrinkage model of Wang, Xi and Jin (2007): every layer shortens by alpha x (Tg - chamber temperature) on the
stack below it, which bends a part of n layers over its longest span on the plate; the index is that model's
end lift over one layer height. Inputs, each with how it is known: the material's thermal expansion and glass
transition (sourced from a paper or a resin datasheet of the same polymer, named; or given with alpha_per_K,
tg_C and source), the chamber temperature (given, else assumed 25 C for an open printer), and from the
geometry in the print orientation the first-layer area, the longest span, the footprint's aspect ratio, the
height in layers and the sharp corners at its ends. The band (low, moderate, high) is a stated convention on
the index, raised by sharp corners and by a footprint that touches the plate on little of its extent.
Returns the index, the band and what raised it, every input, the footprint's corners (where it lifts first),
and the same index for the six axis orientations so they can be compared. orientation: default the design's
print setup. Without a sourced expansion coefficient or glass transition for the material the call is
refused, naming what to give. It does not know the plate, its temperature, the adhesive, a brim, infill or
drafts, and the model is not calibrated to any print.

| Argument | Type | Required |
|---|---|---|
| `project` | string | yes |
| `orientation` | string \| null |  |
| `material` | string \| null |  |
| `chamber_C` | number \| null |  |
| `alpha_per_K` | number \| null |  |
| `tg_C` | number \| null |  |
| `layer_height_mm` | number \| null |  |
| `source` | string |  |

## Prompts

### `design_part(goal)`

A guided session: measure first, look at renders, preview before commit, hand the release to the user.
