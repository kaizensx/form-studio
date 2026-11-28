# Sheet metal and cut parts

Design a bent part as sheet metal, lay it flat with a bend allowance whose source you can read, prove the flat by
folding it back onto the part, write it as a DXF a shop can cut, check any DXF before it goes to a laser, waterjet or
router, find an order a press brake can bend it in, and check it against a service's published limits. Nothing is
uploaded and nothing is ordered.

```
form sheet flat <project> --set material=steel_mild [--set k=0.42] [--set label=PART-1] [--out part.dxf]
form sheet profile <project> --kerf 0.2              # any flat part: the outline for laser, waterjet or router
form sheet check part.dxf --process laser --set t=2  # or a project: its own flat pattern, written and read back
form sheet bends <project>                           # a bend order, or the collisions that rule one out
form sheet preflight <project> --service sendcutsend --material al_5052_h32
form sheet tables                                    # the bend table and the service tables with their sources
```

MCP: `flat_pattern`, `cut_file_check`, `bend_order`, `service_preflight`; `manufacturability` with process
`sheet_metal` judges the bent part with the same rule format as every other process. The code is `form/sheet/`.

## Designing sheet metal

`form.sheet.build.Sheet` builds one constant-thickness solid from features a design's code calls:

```python
from form.sheet.build import Sheet

s = Sheet(t=v["t"], r=v["r"], material="al_5052_h32")        # thickness, inside bend radius
b = s.base([(0, 0), (120, 0), (120, 80), (0, 80)])           # base flange: a polygon, extruded t
f = s.flange(b.edge(0), length=30, angle=90)                 # edge flange, up or down, any angle to 180°
s.flange(b.edge(2), 20, start=10, end=10, relief="obround")  # a shorter flange cuts a relief at each end
s.hem(f.far(), length=8)                                     # 180°, inside diameter = gap (default t)
s.jog(b.edge(1), offset=6, length=25)                        # two opposite bends
s.louvre(b, at=(60, 40), length=30, width=6, height=3)       # a formed feature (not developable)
return s.solid()
```

A flange starts at its parent's edge (the parent keeps its outline). Relief width defaults to t (Fractory: "The
width of such a cut should be above the material thickness"); its depth r + t is Form Studio's default, unsourced.

## Bend allowance and its sources

BA = θ · (r + K · t). The K-factor of each bend is chosen in this order and reported with every bend:

| Method | K | Source | Evidence |
|---|---|---|---|
| `k` given | your shop's value | — | specified |
| `table` (default) | air bending, bottoming or coining; soft, medium or hard; r/t ≤ 1, ≤ 3, > 3 (e.g. air, medium: 0.38, 0.43, 0.50) | Wikipedia, *Bending (metalworking)*, table *Generic K-factors* (last edited 2026-09-06; read 2026-11-28). The page calls it a rule of thumb and gives no primary source for the table. | rule; the material's column is Form Studio's reading (assumed) |
| `din6935` | (0.65 + 0.5 · log10(r/t)) / 2, kept within 0 and 0.5 | DIN 6935 as reproduced in *Blech biegen*, a cad.de forum upload (undated; read 2026-11-28). DIN 6935 itself was not read; the cap at 0.5 is unsourced. | rule |

The default inside radius is the thickness (Fractory, *Sheet Metal Bending*, updated 2026-09-21). Tables:
`form/sheet/tables/bend.toml`.

## Unfolding, and the proof

On the exact B-rep, in the kernel worker:

1. The largest flat face is the base. Faces are walked across **tangent** edges only: that set is one skin of the
   sheet. Sharp edges lead to the sheet's cut edges.
2. t is the nearest face behind the base facing away from it. Every flat face of the skin needs a face t behind it,
   every bend a coaxial cylinder at its radius ± t, every other face must meet the sheet square, and the volume must
   equal the skin's area × t (bends at their mid radius) to 1e-4.
3. Each skin cylinder is a bend: angle from its angular extent, up when the skin is its inside, inside radius from
   the skin or its partner.
4. Breadth-first from the base, each flat face gets a rigid motion into the base's plane; a bend's points land at
   angle × (r + K t) from its start line.
5. Cut edges are mapped (lines stay lines, circles on flat faces stay arcs, circles round a bend's axis become
   lines, anything else a polyline) and chained into closed contours.
6. **Fold-back.** Every vertex of the skin's tessellation, and the point t behind it, is laid flat and folded back by
   `form/sheet/fold.py` from the flat pattern's own numbers (bend lines, angles, radii, K). The largest distance
   between where a point started and where it lands must be under 0.01 mm. On the test parts (L-bracket, U-channel,
   a four-flange box, a part with a hem, a jog, an angled flange and obround reliefs) it is under 1e-13 mm.

The flat of an L-bracket (t 2, r 3, flats 50 and 30) equals 50 + 30 + π/2 · (3 + K · 2) to 1e-6 mm for each method,
and a U-channel's 25 + 40 + 25 + 2 BA likewise (`tests/test_sheet.py`).

**What cannot be unfolded** is named with the face and why: a face that is neither flat nor a cylinder on the skin
(a louvre or emboss), a cylinder tangent to the sheet with no partner at t (an edge round, not a bend), a face
neither on the sheet nor square to it, two thicknesses, a flat that overlaps itself. A louvre built with
`Sheet.louvre` is reported; `solid(forms=False)` gives the body without it and `marks()` its footprint.

## The DXF

Millimetres (`$INSUNITS` 4). Layers: `CUT` (closed contours of lines, arcs and circles; polylines only for edges
that are neither), `BEND_UP` and `BEND_DOWN` (bend centre lines, seen from the flat's +Z), `ETCH` (the label as
outlines, never TEXT), `NOTES` (per bend: direction, angle, inside radius, K, allowance; TEXT for people, not cut).
Read back with ezdxf, the outline's area equals the unfold's to 1e-6 mm².

## The cut-file check

Any DXF (blocks exploded, polyline bulges as arcs, splines and ellipses flattened at 5 µm, extrusion −Z handled).
Each layer's intent comes from its name: cut, bend, etch or ignore; an unknown layer is taken as cut and listed.
Rules in `form/sheet/rules/cut_<process>.toml`, judged by `form/dfm/rules.py`:

| Rule | Laser | Waterjet | Router | Source |
|---|---|---|---|---|
| Every contour closed | fail | fail | fail | SendCutSend, *How to prepare your file for sheet cutting* (undated; read 2026-11-28) |
| No duplicate or overlapping lines | fail | fail | fail | same |
| Contours do not cross | fail | fail | fail | same |
| Text converted to outlines | fail | fail | fail | same |
| Cut geometry on one layer | warn | warn | warn | same |
| Units inch or mm | fail on cm, m | fail on cm, m | fail on cm, m | same |
| Tiny segments | warn under 0.05 mm | warn under 0.05 mm | warn under 0.05 mm | unsourced |
| Smallest hole or slot | 50 % of t | 1.778 mm (0.070 in) | 3.175 mm (0.125 in) | SendCutSend |
| Inside corner radius | not checked (≈ kerf, no number) | 0.813 mm (0.032 in) | 1.600 mm (0.063 in) | SendCutSend |
| Hole to edge | warn: 1.574 mm at t ≤ 0.914 mm, else 3.175 mm | | | Protolabs, *Sheet Metal Fabrication: Design Guidelines* (undated; read 2026-11-28) |
| Hole to bend line | warn under 4 t | | | Protolabs ("typically within 4x material thickness of the bend") |
| Part size | | | 1 × 2 in to 44 × 30 in (44 × 23 in Delrin) | SendCutSend |

A hole's size is the width of its narrowest strip (a circle's diameter exactly, a slot's width). Rules in multiples
of t need `t`; without it they are *not checked* and the verdict is *not proven*. Not judged: kerf, heat, pierce
marks, the bridge between holes (SendCutSend lists it per material on pages that load it on demand; not read).

## Sheet-metal rules (manufacturability `sheet_metal`)

| Rule | Limit | Source |
|---|---|---|
| One sheet that unfolds | — | computed |
| Fold-back | ≤ 0.01 mm | computed |
| Flat does not overlap itself | none | computed |
| Flange (straight run beside each bend, over the bend's span) | fail under 4 t | Protolabs |
| Flange for an 8 t V-die | warn under 6.16 t | Bystronic, *The rules of press brake tool selection* (2019-05): V = 8 t, minimum flange ≈ 77 % of V |
| Hole diameter | fail under t | Protolabs |
| Hole to edge | warn as the cut check | Protolabs |
| Hole to bend zone | warn under 4 t | Protolabs |
| Hem inside diameter | fail under t | Protolabs |
| Inside radius | information | computed |

## Bend order

A depth-first search over bend sequences (deepest flanges first, results remembered per bend and set of bends
already made). Each bend is checked at 25, 50, 75 and 100 % of its angle, the part air-bent on the die with each side
turned up by half the angle, in both orientations.

The tools (stated on every result): a V-die of 8 × t (Bystronic), groove 88° (assumed), block V + 20 mm wide and
60 mm high (assumed) on a bed; a gooseneck punch (assumed, not a catalogue tool): 88° tip 10 mm high, neck to 22 and
30 mm, an arm forward to a column at y = 25 to 55 mm, 120 mm to the ram; behind the neck the punch is open (the
pocket a return flange swings into). The punch is sectioned to the bend's length; die and bed run the full length.

Limits: a 2D cross-section; faces taken by their convex hull (conservative); no springback, back gauge, finger
stops, weight or handling; hems and bends past 92° need an acute punch and a flattening step this model does not
have; tooling is not chosen from a catalogue. Tested: a four-flange box has an order; a 4 mm jog in 1 mm steel hits
the die (it needs a jog tool); a hem is reported as needing other tools.

## Flat parts for laser, waterjet and router

`profile` takes any flat part (a prism through its largest flat face): the outline and holes as lines, arcs and
circles. A chamfer, a bevel, a step or a pocket is reported, since a 2D cut cannot make it. With `kerf`, the cutter's
path is offset half the kerf away from the material (outline out, holes in, round corners outside); shops such as
SendCutSend compensate kerf themselves, so it is off by default.

## Service preflight

`form/sheet/services/sendcutsend.toml`, read 2026-11-28 from SendCutSend's pages: 5052 H32 aluminium and mild steel
with their thickness lists and the thickest they bend (0.250 in), bend angle up to 130°, flat size of a bent part
0.375 × 1.5 in to 30 × 44 in, smallest laser hole 50 % of t, and the cut-file rules. The service bends with its own
radius and K-factor per thickness ("we don't offer custom bend radii"), so its flat can differ from this one by the
difference in allowance; the result says so. The maximum size of a flat part is not checked: the 5052 page states
two different figures. A table read more than 90 days ago says so on every result. Nothing is sent.

## On the Bench

`register_studies` adds **Flat pattern, DXF** (a route), **Cut-file check** and **Bend order** (studies), keyed by
the geometry and the bend table's hash.
