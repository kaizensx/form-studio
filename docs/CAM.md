# CAM: toolpaths for a 3-axis mill, checked on a stock simulation

Form Studio plans the machining of a design on a 3-axis mill or router, writes the G-code for your controller,
reads that file back the way the controller would, runs it on a model of the stock with the tools' real shapes, and
measures the result against the design's solid: where the cutter would gouge the part, what material would be left
and where, whether a rapid move or the holder would hit the stock, and how long it takes.

The simulation is the proof, and it is only a simulation. Every result says **simulated**, and a program is
labelled **"simulated, not proven on a machine"** until you record what happened on a real machine.

```
form cam plan <project> --tool 6mm-flat --tool 5mm-drill --material aluminum [--set setups=auto]
form cam post <project> --machine grbl [--units inch] [--wcs G55] [--include] [--out part.nc]
form cam simulate <project> [--cell 0.1]
form cam status <project>
form cam materials            # the speeds table and its sources
form cam posts                # the controllers
```

MCP: `cam_plan`, `cam_post`, `cam_simulate`. All print JSON. The code is `form/cam/`; no FreeCAD, no other CAM
program. The Bench entry is **CNC, 3-axis**.

## Operations

| Operation | What it does |
|---|---|
| `face` | Level passes over the top of the stock down to the part's top |
| `adaptive` | Clearing at constant engagement. At each level the cutter is steered so that the width of material it meets stays at the stepover asked for; it enters from open stock or down a 3° helix, never straight into a full slot; a radial and an axial allowance stay for finishing. The plan reports the engagement it kept (mean, 95th percentile, maximum) |
| `finish` | 2.5D finishing: each level floor in rings, then the walls that stand on it, along the exact boundary of where the tool can be. A wall taller than the flutes is taken in steps |
| `contour` | The part's outline cut through in depth steps, with holding tabs (count, width, height) |
| `drill` | Drilling, pecking by one diameter when the hole is deeper than three; the depth is where the drill's own point meets the part |
| `bore` | A hole between 1.05 and 1.9 cutter diameters: down a helix, once around at the bottom |
| `chamfer` | Edges of level faces broken with a chamfer mill by a stated width. On a model whose edge is sharp this cuts into the model on purpose: the plan declares it, and the simulation reports it as an edge break, not a gouge |
| `raster` | 3D finishing in parallel passes; the stepover comes from the scallop height asked for |
| `waterline` | 3D finishing at constant heights, for steep faces |

Without `ops`, the plan takes what the part's shape calls for with the tools given: facing when the stock stands
above the part, drilling for holes with a drill of their size, boring for holes a cutter fits, adaptive clearing,
finishing with every flat tool (largest first), parallel finishing with a ball when the part has sloped or curved
faces (and waterline where they are steeper than 56°), the chamfer when `chamfer` gives a width, the outline with
tabs when the stock is larger than the part. What cannot be done with the tools given is said in the plan's notes
and shows up as leftover in the simulation: a hole with no drill of its size, a curved face with no ball.

### Tools

Flat, ball, bull-nose, drill and chamfer, each a solid of revolution: cutting diameter, flutes, flute length,
stick-out below the holder, and the holder's diameter and length. A short name (`6mm-flat`, `3mm-ball`,
`6mm-bull-r1`, `5mm-drill`, `6mm-chamfer-90`) is enough to plan with, but a tool whose flute length or stick-out
nobody gave is **assumed**, and so is every tool of the built-in starting set. Give
`{kind, d, flutes, flute_l, length, holder_d, holder_l}` for a tool you own.

### Setups

A setup is a tool direction: `+Z` unless stated, any of `+Z −Z +X −X +Y −Y`, or a vector. `setups: "auto"` takes
the setups from the manufacturability check's access analysis (`form/dfm`, the fewest that reach the surface with
the largest flat tool given) and drops those with nothing to cut. Each setup has its own work zero (the stock's
front-left corner or its centre, at the stock's top or underside), its own program and its own simulation.

Each setup is planned and simulated from the blank as that side sees it. Of what an earlier setup removed, only
holes drilled or bored through are carried into a later one. Workholding is not modelled.

## Speeds and feeds

```
RPM  = 3.82 × SFM / D[in]
feed = RPM × chip load [in/tooth] × flutes
```

SFM and chip load are read from `form/cam/feeds.toml`, where every row quotes the line it came from: Harvey Tool,
*General Machining Guidelines* (carbide end mills: aluminium wrought and cast, brass, copper alloys, polycarbonate,
acrylic, gray cast iron, carbon and tool steels, three stainless families), read 2026-11-28. The start is the low
end of the source's SFM range, limited to the machine's top speed. The chip load between two diameters the source
lists is interpolated linearly; outside them it is not extended.

Every number says where it came from:

| | |
|---|---|
| sourced / computed | read from the table, or arithmetic on it (RPM from SFM, the feed, radial chip thinning `1/√(1 − (1 − 2·ae/D)²)` for adaptive clearing) |
| specified | you gave it (`feeds: {tool_id: {rpm, feed, plunge}}` or per operation) |
| assumed | no source here covers it: plunge feeds (a third of the feed), drills, chamfer mills, a material with no row (wood, sheet goods), a cutter under 1/8 in |

A plan with anything assumed is planned and simulated like any other. It cannot be released.

## The stock simulation

The stock is a height field: the top of the remaining material over every cell centre of a grid, along the tool
axis. The cell size is stated with the result (a quarter of the smallest tool radius, 0.25 mm at most; `--cell` to
change it).

- **Motion.** The posted file is parsed (`form/cam/posts.py`) and turned into straight segments; arcs become chords
  within 0.002 mm, a drilling cycle becomes the moves the controller makes.
- **Cutting.** A level move or a plunge lowers the stock to the tool's own profile at each cell's distance from the
  path: exact at every cell centre. A move that changes height while it travels is sampled every half cell.
- **Gouge.** For every sample point on the part's surface (about every 0.3 mm), the deepest it ever lies inside the
  cutter: the distance from the point to the tool's surface, at the closest approach of every cutting move. This
  does not depend on the grid: a 0.08 mm cut into a wall is found with 0.25 mm cells. A gouge is a sample deeper
  than the tolerance (0.05 mm unless stated).
- **Leftover.** Stock height minus part height at every cell centre inside the part's outline: its volume, its
  largest height, and the regions with their place and size. Material narrower than a cell beside a wall is not
  seen. Tabs and the stock around a cut-out part are outside the outline and are not leftover.
- **Collisions.** A rapid whose tool (cutter, shank or holder) dips into the stock as it stands at that moment; a
  cutting move whose shank (above the flute length) or holder would pass through stock.
- **Cycle time.** A trapezoidal speed profile per move under one acceleration for all axes, the speed through a
  corner from the junction deviation of Grbl's planner, with a backward and a forward pass. The limits (rapid rate,
  acceleration, junction deviation, feed ceiling) are yours (`machine: {...}`) or defaults named as assumed.
  Spindle run-up and tool changes are not timed.

The verdict is **fail** on a gouge, a rapid through stock, a shank or holder collision, a cut deeper below the
stock than cutting through needs, a word the controller would not accept, or a file whose motion is not the
plan's. Leftover does not fail; it is reported and must be acknowledged at release.

Not judged: workholding, deflection, chatter, chip evacuation, surface finish, tool wear, the machine's travel and
its own look-ahead.

## Drop-cutter

3D heights and every finishing boundary come from our own drop-cutter on the solid's tessellation (0.02 mm). For a
tool of revolution the lowest tip height over a triangle is the largest value of `z(q) − profile(|q − axis|)` over
the triangle, a concave function, so the answer is in the facet (closed form), on an edge (an end point for a flat
tool, the root of a quadratic for a ball, a golden-section search for bull-nose, drill and chamfer), or at a
vertex. Finishing boundaries are contours of that height on the plan's grid, each crossing then moved along its
grid edge to where the tool truly starts to touch.

**Why not opencamlib.** Its licence was checked: LGPL-2.1 (the repository's licence file and README, read
2026-11-28), which would work as an optional, dynamically loaded dependency beside MIT code. It is not used
because its latest release on PyPI (2023.1.11) has wheels up to Python 3.11 and Form Studio runs on 3.12, so it
could not be installed without building it. Nothing of it is in Form Studio.

## Post-processors

| Post | Tool change | Drilling | Ends with | Notes |
|---|---|---|---|---|
| `grbl` (Grbl 1.1) | `T n`, `M5`, a pause `M0` (no M6 there) | written out as G0/G1 | `M5`, `M2` at the clearance height | no move in machine coordinates: an unhomed machine has no known machine zero |
| `linuxcnc` | `T n M6`, `G43 H n` | `G98 G81` / `G83 Q` | `G53 G0 Z0`, `M2` | `G64 P0.01` |
| `fanuc` (generic mill) | `T n M6`, `G43 H n` on the first Z move | `G98 G81` / `G83 Q` | `G91 G28 Z0`, `M30`, `%` | `%`, `O1000`, comments in capitals |
| `haas` | as Fanuc | as Fanuc | `G53 G0 Z0`, `M30`, `%` | `%`, `O00001` |
| `marlin` (Marlin with a spindle) | `M5`, a pause `M0` | written out | `M5` | `;` comments; `G0` carries the rapid rate as `F`; no G54 unless another offset is asked for; no M2/M30 |

Every program states its units (`G21` or `G20`), absolute distances (`G90`), the XY plane and feed per minute where
the controller knows them, and its work offset (`G54` to `G59`). Words are modal. Coordinates have three decimals
in millimetres and four in inches; an arc's centre is taken from the rounded start point so the arc closes within
the controller's tolerance.

Reading back lists what the dialect does not accept, an arc that does not close, cutter compensation, another
plane, a program that never states its units.

## Release

G-code goes into a release only when all of this holds:

1. it was asked for (`cam_post(include=true)`, `form cam post --include`);
2. its simulation is **current**: made for the head revision's solid, the same tools, options, speeds table and
   post, from files that still have the hashes that were simulated;
3. the simulation shows no gouge and no collision;
4. no tool, speed or feed is assumed;
5. a person approves in Form Studio, acknowledging the label and any leftover.

The release then carries the program(s), `CAM_REPORT.md` and a `cam` entry in the manifest with the label. Until a
physical result is recorded for that program (`record_physical_result(kind="machined", result=good | gouged |
collision | left_material | scrapped)`), the label is **"simulated, not proven on a machine"**. A result belongs
to the files it was run from: a new program starts unproven again.

Form Studio never sends a program to a machine.

## Files and the viewport's data

Under the project's `artifacts/cam/`: `plan-<key>.json`, the program(s), `sim-<key>.json`, `view-<key>.json`.

`view-<key>.json`, format `form-cam-view/1`, in the design's frame:

```
{"format": "form-cam-view/1", "label": "simulated, not proven on a machine", "setups": [{
   "n", "name", "frame": {"R", "origin", "text"},
   "toolpaths": [{"op", "operation", "label", "tool", "kind": "feed" | "rapid", "color", "count",
                  "positions": base64 float32 (count, 2, 3),      // each segment's two ends
                  "t": base64 float32 (count)}],                  // seconds at each segment's end
   "stock": {"positions": base64 float32 (n, 3), "indices": base64 uint32, "colors": base64 uint8 RGBA,
             "status": base64 uint8 per vertex (0 cut to size, 1 leftover, 2 gouge), "grid", "cell_mm"},
   "marks": [{"at", "kind": "gouge" | "leftover" | "collision", "label"}]}],
 "legend": {...}}
```

Toolpaths are one entry per operation and kind, coloured by operation; `t` lets a scrubber play them in time.
The stock is the simulated height field as a mesh (at most 256 vertices a side; a coarse vertex takes the worst
status of its cells).

## What was verified

`tests/test_cam.py`, each against a number known in advance:

| What | Result |
|---|---|
| Drop-cutter on a sphere of radius 20 (flat, ball, bull-nose, drill, chamfer) | within the tessellation's sag of the closed form, never above it; on a 101,000-triangle sphere 0.0006 to 0.0010 mm |
| Drop-cutter on planes of slope 0.25, 1 and 2.5 | equal to the closed form within 2e-6 mm |
| Waterline around a cylinder of radius 10 with a Ø6 cutter | a circle of radius 13 within the tessellation's 0.02 mm, never inside it by more |
| Cycle time | one long move, a move too short to reach its feed, two collinear moves, a right-angle corner (20.171338 s), exact stop, a rapid: equal to hand calculation to 1e-6 s |
| Posts | each of the five, in mm and in inches, parses back to the plan's motion move for move; each has its own codes and none it does not accept |
| A slot | removes a stadium's volume within 1 % |
| A pocket's corners | four regions of r²(1 − π/4) each, the pocket's depth high |
| A ball on a pocket floor at 1 mm stepover | cusps no higher than r − √(r² − (s/2)²) = 0.042 mm |
| Planted gouges | 0.2 mm into a wall, 0.08 mm (under one cell), 0.3 mm into a floor: found with their depth within 0.005 mm |
| Planted collisions | a rapid 2 mm into stock, a cut 2 mm deeper than the flutes, a holder 4 mm into a boss: found with their depth |
| Adaptive clearing | mean engagement within 1.25 × and 95th percentile within 1.6 × the stepover; entries down a helix |
| Release | blocked while anything is assumed or the simulation is stale; carries the program, its hashes and its label; a physical result changes the label for that program only |

## Limits

- 3-axis only. A height field holds no undercut: what a setup cannot see from above is another setup's work.
- Material removed by one setup is not carried into the next, except holes drilled or bored through.
- Adaptive clearing is steered on the plan's grid; it keeps its allowance plus three quarters of a cell from the
  part, and its first move out of an entry cuts a full slot.
- A sharp inside corner of a finishing boundary is cut short by under a cell, so slightly more than the cutter's
  own radius is left there. The simulation measures it.
- A feature thinner than the plan's cell can be missed by the planner. The gouge measurement does not use the grid
  and finds what that causes.
- No thread milling, tapping, T-slots, engraving, or rest machining beyond finishing with a smaller tool.
