# Inverse design and topology optimisation

Two ways to let the requirement shape the part, and one rule for both: **what is reported was built by the kernel and
solved by the strength study.** A surrogate model, a density field and a prediction are tools for choosing what to
build next. None of them is ever the result.

| | What you say | What you get | Tools | Terminal |
|---|---|---|---|---|
| **Inverse design** | "Hold 250 N here with a safety factor of 3, as light as possible" | The variants of the design that do it, on a Pareto front, each built and studied | `inverse_design`, `get_inverse_design` | `form optimize pareto` |
| **Topology optimisation** | "Keep half the material, where it matters" | Lightening pockets as named features with parameters, studied again as real CAD | `topology_optimise`, `get_topology`, `apply_topology` | `form optimize topology` |

Both read the load case from the design's static strength study ([STRENGTH.md](STRENGTH.md)): the faces that are
held, the faces that are loaded, the material with its sources. Nothing is entered twice. Both run in the background
with progress and cancel, store their record beside the revision, and appear in the Bench (Design chapter) as
**Inverse design** and **Topology optimisation**. Both need the optional strength engine; without it nothing is
computed and the call says so.

`optimize` (goal seek, one objective) and `make_lighter` are unchanged. Use `optimize` for a quick single-objective
search on what the kernel computes; use inverse design when the requirement is a strength one, or when there are two
or three things to trade.

## Inverse design

```
inverse_design(project, minimize=["mass_g", "fea.max_displacement_mm"], require=["fea.safety_factor >= 3"],
               vary=[{"key": "height", "min": 12, "max": 40}, {"key": "t", "min": 2, "max": 10}],
               budget={"solves": 20, "seconds": 600})
get_inverse_design(project, wait_s=60)

form optimize pareto arm --minimize mass_g --minimize fea.max_displacement_mm \
     --require "fea.safety_factor>=3" --vary height:12:40 --vary t:2:10 --solves 20
```

One to three objectives, any number of requirements, one to six parameters. With `vary` left out the search takes
the design's lengths that are not interfaces (at most four) and names them in the result.

### Metrics

| Metric | From | Evidence |
|---|---|---|
| `mass_g` | B-rep volume × the density of the study's material (else the design's) | computed; the density's source is stated, and it is labelled assumed (1.24 g/cm³) when no material is set |
| `volume_cm3`, `width`, `depth`, `height`, `min_wall_mm`, `derived.<key>`, `statics.<key>` | the kernel, per candidate | computed (B-rep) |
| `overhang_mm2`, `contact_mm2` | the best orientation of each candidate | computed; a proxy for print support, not a slice |
| `fea.safety_factor`, `fea.peak_von_mises_MPa`, `fea.max_displacement_mm` | the static study, solved on each candidate | simulated (FEA), each point with its own stated error |
| `modal.frequency_Hz` | a modal study (`modal_study=`), solved on each candidate | simulated (FEA) |
| `cost` | `mass_g` × a price per kg | only when a price is known: `rates={"per_kg": x}` (labelled assumed), or your own price for the material (specified). No rate is made up. With one material it orders designs exactly as mass does |

Print time and sliced support come from a slice, which a search does not run per candidate: slice the variant you
keep. Manufacturability rules (wave E) join as metrics when that wave lands.

### The search

`form/inverse/search.py`, NumPy only:

1. A Latin hypercube of real evaluations, with the design as it is as the first point.
2. A Gaussian process (Matérn 5/2, one length scale per parameter) per objective and per requirement, fitted to
   every real evaluation, and one more on "did it fail to build or to solve" when some did.
3. NSGA-II (Deb et al. 2002) on those surrogates, read optimistically (mean minus one standard deviation), so an
   unexplored region is worth a look.
4. From the predicted front, the candidates whose optimistic prediction adds the most hypervolume to the front of
   real evaluations are built and solved, four per round; after each pick the front is extended by the pick's mean
   prediction, so a round's picks spread out. When nothing is predicted to improve, the most uncertain is taken.
5. Again from 2, until a limit is reached.

### What makes the result honest

- **Every reported point is real.** The record holds only candidates that were built and, for a strength metric,
  solved. No predicted value appears anywhere in it.
- **The front is of verified points.** A candidate that did not build, whose study did not converge or could not be
  set up, or that misses a requirement stays in the record with the reason and is never on the front. The chart
  data shows them (`misses`, `failed`), it does not drop them.
- **The lower safety factor counts.** `fea.safety_factor` is the value with the study's stated discretisation
  error applied. A point whose central value passes while its lower value does not is marked `close`, not passing.
- **The budget is stated.** Strength solves, builds and seconds used against their limits, and why the search
  stopped. Defaults: 24 solves, 900 s.
- **Approximate, and it says so.** The front is the best of what was evaluated. A better design may exist between
  the points, and nothing bounds by how much.

A limit worth knowing: a study's faces are picked as points. A candidate on which a picked point no longer lies on
a face (a plate made so low that the point is in the air) cannot be studied; it is reported with that reason.

### Keeping a variant

Every front point carries its parameter values. `inverse_design(project, save_point=<index>, name="Light")` or
`form optimize pareto <project> --save 15:Light` saves it as a named variant (`save_variant` with the values does the
same); promote it to a revision like any variant. A search made on other design source is stale.

### Chart data

`get_inverse_design(full=True)` (or `--show --full`) returns `chart`: the axes (metric, label, unit, which way is
better), one entry per evaluated point with its place on each axis, its parameter values and its state (`front`,
`feasible`, `misses`, `close`, `failed`, and whether it is the current design), the front in order, and the
hypervolume after each round.

### Example

A flat arm, 80 × 30 × 5 mm, held at one end, 60 N across the other, PETG (test values: E 2.0 GPa, yield 45 MPa,
1270 kg/m³). Lightest and stiffest with a safety factor of at least 3, over height (12 to 40 mm) and thickness (2
to 10 mm), 20 solves:

| | |
|---|---|
| Evaluated | 20 candidates, 20 strength solves, 107 s |
| Meet the requirement | 16; on the front: 8 |
| Lightest on the front | height 32, thickness 2: 6.50 g, 1.09 mm, safety factor 3.00 (converged to 0.6 %) |
| The design as it was | height 30, thickness 5: 15.24 g, 0.52 mm, safety factor 6.58: on the front |
| Stiffest on the front | height 37, thickness 9: 33.8 g, 0.16 mm, safety factor 18.1 |
| Missed | 4: three below a safety factor of 3, one on which a picked face was gone |

### Verification

`form optimize pareto --verify` (`form/inverse/verify.py`, `tests/test_inverse.py`): analytic problems with a known
front, ZDT1 (convex) and ZDT2 (concave), Zitzler, Deb and Thiele (2000). The measure is the inverted generational
distance (IGD) to 500 points of the known front.

| Case | Evaluations | IGD | Accepted |
|---|---|---|---|
| ZDT1, NSGA-II alone, 30 variables | 60,100 | 0.0084 | ≤ 0.02 |
| ZDT2, NSGA-II alone, 30 variables | 60,100 | 0.0065 | ≤ 0.02 |
| ZDT1, surrogate-assisted, 6 variables | 80 | 0.033 | ≤ 0.08 (NSGA-II alone with the same 80: 1.21) |
| ZDT2, surrogate-assisted, 6 variables | 80 | 0.066 | ≤ 0.08 (NSGA-II alone with the same 80: 1.91) |
| ZDT1 with x₁ ≥ 0.3, surrogate-assisted | 50 | 0.031 | ≤ 0.08, no front point violates it |

The tests also hold the evaluation limit, a stop signal and an evaluator that runs out, and that failed and
infeasible evaluations are kept and never on a front. With the engine installed, a real search on a real design
checks that every front variant was built and solved, meets the requirement at its lower value, and that nothing
dominated is on the front.

## Topology optimisation, written back as features

```
topology_optimise(project, volfrac=0.5)          # or mass_g=8, or safety_factor=3
get_topology(project, wait_s=120)
apply_topology(project)                           # the pockets become features: one revision

form optimize topology arm --volfrac 0.5
form optimize topology arm --apply
```

### 1. The layout: SIMP on the study's mesh

Minimum compliance (the stiffest layout) for a given amount of material, by the method of Bendsøe and Sigmund (2003)
as in Sigmund's 99 lines (2001) and the 88 lines of Andreassen et al. (2011): one density per element, stiffness
E_min + ρ³ (E₀ − E_min), a density filter of radius `rmin` that sets the smallest member, and the optimality
criteria update with a move limit of 0.2.

The elements are the strength study's own: quadratic tetrahedra from Netgen, solved by the same solvers
(`form/topo/mesh3d.py`). One mesh is used for the whole optimisation.

- **Non-design regions.** Elements within `keep` millimetres of the faces that carry supports and loads stay
  solid, and so does a rim of `rim` millimetres along the side walls, so no pocket breaks the silhouette. Defaults:
  `keep` = `rmin`, `rim` = half of `rmin`.
- **A pull direction** (`pull`: x, y, z or a vector; default: the part's thinnest direction) makes the layout 2.5D:
  the filter averages each element with everything above and below it, so the density cannot change along the
  pull. That is what lets the result be written as pockets cut along it.
- **Target.** `volfrac` (the fraction of the volume that stays), `mass_g` (turned into a fraction of the solid's
  mass), or `safety_factor`: the run is repeated at a higher fraction, up to `tries` times, until the rebuilt part's
  studied safety factor (lower value) meets it. Every try is in the record.
- **Stiffness is optimised, not stress**, for one load case. Strength is checked afterwards, on the rebuilt part.

### 2. Reconstruction: from a density field to features

`form/topo/recon.py`, `form/topo/emit.py`, `form/topo/cad.py`. Each step with what it decides:

1. **Picture.** The field is read as a picture across the pull direction: the mean density through the part at
   every pixel (a quarter of an element wide).
2. **Threshold.** The level at which the solid area equals the volume fraction asked for.
3. **Clean.** Void in the non-design regions and the rim is given back; specks smaller than the smallest pocket are
   dropped; an island of material inside a pocket would fall out of a through cut, so it goes with the pocket and is
   counted. The pockets are then grown evenly, every rib thinned by the same amount from both sides, until the
   material left is the fraction asked for, and never so far that two pockets join or a rib falls below half the
   smallest pocket. When that limit stops it, both fractions are stated.
4. **Outline.** Each pocket's boundary is traced at sub-pixel positions (marching squares), reduced to the fewest
   corners within 0.2 `rmin` of the traced line (Douglas-Peucker), and sides too short for a corner arc are merged.
5. **Ribs.** The material between the pockets is thinned to its centre lines (Zhang and Suen 1984). Each stretch
   between junctions is one rib, reported with its length and its width.
6. **Features.** One named feature per pocket, "Lightening pocket 1" and so on, added after the design's last
   feature through the edit protocol, with three parameters:

   | Parameter | What it does |
   |---|---|
   | `topo_inset` | every pocket's outline moved inward: each rib wider by twice this |
   | `topo_fillet` | the radius of the arc at every pocket corner (default 0.4 `rmin`); 0 leaves them sharp |
   | `topo_web` | a floor left under the pockets; 0 cuts through |

   A pocket is straight lines between its corners with tangent arcs: every pocket can be suppressed, deleted or
   reshaped in the feature tree, and its corners are numbers in the design's source. An inset that splits a pocket
   cuts both parts; one that leaves no room cuts nothing; the result is always a valid solid.

Lines and arcs, not splines, and that was measured: the kernel's volume of a solid cut along one long spline was
several per cent off the tessellated solid's (so the mass would have been wrong), and the strength study's mesher
did not get through such faces.

### 3. Verification: the rebuilt CAD is studied again

The edited design is built by the kernel without being saved; its volume is computed from the B-rep. Then the
strength study is solved on that solid with the refining solver, exactly as any strength study: refinement until
the answer stops changing, the discretisation error stated, a safety factor only when it converged. The record sets
three things side by side:

| | From | Evidence |
|---|---|---|
| The density result | the optimisation's own mesh, elements above the threshold at full stiffness | indicative: one coarse mesh, a jagged boundary |
| **The rebuilt CAD** | the strength study on the built solid | simulated (FEA, converged to N %): the one to rely on |
| The solid part | the same study on the design as it was | simulated (FEA) |

`comparison.rebuilt_over_density` gives the ratios (safety factor, compliance, displacement, mass). The stated band
for the safety factor is 0.5 to 2: outside it the two disagree and the record says so. The density result's peak
stress is read at the quadrature points; averaged over an element of that size it was half the rebuilt part's peak.

### 4. When the features do not fit

Honestly: when no pocket is found, when the design's source cannot take feature edits (an OpenSCAD design, a
built-in building block), when the pockets do not build, or when the mode is `free` (a 3D layout, which has no single
pull direction), the outcome is `mesh body`, with the reason. The smoothed surface of the dense region is always
written (marching tetrahedra at the level that holds the volume asked for, Taubin smoothing with the vertices on
the part's own surface left where they are) and offered, labelled "mesh body (not editable CAD)".
`apply_topology(mesh_body=True)` adds it to the design's references as an STL; the design does not change.

When the pockets build but the study of the rebuilt part does not converge inside its limits, the outcome is
`features, not verified`: the pockets can still be kept, and no safety factor is claimed.

### Bounds

Stated in every record: the element size and count (`h`, default the diagonal / 40, coarsened to at most 60,000
elements), the smallest member (`rmin`, default 2 `h`), the iteration limit (80) and time limit (240 s) of the
optimisation, the solves used, the strength studies run and the wall time. The study of the rebuilt part may use up
to 1.5 million unknowns and 300 s, more than a usual study, because a part with pockets has many small faces.

### The density field, for the window

`get_topology(frames=True)` (or `--show --frames`; `frames_file` is the path): for every iteration from the even
start (iteration 0), the picture across the pull direction (one byte per pixel, with the grid's origin, axes and
pixel size) and the density at the vertices of the part's surface mesh (positions, triangles, one byte per vertex),
with each iteration's compliance and volume. While a run is going, `frames=True` returns the newest picture.

### Example

The same arm, 80 × 30 × 5 mm, 60 N, PETG test values. `volfrac` 0.55, `h` 2.5 mm, `rmin` 4 mm, 40 iterations
(the run `tests/test_topology.py` makes):

| | Solid part | Density result | Rebuilt CAD |
|---|---|---|---|
| Mass | 15.24 g | 8.43 g | **8.84 g** (42 % lighter) |
| Safety factor | 6.87 | 2.37 | **2.53** (at least 2.46) |
| Largest displacement | 0.52 mm | 0.99 mm | **1.01 mm** |
| Evidence | FEA, converged to 4.5 % | one mesh of 4,486 elements | FEA, converged to 2.8 %, 3 refinements, 811,956 unknowns |

Rebuilt over density: safety factor 1.07, compliance 1.03, displacement 1.02, mass 1.05. Six pockets, 17 ribs.
Wall time 124 s: 42 solves of the optimisation, two strength studies (90 s of it the rebuilt part's).

With a safety factor as the target (`form optimize topology arm --safety-factor 2.5`, every other setting at its
default: 5,963 elements of 2.1 mm, members of 4.3 mm): the first try at 50 % of the volume gives 5 pockets and a
studied safety factor of 1.69 (at least 1.67), below the target; the second, at 58 %, gives 6 pockets, 9.36 g (39 %
lighter) and 4.20 (at least 4.14), with the density field's own reading at 4.20. Both tries are in the record. 282 s.

A finer layout is not always verified: at `h` 2 and `rmin` 3 the same arm gives 9 pockets, and the study of the
rebuilt part stopped at its limit of 1.5 million unknowns with the peak stress still changing by 5.0 % per
refinement against a tolerance of 5 %. The outcome is then `features, not verified`: mass, displacement and
compliance are reported (within 7 % of the density result's), and no safety factor is claimed.

### Verification

`form optimize topology --verify` (`form/topo/verify.py`, `tests/test_topology.py`), in the engine's Python.

**The published benchmark.** Half of the MBB beam, 50 % volume, penalty 3, on a grid of unit squares: the problem
of Sigmund (2001) and Andreassen et al. (2011), whose paper prints the final compliance under its designs. The
benchmark runs through the same loop (`form/topo/simp.py optimise`) that optimises a design's own mesh.

| Mesh | rmin | Filter | Published | Ours | Error |
|---|---|---|---|---|---|
| 60 × 20 | 2.4 | sensitivity | 216.81 | 216.8137 | 0.002 % |
| 60 × 20 | 2.4 | density | 233.71 | 233.7146 | 0.002 % |
| 150 × 50 | 6.0 | sensitivity | 219.52 | 219.5199 | 0.0001 % |
| 150 × 50 | 6.0 | density | 235.73 | 235.7337 | 0.002 % |

Accepted: within 0.05 %. The topology is checked where it is defined: material in the top and bottom chords, at the
support and under the load; void in the triangles between the diagonals. With the 99 lines' own filter radius
(1.5) the same mesh gives 203.19 in 94 iterations.

**On tetrahedra**, where no number is published, what must hold in any correct implementation: the compliance of
the solid equals the work of the loads (to 3 × 10⁻¹³), the volume constraint is met, the compliance does not rise
after the first iterations, and the layout is stiffer than the same material spread evenly (3.3 times).

**The chain.** With the engine installed, a whole run on a real design: the limits kept and stated, the density
field of every iteration stored, the layout rebuilt as features that build, the kernel's cut volume equal to the
outlines' own area through the thickness (0.2 %), the rebuilt part's study converged, its safety factor inside the
stated band of the density result's, mass, compliance and displacement within 12 to 20 %, and the revision that
`apply_topology` makes with parameters that do what they say.

### What it does not do

- One solid, one static load case. Assemblies and several load cases are not optimised.
- Pockets along one direction. A free 3D layout is found, and offered as a mesh body, not as features.
- Stress, fatigue, buckling of the thin ribs and print orientation are not in the objective. Run the buckling study
  on a part with slender ribs.
- The pockets are fitted to the revision they were found on. After any change to the design, run it again.
