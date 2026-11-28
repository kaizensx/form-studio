# Changelog

## Unreleased

### Added

- **A reply ends in Sources, built from the tool log** (direction I, wave O). Every tool call of a turn whose result
  says how its content is known is one numbered row with its evidence word: SIMULATED, COMPUTED, SPECIFIED, OPENED,
  MEASURED or ASSUMED. The word is the result's own `evidence`; a document or link that was read is OPENED, a
  measurement you answered is MEASURED. A call that failed, or whose result names no class, is not a source
  (`form/cite.py`). A number in the reply carries a source's index only when that exact number stands in that
  source's result. Nothing is taken from what the model says about itself.
- **The plan card.** When the agent plans a design (`plan_design`), its steps are a numbered card in the conversation.
  If it then asks for approval, the question is answered on the card: Approve, Edit (your words go back as the
  answer) or its other choice. A plan nobody was asked about is shown as the plan; the card says "approved by you"
  only after you answered.
- **By hand since the last reply.** Edits you make by hand between two replies are one note in the conversation, and
  the agent reads the same list with your next message, with the revisions.
- **Saved prompts.** The bookmark on a message of yours keeps it as a command; the palette lists it under *Saved
  prompts* and sends it again.
- **Commands on the selection.** With something picked on the part, the prompt starts with what it is ("On 2 edges")
  and the message goes with the selection's numbers.
- **Reduce motion** in Settings › General: movement becomes a short fade, at once. The system's setting turns it on too.

### Changed

- **The live line in the conversation** names what the agent is doing in the design's words, the tool and the step
  ("Running the strength study · strength_study · step 3"), or the feature a build is on. The Designing screen uses
  the same words.
- **The palette** has the prompt's lit well, the open design as its scope, group names in grey capitals and one lit
  row. Revision cards share the look of the Sources and plan cards.
- **A still window redraws less**: the room's light is stepped five times in two seconds, not five times a second.
- Design cards on Home no longer carry an index number.
- **The tool dock follows the mode, and a sketch is drawn on the part** (direction I). Select, Measure, Section and
  Annotate are always in the dock and never move; under a thin rule stand the tools of the mode: Design has Sketch,
  Extrude, Cut, Revolve, Fillet, Chamfer, Hole, Pattern, Shell and Part here; Check has Analyze, Centre of mass,
  Assembly and History; Make has Simulate the print, Print layout, Game asset and Photo render; Document has Views,
  the overall dimensions, Frame and Photo render. The group cross-fades in 180 ms when the mode changes. The active
  tool's options are one capsule at the head of the stage, always in the same place. Each mode's tools have keys that
  answer in that mode (Design: S, then Shift with the tool's letter; Hole is Shift+O).
  **Sketch** no longer opens a sheet: click a flat face or choose a plane, the camera turns to look straight at it,
  and the profile is drawn on that plane in the 3D view. Lines, arcs, circles and rectangles snap to points,
  midpoints, the face's corners and a grid; constraints show as small symbols; a dimension is typed in place; the
  capsule counts the degrees of freedom left and offers what can be said about the selection (coincident, midpoint,
  symmetric, tangent, equal, angle and distance dimensions among them, which the sheet never showed). Extrude, Cut or
  Revolve at the foot of the stage shows the kernel's preview on the part with its change in volume before anything
  is saved. Start blank › Model it by hand draws the first profile the same way, on a plane of the empty floor. The
  sheet remains as the fallback where there is no 3D view. Nothing changed for agents: `get_sketch`, `edit_sketch`
  and `add_feature` are the same routes the window uses; `/sketch/solve` now also returns the closed loops as points.
  Not done: the part is not ghosted behind the sketch and does not hide the lines it should cover; a face is not lit
  under the pointer before it is picked; Revolve has no dashed outline, only the kernel's preview.

- **The right pane is the Bench's chapter for the mode, in one row grammar** (direction I, second part). Check lists
  the studies, Make the routes, Document the documents, and every row reads the same: a state mark, the name, the
  number, and the word that says how it is known. A row without a number says its state in its place (*not run*,
  *describes r02*, *cannot run yet*). A clicked row opens **under the list**: what it found, what you get, what it
  needs, the exact request Run makes, and the buttons. The two row styles that shared a pane are one
  (`BenchRow.qml`), and the hand-written rows of Document that repeated the engine's entries are gone: every
  document is the engine's own entry (`form/studies.py`). Fit is the engine's *Fit under uncertainty* row.
- **The Bench opens as a sheet: Ctrl/⌘ B.** All four chapters as columns over the stage, with filters by state, a
  find field (`/`) and the selected row's request at the foot. Each entry now says which chapter it is in
  (`chapter` in `list_studies`): the features, the requirements, the materials and *Make it lighter* are Design;
  the slice, the print simulation and CNC are Make, with the routes.
- **The tree shows each feature's value and who made it**, in place of its role word, and a selected feature opens
  under the tree, which stays. **Values | Source** puts the design's code under the tree with the open feature's
  lines lit (`GET /tree` returns the source, each feature's lines and the first revision that built it). The
  feature the rollback bar passes lights once on the part.
- **The palette ranks by how close a match is**: the exact name, then a name that starts with the words, then a word
  the place also answers to, then a word inside the name, then the hint. *check* lights the Check mode, *review*
  still finds it, *checks* the Checks study. No query was removed.
- **Four modes: Design, Check, Make, Document** (design direction I, `docs/design/directions/i/IA.md`; the first
  part of it). The five stages at the top of a design are four modes, each with its one line of state. **Describe
  is the Overview**: click the design's name in the top left (Ctrl/⌘ I) and a sheet opens over the stage with the
  brief, the purpose, what is known and measured, the references and the revisions; the conversation stays.
  **Fit is a study in Check**: a row with its yield and the word *modelled*, which opens the fit model in place.
  **Document** is new and honest about what exists: assembly instructions, the report of a release, the share
  card, the turntable and the photo render are rows; the drawing sheet says it is not built yet. Ctrl/⌘ 1 to 4 are
  Design, Check, Make and Document. The engine's ids (`shape`, `prove`, `release`, and `brief` and `fit`) still work
  from the CLI, MCP, `--stage` and the palette, where the old names still find each place.
- **A view cube and a shading chip at the stage's top right** replace the row of view buttons at the foot. A face of
  the cube is a view (top, front, side), its rim is Iso, a double click looks from under; keys 1 to 5 are unchanged.
  The chip under it holds the build plate of a design made for printing, the floor grid and the overall dimensions.
- **A result's legend is a strip under the part.** While a map is shown on the part (wall thickness, overhang,
  section area, small features) one strip under it carries the scale in the map's own colours, how the result is
  known (computed, at which tessellation) and what it does not tell. It replaces the legend panel in the right
  column.
- **The printer is named in Make only**, for a design made for printing: it is a property of the print route.
- **Nothing is set smaller than 11 px.** Evidence tags, list numbers and file keys that were 9 to 10 px are 11 px;
  the window's margin is 20 px and the right pane 332 px wide, as the direction sets them.

### New

- **A board designed here: schematic, placement and routing on KiCad's files** (wave K2, `form/board/`,
  [docs/BOARDS.md](docs/BOARDS.md)). **`board_schematic`**, **`board_place`**, **`board_route`** (MCP, 145 tools) and
  **`form board schematic|place|route|copper`** (terminal, JSON). All of it is Form Studio's own code.
  - *Schematic.* `.kicad_sch` read and written back atom for atom; the netlist (wires, junctions, labels, power
    symbols; this sheet only); operations an agent sends (place a symbol from the KiCad libraries on this computer,
    join pins, label, annotate), all or nothing; a new board from the netlist with footprints from the person's
    libraries. **Form Studio's ERC is a subset and says so** (open pins, power inputs nothing drives, inputs nothing
    drives, outputs that fight, dangling labels, references); KiCad's own ERC runs beside it when kicad-cli is
    installed.
  - *Placement.* Force-directed, then every constraint made exact: connectors stay on their wall openings, the
    standoff and screw head at each mounting hole are keep-outs, a part must fit under the lid (less under its lip)
    and under the board, the board's keep-outs and outline. A part with no legal place is reported and left alone.
  - *Routing.* A grid maze router (A\*, Lee's wavefront on small grids) on two layers with vias, rip-up and reroute,
    PathFinder negotiated congestion, and a pull-tight pass to straight and 45° tracks; widths, clearances and via
    sizes from the net classes in the `.kicad_pro`. Real segments and vias in the `.kicad_pcb`. A net that cannot be
    finished is reported with the pad it could not reach.
  - *Checked, and by whom.* Every routed board is read back from the file and measured by **Form Studio's own
    geometric check** (closed-form gaps between copper shapes; labelled, with what it does not look at), and by
    **KiCad's DRC when kicad-cli is installed**; without KiCad the result says KiCad did not run.
  - *Freerouting, opt-in.* Your own Freerouting (a separate GPL-3.0 program; off until you install it and switch it
    on) through a Specctra `.dsn` and `.ses`. None of its code is in Form Studio and it is never downloaded.
  - The Bench: **Board copper**, **Board placement**, **Schematic checks**. In a design, the board's own copy is
    changed and the version before is kept in `board/history/`; a file outside a design is never written over.
  - Not yet verified against KiCad or Freerouting themselves on a machine that has them (see docs/BOARDS.md).
- **FreeCAD PartDesign export with editable history.** **`freecad_partdesign`** (MCP, 142 tools) and **`form export
  fcstd <project> [--out f.FCStd] [--edit key=value]`** (terminal, JSON) write the design as a native PartDesign
  Body, not a baked solid: sketches with Sketcher constraints and named dimensions, Pad, Pocket, Revolution, Groove,
  Fillet and Chamfer on the edges they were picked on, Hole (ISO size and fit when FreeCAD's table gives the same
  diameter), LinearPattern, PolarPattern, and Thickness for a shell. A "Params" spreadsheet holds every parameter and
  the feature sizes are expressions on its cells, so editing a cell in FreeCAD edits the model as the parameter does
  in Form Studio. Free code is decomposed where it is a prism (a sketch of its cap and a Pad or Pocket, sizes not bound
  to the parameters); what is not recognised goes in as a frozen solid, and the report lists those features as
  non-parametric. FreeCAD's command line builds the file, recomputes it and checks every feature against Form
  Studio's solid (symmetric difference per feature; volume, bounding box and face count of the result): only a
  feature that recomputes to that solid is reported editable. Measured with FreeCAD 1.1.4: a bracket made by hand
  (sketch, pad, ISO 273 holes, counterbore, fillet, chamfer, linear pattern), a revolve, and a tray (shell, cut, polar
  pattern) come back fully native at 0 % volume deviation, equal face counts, and a width edited in the spreadsheet
  gives exactly Form Studio's solid at that width; all 14 built-in building blocks come back at volume parity
  (≤ 0.00005 %, bounding box exact), their free-code stages decomposed (24 stages) or frozen (32, parts included), with
  equal face counts on 12 of 14 (gridfinity_bin 134 in Form Studio against 135 in FreeCAD, battery_holder 74 against
  86; the same solid, cut into more faces).
  Designs of several solids are one frozen Body per part. FreeCAD's topological naming is still fragile: a fillet,
  chamfer or thickness names edges and faces of the solid before it, found by geometry on FreeCAD's own solid, and an
  edit that changes the topology before it can move or break it. The export writes element names in full (the
  document's string hasher off): with the hasher, FreeCAD 1.1.4 lost a scripted fillet's edges on the first edit.
  Parametric CAD Bench runs now write their answer with this export (answer.FCStd and the answer.py that made it);
  the agent's own FreeCAD script stays the fallback.
- **Fixed: a sketch with a construction line could not build.** The sketch literal in the design's source was JSON
  (`"construction": true`); it is Python now (`True`), so a revolve about a construction line builds.
- **Benchmarks in public.** `form bench list|run|publish` runs Form Studio's own verification suites and publishes
  every row, failures included, with the commit, machine and date: strength studies against textbook and NAFEMS cases,
  calculators against published worked examples, ISO 286 limits against the ISO 286-2 tables, every manufacturability
  rule probed on both sides of its threshold, and mesh to editable CAD against tolerance. The results are
  `docs/BENCHMARKS.md` and the site's benchmarks page; the Benchmark suites workflow regenerates them on dev, so they
  are never edited by hand. **`form bench cadbench`** runs Parametric CAD Bench v3 (100 public FreeCAD tasks,
  Apache-2.0) through Form Studio: each task's prompt to the agent with Form Studio's MCP server attached, in a data
  folder of its own, scored by the task's own verifier image with no network; `form bench oracle` checks that a
  task's reference scores 1.0 through the same path. The stand-in agent proves the plumbing; the score is pending a
  run with a real model.
- **Print physics.** Three tools for a printed part, each number saying how it is known.
  **Orientation** is a search over several objectives at once, and the answer is the Pareto front: the orientations
  no other one beats on everything. Support volume and support contact are computed from the facets that overhang
  past the critical angle, each support column going down to the plate or to the part below; print time comes from a
  layer-time model that reads the slicer preset and is calibrated on a real slice when you ask, with the factor
  stated; strength comes from a strength study's stress field against the filament datasheet's Z and X-Y strengths;
  stair height is computed on the faces you mark cosmetic; and the tilt at which the part tips is computed from its
  centre of mass over the plate contact. The search covers the six axis orientations, every flat face the part can
  lie on and a geodesic grid of 162 directions, then refines to 1 degree. You pick; the pick is written to the print
  setup. `verify=N` slices the best candidates with the real slicer and reports the model's error in time and in
  support filament.
  **Strength as printed** is a strength study with a layered (transversely isotropic) material turned to the print
  orientation: the safety factor across the layers with its own stated error, the in-plane one, and how both change
  with the orientation. In-plane and Z moduli and strengths are the datasheet's; what no source gives is given by you
  or assumed by a stated rule, and every assumed value is listed. Verified against Lekhnitskii's off-axis modulus and
  a Timoshenko beam in three build directions (errors 0.00 to 0.28 %).
  **Warp risk** is a first-order indicator from the layer-shrinkage model of Wang, Xi and Jin (2007), with the
  material's thermal expansion and glass transition from named documents, the first layer, the longest span, the
  height and the corners. It is an indicator, never a predicted lift. [docs/PRINT_PHYSICS.md](docs/PRINT_PHYSICS.md).
- **`print_orient`, `print_strength`, `print_warp`** (MCP) and **`form print orient|strength|warp <project>`**
  (terminal, JSON). Bench entries in Check (Orientation front, Strength as printed, Warp risk) and in Make (Print
  orientation: the setup's orientation, and whether it is on the front). 142 MCP tools.
- A strength study's field data now carries the stress tensor at the surface nodes (`stress`, six components), and
  for a layered study the tension across the layers and the shear between them.
- **Engineering drawings from the solid.** A shop drawing of any design on A4 to A0 or ANSI A to E: the views
  projected by OCCT's hidden-line removal on the B-rep (first or third angle, ISO 5456-2), a full section through the
  bores with hatching and its cutting plane, a detail view of a chamfer too small to read at the sheet's scale, an
  isometric, the largest ISO 5455 scale that fits, an ISO 5457 border and an ISO 7200 title block that leaves a field
  empty when Form Studio does not know it. Vector PDF (drawn by Qt, fonts embedded), SVG and DXF, plus paper and night
  previews; the sheet itself is a scene graph (`sheet.json`) for the direction-I sheet pane to draw.
- **A dimension is its parameter.** Sizes are measured on the B-rep and each size parameter is bound to the one it
  equals, proved by building the design again with the parameter nudged. The drawing says "5 of 7 size parameters
  dimensioned, 0 twice", lists each parameter it cannot show with the sizes it drives, and changing a dimension
  commits a new value for its parameter. Placement is a layout algorithm: linear dimensions packed into tiers
  (baseline nests, chain shares a line, ISO 129-1), leaders and frames searched for free space, and every sheet is
  checked for overlaps.
- **Fits, general tolerances, GD&T and surface texture.** ISO 286 limits computed from the standard's formulas (IT5
  to IT11, deviations d to u, the delta rule for K to U holes) and checked cell by cell against the published
  tables; the few cells where the standard's own table differs from its formula are listed and say so. ISO 2768
  general tolerances, ISO 1101 feature control frames, ISO 5459 datums and ISO 21920-1 surface symbols, drawn only
  where the design (a `drawing()` method) or the person declares them, and refused when the declaration breaks the
  standard (a datum on a flatness, perpendicularity without one).
- **STEP AP242 with semantic PMI.** Dimensions with their limits, datums and geometric tolerances attached to the
  solid's faces through OCCT's XCAF document, then the file is read back and compared annotation by annotation:
  14 of 14 on the bearing flange.
- **Check against a drawing.** A person's drawing (PDF, DXF or an image) checked dimension by dimension against the
  part: expected and measured, the tolerance it was judged by, PASS, FAIL or UNSURE, a crop of the sheet and a render
  with the measured feature lit. A PDF's text layer and DXF entities are read exactly; an image is read by the agent,
  row by row with its place on the sheet, and anything it is unsure of stays UNSURE. Form Studio runs no OCR.
- MCP tools `drawing`, `export_pmi` and `check_drawing` (142 tools); `form drawing <project> [--sheet A3]
  [--projection first] [--out part.pdf]`, `form drawing pmi|check|spec|set ...`; a Drawing section with "Drawing,
  A3", "STEP with PMI" in the app's documents.
- **Inverse design.** Say what the part must do ("hold 60 N with a safety factor of 3, as light and as stiff as
  possible") and get the variants of the design that do it, on a Pareto front. The search runs over the design's own
  parameters with Gaussian-process surrogates, NSGA-II and hypervolume infill, and the surrogate only chooses what
  to try next: every reported variant was built by the kernel and solved by the strength study, the safety factor
  that counts is the lower one, and candidates that failed or missed a requirement are shown with the reason. The
  result states the solves, builds and seconds used and that the front is approximate. Any point is saved as a named
  variant. Objectives and requirements: mass from the material's sourced density, safety factor, stress,
  displacement, first natural frequency, support area, wall thickness, and cost when a price is given (no rate is
  made up). Checked on ZDT1 and ZDT2 against their known fronts.
- **Topology optimisation written back as features.** SIMP (density filter, optimality criteria) on the strength
  study's own mesh finds where material carries the load; the faces that carry supports and loads stay solid. The
  density field is then rebuilt as CAD: threshold, outlines, ribs measured, and one named feature per lightening
  pocket, with three parameters (rib inset, corner radius, web thickness). The rebuilt design is built by the kernel
  and its strength study is solved again with the refining solver; the result sets its safety factor, displacement
  and mass beside the density field's own numbers and beside the solid part. On the test arm: 42 % lighter, safety
  factor 2.53 (at least 2.46) against 2.37 read from the density field. A target can be a volume fraction, a mass or
  a safety factor. When the features cannot be fitted or built, the run says why and offers the smoothed dense
  region as a mesh body, labelled as one. SIMP reproduces the published compliance of the MBB beam (Andreassen et
  al. 2011) to 0.002 %. [docs/OPTIMISATION.md](docs/OPTIMISATION.md).
- **`inverse_design`, `get_inverse_design`, `topology_optimise`, `get_topology`, `apply_topology`** (MCP) and
  **`form optimize pareto`**, **`form optimize topology`** (terminal, JSON), with the Bench entries **Inverse
  design** and **Topology optimisation** in the Design chapter. Both run in the background with progress and cancel.
  The stored records hold the Pareto chart data and the density field of every iteration. 142 MCP tools.
- **Tolerance stack-up from the assembly.** Pick the two faces of a gap and Form Studio finds the loop itself: a
  graph search over the declared mates keeps those that hold the parts along the gap (a seat, or a radial fit whose
  clearance is a float), and each part on the path adds the distance between the faces the loop enters and leaves by.
  The links close to the measured gap exactly. Sensitivities come from finite differences on the rebuilt CAD, so
  angles count. Each tolerance names its source: the request, the drawing's ISO 286 fits, a measured parameter's
  sigma, the drawing's ISO 2768 class, the printer's calibration, or FDM ±0.2 mm and ISO 2768-m, both labelled
  assumed. Declared position and profile tolerances are converted by a stated rule. Results: worst case, RSS, a seeded
  Monte Carlo, Cpk and the share out of spec, a contribution chart, the gap over a temperature span from sourced
  expansion (never assumed), and what to tighten first, with cost hints labelled assumed. The result carries the
  loop's faces and segments for the viewport. [docs/TOLERANCES.md](docs/TOLERANCES.md).
- **`tolerance_stack`, `get_tolerance_stack`** (MCP), **`form stack run|add|list|show|rerun|rm`** (terminal, JSON), and
  the Bench entry **Tolerance stack-up** in Check, stale after any change. 142 MCP tools.
- **Engineering calculators that write the part.** Seven calculators size a part from what it has to do, by a named
  standard's equations, and write it as a design with parameters: snap joints (cantilever and annular, Bayer's
  snap-fit guide), living hinges (elastic by strain, or moulded PP and PE from cited practice), springs
  (compression, extension and torsion to EN 13906, with a printed-spring mode), bolted joints (VDI 2230 Part 1,
  simplified: size from the load, preload, tightening torque, thread stripping; bosses with heat-set inserts),
  involute gears (spur and helical with profile shift, internal pairs, rack and pinion; contact ratio, backlash, Lewis
  bending), plate cams from a motion law, and ISO 286 fits over a temperature span. Every number is labelled
  computed, specified or assumed, with its equation and its source; a material value with no source leaves its
  result out instead of being guessed. The calculation stays in the design and runs again on every revision. Checked
  against 72 published quantities; a snap hook is also checked by finite elements where the strength engine is
  installed. [docs/CALCULATORS.md](docs/CALCULATORS.md).
- **`calculate`** (MCP) and **`form calc <calculator> key=value ... [--build]`** (terminal, JSON), and the Bench
  entry **Engineering calculation**. 142 MCP tools.
- ISO 286 tables and published fastener dimensions moved to modules with no CAD kernel behind them
  (`form/iso286.py`, `form/hardware_tables.py`); `form.craft.fits` and `form.parts` read the same copy.
- **Cost per process, with sourced rates.** See what a design costs to make by FDM, resin (SLA), SLS, Multi Jet
  Fusion, metal (LPBF), 3-axis CNC, injection moulding or sheet metal, plus the parts you buy. Each estimate is built
  from the design's own drivers:
  - FDM uses the slicer's grams and hours.
  - CNC uses the current CAM simulation's cycle time and the setups manufacturability counts.
  - Moulding uses the projected area and thickest wall manufacturability measures.
  - Sheet metal uses the unfold's flat area, cut length and bends.
  - Purchased parts use the parts list, priced only where you gave a price.

  Without a slice or a CAM simulation the time is estimated and says so. Moulding follows Boothroyd, Dewhurst and
  Knight: the clamp force picks the machine, the cycle is fill plus cooling (h²/(π²α) · ln(4/π · (Ti − Tm)/(Tx − Tm)))
  plus resetting, and the mould is a mould base plus cavity hours. The model reproduces the book's worked numbers.

  Every rate is published, cited and dated, or it is a process parameter labelled assumed:
  - labour and electricity from Eurostat;
  - printer, material and powder prices from vendor pages;
  - LPBF and milling machine rates from a 2026 paper;
  - resin prices from PlasticPortal;
  - US dollars converted at the ECB reference rate.

  Money is never assumed. A line nobody has priced, such as an MJF machine hour or a press-brake hour, is left out of
  the total and says what to set. Each line shows its formula with the numbers filled in and the evidence of every
  input.

  You can compare cost per part against quantity across processes. The comparison shows the cheapest process at each
  quantity and where one process overtakes another, with the arithmetic, for example "Injection moulding costs less
  per part than FDM printing from about 628 parts". Your own rates, currency and exchange rates go in a shop, in
  Settings › Costs or with `form cost rates`. They are recorded as yours and replace the published ones.
  `costing.cost()` and `costing.objective()` give optimise and inverse design a cost per part.
  Inverse design takes it as the metric `cost.per_part` (`costing={"process", "quantity", "shop"}`; terminal
  `form optimize pareto --cost-process --cost-quantity`): each candidate is costed from its own volume and bounding
  box by FDM, SLA, SLS, MJF, LPBF or CNC, and the axis is labelled with the rates' evidence classes and the largest
  assumed share. Moulding and sheet metal need a check of each candidate's solid and are refused, not guessed.

  Available as `estimate_cost` (now with `process` and `quantities`; without them it is unchanged), `cost_compare`
  and `cost_rates` over MCP (142 tools), as `form cost <project> --process ...`, `form cost compare` and
  `form cost rates`, and as the Bench's **Cost per process** in Make. See docs/COST.md.
- **Sheet metal and cut parts.** Design a bent part from a base flange, edge flanges, hems, jogs, relief cuts
  (rectangular or obround) and louvres, each with its thickness and inside radius (`form.sheet.build.Sheet`). The
  part is unfolded on the exact solid: one skin walked across tangent edges, constant thickness checked face by
  face and by volume, each bend's allowance θ·(r + K·t) with a K-factor from a cited table (the generic air,
  bottoming and coining table, DIN 6935's formula, or your shop's value, recorded as specified). The flat is proved
  by folding it back from its own numbers onto the part (within 0.01 mm; on the test parts under 1e-13 mm), and an
  L-bracket and a U-channel match their analytic flat lengths. What cannot be unfolded is named with the face and
  why. The flat pattern DXF has cut, bend-up, bend-down (with angle, radius and K notes), etch (the label as
  outlines) and notes layers. A cut-file checker reads any DXF (layers by intent) for laser, waterjet or router:
  open contours, duplicates and overlaps, crossings, tiny segments, text not converted to outlines, the smallest
  hole or slot, hole to edge and to bend, inside corner radius, part size, each rule with the SendCutSend or
  Protolabs page it comes from, or marked unsourced. A bend order is searched with a stated V-die and gooseneck
  punch model and collisions are flagged. Any flat part exports as a clean profile with optional kerf
  compensation. A SendCutSend preflight checks material, thickness, bending and limits from their pages, read
  2026-11-28; nothing is uploaded or ordered. Manufacturability's `sheet_metal` process now judges bent parts
  (flange length, holes to edge and bend, hems). `flat_pattern`, `cut_file_check`, `bend_order`,
  `service_preflight` over MCP (142 tools), `form sheet`, three Bench entries, and docs/SHEET_METAL.md.
- **CNC, 3-axis: toolpaths with a stock simulation that measures gouge and leftover.** Plan the machining of a
  design on a mill or router: facing, adaptive clearing at constant engagement, finishing of floors and walls, the
  outline cut through with tabs, drilling with pecks, helical boring, chamfering, and 3D finishing in parallel
  passes and waterlines. Tools are flat, ball, bull-nose, drill and chamfer, each with its flute length, stick-out
  and holder. Speeds and feeds are chip load × flutes × RPM from a table that quotes its source (Harvey Tool's
  machining guidelines); plunge feeds, drills and materials no source covers are marked assumed. The G-code is
  written for Grbl, LinuxCNC, Fanuc, Haas or Marlin, then read back the way that controller reads it and run on a
  model of the stock with the tools' real shapes. You get the deepest gouge and where it is, the material left and
  where, rapid moves through stock, shank and holder collisions, and the cycle time under your machine's limits.
  Setups come from the manufacturability check when you ask for them. A program goes into a release only with a
  current simulation (a new revision, another tool or an edited file makes it stale), nothing assumed and your
  approval, and it is labelled "simulated, not proven on a machine" until you record what it did on one. The
  viewport's data (toolpaths by operation, the stock with gouge and leftover marked) is written beside it.
  `cam_plan`, `cam_post`, `cam_simulate` over MCP (142 tools), `form cam`, the Bench's "CNC, 3-axis", and
  docs/CAM.md.
- **Manufacturability, with fixes that are proved.** Check a design for CNC milling (3, 4 or 5 axes), injection
  moulding, or FDM, resin (SLA), SLS, MJF and metal (LPBF) printing. Every rule is measured on the exact solid and
  every limit names the guide it was read from and the date (Protolabs, Protolabs Network, Formlabs, Materialise,
  RJG), or says it is geometry. Moulding proposes the pull direction and the parting line, finds undercuts and says
  which need a side action or a lifter, checks draft per face and estimates clamp tonnage with its range; CNC finds
  what a cutter of your diameter cannot reach, the setups needed, internal corners against the tool and the cavity
  depth, tool reach and holes. Problems are drawn on the part. Draft, internal corners, escape holes and walls or
  holes set by a parameter can be fixed: the fix is written into the design as a parameter and a feature, checked
  before it is saved, saved as a revision and checked again; it is called fixed only when that check passes. A rule
  that could not be checked is never a pass. `manufacturability` and `apply_fix` over MCP (142 tools), `form dfm`,
  and docs/MANUFACTURABILITY.md.
- **Test plan.** For any design, Form Studio writes what to measure on the made part, from what the design claims:
  one test for each requirement of the brief, each fit (an ISO 286 hole, an ISO 286 pair in the code, the fit window of
  a part that meets another, each mate of an assembly with its designed clearance), each critical dimension (the
  brief's and the interfaces', every measured or specified value, the overall size) and each load of a strength study.
  Each test names the instrument (its resolution a tenth of the tolerance band or finer), the limits and where they
  come from (a dimension the design gives no tolerance gets ISO 2768-1 m, and says so), how many readings, and when it
  passes. A critical dimension takes its limits from the drawing where it states them (an ISO 286 fit on the size, or
  the drawing's ISO 2768-1 class), and a load test quotes the strength study's converged displacement with its
  stated error. A PDF set in Geist with a checklist to fill in, Markdown, and the checklist as CSV. Document › **Test plan**
  on the Bench; `test_plan` (MCP); `form testplan`.
- **Results are measured, and only measured.** `record_physical_result(kind="test", test=..., values=[...])` or
  `form testplan record` (one test, or the filled checklist) keeps each reading with provenance "measured", the
  instrument, who measured it and the limits it was judged against.
- **Results report.** One document for the head revision: the design with its revision, geometry key, design-code
  and STEP SHA-256; every check and study with its evidence class and what it states about its error; the physical
  results against the test plan; the open items; and a verdict. PASS only when every required test is measured within
  its limits and nothing is open; anything unchecked is NOT A PASS; a measured failure is FAIL. The physical section
  holds only numbers a person measured. PDF and Markdown. Document › **Results report** on the Bench;
  `results_report` (MCP); `form report`.
- **Backups.** Every design and conversation (the reference leaves conversations out), on a schedule (hourly, daily
  or weekly) while Form Studio is open, to a folder you choose, and optionally pushed to a Git repository you created,
  with your own Git sign-in. Each backup is one .zip with the SHA-256 of every file; it is read back and checked after
  it is written, the oldest beyond the number you keep are removed (nothing else in the folder is touched), and a
  restore writes back the same bytes. Form Studio never creates a repository and refuses an address with a password
  in it. Settings › **Backups**; `backup` (MCP); `form backup`.
- **Recently deleted, 30 days.** A deleted design is listed with the days it has left and the backup that holds it,
  and comes back with its conversations attached. After 30 days it leaves only when a verified backup holds it.
  142 MCP tools.
- **The Bench.** Every study, route and document of a design in one listing: at the top of the Review pane the
  studies (checks, assembly and joints, requirements, analysis maps, fit, critique, slice, print simulation,
  orientation, every printer, cost, make it lighter), at the top of the Make pane the routes (exports, 3MF with
  colours, slicer project, FreeCAD macro, project archive, game asset, release) and the documents (parts list, assembly
  notes, motion checks, print report, measurement plan, instructions, four-view sheet, photoreal render, turntable,
  share card). Each line shows its state (current, stale with the revision it describes, never run, failed, running,
  or why it cannot run here), its headline number with its evidence, and runs on click; a current one opens what it
  made. States come from keys of the head revision's inputs, never set by hand. The command palette finds every
  entry.
- **`list_studies`, `run_study`, `get_study`** (MCP) and **`form study list|run|show <project> [id]`** (terminal): the
  same Bench, headless. 142 MCP tools. Mass & inertia, Materials & sources (each value with its document) and Features
  (built, suppressed by hand, left out with the reason) are Bench studies too; a change made by hand is a new
  revision, so every study of the revision before it shows stale. The command palette also finds the hand tools:
  Sketch on a plane, Fillet or chamfer, Hole, shell or sketch on a face, Feature tree.
- **Model by hand, in the same code the agent writes.** The Program pane is a feature tree you can work in: drag
  the rollback bar up to any feature and the part shows as it stood then, from the feature checkpoints (a few
  milliseconds; nothing is saved); a line's menu suppresses and restores it, renames it in place, moves it up or
  down, and says what it depends on (the parameters it reads, the features it names, what reads it); drag a line
  by its number to reorder. A move that would make a feature do nothing, or come before one it reads, is refused
  with the reason. Each action is one revision of the design's code, and the checks run again.
- **Fillet, chamfer, hole, pattern and shell on what you pick.** Pick edges in Annotate for a fillet or a chamfer,
  a flat face for a hole (ISO 273 clearance, tap drill, an ISO 286 fit such as H7, or a plain Ø; plain,
  counterbore or countersink, each size with its source) or a shell open there, or a feature in the Program for a
  linear or polar pattern. Preview builds it in the kernel and shows the draft over the head with the change in
  volume; Add to design writes one named feature method and its parameters. Edges and faces are kept as stable
  queries (the features that made them, their kind, direction and place), so a parameter change keeps them; a
  rebuild that cannot find one leaves the feature out and says which. Fix with your agent puts a refusal in the
  conversation.
- **Sketch, then extrude, cut or revolve.** Start blank → **Model it by hand** opens a sketch editor on a datum
  plane; in a design, **Sketch here…** puts it on a picked flat face (its outline drawn as a reference) and the tool
  dock's **Sketch** on a datum. Draw lines, rectangles and circles; lines drawn nearly level or upright snap
  horizontal or vertical; dimension a line or a circle and the solver (form.sketch2d) keeps it true, with the
  degrees of freedom left in mono. Every dimension is a parameter of the design, so changing one later re-solves the
  sketch. A sketch feature's line menu has **Edit sketch…**. The bracket from Start blank (an L profile, four
  dimensions, a 40 mm extrusion, an M4 hole, a 2 mm fillet) is a timed interface test.
- **Hand tools in the dock and in the conversation.** The tool dock has a group for Sketch, Fillet or chamfer and
  Hole, shell or sketch on a face. A pattern can take its direction from a picked edge (a straight edge: along it; a
  round one: around its axis). Every change made by hand appears in the open conversation as the same revision
  card an agent's change gets. Preview and Add to design stay pinned at the foot of the selection pane.
- **The same headless.** New MCP tools `get_sketch` and `edit_sketch` (ops on points, lines, circles, arcs,
  constraints and dimensions; refused when the sketch would not solve or close); `add_feature` kinds `extrude`,
  `cut` and `revolve` with a sketch; `form sketch`, `form model ... extrude|cut|revolve`. `edit_design` gains the ops `suppress`, `restore`, `move` and `rename`; `add_feature`
  the kinds `fillet`, `chamfer`, `hole`, `pattern` and `shell` (with `preview`); `render(upto=)` and
  `get_design_source`'s `tree`. In the terminal: `form tree <project>` (and `suppress|restore|move|rename`,
  `--upto`), `form model <project> fillet|chamfer|hole|pattern|shell`, `form render --upto`.
- **Mass properties from the B-rep.** Mass, centre of mass, inertia tensor and principal axes of every part and of
  the whole, computed by OCCT on the solid; an assembly at any pose of its joints. The grams on the size line show
  the centre of mass and the principal axes on the part with a glass readout (also in Analyze). MCP
  `mass_properties`, `form mass`. Checked against closed-form solids to 1e-6 relative.
- **A materials library with sources.** Density, stiffness, Poisson's ratio, strength, thermal values for 10 printing
  filaments (manufacturers' printed-specimen values in X-Y and Z) and 18 engineering metals, plastics and woods; every
  value names its document, URL and the line it was read from. A value no source gave says "unsourced". `form
  materials`. New engineering materials: alloy steel 4140, white oak, nylon PA6 (moulded).
- **Concept cards show mass and material.** `propose_concepts` takes a material per concept; a print concept without
  one is shown in PLA, marked assumed.
- **Standard parts, generated from the standards' tables.** ISO 4762 (and DIN 912) socket head, ISO 7380-1 button
  head and ISO 10642 countersunk screws, ISO 4032 nuts, ISO 7089 washers, CNC Kitchen heat-set inserts, ISO 15
  deep-groove bearings (60x, 62x, 6xx, 608), ISO 8734 dowels, DIN 705 A collars, ground shafts and THK LM6-12UU
  bushings, GT2 pulleys and belts, NEMA 17/23 motors, V-Slot 2020/2040 with T-nuts, NdFeB magnets by grade and
  ISO 3601-1 O-rings with their gland. Every dimension names its table or datasheet; sizes outside a table are
  refused; threads are cosmetic and say so. Designations as they are ordered ("ISO 4762 M5×12 A2-70").
- **Place a part by picking a hole or a face.** It snaps to the hole's axis or the face, measures the host's
  thickness, picks a screw's stock length, cuts the matching hole, counterbore, pocket, seat or motor mount into the
  design's source as a feature, enters the assembly as purchased, and is checked for fit on the B-rep (interference
  of the fitted part with the cut host, and the clearance per side from the tables). In the app: **Part here…** on a
  selection, the Bench's **Standard parts**, or the palette.
- **A buyable parts list.** Purchased items grouped by designation, with quantity, material and mass (catalogue value,
  else the B-rep volume times the sourced density, else none), and the made parts with their mass; CSV and a PDF
  page. Supplier numbers come only from you or a page at a link you give. An optional catalogue service is in
  Settings, off by default, and says before each search what is sent and to whom; no provider ships yet.
- **`standard_part`, `bom`** (MCP) and **`form parts …`, `form bom …`** (terminal). 142 MCP tools.
- **Motion studies.** A mechanism played over time from its own declaration: drivers (a ramp, keyframes, a speed or a
  sine), couplings (gears, rack and pinion, lead screw, belt, cam) and closed loops solved per frame by Newton's method
  on the loop-closure equations, so a four-bar moves as one. Frames a linkage cannot reach (beyond its Grashof limit)
  are reported, never posed. Points are traced with path, velocity and acceleration; every pair of parts that moves
  relative to another is checked at every frame, with the smallest gap, when it happens and the first contact; the
  holding torque under gravity of each driven joint comes from the parts' masses. An MP4 film of the motion (ffmpeg,
  no GIF). MCP `motion_study`, `animate(kind="motion")`, `form motion`. Verified against the closed-form four-bar
  (Freudenstein) to 1e-5°, and the non-Grashof case frame by frame.
- **More joints.** `cylindrical` (turns and slides on one axis) and `ball` joints; `Coupling`, `gears`, `rack`,
  `lead_screw`, `cam` and `Loop` in the assembly declaration.
- **Robot files.** URDF, SRDF and MJCF from the assembly: a link per part, joints with their limits, couplings as
  mimic and equality joints, loops as MJCF connects, inertia per link from the B-rep mass properties, visual meshes
  and collision as CoACD pieces or convex hulls. Health checks (positive-definite inertia, triangle inequality, mesh
  paths, unit axes, one tree, no self-collision at rest), then the files are loaded by yourdfpy and MuJoCo (a new
  optional engine, MuJoCo 4.0.1 and yourdfpy 0.0.60 in their own Python), or validated structurally and labelled so.
  MCP `robot_files`, `form urdf`, `form mjcf`.
- **Assembly sequence.** A feasible order and each part's straight insertion direction, by disassembly: local freedom
  from the contact normals, then a collision sweep. Threads unscrew along their mate axis. The exploded view and the
  assembly instructions follow it, so each arrow is a proved direction. A set that cannot come apart one at a time is
  reported, never ordered by guess. MCP `assembly_sequence`, `form sequence`.
- Bench entries Motion, Robot files and Assembly steps.
- **Boards and enclosures.** Bring a KiCad `.kicad_pcb` (read by Form Studio's own parser, no KiCad needed) or an
  IDF `.emn`, and get an enclosure made around it as editable features: corner lugs clear of the board, standoffs
  under its mounting holes with heat-set inserts, an opening for each connector sized from its plug's envelope and
  centred on its face, a lid with a lip printed beside the box, vents, and the inserts and screws in the parts list.
  The board is then checked against the enclosure on the solids: board to wall, a standoff under each hole, each
  plug swept out through its wall, every part of known height under the lid, a screwdriver's way to each board screw.
  Bring the board again after a change and the checks say what no longer lines up, with what moved. Heights come only
  from the board file, a board STEP or you; a part without one is "not checked".
- **Board checks with your own KiCad.** When `kicad-cli` is installed, KiCad's DRC and ERC run and are reported as
  KiCad's; when it is not, the result says so and KiCad is an opt-in engine in Settings (`form install kicad`). The
  board's track widths, spacing, drills, annular rings and size are checked against the published limits of JLCPCB,
  PCBWay and OSH Park, each quoted with its page and the date it was read.
- **Board fab files.** Gerbers, drill files, pick-and-place, BOM and the board STEP through your KiCad.
- **`board_import`, `board_check`, `board_fab`** (MCP), **`form board read|import|check|fab|kicad`** (terminal) and the
  Bench's **Board and enclosure**, **Board checks** and **Board fab files**. docs/BOARDS.md, with the plan for
  schematic capture and routing (K2). 142 MCP tools.

### Changed

- **One ISO 286 module** (`form/iso286.py`) for drawings, hand-made holes and the fit calculator: limits computed
  from the standard's formulas, the cells where its published table differs kept as the table says, and the printed
  tables kept as the reference every cell is checked against. Fits now cover deviations d to u and holes D to U.
- **A drawing's title block gives the material and the mass** from the B-rep volume and the sourced density, with
  the evidence; with no material both stay empty. A new material makes a new sheet.
- **The Bench lists every wave's entries:** strength, the engineering calculation, manufacturability, sheet metal,
  CNC, the drawing and STEP with PMI, standard parts and the parts list, motion, robot files and assembly steps,
  the board and its enclosure, beside mass, materials and features.
- The packaged app paints drawings and reads PDF drawings (its executable runs the Qt painter, and QtPdf ships), the
  MuJoCo check finds its code, and CAM's speeds table ships with the rule and bend tables.
- Filament and engineering densities are now the cited datasheet values (for example PETG 1.28, PA-CF 1.09, stainless
  304 8.00 g/cm³); woods keep the bd_materials catalogue density, labelled typical. "Oak" is red oak.
- **Strength studies with a stated error.** Pick the faces that are held and the faces that are loaded, and get
  stress, displacement and a safety factor against the material's yield; also natural frequencies (modal) and the
  load at which a slender part buckles. Supports are fixed, roller and pin; loads are force, pressure, a bolt's
  preload and gravity. A design of several parts is solved assembled, bonded where its parts touch, with a material
  for each. Netgen meshes the B-rep into quadratic tetrahedra, finer on fillets and holes, and the solid is meshed
  and solved again until the answer stops changing. Every result says how it is known:
  `simulated (FEA, linear static, converged to 1.1 %)`, with the convergence of every refinement kept. A study that
  does not reach its tolerance says so and gives no safety factor.
- **Singularities are named, never reported as strength.** At a sharp inside corner the elastic stress has no finite
  value. The study finds such edges, leaves the stress within a stated radius of them out of the peak and the safety
  factor, and lists each with where it is, why, and how the stress there grew with refinement. The edge of a fixed
  face and the edge of a loaded face are treated the same way when the stress there keeps growing.
- **Material numbers with their sources.** A study takes Young's modulus, Poisson's ratio, yield strength and
  density from the materials library, each with its document, or from values given with the study and their source.
  Nothing is defaulted: a missing modulus stops the study, a missing yield strength means no safety factor. A
  printed filament is solved solid and isotropic, judged against its weakest sourced strength, and says so.
- **A verification suite, published.** Textbook and published cases, each quantity with its reference and tolerance:
  a cantilever against Timoshenko and Euler-Bernoulli, a plate with a hole against Peterson's chart, Lamé's thick
  cylinder, self weight, two bonded solids, a bolt preload, the frequencies of a clamped and a free beam, Euler's
  column, and a sharp corner that must be named. [docs/STRENGTH.md](docs/STRENGTH.md) has the table;
  `form strength verify` runs it.
- **Headless and in the background.** `strength_study` and `get_strength_study` over MCP, and `form strength
  static|modal|buckling|thermal|thermal_stress|run|list|show|verify` (also as `form study strength ...`) with JSON
  output. A study runs
  as a job with progress and cancel. Its result is stored beside the revision under a key of the geometry, the
  loads, the material's numbers and the engine, so it goes stale after any change and says which revision it
  describes. A typical bracket converges in about 10 s.
- **Field data for the viewport.** Each result has a compact surface field: per-vertex displacement, von Mises
  stress, safety factor and a mask of the singular zones; mode shapes for modal and buckling studies.
- **Curved elements.** The quadratic tetrahedra are isoparametric: every mid-side node lies on the geometry, so a
  fillet or a bore is a curved surface in the model. Lamé's cylinder comes out within 0.1 %, and the bracket's fillet
  stress settles in three refinements.
- **NAFEMS LE1 and LE10** are in the verification suite with their published targets (92.7 MPa and −5.38 MPa).
- **A hand estimate beside the result.** Where a part reads as a bar fixed at one end, a static result carries the
  beam-theory stress and deflection from section properties measured on the solid (evidence: computed, closed
  form). Any other shape says why no formula fits.
- **Strength as a constraint in a search.** `optimize` and `make_lighter` take `fea.safety_factor >= 2` (the lower
  value, with the stated error applied). The study is solved on real candidates, best first, within 8 solves and
  300 s; only candidates that were solved and passed count, and the result lists each one.
- **Heat and thermal stress.** `thermal` studies solve steady conduction with temperature, convection, heat and
  heat-flux conditions on picked faces, and report the temperature range, the heat through each condition and the
  heat balance. `thermal_stress` adds the expansion of that temperature field to a static study. Checked against a
  wall with convection, a pipe wall, a held bar and Timoshenko's thick cylinder.
- **A `hold` support** stops single directions of a face, and a support along a line is named as singular.
- **Guidance for agents.** A `strength-studies` skill and `design_guide(topic="strength")`: loads on picked faces,
  sourced materials, reading convergence, and never quoting the stress at a singularity.
- **The solver is an optional engine.** "Strength studies (FEA)" in Settings, Engines & software installs Netgen
  (LGPL-2.1, unmodified wheels), scikit-fem and SciPy (BSD-3-Clause) and PyAMG (MIT) into a Python of their own,
  about 190 MB. Without it a study computes nothing and says how to get it.

### Fixed

- A commit no longer fails on a design whose `derived()` reports a value as text (the bearing flange's housing
  limits).
- The packaged app now carries the speeds-and-feeds table CAM reads (form/cam/feeds.toml) and the cost rates table.
- Saving print prices (`form cost --save`, the Cost section) keeps the other settings in cost.json.

- **Parts that do not fit one plate go onto more plates, never off the plate.** A design whose parts (or copies of
  it) do not fit the printer's bed is packed onto as many plates as it takes: largest first, turned about Z where
  that helps, with the gap between parts, room for the brim the slicer will add and the bed's excluded zones (an
  X1's cutter corner, the square inside a round bed). The 3D view shows every plate side by side, "Plate 1 of N"
  under each, each part lying as it prints. The exported 3MF carries every plate in the form the slicer reads as
  plates: Bambu Studio and OrcaSlicer (and ElegooSlicer, Snapmaker Orca) get their plate entries, PrusaSlicer 2.9 its
  bed grid. Open in slicer now opens one project with every plate, each sliced by the slicer itself (time and grams
  per plate and in all); PrusaSlicer, which keeps one plate per project, opens one window per plate. A part larger
  than the plate however it lies is never placed: it is named with its size against the bed and what would make it
  fit (another side down, a scale, a split, a larger printer). `open_in_slicer` and `form slicer-open` take
  `copies`, `pack_plate` and `form pack` say how many plates the copies take, `plate_plan(write_3mf=true)` and
  `form pack --3mf DIR` write them.
- **Assembled and exploded views rest on the ground, and pull apart about the base.** The assembled set rests on
  the plate or studio floor (its lowest point at z = 0), a part built lying down and stood upright by its placement
  included. Pulling it apart keeps the anchor (the part fixed to the world with the largest footprint) exactly where
  it rests: the other parts move away from it, and an offset that would go through the ground is turned upward.
  Swinging a joint keeps the fixed part where it is, unless the swing would take a part below the ground: then the
  whole set is lifted just enough for the lowest point the joint reaches over its whole range, so the lift stays
  the same through the motion and nothing is ever drawn under the plate. The same in the app and in
  `render(view="exploded")`.

## 1.1.0

Form Studio 1.1 is the largest release since 1.0. The app has a new look and layout, Lightdesk: the 3D view fills
the window, every control is a pane of glass, the conversation is a column on the left, and one colour, electric
cyan, means "this is where you are". You can now bring anything (a mesh, a scan, a sculpt, a STEP, a photo, a PDF,
a link or only words) and a triage step works out what it is and what to make of it. Designs are checked against
the numbers you asked for, built one feature at a time while you watch, and refined after they build. Settings is
reorganised, with a switch for every engine you install, and the agent and model are chosen right on Home.

### New

- **Bring anything; Form Studio works out what it is.** A triage step looks at whatever you attach or describe (a
  mesh, a STEP, a photo, a sketch, a PDF, a link, or only words), says what it is and takes the right route. A mesh
  is classed mechanical, organic or mixed from its own surface, with its triangle count, defects, a guess at its
  units and its bodies. `triage` is an MCP tool and `form triage FILE` in the terminal; "Make editable" and
  `reconstruct` run it themselves. You are asked only when the answer changes the result, with one question.
- **Bring files from any program.** Besides STL, OBJ, 3MF and STEP, Form Studio now reads PLY (ASCII and binary,
  vertex colours included), OFF, AMF, glTF and GLB, Collada (DAE), X3D, VRML, VTK, VTP and VTU meshes; scanner point
  clouds as XYZ, PTS, LAS and E57 (and a PLY of vertices), turned into a surface first and then routed like a mesh;
  IGES and OpenCASCADE BREP as exact CAD; DXF and SVG drawings as a profile with their sizes; and zip archives of
  any of these, as Printables and Thingiverse hand them out, unpacked safely with each file triaged. Units are
  converted where the file states them (3MF, AMF, Collada, STEP, IGES, DXF, SVG) or the format fixes them (glTF,
  LAS and E57 are metres), and glTF's and Collada's Y-up becomes Z-up. Every way in takes them: drop, the paperclip,
  Import a reference part, links, `triage`, `reconstruct`, `import_reference` and `form formats`. A format that is
  not read (FBX, USD, LAZ, native SolidWorks or Inventor parts) gets one message saying why and what is read.
- **Scans and sculpts become designs.** A smooth closed sculpt becomes a surface body: NURBS faces over a cage you
  can edit, with a STEP export. One with fine detail, handles or many triangles becomes a mesh body: the repaired
  mesh with a Scale and a Flat base parameter, into which exact CAD features (holes, pockets, a split) are cut. The
  result says how far it is from your file, as measured, and what it is not.
- **Imperfect meshes are repaired, and every repair is listed.** Sliver triangles on an edge, triangles facing the
  wrong way, small holes, flat openings and loose debris are fixed before anything is refused; vertices are never
  moved. A large opening that is not flat is never guessed: the file stays a reference and you are told.
- **Heavy meshes are welcome.** A mesh with more triangles than a design can carry gets a lighter working copy that
  stays closed, with its distance from your file measured and shown; your file is unchanged. A reference mesh above
  400,000 triangles is drawn from a lighter copy instead of being refused.
- **Mesh to editable CAD.** Make editable turns an STL, OBJ or 3MF into a new design checked against the mesh, and
  shows it: the mesh's outline stays on screen while the CAD grows inside it, with the largest distance between the
  two counted beside it. Analytic and freeform faces and a feature tree from the mesh are Beta.
- **A new look: Lightdesk.** The 3D view fills the whole window and every control floats over it as a pane of glass,
  in the dark studio or on paper. One colour, electric cyan, always means "this is where you are"; green only means
  pass and amber only means review. The app is set in Geist and Geist Mono, and Home, the first run, Settings,
  sheets, menus and messages use the same glass, type and colours.
- **The conversation is a column on the left.** Once something is said, the conversation is a glass column beside
  the stage (drag its edge to resize it; the width is remembered) with the prompt at its foot. Ctrl/⌘ J or Fold
  turns it into one bar under the part: a status line, up to four numbered suggestions (press 1 to 4) and the
  prompt. The part, its dimension lines and the print simulation are framed in the stage that is left.
- **Calm and Focus.** A click into the 3D view, or Esc, folds the conversation to its bar; taking up the prompt
  brings it back. Focus (Ctrl/⌘ .) steps both side columns away and leaves the part alone. A tab on the pane's edge
  folds the pane.
- **The top of the window is three capsules.** The design, its revision and its state, with a way back to all
  designs; the stages (Describe, Design, Fit, Review, Make) on the window's centre line, each with one line that
  says where it stands; the printer (when printing is on), search and Settings.
- **The features are a program.** In Design the features are a numbered listing in build order. While a design
  builds it runs: a light travels down the margin to the line being built and built lines are ticked. The pipeline
  is one line at the pane's foot: a dot for each step, what the checks found, and Auto.
- **A build has a title.** While a design builds, a pane in the lower part of the stage names the feature being
  made in large type, with its number, a track with one segment per step and the feature before and after. The part
  stands as large as it will at rest, its edges traced before each solid rises, and its size so far is on thin lit
  dimension lines and one small line above the view buttons.
- **While a design is being made, its words sit in the middle of the stage.** The agent's real steps are written
  there; a conversation that grows (tool steps, a question with long answers) glides to the left column, and a
  question keeps its reply buttons in view.
- **No bands anywhere.** The room, the floor, shadows, glows, glass, fades and the part itself are dithered, so
  slow gradients no longer show as steps on a display. The part stands in a pool of warm light; the 10 mm grid is
  off until you ask for it.
- **A thin lit caret.** In every text field the caret is a thin line of cyan as tall as the text, lit while you
  type and blinking once the field is still.
- **The agent and model are chosen in Home's composer.** A chip beside Design it names the agent, the model and the
  effort and opens the same picker as a conversation. With no agent connected it opens Settings › Agents & models.
- **Home on the first day shows a real build.** With no designs yet, a sensor enclosure (13 features, real geometry
  from the CAD kernel, labelled as an example) turns beside the composer. Nothing is created.
- **The conversation reads as a record of the design.** A step that changes the design is a card with one sentence
  and the render the agent took. A new revision posts its number, the features it changed, the values as from → to,
  and Compare.
- **Glass you can turn off, and a quieter window.** With "Reduce transparency" on, in Low Power Mode or without a
  graphics card the panes are solid; Reduce Motion keeps only fades. A still window redraws about 15 times a second
  or fewer (it was about 65).
- **A design is checked against what you asked for.** The numbers in a request (sizes, hole counts and diameters, a
  bolt circle, wall thickness, threads, the number of parts) become requirements measured on the built solid. Each
  revision shows what was measured and whether it passed; one that fails blocks release. Numbers that cannot all be
  true are reported before anything is designed.
- **Designs built one feature at a time.** You watch the design take shape; a feature that fails no longer loses
  the work, and each feature is checked as it is made.
- **Faster, cheaper changes by an agent.** An agent changes one feature or one parameter by name instead of sending
  the whole design again, and only what changed is rebuilt. Common mistakes in design code are found before the
  build starts, all at once.
- **Designs are refined after they build.** Form Studio looks for small improvements (edge rounding, details,
  materials) and keeps only those that pass its checks. They arrive as one extra revision, "Refined: N changes",
  that you can undo change by change or all at once. Pointing at a change lights up its feature, Before / After
  shows the design as it was, and refinement can be turned off per design or in Settings › General.
- **Compare is a wipe.** Comparing two revisions puts a line down the view, the head on one side and the other
  revision on the other. Drag the line across the part; Done and Esc end it.
- **Drag a face to change the design**, constrained 2D sketches, and sculpted forms as exact NURBS.
- **Real standard hardware.** ISO screws, nuts, washers, heat-set inserts and bearings built into designs, with
  their masses in the bill of materials.
- **Engineering materials for models.** Aluminium, steel, brass, titanium, woods and engineering plastics for
  designs that are machined, cast or rendered, with the design's computed mass.
- **Game assets (Beta).** A design can be made ready for a game engine: LODs, UVs, baked maps and collision, with
  Blender as an optional modelling editor.
- **A light appearance**, concepts in the conversation, and links and every file type in chat.

### Changed

- **Settings, reorganised.** A rail on the left lists the pages (General, Agents & models, Engines & software,
  Printing, Other apps, Updates, Advanced); each page is a set of titled cards with one row per setting. Search
  finds a setting on any page and a dot marks a page with unsaved changes. "Software" is now "Engines & software"
  and "Agents" is "Agents & models".
- **Use in Form Studio: a switch for everything you install.** Each optional engine or app (CAD-Recode, CADFit,
  CoACD, the CADEvolve corpus, Blender, FreeCAD, OpenSCAD and every slicer) shows whether it is installed and,
  separately, whether Form Studio uses it. Switched off, it stays on your computer and is never called. Each
  installs from its own button, with its size and licence shown first; CAD-Recode is opt-in and non-commercial
  (CC BY-NC 4.0). In `studio.toml`: `[recon] learned`, `[recon] cadfit` and `[use]`.
- **The Mac app is now called Form Studio.app** (it was FORM.app). If you added Form Studio to an agent by the old
  app's path, add it again: `form setup` finds your agents and writes the entry.
- **Creation first.** A new design is a 3D model; 3D printing is optional and turned on when you want it.
- **A design is built once.** The solid a change builds is kept and reused for the view, the exports, the checks
  and every render: one build per change instead of three, and renders draw 4 to 8 times faster. Builds run side by
  side in a kernel pool, and pipeline jobs survive a restart.
- **Agents:** MCP 2026-07-28 throughout, long tools can run as tasks, and the design guidance is served as skills.
- **Recipes are no longer a public library.** The engine still uses them as building blocks for agents.
- **A draft reads as a change, not an error.** What a draft does to each feature is tagged in the draft's own
  colour instead of the red used for failures.

### Fixed

- A mesh with a few stray triangles was refused as "not closed (0 open boundaries…)": it is now repaired, and what
  is open is counted correctly when a mesh really does not close.
- A refusal names the next step to take and says when it comes back unchanged, so an agent does not repeat a call
  that cannot work. Designs with many faces (a mesh brought in as a body) build several times faster.
- **The first click into the 3D view folds the conversation**, and the prompt under the part is written in where
  it stands; sending the message brings the conversation back.
- **Refinement always opens** from its header, in every stage.
- **The part comes back to the middle** when a column folds, opens or is resized, the pane folds, Focus is switched
  or the window is resized; it never shrinks while it is built.
- **A tall part stands whole on the stage.** A vase, a wall hook or a box with its lid open or pulled apart ran up
  under the top row and down into the bar and its suggestions. The part, its dimension lines and their numbers now
  stay inside the free stage at every window size, and the camera glides back when the bar grows.
- **"The Form Studio engine is not answering" in Settings.** A burst of requests was dropped although the engine
  was fine. The engine now accepts them all, and the app asks again once before saying so.
- **Threaded holes have their thread.** A hole cut with the built-in internal thread could come out as a plain
  bore. The thread is now cut, and one that cannot be cut is reported.
- **A decorative finish can no longer thin a wall below the print minimum.** Flutes, grooves, knurls and textures
  are measured as they are made; one that would leave a wall under three nozzle widths (1.2 mm on a 0.4 mm nozzle)
  is left out and named in the build log. A thin wall in a structural feature now fails the Thinnest-wall check.
- **STL export no longer hangs on a mesh that will not close** (703 s became 1.8 s on the case that found it), and
  a fillet as large as an arc's own radius no longer crashes the geometry kernel.
- **Saved conversations open with every message**, Compare turns off (a toggle, Done, Esc), and the Building
  caption goes when the build is saved.
- Text sits in the middle of its line beside icons and tags, and on a Mac it is drawn at its real weight. Menus
  are easier to read over the part, and a tooltip no longer covers the menu its button opened.
- Settings opened from Home's "Connect an agent" no longer shows an empty sheet, no outline crosses the window
  when a design is opened from Home, and "Outputs are current" is not announced when a design merely opens.
- **Agents can call the design workflow by name at once**: the tools the server's instructions name first load up
  front.

### Known limits

- Game assets are Beta: every asset passes its technical checks, and its visual quality is still improving. They are
  refined only when you ask.
- Mesh to CAD's freeform faces and feature tree are Beta; a feature that does not verify stays in the base solid, and
  the report says so. A surface body is made only for a smooth closed sculpt; other scans become a mesh body.
- Refinement adds a revision to your history. Undo it, or turn refinement off, if you would rather keep the design as
  you built it.

### Details

- **Triage, in full** (`form/triage.py`). One step for any input. A mesh is read, repaired on a copy and measured:
  triangles, size, a guess at the units, defects before and after repair, bodies, genus, and the share of the surface
  that is flat or ruled. It is classed mechanical, organic or mixed and the route follows: parametric, surface body,
  mesh body, assembly or reference only. `reconstruct` runs it and takes the route; when the parametric route fails on
  a mesh that closes it keeps the mesh body and says so; a size that makes no sense in millimetres is asked about once
  (`units=`, `--units`). `design_guide`, the skills, the server instructions and the chat prompt lead with triage.
- **Mesh repair and lighter copies** (`form/meshrepair.py`). Safe, listed repairs: fins, extra triangles on an edge,
  orientation, small holes, flat openings, debris. Vertices never move. A heavy mesh gets a lighter working copy that
  stays closed, with the distance to the file measured both ways.
- **The organic route** (`form/sculpt.py`). A smooth closed sculpt becomes NURBS faces over a cage within a time
  limit, taken only when measured within 0.1 % of its size; anything else becomes a mesh body with Scale and Flat base
  that exact CAD features are cut into. `MeshBody` has load, trim, scale, move, bounds and solid; a closed mesh becomes
  a solid directly (2 s for 100,000 triangles instead of a minute of sewing), and its nearest-point search is exact.
- **Many faces, faster.** Indexing a build123d ShapeList copied it for every face: a design with 100,000 faces built
  in 72 s, now 22 s.
- **The workspace's measures.** In a 1440 pt window the stage between the conversation column and the pane is 716 pt
  wide (it was 560): the column is 340 px (300 to 480 by dragging its edge, remembered), the pane 300 px, the outer
  gutters 12 px and the top row's capsules 40 px tall. The tool dock floats inside the stage at its left edge and takes
  no column. Legends, measurements, the selection and the refinement's changes have their slot in the right column.
  A window under 1200 px has room for the column or the panes: with the conversation open the panes fold to one
  button. The smallest window is 1100 × 700.
- **The top row.** On macOS the close, minimise and zoom buttons stand 24 px in, on the row's centre line. The mark in
  the title capsule carries a chevron and goes back to all designs (also Ctrl/⌘ [). Under 1400 px the printer is its icon
  and the default "unreleased" is not said, so the stages keep their words.
- **The print simulation is laid out in the free stage.** Its transport stands at the foot of the stage between the
  tool dock and the panes and folds to its row of controls when the stage is short; the print is framed in the
  rectangle that is left and glides when that changes.
- **The camera keeps the part in the free stage.** It pulls back until the part, with the dimension lines and numbers
  outside its box, is clear of the tool dock and the pane. Its shift runs along the camera's own axes, so the part no
  longer stands low with the column open. A part mid-build is framed as it will be at rest (at 1440 × 900, step 6 of 12
  of the sensor case: 478 pt wide, was 363 pt).
- **Dithering, in full.** The shadow under every floating layer is one smooth falloff worked out per pixel
  (`shadow.frag`), a glow likewise (`glow.frag`), and the blur inside a glass pane is kept in floating point at a
  quarter size until its last pass (`glass.frag`). Scroll shadows, plate fades and the loading shimmer share one
  gradient; the part (`clay.frag`, `game.frag`) takes one display step of noise on its lit colour. The noise is fixed
  to the pixels, so a still window is not redrawn for it. A software renderer keeps the plain gradients.
- **One caret** (`Caret.qml`) in every text field: a 2 px lit line at the cursor, solid while the words change,
  blinking in steps once they are still, so a resting prompt does not redraw the window. Glows exist only while lit.
- **The accent is electric cyan**: #3ee6ff in the dark studio and #087f9f on paper, for the mark's origin, the stage
  you are in, the line being built, the prompt, switches, focus, dimension lines and the cue. The brand mark, app
  icons, the website, the README drawings and the engine's pictures (analysis, share card, print simulation) use it.
- **The engine accepts a burst.** Its listen backlog is 128, and the app asks a read once more before reporting that
  the engine is not answering.

- **A design in several parts stays calm while you slide a parameter or orbit it.** Every draft (each step of a
  slider) used to destroy and re-make every part node of an assembled design, its edge lines and its meshes, some of
  them twice: 272 part nodes during one slide and orbit of an eight-part figure, all on the GUI thread. Part nodes
  now stay while the design has the same parts and read their placement from the current model, and each part
  keeps its meshes while its geometry is the same, so a head-size draft re-makes only the head and the hat. A mesh
  whose new positions arrive before its new triangles keeps what it draws instead of reading triangles that do not
  fit. A new journey (viewport_parts_calm) slides and orbits an eight-part figure while its pipeline runs and samples
  every frame.
- **Home: the "Make it for" row no longer moves.** Every item is one height on one centre line; the purpose and the
  printer sit on the left under the composer, the agent on the right, and the printer chip's place is kept whenever
  printing is on, so picking My printer only shows it. Start blank and Replace a broken part are a quiet line below.
  The segmented control centres its segments at any height.
- **Settings › Software says what each thing does.** Every optional engine, Blender, FreeCAD, OpenSCAD, the slicers,
  the CAD kernel and the parts libraries say in plain words what they do and when you would want them, and one line
  says what each gives you (CAD-Recode: a learned point-cloud to sketch-and-extrude model, non-commercial; CADFit: an
  extrude and revolve search, slower, non-commercial; CoACD: convex decomposition for game collision, MIT; CADEvolve:
  reference programs, never run). What Form Studio downloaded itself (an engine's own Python, CAD-Recode's weights,
  the CADEvolve corpus) can be removed from its card, after one question (`POST /api/install/remove`); nothing
  outside Form Studio's folders is ever removed.
- **Settings: calmer grouping.** General reads Appearance, Set up for, then Preferences, with what refinement learned
  after the refinement settings; section headings have the same rhythm on every tab, and Set up for says it is
  reading instead of showing nothing.
- **The feature panel says what shapes a feature.** A feature with no parameters of its own no longer reads "0
  parameters": it says its size and place come from the values it uses, the general parameters or the features
  built before it, with those one click away. A feature without a description no longer leaves a gap.
- **Game asset: a calm start and readable errors.** Before the first build the preview is a card on the sheet's own
  surface with one line about what a build makes and the Build button, never a black box; while it bakes, a spinner
  and one line. A build that fails is a note that says what happened and what to do, with Build again and Settings ›
  Software.

- **Game assets are marked Beta.** Home's "Make it for", the design's Purpose and the Game asset sheet carry a small
  "Beta" tag (BetaTag.qml, Theme tokens, light and dark); the website's game section, How we measure and the README
  say it once, with one line: every asset passes its technical checks, and its visual quality is still improving.
- **Website: 1.1.** The hero badge names Form Studio 1.1 and what it brings (engineering materials for CNC, game
  assets in Beta) and links to the releases; the README no longer says "Also in 1.0.0".
- **Game assets are refined only when you ask.** Automatic refinement still runs after every CAD build; a game asset
  (purpose "game", or a cage source) is left as it was built unless refinement is turned on for it
  (`refine_design(action="on")`, or Refine again once) or for all of them in Settings › General › Refine game assets
  (`[refine] game = true`). The guidance skills and `design_guide(topic="game")` say so.
- **The enclosure builds with every lid thickness and screw head.** Since the countersink follows the screw's real
  head cone, a 1.2 mm lid with countersunk M3 screws was refused ("recess deeper than the hole"). The lid now takes
  the head asked for when its recess leaves at least 0.4 mm of lid under it, and otherwise the next that fits
  (countersunk, then socket in a counterbore, then a pan head on the surface); the derived values and the BOM name
  the head used and why. A test builds every lid thickness edge with every head and screw size.
- **Engineering materials for models.** A design that is not printed (CNC, casting, rendering) can be aluminium
  6061 or 7075, mild or stainless steel, brass, copper, titanium, oak, walnut, maple, pine, POM, PTFE, PEEK or
  acrylic: `set_appearance` and Colour and material in the workspace take them, with bd_materials' typical density
  and look (form/material_library.py), and the design's mass is shown and reported by `get_project` (computed:
  modelled volume x typical density). A design's `appearance()` zone may name one too (`"material": "brass"`).
  Printing filaments are unchanged, and a print design keeps to them.
- **The interface as data, for failed journeys.** `ui.tree()` (form/app/uitest.py) writes the visible QML item tree
  as JSON: each item's type, objectName, visible text (capped at 240 characters), enabled, checked and focus, its
  bounds in the window and the QML file it comes from. Every failing journey writes it beside its fail-*.png, and
  `python -m form.app --tree out.json` writes it for any screen, with or without `--shot`. The text of a password
  field is never in it, on the field or anywhere else.
- **The drawn app on the website shows a planetary gearbox, not the phone dock.** The sample project behind the
  live replica and "How it works" is the planetary gearbox exemplar, created for printing, with one committed change
  (backlash 0.15 to 0.2 mm), then built, checked and sliced: 6 parts, 1027 faces, 7 checks pass and one asks for a
  look, 55 min and 23.4 g on one plate. site/tools/export_site_data.py makes the project itself in a scratch data
  folder, so the data is reproducible; the replica reads the design's purpose and draws a Fit tab, a Slice step, the
  print simulation and the toolpath only for a print design that was sliced (site/tools/check_site.py fails
  otherwise). Parts that are wider than one plate as modelled show the plate only with the sliced toolpath. The
  layer chart of the print simulation keeps its height. README: the checks, slicer and terminal cards are drawn from
  the same gearbox (scripts/readme_art.py builds it as a print design through the staged workflow); the social card
  (site/assets/og.png) shows the hero helmet; the gallery's game controller gave way to a bottle and cap. The
  scripts that make the product pictures are in scripts/media/showcase/, with a README.
- **Website and README: real builds up front.** The home page opens on a photograph of the hero helmet pulled apart
  into its four parts, followed by a gallery of original designs built by the engine (planetary gear stage, ratchet
  wrench, cam and follower, spiral vase, perforated lampshade, cube speaker, bottle and cap, woven basket, a
  treasure chest game asset), then how it works, the app drawn live, mesh to editable CAD (a synthetic bracket:
  3,216 triangles to 18 dimensions, 0.0017 mm from the mesh), automatic refinement before and after, game assets
  with their four levels of detail, assemblies, and "your agent, your computer". The navigation is What it makes,
  How it works, Your agent, Docs; the "3D printing" menu is gone. A new page, How we measure
  (site/measure/), states what the three benches measure and their numbers, with the full reports as docs pages;
  build timings and slicer compatibility are linked from the footer. The drawn app loads when it comes near, so the
  first view is about 0.25 MB uncompressed where it was about 1.4 MB. The README opens with the same photograph and a strip of
  builds. Product pictures are Blender renders of the designs' own geometry with the app's scene and materials.

- **Real standard hardware in designs, with masses in the BOM.** `form.parts` now builds the hardware itself from
  bd_warehouse, not only the holes for it: ISO screws (socket, pan, countersunk, button, hex), nuts, washers, brass
  heat-set inserts and 6xx bearings, each with a computed mass, its material and `.bom()` for the assembly's
  hardware list. `parts.bolted_joint(size, clamp, into="insert" | "nut" | "tap" | "self_tap")` cuts the clearance
  and counterbore, the insert pocket, nut trap or tap hole, and picks a stock screw length with enough thread
  engagement. New: ISO tap drills, multi-start trapezoidal and ACME lead-screw threads, PCO 1881 and ASTM D2911
  bottle threads, roller-chain sprockets with `chain_drive` (an even link count and the exact centre distance for
  it), pipe sizes, pipe sockets and ASME B16.5 flanges. `form.material_library` gives densities and a look for
  metals, woods and engineering plastics from bd_materials. BOM.csv lists the grams of purchased hardware (computed:
  modelled volume x typical density). Three new exemplars show them: `lead_screw_axis`, `chain_drive` and
  `bottle_pipe_adapter`. A countersink cut by `parts.screw_clearance` now follows the screw's theoretical head cone
  (2 d for ISO 10642): the old one was narrower than the head below its top face, so a real screw stood proud.
  bd_materials ships with the app (its 87 MB of texture maps do not).

- **Cage operators keep every LOD closed and manifold.** Refinement replays a cage in a strict mode: the cage
  literal's zero-length edges are collapsed before the first refinement op (the helmet had two beside its visor,
  and Blender's bevel clamps the whole bevel to its tightest spot, so a panel line there folded into coincident
  points), a bevel that would still clamp to zero width leaves out the edges with no room beside them or is refused,
  and every op must leave the cage as closed, manifold and consistently wound as it found it (a new winding error is
  repaired; anything else refuses the op in a second, before any bake). LOD decimation checks every try the way the
  validator will (welded open and non-manifold edges, winding errors, inverted shells, faces folded against the
  source), removes small parts the collapse turned flat or inside out (a rivet at LOD3), prefers a sound try over a
  closer unsound one, and retries milder before giving up. Exemplar op lists replay exactly as before.
- **Primary-form operators for game cages** (form/refine/ops_form.py), chosen by the brief's words and the cage's
  shape: shell fairing (Taubin smoothing of a lumpy shell, creases, region borders and frozen regions held, carried
  to the bake source), a dished wheel face (spokes sink, the hub stands out), lid and body massing for a chest (the
  lid overhangs and its dome rises, the walls step in above the foot), end piers with caps for a wall piece (inside
  its grid), and a waist for a handheld bar. They move points or add closed parts and never change a part's faces,
  so the cage stays manifold by construction. A new `fairness` deficit measures how lumpy a cage's shell is.
- **Refinement does not delay the next design's first picture.** A kernel worker pruned its checkpoint folder inside
  the first feature it built after 20 s; with every design refined the folder holds about a thousand checkpoints
  (three times as many as without), and the listing took milliseconds out of the next design's first stage. It now
  prunes in a background thread. A candidate batch the engine stopped waiting for, or a finished run's, starts no
  more builds and measures nothing it gets back.
- **Benches, measured honestly.** Creation bench (docs/CREATION_BENCH.md): every gate passes: function checks
  identical, mean critic gain 1.91, no brief lower, first visible 0.044 s on and 0.043 s off (within 5 %; an
  earlier run before the pruning fix failed at 0.048 s against 0.0435 s). Game bench (docs/GAME_BENCH.md), three new
  blind passes by an AI model, not a person, over the fourteen sheets of both runs shuffled together: refinement now keeps a
  primary-form change on three of six assets (shell fairing on the helmet, lid and body massing on the chest, end
  piers on the wall) and no detail operator fails on a non-manifold LOD any more; rubric with refinement on 2.81
  helmet, 3.31 chest, 3.19 sword, 2.94 wall, 3.31 wheel, 2.94 remote, so the aesthetic gate (4.0 on five of six)
  still fails. The blind passes still read the helmet shell as lumpy and the remote as a plain bar; the wall went
  from 2.38 to 2.94 and the chest from 3.12 to 3.31.

- **Game refinement sees what a candidate looks like baked.** Each game candidate now gets a quick bake (256 px
  maps, few samples: a new internal `preview` bake of form/game) and is scored on that asset's game evidence: bevel
  coverage, value contrast, detail scales and their density, wear, and the interior read of a lit render with the
  baked base colour. Before, candidates were measured on the bare cage, so a panel line, a trim or an inset made a
  stand-in edge measure worse and the engine kept nothing on five of the six bench assets. REFINE_OPS now replay on
  the bake source too, so a groove cut in the low cage is in the high one and the normal map no longer bakes it
  flat. The game time budget is 300 s (every candidate bakes; at most two Blender processes).
- **Fixes in refinement.** Panel lines and trims pick a region that has a border (a region that is a whole part
  has none, which failed in Blender with "the edge selection is empty"). Large cage literals and long REFINE_OPS
  lists are written packed (`meshsource.pack`: deterministic JSON, zlib, base64; regions stay readable), so the
  bench chest's kit detail no longer hits the 200 kB source limit. The exported STL drops the zero-area triangles
  OCCT's mesher leaves where three rounds meet, which made a closed solid read as open and took fillets out of
  refined designs (magnet organizer, the test block). Edge break skips edges shorter than 3 r and faces narrower
  than 2.2 r (groove walls, slivers), where OCCT's fillet could take the kernel down.
- **Stricter game deficits.** A game asset's silhouette deficit also counts its plainest view (a slab or a disc
  from the side), and its detail scales count how dense the secondary breakup is (feature-edge length per diagonal),
  so the engine has something to do on assets the old measures called finished.
- **New cage operators.** Crisp plates (`crisp_regions`): soft region borders creased with their corners kept and
  support loops beside them, so a pushed-out plate reads as a plate, not a swell. The silhouette breaker works on
  any cage: without a brow, crest or vent region it pushes out the bordered region that faces across the plainest
  view, and every breaker's seat is creased. A quick bake that fails the validator's geometric checks (closed and
  manifold LODs, flipped faces, baked normals) rejects its candidate during the search; texel density and UV
  overlap are left to the full bake.
- **More refinement fixes.** REFINE_OPS is written as a Python literal (an op with `pin_corners: true` made the
  refined source fail to load), and packed literals keep their region order (the wall's bricks lost their
  material). The bench sword's guard ends in two terminals.
- **Game bench, measured honestly.** docs/GAME_BENCH.md has the new on and off runs and three new blind passes by
  an AI model, not a person, over the fourteen sheets of both runs shuffled together: 0 of 6 assets at 4.0 (gate failed),
  the control fails as it must, every technical check passes. Refinement kept one change (a silhouette breaker on
  the wall); on the other assets the panel line, crisp plates, inset and kit operators made LODs that are not
  manifold or have flipped faces after decimation, and the quick bake rejected them. That LOD robustness is the next
  piece of work.

- **Design guidance as skills, one source.** The design guide's topics and the plugin's skills now live once in
  `form/guidance/<skill>/` (SKILL.md plus `references/`). `design_guide(topic)` returns the same text as before, read
  from those files, and names the skill that holds it (`skill`, `skill_file`). `form/mcp_skills.py` serves them over
  MCP as the `io.modelcontextprotocol/skills` extension (`skills/list`, `skills/get`, files through `resources/read`
  at `skill://<name>/...`, each manifest digest the SHA-256 of the bytes served); the server registers it separately.
  `scripts/gen_skills.py` writes `plugins/form/skills` from the same source, and a test fails on drift. Six new
  skills: cad-core, staged-design, surfacing-organic, texture, remodel-from-mesh and game-asset (listed only when the
  game pipeline is in the build); aesthetics joins industrial-design, mechanisms joins assemblies-and-mechanisms and
  design for printing joins fdm-engineering. The skills mention the automatic refinement (`refine_design`), and intake
  points meshes to remodel-from-mesh instead of saying scans cannot be rebuilt.
- **Questions through the agent's own client.** Outside Form Studio's chat, a client that supports MCP elicitation
  (form mode) now shows Form Studio's questions in its own form: `ask_user` (choices, several at once, or a free
  answer), `ask_measurement` (the value within the parameter's range, and calipers, ruler or a datasheet; a datasheet
  value is recorded as specified), a confirmation before `delete_project` with the trash path, the commands and
  licence before `install_software` (always for a non-commercial licence), and a check before a `fetch_link` download
  over 100 MB. Declining or closing the form is an answer, not an error: nothing is changed. On MCP 2026-07-28 the
  tool answers with an `InputRequiredResult` and a sealed request state, and takes an answer only with that state;
  earlier versions get the form on the session. Form Studio's own chat, and clients without elicitation, get exactly
  what they got before (`form/elicit.py`).
- **Claude Code searches Form Studio's tools.** The chat's Claude Code runs list ToolSearch and set
  `ENABLE_TOOL_SEARCH=auto`; eleven tools (form_overview, get_project, create_design, update_design, render,
  preview_change, commit_change, design_guide, design_brief, ask_user, get_job) carry `anthropic/alwaysLoad` and the rest are found
  by searching, so every tool description now opens with a verb and its object. `[chat] tool_search = "false"` (or
  `FORM_TOOL_SEARCH=false`) loads every tool up front as before, for this release. The server's instructions are
  shorter (3,805 characters, within the 4,096 Claude Code reads), and tests keep them and every description there.
- **MCP 2026-07-28 throughout.** The API agents' MCP client speaks 2026-07-28 (`server/discover` and a per-request
  envelope, with the older handshake as a fallback), and a change's author comes from each request's own client info.
  The server registers the skills and tasks extensions when their modules are present (`form/mcp_skills.py`,
  `form/mcp_tasks.py`). docs/MCP.md has new Skills, Questions to the person and Tool search sections.

- **Long MCP tools can run as tasks** (`form/mcp_tasks.py`, extension `io.modelcontextprotocol/tasks`, schema
  2026-07-28). A client that declares the extension on a call to create_design, update_design, reconstruct,
  fit_params, optimize, build_candidates, propose_concepts, refine_design (rerun), run_pipeline, commit_change (run),
  render_photo, turntable, print_simulation, install_software (confirm) or fetch_link gets a task handle at once and
  polls `tasks/get` until it is completed (the tool's own result), failed or cancelled; progress the tool reports
  becomes the task's status message, and the task waits for the pipeline job it started. `tasks/cancel` is
  cooperative: the engine stops at its next stage, before a revision is saved, and cancels the pipeline job,
  refinement or install the call started; a cancelled task says what it kept (revisions saved before the cancel, or
  the last stage built as a draft, never a half-written revision). A task never asks the person anything. A client
  that does not declare the extension gets exactly today's results. Tasks are kept for 24 hours in `<data>/.tasks`
  (`form/taskstore.py`) and survive a server restart; one whose process stopped reads failed. The extension is
  wired into the server separately; the tool count stays 96.
- **Pipeline jobs survive a restart.** `Studio.jobs` writes each job to `<data>/.tasks/jobs/<id>.json` instead of an
  in-memory list of the last 50, so `get_job` and the app find a job after the server that ran it restarted; a job
  whose process stopped reads failed. A pipeline job can be cancelled (`Studio.cancel_job`): it finishes the step it
  is on and marks the rest cancelled.
- **Every design is refined after it builds.** create_design, update_design, add_feature (code and standard
  features) and a kept candidate now start design refinement in the background once the revision is saved and on
  screen, so the first picture comes as fast as before. What the engine keeps lands as one more revision, "Refined: N
  changes", each change a named `refine` feature with its reason and measured change, streamed to the activity log
  stage by stage and kept in `<project>/refine.json`. The next edit cancels a job that is still running, and its
  commit is guarded by the head it started from. When the app's engine serves the same data folder, an agent's MCP
  server hands the job to it, so it does not end with the agent's turn. Off per call (`create_design(refine="off")`),
  per design (`refine = False` on the class, or `refine_design(action="off")`), everywhere (Settings › General,
  `[refine] enabled = false`) or with `FORM_REFINE=off`. New MCP tool `refine_design` (status, rerun, undo, off; 96
  tools). The workspace's dock has a Refinement panel: the stage while it runs, then one row per change with its own
  undo, undo all and refine again. Settings › General has the on/off row and a reset of what refinement learned on
  this computer.
- **Plain Recipes are refined too.** A design that is not a FeatureDesign is wrapped (`form/refine/adapter.py`): its
  build() becomes the skeleton feature (`@feature(stages=True)`), whose stages keep their own declared features, so a
  bore stays the interface it was and its faces stay frozen; refine features follow it, and undoing the last one
  gives back the Recipe as it was written. The wrapped skeleton is built once and its stages are checkpoints, so
  candidates build only their own feature.
- **Refinement engine fixes.** Frozen faces are compared by their B-rep faces (surface type, exact area and centre)
  instead of tessellation boxes at 0.001 mm, which rejected the pillow block's fillets for a re-split mesh. A
  candidate whose solid equals one already measured reuses those measures (only its materials and the analysis are
  computed again), the base is measured from the head's own build, and each candidate is built on its own so a quick
  one lands while a slow fillet still builds. Operators get the base build's check ids: the ribbed lightening needs a
  statics check to show the part still holds its load. Refine features measure the frozen features' boxes in the
  build itself (`frozen_boxes(self, literal)`), so they follow a parameter change. A candidate feature's alarm is a
  fixed 10 s instead of a share of the time left, so the same design gives the same source on any machine. The
  largest-unbroken-surface measure is taken of the bounding box's surface when that is larger, so fillets no longer
  count against it, and the edges of grip textures and grooves no longer count as sharp touch points. Styles:
  organic designs get no parting line, clean consumer knurls at 1.2 mm. The fillet hierarchy skips a free-form shell
  cut by planes (75 % free-form, 10 % planar or more): OCCT's rounds faceted on the hero helmet's crest and crashed
  the kernel on the twisted shade; the edge break rounds or chamfers those edges instead.
- **Game assets: refinement checked by a bake.** A cage design's candidates are replayed in Blender's fixed runner
  (REFINE_OPS on the low cage, at most two Blender processes) and judged on the level-2 limit surface and the
  materials() zones, so material operators show their gain; the result gets one bake, the validator and the
  triangle budgets, with the worn share from the baked mask, and the path is shortened until it passes. The game
  pipeline builds a refined design's asset from the low cage with REFINE_OPS replayed and the design's own bake source.
- **geometry_diff no longer changes the shapes the kernel keeps.** OCCT's booleans grow their arguments' tolerances
  in place, and the diff's tessellation wrote into them, so viewing a revision after diffing it could fail with
  valid=False (drag chain, hex planter). The diff now works on copies.
- **Benches with refinement on and off.** `scripts/creation_bench.py --refine on|off` waits for the last refinement
  of each brief, scores the refined head and runs the final design's checks; `--compare on.json off.json --doc ...`
  writes the gates. `scripts/game_bench.py --refine on|off --scores ...` refines each design before its asset,
  `--rescore` applies blind passes scored afterwards, and `--compare` writes docs/GAME_BENCH.md with both runs.
  Measured (docs/CREATION_BENCH.md): on the 22 creation briefs, function checks identical on and off, the design
  bench's critic up by 1.27 on average (+7 on four briefs, none lower), first stage on screen 0.0445 s median on vs
  0.0425 s off (4.7 %), 21 of 22 refinements within 20 s (the longest 20.02 s). Game bench (docs/GAME_BENCH.md):
  refinement kept nothing on five assets and its one kept change on the chest was not committed (the source would
  pass 200 kB); trim_strip and panel_line fail in Blender on the replayed cages (empty edge selection). With three
  new blind passes, scored by a model and not a person, no asset reaches a rubric of 4 (2.56-3.38); the control
  fails, as it must. The game gate is not met.

- **CAD refinement operators.** `form/refine/ops_cad.py` gives the refinement engine its first operators for
  build123d designs, each one a named `refine` feature: a three-tier fillet hierarchy (plan corners large, perimeters
  medium, footprint and details small, scaled to the part), a 0.3 mm break on the edges the hierarchy left, a
  0.4-0.6 mm parting-line groove on a split plane, a draft for moulded or cast briefs, a knurled or diamond-cell grip
  zone, a recessed panel, raised button pads for devices, and a ribbed pocket that lightens a thick floor. They
  never touch fit, access, mechanism or interface features: edges near those features are left alone, and every
  round is checked against the faces inside their boxes, because OCCT carries a fillet along tangent edges. A round
  that does not fit is tried on smaller sets and at smaller radii down to 0.2 mm instead of being dropped, and large
  sets are split so one fillet call cannot crash the kernel. Measured on the creation bench with only these
  operators, the deficit total went down on 15 of 21 designs with no check regression and identical frozen faces.
- **Cage refinement operators, and the game exemplars' art fixed with them.** `form/refine/ops_cage.py` adds the
  subdivision-cage operators of the refinement engine (support loops, panel line, trim strip, inset, kit detail and
  silhouette breakers) and the planners the exemplars are written with. New model_mesh options, every one off by
  default so existing op lists replay unchanged: `crease` and `support_loops` take `pin_corners` (where a creased loop
  turns a corner, the point gets a third creased edge, so it subdivides as a true corner instead of the round "pill"
  a creased quad becomes); `extrude_region` takes `sides: "region"` (the side walls take the extruded faces' regions;
  by default bmesh copies a neighbour's, which is not even mirror-symmetric); a face selection by region or normal can
  add a `box` (faces whose centre is inside); `geonodes_array` can turn a kit part round an axis in equal steps
  (Geometry Nodes). `kit_line` places kit parts at a constant pitch in three sizes (1 : 0.38 : 0.15) and never inside
  a frozen feature; the silhouette breakers (brow, crest, vent) are ranked by the 64 px convexity deficit of the
  views each one changes. A new kit part, `tread_block`, is a tapered chevron tyre lug. The exemplars, still
  original: the wall's bricks are blocks with true corners (corner fillet 0 mm, was about 66 mm on a 201 mm brick
  face), its coping is cut into stones, four brick corners are knocked back and the back is ashlar; its brick insets
  no longer catch slivers of the edge bevels, so the share of its normal map that points inward fell from 0.42 % to
  0.32 %. The helmet has a brow, a chin bar, a flared nape and vent pods, and its visor is one unbroken band (64 px
  convexity deficit of LOD0 0.101, was 0.049); the wheel's tread is two rows of chevron lugs at one pitch made by
  Geometry Nodes (pitch spread 0 %, was 50 % on the centre row); the remote has a parting line and a wider, deeper
  battery-door shadow gap; the chest's boards each stand proud or sit back by their own 1-3.4 mm. LOD budgets and
  every game validation check still pass (game bench, Blender 5.2.3).
- **Visible edge wear, measured; a stricter silhouette read; better wood; material refinement.** Game materials wore
  through only above `1 - 0.75 x wear`, which left about 1 % of an asset's surface worn at the usual wear, while the
  critic said "wear yes" from a material setting. The runner now wears a wider band of the convex edges (narrower
  where a part is thin) from `0.63 - 0.35 x wear`, calibrated on the six bench assets, bakes the wear mask itself and
  measures the worn share of LOD0's surface in the bake (`bake.wear` in the report). The critic reads that share:
  under 2 % is "no edge wear", over 12 % reads as damage, both cap the material at 4. On the game bench the worn
  share is now 3.2 % (helmet) to 7.0 % (wall) on five assets and 12.05 % on the sword, whose thin blade is nearly all
  edge (just over the band, so it is capped); the control blob has none. The silhouette cap now uses the
  outline at 64 px from six views and the value regions inside a 64 px lit render (`form/refine/analyze.py`): a
  nearly convex outline caps the silhouette at 4, at 3 when fewer than six value regions read inside it, at 2 with no
  detail; the old floor (complexity under 0.005) never caught the control blob. Print and model critiques are
  unchanged. Wood has cylindrical growth rings warped by noise, so long faces show streaks and end faces show ring
  arcs (darker and rougher), with a ring pitch of about a fifth of the grain size; every plank (faces between creased
  grooves and corners, a `form_board` face attribute the subdivision keeps) gets its own cut of the log and its own
  tint, and stone blocks vary a little too. The game runner is version 4, so earlier assets rebuild. New refinement
  operators in `form/refine/ops_material.py`: `material_zones` (zones by region: the body, trims and grips, and the
  fit, access, mechanism and interface parts take the style's looks), `contrast_pair` (the lightest and darkest zone
  pushed apart to a value contrast of 0.15) and `edge_wear` (game materials' wear moved toward the 2-12 % band). They
  edit `appearance()` or `materials()` as literals and change no geometry.
- **The design refinement engine (engine and analysis).** `form/refine` measures what a built design lacks as a
  deficit vector from 0 to 1 (the outline at 64 px from six views, value regions of a small lit render, proportion,
  balance over the support, detail scales, edge hierarchy, the largest unbroken surface, material zones and contrast,
  edge wear for game assets, and sharp edges where the hand goes), all computed and deterministic. A beam search
  (width 3, depth up to 4, six candidates a round, built in parallel through `candidates.run`) tries refinement
  operators ranked by deficit, style and a local ledger, and keeps a step only when the function checks are not
  worse, the faces of fit, access, mechanism and interface features are identical, the walls stay above the
  minimum and, for game assets, the validator and budgets pass. Each kept step is one `@feature(role="refine")` with
  its reason and measured change, and `delete_feature` takes it out again. Budgets are 20 s for CAD and 90 s for
  game assets. Five style tables (clean consumer, rugged tool, sci-fi hard surface, stylised fantasy, organic) are
  picked from the brief. The ledger (`refine_ledger.json` in the data folder) is never uploaded and can be reset.
  Refinement is off per design (`refine = False`), per call (`refine="off"`) or in `studio.toml` (`[refine]
  enabled = false`). The operator interface is in `form/refine/__init__.py`; the operators themselves and the app
  wiring come next.
- **UI journeys keep the keyboard.** Qt Quick shortcuts fire only in the focus window, so when another app or window
  took the focus during a run, journeys that press keys (E, 1-5, T, Esc, Ctrl+3, Ctrl+K) timed out while clicks
  still worked. A journey's key press now makes the app window active again first, and fails with a clear message
  if it cannot. The Home check for printing off now expects "Make it for: Anything / Game asset" with no My printer
  choice, as the game asset purpose made that control always shown. The kernel's alarm test reads the budget it
  reports (stretched under load) instead of expecting exactly 1 s.
- **A game critic, and six game exemplars rebuilt with it.** `critique` judges a design for a game by what the built
  game asset shows instead of CAD blend faces and appearance() zones, which held every cage-built asset at 1: bevel
  coverage (the share of LOD0's feature edges that is bevelled in the mesh or baked into the normal map), materials,
  value contrast, three detail scales, silhouette complexity against the convex hull, and edge wear, all measured from
  the asset's LODs and maps. The rubric takes several blind scoring passes and uses each item's median. Print and model
  designs are judged as before. Six original exemplars in `form/exemplars/game/` (a helmet with a recessed visor and
  cheek plates, a boarded chest with strap iron, a sword with a real fuller, a tiling brick wall, a spoked wheel with a
  baked tread, a remote with raised buttons) are built from the cage vocabulary, the kit and the material library,
  with bake-only detail kept high_only, and a deliberately bad control asset that must fail. The game bench renders
  each asset from four lit views and a 64 px outline for blind review and publishes every number in
  [docs/GAME_BENCH.md](docs/GAME_BENCH.md).
- **A detail vocabulary for cages, and a kit of original parts.** `model_mesh` has eight new ops, checked like the
  others before Blender starts: `bevel`, `support_loops`, `inset`, `panel_line` (a V groove along an edge path),
  `trim_strip` (a raised band), `solidify`, `bridge` (a tunnel or handle between two face sets) and `kit_place`.
  Edges can be picked by pairs, a path, a region's border, a box, an angle or their crease. `kit_place` puts copies
  of 33 parametric parts made by code (bolts, rivets, nuts, washers, studs, vents, grilles, hinges, straps, a buckle,
  a latch, handles, a cable clamp, a grip wrap, pommels, fuller shoulders, a spine ridge, lugs, corner caps, panels,
  a knob and seeded greebles; `form/game/kit`, nothing downloaded) on faces or snapped to points. Any op can say
  `high_only`: it details only the bake source, which comes back as the cage's optional `high` field, and never the
  LODs. Every op keeps the cage closed and consistently oriented (tested in Blender 5.2.3); existing op lists keep
  their keys and cages, and the SubD deviation report is unchanged for the reference cages.
- **Game materials, masks and bake.** A procedural material library, generated by code: wood, bare, brushed and
  painted metal, leather, plastic, rubber, stone, fabric and emissive, each with a base colour, roughness, metallic and
  a height pattern baked into the normal map, and parameters for tint, grain size and wear. Curvature, ambient
  occlusion and thickness are read from the high poly and drive edge wear (painted metal wears to bare metal), cavity
  dirt and roughness breakup; curvature, thickness and emissive maps are baked too, and the GLB carries the emissive
  map. A design keeps its materials in its source as a `materials()` method, read without running it, so Build in the
  app uses them instead of one grey material. The bake ray is measured per part from the low-to-high distance
  (extrusion the 99th percentile x 1.2, ray twice that), which takes the remote's inward normals from 1.6 % to 0 %. UV
  islands are evened out on the real surface, and LOD0 keeps its UV seams when decimated: a new check holds every
  island within 25 % of the median texel density. A cage's optional high-only mesh is baked when present. Blender is
  stopped when Form Studio quits or dies, and work folders a killed build left behind are removed. Wrong request types
  (a text texture size, a list of materials) now answer with a clear message instead of an internal error. On the six
  bench assets: every check passes, two or more materials each, and normal-map detail of 0.0055 to 0.023 (blue
  channel standard deviation; the five cage assets' flat maps before measured 0.00014 or less).
- **LODs that keep their shape, measured against LOD0.** Decimation now dissolves flat areas first, then tries an
  even collapse and collapses that hold borders, UV seams, sharp and creased edges, material boundaries, the
  silhouette from 8 views and curvature, and keeps the most held one that stays about as close to the source.
  LOD1 to LOD3 come from LOD0's own cage level at most, decimated from a level with room to spare, and the bare
  cage (whose points lie off the surface) is never a LOD. Two new checks measure every LOD against LOD0 from the
  GLB: the worst of 8 silhouettes (IoU at least 0.985, 0.96, 0.90 for LOD1 to LOD3) and the Hausdorff distance
  (at most 0.5 %, 1 %, 2.5 % of the diagonal); both thresholds are proposed. On the six bench assets every LOD
  passes both; the worst were the remote's LOD3 (IoU 0.957) and the wheel's LOD3 (1.90 %). The wheel's LOD1 tyre
  dips 0.43 % under its outer radius, rounder than a 24-sided one (0.86 %).
- **The baked normal map in the shaded view.** The Game asset sheet's shaded view applies the tangent-space normal
  map (with a switch to compare without it) and adds an emissive map when the asset has one.
- **One bake per click, and none left behind.** The app now waits for a game build as long as the pipeline lets
  Blender run, so a slow 4k bake no longer shows a false error; a second identical Build or Export while one runs
  joins it instead of starting another Blender; and quitting the app stops any Blender bake it started.

- **Game assets in the app, and two new agent tools.** "Game asset" is now a purpose on Home ("Make it for") and in
  the brief. A design for a game opens the Game asset sheet from the rail: build it in Blender, switch between LOD0
  and LOD3 with each one's triangle count against its budget, and look at it shaded with its baked maps, as a UV
  checker, one baked map as stored (base colour, normal, ORM, AO) or as a wireframe. Pick glTF/Godot, Unity or
  Unreal and Export saves every file as one zip. Without Blender the sheet shows the one-click install card; CoACD
  has its own optional card. Agents get `model_mesh` (a subdivision cage modelled in Blender by declarative ops; each
  op's preview streams into the app like a build's stages) and `game_asset`: 95 MCP tools. `design_guide` lists the
  hybrid and game topics, and `plan_design` takes a route per feature.
- **A cleaner normal bake, and Unreal collision names that match.** Parts that touch or nest (a lid on a box, a band
  round a body) used to trade surfaces in the bake: a treasure chest's 1k normal map had flat olive patches, 16.8 % of
  LOD0's UV area pointing into the surface. Surface maps are now baked with the parts moved apart (ambient occlusion
  stays in place), and the same chest measures 0.000 %. A new check fails any asset whose baked normals point inward
  on more than 0.5 % of LOD0 (proposed). Unreal hulls stay `UCX_<asset>_LOD0_NN`, named after the exported LOD0 mesh as
  Unreal pairs them; the guide and the tool now say so, and the name is built from the LOD name so they cannot drift.
- **Game bench.** Six original briefs (a sci-fi helmet prop, a stylised treasure chest, a fantasy sword, a modular
  wall piece, a vehicle wheel, a remote as CAD plus asset) made end to end by a scripted agent
  (`scripts/game_bench.py`, [docs/GAME_BENCH.md](docs/GAME_BENCH.md)). On this Mac with Blender 5.2.3 every design
  built, every STEP read back valid, the SubD-to-CAD deviation was at most 0.28 mm per 100 mm, every LOD met its
  budget and bakes took 1.0 to 2.2 s at 1k. Five of six assets passed every check; the remote failed the new normal
  map check (an inverted patch over its small button holes). None reached the aesthetic gate (means 1.62 to 2.62,
  scored by an AI agent from the renders, not by a person). Design sources made from a cage now carry Blender crease
  weights as exact or semi-sharp creases, and the packaged app ships the Blender runners and `form/game`, with a
  smoke step that builds a small cage asset.

- **Game assets: a design made ready for a game engine.** A new purpose, "game" (also "game asset", "asset de jogo",
  "Unity", "Unreal", "Godot"), is never sliced or checked against a printer. The game pipeline (`form/game/`) takes a
  design's subdivision cage, or its CAD tessellation, and makes LOD0 to LOD3 at triangle budgets (cage subdivision
  levels first, as clean quads; a level decimated to the budget only when no level fits, labelled automatic
  retopology; Decimate or QuadriFlow for CAD bodies), UVs (seams on region borders when every region is a disc, else
  Smart UV Project, then packed at one texel density), a Principled material per zone with fixed procedural wood,
  noise and brushed patterns, and Cycles bakes of base colour, normal, ORM and AO at 1k, 2k or 4k. Collision is a
  convex hull per part (at most 64 points each); CoACD is an optional one-click engine with its own Python. Presets:
  glTF and Godot (GLB, metres, +Y up, Godot's `-convcolonly` hulls), Unity (FBX, metres) and Unreal (FBX,
  centimetres, Z up, `UCX_<asset>_LOD0_NN` hulls); GLB is written by Form Studio itself, FBX and USD by Blender's exporters and read
  back in to measure their size. A pure-numpy validator checks every GLB (budgets, closed and manifold, flipped
  faces, UVs inside 0..1, UV overlap by rasterising, texel density spread, scale, the file itself) and caught 7 of 7
  seeded defects. Measured on this Mac (Blender 5.2.3, Cycles on the CPU, fast preset) with an original stylised
  treasure chest cage (502 quads): LODs of 11,940, 4,016, 2,486 and 796 triangles for budgets of 12,000, 6,000,
  2,500 and 800, no UV overlap, every UV inside 0..1, texel spread 1.08, the GLB, FBX and USD at the design's size
  to 0.000 %, and all bakes in 2.8 s at 1k, 11.5 s at 2k and 52.3 s at 4k. The fixed runner gets a JSON job and numpy
  arrays, never code; Blender runs as the modelling bridge runs it, and network access is not isolated by the
  operating system. The MCP tool is `game_asset`.
- **Blender as a modelling editor, driven by ops instead of code.** An agent can model a subdivision cage in Blender
  with a declarative op list (new cage from a primitive or quads, extrude a region, loop cut, move, crease, name a
  region, mirror, Geometry Nodes array and scatter, bounded sculpt brushes, voxel or QuadriFlow remesh). Every op is
  checked before Blender starts, a fixed runner executes it, each op streams a level-2 subdivision preview into the
  same live stage view a build uses, and the result comes back as cage data (points, quads, creases, named regions)
  for a design's source and `form/craft/subd.py`. Replaying an op list gives the same cage. Measured on this Mac
  (Blender 5.2.3): a run is about 0.5 to 1.1 s, most of it Blender starting; modelling ops take under 1 ms each,
  scatter 3 ms, voxel remesh 29 ms and QuadriFlow 0.33 s on a 2000-face target; Form's Catmull-Clark matches
  Blender's level-3 subdivision to 1e-7 of the part's size. Blender runs with factory settings, offline mode, no
  auto-run scripts, a scrubbed environment, a temporary folder and a time limit; network access is not isolated by
  the operating system. The MCP tool is `model_mesh`.
- **A construction route per feature.** A plan now says how each feature is built: kernel (exact build123d with
  form.craft), subd_cage (a quad cage whose limit surface becomes CAD patches), sculpt_recon (sculpted mesh detail
  fitted back to a surface) or procedural (form.patterns in the kernel, MeshTexture or Geometry Nodes on the mesh).
  The new router (`form/router.py`) reads the route from the feature's words in English and Portuguese, or the helpers
  its how names, and returns the words that chose it with evidence "heuristic". A plan can also state `route` on a
  feature. A feature it cannot read is built in the kernel and added to the brief's unknowns. plan_design warns when a
  hole, thread, magnet pocket, snap, bearing seat or mating face sits on a mesh-only route. Every step lists the real
  helpers for its route; model_mesh is named only as "when available". On a labelled set of 97 phrases the router
  agrees with the labels on 99.0 %. That set was written alongside the vocabulary. On a held-out set of 36 phrases,
  never used to tune it, it agrees on 88.9 %; its four misses are sculpt phrases it does not recognise, and it reports
  them as unknowns. New design_guide topics: `hybrid` (when to use each route, how a SubD cage becomes CAD,
  editability, limits) and `game` (budgets, LODs, UVs, bakes, collision, engine presets; it says when the game
  pipeline is not in the build yet).
- **Subdivision cages become exact CAD where the surface allows it, and say so where it does not.** A quad cage
  (`craft.subd.Cage`) now takes creases and open borders: an infinitely sharp crease is a C0 border between patches
  that carry the crease's B-spline exactly, a semi-sharp crease (sharpness s) is resolved by ceil(s) subdivision
  levels, and an open border follows the B-spline boundary rules, closed by a planar cap (exact), an OCCT filling cap
  (approximate, noted) or `close="thicken"`. Regular patches are merged into multi-span bicubic B-spline faces: the
  test torus is 4 faces instead of 96, the cube-sphere 66 instead of 216. Named regions (`regions={"lid": [...]}`)
  label faces (`region_faces`), give a point and normal for `craft.magnet_pair` (`region_frame`) and a slab that
  follows the skin for cuts and `craft.parts` (`region_tool`). The new `craft.subd_report` measures every result
  against the true Catmull-Clark limit (a level-6 limit mesh): max and RMS deviation, seam angles, BRepCheck, face
  count and a STEP round trip. Measured on the reference cages: regular torus and open tube 4e-14 mm (exact);
  cube-sphere 0.0046 mm on 89 mm, worst seam 0.73 degrees; genus-2 slab (3 levels) 0.027 mm on 108 mm, worst seam
  1.84 degrees (over the 1 degree target; 1.08 at 4 levels); creased lenses about 0.003 mm, 0.58 degrees. STEP
  re-imports valid with the same volume, and a hole cuts cleanly through all seven. Only a skin whose patches are all
  regular is called exact; anything near an extraordinary vertex is reported as the measured approximation it is.
- **The view from below is lit, and moving the view no longer flashes dark.** Faces that look down get the light
  the bench bounces back up (an ambient term in the clay shader that grows toward the floor), so the Under view and
  every elevation down to -89 degrees show shaded clay instead of a black shape: on the test enclosure the Under view
  went from 12 % to 61 % of the iso view's brightness in the dark appearance. Seen from below, the floor and the
  build plate are a translucent ground the part reads through instead of disappearing, and they thicken in over the
  first few degrees under the bench, so going under is a glide. Shadows reach as far as the camera can zoom out (they
  popped out past 1400 mm), the floor and plate keep a depth gap that grows with distance, and a camera frame that is
  not a finite number is logged once when the last good one is kept. A new UI journey (viewport_light) checks every
  standard view and an elevation sweep at 30, 420 and 3000 mm in both appearances.
- **Every optional engine installs in one click.** Each row in Settings › Software has its own Install button (or the
  official download page when Form Studio cannot install it here), with its size and licence always on the card. In the
  packaged app, CAD-Recode and CADFit get a Python of their own: Form Studio downloads a pinned uv (its SHA-256 checked
  before use), makes `<data folder>/.engines/<engine>` with Python 3.12 and pinned libraries, fetches the weights, and
  runs the engine out of process with that interpreter. CADFit is now in the list and its code ships with the app (its
  LICENSE and PERMISSION.md included); installing it turns it on. A non-commercial licence (CAD-Recode, CADFit) is shown
  as one line before anything is downloaded, and pressing Install there accepts it. The CADEvolve corpus downloads in
  the app everywhere. Progress and errors show on the row, and a failed install leaves things as they were.
- **Deploy notices an old app in the Trash.** `scripts/deploy_mac.sh` says when an old Form Studio is still in the
  Trash (Spotlight keeps showing it) and asks you to empty it; it never touches the Trash.
- **One conversation on screen at a time.** Every step an agent's run takes names its conversation. Only the open
  conversation's agent draws its build stages, opens its designs and turns the view. Another conversation at work is
  one calm note ("The agent is working on Staged block"), over the view or in the top bar, and Show opens that
  conversation. The open design and screen never change because of it, and its steps are not written into the open
  conversation. An agent outside Form Studio's chat is followed only while no conversation here owns the open design.
- **Concepts in the conversation.** When the agent proposes concepts, the conversation shows them as a card: a
  picture of each, its rationale and Pick, plus Side by side for the full sheet. The agent rendering a concept no
  longer closes the concepts sheet or opens that concept's workspace. Concepts proposed while a design is open now
  open their sheet there too.
- **A print names its printer.** A design made for printing shows its printer in the top bar in every stage, and it
  stands on its build plate from Describe on. In Describe and Design the plate can be hidden. A 3D model still shows
  no printer and no plate.
- **The command palette keeps the keyboard's pick.** A pointer resting where the list opens no longer moves the
  highlight; the pointer takes the highlight only once it moves.
- **"Make it beautiful" now gets a design method, not one build.** Every chat message is checked for a request to
  look special, in English, Portuguese and Spanish and with misspellings ("beautiful", "impress me", "premium",
  "bonito", "lindo", "que impressione", "beatiful"); printing words such as "impressão" and "impressora" and plain
  praise ("awesome, now...") do not count. On a hit the agent's instructions carry a mandatory loop: read the
  aesthetics guide and two close exemplars, write a design-language statement (archetype, gesture, proportion, three
  radius tiers, surface break, materials), build skeleton first, photograph from three angles, score the new
  aesthetic rubric in critique, fix the lowest items and repeat at least twice before presenting. Rounding is never
  dropped after a fillet fails.
- **The aesthetics guide is an industrial designer's method** (`design_guide(topic="aesthetics")`): archetypes,
  proportion systems, G2 continuity with superellipse plans, lofts and sections, a three-tier radius hierarchy with
  `craft.safe_fillet` fallbacks, shadow gaps and split lines, detail rhythm, and material and colour pairing through
  `appearance()`, each with the code that does it.
- **critique has an aesthetic rubric:** silhouette, proportion, continuity, radius hierarchy, break-up, detail rhythm,
  material and "would sell", each 0-5 from the agent's look at the photos (`critique(..., aesthetic={...})`), capped
  by what the geometry and the appearance zones support (no radii caps the radius hierarchy at 1, one colour caps
  material). It passes at a mean of 4 with nothing under 3, and every pass is recorded.
- **Eight premium everyday exemplars**, each a FeatureDesign built skeleton first with two to four material zones:
  cable_dock, ribbon_phone_stand, valet_tray, lamp_base, cube_speaker, slim_remote, floating_wall_hook and
  sofa_arm_clip.
- **Exemplar photos keep their materials.** Seven exemplars named finishes that do not exist ("satin", "clear"), so
  their photos fell back to one colour; they now use real finishes, and a test checks every exemplar.
- **The spending cap is said plainly.** A reply that reaches the per-message cap no longer shows
  `error_max_budget_usd`: it says it stopped at the cap, what it kept (new designs, the revision reached) and that the
  cap is in Settings › Chat › Spending cap per message. The default stays $3.00.
- **Claude Code finds Form Studio's tools on the first call.** Its instructions name the tools with the `mcp__form__`
  prefix its tool list uses (a bare `design_guide` failed with "No such tool available"), and its runs set
  `ENABLE_TOOL_SEARCH=false` so no Form Studio tool is deferred behind a search tool.
- **Sheet labels draw accented names** (Capacete de herói, Peça) with the app's own font instead of boxes.

- **Feature records stay true.** A feature left out because it made more parts than the design declared is built
  again as soon as `solids` is raised (the record follows the part count it was checked against). Only a feature that
  ran past its own time budget is written down as hung: a whole build that runs out of time no longer blames the
  feature it happened to be on. Hang marks expire after a day, checkpoints and records follow the Form build (its
  version and the code that shapes solids), so a fix in a new version reaches designs checkpointed before it, and the
  records kept next to the checkpoints are pruned with them. A feature's checkpoint now also follows the mixins its
  class inherits, members read through `type(self)`, and every way of reading the values; anything it cannot follow
  rebuilds instead of loading a stale checkpoint.
- **fit_params has a time budget** (`budget_s`, 120 s by default): the search stops when it is up, keeps the best
  values found, says why it stopped, and reports progress while it runs. Sending a step to the reconstruction helper
  is bounded by the step's time too.
- **CADFit runs inside the kernel worker** and keeps within the reconstruction's hard deadline (its slice is never
  longer than the time left). The packaged app ships CADFit's hook and licence files but not its search; there it
  says it needs form-studio[cadfit]. THIRD_PARTY_NOTICES.md has a CADFit entry.
- **Hero helmet:** the lenses tilt 9 degrees instead of 16, the colours are graphite and teal, and the faceplate's
  magnet tabs are gone from its face (the flange holds the pockets behind a flush face).

- **Scanned meshes reconstruct.** Mesh to CAD now fills the small holes a scan leaves (the missing triangle put
  back, or the triangulation with the least area and bend, so a hole across an edge keeps the edge), lists what it
  filled, and refuses a mesh only when a hole is too large to fill without guessing. It measures the scan noise and,
  when there is any, reads the sketches from a copy with every vertex put back on its fitted plane, cylinder or cone;
  the result is still measured against the mesh as given. On the bench, the bolt flange with 1 % of its triangles
  removed went from refused to 100 % B-rep and 100 % editable in 14.8 s, and with 0.01 mm noise (measured: 0.0101 mm)
  from 0 % editable in 296 s to 100 % editable in 26.6 s, 0.042 mm from the noisy mesh.
- **Candidates are ranked by the critics too.** The learned engine, CADFit and any future generator are one list in
  the pipeline, each through the same steps: verified against the mesh, then the occupancy, void and opening gates,
  then the share of the surface their Params drive. A candidate that fills a cavity solid now loses to the faithful
  one even when it is as close to the surface. The gates use at most 4 % of the time budget (about 0.5 s per part on
  the bench).

- **A hang or a crash never loses the work.** When the geometry kernel times out or crashes during create_design,
  update_design or add_feature, Form Studio keeps what was built: a FeatureDesign keeps the features finished before
  the one that hung (loaded from their checkpoints on disk, nothing built twice), any other design keeps its stages,
  and the result is a partial revision that names the feature and the seconds it ran. Every feature has a time
  budget (90 s by default, `@feature(..., budget=s)`): a Python loop past it is stopped by an alarm, a hang inside
  OCCT is stopped by the kernel's supervisor, and the next build leaves that feature out at once instead of waiting
  for it again. A boolean inside a feature never runs past the feature's budget, and a plain boolean that alone uses
  the boolean time bound is not followed by a pre-flight or rewrites.
- **Several parts, skeleton first.** A design that declares four parts can start from a one-solid skeleton: each
  revision is saved while parts are still to come (flagged partial, release blocked), and add_feature(kind="code")
  makes a revision per part. A feature says how many parts it adds with `@feature(..., parts=N)`; the solid count is
  then checked after every feature, so a "part" that fuses into the shell is caught at that feature with the counts.
- **Checkpoints follow what a feature reads.** A feature's checkpoint is keyed on its own code, the helpers and
  methods it actually uses, the values it actually reads and the feature before it. Changing `solids`,
  mesh_texture(), appearance() or a parameter that no feature reads rebuilds nothing; changing a value rebuilds
  only the features that read it and those after them. Part names of craft.parts() results survive the disk.
- **Every feature is checked as it is made:** its solid count and volume change are in the build log, a cut that
  removes nearly the whole body is caught, and the hint follows the measured cause (no solid, an invalid solid, the
  wrong part count, not a solid at all) instead of always suggesting a boolean overlap.
- add_feature(kind="code") shows the feature's stages live in Form Studio while it builds and returns the six-view
  sheet and the section like create_design. Old draft files (the live stages of an attempt) are cleaned up.
- A design with an assembly keeps its mesh texture on the parts that carry it in the view and the render sheets.
- Form Studio shows a partial revision calmly: a "partial" badge beside the revision in the header, left-out features
  marked "left out" in the feature list with the measured reason, and the reason in the conversation in whole
  sentences instead of cut mid-sentence.
- Creation bench: a true multi-part skeleton-first brief (a speaker pod: shell, faceplate on a magnetic lip, two
  lenses, added part by part) and an injected kernel hang, and the bench reports refused vs partial revisions, hangs
  with the project still there, and the checkpoint hit rate.

- **Twelve new design examples, ported from CADEvolve's hand-written seeds.** A bearing flange, a braille door sign,
  a compression spring with closed and ground ends, a connector panel with D-sub cutouts, a door wedge, a fan to hose
  adapter, a flat flask, an I-beam, a flanged pipe elbow, a pipe saddle clamp, a two-part enclosure with screw posts
  and a hubbed spur gear with involute teeth. Each one is built one feature at a time (skeleton first), checks its
  own numbers, and names where it came from: kulibinai/CADEvolve at e30e635, Apache-2.0, modified (rewritten for
  build123d and Form Studio). The licence is in form/exemplars/LICENSE-CADEvolve. There are now 56 examples; each new
  one builds in under 3 s. `scripts/exemplar_check.py` now fails a design when one of its features was skipped.
- **An optional reference corpus for the agent.** `form install exemplars.cadevolve` downloads CADEvolve's dataset
  (4.73 GB, Apache-2.0, both shown before anything is downloaded; never pre-ticked) and keeps only its parametric
  CadQuery generators: nothing from the ABC or ShapeNet folders is written to disk. Design example search then adds
  up to two of them after Form Studio's own examples, labelled "reference CadQuery, not the Form API". They never
  rank above a Form Studio example, and without the corpus search works as before.
- **The hero helmet exemplar, redesigned and built one feature at a time.** It is now a FeatureDesign: the skin is
  fitted once in setup(), the shell is the skeleton, and each of its eleven features is its own method, so an agent
  learns the route the design guide teaches. The design is new: rounded pill lenses tilted up in a raised bezel, a
  smooth faceplate that stands 0.4 mm proud of the shell with a thin frame and one brow ridge, a crest of two stacked
  bands with pointed ends, raked ear pods, a panel line that runs from the pods round the nape, a longer chin and a
  lower edge raked up to the nape, and crisper hex panels on the shell only (18 mm tiles, 0.9 mm relief). The two
  small circles that showed on the faceplate were measured with rays: no pocket broke through (1.9 mm of plate was
  left), but the pocket floors sat within the renderer's edge tolerance. The lens magnets now sit in a 1 mm seat
  inside the faceplate, so 3.3 mm or more of plate covers each one, and a raised tab covers the lower faceplate
  magnets. Every magnet pair stays coaxial with its 0.6 mm floors measured, and the four parts keep their measured
  clearance. It builds in about 25 s.
- **The residual loop for remodels.** Two new MCP tools (93 in all) for rebuilding a mesh as clean CAD.
  `reference_residual` lists what is left between the design and the mesh as named bodies: missing material to add,
  extra material to cut, each with its volume, centre, axis, size and shape. Alike bodies are grouped as one pattern:
  bolt holes around a circle read as a polar pattern at equal angles, holes on a row or a grid read with their pitch.
  `fit_params` tunes only the Params the design declares, inside their limits, by bounded least squares, with every
  evaluation a real build. It keeps the result only if the design gets closer to the mesh, so it never makes the
  deviation worse. The `reference_parts` guide now teaches the loop: build one feature, check the residual, keep the
  change only if it drops, stop after three stalled steps, and deliver the revision with the smallest residual.
  Measured on a scripted remodel of a six-hole flange (tests/test_remodel_residual.py): 0.1 mm was reached in 6 MCP
  calls with the residual tools (final Hausdorff 0.0099 mm), against 18 calls with compare_to_reference alone
  (0.0142 mm). The residual idea (a work list of missing and extra bodies, angles about an axis, pick-best and the
  stall rule) comes from kulibinai/cadmageddon (MIT); this is an independent implementation.

- **Mesh to CAD keeps its time budget.** A reconstruction no longer runs past its budget (240 s by default): the
  program route, Layer 1 and the feature search each run in a child process that is stopped when its time is up
  (one OpenCascade sewing of 19 faces took about 170 s on a filleted block, and nothing in Python can interrupt
  it). The result is the best found in time, and the report lists what was cut short (`cut_short`, and a note on
  the result). The filleted block now comes back in 163 s instead of 820 s. The sketches route also skips the other
  directions when less time is left than the main direction alone took.
- **The time budget holds in the packaged app too.** The bounded steps now run in one warm helper process started
  the way the CAD kernel worker is (a multiprocessing spawn process, which the packaged app supports), never a fork.
  Layer 0 and the optional learned engine are bounded as well, Layer 0 always keeps enough time to give the exact
  copy, and `form reconstruct --budget SECONDS` sets the budget. A box with four holes no longer tries to be a
  turned part (its corners lie on one circle, the middles of its sides do not), which had cost it about 10 s.
- **Small rounds can grow.** A corner radius Param may now grow by at least 0.5 mm (it was 30%), so a 1 mm fillet
  on a turned shaft is a dimension you can change; whether it fits its corner is what the build checks.
- **Mesh to CAD has critics beyond the distance to the mesh.** New gates (`form/recon/gates.py`) compare a
  reconstruction with the part in three ways. Occupancy fills both on one voxel grid and gives the slice IoU on X, Y
  and Z. Openings check that every hole, slot and pocket in a plane section has the same shape in the result. Voids
  find a cavity filled solid. Every threshold is relative to the part's size. A round hole modelled square now fails,
  and so does a block filling a cavity whose faces all lie on the part, though both stay close to the mesh. A
  GMS-compatible surface score sits beside them (`form/recon/gms.py`). `scripts/recon_bench.py` reports occupancy
  IoU, GMS and the gate verdict for every part. It adds a scan-artifact class (noise, quantised coordinates and
  missing faces) and a before-and-after table. `scripts/cadena_bench.py` scores real parts from CADENA-Bench. It runs
  only when you ask: it downloads nothing without `--download`, writes nothing into the repository and reports
  aggregates only. `THIRD_PARTY_NOTICES.md` credits the projects whose ideas these build on, and the app ships it.
  The gates do not yet choose between candidates in the pipeline.

- **CADFit as an optional mesh-to-CAD candidate.** With `[recon] cadfit = true` (and `pip install form-studio[cadfit]`), Make editable also asks CADFit (Nehme, Whalen, Ahmed, ICML 2026) for a CAD program: sketches read from planar and axis slices, extrusion heights and revolve axes measured on the surface, a greedy IoU search with beam refinement and backward pruning, then residual cut and add passes. It runs in a child process within a quarter of the budget (20 to 120 s) and is stopped at that deadline, keeping the best program it had sent. Its program is read, never run, by a small CadQuery reader on build123d, translated into Params, built and verified against the mesh like every other candidate; one that does not verify is reported and never the result. Off, nothing changes. CADFit's code is CC BY-NC 4.0 and is included in `form/recon/cadfit/` with its author's permission; Form Studio's MIT licence does not cover that folder (PERMISSION.md lists what was changed in it).
- **Watch the design being built.** While an agent creates or rewrites a design in a conversation, the 3D view draws
  each stage the moment the kernel has built it, before anything is saved. Each new stage grows in over the one before
  with the same fade and rise as a new revision, and a quiet caption says what is being built: "Building Bore (2 of
  4)". The last stage always grows in before the save takes over, even when both arrive at once. When the agent of
  your conversation starts a new design while another is open, the workspace hands over to the being-designed view
  and its stages are drawn there. When the design is saved it takes over in place, with no blink, no screen fade and
  no second build-up. If the
  partial build dropped a stage, the saved design is what stays. A feature a partial build left out is one calm line
  in the conversation, with the reason the build measured (for example, a 40 mm fillet on a 12 mm edge), not an
  error. Each stage event and draft now also says where the stage is in the design (`at`, `of`) and its label.

- **A failing feature no longer loses the design.** When an agent's `create_design` fails on one feature, the stages
  that built before it are saved as a partial revision and shown, instead of nothing being saved. The revision says
  which feature failed and why, and release stays blocked until that feature builds. `partial=False` keeps the old
  all-or-nothing behaviour. While a design builds, each stage is shown as soon as it exists: it is written as a draft
  and named in the activity log.
- **Designs built one feature at a time.** A design can be written as a `FeatureDesign` (`form.featureprog`), with one
  `@feature` method per feature. A feature that fails is left out with its diagnosis, and the features after it still
  build. Each feature's result is kept as a B-rep checkpoint, keyed by its code and everything before it. Fixing one
  feature rebuilds only that feature and the ones after it. `update_design(feature=, code=)` sends a single method,
  `add_feature(kind="code")` adds one, and `remove_feature` removes any feature of such a design. Each revision has a
  build log that says, for every feature, whether it was built, loaded from its checkpoint or skipped.
- **Skeleton first, taught and planned.** `design_guide` now opens with the creation loop: write a `FeatureDesign`,
  create the skeleton alone, look at it, then add one feature per call. A feature gets two retries; after that it is
  deferred and listed at the end. A risky feature goes through `build_candidates`. The guide carries a complete
  example that builds. `design_brief` returns a route (prismatic, revolve, skin+features or mechanism) and how its
  skeleton is built. `plan_design` refuses a plan that names a helper that does not exist and lists the closest real
  names. It returns the plan as ordered steps, each with a risk class and a fallback. A brief with magnets, a lid, a
  faceplate or separate parts must declare its parts, the clearances between them and its magnet stock.
- **Exemplars as steps, and better routing.** Every exemplar is also exposed as its features in build order, each with
  the helpers it uses. A query for a full-face helmet with separate parts, magnets or lenses goes to the hero helmet
  exemplar first.
- **One feature, several versions.** `build_candidates` accepts `{label, feature, code}` entries: versions of one
  feature of a `FeatureDesign`, built on the checkpoints of the features before it.
- **Fixing a feature always rebuilds it.** A feature's checkpoint key now includes its own code for designs written
  through the tools. Before this fix, a changed feature with the same values could load the old result. A parameter
  may also name a feature that is not written yet.
- **Creation bench.** `scripts/creation_bench.py` runs twenty original briefs (mechanical, creative, organic,
  assemblies) through the MCP tools with a deterministic scripted agent. It writes measured JSON: first and final build
  rate, time to the first visible solid, features built against planned, deferred features, the critic score and the
  total time.
- **Organic shells from one fitted skin.** `craft.skin_from_sections` samples a section stack (for example
  `helmet_fullface`) and fits one B-spline grid to it, with its deviation from the sections measured and reported
  (the full-face helmet: max 1.4 mm, mean 0.31 mm on a 22 x 22 grid). The shell is three faces, and every band, ledge,
  visor and lens is the same skin offset along its normal, so no two of them share a face. The carbon helmet exemplar
  now builds in about 27 s on this route, where the audit measured 163 s for the lofted one.
- **Separate parts, splits and magnets.** `craft.parts(shell=..., visor=...)` returns separate parts and measures every
  pair against a clearance, instead of `fuse(a, b, max_solids=2, min_solids=2)`, which fails as soon as parts touch
  (the helmet exemplar no longer teaches it). `craft.split` takes a faceplate or hatch out of a skin shell with a lip
  it rests on and the same gap all round; `craft.lens` makes a lens from the inner offset skin. A `craft.MAGNETS`
  stock table (6x2, 6x3, 8x3, 10x3 mm) with press, glue and printed-in clearances, a 0.6 mm floor checked on the
  built part, and pocket pairs that are coaxial by construction. The pull force stays unknown unless a datasheet
  value is given.
- **An original hero helmet exemplar.** `hero_helmet`: a shell with a crest, ear pods and chin grille, a magnetic
  faceplate on a lip, two lenses on magnets and a hex panel texture, built in four parts in about 12-20 s. It is
  found first for "full-face helmet separate parts magnets lens texture".
- **A neutral radial pattern.** `craft.organic.web_heightmap` is now `radial_grid_heightmap` (straight rings by
  default; the old name still works), and the hidden mask exemplar describes its hex default without any likeness.
- **Mesh to CAD: two numbers, never merged.** Every reconstruction now reports, beside editable (the share of its
  Params that are real dimensions and move 0.5 mm), the share of its surface that is real CAD faces rather than a
  facet copy of the mesh (`result.brep_pct`, counted only within the tolerance). `scripts/recon_bench.py` measures
  both per part class (bracket, flange, turned shaft, enclosure with holes, filleted block) and runs each part in
  its own process, so a part that crashes the kernel is reported instead of ending the run.
- **Turned parts as one revolved profile.** When every section of a part is one circle (and at most one bore) about
  one axis, the program route reads its half-section and revolves it: steps, chamfers, grooves and rounds become
  diameters, levels and radii. Holes off the axis stay features.
- **Polar patterns.** Equal holes equally spaced on a circle become one pattern with a pitch-circle diameter Param
  that moves every hole at once.
- **A stepwise loop and a guard on other directions.** A stepwise loop (`form/recon/stepwise.py`) adds one feature
  that the batch kept as the mesh back at a time and keeps it only when the residual against the mesh drops, and
  drops features of the other directions the result does not need. A result carved by the other directions now
  replaces the main direction's verified one only if it does not lower the share of its Params that are dimensions
  and does not bring more than 1.5 times the Params: measured on the bench, reading the other directions above 80%
  gained surface but cost editability, so they still start below 80%.
- **Wider honest ranges.** A level or coordinate Param may now move 0.4 of the way to the nearest value on each side
  (it was the nearest value on either side), so a 1 mm chamfer's levels can move 0.5 mm away from each other.
- **No crash on corner blends.** Defeaturing in the feature tree runs in a forked child: a block whose rounded edges
  meet in corner blends crashed the whole reconstruction (a segmentation fault in OpenCascade); now that feature
  simply stays.
- **Optional learned engine (CAD-Recode), opt-in.** `form install recon.learned` shows its size (3.09 GB of weights
  plus PyTorch) and its non-commercial licence (CC BY-NC 4.0) before anything is downloaded; the download refuses to
  start without `--accept-licence cc-by-nc-4.0`. It is never bundled and runs offline. Its CadQuery output is read,
  never executed, as sketch extrusions, placed and snapped onto the mesh, and accepted only through the same verify
  and comparison gates as every other candidate. Not installed, nothing changes.

- **One boolean engine, measured.** `craft.fuse`, `craft.cut`, `craft.safe_union`, `craft.safe_cut` and
  `craft.safe_intersect` now share one path, `form.craft.boolean`, instead of two blind ladders. The plain boolean
  runs first and is checked: a valid solid, the allowed solid count, a volume the operation can give, and, when it
  looks like a silent failure (a cut that removed almost nothing), a mesh check (manifold3d) that catches the
  valid-looking wrong result. When it fails, the engine measures overlap, gap, coincident faces and operand validity,
  names one cause (coincident faces, a grazing tool, parts that touch, an invalid operand, a gap...), tries only the
  repairs for that cause within 25 s, and says what it measured, with a hint for that cause. Two halves that touch
  fail at once with "keep them as separate parts" instead of four blind retries. It no longer tells you parts do not
  overlap when they do. The repairs run on pristine copies, because a failed OCCT boolean raises its operands'
  tolerances in place, which left the body broken for every later try (most of the old "invalid result" ladders).
  A mesh result is only returned when asked for, and is labelled.
- **Make editable makes it editable.** A mesh is now read the way it was modelled: sketches of lines, arcs and rounded
  corners extruded and lofted between levels, with every coordinate, level, radius and diameter a Param (pooled,
  snapped to round numbers and standard hole sizes, mirrored about the centre, each saying where it came from). What
  does not read as a sketch is kept as the mesh's own slices beside the parametric features instead of turning the
  whole part into an embedded solid. Prismatic parts come back fully editable in seconds to a minute (the numbers per
  part are in `docs/RECON_BENCH.md`).
- **Editable first, and honest about it.** Every reconstruction, its activity line, the multi-part lines and the
  app's toast lead with how editable it is and its distance to the mesh, and say when the result is outside the
  tolerance you asked for. Editable now counts only Params that are real dimensions (lengths, diameters, radii,
  angles, levels; a mirrored ±X is half a symmetric width) and that move 0.5 mm with the design still building; the
  positions of sketch corners do not count. The share of the surface its features make is reported beside it. A new
  design is named "(editable)" only when at least half its Params are such dimensions, "(partly editable)" below
  that and "(exact copy)" when none are; a 0% result is never called editable.
- **The old route keeps its time.** The sketches route may use a quarter of the reconstruction budget, and the
  layers below it then get the whole budget they had before it existed, so a part it gives up on is no longer
  starved of time for finding planes, cylinders and features.
- **Faster and never silent.** Surface fitting uses analytic derivatives (segmentation is several times faster),
  and a reconstruction reports progress about every second.
- **Exact edges.** The program route's faces are exact by construction: every edge is where two sketch features meet.
- **Parts that fit stay fitting.** `form.recon.assembly` ties the dimensions where several reconstructed parts meet
  (walls across a gap, a pin in a hole) into one Param plus a clearance and writes them as one multi-part design.
- **A benchmark.** `scripts/recon_bench.py` writes `docs/RECON_BENCH.md`: editable share, deviation, time and a sweep of
  every Param, before and after, on the synthetic fixtures.
- **A kernel pool: builds run side by side.** The CAD kernel now runs as a pool of worker processes (one per performance core, up to 4; `[kernel] workers` in studio.toml or `FORM_KERNEL_WORKERS`). Independent builds no longer queue behind one process: three reconstructions, a concept board or a batch of candidates take about as long as the slowest one. A call for a design goes back to the worker that has it cached, so a view, a selection and an export of one design still build it once. Four candidates of the fluted-cup exemplar build in 2.8 s against 2.3 s for one (9.1 s one after another). A build's time limit stretches with the number of workers busy beside it (and the machine's load), so three heavy concepts at once, such as helmets, no longer run out of time.
- **Failed builds explained.** A build that fails now says, in plain words, which operation failed (fillet, chamfer, loft, sweep, shell, fuse, cut), on which line and for which feature, the likely cause read from the shapes on that line (an invalid operand, parts 0.01 mm apart, loft sections with 6 and 14 edges, a fillet wider than the shortest edge it must fit on, the stage where the solid count went wrong) and ranked fixes, instead of "BRep_API: command not done". The kernel's own text is kept in the diagnosis for reference. Every one of the seven kernel failures of a recorded owner conversation, replayed as fixtures, is diagnosed with its stage and a repair.
- **Operations that degrade gracefully.** `craft.safe_union`, `safe_cut`, `safe_intersect`, `safe_loft`, `safe_fillet`, `safe_chamfer`, `safe_shell` and `safe_sweep` try the plain operation, then fuzzy booleans, repaired shapes (`craft.repair`: ShapeFix and face merge), re-seamed and resampled loft sections (`craft.reseam`), ruled and pairwise lofts, smaller fillets and thinner walls, and note what they gave up. They stay honest: a gap is closed only under 0.05 mm, a cut that removes nothing is a failure, a loft section with a hole is never filled. Eight of the nine failure fixtures build through them; the ninth is a part that really is 3 mm away, and says so.
- **Several candidates, the best one kept.** `build_candidates` (MCP) builds two to six versions of a risky design or step at the same time, one kernel worker each, scores every one (a valid solid with the declared count, brief targets such as size and solids, critique quality and the product-class silhouette, fewer craft fallbacks, and the share of parameters that still build at both ends of their range) and makes the best one the design. A candidate that fails carries its diagnosis and never sinks the others. 91 tools.
- **Concepts that build are kept.** `propose_concepts` builds every concept at the same time; the ones that build go on the board and the others come back with their diagnosis and how to add a fixed one to the group.
- **43 exemplar designs.** The exemplar library grew from 14 to 43: mechanical parts (linear slide, shaft coupler, gusseted bracket, pillow block, 2020 corner bracket, cam follower, action-camera mount), consumer products (headphone hook, soap dish, desk organiser, earbud case, wall hook, game controller, lens cap), organic forms (prop mask, creature horn), textured parts (hex planter, perforated lampshade, woven basket, fluted cup, bike grip), assemblies (ratchet wrench, bottle and cap, robot head), helmets (open-face, sci-fi prop) and enclosures (electronics box with insert bosses and a seal lip, sliding battery box, handheld shell). `design_examples` ranks them with BM25 over names, tags, techniques and lessons, filters by category, and returns technique snippets: `design_examples(technique="snap-fit lid")` gives just the block that does it. The character mask, the half-face prop mask and the sci-fi helmet stay in the repo but are not offered to the agent until they are redone: their sculpted forms read as eggs. A test lays the packaged app out from `packaging/form.spec` and fails unless it serves at least 40, and the packaged smoke test checks the running app.
- **Agents know their sandbox.** Every agent is told what it can and cannot do (Codex: a read-only shell with no network; Claude: no shell) and which Form Studio tools to use instead, so it stops spending steps on `python`, `curl` or `cat`. Its instructions now also name the robust helpers, the build diagnosis and `build_candidates`.
- **Usage limits without the upsell.** When an agent reports its plan's usage limit, the conversation gets the facts only: which agent, when it can work again ("in about 2 hours", "at 9:34 PM", or the time and the day when it is not today), that the conversation and the designs made so far are kept, and what to do now. No upgrade or purchase links. The card appears only for a real plan limit: a short rate limit, an HTTP 429 or the word "quota" in another error is shown as the error it is.
- **Effort follows the task.** A mesh to make editable, a mechanism, a styled or organic form, a texture or several parts runs at high reasoning effort, a new design at least medium, whatever the default for quick edits is; effort is never lowered. The conversation says so when it happens ("Using high effort for this task: gears"), and Settings › Agents › Raise effort for hard tasks turns it off (`[chat] auto_effort`).
- **Creation first in every word.** The MCP server's instructions and its guided prompt now start from designing (create_design, render, update), with exporting, slicing and release only for a design made for printing; "Start blank" opens an empty design, not an empty build plate. iPhone photos (HEIC) attach and are converted to JPEG so any agent can look at them. A link that cannot be reached says why in plain words ("could not find files.example.com") instead of the system's error code, and the Thingiverse advice no longer asks you to set an environment variable.
- **New designs are 3D models in the agent's instructions too.** The agent is told new designs are 3D models unless the request (or Settings › New designs are made for) says printing; that the person owns a printer is context only.
- **Design bench and evaluation.** Twelve new briefs (a sliding wallet, an open-face helmet shell, a shaft coupler, a pillow block, an enclosure, a sliding battery box, a bottle, a controller, a textured planter, a ratchet, a sci-fi helmet, an earbud case). `scripts/design_eval.py` runs the briefs through a real agent in Form Studio's chat and records first-build and final-build rates, builds tried and the bench score; `scripts/bench_timing.py` times the bench on one worker and on the pool; `scripts/exemplar_check.py` builds, checks and draws any design.

- **One request, one design.** A conversation now keeps the list of every design it made or touched, with its role (made, concept, continued) and whether it is still there or in the trash. Form Studio records each design the moment a tool creates, picks, copies or reconstructs it, so a design the agent makes is never left unlinked, and the designs one request makes share one family: Home shows them as one card. Opening any of them leads back to the conversation. Older conversations get their list rebuilt from what they recorded the first time Form Studio starts.
- **Several meshes, one design.** "Make this editable" with three STLs of one product makes one design with three parts, in the positions the files give, instead of three unrelated designs. Each part keeps its own parameters, prefixed with the part's name. `reconstruct(files=[...])` over MCP, `form reconstruct A.stl B.stl C.stl`, or several references from Describe. A reconstruction writes an activity line every few seconds, so a long run is not silent.
- **The agent says what new code is for.** In a conversation that already has a design, `create_design` asks whether the new code replaces it (a new revision), is a part of it, an alternative in its family, or something new. Only an alternative or a new design creates another project.
- **One brief for the whole request.** A design brief stays after the first design uses it, so the parts of one product and a second attempt can all be made from it. A brief consumed by an earlier version is found again on the design that took it.
- **No empty conversations.** Attaching a file before writing keeps a draft that becomes a conversation when the message is sent; a draft that is never sent goes to the trash (`.trash/conversations` in your Form Studio folder) after a week, never erased. Conversations left with no message, no attachment and no design by earlier versions become drafts. The one-time update of older conversations deletes nothing, copies every file it changes to `.backups/migration-<time>` first, skips a conversation it cannot read instead of stopping, and runs once.
- **Big files attach at once.** Attachments go up to 2 GB (a warning above 500 MB). A file from your disk is cloned into the conversation (copy-on-write on APFS), else hard-linked or streamed, and the app hands the engine its path: nothing is read on the interface thread or sent through the engine in memory. A generated 250 MB STL attaches in 0.04 s with 15 MB of memory; a 500 MB one in under 0.1 s.
- **3MF files from Bambu Studio, Orca Slicer and MakerWorld.** 3MF is read with lib3mf, following the production extension's `p:path` to the meshes in `3D/Objects/*.model`. Each object is a named part where the slicer put it, with its plate and filament colour, and modifier volumes are left out. Before, those files put every part at the origin, stacked, in one nameless mesh. A plain zip and XML reader that also follows `p:path` takes over where lib3mf is missing. OBJ files keep their named objects apart; chat accepts OBJ.
- **Links pasted in a chat are fetched by the engine.** Before the agent sees the message, Form Studio downloads what the links point to and tells the agent what it attached, with the source and licence, or why a link could not be fetched. A signed MakerWorld download link (valid for minutes) is fetched at once, and only once: a link the app fetched as you sent the message is not downloaded again by the engine, so a single-use link works and its file is attached one time. Downloads stream to disk; `GET /api/conversations/fetches` reports their progress.
- **Model pages resolve to their files** (`form/sources`). Printables: title, author, licence and the part files, downloaded through its public API with no account. Thingiverse: with an app token (`FORM_THINGIVERSE_TOKEN`) the same; without one, why not and how to download them. MakerWorld: files need a signed-in person, so Form Studio says so, reads the public page's title when the site allows it, and explains how to download the file or paste its signed link. Any other page gives its title and pictures. Requests carry a generic `FormStudio/<version>` user agent, no cookies and nothing about you. `form resolve URL`, `form fetch URL`.
- **Mesh preflight and a display proxy.** `mesh_preflight` (MCP), `form mesh-preflight FILE` and `GET /api/conversations/<id>/preflight/<file>`: triangles, size, closed or not, class and estimated seconds to read and analyse, in 1.2 s for 1.2 million triangles and 0.2 ms when asked again. A heavy mesh gets a decimated copy of about 200,000 triangles for display only; the source file is never replaced.
- **Three MCP tools for inputs:** `fetch_link` (download what a link the person gave points to, into the conversation, from outside the agent's sandbox), `resolve_model_page` and `mesh_preflight`. 90 tools.
- **Drag a face to change the design.** ⌘-drag (Ctrl-drag) a face in the viewport and the parameter that drives it follows the pointer: the top of a box changes its height, its side its width, a sculpted brow its brow handle. Form Studio finds the parameter by rebuilding the design one parameter at a time and measuring how far the face travels along its normal and how much else changes (computed, one finite difference per parameter); the readout shows the parameter, from and to, and the draft's volume change while the part rebuilds. It picks the right parameter on 10 of 10 fixture designs. With a draft open, a drag starts from the draft's values and shape, so a second drag on the same face carries on instead of jumping back to the saved revision. Engine route `POST /projects/<id>/drag_face`.
- **Constrained sketches.** `form.sketch2d`: lines, arcs and circles placed by a solver from coincident, horizontal, vertical, parallel, perpendicular, tangent, equal, symmetric, midpoint and on constraints and named dimensions (length, distance, horizontal and vertical distance, radius, diameter, angle). Named dimensions are a design's parameters; a change re-solves the profile (walking there in steps when it is large) so it keeps its intent. Ten fixture sketches re-solve with every dimension at ±20 %; a 32-entity, 67-constraint gasket solves in about a millisecond. Conflicts name the constraints and dimensions involved. `Sketch.face()` gives the build123d face, `Sketch.svg()` a dimensioned drawing.
- **Sculpted forms as exact NURBS.** `form.craft.subd`: grid cages evaluated as clamped bicubic B-splines (the Catmull-Clark limit inside), skins trimmed by a circle of their parameters, shells made of a skin, its inside and a ruled rim (three faces, C2 inside each skin), and closed Catmull-Clark cages turned into bicubic patches (Loop-Schaefer) that are G1 at extraordinary points and within a measured angle along their borders (`seam_angles`). Named `Handle`s on a cage are parameters. Plain numpy and scipy with build123d's OCCT: nothing new to install or package. OpenSubdiv bindings (no maintained wheels), Blender (optional, renders only) and OCCT plate surfaces (no editable cage) were weighed and not used.
- **Sculpted meshes to solids.** `form.meshbody.organic_solid`: a thick shell mesh is split at its creases, each skin mapped onto a disk (a harmonic map, re-spaced for even area), fitted as a grid cage with parameter correction, and built as a three-face solid; a closed prop is shrink-wrapped by a cube-sphere cage. The report gives the measured distance both ways, faces, validity, smoothness and timings. A 200,000-triangle helmet-like shell (made in-house) becomes a closed three-face solid within 0.28 mm in about a minute; FreeCAD reopens its STEP as one closed solid. `MeshBody` keeps sculpted detail as a mesh and cuts exact features into it with manifold3d (optional: `pip install manifold3d`).
- **Character mask exemplar.** A full-head cowl sculpted from a cage (brow, cheekbones, jaw, chin, crown and back are handles), eye openings from a constrained sketch, eye lenses that fit from the inside on magnets, a front/back split held by four magnets in bosses that span it, and a web relief as a mesh texture. New organic helpers: `surface_point`, `magnet_boss`, `magnet_pocket`, `split_with_magnets`, `split_spots`, `web_heightmap`.
- **A creation studio, not a slicer preview.** The top bar holds the design's name, revision and state, and never a printer. Every design stands on a neutral studio floor with a faint origin cross and a scale cue; the printer's build plate, grid and outline appear only in Fit, Review and Make of a design made for printing, or with **Show build plate**, and leave on the way back. The printer chip moved into the header of Fit, Review and Make. Home's bench and design cards have no plate, and a 3D model needs no "not for printing" label anywhere.
- **A new design is a 3D model.** For everyone, printing on or not, unless you say it is for printing: Home's **Make it for: Anything / My printer** (shown only when 3D printing is on, Anything by default), the request itself ("for my A1 mini"), or one click on **Make it for 3D printing** in Make. Someone who wants every new design made for the printer sets Settings › Printing › **New designs are made for** to print.
- **Conversations lead to their designs.** Opening a conversation opens its design within a second. One that made several shows them in a strip under its title, each a click away; one that made none says "No design yet" with **Continue the conversation**, never Home's question; a design moved to the trash is named as such. Home's conversation cards show the designs they made.
- **The agent never takes the view away.** Once you work on the open design, an agent working on another design is named ("Codex is working on Wallet base · Show") instead of switching the workspace to it.
- **Links and every file type in chat.** A link pasted or dropped into a conversation is fetched like one on Home: a file link becomes an attachment, a page goes with the message as a link; links typed into a message are fetched before it is sent. The attach button lists STEP, STL, 3MF, OBJ, PDF and pictures.
- **A calm usage-limit card.** When an agent hits its usage limit the conversation says which agent, when it can work again and what is saved, with **Use another agent** or **Continue later**, instead of a red error with an upgrade link.
- **Files on their way in.** A link or attachment that is downloading shows its name, how much has arrived and a bar under the composer, on Home and in a conversation. A link a site will not hand over (a sign-in, a token) says why and what to do. Describe names where each reference came from and its licence.
- Fixed a binding loop on Home's design cards.

- **Organic products that read as the real thing.** `form.craft` draws a product's silhouette in three views as guide curves and turns them into sections (`profile_sections`), checks every loft for folds and twisted seams (`checked_body`, `loft_report`), and sizes product families from named proportions: full-face and cycling helmets from an EN 960 headform and ANSUR II head data with typical liner and shell build-up, a palm-grip mouse from the hand, power grips, drinks bottles with a PCO 1881 neck. Details follow the surface (`surface_band` for trim, pads, scoops, spoilers and raised panels), openings are drawn in two views (`two_view_cutter`), vent grilles are B-rep (`slot_grille`), and `craft.cut` / `craft.fuse` retry free-form booleans with fuzzy tolerances and refuse a visor that touches the shell.
- **The helmet exemplar, rebuilt, and a mouse exemplar.** A carbon full-face helmet sized from a head: eye port cut in two views, a smoked visor on pivots, rubber trim, chin and brow intakes, crown scoops, a ducktail spoiler over exhausts and a carbon twill. An ergonomic mouse sized from the hand, with a thumb groove, split buttons, a rubber-tyred wheel, side buttons and rubber grips.
- **Critique knows what a product looks like.** It checks lofted skins for folds, measures wall thickness by rays (break-through and paper-thin spots with where they are) and lists sharp turns in the silhouettes. For a product class named in the brief or the plan (`helmet_fullface`, `helmet_open`, `mouse`, `bottle`) it compares the side, front and top silhouettes with the class outline, the proportions with real products (sources given) and its signature (an eye port and a visor, a neck opening, a palm hump, a scroll wheel), and keeps asking "does it read as one?" until the agent answers after looking (`critique(reads_as=...)`, `plan_design(product_class=...)`).
- **A stricter design bench.** Briefs score integrity (folded skins; thin or broken-through walls in shells) and, for product classes, the silhouette; a design whose class score is under 0.8 does not read as its class and is capped at 60, a folded skin or a broken-through shell wall at 65. The helmet and mouse the first design evaluation produced now score 60-65, below the bar of 70.
- **Photos with real materials, from any angle.** `render_photo` takes `view` (front, back, left, right, top, three_quarter, three_quarter_back) or `azimuth`/`elevation`, and new finishes: gloss paint, carbon twill under a clear coat, smoked polycarbonate, rubber and metal. A design that declares `appearance()` zones gets each its own material in one photo.
- **Textures you can see on the sheet.** The six-view sheet of a design with a mesh texture shows a zoomed tile of it.

- **Meshes rebuilt as clean, editable CAD by your agent.** When you bring meshes to make editable or to understand, the agent no longer wraps them as the design: it reads them like an engineer, models the parts again in build123d with named features and Params, and checks the result against the meshes until it is within 0.1 mm. Three new tools, also on the command line:
  - `analyze_reference` (`form analyze-reference <project> <mesh>`): dimensioned sections in the three principal planes at several levels, as pictures and as vector outlines with lines and arcs, and the features with their sizes: holes, bosses, openings with count and pitch, plates, walls, ribs, rails and grooves, steps, ramps with angles, draft, fillets and chamfers, detail areas such as text, symmetry and wall thicknesses.
  - `analyze_assembly` (`form analyze-assembly <project> FIXED OTHER...`): for several meshes, the mating surfaces and clearances, how far each part slides or turns and where it stops (bumps such as detents and flexing arms are listed), the joints that follow and couplings such as a rack driving a gear, with the ratio.
  - `compare_to_reference` (`form compare-reference <project> <mesh> [--part P]`): two-sided Hausdorff, a deviation picture, the worst regions named by where they are and whether the design has too much or too little material there, and per-feature differences such as a hole's diameter.
  - `design_guide(topic="reference_parts")` gives the agent the staged workflow, and the agent's instructions say never to embed a mesh as the design.
- **Rebuild as editable CAD.** Describe › Reference parts has a **Rebuild as editable CAD** button that starts a conversation with that brief for every mesh in the design. When **Make editable** does not reach a verified feature recipe, it says so and the button is the next step.
- **Meshes drawn smooth, without triangle edges.** Imported meshes and faceted solids (the exact Layer 0 solid, frozen facets, a design that reads an STL) are shaded smooth, and only creases sharper than 25° and boundaries are drawn as edges, in the 3D view, card thumbnails and render sheets. Every edge of a real CAD face is still drawn.
- **Make editable gives up less.** A plane that is off the mesh in a few places now keeps the rest of its triangles as a plane (only the bad ones become frozen facets), a fillet or chamfer that will not go back on is tried edge by edge before it is left in the base, and the feature tree stops at the time budget with its best attempt instead of running past it.
- **measure explains itself.** Calling `measure` with only one point now says what was missing and shows both ways to call it, with an example.
- **Open in your slicer, sliced with chosen settings.** With 3D printing on, Prove has **Open in <your slicer>**: Form Studio picks the orientation, layer height, walls, top and bottom layers, infill, supports, brim, seam, filament and speed profile for this part on this printer, each with a one-line reason labelled computed or heuristic, starts from the slicer's own preset and overrides only those keys, slices for real so the time and grams show first, and opens a project 3MF that carries the settings (read back from the file before it opens). Bambu Studio and OrcaSlicer show the chosen values as edits of their preset. A 3D-model design says how to make it printable first. `form slicer-open <project> [--printer ID] [--explain]`; MCP `open_in_slicer` (a print tool, off with printing).
- **A calm, instant viewport.** Orbiting, zooming and rebuilds draw the part in place with no snapshot laid over the view, a slider drag rebuilds the part while you drag with no "Previewing the change" step, and a new build grows in feature by feature, each fading and rising into place in build order (reduced motion: one fade).
- **A new opening screen.** The app opens on the mark's origin: two construction lines meet, the mark is built on them and the name sets beside it. The whole logo is on screen, centred, within half a second. The line under it says what is really happening (starting the engine, starting the CAD kernel, loading your designs and setup) and the bar never pretends to know how far along it is. When everything is loaded the logo travels to the top bar and stays there while Home appears behind it, with no flash; it shows for as long as the start takes, and at least 0.8 s (it was held for 2.3 s).
- **Design families on Home.** A design with its copies, saved variants and the concept you picked is one card with a count; the count opens the family under its row, the first design first. Designs now come before conversations, and the sentence under "What do you want to make?" shows only on a first visit.
- **Describe, Design, Fit, Review, Make.** The workspace's stages are named for what you do in them (they were Brief, Shape, Fit, Prove, Release). Shortcuts are unchanged, the old names still find each stage in the command palette, and the CLI and MCP keep their stage ids.
- **A light appearance.** Settings › General › Appearance: Dark, Light or Match system, applied at once and remembered. The 3D bench, the cards and every sheet follow it. `FORM_APPEARANCE=light|dark` forces one for a run.
- **Conversation exports say where they come from.** A conversation exported as JSON carries `ancestry` (its thread, the chain it was branched from with the event and reason of each branch, and its own branches), and the Markdown export has a short Thread section. `form export-conversation` and the MCP tool `export_conversation` include it.
- **A design brief.** `docs/DESIGN.md` states the intent, organisation, palette, type, spacing and motion the interface follows. Screen changes take 240 ms instead of 380.
- **Creation first; 3D printing is optional.** Form Studio is an AI CAD studio: describe a part, a product or a mechanism and it is built as real, editable CAD. 3D printing is now opt-in: until it is turned on there is no printer chip, no Fit stage, no slicer, print simulation, print orientation, filament cost or print rows in Prove, no Printing tab, and new designs are 3D models. People who already print stay on printing: a configured slicer or printer, or a design made for printing, turns it on once at the first start.
- **A launcher for setup.** The first run asks **What do you want to make?** with a card for each capability (parametric CAD, mechanical parts, mesh to CAD, photoreal renders, CAD exchange and, last, 3D printing) and a live download total, then your agent, then installs only what you chose with every command in the log. Nothing is downloaded before that last step.
- **Settings › General › Set up for.** The same cards: turning one on installs only what it needs; turning one off hides it and never uninstalls anything. `form capabilities [on|off <id>]`; `[general].capabilities` in studio.toml (the older `printing` setting still works).
- **Agents follow the same choice.** With printing off, `form_overview` leaves out the print tools, `choose_printer`, `plate_plan`, `pack_plate`, `print_simulation`, `slice_test_piece` and print settings in `set_print_setup` answer "printing is off; enable it in Settings", and `design_guide` gives the bed-orientation, overhang and nozzle-wall rules only for a design made for printing.
- **New Home words.** Home asks "What do you want to make?" and says "Describe it. Form Studio engineers it."; the suggested starters mix mechanisms, product shells and organic forms.
- **No bundled examples.** The example projects, `form examples` and the Import sheet's examples are gone; a new projects folder starts empty and every design starts from what you describe.
- **The 3D view stays drawn while you move.** Orbiting, panning and zooming to the extremes while panels open and close no longer turns the view black: the camera keeps a safe distance and depth range, the orbit centre stays near the part, and the cross-fade after a rebuild never leaves an old frame on top.
- **Close concepts without picking one.** A concept group on Home has a close button and a menu, and the concepts sheet has **Not now**, **Keep all** and **Discard all**: keep every concept as a design of its own, or move them all to the trash (recoverable). A group whose concepts are all gone closes by itself. `form concepts dismiss <group> [--discard]`; MCP `dismiss_concepts`.
- **Linked conversations.** A conversation now follows its design: picking a concept, a design the agent makes in the conversation, or copying a design keeps the talk linked instead of starting a blank one. **Fork from here** on any message starts a branch with the conversation up to that point; the column's header shows the branch and switches between them, and the conversation list shows branches under the conversation they came from. Designs record where they came from (copies, picked concepts, variants). `form conversations fork <id> [--at N]`.
- **Mesh to editable CAD.** An STL, OBJ or 3MF becomes a new design, checked against the mesh: **Make editable** next to an imported mesh, `form reconstruct FILE [--name] [--tolerance MM] [--layer 0|1|2]`, MCP `reconstruct`. Layer 0 always builds the mesh as an exact solid (Hausdorff distance at float precision); open boundaries and non-manifold edges are reported, and a hole is only closed as a listed repair.
- **Analytic and freeform faces from a mesh (beta).** Layer 1 fits planes, cylinders, cones, spheres and tori within a tolerance (0.02 mm by default) and fits smooth organic regions that none of them explains with B-spline patches ("freeform (B-spline fitted)"), then sews them, with frozen facets for whatever is left, into one solid; the report gives the parametric, freeform and frozen shares of the area, the two-sided Hausdorff distance, the volume difference and a deviation map.
- **A feature tree from a mesh (beta).** Layer 2 takes the features off the reconstructed solid and writes a build123d design that puts them back in order: a base (an extrusion stack with steps, bosses, pockets and cutouts, a revolution, or the reconstructed solid kept exactly), then fillets and chamfers as real operations with their radius and distance as Params, and holes on any axis (counterbored, countersunk, blind or through, snapped to standard sizes) with grids, lines and bolt circles as patterns. A spur gear becomes a parametric gear (teeth, module, pressure angle; `form.parts.spur_gear` when the mesh is one). Every value is "computed from mesh"; a feature that does not verify stays in the base and the report names it; the design is used only when its rebuild is within the limit, and the report says how much of the area its Params drive.
- **Faster, steadier reconstruction.** Mesh-to-solid distances test far fewer triangles (exact as before), faces that go all the way round a hole or a shaft get their seam where it crosses nothing, organic regions skip the analytic search, and a sphere is no longer refused as a face.
- **OBJ and 3MF reference parts.** Brief › Import part also takes OBJ and 3MF meshes.
- **Complex designs are briefed, planned and critiqued.** For a mechanism, an organic or styled form, a texture or several parts, the agent writes a structured brief and a feature plan before any code, and Form Studio refuses to build a complex design without one. Every new or changed design comes back with a six-view sheet and a section; `critique` adds close-ups of each feature and computed metrics (smallest fillet, sharp edges, symmetry, proportions, surface mix, missing planned features) with a checklist, and a briefed design is released only after a critique of that revision. MCP `design_brief`, `plan_design`, `critique`, `create_design(plan=...)`.
- **form.craft, a helper library for real design work.** Lofts, sweeps, revolves, shells and fillets that fall back safely; hinges, snap fits, bayonets, dovetails, detents, ratchets, cams, four-bar linkages, gear trains and planetary sets with their numbers; ISO 286 fits; ribs, gussets, bosses and lattices; helmet, grip and handle bodies from sections.
- **Texture.** Knurls, spiral ribs and embossed cells as real CAD geometry, and fine mesh textures (leather grain, carbon-like twill, cells, noise, hexagons, a heightmap) that the STL, OBJ, GLB and renders carry while the STEP keeps the smooth body, labelled as such.
- **Design guides by topic and twelve exemplar designs.** `design_guide(topic=...)` covers surfacing, mechanisms, organic forms, texture, aesthetics and design for printing; `design_examples` serves complete exemplars, from a textured full-face helmet shell to a planetary gearbox, to the agent only.
- **Features are named correctly on free-form surfaces.** A large lofted face is attributed to the feature that made it, not to a later cut through it.
- **Agents see what they build, from the command line too.** `form tool` now saves the sheet, section, close-up and render pictures a tool returns and lists their paths under `images`; a tool's JSON is no longer wrapped in a string. Multi-part designs show an exploded view on their six-view sheet, so a gearbox shows its gears, not just its housing.
- **Failures say where.** A design that ends with the wrong number of bodies reports the count after every step and where it changed; a step that leaves no solid is named. Every helper fallback (a smaller fillet, a loft in runs, a cam built another way) and every intermediate step that is not a valid solid is listed in `get_project` as `craft_fallbacks`, and `critique` flags it, along with steps that changed nothing. Heavy designs say when their checks are still running and wait longer for their pictures.
- **Sharper critique numbers.** Knurls and other texture facets no longer count as sharp edges, and smooth spline transitions count as rounded.
- **Better design helpers.** Fillets that fail as a set are tried edge by edge; spiral ribs fade into a plain foot and collar and take any twist; profiles always extrude along their plane; lofts take a seam position; a ring gear can span several stacked stages; hinges give the cuts that keep their knuckles clear of the walls; bayonet parts fit together as placed; four-bar linkages can be posed and their links placed between pivots; organic shells can be shaped outside before hollowing; helmet sections are available for visors; mesh textures can be limited to a region. A cam with a roller follower no longer depends on a 2D offset some OCCT builds refuse.
- **Assembly parts by position.** `Part(solid=(x, y, z))` names a body by a point inside it, so parts on one axis need no counting; bodies are numbered by X, then Y, then Z.
- **Eight new design-bench briefs** (a textured helmet with a visor, a 64:1 three-stage NEMA17 gearbox, a sealed Pi 5 case with hinge and latch, a mouse shell, an M6 thumb knob, a bike phone mount, a spiral lamp base, a four-bar gripper finger), each with a reference solution built through the tools. Gear designs are skipped, not failed, where the optional gear library is not installed.

- **Make it lighter.** Tools › Make it lighter (also the palette, the menu and the chat's suggestions) tries thinner walls and floors and larger lightening pockets where the design has them (never an interface parameter), building a ladder of candidates in the kernel and taking the lightest through the real checks and slicer, plus lower infill and one wall fewer over the slicer's process. Only candidates that keep every passing check passing are shown, each with its computed mass and the slicer's grams before and after and its checks; **Apply** commits the chosen one as a new revision (its outputs are already built) or sets the design's own infill and wall count. `form lighter <project> [--apply c1]`; MCP `make_lighter`, `apply_lighter`.
- **Replace a broken part.** On Home, **Replace a broken part** takes a photo of the part with a bank card, coin or ruler beside it, what it is and where it broke, and starts one conversation: the agent estimates sizes from the photo's scale, asks you for the sizes that decide the fit with a measurement card, then designs the replacement. Four steps (Photo, Estimate, Measure, Design) sit above the conversation and follow what the agent really does. `form replace --photo broken.jpg --name "Shelf clip"`; MCP `replace_part_guide`.
- **Designs made of imported parts build in seconds.** Three imported STL meshes of about 10,000 triangles each used to pass the kernel's 180 s limit; they now build in about 8 s.
- **Fewer failed steps in conversations.** A design that fails to build says the error and the line it came from; an STL export that comes out with a gap is meshed again until it is closed; a reference part named without an extension keeps its format; assembled and exploded views work for every multi-part design.
- **A safer engine.** Download file names can no longer add HTTP headers, web pages from other sites cannot send requests to the engine on your computer, design ids cannot point outside their folder, and lock files are private to you.
- **Errors are kept.** An unexpected engine error is written with its details to `.logs/engine-errors.log` in your projects folder.
- **A Discord server.** [discord.gg/b6ZgyndkmS](https://discord.gg/b6ZgyndkmS) has a guide for each part of the app, a help forum where the bot answers each new post with the guides for its tags, a showcase, ideas, and every release as it ships. It is linked from the README and the website's footer.

## 1.0.0

**The first public release of Form Studio.** Describe a part, and an agent designs it as real CAD: built in an
OpenCascade kernel, checked on the solid, sliced with your own slicer and played back layer by layer before you
print. Open source, for macOS, Windows and Linux.

- **Start from anything.** One composer on Home takes words, a photo (with a card, coin or ruler in it the agent estimates sizes), a sketch with real dimensions, a STEP, STL or 3MF part, a PDF drawing or a link. Choose **For my printer** or **Just a 3D model**, the printer, and the agent and model right under it, or **Start blank** with an empty plate.
- **Talk to it like a chat app.** Conversations are kept, searchable, pinnable and tied to their design, each with its own agent and model. Use agent apps (Claude Code, Codex, Gemini CLI, Cursor CLI, OpenCode, Qwen Code, GitHub Copilot CLI), model APIs (Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, DeepSeek, Groq), local models (Ollama, LM Studio, llama.cpp) or any provider added by its address.
- **Concepts, then real CAD built in front of you.** A new idea comes back as several genuinely different concepts, each real CAD with its size and volume. The agent writes a parametric build123d design, and it grows in the viewport feature by feature. When a number matters, it asks you to measure it and shows where.
- **Proved on the solid.** Every revision is checked: one valid solid, the export mesh, walls, overhangs, bridges, plate contact, tip-over, the build volume and fits modelled against your printer. Every number says how it is known: computed, heuristic, modelled, simulated or measured.
- **Assemblies that move.** Joints form chains, mates are fits rather than collisions, and every joint is swept through its range for collisions, with Assembled, Exploded and Print layout views and assembly instructions as a PDF.
- **Your slicer, for real.** Bambu Studio, OrcaSlicer, PrusaSlicer, SuperSlicer, QIDISlicer, ElegooSlicer and Snapmaker Orca slice every revision with your printer's own presets, on several plates when a design needs them, and the print is played back from the G-code.
- **Every printer you have, compared.** Prove › Every printer slices the design for real on each printer set up in each installed slicer, with that printer's own process and filament, and shows the slicer's time and filament and the cost from your prices side by side, with a bar per printer and the fastest, least filament and cheapest marked. A printer whose bed is too small says so; a failed slice says why. Slices are kept per model and presets, so asking again is instant. `form compare-printers <project> [--limit N] [--printer ID]`; MCP `compare_printers`.
- **Screw bosses and snap-fit hooks where you click.** In Annotate, pick a point on a flat face and choose **Feature here…**: a screw boss (M2 to M5; the hole for a screw cutting its thread is the ISO tap drill, for a heat-set insert a typical insert hole, for a screw passing through the ISO 273 clearance) or a cantilever snap-fit hook. The boss wall is checked against your nozzle and the hook's strain (1.5·t·y/L²) against an allowable strain as you type. **Add to design** writes the feature into the design's code and builds a new revision in the kernel; one that does not sit on the part is refused with the reason. `form feature <project> boss|snap_hook --at x,y,z --normal x,y,z`, `--list`, `--remove`; MCP `add_feature`, `remove_feature`.
- **Turntable videos.** Release › Share › **Turntable…** (also in the palette and the Tools menu) renders the part turning once from the kernel's mesh, at the frames and camera height you choose, as MP4 (when ffmpeg is installed), a PNG sequence, an animated WebP or a GIF, plays it in the sheet and saves it. `form turntable <project> --fmt mp4|png|webp|gif`; MCP `turntable`.
- **Shape it by hand.** Measure with snapping, annotate faces and regions with the numbers from the solid, add raised or sunk text on any flat face, set colours and materials per part, and see what changed between two revisions on the solids themselves.
- **Release what you approved.** Only a person approves a release. STEP, STL, 3MF, OBJ, GLB and G-code are frozen with SHA-256 hashes and a report of every check and its evidence; **Save files…** takes them all in one .zip.
- **Set up inside the app.** The first start installs what Form Studio needs and pauses only for a sign-in or a download that needs you, all in its own window with no terminal. No example project is added.
- **Everything headless.** Every action is a `form` command that prints JSON, and every agent tool is one of 74 MCP tools, also callable as `form tool NAME '{json}'`.
- **Design it, not print it.** Just a 3D model skips slicing and print checks, and a release holds the formats for CAD, CNC, laser cutting or rendering.

Notes of the development builds before 1.0.0 are in [docs/HISTORY.md](docs/HISTORY.md).
