# Manufacturability

Can this part be made by the process it is meant for, and if not, what change makes it so? Form Studio answers on
the exact solid, draws every problem on the part, and for the problems it can fix, writes the fix into the design's
own source, checks the result again, and only then says it is fixed.

```
form dfm <project> --process cnc --set tool_d=6 --set material=metal     # JSON: rows, findings, fixes, overlay
form dfm <project> --process injection --set resin=abs --png check.png
form dfm <project> --process cnc --set tool_d=6 --set material=metal --fix cnc.corner_tool
form dfm rules sls                                                       # the rule table with its sources
```

MCP: `manufacturability(project, process, options)` and `apply_fix(project, process, fix, options)`. The code is
`form/dfm/`; the rule tables are `form/dfm/rules/<process>.toml`.

## Processes and their rules

Every limit names the page it was read from, with the date it was read (all on 2026-11-28; pages without a date
are marked undated). A limit that is plain geometry says **computed**. A limit nobody published is left out. A rule
whose input is missing (no tool stated, no resin, no machine) is **not checked**, and the check's verdict is then
*not proven*: not checked is never a pass.

### CNC milling (`cnc`)

Options: `tool_d` (flat end mill diameter, needed), `material` (`metal` or `plastic`), `axes` (3, 4 or 5),
`flute_l` and `holder_d` (holder clearance), `rotary_axis` (4-axis).

| Rule | Limit | Source |
|---|---|---|
| Every face reached by the tool | no unreached area | computed |
| Internal vertical corner ≥ tool radius | fail under r | computed |
| Internal vertical corner ≥ ⅓ cavity depth | warn under | Protolabs Network (Hubs), *How to design parts for CNC machining* |
| Tool reach | warn over 4 × D, fail over 30 × D | same |
| Thinnest wall | metal: fail 0.5, warn 0.8 mm; plastic: fail 1.0, warn 1.5 mm | same |
| Hole depth | warn over 4 × d, fail over 40 × d | same |
| Smallest hole | fail under 1 mm, warn under 2.5 mm | same |
| Hole at a drill size | warn off the series | same (the series itself, 0.1 mm steps to 13 mm and 0.5 mm to 20 mm, is unsourced) |
| Setups | shown, never failed | computed |

### Injection moulding (`injection`)

Options: `resin` (`abs`, `acetal`, `acrylic`, `lcp`, `lfrp`, `nylon`, `pc`, `polyester`, `pe`, `pps`, `pp`, `ps`,
`pu`), `pull` (`[x, y, z]` or `auto`), `cavities`, `textured`.

| Rule | Limit | Source |
|---|---|---|
| No undercut against the pull | none | computed |
| Draft | fail under 0.5°, warn under 2° | Protolabs, *Plastic Injection Molding Design Guidelines* |
| Draft on textured faces | fail under 3° | same |
| Wall range per resin | warn outside the table (ABS 1.143 to 3.556 mm, ...) | same |
| Projected area | warn over 175 in² | same |
| Depth from the parting line | warn over 101 mm | same |
| Clamp tonnage | 2 to 10 tons/in², 3 to start | RJG, Inc., *Clamp Tonnage: More is Better, Right?* (2017-05-01) |

### Printing

| Rule | FDM | SLA | SLS | MJF | LPBF |
|---|---|---|---|---|---|
| Thinnest wall | 0.8 mm | 0.2 mm | 0.6 mm | 1.0 mm | warn 1.0, fail 0.381 mm |
| Overhang from level | warn under 45° | warn under 10° | not checked (powder bed) | not checked (powder bed) | fail under 45° (55° for 316L, CuNi2SiCr) |
| Smallest hole | | 0.5 mm | 1.0 mm | fail 1.0, warn 2.0 mm | |
| Enclosed void | | 2 drain holes Ø0.75 mm | 2 escape holes Ø3.5 mm | 2 holes Ø2 mm | fails; no sourced hole size, so no fix |
| Build volume | `machine` or your printer | `machine` | 159.8 × 159.8 × 295.5 mm | 370 × 274 × 375 mm | 245 × 245 × 330 mm |
| Source | Protolabs Network (Hubs), *What are the key design elements for 3D printing?* | Formlabs, *Design specifications for 3D models (Form 4L generation)* | Formlabs, *Fuse Series SLS Design Guide* | Materialise, *Design Guidelines for PA 12 (MJF)* | Protolabs, *Designing for Metal 3D Printing* |

The SLA, SLS, MJF and LPBF numbers are one maker's or one service's machine and material, named on every result.
A shop's own limits are given as `overrides={"rule_id": {"fail": x, "warn": y}}` and the row then says
*specified*, with the source it replaced.

### Sheet metal (`sheet_metal`)

Measured by `form/sheet` (the part unfolded on the B-rep and folded back to prove it) and judged here with the same
rule format: one sheet that unfolds, the fold-back within 0.01 mm, no overlap in the flat, flange ≥ 4 t (Protolabs),
flange for an 8 t V-die (Bystronic), hole ≥ t, hole to edge, hole to bend ≥ 4 t, hem inside diameter ≥ t
(Protolabs). Options: `material`, `k`, `method` (table | din6935), `forming`. Limits in multiples of t use the
rule field `per = "t"` with the measured thickness. The flat pattern DXF, the cut-file check, bend order and
service preflight are their own tools: see [SHEET_METAL.md](SHEET_METAL.md).

## How it is measured

On the kernel's B-rep and its 0.05 mm tessellation, in the kernel worker:

- **Surface samples.** The tessellation's triangles split until no edge is longer than the sample spacing (about the
  part's diagonal / 140, at most 60,000 samples); each keeps its B-rep face.
- **Rays along one direction, all at once.** The triangles are projected on the plane normal to the direction and
  binned on a grid; each ray meets only the triangles of its cell (exact for the tessellation).
- **Pull direction.** Directions over the Gaussian sphere (a golden-angle spiral on the hemisphere, since a pull and
  its reverse release the same surface), the axes, the normals of the largest flat faces and the axes of cylinders,
  then a local refinement around the best three. Score: the undercut area (a sample neither half releases), then
  the area with no draft. An axis or a face normal wins over an oblique direction that is as good.
- **Parting line.** The silhouette for the chosen pull: tessellation edges between a triangle released by one half
  and one released by the other (faces along the pull go with the +pull half). Proposed for a two-plate tool; the
  parting surface is not designed.
- **Side actions and lifters.** Each connected undercut region is tested along 16 directions in the parting plane
  and its own mean normal: a direction along which it leaves the part is a side action; a free stroke as long as
  the undercut is deep is a lifter; neither is a collapsible core or a change to the part.
- **Draft per face.** asin(n · pull) toward the half that releases the face: exact for planes and for cylinders and
  cones along the pull, sampled on other surfaces (the band at the parting line excluded).
- **Tool access.** For each tool direction, a height field (the z-map of CAM) on a pixel of a quarter of the tool
  radius, the highest surface over a disc of the tool radius (a flat end mill cannot go lower than the highest
  material under its end), and the same over the holder's radius above the flute length. A sample is reached when
  a tool centre near it (pushed out along its normal, or around it) comes down to it. Setups by greedy set cover of
  the reachable surface; bores are drilled and judged by the hole rules instead.
- **Internal corners.** Concave straight edges (convexity from the two faces' normals at the edge, exact) and concave
  cylindrical blends along a tool direction whose faces that direction reaches.
- **Walls.** The thickness field (`form/thickness.py`): an inward ray from every sample, each thin region's minimum
  re-measured by an exact B-rep ray. Knife edges are listed, not counted as walls.
- **Projected area.** Pixel coverage of the shadow along the pull, boundary pixels counted half, ± half the boundary
  pixels' area.
- **Voids.** The solid's inner shells (exact).

Not judged, and said on every result: for moulding, fill, packing, cooling, warpage, shrinkage, weld lines, gates
and sink; for CNC, fixturing, deflection, chatter, finish, threads and tolerances; for printing, warping,
adhesion, supports and strength.

## Fixes, proved

| Rule | Fix written into the design |
|---|---|
| Draft | a parameter `dfm_draft_deg` and a feature `dfm_draft` (`form.dfm.ops.draft`): every face along the pull turned about its far end, so the draft only adds material and no wall gets thinner |
| Internal corners | a parameter `dfm_corner_r` and a feature `dfm_corners` (`ops.round_corners`): at least the tool radius, and a third of the cavity depth when that builds; an existing blend that is a parameter is raised with `set_param` |
| Enclosed voids | a parameter `dfm_escape_d` and a feature `dfm_escape` (`ops.escape_holes`): the source's count and diameter, along the shortest way out |
| Thin wall | `set_param` on the parameter whose value is the wall |
| Hole off the drill series | `set_param` on the parameter whose value is the hole (or its radius) |

`apply_fix` builds the edited source without saving it and checks it (the preview). It applies only a candidate
that turns every targeted rule to pass and makes no other rule worse; a trade is shown and applied only with
`accept_trades`. It then saves the edit through `edit_design` as a new revision and checks the new head again from
a fresh measurement. It says **fixed** only when that second check passes the rule, with before and after pictures.
A plain Recipe is lifted into features first (`edit_design`'s canonical form), so the fix is a feature there too.

## The overlay

`artifacts/dfm/overlay-<key>.json`, format `form-dfm-overlay/1`: the same fields as an analysis map (`positions`,
`indices`, `values`, `colors` in base64) plus `status` per vertex (0 pass, 1 warn, 2 fail, 3 not checked), `faces`
(per B-rep face: status and rules), `markers` (one per finding, at its place) and `lines` (the parting line). `map`
says what `values` holds: draft in degrees, tool reach in tool diameters or overhang in degrees from level.

## On the Bench

`register_studies` adds one study per process (`dfm_cnc`, `dfm_injection`, `dfm_fdm`, ...), keyed by the geometry,
the rule table's hash and the options, so a new revision or an edited rule makes it stale.
