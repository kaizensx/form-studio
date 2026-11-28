# Print physics

What the print orientation does to a part: the support it needs, the time it takes, how strong it is along the load,
how the faces that show come out, whether it stands, and whether it is likely to lift off the plate. Three tools,
each with the same rule as the rest of Form Studio: **every number says how it is known.**

| Tool | Terminal | What it gives |
|---|---|---|
| `print_orient` | `form print orient <project>` | The Pareto front of print orientations over support, time, strength, surface and tip-over; the pick written to the print setup; the model checked against real slices |
| `print_strength` | `form print strength <project>` | A strength study of the part as printed: a layered material in the print orientation, the safety factor across the layers and in them, and how it changes with orientation |
| `print_warp` | `form print warp <project>` | A first-order warp-risk indicator. Never a predicted lift |

They apply to a design made for printing, with 3D printing switched on. The code is `form/printphys/`.

Evidence classes used below:

- **computed**: geometry, measured on the tessellation of the B-rep
- **modelled**: a stated model with its source; the model's limits are part of the result
- **simulated**: the slicer's own slice, or the finite-element engine
- **specified**: a value read from a document that is named, with the line it was read from
- **assumed**: said so, with the rule, and replaceable by a value you give

## Orientation: a front, not a score

`print_orient` does not return one best orientation. It returns the orientations that no other one beats on every
objective at once (the Pareto front), ranked by weights you can see and change. The pick is yours.

### Objectives

| Objective | Unit | How it is known |
|---|---|---|
| Support volume | mm³ | computed |
| Support contact on the part | mm² | computed |
| Print time | s | modelled; calibrated on a real slice when there is one |
| Strength used by the load | 1 / safety factor | modelled, from a strength study's stress field and the datasheet's Z and X-Y strengths |
| Stair height on cosmetic faces | µm | computed (cusp height) |
| Cosmetic area under support | mm² | computed |
| Tilt before it tips | degrees | computed |

Strength is an objective only when there is a load: a static strength study with a current result (`study=`), or just
its direction (`load_direction=`). Surface quality is one only when faces are marked cosmetic (`cosmetic=`, a point on
each). The result says which objectives were used and why the others were not.

### Supports, from the facets

A facet needs support when it faces down more steeply than the critical angle and does not lie on the plate. The
angle is measured from vertical: 0° is a wall, 90° a ceiling. It comes from the slicer preset's support threshold
(the slicers count from horizontal, so 90° minus theirs), else it is 45° and labelled assumed.

The support under a facet is the column from it straight down to **the first surface of the part below, or to the
plate**. The volume is the integral of that column's height over the facet's shadow. The facet's own height is
linear, so the integral is exact wherever a piece's whole shadow lands on one plane. Facets are cut into pieces
(a 120th of the part's diagonal for the rows of the front), each piece's floor is found by a ray cast down, and where
a piece straddles an edge of what is below, the result carries `support_mm3_spread`: the difference between a
one-point and a three-point rule per piece, which measures exactly that.

Support contact is what the support touches: the facets it holds up, plus the area it stands on where it lands on the
part.

Checked against shapes worked by hand (`tests/test_print_physics.py`):

| Shape | By hand | Computed |
|---|---|---|
| Tee: two 10 × 10 overhangs, 20 mm up | 4 000 mm³, contact 200 mm² | 4 000.000 mm³, 200.000 mm² |
| Cee: a 20 × 10 overhang, 15 mm above the arm below | 3 000 mm³, contact 400 mm² | 3 000.000 mm³, 400.000 mm² |
| Leaning wall, 45° from vertical | 0 at a 45° critical angle; a 2 000 mm³ wedge at 30° | 0; 2 000.000 mm³ |
| Cylinder lying on the plate, r 10, length 40 | L r² (√2 − ½ − π/4) = 515.2 mm³ | within 1 % (a tessellated circle) |
| Cee whose overhang reaches past the arm below | 3 400 mm³ | within 1 %, inside its stated spread |

### The plate

Plate contact is the flat area lying on the plate. The part tips when its centre of mass (uniform density, from the
mesh) leaves the convex hull of that contact; `tip_over_deg` is the tilt at which it does. The front is taken over
the orientations in which the part stands on the plate on its own. `free=True` also admits orientations that rest on
supports; if the part stands in none, every orientation that fits is kept and the result says so.

### Surface

A layer of thickness t leaves a stair of height t·|cos a| on a face whose normal makes the angle a with the build
direction (Dolenc and Mäkelä, "Slicing procedures for layered manufacturing techniques", Computer-Aided Design 26(2),
1994). The objective is the area-weighted mean over the faces marked cosmetic. Flat faces that face straight up or lie
on the plate have no stairs.

### Print time

The time model draws lines: walls from the area seen from the side, skins from the upward and downward areas,
infill from the rest of the volume, supports from the support volume at the preset's pattern spacing plus interface
layers. Each length is divided by its speed, plus a fixed time per layer. The values come from the slicer's process
and filament presets where they have them, and are assumed otherwise; `settings.how_known` lists which.

That model ignores acceleration, cooling slow-downs and travel, so **uncalibrated it ranks orientations and little
more**, and the result says "uncalibrated". With `calibrate=True` the current orientation is sliced once, supports
on, and the model's time and grams are multiplied by slicer / model of that slice. The two factors are stated.

### Strength along the load

With a static strength study, the tension across the layers in an orientation is b·σ·b at every surface node of the
study's field, b being the build direction, outside the zones the study left out as singular. Against the Z strength
of the filament's datasheet that is a safety factor across the layers; von Mises stress against the X-Y strength is
the in-plane one; the lower governs. The stress field is the isotropic study's, so this term is first order: how the
layered stiffness moves the stress is not in it. `print_strength` solves that.

With only a load direction, the term is the share of in-plane strength left along the load, from the datasheet's
Z / X-Y strength ratio.

### The search

Candidates: the six axis orientations, every flat face of the part's convex hull, and a geodesic grid over the
sphere of directions (162 directions at level 2, about 16° apart; 42 at level 1, 642 at level 3). From the
non-dominated candidates a walk moves to any neighbour that dominates, at half the grid spacing and halving, down to
1°. The front is recomputed over everything evaluated. Two values of an objective closer than a stated step (0.2 % of
the part's volume for support, 1 % for time) count as equal, so noise does not make a front.

### The pick

`print_orient(project, pick="<id>")`, or `form print orient <project> --pick <id>`, writes the orientation to the
design's print setup. A search writes nothing. The Bench's Make entry **Print orientation** shows the setup's
orientation and whether it is on the current front.

### Checked against the real slicer

`verify=N` slices the N best-ranked candidates, and the setup's orientation, with the real slicer, normal supports
on at the same critical angle, and reports the model's error per candidate in time and in support filament (the
slicer's support, interface and transition extrusion, read from its G-code). The slice the model was calibrated on
is marked; its time error is zero by construction and is not counted.

Measured on 2026-11-28 with Bambu Studio 02.09.01.70, preset "0.16mm High Quality @BBL A1M", Bambu PLA Basic, on two
test parts:

| Part | Calibration (time, mass) | Time error on the other orientations | Support filament, standing |
|---|---|---|---|
| Tee (a 60 × 20 cap on a 20 × 20 stem, a shelf under one side) | × 1.908, × 1.101 | 12.9 % and 12.7 % low | 5.58 g predicted, 6.38 g sliced (−12.5 %) |
| L bracket with three 6 mm holes | × 2.259, × 1.069 | 0.04 % and 0.44 % low | 0.02 g predicted, 0.25 g sliced |

Read them as they are. The time model needs its calibration: uncalibrated it is about half the slicer's time on this
printer. Calibrated on one slice, it was within 13 % on the others. Support filament was within 13 % where the
support is a real column, and far too low where the only supports sit inside small holes, because the slicer's own
minimum structures dominate there. A slice is a simulation, not a print.

`tests/test_print_physics.py` repeats the Tee comparison where a slicer resolves, and is skipped otherwise.

## Strength as printed

`print_strength` is a static strength study ([STRENGTH.md](STRENGTH.md)) with a layered material: stiff and strong
in the layers, weaker across them, turned to the print orientation. It is stored, keyed and run like any strength
study, and read with `get_strength_study`; the layered part is `result.layers`.

### The material

A transversely isotropic solid has five elastic constants. Where each comes from:

| Constant | Source |
|---|---|
| Young's modulus in the layers, E_p | specified: the filament datasheet's X-Y specimens |
| Young's modulus across the layers, E_z | specified: the datasheet's Z specimens. Without one, assumed equal to E_p, and said |
| Poisson's ratio in the layers | no filament datasheet states it. Specified from printed specimens of the same polymer where a paper gives it (PLA, ABS, PC: the table below); else it must be given |
| Poisson's ratio across the layers | in no source: assumed equal to the in-plane one, unless given |
| Shear modulus between the layers | in no source: assumed by Huber's approximation, G = √(E_p E_z) / (2 (1 + √(ν_pz ν_zp))), unless given |

Strengths: the datasheet's X-Y and Z ultimate tensile strengths. A shear strength between the layers is in no
datasheet; give one in `assume` to get a factor for it, otherwise the peak shear is reported without one.

`result.layers.material.assumed` lists every assumed value, and the study's evidence line names them. Give them in
`assume` with a `source` to replace an assumption with a specified value.

### The verdict

- **Across the layers** (the weak direction): the largest tension normal to the layer plane, against the Z strength.
  It has its own stated discretisation error, from the same refinement that settles the von Mises peak.
- **In the layers**: von Mises stress against the X-Y strength.
- The safety factor is the lower of the two, and says which governs. Compression across the layers is not taken as a
  failure.

### How it changes with orientation

`layers.by_orientation` solves the same mesh, supports and loads again with the material turned to each of the six
axis orientations (or those named in `sweep`). Only the chosen orientation is refined until it stops changing; the
others are solved on its finest mesh and carry no stated error of their own.

With `orientation="setup"` the study follows the design's print setup: picking another orientation makes its result
stale.

### Verified against closed forms

Two cases in the strength verification suite (`form/fea/verify.py`; the full table is in
[STRENGTH.md](STRENGTH.md#verification)):

| Case | Quantity | Reference | Error |
|---|---|---|---|
| A bar pulled at 30° to its build direction | elongation; tension across the layers; shear between them; the factor | Lekhnitskii's off-axis modulus, 1/E = cos⁴/E_z + sin⁴/E_p + (1/G − 2ν/E_z) sin² cos² (Jones, *Mechanics of Composite Materials*, eq. 2.97); σ cos², σ sin cos | 0.00 % (tolerance 0.1 %) |
| A cantilever in three build directions | tip deflection standing, flat and on its side; the ratio standing / flat; bending stress | A Timoshenko beam with the modulus along the beam and the shear modulus of the bending plane | 0.01 %, 0.27 %, 0.28 %; 0.00 %; 0.01 % |

### What it does not model

Infill, walls, raster direction, voids and the seam. The part is a homogeneous solid with the datasheet's values,
which are for specimens printed at 100 % infill with the datasheet's settings. Thermal stress in a layered material
is refused: no source here gives the expansion across the layers.

## Warp risk: an indicator

`print_warp` gives an index and a band. It does not predict how far a corner lifts.

### The model

Wang, Xi and Jin, "A model research for prototype warp deformation in the FDM process", International Journal of
Advanced Manufacturing Technology 33:1087–1096 (2007), doi:10.1007/s00170-006-0556-9, in the form reproduced by
Armillotta, Bellotti and Cavallaro, "Warpage of FDM parts: Experimental tests and analytic model", Robotics and
Computer-Integrated Manufacturing (2018), doi:10.1016/j.rcim.2017.09.007. Each layer shortens by α (T_g − T_e) as it
cools from the glass transition to the chamber temperature while the stack under it does not. That bends a stack of
n layers of thickness Δh to the curvature

    1 / R = 6 α (T_g − T_e) (n − 1) / (n³ Δh)

and lifts the ends of a section of length L by δ = R (1 − cos(L / 2R)).

The model assumes the part is free of the plate, solid, elastic and perfectly bonded. A real part is none of those,
so its δ is not a lift you would measure, and Armillotta's tests found the largest warpage at intermediate heights
where the model falls steadily with height. What the tests confirm is the trend over length, which dominates, and
that width does not matter.

### The index

index = the model's δ over one layer height, with

- **α** and **T_g** sourced for the polymer (the table below), or given with their source
- **T_e** the chamber temperature: given, else 25 °C, labelled assumed
- **L** the longest span of the part's contact with the plate (computed)
- **n** the part's mean height over its footprint, in layers: the volume over the footprint's area. The model has
  one height and a part is rarely a block; the index at the full height is given beside it
- **Δh** from the slicer preset, else assumed

The band is a convention on that index, stated in the result: low below 0.25, moderate below 1, high from 1. It is
raised one step by each of two conditions the model does not contain: sharp corners at the ends of the footprint
(Bambu Lab's guides name sharp corners as where a part lifts first, and brim ears at them as the remedy), and a
footprint the part touches on less than half its extent. The result lists what raised it, the footprint's corners,
its aspect ratio, and the same index for the six axis orientations.

Without a sourced α or T_g the call is refused and names what to give. It knows nothing of the plate, its
temperature, the adhesive, a brim, infill or drafts, and it is not calibrated to any print.

## Sourced values

Filament datasheets state no thermal expansion, no glass transition and no Poisson's ratio. These values are for the
same polymer from another document, and each result that uses one says so (`form/printphys/sources.py` has the URL
and the table line each was read from, on 2026-11-28).

| Polymer | Value | From | Basis |
|---|---|---|---|
| PLA | α 96 ± 5 × 10⁻⁶ /K; T_g 62 ± 2 °C | Matsika-Klossa et al., Materials 17(18):4668 (2024), Table 2 | printed specimens, fibre Bragg grating |
| PLA | ν 0.331 ± 0.011 | Ferreira et al., Composites Part B 124 (2017), Table 4 | printed specimens, ASTM D638 |
| ABS | α 86 ± 3 × 10⁻⁶ /K; T_g 92 ± 2 °C | Matsika-Klossa et al. (2024), Table 2 | printed specimens |
| ABS | ν 0.36 to 0.38 | Cantrell et al., Rapid Prototyping Journal (2017), Table II | printed specimens, ASTM D638 with image correlation |
| PA | α 118 ± 5 × 10⁻⁶ /K; T_g 52 ± 2 °C | Matsika-Klossa et al. (2024), Table 2 | printed specimens (Taulman Bridge nylon) |
| PETG | α 51 × 10⁻⁶ /K; T_g 80 °C | Eastman, Eastar Copolyester 6763 data sheet | moulded resin |
| ASA | α 80 to 110 × 10⁻⁶ /K | INEOS Styrolution, Luran S 777K datasheet | moulded resin |
| PC | α 65 × 10⁻⁶ /K; T_g 145 °C | Makrolon 2805 ISO datasheet | moulded resin |
| PC | ν 0.29 to 0.39 | Cantrell et al. (2017), Table III | printed specimens |

No glass transition was found for ASA in a document that was read: the datasheet's Vicat softening temperature
stands in, labelled assumed. Nothing is sourced for TPU and the fibre-filled filaments; the tools ask for the values.

## The Bench

In Check: **Orientation front** (`print.orient`), **Strength as printed** (`print.strength`) and **Warp risk**
(`print.warp`). In Make: **Print orientation** (`print.orientation`), the orientation in the print setup and whether
it is on the front. Each is keyed by the geometry and by what else it reads, so a new revision or a new print setup
makes it stale by construction.

## What is not here yet

- A warp map on the part, and a thermoelastic tier of the warp model
- Tree supports in the support and time model (the comparison forces normal supports)
- Layered studies of a design with several parts, and layered modal or buckling studies
- The window's panes for these entries: the Bench lists and runs them, the results are read through the tools
