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
**Board fab files** for a design with a board. The code is `form/board/`.

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

## K2: schematic and routing (planned, not built)

The owner chose the full loop: wave K first (the board as a constraint on the enclosure, the person's KiCad for its
rules and outputs), then K2: schematic capture and routing inside Form Studio, on KiCad's file formats and with its
rule checks, so a product's board and its enclosure are designed together.

**Schematic.** Read and write `.kicad_sch` with the same S-expression reader (symbols, wires, labels, sheets); a
netlist from it; edits as operations an agent sends (place symbol, connect pins, label a net), each a new revision
of the schematic file. ERC stays KiCad's (`kicad-cli sch erc`), reported as KiCad's.

**Placement.** Footprints from the person's KiCad libraries, placed against the enclosure's constraints wave K
already measures: connectors on the wall openings, tall parts where the lid has room, keep-outs from the standoffs
and the screwdriver paths. The enclosure's solids become a placement keep-out map.

**Routing, Form Studio's own router.** On a grid of 0.05 to 0.1 mm per layer, with the board's clearance and track
widths from its rules:

1. *Lee maze routing* (breadth-first wavefront) for a first, exact shortest path where the grid is small; *A\** with
   an octile heuristic and a bend and via cost for the rest. Both expand only free cells (copper of other nets
   dilated by clearance + half the track width).
2. *Net order*: shortest Manhattan span first; multi-pin nets joined as a minimum spanning tree (Prim) of their pads,
   each edge routed to the tree grown so far.
3. *Rip-up and reroute*: when a net fails, the nets whose copper blocks its cheapest relaxed path are removed and
   queued after it; a bounded number of passes.
4. *Negotiated congestion* (PathFinder, McMurchie and Ebeling, 1995): every net routes with sharing allowed; a cell's
   cost grows with its present and historical overuse each iteration until no cell is shared. This is the step past
   a router without rip-up.
5. *Pull-tight*: each path is shortened to the farthest clear straight or 45° segment, then checked again.
6. Every result is written to the `.kicad_pcb` and checked by KiCad's own DRC; Form Studio reports KiCad's findings
   and never claims a routed board is clean on its own say.

**Or Freerouting.** Freerouting (GPL-3.0, a separate Java program the person installs) reads a Specctra `.dsn` and
writes a `.ses`. The interface: export DSN (`kicad-cli` does not export DSN today; Form Studio would write it from
the board model), run `freerouting -de board.dsn -do board.ses -mp <passes>` as a separate process, import the session's
wires and vias back into the `.kicad_pcb`, then KiCad's DRC. It would be an opt-in engine in the installer, like
KiCad; no Freerouting code would be in Form Studio.

**Tests K2 needs.** Known small boards routed to completion with zero KiCad DRC errors; a net that cannot fit
reported as unrouted, never dropped; the same board routed twice gives the same copper (deterministic order).
