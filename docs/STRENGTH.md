# Strength studies

"Will it hold?" answered on a design: pick the faces that are held and the faces that are loaded, and get stress,
displacement and a safety factor against the material's yield, with the discretisation error stated. The same engine
gives natural frequencies, the load at which a slender part buckles, steady temperatures and thermal stress.

Every result carries its evidence class: `simulated (FEA, linear static, converged to 1.1 %)`. A study that does not
reach its tolerance reads `simulated (FEA, linear static, not converged)`, says why, and gives no safety factor.

- [What a study is](#what-a-study-is)
- [Supports and loads](#supports-and-loads)
- [Materials](#materials)
- [How the error is stated](#how-the-error-is-stated)
- [Singularities](#singularities)
- [A hand estimate beside the result](#a-hand-estimate-beside-the-result)
- [Heat and thermal stress](#heat-and-thermal-stress)
- [Strength as a constraint in a search](#strength-as-a-constraint-in-a-search)
- [What the model does not cover](#what-the-model-does-not-cover)
- [Verification](#verification)
- [Timings](#timings)
- [Tools and commands](#tools-and-commands)
- [Stored results and staleness](#stored-results-and-staleness)
- [Field data](#field-data)
- [The engine and its licences](#the-engine-and-its-licences)
- [The Bench entry](#the-bench-entry)

## What a study is

| Kind | Answers | Headline |
|---|---|---|
| `static` | Stress and displacement under the loads | Safety factor, peak von Mises stress ± error, largest displacement |
| `modal` | The frequencies the part rings at | Natural frequencies in Hz (a part with no supports is a free body) |
| `buckling` | When a slender part gives way sideways | The factor on the loads at which the perfect elastic part buckles |
| `thermal` | How hot it gets and how much heat it carries | Temperature range and the heat through the part |
| `thermal_stress` | The stress a temperature field causes, with any loads | As `static`, with the temperature range |

The solid is the design's B-rep. Netgen meshes it into tetrahedra, with more elements on fillets and around holes.
The elements are quadratic (10-node) and isoparametric: the mid-side node of every edge lies on the geometry, so a
fillet or a bore is a curved surface in the model, not a row of flat facets. A design that declares an assembly is solved assembled, with its parts
bonded where they touch and a material for each part.

## Supports and loads

A face is picked as a point on it, `[x, y, z]` in design millimetres on the part as printed, the same points
`analyze_selection` takes.

| Support | Meaning |
|---|---|
| `fixed` | No movement in any direction |
| `roller` | Free to slide in the face, held across it: a part resting on a surface, or a symmetry plane |
| `pin` | A cylindrical face that may turn about its axis and is held across and along it |
| `hold` | No movement along the directions given (`"directions": [[0, 0, 1]]`), free in the others |

| Load | Unit | Meaning |
|---|---|---|
| `force` | N | A force vector spread evenly over the picked faces |
| `pressure` | MPa | Pushes on the face along its normal |
| `preload` | N | A bolt's clamping force: two equal and opposite forces pressing two face sets together. A modelled connector: the bolt's own stiffness is not in the model |
| `gravity` | g | The part's own weight in a direction |

Loads act on faces, never on a point or an edge: a point load has no finite stress under it. A static or buckling
study whose supports leave a rigid motion free is refused, with the number of motions that are free.

## Materials

A study uses four numbers: Young's modulus, Poisson's ratio, the yield strength and the density. Each comes from the
materials library with the document it was read from, or is given with the study together with its source.

```json
{"material": "AL-6061"}
{"material": {"name": "S355JR", "E_GPa": 210, "poisson": 0.3, "yield_MPa": 355, "density_kg_m3": 7850,
              "source": "EN 10025-2, mill certificate 4711"}}
{"material": {"key": "PLA", "poisson": 0.35}}
```

Nothing is defaulted. Without Young's modulus or Poisson's ratio the study is refused and names the missing value.
Without a yield strength the study runs and reports stress and displacement, and no safety factor. A value given
without a source is recorded as `assumed`.

A printed filament is solved as a solid isotropic part with the in-plane modulus of the datasheet's specimens. Its
strength is the weakest sourced direction, the ultimate strength across the layers when the datasheet has it, and the
datasheet's Z / X-Y ratio is named in the result as the knock-down applied. Layers, infill and walls are not simulated.

## How the error is stated

The mesh is refined until the answer stops changing.

1. The solid is meshed and solved at least three times. For a static study each new mesh is finer where the error
   indicator of the last one is large (Zienkiewicz-Zhu stress recovery), so the elements go to the fillets, the holes
   and the load path. The surface is meshed again from the B-rep at every level, corners and mid-side nodes on the
   geometry. Each level has at least 1.5 times the elements of the one before.
2. Every level is kept in the result: unknowns, strain energy, largest displacement, peak von Mises stress and the
   error indicator in the energy norm.
3. The stated error of a quantity is **twice its last change** where the last three levels shrink steadily, or
   the remaining change by Aitken's extrapolation when that is larger. Where the levels go up and down, it is
   **twice the larger of the last two changes**: a peak read off a mesh does not converge smoothly, and one small
   step between two meshes is not taken as convergence. It is an estimate with a margin, not a mathematical bound.
   Where the levels move one way without shrinking there is nothing to extrapolate from, and the stated error is
   twice the sum of the last two changes.
4. A study is converged when the stated error of the peak stress is within 5 % and that of the displacement within
   1 % (1 % for a frequency, 2 % for a buckling factor), and the reactions balance the loads. The tolerances can be
   tightened per study.
5. Reactions at the supports are summed and compared with the applied loads, forces and moments; the residual is in
   the result.

The safety factor is the strength over the peak von Mises stress outside the singular zones. It comes with a lower
value that applies the stated error, and with the source of the strength it is measured against.

## Singularities

At a sharp inside corner the elastic stress is unbounded (Williams, 1952): the number a mesh gives there grows with
every refinement and is a property of the mesh, not of the part. Form Studio finds these edges on the mesh (two faces
that meet at more than 180° inside the solid, turning by more than 15°), holds refinement back there, and leaves the
stress within a stated radius of them out of the peak and the safety factor. The radius is 2 % of the part's diagonal
(at least 0.5 mm) and can be set per study.

The edge of a fixed face and the edge of a loaded face are treated the same way when the peak is there and the stress
there rises at each of the last two refinements, by more than 8 % in all: a perfectly rigid support and a load that
ends abruptly are models with a singular line. Stress that merely has not settled yet is not called singular; the
study keeps refining, or ends as not converged.

Each one is listed in the result with where it is, why it is singular, how many nodes were left out, and the stress
there at every refinement, so the growth is visible. The fix for a sharp corner is a fillet; with a fillet the
stress converges and counts.

## A hand estimate beside the result

Where the part reads as a prismatic bar fixed at one end (a cantilever, a strut, a tie rod), a static result carries
`hand_estimate`: the beam-theory stress at the fixed end and the deflection at the load, from section properties
measured on the solid. Its evidence class is `computed (closed form: Euler-Bernoulli beam, section properties measured
on the solid)`, and it shares nothing with the solver.

It applies when the solid is one part, at least three times longer than wide, with the same cross-section along its
length (four slices agree within 8 %), one fixed end face and forces as loads. For anything else it says why no
formula fits: `{"applies": false, "why": "not slender: 80 mm long and 60 mm wide"}`. An estimate that does not fit is
not offered. It leaves out shear deflection and every stress concentration, so a simulated peak well above it points
to a fillet, a hole or a notch the formula does not know.

## Heat and thermal stress

`thermal` solves steady heat conduction on the same mesh. Conditions sit on picked faces:

| Condition | Unit | Meaning |
|---|---|---|
| `temperature` | °C | The face is held at this temperature |
| `convection` | W/(m² K), °C | Exchange with a fluid at `ambient_C` with coefficient `h_W_m2K` |
| `heat` | W | Heat entering, spread evenly over the faces |
| `heat_flux` | W/m² | Heat entering per area |

A face with no condition is insulated, which is also what a symmetry plane is. At least one temperature or convection
must set the level. The result gives the temperature range with where, the heat through each condition, and the heat
balance (heat in against heat out), which must close.

`thermal_stress` solves that temperature field first and then the static study with the strain α (T − `reference_C`)
added: expansion the supports or the part itself hold back becomes stress, expansion that is free does not. Supports
and loads are as for a static study; the result is a static result with the temperatures beside it.

The material needs its thermal conductivity (`k_W_mK`) for a heat study, and its expansion coefficient (`cte_per_K`)
as well for thermal stress, each from the library with its source or given with one. Steady state only; conductivity
and expansion do not vary with temperature; no radiation.

## Strength as a constraint in a search

`optimize` and `make_lighter` take a static study as a constraint:

```bash
form optimize bracket --vary t:3:10 --minimize solid_mass_g --require "fea.safety_factor>=2"
form lighter bracket --require "fea.safety_factor>=2"
```

A solve costs seconds and a search builds dozens of candidates, so the study is not solved on every one. The search
runs first on what the kernel computes for each candidate. The study is then solved on real candidates, best first,
and by halving between one that failed and one that passed, within 8 solves and 300 s. The winner is the best
candidate that was itself solved and met the constraint; `strength.solved` lists every one with its numbers and
evidence, and a candidate that was not solved is never called feasible. The result says that the search was not
steered by the strength constraint.

`fea.safety_factor` is the lower value, with the stated error applied. `fea.peak_von_mises_MPa` and
`fea.max_displacement_mm` are available too. A candidate whose study does not converge, or on which a picked face is
no longer there, fails the constraint with that reason. With a strength requirement `make_lighter` does not offer
lower infill or fewer walls: the study is of a solid part.

## What the model does not cover

- **Linear elastic material.** No yielding, no creep, no fatigue, no impact. A safety factor below 1 means the linear
  model predicts yield; it does not say how the part fails.
- **Small strain and small displacement.** The load does not change the shape it acts on.
- **Curved faces are followed by quadratic element sides,** not exactly. Where a curved side would turn an element
  inside out, the whole mesh falls back to straight sides and the result's `mesh.element` says so.
- **Isotropic, homogeneous solids.** A printed part's layers and infill are not in the model.
- **Bonded contact only.** Parts are joined where they touch; sliding, opening and friction are not modelled.
- **Linear buckling** is the load of the perfect elastic part. A real part, never perfectly straight, buckles
  earlier.
- **A study is evidence, not a certificate.** It does not replace a test of the made part.

## Verification

The solver is checked against cases with a known answer, through the same code path a design's study takes: Netgen
meshing, faces found from picked points, supports, loads, refinement and the stated error. Each quantity has the
tolerance it must meet. `tests/test_fea_verification.py` runs the suite; this table is written from a run by
`scripts/gen_strength_docs.py`.

<!-- verification:begin -->
| Case | Quantity | Reference | Expected | Got | Error | Tolerance | Pass |
|---|---|---|---|---|---|---|---|
| Cantilever beam, end load | tip deflection | Timoshenko beam: F L^3/(3 E I) + F L/(kappa G A) | 0.19162 mm | 0.19161 mm | 0.01 % | 1.0 % | PASS |
|  | tip deflection (Euler-Bernoulli, no shear) | F L^3/(3 E I) | 0.19048 mm | 0.19161 mm | 0.59 % | 1.5 % | PASS |
|  | bending stress near mid-span, top fibre | M c / I at that node | 29.926 MPa | 29.924 MPa | 0.01 % | 2.0 % | PASS |
|  | hand estimate: stress at the fixed end | M c / I; the estimate measures the section on the mesh | 60 MPa | 60 MPa | 0.00 % | 0.5 % | PASS |
|  | hand estimate: deflection at the load | F L^3/(3 E I); the estimate measures the section on the mesh | 0.19048 mm | 0.19048 mm | 0.00 % | 0.5 % | PASS |
| Plate with a hole in tension | peak stress at the hole / applied stress (Kt, gross) | Howland/Heywood in Peterson, chart 4.1 (d/W = 0.2); Kirsch gives 3 for an infinite plate | 3.1488 | 3.1556 | 0.22 % | 3.0 % | PASS |
| Thick cylinder under internal pressure | peak von Mises stress (at the bore) | Lame, plane strain | 231.32 MPa | 231.53 MPa | 0.09 % | 2.0 % | PASS |
|  | radial displacement of the bore | Lame, plane strain | 0.018159 mm | 0.018158 mm | 0.00 % | 1.0 % | PASS |
| Cantilever under its own weight | tip deflection under gravity | w L^4/(8 E I) | 0.035192 mm | 0.035203 mm | 0.03 % | 1.0 % | PASS |
| Two bonded solids in series | elongation of two bonded solids | F L1/(E1 A) + F L2/(E2 A) | 0.0085714 mm | 0.0085714 mm | 0.00 % | 0.5 % | PASS |
|  | safety factor (the weaker solid governs) | yield / (F / A) | 24 | 24 | 0.00 % | 1.0 % | PASS |
| Block under a bolt preload | shortening under a bolt preload | N L/(E A) | 0.0029762 mm | 0.0029762 mm | 0.00 % | 0.5 % | PASS |
|  | stress under a bolt preload | N / A | 12.5 MPa | 12.5 MPa | 0.00 % | 1.0 % | PASS |
| NAFEMS LE1: elliptic membrane | stress yy at D (2, 0) | NAFEMS, The Standard NAFEMS Benchmarks (1990), test LE1: 92.7 MPa (plane stress) | 92.7 MPa | 92.518 MPa | 0.20 % | 2.0 % | PASS |
| NAFEMS LE10: thick plate under pressure | stress yy at D (2, 0, top) | NAFEMS, The Standard NAFEMS Benchmarks (1990), test LE10: -5.38 MPa | -5.38 MPa | -5.2714 MPa | 2.02 % | 3.0 % | PASS |
| Natural frequencies of a cantilever | mode 1: first bending, thin direction | Euler-Bernoulli, beta L = 1.8751 | 104.44 Hz | 104.88 Hz | 0.42 % | 2.0 % | PASS |
|  | mode 2: first bending, stiff direction | Euler-Bernoulli, beta L = 1.8751 | 208.88 Hz | 209.04 Hz | 0.08 % | 2.0 % | PASS |
|  | mode 3: second bending, thin direction | Euler-Bernoulli, beta L = 4.6941 | 654.51 Hz | 655.57 Hz | 0.16 % | 2.0 % | PASS |
| Natural frequencies of a free beam | free-free mode 1: bending, thin direction | Euler-Bernoulli, beta L = 4.7300 | 664.56 Hz | 663.28 Hz | 0.19 % | 2.0 % | PASS |
|  | free-free mode 2: bending, stiff direction | Euler-Bernoulli, beta L = 4.7300 | 1329.1 Hz | 1317.5 Hz | 0.88 % | 2.0 % | PASS |
| Euler buckling of a column | buckling load factor | Euler: pi^2 E I/(4 L^2) / P | 10.795 | 10.815 | 0.18 % | 2.0 % | PASS |
| Heat through a wall with convection | heat through the wall | q = (T1 - Ta) / (L / k + 1 / h), times the area | 38.4 W | 38.4 W | 0.00 % | 0.5 % | PASS |
|  | temperature of the convective face | Ta + q / h | 68 C | 68 C | 0.00 % | 0.5 % | PASS |
| Heat through a pipe wall | heat through the wall (a quarter) | 2 pi k L (Ti - To) / ln(ro / ri) | 169.96 W | 169.96 W | 0.00 % | 0.5 % | PASS |
|  | temperature at mid-wall (span minus the worst node error) | T(r) = Ti - (Ti - To) ln(r / ri) / ln(ro / ri) | 150 K | 149.99 K | 0.01 % | 0.5 % | PASS |
| Thermal stress in a bar that cannot expand | stress in a bar that cannot expand | E alpha dT | 201.6 MPa | 201.6 MPa | 0.00 % | 0.5 % | PASS |
|  | sideways growth of the free faces | (1 + nu) alpha dT a | 0.01248 mm | 0.01248 mm | 0.00 % | 0.5 % | PASS |
| Thermal stress in a thick cylinder | hoop stress at the bore (hot side, compression) | Timoshenko and Goodier, Theory of Elasticity, art. 151: long cylinder, steady radial heat flow | -330.47 MPa | -329.97 MPa | 0.15 % | 2.0 % | PASS |
|  | hoop stress at the outside (cold side, tension) | the same solution at r = ro | 209.53 MPa | 209.17 MPa | 0.17 % | 2.0 % | PASS |
| Sharp inside corner (singularity) | the sharp inside corner is named and its stress left out | Williams (1952): the stress at a re-entrant corner is unbounded | yes | yes |  |  | PASS |

| Case | Study | Refinements | Unknowns | Stated error | Converged | Time |
|---|---|---|---|---|---|---|
| Cantilever beam, end load | static | 3 | 4,380 | 0.5 % | yes | 0.25 s |
| Plate with a hole in tension | static | 4 | 43,461 | 0.7 % | yes | 2.7 s |
| Thick cylinder under internal pressure | static | 3 | 12,345 | 0.3 % | yes | 0.68 s |
| Cantilever under its own weight | static | 3 | 2,574 | 0.1 % | yes | 0.09 s |
| Two bonded solids in series | static | 3 | 3,996 | 0.1 % | yes | 0.16 s |
| Block under a bolt preload | static | 3 | 27,339 | 0.1 % | yes | 1.36 s |
| NAFEMS LE1: elliptic membrane | static | 4 | 27,453 | 0.6 % | yes | 1.35 s |
| NAFEMS LE10: thick plate under pressure | static | 4 | 70,632 | 1.9 % | yes | 5.01 s |
| Natural frequencies of a cantilever | modal | 3 | 3,474 | 0.2 % | yes | 0.16 s |
| Natural frequencies of a free beam | modal | 3 | 3,474 | 0.1 % | yes | 0.16 s |
| Euler buckling of a column | buckling | 3 | 5,541 | 0.5 % | yes | 0.22 s |
| Heat through a wall with convection | thermal | 3 | 15,379 | 0.1 % | yes | 1.23 s |
| Heat through a pipe wall | thermal | 3 | 3,489 | 0.1 % | yes | 0.18 s |
| Thermal stress in a bar that cannot expand | static | 3 | 5,418 | 0.1 % | yes | 0.25 s |
| Thermal stress in a thick cylinder | static | 4 | 32,976 | 0.3 % | yes | 1.89 s |
| Sharp inside corner (singularity) | static | 5 | 105,135 | 4.5 % | yes | 6.4 s |

30 quantities in 16 cases, all within tolerance; 22.09 s in total. Run on 2026-11-28 with Netgen 6.2.2608, scikit-fem 12.0.2, SciPy 1.18.1, PyAMG 5.4.1 and NumPy 2.5.5.
<!-- verification:end -->

The cases:

- **Cantilever beam.** 100 × 10 × 10 mm, 100 N at the free end, ν = 0. Deflection against Timoshenko's beam with
  shear (κ = 10(1 + ν)/(12 + 11ν)) and against Euler-Bernoulli; bending stress against M c / I. The hand estimate
  is checked here too: it must give the root stress and the tip deflection of beam theory.
- **Plate with a hole.** A 200 × 100 × 2 mm strip with a 20 mm hole in 100 MPa tension, one eighth by symmetry,
  solved to a stress tolerance of 2 %.
  Howland's solution for a finite width as fitted by Heywood (Peterson's Stress Concentration Factors, chart 4.1):
  Ktn = 2 + 0.284(1 − d/W) − 0.600(1 − d/W)² + 1.32(1 − d/W)³ on the net section. Kirsch's infinite plate gives 3.
- **Thick cylinder.** Inner radius 20 mm, outer 40 mm, 100 MPa inside, plane strain, a quarter by symmetry, solved
  to a stress tolerance of 2 %. Lamé's
  hoop, radial and axial stress at the bore, and the bore's radial displacement.
- **Self weight.** A cantilever under gravity, w L⁴ / (8 E I).
- **Two bonded solids.** Steel and aluminium end to end in tension: springs in series, and the weaker solid sets the
  safety factor.
- **Bolt preload.** A block clamped by a preload: N L / (E A) and N / A.
- **NAFEMS LE1, elliptic membrane.** The published benchmark (The Standard NAFEMS Benchmarks, 1990): a quarter of an
  elliptic plate 0.1 m thick with 10 MPa outward on its outer edge; the direct stress σyy at point D is 92.7 MPa.
- **NAFEMS LE10, thick plate.** The same outline 0.6 m thick, 1 MPa on the upper face, held along the mid-plane edge
  of its outer face; σyy at D on the top surface is −5.38 MPa. The support along an edge is a singular line: the
  study names it and leaves the stress within 300 mm of it out, and the benchmark point lies far from it.
- **Natural frequencies.** A clamped-free and a free-free steel beam against Euler-Bernoulli,
  f = (βL)² / (2π L²) · √(E I / ρ A) with βL = 1.8751, 4.6941 and 4.7300 (Blevins, table 8-1).
- **Euler column.** A clamped-free column, P = π² E I / (4 L²).
- **Heat through a wall.** A 20 mm wall held at 100 °C with convection on the other side: q = (T1 − Ta) / (L/k + 1/h)
  and the temperature of the convective face.
- **Heat through a pipe wall.** Radial conduction, Q = 2π k L (Ti − To) / ln(ro/ri), and the logarithmic temperature
  profile at mid-wall.
- **Thermal stress in a held bar.** A bar that cannot grow along its length, heated by 80 K: σ = E α ΔT, and the
  sideways growth (1 + ν) α ΔT.
- **Thermal stress in a thick cylinder.** 200 °C inside and 50 °C outside, plane strain: the hoop stress at the bore
  and at the outside (Timoshenko and Goodier, Theory of Elasticity, art. 151).
- **Sharp inside corner.** An L-bracket without a fillet: the study must name the corner, show its stress growing with
  refinement, and report a peak that leaves it out.

Run it yourself:

```bash
form strength verify            # JSON: every case, expected, got, error, tolerance, pass
form strength verify cantilever plate_with_hole
```

## Timings

A typical bracket, solved to convergence: an aluminium L-bracket 80 × 40 × 60 mm, 6 mm thick, with a 6 mm fillet and
three 6 mm holes, fixed at the two base holes and loaded at the hole of the upright.

<!-- timings:begin -->
| Study | Time | Unknowns | Tetrahedra | Refinements | Evidence | Result |
|---|---|---|---|---|---|---|
| static | 8.5 s | 106,110 | 22,470 | 3 | simulated (FEA, linear static, converged to 1.8 %) | peak von Mises 50.4 MPa, safety factor 5.48 |
| modal | 8.6 s | 71,583 | 13,103 | 3 | simulated (FEA, modal, converged to 0.5 %) | first frequencies 925, 1357, 3154 Hz |
| buckling | 9.7 s | 71,583 | 13,103 | 3 | simulated (FEA, linear buckling, converged to 0.4 %) | load factor 151.6 |

Machine: arm64, Darwin 27.3.0, 18 cores. The time is the whole study in the engine: every mesh, every solve, the stress recovery and the field data.
<!-- timings:end -->

A study runs in the background. It reports its progress (meshing, solving refinement n with its unknowns) and can be
cancelled at any time; a cancelled run stores nothing. A study stops refining when the next level would pass its time
budget (90 s by default) or its limit of unknowns (600,000 for a static study, 160,000 for modal and buckling), and
then says that it stopped before converging.

## Tools and commands

Two MCP tools, and the same from the terminal with JSON output.

| MCP tool | Command | Does |
|---|---|---|
| `strength_study` | `form strength static\|modal\|buckling\|thermal\|thermal_stress <project> ...` | Defines a study and runs it. With no definition: the design's studies and their states |
| `strength_study(study=...)` | `form strength run <project> <study>` | Runs a saved study again |
| `get_strength_study` | `form strength show <project> <study>` | State, progress, the result, the field file; `cancel=True` stops a running study |
| | `form strength list <project>` | The design's studies with their states |
| | `form strength verify` | The verification suite |

`form study strength ...`, `form study static ...`, `form study modal ...`, `form study buckling ...` and
`form study thermal ...` are the same commands.

```bash
form strength static bracket --fix 33,20,3 --fix 65,20,3 --force 3,20,45:300,0,-200 --material AL-6061
form strength modal bracket --fix 33,20,3 --modes 4 --material AL-6061
form strength thermal heatsink --temperature 0,0,0:80 --convection 20,5,30:15:25 \
     --material '{"k_W_mK": 167, "source": "6061-T6 datasheet"}'
form strength buckling column --fix 5,5,0 --force 5,5,200:0,0,-1000 \
     --material '{"E_GPa": 210, "poisson": 0.3, "yield_MPa": 355, "density_kg_m3": 7850, "source": "EN 10025-2"}'
```

```json
{"project": "bracket", "kind": "static", "material": "AL-6061",
 "fixtures": [{"type": "fixed", "faces": [[33, 20, 3], [65, 20, 3]]}],
 "loads": [{"type": "force", "faces": [[3, 20, 45]], "vector": [300, 0, -200]}]}
```

The command exits 0 with a converged result, 3 when the study ran and did not converge, and 1 on an error.

What a result holds: `headline`, `evidence`, `how_known`, `converged` (and `not_converged_because`),
`safety_factor` (`value`, `low`, `against`, `strength_source`, `at`), `peak_von_mises_MPa` and `peak_at`,
`max_displacement_mm`, `discretisation_error`, `singularities`, `equilibrium`, `convergence.levels`, `mesh`,
`materials` (every number with its source), `assumptions`, `faces` (what each picked point landed on),
`hand_estimate`, and for the other kinds `frequencies_Hz`, `modes`, `load_factor` and `meaning`, or `t_min_C`,
`t_max_C`, `heat_through_W`, `conditions` and `heat_balance`.

## Stored results and staleness

A study's definition is kept in the project file. Its result is stored beside the revision under a key made of:

- the geometry key of the revision (the design's code, the kernel and the parameter values),
- the definition (kind, supports, loads, mesh options),
- the numbers of every material used,
- the engine and the versions of its libraries.

A result is current only when it exists under the key of the head revision. After a change to the geometry, the
loads, a material's sourced value or the engine, the stored result is stale: it is still shown, marked with the
revision it describes, and its field is no longer drawn. Nothing marks a result current by hand.

## Field data

For the viewport: the outside surface of the finest mesh with per-vertex results. `get_strength_study` returns
`field_file`, a JSON file beside the result (`<project>/artifacts/studies/strength.<study>/<key>.field.json`).

```json
{"format": "form.fea.field/1", "version": 1, "study": "s1a2b3c", "rev": 4, "kind": "static", "frame": "as built",
 "evidence": "simulated (FEA, linear static, converged to 1.1 %)",
 "units": {"length": "mm", "stress": "MPa", "frequency": "Hz"},
 "vertices": 5195, "triangles": 10398,
 "positions": "<base64: float32 little-endian, 3 per vertex>",
 "indices":   "<base64: uint32 little-endian, 3 per triangle, outward winding>",
 "face":      "<base64: uint32, one per triangle: the B-rep face it lies on>",
 "fields": {
   "displacement":  {"type": "f4", "components": 3, "data": "<base64>"},
   "von_mises":     {"type": "f4", "components": 1, "data": "<base64>"},
   "safety_factor": {"type": "f4", "components": 1, "data": "<base64>"},
   "singular":      {"type": "u1", "components": 1, "data": "<base64>"}},
 "ranges": {"von_mises": [0.02, 124.0], "safety_factor": [2.2, 13800.0], "displacement": [-0.31, 0.21]}}
```

- `displacement`: mm, per vertex. Add a multiple of it to `positions` for the deformed shape.
- `von_mises`: MPa, the smoothed nodal stress.
- `safety_factor`: strength over von Mises stress at that vertex; absent when no strength is sourced.
- `singular`: 1 where the vertex lies in a singular zone that was left out of the verdict. Draw these differently:
  their stress is not a result.
- A heat study has `temperature` (°C) and `heat_flux` (W/m²); a thermal stress study adds `temperature` to the
  static fields.
- A modal or buckling study has `modes` instead: `count` shapes of 3 components per vertex, each scaled so its largest
  component is 1, with `mode_frequencies_Hz` or `mode_load_factors`.
- `frame` is `as built` for one solid and `assembled` for a design of several parts.

About 90 bytes per vertex; a bracket's field is 0.2 to 0.5 MB.

## The engine and its licences

The solver libraries are an optional engine with a Python of its own, installed from Settings, Engines & software
with one click (about 190 MB, measured on macOS arm64). Form Studio itself stays importable and MIT without them; the solver runs out of
process.

| Library | Version | Role | Licence |
|---|---|---|---|
| Netgen (`netgen-mesher`) | 6.2.2608 | Tetrahedral mesh from the B-rep | LGPL-2.1 |
| `netgen-occt` | 7.8.1 | The Open CASCADE build Netgen reads STEP with | LGPL-2.1 with the Open CASCADE exception |
| scikit-fem | 12.0.2 | Shape functions of the quadratic tetrahedron | BSD-3-Clause |
| SciPy | 1.18.1 | Sparse matrices, SuperLU, ARPACK | BSD-3-Clause |
| PyAMG | 5.4.1 | Algebraic multigrid preconditioner | MIT |
| NumPy | 2.5.5 | Arrays | BSD-3-Clause |

The LGPL libraries are used as unmodified wheels in a separate environment. Gmsh and CalculiX (both GPL) are not used.

How it solves: the elements are isoparametric (scikit-fem's quadratic tetrahedron on a quadratic mesh), integrated
with a 14-point rule; element matrices are assembled from the shape-function gradients; one load case is solved by conjugate
gradients preconditioned with smoothed-aggregation multigrid, using the six rigid-body modes as its near-null space
(a sparse direct factorisation below 15,000 unknowns); frequencies and buckling factors come from shift-invert
Lanczos on a factorisation made once.

## The Bench entry

`form/fea/bench.py` registers one entry, **Strength**, for the Bench: current only when every study of the design is
current for the head revision, stale when any is, with the lowest safety factor as its headline and a run action
that solves every study that is not current. It plugs into the Bench's hook for later waves, a module listed in
`studies.PROVIDERS` that exposes `register_studies(register)`.
