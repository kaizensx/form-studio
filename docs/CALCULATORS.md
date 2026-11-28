# Engineering calculators

A calculator sizes a part from what it has to do, with the equations of a named standard or design guide, and writes
the part as a design with parameters. Seven of them: snap joints, living hinges, springs, bolted joints, gears, cams
and fits at temperature.

Every number on a result carries one of three words:

| Evidence | Meaning |
|---|---|
| `computed` | From the equation named, with the other numbers of the sheet |
| `specified` | Given in the request, or published: a standard's table, a design guide, a material's datasheet |
| `assumed` | A default Form Studio chose because nothing was given and nothing sourced exists; the row says why |

Nothing is made up. A material value comes from the sourced library (`form materials`) or from the request. When
neither has it, the number that needs it is left out, and the sheet's `not_computed` says what to give. A guide's
value keeps the guide's name and its condition, and a printed part gets the caveat that goes with it.

- [Three ways in](#three-ways-in)
- [What a sheet holds](#what-a-sheet-holds)
- [The calculation stays with the design](#the-calculation-stays-with-the-design)
- [Snap joints](#snap-joints)
- [Living hinges](#living-hinges)
- [Springs](#springs)
- [Bolted joints and insert bosses](#bolted-joints-and-insert-bosses)
- [Gears](#gears)
- [Cams](#cams)
- [Fits at temperature](#fits-at-temperature)
- [Verification](#verification)
- [The solids, measured](#the-solids-measured)
- [By finite elements](#by-finite-elements)
- [What is not covered](#what-is-not-covered)

## Three ways in

| Where | How |
|---|---|
| MCP | `calculate(calculator, inputs)` returns a sheet and saves nothing. `build=True` writes the design. `project=` with `at=` and `normal=` puts a snap hook or an insert boss on a face of an existing design. `project=` alone re-reads the sheet of a design a calculator wrote. No arguments: the calculators with every input |
| Terminal | `form calc <calculator> key=value ... [--build] [--name N]`, `form calc list`, `form calc show <project>`, `form calc verify [--geometry]`. JSON on standard output |
| The Bench | The entry **Engineering calculation** (`calc`) among a design's studies: the calculation run again on the head revision's values, with its headline and the standard it follows. `form study show <project> calc`, `get_study` |

```
form calc snapfit material=PETG length=15 width=6 undercut=1 mu=0.3
form calc spring wire_d=1.6 mean_d=14 active=6 force=40 wire=music --build
form calc fastener axial=2000 shear=1500 mu_interface=0.15 plate_material=AL-6061 into=tapped
form calc gear module=2 z1=14 z2=30 x1=0.3 torque=800 material=POM
form calc cam lift=8 rise=120 dwell=60 fall=120 roller_radius=4
form calc fit fit=H7/g6 diameter=25 hole_material=AL-6061 shaft_material=STAINLESS t_min=-20 t_max=80
```

Units are millimetres, newtons, newton-millimetres, degrees, megapascals and degrees Celsius. An input the calculator
does not know is refused, so a typo is never ignored.

## What a sheet holds

| Field | Content |
|---|---|
| `headline`, `status` | One line, and `PASS`, `WARN` or `FAIL` (the worst check) |
| `values` | Every number: `key`, `label`, `value`, `unit`, `evidence`, the `equation` it is from, its `source`, a `note` |
| `checks` | `PASS`, `WARN`, `FAIL` or `INFO`, with the value, the reason and the equation that decided it |
| `equations` | Every equation used, as text, with the source it is from |
| `sources` | Every source: title, URL where there is one, the condition or the quoted line |
| `caveats` | What the result does not cover |
| `not_computed` | What was left out because an input has no source, and what to give |
| `geometry` | The design it writes: its kind and values |

## The calculation stays with the design

A design a calculator writes is ordinary design code: a `FeatureDesign` with one parameter per dimension the
calculator sized and one feature per solid step. The calculation itself (the calculator and its inputs) is in the
source as `CALC`, so it is in every revision and travels with the design.

Every build runs the calculation again on the revision's values. Drag a snap hook shorter and the next revision's
derived dimensions show the new strain, with `FAIL: Strain when it snaps` beside it when it is over the limit; the
Bench entry says the same. Dimensions that follow from others (a gear pair's centre distance and tooth depth) are
recomputed by the calculator before the solids are built, so a pair with more teeth still meshes.

## Snap joints

`snapfit`. Source: Bayer MaterialScience, *Snap-Fit Joints for Plastics: A Design Guide*.

| | |
|---|---|
| Deflection (rectangular arm) | `y = K · ε · l² / h`, K = 0.67 constant section, 1.09 thickness tapering to one-half, 0.86 width tapering to one-quarter (Table 1, shape A) |
| Deflection force | `P = (b · h² / 6) · E_s · ε / l` |
| Mating and separation force | `W = P · (μ + tan α) / (1 − μ · tan α)`, the return angle for separation; a face with `μ · tan α ≥ 1` locks |
| Annular joint | `ε = y / d`, `P = y · d · E_s · X`, with the guide's geometric factors X_N (elastic hub) and X_W (elastic hollow shaft); about three times the force when the bead is remote from the tube's end |

**Permissible strain**, in this order: the request's `allow_strain`; the guide's Table 2 value for a moulded resin
(`guide_resin`: PC 4 %, PC/ABS 2.5 %, PC blend 3.5 %, PC with 10 or 20 % glass 2.2 and 2.0 %); else from the
material's sourced datasheet, the smaller of half the elongation at break (the guide's rule for a material with no
distinct yield point) and strength over modulus. The second bound is Form Studio's own and is labelled so. For
frequent joining the guide takes 60 %.

**Forces** use the request's `E` (a secant modulus) or the datasheet's tensile modulus; with the latter the sheet says
the forces are an upper estimate. **Friction** is the request's `mu`, or the guide's Table 3 mid-range where it has
the material (ABS, PA, PC, POM, PMMA, PTFE). For PLA, PETG, ASA and TPU the guide has no value: the mating force is
left out and the sheet asks for `mu`.

Writes a hook on a pad (three arm designs), or a beaded tube and its grooved hub. A hook can go onto a face of
another design.

## Living hinges

`hinge`. Two modes, and the sheet says which.

| Mode | For | Basis |
|---|---|---|
| `elastic` | Printed parts, any material | Pure bending of a strip onto an arc: `R = L / θ`, `ε = t / (2R) = t · θ / (2L)`; the strain kept under the permissible strain above (60 % of it by default: a hinge folds often). Holding moment `M = E · (w t³ / 12) · θ / L` |
| `moulded` | Injection-moulded polypropylene or polyethylene | Moulders' dimensions from cited guides: web 0.20 to 0.38 mm (0.25 to 0.30 mm baseline for a 180° fold), land about 1.5 mm, bottom relief radius 0.75 mm |

A moulded PP hinge is not an elastic design: 0.3 mm folded flat over 1.5 mm is about 31 % nominal strain. It lasts
because the resin orients across the hinge. The sheet reports that strain as `INFO` so nobody mistakes the moulded
dimensions for something a printed web survives, and computes no fatigue life.

Sources: Protolabs, *Designing Living Hinges that Fold Flat*; Plastics Technology Alliance, *Injection Molding Living
Hinge Design*; RJC Mold, *Living Hinge Design Guide*.

## Springs

`spring`, `kind` = `compression` (EN 13906-1), `extension` (EN 13906-2) or `torsion` (EN 13906-3).

| | |
|---|---|
| Rate | `R = G · d⁴ / (8 · D³ · n)`; torsion `M / α = E · d⁴ / (3667 · D · n)` per degree |
| Stress | `τ = 8 · D · F / (π · d³)`, corrected `τ_k = k · τ` with Bergsträsser's `k = (w + 0.5) / (w − 0.75)`; torsion `σ_q = q · 32 M / (π d³)`, `q = (w + 0.07) / (w − 0.75)` |
| Ends, solid length | Shigley's Table 10-1: total coils and solid length by end type |
| Coil clearance | `S_a = n · (0.0015 · D² / d + 0.1 · d)` at the shortest working length |
| Buckling | `s_K = L0 · 0.5/(1 − G/E) · [1 − √(1 − (1 − G/E)/(0.5 + G/E) · (π D / (ν L0))²)]`, ν the seating coefficient |
| Natural frequency | `f_e = d / (2π · n · D²) · √(G / (2ρ))` (the standard's `3560 · d/(n D²) · √(G/ρ)`) |
| Extension hooks | Shigley eq. 10-34, bending and tension at the hook's bend |

Steel wire uses the standard's G = 81 500 MPa, E = 206 000 MPa and 7.85 kg/dm³. The wire's tensile strength is the
request's `Rm`, or Shigley's Table 10-4 estimate `R_m = A / d^m` when the request names a wire (`wire=music`,
`oil_tempered`, `hard_drawn`, `chrome_vanadium`, `chrome_silicon`). The permissible stress is the standard's share of
it (0.56 at solid length, 0.45 for extension, 0.7 in bending), or `stress_factor`. With no tensile strength the
stresses are reported with no verdict.

**Printed springs.** `material=PETG` (any filament of the library) runs the same equations on the datasheet's modulus,
with `G = E / (2 (1 + ν))` and ν = 0.35 labelled assumed. The permissible stress is then the datasheet's strength over
√3, Form Studio's own bound. The sheet carries the caveat: a printed coil creeps under a held load, is weaker between
layers, and has no fatigue data. Treat the rate as a first estimate and measure one.

Writes the coil as a swept solid: closed ends eased into the working pitch and ground flat, or tangent legs.
An extension spring is written as its close-wound body; the hooks are not drawn (their form is the maker's).

## Bolted joints and insert bosses

`fastener`, `kind` = `joint` or `boss`. Source: VDI 2230 Part 1:2015, a simplified core; ISO 898-1 property classes.

| | |
|---|---|
| Permissible assembly preload | `F_Mzul = A_s · ν · R_p0.2 / √(1 + 3 · [(3/2) · (d2/d0) · (P/(π d2) + 1.155 μ_G)]²)` |
| Tightening torque | `M_A = F_M · [0.16 P + 0.58 d2 μ_G + (D_Km / 2) μ_K]` |
| Clamp load against slipping | `F_Kerf = F_Q / (q_F · μ_T)` |
| Preload wanted | `F_Mmin = F_Kerf + F_A + F_Z`, `F_Mmax = α_A · F_Mmin ≤ F_Mzul` |
| Working stress | `σ_red = √(σ_z² + 3 (0.5 τ)²)`, `S_F = R_p0.2 / σ_red` |
| Thread stripping | The engagement at which the screw breaks before the internal thread strips, from the internal thread's shear area |

With no `size`, the smallest coarse-thread size from M2 to M16 whose permissible preload covers the demand.

**What is simplified**, on every sheet: concentric clamping and loading, static, no bending, no temperature, no
fatigue check; the whole axial load is taken off the clamp load and the bolt's added load takes the full load factor
(conservative on both sides); the bolt's shank at its nominal area; the plates as the deformation cone of an extensive
joint; thread stripping with the factors C1 and C3 as 1 and the tapped material's shear strength as R_m / √3.

**Friction is never silent.** The friction between the plates has no default: a shear load without `mu_interface` is
refused. Thread and head friction default to 0.12, labelled assumed, and the torque's label carries the friction it
belongs to.

**Insert bosses.** Hole, insert length and least wall are the insert maker's published figures (CNC Kitchen). The
datasheet gives no pull-out force, so none is quoted as a rating. With a boss material from the library the sheet
gives a modelled upper bound, `π · d_insert · L_insert · R_m / √3`, says it is a bound, and compares the load against
it with a safety factor of 3 (assumed).

Writes two plates with ISO 273 clearance holes, counterbores and tap-drill holes from the hole wizard (`form.parts`),
or a boss with the insert's pocket. An insert boss can go onto a face of another design.

## Gears

`gear`, `kind` = `external`, `internal` or `rack`. Geometry: ISO 21771, checked against the KHK Gear Technical
Reference's tables.

| | |
|---|---|
| Transverse section | `α_t = atan(tan α_n / cos β)`, `m_t = m_n / cos β`, `d = z · m_t`, `d_b = d · cos α_t` |
| Working pressure angle | `inv α_wt = inv α_t + 2 tan α_n · (x1 + x2) / (z1 + z2)` |
| Centre distance | `a_w = a · cos α_t / cos α_wt` |
| Tooth depth | `h_a1 = (1 + y − x2) m_n`, `h = (2.25 + y − (x1 + x2)) m_n` |
| Contact ratio | `ε_α = [√(r_a1² − r_b1²) + √(r_a2² − r_b2²) − a_w sin α_wt] / (π m_t cos α_t)`; helical overlap `ε_β = b sin β / (π m_n)` |
| Undercut | `x_min = 1 − z sin² α_t / (2 cos β)` |
| Backlash | `j_bn = 2 m_n Δx sin α_n` from a centre distance wider than the tight mesh, plus tooth thinning |
| Bending | Lewis: `σ_F = K_v · F_t / (b · m_n · Y)`, Y from Shigley's Table 14-2, Barth's `K_v = (6.1 + V) / 6.1` |

**Bending is Lewis, and labelled so.** No ISO 6336 or AGMA factors (stress concentration, load sharing, application,
size, life), no contact (pitting) stress, no fatigue. The form factor is the unshifted 20° value even for shifted or
helical teeth (then with the virtual tooth count). Internal pairs and racks take no profile shift on the ring or rack.
Tip interference of an internal pair is not computed: a rule of thumb, labelled assumed, warns under ten teeth of
difference.

The solids are written with py_gearworks' involute generator and placed in mesh at the working centre distance. A
rack's flanks are straight lines at the pressure angle, which is exact. The built tooth is measured against the exact
involute ([below](#the-solids-measured)).

## Cams

`cam`. Source: Norton, *Design of Machinery*, chapter 8. A rise-dwell-fall-dwell plate cam for a translating roller
follower, with a cycloidal, simple harmonic or 3-4-5 polynomial law.

| | |
|---|---|
| Pressure angle | `φ = atan((s′ − e) / (s + √(R_p² − e²)))` |
| Radius of curvature | `ρ = ((R_p + s)² + s′²)^1.5 / ((R_p + s)² + 2 s′² − (R_p + s) s″)` |

Checks: the pressure angle within 30° (or `max_pressure_angle`), and the smallest convex radius of curvature above the
roller radius, with a warning under twice it. With no base circle given, the smallest that keeps the pressure angle.
Simple harmonic motion next to a dwell is warned: its acceleration jumps.

## Fits at temperature

`fit`. The limits are ISO 286's (`form/iso286.py`, the one copy that `form.craft.fits` also reads) at ISO 1's 20 °C.
Each part grows by its own expansion, `d(T) = d(20 °C) · (1 + α · (T − 20))`, so the clearance or interference range
is given at 20 °C, at both ends of the span and over the whole span, with the change per kelvin. A fit that changes
character over the span (clearance at 20 °C, interference cold) is a `WARN`.

The expansion coefficients are the materials' sourced values or the request's. A material with no sourced coefficient
(the library's mild steel has none) leaves the span out and asks for `alpha_hole` or `alpha_shaft`.

## Verification

Each calculator is run on worked examples whose answers are printed in their sources. The reference is only what the
source prints. Where the source rounds an intermediate, the accepted error covers the rounding and the row says so.
`form calc verify` prints this table; `tests/test_calculators.py` asserts it.

<!-- verification-table -->
| Calculator | Case | Quantity | Reference | Computed | Unit | Error | Accepted | Source | Note |
|---|---|---|---|---|---|---|---|---|---|
| snapfit | Calculation example I: PC hook, l 19, b 9.5, y 2.4 mm, half of 4 % strain, thickness tapering to one-half | thickness h | 3.28 | 3.27908 | mm | 0.028 % | 0.2 % | Bayer, Snap-Fit Joints for Plastics |  |
| snapfit | ″ | deflection force P | 32.5 | 32.526 | N | 0.08 % | 0.2 % | Bayer, Snap-Fit Joints for Plastics | E_s = 1815 MPa from the guide's Fig. 16 |
| snapfit | ″ | mating force W | 58.5 | 58.591 | N | 0.16 % | 0.3 % | Bayer, Snap-Fit Joints for Plastics | the guide reads the friction term as 1.8 off its chart; it is 1.801 |
| snapfit | Annular example: PC lamp cover, d 200, t 2.5, undercut 2 × 1 mm, both parts equally stiff | hoop strain | 0.005 | 0.005 |  | 0 % | 0.0001 % | Bayer, Snap-Fit Joints for Plastics |  |
| snapfit | ″ | geometric factor X_N | 0.0017 | 0.00168613 |  | 0.82 % | 1 % | Bayer, Snap-Fit Joints for Plastics | read off the guide's Fig. 27; its formula gives 0.001686 |
| snapfit | ″ | transverse force P | 748 | 741.898 | N | 0.82 % | 1 % | Bayer, Snap-Fit Joints for Plastics | the guide multiplies by the rounded 0.0017 |
| snapfit | ″ | mating force W | 1346 | 1336.42 | N | 0.71 % | 1 % | Bayer, Snap-Fit Joints for Plastics | same rounding |
| spring | Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | tensile strength S_ut | 324 | 323.578 | kpsi | 0.13 % | 0.3 % | Shigley's Mechanical Engineering Design, 10th ed. | Table 10-4, A / d^m |
| spring | ″ | correction factor K_B | 1.124 | 1.12408 |  | 0.0069 % | 0.1 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| spring | ″ | rate k | 4.13 | 4.11565 | lbf/in | 0.35 % | 0.5 % | Shigley's Mechanical Engineering Design, 10th ed. | the book rounds intermediates; exact arithmetic gives 4.116 |
| spring | ″ | solid length L_s | 0.5 | 0.4995 | in | 0.1 % | 0.2 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| spring | ″ | load at torsional yield | 6.46 | 6.43366 | lbf | 0.41 % | 0.5 % | Shigley's Mechanical Engineering Design, 10th ed. | from the sheet's k and R_m |
| spring | ″ | deflection at that load | 1.56 | 1.56322 | in | 0.21 % | 0.5 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| spring | ″ | longest free length that cannot buckle | 2.11 | 2.10663 | in | 0.16 % | 0.3 % | Shigley's Mechanical Engineering Design, 10th ed. | EN 13906-1's buckling relation changes from no root to a root at 2.63 D / α |
| spring | d 2, D 20, n 8, steel | natural frequency, the standard's 3560 d/(n D²) √(G/ρ) | 226.712 | 226.636 | Hz | 0.033 % | 0.1 % | EN 13906-1 | the SI form used here against the standard's unit form (3560 is 10³·√500/2π = 3558.8, rounded) |
| fastener | M6 class 8.8, μ = 0.1 | permissible preload F_M | 10.4 | 10.4473 | kN | 0.46 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 9 | 8.95675 | N·m | 0.48 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M6 class 8.8, μ = 0.12 | permissible preload F_M | 10.2 | 10.1819 | kN | 0.18 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 10.1 | 10.1493 | N·m | 0.49 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M6 class 8.8, μ = 0.14 | permissible preload F_M | 9.9 | 9.90656 | kN | 0.066 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 11.3 | 11.2564 | N·m | 0.39 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M8 class 8.8, μ = 0.1 | permissible preload F_M | 19.1 | 19.1032 | kN | 0.017 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 21.6 | 21.6375 | N·m | 0.17 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M8 class 8.8, μ = 0.12 | permissible preload F_M | 18.8 | 18.6273 | kN | 0.92 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | the table prints 18.8 between 19.1 and 18.1; the guideline's formula gives 18.6 |
| fastener | ″ | tightening torque M_A | 24.6 | 24.573 | N·m | 0.11 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M8 class 8.8, μ = 0.14 | permissible preload F_M | 18.1 | 18.1315 | kN | 0.17 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 27.3 | 27.3011 | N·m | 0.0039 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M10 class 8.8, μ = 0.1 | permissible preload F_M | 30.3 | 30.3504 | kN | 0.17 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 43 | 42.6193 | N·m | 0.89 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M10 class 8.8, μ = 0.12 | permissible preload F_M | 29.6 | 29.6032 | kN | 0.011 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 48 | 48.4631 | N·m | 0.97 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M10 class 8.8, μ = 0.14 | permissible preload F_M | 28.8 | 28.8229 | kN | 0.08 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 54 | 53.8971 | N·m | 0.19 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M12 class 8.8, μ = 0.1 | permissible preload F_M | 44.1 | 44.1888 | kN | 0.2 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 73 | 73.5003 | N·m | 0.69 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M12 class 8.8, μ = 0.12 | permissible preload F_M | 43 | 43.1095 | kN | 0.26 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 84 | 83.632 | N·m | 0.44 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener | M12 class 8.8, μ = 0.14 | permissible preload F_M | 41.9 | 41.9807 | kN | 0.19 % | 0.6 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |  |
| fastener | ″ | tightening torque M_A | 93 | 93.0566 | N·m | 0.061 % | 1.2 % | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) | hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| gear | Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | working pressure angle | 26.0886 | 26.0886 | deg | 0.00015 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | centre distance | 56.4999 | 56.4999 | mm | 5.3e-05 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | centre distance modification y | 0.8333 | 0.83329 |  | 0.0012 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | ″ | pinion tip diameter | 44.84 | 44.8397 | mm | 0.00058 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | ″ | gear tip diameter | 79.4 | 79.3997 | mm | 0.00033 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | ″ | pinion root diameter | 32.1 | 32.1 | mm | 0 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | ″ | gear root diameter | 66.66 | 66.66 | mm | 0 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | ″ | tooth depth | 6.37 | 6.36987 | mm | 0.002 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | transverse pressure angle | 22.7959 | 22.7959 | deg | 0 % | 0.0001 % | KHK Gear Technical Reference |  |
| gear | ″ | working pressure angle | 23.1126 | 23.1126 | deg | 0.00013 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | centre distance | 125 | 125 | mm | 0 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | pinion reference diameter | 41.569 | 41.5692 | mm | 0.00053 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | gear reference diameter | 207.846 | 207.846 | mm | 4.8e-05 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | pinion base diameter | 38.322 | 38.3223 | mm | 0.00076 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | gear base diameter | 191.611 | 191.612 | mm | 0.00026 % | 0.001 % | KHK Gear Technical Reference |  |
| gear | ″ | pinion tip diameter | 48.153 | 48.1539 | mm | 0.0019 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | ″ | gear tip diameter | 213.842 | 213.842 | mm | 9.4e-05 % | 0.01 % | KHK Gear Technical Reference |  |
| gear | Example 13-1: P 2 teeth/in, 16/40 teeth, 20°, mounted 1/4 in too far apart | pinion base radius | 3.76 | 3.75877 | in | 0.033 % | 0.2 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| gear | ″ | gear base radius | 9.4 | 9.39693 | in | 0.033 % | 0.2 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| gear | ″ | pressure angle as mounted | 22.59 | 22.6005 | deg | 0.046 % | 0.1 % | Shigley's Mechanical Engineering Design, 10th ed. | the book rounds the base radius first; exact arithmetic gives 22.60 |
| gear | Example 14-1: P 8, 16 teeth, face 1.5 in, 1200 rev/min, W_t 365 lbf | velocity factor K_v | 1.52 | 1.52326 |  | 0.21 % | 0.3 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| gear | ″ | Lewis form factor Y | 0.296 | 0.296 |  | 0 % | 1e-07 % | Shigley's Mechanical Engineering Design, 10th ed. |  |
| gear | ″ | bending stress | 10 | 10.0178 | kpsi | 0.18 % | 0.3 % | Shigley's Mechanical Engineering Design, 10th ed. | the book's allowable stress, which its W_t = 365 lbf was sized to |
| gear | involute function | inverse of inv α at α = 26.0886° | 26.0886 | 26.0886 | deg | 1.4e-14 % | 1e-07 % | ISO 21771 |  |
| cam | cycloidal rise | peak velocity factor C_v (v = C_v h/β) | 2 | 2 |  | 3.6e-05 % | 0.1 % | Norton, Design of Machinery, ch. 8 |  |
| cam | ″ | peak acceleration factor C_a (a = C_a h/β²) | 6.283 | 6.28319 |  | 0.0029 % | 0.1 % | Norton, Design of Machinery, ch. 8 |  |
| cam | harmonic rise | peak velocity factor C_v (v = C_v h/β) | 1.571 | 1.5708 |  | 0.013 % | 0.1 % | Norton, Design of Machinery, ch. 8 |  |
| cam | ″ | peak acceleration factor C_a (a = C_a h/β²) | 4.935 | 4.9348 |  | 0.004 % | 0.1 % | Norton, Design of Machinery, ch. 8 |  |
| cam | poly345 rise | peak velocity factor C_v (v = C_v h/β) | 1.875 | 1.875 |  | 6.1e-06 % | 0.1 % | Norton, Design of Machinery, ch. 8 |  |
| cam | ″ | peak acceleration factor C_a (a = C_a h/β²) | 5.777 | 5.7735 |  | 0.061 % | 0.1 % | Norton, Design of Machinery, ch. 8 | the handbook prints 5.777 for the 3-4-5 polynomial; the exact maximum is 5.7735 |
| fit | H7/g6 at Ø25: hole 0/+21 µm, shaft −7/−20 µm | smallest clearance at 20 °C | 0.007 | 0.007 | mm | 0 % | 1e-07 % | ISO 286-2 tables |  |
| fit | ″ | largest clearance at 20 °C | 0.041 | 0.041 | mm | 0 % | 1e-07 % | ISO 286-2 tables |  |
| fit | H7/g6 at Ø25: hole 0/+21 µm, shaft −7/−20 µm; aluminium on steel, +100 K | growth of the clearance, d (α_h − α_s) ΔT = 25 × 11.9e-6 × 100 | 0.02975 | 0.0298 | mm | 0.17 % | 0.2 % | hand calculation | the limits scale too, hence the 0.1 % difference |

72 of 72 rows within the accepted error.
<!-- /verification-table -->

Living hinges have no published worked example to check against: the elastic mode is one closed-form relation, and
the moulded mode is cited dimensions.

## The solids, measured

Each kind of solid is built and measured against the sheet that sized it (`form calc verify --geometry`). A gear's
tooth is cut with a thin tube at four radii between the base and the tip, and its arc thickness there compared with
the exact involute's.

<!-- geometry-table -->
| Solid | Measured on the solid | Expected | Measured | Unit | Difference | Accepted |
|---|---|---|---|---|---|---|
| snap hook | root thickness plus undercut (extent in X) | 3.83177 | 3.83177 | mm | 4.42e-08 | 0.0001 |
| snap hook | width (extent in Y) | 6 | 6 | mm | 0 | 0.0001 |
| snap hook | valid solid | 1 | 1 |  | 0 | 0 |
| compression spring | free length (between the ground faces) | 24.7264 | 24.7264 | mm | 3.68e-07 | 0.02 |
| compression spring | outside diameter D + d | 15.6 | 15.6001 | mm | 5.93e-05 | 0.02 |
| compression spring | wire volume against π d²/4 · π D n_t (less what is ground off) | 1 | 0.975915 | ratio | 0.0241 | 0.08 |
| compression spring | valid solid | 1 | 1 |  | 0 | 0 |
| spur gear, x = 0.3 | tip diameter d_a1 (bounding box) | 33.1461 | 33.1461 | mm | 4.2e-06 | 0.002 |
| spur gear, x = 0.3 | tooth thickness against the exact involute at four radii, largest difference | 0 | 0.000677423 | mm | 0.000677 | 0.002 |
| spur gear, unshifted | tip diameter d_a1 (bounding box) | 52 | 52 | mm | 2e-07 | 0.002 |
| spur gear, unshifted | tooth thickness against the exact involute at four radii, largest difference | 0 | 0.00127748 | mm | 0.00128 | 0.002 |
| helical gear, β = 20° | tip diameter d_a1 (bounding box) | 35.9253 | 35.9253 | mm | 3.37e-06 | 0.002 |
| helical gear, β = 20° | tooth thickness against the exact involute at four radii, largest difference | 0 | 0.0014946 | mm | 0.00149 | 0.002 |
| spur pair, x = 0.3 | centre distance at which the library meshes the two gears | 44.573 | 44.573 | mm | 2.17e-06 | 0.002 |
| spur pair, x = 0.3, backlash 0.1 | volume the meshed pinion and gear share | 0 | 0 | mm³ | 0 | 0.001 |
| helical pair, β = 20°, backlash 0.1 | volume the meshed pinion and gear share | 0 | 0 | mm³ | 0 | 0.001 |
| internal pair, backlash 0.1 | volume the pinion and the internal gear share | 0 | 0 | mm³ | 0 | 0.001 |
| rack | length = teeth × π m | 62.8319 | 62.8319 | mm | 0 | 0.0001 |
| rack and pinion, backlash 0.1 | volume the pinion and the rack share | 0 | 0 | mm³ | 0 | 0.001 |
| cam | largest radius = base circle + lift (extent toward the dwell) | 28 | 28 | mm | 1e-07 | 0.02 |
| cam | valid solid | 1 | 1 |  | 0 | 0 |
| fit pair | pin diameter = middle of g6 at Ø25 | 24.9865 | 24.9865 | mm | 0 | 0.0001 |
| insert boss | boss diameter = hole + 2 × least wall (CNC Kitchen M3: 4.0 + 2 × 1.6) | 7.2 | 7.2 | mm | 0 | 0.0001 |
| insert boss | pocket depth below the boss top = insert length + 1 | 6.7 | 6.7 | mm | 0 | 0.001 |

24 of 24 measurements within the accepted difference.
<!-- /geometry-table -->

Every kind (19 designs: three hook designs, an annular joint, two hinges, four springs, two bolted joints, an insert
boss, spur, helical and internal gear pairs, a rack and pinion, a cam, a fit pair) also builds through the Studio as a
design with parameters, with every feature built, and passes the design checks.

## By finite elements

`calculate(..., build=True, fea=True)` defines a static strength study on a cantilever hook: the pad held, the
deflection force on the lip's face. Beam theory says what it should find: the peak stress at the root, `E · ε`, and
the largest displacement at the top of the hook.

| Hook | Quantity | Beam theory | Finite elements | Difference |
|---|---|---|---|---|
| POM, l 30, h 2, b 6 mm, y 1.82 mm, P 2.33 N | Peak stress at the root | 17.50 MPa | 17.30 MPa ± 0.6 % | −1.2 % |
| ″ | Largest displacement (top of the hook) | 2.15 mm | 2.25 mm | +4.3 % |

Run with the strength engine (Netgen 6.2.2608, scikit-fem 12.0.2), converged, peak stress at the root. The solid
moves a little more than the beam because the root and the pad give and the beam equation has no shear. A stubby hook
(length under five thicknesses) is warned on the sheet: there the solid moves far more than the equation says.

Without the strength engine the study is defined and says it cannot run; nothing is made up. Finite elements are not
applied to the other calculators in this version.

## What is not covered

- Fatigue, for any of them: springs, bolts, gear roots and hinges are checked statically.
- Secant modulus curves: forces of snap joints use one modulus.
- The full VDI 2230: eccentric joints, bending, thermal loads, alternating stress.
- ISO 6336 or AGMA gear ratings, contact stress, tip interference of internal pairs, profile shift on rings and racks.
- Cam followers other than a translating roller; the offset enters the pressure angle only.
- Moisture swelling and interference stress in fits.
- Printed parts beyond the datasheet's specimens: infill, walls, layer bonding and creep are caveats, not numbers.
