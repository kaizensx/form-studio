# Boards and enclosures

Bring a circuit board and get an enclosure that is checked against it, on the solids, at every revision. When the
board changes, the checks say what no longer lines up.

```
form board import board.kicad_pcb                       # a new design: the enclosure around the board
form board check <project>                              # the board against the enclosure, KiCad's DRC/ERC, fab limits
form board import board-v2.kicad_pcb --project <project> # the board changed: the checks say what moved
form board fab <project>                                # Gerbers, drill, pick-and-place, BOM, board STEP (your KiCad)
```

MCP: `board_import`, `board_check`, `board_fab`. The Bench lists **Board and enclosure**, **Board checks** and
**Board fab files** for a design with a board. The code is `form/board/`. The board itself (schematic, placement,
routing) is designed with `board_schematic`, `board_place` and `board_route`: see
[K2](#k2-schematic-placement-and-routing) below.

## Reading a board

| File | Read by | What comes out |
|---|---|---|
| KiCad `.kicad_pcb` (KiCad 5 to 9) | Form Studio's own S-expression parser (`form/board/sexpr.py`); no KiCad needed | outline and its holes and cut-outs (`Edge.Cuts`, arcs included), thickness, every footprint with its courtyard (pads when it has none), side, rotation and the height its footprint states, mounting holes, keep-out zones, track widths, vias, pad drills and annular rings |
| KiCad `.kicad_pro` beside it | JSON | the board's own rules: minimum clearance, track width, net classes |
| IDF 3.0 `.emn` with its `.emp` | `form/board/idf.py` | outline (arcs included), thickness, drilled holes, placed parts with outline and height from the library |
| KiCad's board STEP (`step=`) | the kernel (`op_board_step`) | each part's height, measured over its courtyard; the STEP moved into the enclosure for drawing |

IPC-2581 is not read yet; export IDF or the `.kicad_pcb` instead.

**The board frame.** Millimetres; x right, y away from the viewer seen from the top (KiCad's y points down, so it is
negated), z up from the board's underside; origin at the centre of the outline's bounding box. The board model
keeps where that centre is in the file, and a board imported again into the same design is placed in the first
import's frame, so a connector that moved reads as moved.

**Heights are never guessed.** They come from a footprint property (`Height`, `Component Height`, `3D Height`,
`Max Height`), an IDF library, a board STEP, or the person (`heights={"C1": 10.5}`). A part without one is "not
checked" against the lid, never a pass. `use_kicad_step=True` has the person's KiCad export the STEP.

**Mounting holes** are mounting-hole footprints, non-plated holes of 2.1 mm and more, and round holes in the outline.
Each gets the largest metric screw whose ISO 273 close clearance hole fits it (Ø3.2 takes M3).

**Connectors** are footprints whose reference starts with J, P, CN, CON, USB or X (and a connector-like library name,
or J, USB, CN). Each mates through the board edge its courtyard comes within 2.5 mm of (overhangs included);
further in, it mates from above. The plug's envelope is the USB Type-C specification's overmold maximum
(12.35 × 6.5 mm, specified) for a USB-C receptacle, otherwise the connector's face plus 1.5 mm per side, marked
assumed. `connectors={"J2": {"side": "+x", "plug": [w, h]}}` overrides both.

## The enclosure

`board_import` writes the enclosure as an ordinary design (a FeatureDesign in Python), one feature per step, every
size a parameter, so it is edited like any other design (`edit_design`, the app):

| Feature | What it does |
|---|---|
| Shell | outer walls and four corner lugs outside the cavity, clear of the board's corners |
| Cavity | the board and every courtyard plus `clearance` per side; height = standoffs + board + tallest part + `headroom` |
| Standoffs | a column under each mounting hole, top at the board's underside |
| Connector openings | each plug's envelope plus `port_clearance`, centred on its connector's face; a rounded rectangle whose corners still pass the envelope |
| Lid, Lid lip | the lid printed turned over beside the box, its lip inside the walls |
| Vents | slots through the lid over the board |
| Inserts and screws | CNC Kitchen heat-set inserts in the standoffs and lugs, ISO 7380-1 board and lid screws, from the standard-parts tables (form/catalog.py) with their mating cuts; placed from the values (`std_parts`), so they follow every change; `assembly()` lists them for the parts list |

The board is a constant in the source (`BOARD`), named with the file's SHA-256, so the design's geometry key changes
with the board it was made for. `assembly()` puts the lid on the box; `board_layout()` says where the board and the lid
are for the checks. The board is drawn beside the design as a reference part (`board.step`): the board STEP when one
was given, otherwise Form Studio's plain model (the slab and a box per part of known height), and it says which.

## The checks

**Board and enclosure** (`board_check what="fit"`): the board as it is now in the project against the head
revision's solids. Every row is computed on the B-rep in the kernel worker (`form/board/fit.py`).

| Row | How |
|---|---|
| Board to enclosure | the board's slab (outline, holes, cut-outs) against the walls at its height: overlap volume and the smallest gap |
| Standoff under each hole | point tests: material under the hole's ring, nothing above the board's underside, a pocket under the hole |
| Connector plug | the plug's envelope swept 30 mm out from the connector's face, intersected with the box and the lid as assembled; the opening's centre tested open mid-wall and the wall tested solid just beyond the plug and its clearance; the distance the plug must reach from the outer face |
| Parts against the enclosure | each part of known height as its courtyard extruded, against the box and the lid as assembled; the closest gap to the lid |
| Screwdriver | a path straight down to each board screw (the pan head's diameter from the tables, + 0.5 mm per side, assumed for the driver), against the parts and the box |

**Board checks** (`what="board"`):

- **KiCad's own DRC and ERC**, when `kicad-cli` (KiCad 8 or later) is installed: `kicad-cli pcb drc` and
  `kicad-cli sch erc` with `--format json --severity-all`; the report is kept as KiCad wrote it and read into rows
  that say "KiCad DRC" or "KiCad ERC". Without KiCad, the result says it is not installed and names the install route
  (Settings › Engines & software › KiCad, `form install kicad`); nothing is run in its place. ERC needs the
  `.kicad_sch` beside the board.
- **Fab limits** for JLCPCB, PCBWay and OSH Park (`form/board/fabs.py`): track width, track to track spacing
  (computed on the track segments of different nets; pads, vias and zones are KiCad DRC's job), the board's own
  clearance rule, the smallest plated and via drill, non-plated holes, annular rings, board size and thickness. Every
  limit is quoted from the fab's own capability page with its URL and the date it was read (2026-11-28):

| Fab, process | Trace / space | Drill | Annular ring | Board size | Page |
|---|---|---|---|---|---|
| JLCPCB 1-2 layers, 1 oz | 0.10 / 0.10 mm | 0.15 mm (NPTH 0.50) | 0.18 min, 0.25 recommended | 3 × 3 to 670 × 600 mm | https://jlcpcb.com/capabilities/pcb-capabilities |
| JLCPCB multilayer, 1 oz | 0.09 / 0.09 mm | 0.15 mm | 0.15 min, 0.20 recommended | 3 × 3 to 663 × 593 mm (4-layer) | same |
| PCBWay standard | 0.1 / 0.1 mm | 0.15 mm (under 0.2 costs more) | 0.15 mm | 3 × 3 to 600 × 1200 mm (1-2 layers), 560 × 1150 (multilayer) | https://www.pcbway.com/capabilities.html |
| OSH Park 2 layer | 0.1524 / 0.1524 mm | 0.254 mm | 0.127 mm | 6.35 × 6.35 to 406.4 × 558.8 mm, 1.6 mm thick | https://docs.oshpark.com/services/two-layer/ |
| OSH Park 4 layer | 0.127 / 0.127 mm | 0.254 mm | 0.1016 mm | same | https://docs.oshpark.com/services/four-layer/ |

A limit is the fab's published claim about its standard process, not an approval. No findings from KiCad is KiCad's
result, not a manufacturability approval. Read the fab's page again before ordering.

## Fab files

`board_fab` runs the person's `kicad-cli` (`pcb export gerbers`, `pcb export drill` with a PDF map, `pcb export pos`,
`sch export bom`, `pcb export step`) into `<project>/board/fab/<board hash>/`. Gerbers without an Edge.Cuts layer are
called out. Without KiCad only the board STEP is made, from Form Studio's plain model, and it says so. Nothing is
uploaded or sent to a fab.

## Files and evidence

The board's files are copied into `<project>/board/` (the `.kicad_pcb` with its `.kicad_pro` and `.kicad_sch`, or
the `.emn` with its `.emp`) and never changed where they are. `board.json` is the board model; `p["board"]` records
the file, its SHA-256 and its key. The fit check is keyed by the head's geometry and the board model; the board
checks by the board, KiCad's version and the fab table's date; a change to any of them makes the Bench entry stale.

## K2: schematic, placement and routing

The board itself is designed here, on KiCad's file formats, so a product's board and its enclosure are designed
together. Everything below is Form Studio's own code; no KiCad code and no Freerouting code is in it.

```
form board schematic edit new.kicad_sch --lib My.kicad_sym --ops @ops.json   # place symbols, join pins, annotate
form board schematic netlist <project or file.kicad_sch>                     # nets with their pins, parts with footprints
form board schematic erc <project or file.kicad_sch>                         # Form Studio's subset, then KiCad's when installed
form board schematic to_board file.kicad_sch --size 40,30 --out board.kicad_pcb
form board place <project or board.kicad_pcb> [--check-only]                 # against the enclosure's constraints
form board route <project or board.kicad_pcb> [--engine form|freerouting]    # segments and vias into the .kicad_pcb
form board copper <project or board.kicad_pcb>                               # Form Studio's geometric check of the copper
```

MCP: `board_schematic`, `board_place`, `board_route`. The Bench adds **Board copper**, **Board placement** and
**Schematic checks**. In a design the files worked on are the copies in `<project>/board/`; every change keeps the
version it replaced in `<project>/board/history/`, and the board model is read again so the fit check goes stale. On
a file outside a design the result goes to a new file (`out=`, default `<name>-routed.kicad_pcb` and the like); the
file given is never written.

### Who checked what

| Result | Whose it is | When it runs |
|---|---|---|
| `check` of `board_route`, **Board copper** | "Form Studio geometric check (not KiCad's DRC)" | always |
| `kicad_drc` of `board_route` | KiCad's DRC report, read as KiCad wrote it | only when kicad-cli is installed; otherwise it says it did not run |
| `form` of `board_schematic erc`, **Schematic checks** | "Form Studio ERC (a subset; not KiCad's ERC)" | always |
| `kicad` of `board_schematic erc` | KiCad's ERC report | only when kicad-cli is installed |

No findings from Form Studio's checks is not KiCad's verdict, and neither is a manufacturability approval. Each
result lists what it does not look at (`not_checked`).

### Schematic (`form/board/schematic.py`)

`.kicad_sch` (KiCad 6 to 9) is read into a tree and written back atom for atom: a quoted string stays quoted, a bare
symbol stays bare, and what Form Studio does not understand is kept as it was.

**The netlist.** A pin's connection point is its symbol's position plus the pin's library position turned by the
symbol's rotation (KiCad's orientation matrices: 0° x, −y; 90° −y, −x; 180° −x, y; 270° y, x) and then its mirror.
A wire joins what is at its two ends; a pin, label, junction or another wire's end lying on a wire joins it; two
wires that only cross do not join without a junction. Labels with the same text name one net; a power symbol names a
global net by its Value. Unnamed nets are `Net-(R1-Pad1)`, single pins `unconnected-(U2-PA1)`. This sheet only:
sub-sheets are listed, not opened, and buses are not expanded; the result says so.

**Form Studio's ERC subset.** Pins not connected (a no-connect mark or a no-connect pin excuses one), power inputs
no power output or `PWR_FLAG` drives, inputs nothing drives, two drivers on one net (output and power-output pairs,
open collector against a push-pull output), dangling labels, missing and duplicate references. The pin-pair table is
Form Studio's own short list, not KiCad's full matrix.

**Editing.** Operations in order, all or nothing: `place` (the library symbol is copied into the file, as KiCad
does; `extends` is resolved), `net` (a label on each pin), `connect` (a wire; refused when it would run over another
pin), `wire`, `label`, `power`, `junction`, `no_connect`, `set`, `remove`, `annotate`. Symbols come from the
`.kicad_sym` libraries on the person's computer: KiCad's standard folders where it is installed, `[cad]
kicad_symbols`, or `libraries=[...]`. A symbol is found by its block in the file, so a large library costs only the
symbol asked for. Nothing is downloaded.

**To a board.** `to_board` makes a new `.kicad_pcb` from the netlist: each part's footprint is read from the
person's `.pretty` folders and its pads are given their nets. A part whose footprint is not named or not found is
listed in `missing`, never replaced by a guess. Footprints go on the top side.

### Placement (`form/board/place.py`)

| Constraint | Where it comes from |
|---|---|
| a connector that mates through a wall stays put | the board model's connectors (the enclosure's openings are cut for them) |
| the screw head and its driver over each mounting hole, the standoff under it | the mounting holes; the head diameter from the standard-parts tables + 0.5 mm, the standoff's diameter from the enclosure's parameters |
| the room under the lid, less under the lid's lip along the walls | the enclosure's `board_layout()` and `lip_h`, `lip_wall`, `lip_clearance` |
| the room under the board | the standoff height above the floor |
| the board's own keep-out areas that forbid footprints, the outline, cut-outs | the board file |
| a gap between courtyards (0.25 mm) and to the edge (0.5 mm) | assumed, and said |

Forces first (a spring from each pad to the centroid of its net's other pads, a push off overlaps, out of keep-outs
and back inside the outline, a step that shrinks; no random numbers), then each part goes to the nearest position on
a 0.5 mm grid where every constraint holds, largest first, then rotations and swaps of like parts that shorten the
wires. A part with no legal position stays where it was and is reported. A part without a height is "not checked"
against the lid. The check is on courtyard rectangles in the plane; the 3D fit is `board_check what="fit"`.

### The router (`form/board/route.py`)

1. **The grid.** Track centres run on a square grid. For each net class every cell is marked with the copper a track
   of that class centred there would come too close to: pads, kept tracks and vias of other nets, the board edge,
   non-plated holes, keep-out areas. A second map does the same for a via centre.
2. **Why a grid path is legal between its points.** For a need R (half the track width plus the clearance to the
   other copper) cells are blocked within ρ = √(R² + g²/2) of that copper, g the pitch. Take a point P of the other
   copper and a step AB of length s ≤ g√2 between two free cells. If the nearest point Q of AB to P is inside the
   step, PA² = PQ² + QA² and one end is within s/2 of Q, so min(PA, PB)² ≤ PQ² + g²/2; both ends are at least ρ
   away, so PQ ≥ R. The pitch is chosen so that tracks k cells apart are exactly at their rule:
   g = (w + c)/√(k² − ½), 0.1017 mm for 0.2 mm tracks 0.2 mm apart.
3. **Search.** A\* over (layer, cell), eight moves, an octile heuristic to the target's box, a cost per bend and per
   via; or Lee's wavefront (four moves, cells expanded in order of cost) on grids under 40 000 cells. Multi-pin nets
   are joined as a minimum spanning tree (Prim), each pad routed to the tree grown so far.
4. **Net order.** Shortest span first, ties by name; nothing is random, so the same board gives the same file.
5. **Rip-up and reroute.** A net with no way is routed once more with other nets' copper allowed at a high cost; the
   nets that path crosses are removed and queued behind it. A net can force at most four rip-ups.
6. **Negotiated congestion** (PathFinder; McMurchie and Ebeling, 1995), for what rip-up leaves: every net is routed
   with sharing allowed, and a cell's cost grows with its present sharing and its history of sharing until no two
   nets share. When it does not settle, the nets still in conflict are removed and reported.
7. **Pull-tight.** Each path is shortened to straight and 45° legs. Every new segment is tested in closed form
   against the real copper shapes (`form/board/geom.py`), not the grid, before it replaces the grid path. Junctions,
   vias and pad entries stay where they are.
8. **Rules.** Width, clearance, via size and drill per net class from the `.kicad_pro` beside the board (classes,
   `netclass_patterns`, `netclass_assignments`), the board's edge and hole clearances from its design rules. Without
   a `.kicad_pro`, KiCad's values for a new project are used and marked assumed.
9. **Output.** `(segment ...)` and `(via ...)` in the `.kicad_pcb`, with ids derived from the copper so a rerun
   writes the same file.

A net that cannot be finished is in `unrouted` with the reason, the pads left out and the pads that were joined.

**Numbers on the synthetic boards** (`form/board/synth.py`; made-up boards, this machine, pure Python):

| Board | Nets routed | Segments | Vias | Rip-ups | Negotiation rounds | Own check | Time |
|---|---|---|---|---|---|---|---|
| header, SOIC-16, eight 0603 parts, 40 × 30 mm, 2 layers | 16 of 16 | 114 | 4 | 0 | 0 | 0 findings, tightest gap 0.210 mm (0.2 needed) | 0.3 s |
| the same with a pad walled in by a keep-out | 15 of 16, the pad named | 114 | 4 | 0 | 0 | 0 findings, 1 connection not made | 0.3 s |
| rooms (one layer), first pass only | 1 of 2 | | | 0 | 0 | | 0.1 s |
| rooms, rip-up and reroute | 2 of 2 | 15 | 0 | 1 | 0 | 0 findings | 0.1 s |
| rooms, negotiated congestion only | 2 of 2 | 13 | 0 | 0 | 8 | 0 findings | 0.4 s |
| channel of 8 tracks (one layer), first pass only | 7 of 8 | | | 0 | 0 | | 0.2 s |
| channel of 8 tracks, rip-up and reroute | 8 of 8 | | 0 | 1 | 0 | 0 findings | 0.2 s |
| channel of 8 tracks, negotiated congestion only | 7 of 8 | | | 0 | 40, not settled | 0 findings, 1 connection not made | 9 s |

Negotiation alone does not settle a channel that holds exactly its tracks; rip-up does. None of these boards was
checked by KiCad's DRC here: this machine has no KiCad.

**Limits.** Two layers (F.Cu and B.Cu; inner layers are left alone). Through vias only. Zone fills are not seen:
fill the zones again in KiCad. No differential pairs, length matching or teardrops. Arcs already on the board are
treated as their chord. Pure Python: a board is capped at 450 000 cells per layer, above which the pitch grows and
the result says so.

### Form Studio's geometric check (`form/board/drc.py`)

Every copper shape is a convex skeleton grown by a radius (a circle is a point, a track or oval pad a segment, a
rectangle its corners, a rounded rectangle the rectangle shrunk by its corner radius), so the gap between two is the
distance between skeletons minus both radii, exactly. It reports copper of different nets closer than the larger of
their class clearances, tracks and vias against the board edge, non-plated holes and keep-outs, drilled holes too
close, widths under the board's minimum, and for each net the groups of pads its copper does not join. Not looked
at, and listed: zone fills, mask and silkscreen, courtyards, annular rings, differential pairs, `.kicad_dru` rules,
pads of one footprint against each other; a custom-shaped pad is its bounding rectangle.

### Freerouting, the person's own (`form/board/specctra.py`)

Freerouting (GPL-3.0) is a separate program. Form Studio does not contain it and does not download it. It is an
opt-in engine: Settings › Engines & software › Freerouting opens its releases page, `[cad] freerouting` gives the
path of the `.jar` or launcher, and `[use] freerouting` is off until the person turns it on. `board_route
engine="freerouting"` then writes a Specctra `.dsn` (outline, keep-outs, every pad's shape where it is on the board,
nets, classes, kept wiring as protected), runs `freerouting -de board.dsn -do board.ses -mp <passes>` as its own
process, reads the `.ses` and writes its wires and vias into the `.kicad_pcb`, checked like any other copper. When
it is not installed or not on, the result says so and nothing is routed.

### What is tested, and what is not

`tests/test_board_k2.py`, on synthetic boards and libraries: the writer gives back the tree it read (board and
schematic); the netlist of hand-written wires, junctions, crossings, rotations and mirrors; the ERC subset's
findings; the router to completion with no clearance violation, measured by the check and again by a separate
segment-distance formula; an unreachable pad reported; rip-up and negotiation each finishing the rooms board;
determinism; planted violations found by the check; placement constraints; the `.dsn` and `.ses`; Freerouting never
started unless installed and on.

Not verified here, because this machine has neither program: a routed board through KiCad's own DRC (the test is
skipped without kicad-cli), files written here opened in KiCad itself, the pin positions of a schematic drawn in
KiCad (the matrices above are KiCad's as documented, exercised only on hand-written files), and the `.dsn` read by
Freerouting itself (the hand-over is exercised with a stand-in program).
