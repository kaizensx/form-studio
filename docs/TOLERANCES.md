# Tolerance stack-up

Pick a gap or a clearance between two faces of an assembly. Form Studio finds the loop of dimensions that sets that
gap, through the mates and each part's own dimensions. Then it says how far the gap can move:

- worst case, RSS and Monte Carlo;
- Cpk and the share out of spec;
- the share of the spread each tolerance causes;
- the gap over a temperature span;
- which tolerance to tighten first.

- [Three ways in](#three-ways-in)
- [Picking the gap](#picking-the-gap)
- [How the loop is found](#how-the-loop-is-found)
- [Sensitivities](#sensitivities)
- [Where each tolerance comes from](#where-each-tolerance-comes-from)
- [GD&T in the stack](#gdt-in-the-stack)
- [The methods](#the-methods)
- [Temperature](#temperature)
- [What to tighten](#what-to-tighten)
- [What the result holds](#what-the-result-holds)
- [Verification](#verification)
- [What is not covered](#what-is-not-covered)

## Three ways in

| Where | How |
|---|---|
| MCP | `tolerance_stack(project, a, b, ...)` computes a stack and saves nothing. `save=True` keeps it with the design. `stack=` alone runs a kept stack for the head revision. `get_tolerance_stack(project[, stack])` lists the kept stacks with their state, or reads one result |
| Terminal | `form stack run <project> --a X,Y,Z[@part] --b X,Y,Z[@part] [--dir X,Y,Z] [--tol KEY=T] [--spec LO,HI] [--temps TMIN,TMAX]`. Also `form stack add` (keep it), `list`, `show <id>`, `rerun <id>` and `rm <id>`. JSON on standard output; `--brief` gives the headline, the chart and the suggestions |
| The Bench | The entry **Tolerance stack-up** (`stack`) among the Check studies. It is current when every kept stack is current for the head revision, and stale after any change to the geometry, a tolerance source, a material or a definition. Its headline is the stack with the lowest Cpk. Running it computes every stack that is not current. Also `form study show <project> stack` and `get_study` |

## Picking the gap

Each face of the gap is picked in one of three ways:

- `{"at": [x, y, z]}`: a point on the face, as built. This is the frame `analyze_selection` and the viewport's picks
  use.
- Add `"part"` to that pick to name the part, or `"frame": "assembled"` for a point picked in the assembled view.
- `{"face": i}`: a model face index.

The gap is measured along a direction n. By default n is face A's outward normal, because a face that bounds a gap
faces into it. Pass `direction=` for any other direction, and always when face A is not planar.

The gap is `level(B) − level(A)`. A face's level is its extreme along n on the side that faces the gap. On a plane
square to n this is exact. On any other face it is OCCT's optimal bounding box in a frame whose Z is n.

## How the loop is found

The parts are the nodes of a graph. A declared `Mate(a, b, ...)` is an edge **along n** only when the two parts have
an interface that holds them along n. Two kinds count:

| Interface | What it is | In the stack |
|---|---|---|
| **Seat** | Two planar faces with opposite normals along n, within 0.02 mm of each other: a lid on a rim, a screw head on a lid | No float: the parts are pressed together there |
| **Radial fit** | Two coaxial cylinders whose axis is square to n: a pin in its hole | A float of ± the radial clearance per side, uniform, because where the pin sits in the hole is not known. A declared `Mate(clearance=)` is used instead of the measured radii when given |

A thread or a pin along n holds nothing along n, so it is not an edge. The result lists every mate with the reason
it is or is not an edge. Two parts joined by no declared mate can still be joined by a seat found on the model. Such
an edge is labelled `found` and costs more, so a declared mate is always preferred.

The loop is the cheapest path from A's part to B's part (Dijkstra). In each part on the path, the **link** is the
distance along n between the face the loop enters by and the face it leaves by. Between parts, the **interface term**
is the seat's gap or the fit's offset. The links and the terms telescope to the gap. The result reports this as
`closure`, which is zero to rounding when the faces were picked well.

A gap between two faces of one part is a loop of one link.

## Sensitivities

Each length (mm) and angle (degrees) parameter of the design is nudged both ways by 0.01 and the design is rebuilt by
the kernel. A parameter at the end of its range is nudged one way only, and the result says so.

Every face of the loop is found again by:

- its part;
- the feature that made it;
- its kind (plane or cylinder);
- its normal or axis;
- the face nearest to where it was in its part.

The derivative is `d link / d parameter` for each part. A parameter that sizes two parts gives two contributors,
because each part is made on its own. A parameter that only places a part, such as the box height that sets where the
lid sits, moves no link and is listed in `not_moving`.

Angles need nothing special, because the derivative is taken on the real rebuild. A ramp's gap changes by
`−W sec²θ · π/180` mm per degree, and the finite difference finds the same number (see [Verification](#verification)).

## Where each tolerance comes from

The first rule that applies is used:

| # | Source | Range | Distribution | Evidence |
|---|---|---|---|---|
| 1 | `tolerances=` in the request: `{param: ±t}`, `{param: [lower, upper]}`, or `"part:param"` for one part | as given | normal | specified |
| 2 | An ISO 286 class the drawing states for that size (`fits` with `at: {"param": key}`, or a cylinder of the parameter's feature) | the class's limits, asymmetric where the class is (g6 is −6 to −17 µm at 12 mm) | normal | specified (ISO 286-1/-2) |
| 3 | The parameter's provenance, when it carries a sigma (a measured or specified value) | ±3σ | normal | its provenance (measured, calibrated, specified) |
| 4 | The drawing's stated ISO 2768 class (`general`) | ISO 2768-1 for the size; angles use the shortest-side band, because the side length is not known here | normal | specified (ISO 2768-1) |
| 5 | A printed design: the printer's calibration, when it has three or more measured widths | ±3σ of the measured spread | normal | calibrated |
| 6 | A printed design without one | FDM ±0.2 mm, ±0.5° | uniform | **assumed**. A fit coupon measures the real value |
| 7 | Anything else | ISO 2768-m | uniform | **assumed**: the drawing states no class |

`dist={id: "normal" | "uniform"}` overrides the distribution of any contributor. A normal reads the tolerance as
±3σ. An assumed tolerance is uniform over its range, because nothing is known about where in the range the part
falls.

## GD&T in the stack

Only position and profile tolerances move where a face is, so only those are converted. They must be declared on the
drawing (`drawing(v)` in the design, or `set_spec`) on a face of the loop: `at` names the feature, and optionally the
normal or `cylinder`.

The rule: a zone of total width t lets the face sit ±t/2. For a plane this is along its normal. For a cylinder with a
Ø zone it is square to its axis. The effect on the gap is that ±t/2 times how much of n lies along it: `|normal · n|`
for a plane, `√(1 − (axis · n)²)` for a cylinder. The contributor is normal at ±3σ = t/2.

Datum shifts and the bonus tolerance of Ⓜ or Ⓛ are not credited. Flatness, orientation and runout tolerances are
listed with the reason they are not converted.

## The methods

x_i is each contributor's deviation, within [lower, upper]. s_i is its sensitivity, t_i its half range and m_i its
centre. The gap is

```
gap = gap_nominal + Σ s_i · x_i
```

| Method | Result | Assumes |
|---|---|---|
| Worst case | `mean ± Σ |s_i| t_i`, mean = nominal + Σ s_i m_i | every contributor at its limit at once, in the direction that moves the gap the same way |
| RSS | σ = √Σ (s_i σ_i)², σ_i = t_i/3 (normal) or t_i/√3 (uniform); limits mean ± 3σ | independent contributors; reading ±3σ as 99.73 % assumes the sum is close to normal |
| Monte Carlo | every contributor sampled from its own distribution (default 200 000 samples, seed 1, so a run repeats exactly), the same linear model; mean, σ, the 0.135 % and 99.865 % quantiles, a histogram, the share out of spec with its standard error | the linear model |

Capability uses the gap's specification `spec=[LSL, USL]`, where either limit may be open. Without it the lower limit
is 0, labelled assumed (a gap must not close), unless the nominal gap is already an interference.

```
Cpk = min(USL − mean, mean − LSL) / 3σ
```

The share out of spec comes both from the normal with the RSS mean and σ, and counted in the Monte Carlo samples.

## Temperature

With `t_min` and `t_max` (°C), every part's link grows by its own expansion:

```
gap(T) = gap(20 °C) + (T − 20) · Σ αᵢ dᵢ
```

Here dᵢ is each part's signed link along the gap. αᵢ is the sourced coefficient of the part's material from the
materials library (`form materials`), with its document. The material comes from the part, then the design's code,
then the design. A part with no sourced coefficient, such as most printing filaments, leaves the thermal result out.
The result says which part lacks one and what to give: `alpha={part: 1/K}`, taken from the material's datasheet. It is
never assumed.

The result gives the gap at both temperatures, the worst case and RSS limits shifted, the worst-case range over the
whole span, and the change per kelvin.

The model holds each part at one uniform temperature, free to grow, with a constant α. The growth of the tolerance
zones themselves (α · t · ΔT) is left out.

## What to tighten

For every contributor that causes 1 % or more of the variance, or 5 % or more of the worst-case range, the result
computes what happens if its tolerance is halved: the new σ, the new worst case and the new Cpk. Suggestions are
ranked by how much σ shrinks. These numbers are computed.

Each suggestion carries a cost hint by the kind of tolerance. Every hint is labelled **assumed**: it is a rule of
thumb, not a quote.

| Tolerance from | Hint |
|---|---|
| ISO 286 | one IT grade finer usually means a finer process (reaming, fine boring, grinding) |
| ISO 2768 | a finer class is the same process with more care, or the size toleranced on its own |
| FDM, assumed | calibrate the printer (fit coupon) before buying precision |
| Printer calibration | a better printer or finer printing, or ream or machine the size after printing |
| Provenance | measure the bought part better, or buy a tighter grade |
| A fit's float | a tighter fit class, or a locating feature that removes the float |
| GD&T | a smaller zone, which costs inspection as well as making |

When the worst case crosses a limit, or the mean is off the middle of a two-sided spec, the parameter that moves the
gap most (summed over the parts it sizes) is named with the change that fixes it. That change is computed. Its cost
hint, a design change, is assumed.

## What the result holds

| Key | What |
|---|---|
| `gap` | nominal, direction (and where it came from), closure, the two faces |
| `loop` | `chain` of parts; `links` (part, signed length, entry and exit faces); `interfaces` (seat or fit, offset, float, the mate); `mates` (each declared mate and why it is or is not on the loop) |
| `contributors` | id (`part:param`, `float:a/b`, `gdt:n`), label, sensitivity, lower, upper, dist, evidence, source, rule |
| `worst_case`, `rss`, `monte_carlo`, `capability` | as above, each with what it assumes |
| `contributions`, `chart` | share of variance and of the worst-case range per contributor; `chart` is the contribution chart in percent, largest first |
| `thermal` | per temperature: shift, nominal, worst case and RSS limits; the span; α per part with its source; `not_computed` when an α is missing |
| `suggestions` | what to tighten, with the effect computed and the cost assumed |
| `draw` | the loop for the viewport (see below) |
| `not_moving`, `skipped`, `gdt`, `caveats` | parameters that move no link, parameters not differentiated and why, GD&T not converted and why, what the result does not cover |

`draw` is what the viewport needs to light the loop on the parts:

- `faces`: each face's model face index, its part, its role (`gap_a`, `gap_b`, `interface`), its feature, its centre
  (assembled and as built) and its normal, or its axis and radius.
- `segments`: one per link, one per interface and one for the gap. Each runs from one level to the next along the
  direction, on a line through face A's centre, in the assembled frame at rest, with its length.

## Verification

`tests/test_stack.py` checks each of these:

| Case | Against | Tolerance |
|---|---|---|
| A 1D linear stack of five contributors (one asymmetric like a g6 shaft, one uniform) | hand worst case, RSS and variance shares | 1e-12 |
| Cpk and share out of spec | hand values from the normal distribution | 1e-12 |
| Monte Carlo, 400 000 samples, four normal contributors | the analytic mean, σ and share out of spec | 4 standard errors; repeats exactly with the same seed |
| Box, lid and screw: the gap from the screw's tip to the floor of its pilot hole | the loop found on its own (screw, lid, box through two seats; the thread mate along the gap is not an edge), closure 0, sensitivities −1, +1, +1, box height not moving, worst case 3 ± 0.45 | 1e-6 |
| The same with the drawing's js11 fit on the screw, ISO 2768-f stated and a profile tolerance on the hole floor | ISO 286 (±55 µm), ISO 2768-f bands, the profile converted to ±0.1 | exact |
| Temperature: aluminium box and lid, stainless screw, −20 to 80 °C | the hand calculation `ΔT (12 α_Al + 3 α_Al − 12 α_SS)` with the library's sourced α | 1e-12 mm |
| A lid made of PLA (no sourced α) | thermal result left out, with what to give | — |
| A ramp at 10° under a cover | `d gap / dθ = −W sec²θ · π/180` mm/°, `d gap / dW = −tan θ` by finite differences on the rebuild | 1e-6 |
| A pin in a hole with a wall across the gap | a radial fit with a float of 0.1 mm, uniform; the bore's size moves the float, not the axis | 1e-6 |
| A kept stack | the Bench entry current, stale after a commit, current again after a run | — |

## What is not covered

- **Linear only.** The gap is linearised at the nominal design. Large tolerances on angles bend the line. The Monte
  Carlo uses the same linear model, not a rebuild per sample.
- **Floats** use the nominal radii. The radii's own tolerances widen a fit's float, and that is not added.
- **One direction.** The loop is one-dimensional along n. A 2D or 3D vector loop (Chase and Greenwood) with rotations
  between parts is not modelled, beyond what each part's own geometry gives through its sensitivities.
- **Seats are rigid.** A seated pair is taken as pressed together. Flatness of the seat, deformation under a screw's
  preload and settling are not in the stack.
- **GD&T** converts position and profile only, without datum shift or bonus tolerance.
- **Cost hints** are rules of thumb, always labelled assumed.
