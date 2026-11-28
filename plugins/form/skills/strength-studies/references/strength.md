# Strength studies: defining one, and reading it

A study answers one question about one load case: with the part held here and loaded there, in this material, what
are the stress and the displacement, and how sure is the number. This page is how to set one up and how to read what
comes back. The method and its verification against textbook cases are in docs/STRENGTH.md.

## Defining a study

```json
{"project": "bracket", "kind": "static", "material": "AL-6061",
 "fixtures": [{"type": "fixed", "faces": [[33, 20, 3], [65, 20, 3]]}],
 "loads": [{"type": "force", "faces": [[3, 20, 45]], "vector": [300, 0, -200]}]}
```

**Faces.** Every support and load names faces by a point on each, in design millimetres on the part as printed.
`analyze_selection` with `{"kind": "face", "at": [x, y, z]}` tells you what a point lands on (face type, area,
feature). A point more than 1 mm off the surface is refused. For a design of several parts, pick on each part as
printed; the study assembles them.

**Supports.**

| Type | Use it for | Holds |
|---|---|---|
| `fixed` | A face clamped, welded or glued to something rigid | Everything |
| `pin` | A hole on a shaft, a bolt that may turn | Across and along the axis; free to turn |
| `roller` | A face resting on a surface; a symmetry plane | Across the face; free to slide in it |
| `hold` | One direction at a time: `"directions": [[0, 0, 1]]` | Those directions |

The supports together must remove all six rigid motions. Three rollers on faces that meet at a corner do; one
roller does not. A `fixed` face is perfectly rigid, which no real support is: its edge often shows up as a
singularity (below).

**Loads.**

| Type | Unit | Notes |
|---|---|---|
| `force` | N | `vector`, or `magnitude` and `direction`; spread evenly over the faces. 1 kg hanging is 9.81 N |
| `pressure` | MPa | Pushes on the face. 1 bar = 0.1 MPa |
| `preload` | N | A bolt's clamping force between `faces` (under the head) and `faces_b` (under the nut) |
| `gravity` | g | The part's own weight; needs the density |

Loads act on faces. A force on a very small face behaves like a point load and is reported as a singularity.

**Material.** A key of the materials library, or values with their source. What each kind needs:

| Kind | Needs | For a safety factor |
|---|---|---|
| `static`, `buckling` | E, Poisson's ratio | yield strength |
| `modal` | E, Poisson's ratio, density | |
| `thermal` | thermal conductivity `k_W_mK` | |
| `thermal_stress` | E, Poisson's ratio, `k_W_mK`, `cte_per_K` | yield strength |

Nothing is defaulted. A printed filament is solved as a solid, isotropic part with its in-plane modulus and judged
against its weakest sourced strength; the result names that and the datasheet's Z / X-Y ratio. Layers and infill are
not in the model: say so whenever you report a printed part's safety factor.

**Thermal conditions** (`thermal`, `thermal_stress`): `temperature` (value_C), `convection` (h_W_m2K, ambient_C),
`heat` (value_W), `heat_flux` (value_W_m2). A face with none is insulated. At least one temperature or convection
must set the level. `reference_C` is the temperature at which the part is free of stress (20 by default). Free air
is roughly 5 to 25 W/(m² K), forced air 25 to 250: these are ranges, so a convection coefficient you choose is
assumed, and should be said to be.

## Reading a result

| Field | Meaning |
|---|---|
| `evidence` | The evidence class to quote: `simulated (FEA, linear static, converged to 1.8 %)` or `... not converged` |
| `converged` | False: the tolerance was not reached. `not_converged_because` says why. No safety factor is given |
| `safety_factor` | `value`, and `low` with the stated error applied; `against` and `strength_source` say what strength |
| `peak_von_mises_MPa`, `peak_at` | The peak outside the singular zones, and where |
| `max_displacement_mm` | The largest displacement |
| `discretisation_error` | The stated error of stress and displacement: an estimate with a margin, not a bound |
| `singularities` | Places left out of the verdict, with where, why and the stress there at every refinement |
| `hand_estimate` | Beam theory beside the result where the part is a bar fixed at one end; otherwise why not |
| `equilibrium` | Reactions against loads; `balanced` must be true |
| `convergence.levels` | Every refinement: unknowns, displacement, peak stress |
| `materials` | Every number used, with its source |
| `assumptions` | What the model takes for granted |

### Convergence

The solid is meshed and solved at least three times, each mesh finer where the last one was least accurate. The
stated error is twice the change the last refinements show. A converged static study is within 5 % on stress and
1 % on displacement by default (`mesh.tol_stress`, `mesh.tol_disp`).

Not converged is a result, not a failure to hide. Report it as "the study did not converge: ..." and offer what
would help: a longer budget (`mesh.budget_s`), a fillet where the stress is growing, a simpler load case.

### Singularities

At a sharp inside corner the elastic stress is unbounded: every finer mesh gives a higher number, and none of them
means anything. The study finds these edges, lists them, and leaves the stress within `left_out_within_mm` of them
out of the peak and the safety factor. The same is done at the edge of a fixed face or of a loaded face when the
stress there keeps growing.

What to do with one:

- **Never quote it.** `stress_there_MPa_by_refinement` is shown so the growth is visible, not as the part's stress.
- **A sharp inside corner in the load path is a design finding.** Real parts crack there. Propose a fillet, add it
  with `edit_design`, and run the study again: with a radius the stress converges and counts.
- **A fixture edge** is the model's rigid support, not the part. Say that the stress at the support edge was left
  out, and why.

### The hand estimate

For a prismatic bar fixed at one end, `hand_estimate` gives the bending stress at the fixed end and the deflection at
the load from beam theory, on section properties measured from the solid. It is computed, not simulated, and shares
nothing with the solver. Agreement within a few percent is a good sign. A simulated peak well above it points to a
stress concentration (a hole, a notch); one far below it means the loads or supports are probably not what was
meant.

## Staleness

A result belongs to the revision, the loads, the material's numbers and the engine it was computed with. After a
commit it is stale: `get_strength_study` still returns it, marked with the revision it describes. Do not repeat a
stale number as the design's strength; run the study again (`strength_study(project, study="<id>")`).

## Strength as a constraint

```json
{"project": "bracket", "vary": [{"key": "t", "min": 3, "max": 10}], "objective": {"minimize": "solid_mass_g"},
 "constraints": ["fea.safety_factor >= 2"]}
```

`optimize` searches on what the kernel computes for every candidate, then solves the design's static study on real
candidates, best first, within 8 solves and 300 s. `strength.solved` lists each one with its numbers and evidence.
Only those are checked: a candidate that was not solved is never called feasible, and the search was not steered by
the strength constraint, so say "the best of the N candidates that were solved". `fea.safety_factor` is the lower
value. `make_lighter(require=[...])` solves each lighter geometry it would offer and rejects the ones that fail.

## What a study cannot tell you

Fatigue under repeated load, impact, creep (plastics under constant load, more when warm), yielding and what happens
after it, layer adhesion and infill of a printed part, a bolted joint that opens or slips, parts that slide on each
other. When the question is one of these, say that the linear study does not answer it.
