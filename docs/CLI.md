# Command line

Everything the desktop app does is also a `form` command. Commands print JSON, so scripts and agents can read them,
and they work on the same project folder as the app and the MCP server, at the same time.

```bash
form --help              # every command
form <command> --help    # its arguments
```

Projects live in `~/FORM` by default. Set `FORM_DATA` to use another folder, and `FORM_CONFIG` to use another
`studio.toml`.

## Quick start

```bash
form start --text "A stand for my phone, 9.5 mm thick" --photo phone.jpg   # start the way Home does
form new "Desk stand" device_stand device_width=75.6                    # or from a recipe: solid, exports, checks, slice
form commit desk-stand lean=18 --expect-head 1                          # a new revision, rebuilt and checked
form simulate desk-stand --png sim.png --layer 40                       # the print, drawn from the G-code
form share desk-stand --out card.png                                    # a share card
form chat "Make the base 92 mm deep" --project desk-stand --agent codex
```

## Apps and servers

| Command | Does |
|---|---|
| `form app` | Open the desktop app |
| `form mcp` | The MCP server over stdio (the same as `form-mcp`) |
| `form serve` | The engine's local HTTP interface on `127.0.0.1` |

## Setup

| Command | Does |
|---|---|
| `form setup` | Find what is missing and fix what you choose. `--check` prints the findings as JSON, `--yes` accepts every fix, `--dry-run` shows the commands only, `--auto` installs everything needed hands-free and waits where you must act (`--no-wait` skips those steps) |
| `form doctor` | The kernel, slicer, printer, purpose and agents Form Studio found |
| `form install --list` | Everything Form Studio can install: parts libraries, slicers, agents, OpenSCAD, Blender, FreeCAD |
| `form install <id>` | Install one item, after showing its commands (`--yes`, `--dry-run`) |
| `form config get [key]` / `form config set <key> <value>` | Read or change `studio.toml` |
| `form secrets status \| set NAME \| clear NAME` | Agent keys such as `gemini_api_key`, read from a hidden prompt |
| `form providers list \| add URL [--name N] [--no-key] \| edit ID \| test ID [--model M --tools\|--images] \| remove ID` | Model providers added by address: format and models detected; the key is read from stdin or a hidden prompt, never an argument |
| `form update` | Is there a newer version (`--check` prints JSON; `--install` installs it) |
| `form capabilities [on\|off <id>]` | What Form Studio is set up for (core, parts, mesh, render, exchange, print); off never uninstalls |

## Start a design

`form start` starts a design the way Home does: words, photos, files, a sketch and links go to an agent in one
message, with what the design is for.

| Command | Does |
|---|---|
| `form start --text "…" [--photo F]... [--file F]... [--sketch F.json] [--link URL]... [--purpose print\|model] [--agent ID] [--model X] [--json]` | A new conversation with everything attached, sent to the agent; prints like `form chat` |
| `form start --blank [--name N] [--purpose print\|model]` | A blank design (a rounded 60 × 40 × 20 mm block) built in the kernel; prints `{id, name, purpose}` |
| `form concepts` | Open concept groups, newest first |
| `form concepts <group-or-project>` | One group's board: each concept's project, title, rationale and computed size and volume |
| `form concepts pick <group> <project> [--keep-others]` | Keep one concept: it takes the group's name; the others move to the trash unless `--keep-others` |

- `--purpose print` is for 3D printing on your printer; `model` is just a 3D model: Design only is set and nothing is
  sliced. Without it, the choice you made last on Home is used, else `print` when a slicer is installed.
- `--link`: a link to a file (any part, scan, drawing or zip `form formats` lists, a PDF or a picture) is downloaded (streamed, up to 2 GB) and
  attached; a Printables model page has its part files attached with title, author and licence; a MakerWorld or
  Thingiverse page says why its files cannot be fetched; any other link is passed to the agent as a page and nothing
  is downloaded.
- `--file` attaches up to 2 GB. The file is cloned into the conversation (copy-on-write on APFS, Btrfs and XFS), else
  hard-linked or streamed; it is never read whole.

### Links and big meshes

| Command | Does |
|---|---|
| `form resolve URL` | What a model link is, without downloading: site, title, author, licence, pictures, files, and whether and why not they can be fetched |
| `form fetch URL [--conversation ID]` | Download what the link points to: into a conversation, else under `<data>/.references/links/` with a `.source.json` beside each file |
| `form formats` | Every file format Form Studio reads, with its kind (mesh, pointcloud, brep, 2d, archive, photo, document) and what it says about units, and the formats it does not read with the reason. Meshes: STL, OBJ, 3MF, PLY, OFF, AMF, glTF/GLB, Collada (DAE), X3D, VRML, VTK, VTP, VTU; point clouds: XYZ, PTS, LAS, E57; CAD: STEP, IGES, BREP; drawings: DXF, SVG; zip archives of these |
| `form mesh-preflight FILE [--no-proxy]` | Triangles, vertices, bounds, closed or not, class, estimated seconds, and a display proxy for a heavy mesh or scan |
| `form triage FILE\|LINK\|WORDS` | What the input is and the route Form Studio takes. A mesh is repaired on a copy and measured (triangles, size, a guess at the units, defects before and after repair, bodies, how much of the surface is flat or ruled), classed mechanical, organic or mixed, and given a route: parametric, surface body, mesh body, assembly or reference only. A point cloud (XYZ, PTS, LAS, E57) is made a surface first and the reconstruction is in its facts. Also routes STEP, IGES and BREP (CAD reference), DXF and SVG (profile, with outlines and sizes), a zip (unpacked safely, each file with its route), a photo, a PDF, a link and plain words. MCP `triage` |

- Sites: Printables (public API, no account), Thingiverse (needs `FORM_THINGIVERSE_TOKEN`, an app token sent only to
  api.thingiverse.com; without it the page and the reason are returned), MakerWorld (files need a signed-in person:
  the reason and how to download it; a signed download link pasted from the browser is a direct file link). Every
  request carries the user agent `FormStudio/<version>`, no cookies and nothing about you.
- The preflight is cached under `<data>/.cache/meshprep/` by the file's path, size and modification time.
- `--sketch` takes Form Studio's sketch JSON (millimetres, y up; see `form/sketch.py`). The agent reads its geometry
  as exact numbers; a dimension with a stated value overrides the drawn length.
- Concepts are made by the agent (`propose_concepts`): three or four genuinely different designs, each a real project.

## Designs

| Command | Does |
|---|---|
| `form replace --photo FILE [--name NAME] [--what TEXT] [--broke TEXT] [--reference card\|coin\|ruler\|none]` | Start the replacement of a broken part from a photo with a scale reference |
| `form list` | Every project |
| `form recipe <recipe>` | A recipe's parameters, features and checks |
| `form new <name> <recipe> [key=value ...] [--purpose print\|model] [--process P] [--brief TEXT]` | A new design from a recipe; `--process` (for a model) is `cnc`, `laser`, `injection`, `casting`, `sheet_metal`, `render`, `cad` or `other` |
| `form purpose <project> [print\|model] [--process P]` | Read or change what a design is for |
| `form state <project>` | The head revision: parameters with provenance, outputs, checks, fit, slice, release gate |
| `form preview <project> key=value ...` | Build a change without saving it, and report its impact |
| `form commit <project> key=value ... [--note] [--expect-head N] [--measured keys]` | Save a change as a new revision |
| `form run <project> [--force]` | Regenerate whatever is stale: solid, STEP, STL, OBJ and GLB, checks, slice |
| `form history <project> [--gif FILE]` | The revision list; `--gif` writes a morph through every revision (`.gif` or `.webp`) |
| `form variants list\|save\|promote\|delete <project> [name] [key=value ...]` | Named variants |
| `form mark <project> --text TEXT` | The label text for designs with lettering |
| `form rename <project> <name>` | Change the display name (the id stays) |
| `form duplicate <project> [--name NAME]` | Copy a project under a new id |
| `form delete <project> --yes` | Move a project to the trash inside the projects folder |
| `form export <project> [--out FILE.formstudio] [--no-conversations]` | The design, its history, its conversations and the code it was built from, as one file |
| `form import FILE.formstudio \| FILE.formproj \| CONVERSATION.json` | Import; a clashing id gets a new one and nothing is overwritten |
| `form testplan <project> [--out DIR]` | The test plan: each requirement, fit, critical dimension and load with its instrument, limits, readings and when it passes; TEST_PLAN.pdf, TEST_PLAN.md and TEST_CHECKLIST.csv |
| `form testplan record <project> TEST V1 V2 ... [--instrument I] [--by NAME]`, `--result pass\|fail`, `--csv FILLED.csv` | Record what you measured against one test (or every filled row of the checklist), with provenance measured |
| `form report <project> [--out DIR]` | The results report: measured results against the plan, every check and study with its evidence, open items and the verdict (PASS, NOT A PASS, FAIL); exits 0 only on PASS |
| `form backup status\|run [--if-due]\|list\|verify [FILE]` | Back up every design and conversation to the folder (and Git repository) in Settings › Backups; check a backup's SHA-256s |
| `form backup restore FILE [--project ID ...] [--replace]` | Restore from a backup file or a clone of the backup repository; an existing design is kept unless `--replace` (then it goes to Recently deleted) |
| `form backup deleted\|undelete ENTRY\|purge` | Recently deleted: 30 days, and longer while no backup holds a design |

## Look and analyse

| Command | Does |
|---|---|
| `form render <project> [--view iso\|front\|side\|top\|under\|sheet] [--highlight FEATURE] [--out PNG]` | An engine render coloured by feature |
| `form analyze <project> --map thickness\|overhang\|section\|features [--png FILE]` | An analysis map and its statistics |
| `form measure <project> --from x,y,z --to x,y,z` | A distance; `--at x,y,z` reports the face, edge or hole at a point |
| `form orient <project> [--apply [ID]] [--png FILE]` | Rank print orientations; `--apply` sets the best one |
| `form animate <project> [--morph 1:4] [--frames N] [--out FILE]` | A turntable, or a morph between two revisions |
| `form turntable <project> [--fmt mp4\|png\|webp\|gif] [--frames N] [--elevation DEG] [--out FILE]` | The part turning once, rendered from the kernel's mesh; MP4 needs ffmpeg |
| `form share <project> [--out PNG] [--photo]` | The share card; `--photo` uses the newest Blender render |
| `form select <project> [--point\|--edge\|--face x,y,z]... [--region "x,y,z;..." --radius R] [--keep NAME --note TEXT] [--text]` | Analyse points, edges, faces or a painted region on the solid: area, tilt, overhang, wall thickness, curvature, height; `--keep` saves it as an annotation |
| `form annotations <project> [list\|show\|delete] [ID]` | Kept selections |
| `form appearance <project> [--part PART] [--color #hex] [--material M] [--clear] [--3mf FILE]` | Colour and material of the design or one part; `--3mf` writes a 3MF with colours |
| `form engrave <project> TEXT --at x,y,z --normal x,y,z [--up x,y,z] [--height MM] [--depth MM] [--sunk]` | Raised or sunk text on a flat face, written into the design's code as a feature and built as a new revision; `--list` and `--remove text_N` |
| `form feature <project> boss\|snap_hook --at x,y,z --normal x,y,z [--size M3] [--hole tapped\|clearance\|insert] ...` | A screw boss or a snap-fit hook on a flat face, written into the design's code and built as a new revision |
| `form strength static\|modal\|buckling\|thermal\|thermal_stress <project> [--fix x,y,z]... [--roller x,y,z] [--pin x,y,z] [--force x,y,z:Fx,Fy,Fz] [--pressure x,y,z:MPa] [--preload x,y,z:x,y,z:N] [--gravity [G]] [--temperature x,y,z:C] [--convection x,y,z:H:AMBIENT] [--heat x,y,z:W] [--reference C] [--material KEY\|JSON] [--modes N] [--mesh JSON]` | A strength study with a stated error: stress, displacement and safety factor, natural frequencies, the buckling load factor, steady temperatures or thermal stress. Exit 3 when it did not converge. `form study strength ...` is the same. [STRENGTH.md](STRENGTH.md) |
| `form lattice list`, `form lattice props KIND cell=8 density=0.2\|wall=0.8\|strut_d=1.0 [form=sheet\|network] [material=M] [process=P] [nozzle=N] [--verify]`, `form lattice fill <project> KIND ... [skin=1.2] [region=x0,y0,z0:x1,y1,z1] [grading=JSON] [study=ID] [output=auto\|brep\|mesh]`, `form lattice show\|remove <project>` | A strut lattice (bcc, fcc, octet, kelvin) or TPMS (gyroid, schwarz_p, schwarz_d, neovius) in a design or a box of it, with a skin: what was built (B-rep or mesh, and why), relative density, stiffness by scaling law, printability. `props` saves nothing. [LATTICES.md](LATTICES.md) |
| `form photo-profile PHOTO [--card \| --coin eur_1 \| --coin-d MM \| --scale X0,Y0:X1,Y1=MM] [--ref-at X,Y] [--part-at X,Y] [--tol MM] [--svg FILE] [--build --depth MM --name N] [--full]` | A flat part's outline from a photo with a reference object: lines, arcs and circles in mm as a sketch, each dimension with its uncertainty, estimated from the photo. `--build` extrudes it into a design with assumed parameters. [PHOTO_AND_LINKAGES.md](PHOTO_AND_LINKAGES.md) |
| `form linkage motion --poses JSON`, `form linkage function --pairs JSON [--ground MM]`, `form linkage path --targets JSON [--open] [--seed N]`, each with `[--require-crank] [--steps N] [--max-size X] [--build --name N] [--full]` | Four-bar synthesis from three poses (Burmester), three angle pairs (Freudenstein) or a path (optimisation, error stated): link lengths, Grashof, transmission angle, defects, and a simulation through the targets. `--build` writes the assembly. [PHOTO_AND_LINKAGES.md](PHOTO_AND_LINKAGES.md) |
| `form stack run <project> --a X,Y,Z[@part] --b X,Y,Z[@part] [--dir X,Y,Z] [--tol KEY=T\|KEY=LO:HI] [--dist KEY=normal\|uniform] [--spec LO,HI] [--temps TMIN,TMAX] [--alpha PART=1/K] [--samples N --seed S] [--brief]`, `form stack add ... --name N`, `form stack list\|show\|rerun\|rm <project> [id]` | Tolerance stack-up of the gap between two picked faces: the loop found through the mates, worst case, RSS, Monte Carlo, Cpk, each tolerance's share and source, the gap over a temperature span, what to tighten first. `add` keeps it with the design (the Bench entry `stack`). [TOLERANCES.md](TOLERANCES.md) |
| `form calc <calculator> key=value ... [--build] [--name N] [--project P --at x,y,z --normal x,y,z] [--fea]`, `form calc list`, `form calc show <project>`, `form calc verify [--geometry]` | An engineering calculator: `snapfit`, `hinge`, `spring`, `fastener`, `gear`, `cam` or `fit`. A sheet with every number labelled computed, specified or assumed, its equation and its source; `--build` writes the geometry as a design with parameters, `--project` puts a snap hook or an insert boss on a face. `show` runs the calculation of a calculator-written design again for its head revision; `verify` prints the worked examples against their published answers. [CALCULATORS.md](CALCULATORS.md) |
| `form print orient <project> [--cosmetic x,y,z]... [--study ID \| --load x,y,z] [--weights JSON] [--level 1\|2\|3] [--calibrate] [--verify N] [--critical DEG] [--free] [--top N]`, `form print orient <project> --pick ID` | The Pareto front of print orientations over support, time, strength, surface and tip-over; `--pick` writes one to the print setup; `--verify N` slices the best with the real slicer and reports the model's error. [PRINT_PHYSICS.md](PRINT_PHYSICS.md) |
| `form print strength <project> --study ID [--orientation O] [--sweep a;b \| --no-sweep] [--assume JSON]` (or `--fix`, `--force`, `--material` as for `form strength`) | Strength as printed: a layered material in the print orientation, the safety factor across the layers and in them, and how it changes with orientation. Exit 3 when it did not converge |
| `form print warp <project> [--orientation O] [--material M] [--chamber C] [--alpha 1/K] [--tg C] [--layer mm] [--source TEXT]` | Warp risk: an indicator from a cited model, never a predicted lift |
| `form strength run\|show\|remove <project> <study>`, `form strength list <project>`, `form strength verify [case ...]` | Solve a saved study again, read it (`--full`, `--field`), list a design's studies with their states, or run the verification suite |
| `form dfm <project> [--process P] [--set k=v ...] [--override RULE:fail=X] [--fix ID [--preview]] [--png FILE]` | Manufacturability for CNC, moulding or a printing technology: every rule with its source, findings, proposed fixes; `--fix` applies one and proves it by checking again. `form dfm rules [PROCESS]` prints the rule tables |
| `form sheet flat\|profile\|check\|bends\|preflight\|tables <project or file.dxf> [--set k=v ...] [--kerf MM] [--process laser\|waterjet\|router] [--service sendcutsend --material M --thickness MM] [--out FILE]` | Sheet metal and cut parts: the flat pattern (unfolded, folded back to prove it) and its DXF, a flat part's profile with kerf, the cut-file check of any DXF, a bend order with a press-brake model, a service preflight (nothing is sent); see docs/SHEET_METAL.md |
| `form cam plan\|post\|simulate\|status <project> [--tool NAME\|JSON ...] [--material M] [--machine grbl\|linuxcnc\|fanuc\|haas\|marlin] [--set k=v ...] [--units mm\|inch] [--wcs G54] [--include] [--cell MM] [--out FILE]` | CNC, 3-axis: plan the operations, write the G-code for a controller, read it back and run it on a stock model: gouge, leftover, collisions and cycle time, measured against the design. Simulated, not proven on a machine. `form cam materials` and `form cam posts` list the speeds table with its source and the controllers ([CAM.md](CAM.md)) |
| `form board import FILE [--project P] [--step S] [--kicad-step] [--heights JSON] [--connectors JSON] [--regenerate]` | A KiCad `.kicad_pcb` or IDF `.emn`: without `--project` a new design, the enclosure made around the board; with it, the board replaces that design's board and the checks say what moved. `form board read FILE` prints the board model |
| `form board check <project> [--fit] [--board] [--fab jlcpcb] [--no-kicad]` | The board against the enclosure on the solids; KiCad's own DRC and ERC when kicad-cli is installed; the fabs' published limits with page and date |
| `form board fab <project> [--kinds gerbers,drill,pos,bom,step]` / `form board kicad` | Fab files through your KiCad; whether kicad-cli is installed |
| `form tree <project> [suppress\|restore FEATURE \| move FEATURE --after\|--before F \| rename FEATURE --label L [--id I]] [--preview]` | The feature tree: build order, suppressed, what each feature reads; each action one revision of the code, refused with the reason |
| `form tree <project> --upto FEATURE [--png FILE]` | The part as it stood after one feature, from the checkpoints (never saved); also `form render <project> --upto FEATURE` |
| `form model <project> fillet\|chamfer --at x,y,z [--at ...] --radius R\|--length L` | A fillet or chamfer on the edges nearest the points, written as one feature with its parameter |
| `form model <project> hole --at x,y,z [--standard clearance\|tapped\|iso286\|plain] [--size M3] [--fit H7 --nominal 8] [--style counterbore\|countersink] [--depth 0]` | A hole into the face at the point; sizes from ISO 273, the tap drill table or ISO 286, with their source |
| `form model <project> extrude\|cut\|revolve --sketch F.json [--at x,y,z] [--depth D] [--axis-entity N]` | A feature from a sketch, on a datum plane or the face at the point |
| `form sketch <project> FEATURE [--ops JSON\|-] [--set NAME=VALUE] [--preview]` | A feature's sketch solved (degrees of freedom, dimensions), or changed by `edit_sketch` ops |
| `form sketch --new NAME --file F.json [--depth D]` | A new design whose first feature is the sketch extruded |
| `form model <project> pattern --of FEATURE [--mode linear --axis x --count 3 --pitch 12 \| --mode polar --axis z --count 6]` and `shell --thickness T [--at x,y,z]` | A pattern of one feature; a shell open at the picked face. `--preview` builds and reports without saving |
| `form parts search QUERY` / `families` / `describe SPEC [--step]` / `din DESIGNATION` | Standard parts from published tables (local, nothing sent): candidates with their designations; a part's dimensions with their sources, its mating cut and material; `--step` builds it, measures it on the B-rep, gives its mass with the evidence and writes a STEP. SPEC is JSON or `family:size` |
| `form parts place <project> --spec SPEC --at x,y,z [--normal x,y,z] [--depth MM] [--qty N] [--no-cut] [--no-snap]` | Place a standard part on a hole or a flat face: snaps, cuts its clearance hole, counterbore, pocket or seat into the design as a feature (a new revision), records it as purchased and checks its fit; `parts snap\|list\|fit\|remove <project>` |
| `form bom <project> [--csv FILE] [--pdf FILE] [--no-made]` | The parts list: purchased items by standard designation with quantity, material, mass (with its evidence) and supplier numbers; the made parts with their mass. `bom supplier add\|remove <project> DESIGNATION --supplier S --part-number N [--url URL]`; `bom catalogue [QUERY] [--confirm]` (off by default) |
| `form diff <project> A [B] [--png FILE]` | What changed between two revisions on the solids: material added and removed, with volumes and regions |
| `form import-reference <project> FILE [--name N]` | Keep a part, mesh, scan or zip of them as a reference of the design: copied, measured in the kernel (box and volume, computed) and drawn in blueprint; a design reads it with `self.reference(name)`. STEP, IGES, BREP and every mesh and point cloud format; a zip imports each part in it. MCP `import_reference` |
| `form reconstruct FILE [FILE ...] [--name N] [--tolerance MM] [--layer 0\|1\|2] [--budget S] [--route auto\|parametric\|surface_body\|mesh_body] [--units auto\|mm\|cm\|m\|in] [--scale K]` | A mesh or scan (any format `form formats` lists; a zip of meshes makes one design with a part each) as a new design, by the route its triage chooses: parametric CAD (the exact solid, analytic faces (beta) and a feature recipe (beta), each compared with the mesh), a surface body for a smooth sculpt, or a mesh body for a scan. `--route` forces one; `--units` says what the file's numbers are (a size that makes no sense in millimetres is asked about). Several files of one product: one design with one part per mesh |
| `form analyze-reference <project> <mesh> [--tolerance MM] [--levels JSON]` | An imported mesh read like an engineer: dimensioned sections (pictures and outlines), features with sizes, symmetry, walls |
| `form analyze-assembly <project> FIXED OTHER... [--fixed P] [--near MM]` | How imported meshes go together and move: mating surfaces, clearances, slide and turn ranges, couplings |
| `form compare-reference <project> <mesh> [--part P] [--tolerance MM] [--rev N] [--png FILE]` | The design, or one part, against an imported mesh: Hausdorff, worst regions by place, per-feature differences |

## Print

| Command | Does |
|---|---|
| `form printers` | Every printer set up in every installed slicer |
| `form printers options KIND NAME` | A printer's filaments and processes |
| `form printers use KIND NAME [--filament F] [--process P] (--project ID \| --default)` | Use a printer for one design or as the default |
| `form printers clear (--project ID \| --default)` | Forget a design's printer, or the default |
| `form plates <project> [--orient PART=O] [--material PART=M] [--color PART=#hex]` | How the design's parts go onto plates, and per-part print settings |
| `form material <project> <PLA\|PETG\|ABS\|ASA\|TPU\|... \| "">` | The filament the slice uses |
| `form design-only <project> on\|off` | Slice this design or not |
| `form simulate <project> [--png PNG --layer N] [--gif GIF] [--frames DIR] [--layers a:b]` | Pictures of the toolpaths building up, from the slicer's G-code |
| `form cost <project> [--price-per-kg] [--kwh-price] [--watts] [--machine-rate] [--copies] [--save]` | Filament, electricity and machine time |
| `form cost <project> --process fdm\|sla\|sls\|mjf\|lpbf\|cnc\|injection\|sheet_metal\|purchased [--qty 1,100,1000] [--option injection.cavities=2] [--rate ID=VALUE] [--shop S] [--currency C] [--full]` | A cost per process from the design's drivers: fixed and per-part lines, each with its formula and evidence, and the cost per part at each quantity (docs/COST.md) |
| `form cost compare <project> [--processes fdm,cnc,injection] [--qty ...]` | Cost per part against quantity across processes, the cheapest at each quantity, where it switches and every crossover |
| `form cost rates [--shop S] [--label L] [--rate ID=VALUE] [--currency EUR] [--fx USD=1.1] [--part-price D=X] [--use] [--delete] [--full]` | The rates table with sources, and your shops' own rates (specified) |
| `form pack <project> [--copies N] [--spacing MM] [--no-rotate]` | Do N copies fit on one plate |
| `form optimize <project> --vary key:min:max ... --minimize\|--maximize METRIC [--require EXPR] [--budget N] [--study ID]` | Goal seek over parameters. `--require "fea.safety_factor>=2"` keeps a strength study as a constraint, solved on real candidates within 8 solves |
| `form optimize pareto <project> --minimize METRIC ... [--maximize METRIC] [--require EXPR] [--vary key:min:max] [--solves N] [--seconds S]` | Inverse design: the variants that meet the requirements, on a Pareto front. Every reported variant is built by the kernel and, for a strength metric, solved by the study; the budget used is stated. `--show` reads the stored search, `--save INDEX[:NAME]` keeps a point as a variant, `--verify` runs the search on ZDT1 and ZDT2. [OPTIMISATION.md](OPTIMISATION.md) |
| `form optimize topology <project> [--volfrac F \| --mass G \| --safety-factor SF] [--pull z] [--h MM] [--rmin MM] [--mode pockets\|free]` | Topology optimisation written back as features: SIMP on the strength study's mesh, the result rebuilt as lightening pockets with parameters and studied again. `--show [--frames]` reads the stored run, `--apply [--as-new NAME] [--mesh-body]` keeps it, `--verify` runs the MBB benchmark. [OPTIMISATION.md](OPTIMISATION.md) |
| `form slicer-open <project> [--printer ID] [--explain] [--no-open]` | Choose settings for this part on this printer (orientation, layer height, walls, top and bottom layers, infill, supports, brim, seam, filament, speed profile; each with its reason, computed or heuristic), slice it for real, write a project 3MF with those settings and open it in the slicer. `--explain` leads the JSON with one line per decision; `--no-open` writes the file only |
| `form compare-printers <project> [--printer ID] [--limit N]` | Slice the design for real on every printer in your slicers: time, filament and cost side by side |
| `form lighter <project> [--builds N] [--apply ID] [--require "fea.safety_factor>=2"] [--study ID]` | Lighter versions that keep every passing check passing: thinner walls, bigger pockets, less infill, each with its mass and the slicer's grams; `--apply` commits one |
| `form verify <project> <release>` | Re-hash a release against its manifest |
| `form release-files <project> [release] [--out FILE.zip]` | Every file of a release in one .zip: models, G-code, sliced 3MF, report, documents and manifest (the newest release by default) |
| `form instructions <project> [--rev N] [--out FILE.pdf]` | Assembly instructions as a PDF: a parts page, then one page per part in the order the assembly attaches them |
| `form drawing <project> [--sheet A3] [--projection first\|third] [--no-prove] [--out FILE.pdf]` | The engineering drawing from the solid: PDF, SVG, DXF, previews and the sheet scene, with the report (bindings, completeness, overlaps) |
| `form drawing pmi <project> [--out FILE.step]` | STEP AP242 with semantic PMI on the faces, read back and compared annotation by annotation |
| `form drawing check <project> <file> [--rows JSON]` | Check a person's drawing (PDF, DXF or image with the agent's rows) against the part, one row per dimension |
| `form drawing spec <project> '<json>'` | Declare datums, GD&T, fits, surface texture, general tolerance and notes for the drawing |
| `form drawing set <project> <dimension id> <value> [--expect-head N]` | Change a dimension: commits its parameter |

## Benchmarks

Results are kept in `docs/benchmarks/` and published as [BENCHMARKS.md](BENCHMARKS.md) and the site's benchmarks page.
Every command prints JSON.

| Command | Does |
|---|---|
| `form bench list` | The own suites (strength, calculators, ISO 286, manufacturability rules, mesh to CAD) with their saved results, and Parametric CAD Bench v3 with its runs |
| `form bench run [--suite S ...] [--skip S] [--source DIR] [--commit SHA] [--branch B] [--save]` | Run suites, each in its own process with a data folder of its own, on this checkout or another source tree; `--save` merges the rows into `docs/benchmarks/suites.json`. Exit 1 when a row fails |
| `form bench publish` | Write `docs/BENCHMARKS.md` and `site/benchmarks.html` from the saved results, every row with its commit, machine and date |
| `form bench cadbench --download DIR` | Fetch the pinned Parametric CAD Bench v3 task set with Harbor (`harbor download`) |
| `form bench cadbench --tasks DIR --agent claude-code --model M [--effort E] [--task ID ...] [--limit N] [--budget-usd 10] [--out DIR] [--no-publish]` | Each task's prompt to the agent with Form Studio's MCP server attached, scored by the task's own verifier in Docker; saves the run and publishes. `--agent standin` is the deterministic stand-in (no model) that proves the plumbing |
| `form bench oracle --tasks DIR [--task ID ...]` | Score each task's held-back reference through the harness: the scorer parity check, every reward 1.0 |

## Any MCP tool

| Command | Does |
|---|---|
| `form tool` | Every MCP tool with a one-line summary |
| `form tool NAME '{"key": value}'` | Call any MCP tool headless, with the same arguments, checks and refusals as over MCP ([MCP reference](MCP.md)); `-` reads the JSON from stdin |

## Agents

| Command | Does |
|---|---|
| `form chat "message" [--project ID] [--conversation ID] [--agent ID] [--model X] [--effort L] [--json]` | Send one message to an agent, with Form Studio's tools |
| `form conversations list [--project ID] [--involving ID] \| show ID \| rename ID TITLE \| pin ID \| delete ID` | Saved conversations; `--involving` lists every conversation that made or touched a design |
| `form conversations designs ID` | The designs a conversation made or touched, in order, with role (made, concept, continued) and state (live, trashed, gone) |
| `form conversations migrate [--dry-run] [--no-families]` | Rebuild the design list of older conversations from their events, tidy empty ones away, and join each request's designs into one family (the app does this once on its own) |
| `form export-conversation <id> [--format md\|json] [--out FILE]` | One conversation as Markdown (to read) or JSON (to import again) |

`form chat` asks the agent's questions in the terminal, and takes `--attach FILE` for files.

## Recipes

Recipes are internal building blocks that agents may start a design from; they are not offered to people as a library.
Installing one never runs it: the code runs only when a design is created from it.

| Command | Does |
|---|---|
| `form recipes [list] [--q WORDS] [--section builtin\|mine] [--tag T] [--sort name\|recent]` | Built-in recipes and the ones installed on this computer |
| `form recipes inspect FILE` | What installing a file would install: its SHA-256, title and any problems |
| `form recipes install FILE --sha256 HEX` | Install exactly that file, by its hash |
| `form recipes uninstall ID` | Remove an installed recipe |
| `form recipes export ID [--out FILE] [--author NAME] [--tags a,b]` | One `.formrecipe` file: the code, `meta.json` with its SHA-256, and a preview from a real build |
| `form recipes import FILE.formrecipe [--sha256 HEX]` | Shows the code's checksum; with `--sha256`, installs it |
| `form recipes derive PROJECT [--title T] [--summary S] [--range key=min:max ...] [--install --sha256 HEX]` | Turn a design into a recipe whose defaults are the design's values |

Release approval has no command. It is a deliberate action in the app's Release stage.
