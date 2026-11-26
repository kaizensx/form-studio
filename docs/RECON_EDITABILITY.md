# Mesh to CAD: editability follows recognition

A reconstruction used to answer all or nothing per part: when the route that would have made a recipe failed
somewhere, the result was Layer 1 or Layer 0, a solid with no Params, **0 % editable however much of its surface had
been recognised**. This page records what was measured, what changed (`form/recon/mixed.py`, `form/recon/patterns.py`,
the budget in `form/recon/pipeline.py`) and the numbers before and after.

## What was measured

Three parts of one product (a plate with rails, a tray and a toothed part), private meshes measured on one Mac only:
nothing of them, and nothing derived from their geometry, is in the repository. Tolerance 0.1 mm (a remodel's default), budget
240 s (the default), program route on, CADFit off, dev at `a20b175`, the parts one after another (581 s in all). The
same Mac ran other work at the same time, so times are a few tens of percent noisy.

| Part | Result | Analytic surface (Layer 1) | Editable | Time |
|---|---|---|---|---|
| Plate with rails | Layer 1 | 90.82 % | 0 % | 225 s |
| Tray | Layer 1, 0.1065 mm (outside the 0.1 asked for) | 68.78 % | 0 % | 226 s |
| Toothed part | Layer 0 | 27.42 % (did not close) | 0 % | 130 s |

Why, read from the reports and from running each route alone:

- **Plate with rails.** The program route read 53.6 % of its walls as sketches, then spent 113 s booleaning 669 kept slices of
  the mesh and built an invalid solid (two solids, negative volume, 87 mm from the mesh); in the pipeline it was
  stopped at its 85 s share with nothing to show. The feature tree failed on a chamfer twice and then ran out of
  time. Layer 1 (90.82 % analytic, within the tolerance) was the result: no recipe, so 0 %.
- **Tray.** The program route read 39.9 % of its walls as sketches and gave up below its fixed 40 % threshold. The
  feature search was stopped after 148 s. Layer 1 was chosen over Layer 0 although it was 0.1065 mm from the mesh,
  outside the tolerance.
- **Toothed part.** The program route read 68.5 % of its walls as sketches (its teeth among them, as arcs repeated in each
  level's sketch), but one boolean, the kept slices of the slanted wedge fused to the features, returned a null shape
  at every fuzzy value tried, and that one failure threw the whole route away. Layer 1 did not close. Layer 0.

The hypothesis holds: **the choice was all or nothing per part**. Four gates each discarded everything that had been
recognised: a share threshold (40 %), one failing boolean, one failing fillet or chamfer plus the clock, and a Layer 1
result that has no recipe by construction. None of them kept what did work. Spending was not tied to what a route
could still add either: the program route used its full share on a part where it could not finish, and the slower
layers then had less.

## What changed

1. **A floor** (`mixed.py`). Right after Layer 0, what is recognised on the exact solid becomes features, and
   the rest stays frozen, exactly: planes grouped by plane become dimensions (a thickness to the opposite face, a
   width between two mirrored faces, or a level), each kept only when moving it 0.5 mm builds one valid solid that
   changed (`ops.push`: the faces swept out or in). Every later route is a candidate against it. A recognised part
   is no longer 0 % because one route failed elsewhere.
2. **Patterns first** (`patterns.py`). Teeth repeated round an axis are found on sections of the mesh (the turn that
   lays the outline's flanks back onto it, about each hole's centre), the run of equal pitches is cut out of the base
   as one annular band, and one tooth sketch is extruded over the levels where every tooth holds and repeated as a
   polar pattern (pitch, first angle, count and levels are Params). The pattern is measured against the mesh; its
   angle and phase are fitted (`form.remodel.fitparams`) when the first build is outside the limit, and when it still
   is the teeth stay in the base and the residual (`form.remodel.residual`) is reported as the work left.
3. **Budget by predicted gain** (`pipeline.py`). The program route still runs first, but after reading the slices
   it predicts its own best share (`program.predicted_share`: what faces or runs along its direction, less the walls
   that do not read as sketches) and is built then only when that can be enough on its own (`PROGRAM_ENOUGH`, 80 %);
   a part it makes in seconds stays the fast path. Otherwise Layer 0 and the floor come next, and the program route
   is read again, within the time its gain is worth, only when its prediction beats the floor. After the floor, each route gets at most the share of the budget
   that matches the share of the surface it could still add (`GAIN_K`, `LAYER_GAIN_K`; the floor's pushed faces count
   half, `FLOOR_CREDIT`, since a later route can still turn them into holes, fillets and sketches), and a route worth
   less than `MIN_STAGE_S` is not started. The feature search does not run when Layer 1 recognised no more
   of the surface than the result in hand already makes editable. Inside the floor, each face group is checked in
   order of area until the predicted gain per second of checking falls below `mixed.MIN_RATE`.
4. **Ranking.** The floor beats another candidate only when its editable share, at half credit, is higher; the
   critics (`gates.py`) rank the other candidates as before but not the floor, which is the exact solid with faces
   that move. A Layer 1 solid outside the tolerance no longer replaces Layer 0 as the fallback.

What it is not: a pushed face is a direct edit of the kept solid (its neighbours are not reshaped), not a sketch
history; the report names the method ("mixed: recognised features on the kept solid") and the recipe says so.

## After

The same three meshes, the same settings, one after another:

| Part | Result | Editable surface (feature area) | Dimensions that move | Deviation | Time |
|---|---|---|---|---|---|
| Plate with rails | the floor: 24 face dimensions | 0 % → 91.37 % | 24 of 24 | 0.00009 mm | 225 s → 57 s |
| Tray | the floor: 24 face dimensions | 0 % → 75.99 % | 24 of 24 | 0.1065 → 0.0001 mm | 226 s → 91 s |
| Toothed part | the floor: a tooth pattern (4 teeth at 18.0°, levels 3.45 to 8.7) and 8 face dimensions | 0 % → 76.74 % | 12 of 12 (13 Params: the tooth count is not a dimension) | 0.0832 mm | 130 s → 100 s |

All three within the 0.1 mm tolerance, 248 s in all (581 s before). The program route on the plate predicted at most
50.8 % of the surface, under the 80 % it needs to be enough alone, and below the floor's 91.37 % it was not read again
(8 s instead of its 85 s share); on the tray it gave up at its 40 % threshold as before (15 s); on the toothed part it
predicted 85.4 %, was built and failed again (58 s). On the tray, Layer 1 had the 45 s its predicted gain was worth and
was stopped. The toothed part's fifth tooth merges into the slanted outline
next to it and is not one of the pitch's copies (1.5 mm from the tooth), so it stays in the frozen base.

## The bench

`docs/RECON_BENCH.md`, regenerated: no part lost B-rep or editable share. `filleted_bracket` gained (editable 75 % →
100 %, B-rep 90.89 % → 100 %: its sketch program now predicts it cannot be enough alone, and the feature tree it gets
to is). The parts the program route makes in seconds keep their times. The parts the feature tree makes pay for the
floor before it: `flanged_shaft` 145 s → 207 s, `enclosure_with_holes` 154 s → 180 s, `filleted_bracket` 40 s → 56 s;
`stepped_bracket` and `filleted_block` were faster (113 → 89 s, 163 → 130 s). Same caveat on times: a shared machine.

## Synthetic failure classes (committed)

`tests/recon_fixtures.py` rebuilds each failure class with build123d, none of the private geometry:

| Fixture | Failure class | Checked in `tests/test_recon_mixed.py` |
|---|---|---|
| `railed_tray` | planes everywhere, rails with 45° chamfers; the routes that make recipes fail (made to fail in the test, as the chamfer did) | without the floor: Layer 1, 0 % editable; with it: within the tolerance, at least 50 % of the surface editable, the plate's 2.5 mm thickness a Param that moves |
| `rounded_tray` | walls rounding along the main direction: the program route reads 30 % of them as sketches and gives up (without the floor: Layer 0, 0 % editable, measured) | the floor, at least 50 % editable |
| `sector_ratchet` | six teeth round a hole on a slanted wedge (the program route reads the teeth as arcs in every level's sketch) | one tooth sketch and a polar pattern: 6 teeth at 20°, levels 0 to 6; one more tooth adds material |

Plus: `ops.push` moves exactly one plane, a sketch program that cannot beat the floor is not built (`railed_tray`),
and a floor with no time left offers no recipe and says why.
