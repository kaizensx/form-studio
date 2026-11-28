# Lattices and TPMS infill

A strut lattice or a triply periodic minimal surface (TPMS) inside a region of a design, with a skin left round it.
The lattice is one feature of the design: it is kept as data in the design's source, the build replaces the inside
of the region with it, and changing or removing it is a new revision.

| | |
|---|---|
| Code | `form/lattice/` (`cells.py` unit cells, `geom.py` the geometry in the kernel, `homog.py` one cell by finite elements) |
| MCP | `lattice_properties` (reads only), `lattice_fill` |
| Terminal | `form lattice list \| props \| fill \| show \| remove` (JSON) |
| Bench | *Lattice infill*, in Check |
| Tests | `tests/test_lattice.py` |

## The cells

**TPMS**, as the usual trigonometric level sets with X = 2πx / a:

| Kind | f(X, Y, Z) |
|---|---|
| `gyroid` | sin X cos Y + sin Y cos Z + sin Z cos X |
| `schwarz_p` | cos X + cos Y + cos Z |
| `schwarz_d` (also `diamond`) | sin X sin Y sin Z + sin X cos Y cos Z + cos X sin Y cos Z + cos X cos Y sin Z |
| `neovius` | 3 (cos X + cos Y + cos Z) + 4 cos X cos Y cos Z |

Each gives two solids: a **sheet** |f| ≤ c (a wall about the surface, open on both sides) and a **network** f ≤ c
(one of the two channel systems filled). Schwarz D and "diamond" are the same surface, so they are one kind.

**Struts**, nodes in units of the cell a. Each strut is a cylinder; each node carries a sphere `node` times the
strut's radius (1.25 by default), so the surfaces cross instead of grazing each other.

| Kind | Struts | Length per cell |
|---|---|---|
| `bcc` | centre to the 8 corners | 4√3 a |
| `fcc` | each face centre to that face's 4 corners | 6√2 a |
| `octet` | `fcc` plus the 12 struts between neighbouring face centres | 12√2 a |
| `kelvin` | the 36 edges of the truncated octahedron (0, ±1, ±2) a / 4 | 6√2 a |

Size a cell by one of `density` (relative density), `wall` (mm, a sheet TPMS) or `strut_d` (mm).

## What is built: B-rep or mesh, and why

The region is the body, or the part of it inside a `region` box. The inner region is the region offset inward by
`skin` (an exact OCCT offset). The lattice's open space inside the inner region is cut out of the body, so the skin
and everything outside the region keep the body's own exact faces.

| Lattice | Output | Why |
|---|---|---|
| Struts, up to about 900 | **Exact B-rep**: cylinders and spheres fused in OCCT. Written to STEP. | The fuse of that many struts takes about half a minute. |
| Struts, more | **Mesh body**: the same cylinders (16-sided) and spheres as facets, combined by manifold3d. | OCCT's fuse grows to minutes. |
| TPMS, small | **Faceted B-rep**: the surface as planar triangles, cut into the exact body in OCCT. A valid solid; STEP holds facets where the lattice is. | A level set of sines has no exact B-rep. |
| TPMS, large | **Mesh body**: everything facets, combined by manifold3d. Not written to STEP. | Above about 60,000 facets (6,000 when there is no skin and the open space reaches the body's surface) OCCT's cut takes minutes. |

`output="auto"` decides on the body in the kernel and the result says which it produced and why (`plan.output`,
`plan.why`, `built.representation`). `output="brep"` or `"mesh"` forces one; a request that cannot be met is refused
with the reason.

How a TPMS is meshed: marching tetrahedra on a grid of `resolution` points per cell (14 by default). A sheet's two
channel systems, f > c and f < −c, are each the level set of a smooth function and are meshed separately; one
function |f| − c would have a crease in the middle of the wall. Vertices are moved onto the level set by two Newton
steps. Flat facets cut the corners off the curved channels, so a mesh of level c reads a few percent too dense at
practical grids: one cell is meshed at the same grid and the level is moved until that cell's faceted density equals
the true one (`built.level`, `built.level_meshed`). Facets are then merged where that moves the surface by less than
0.02 mm. The distance of the facets from the true level set is measured and returned (`built.deviation`).

Pieces of lattice that the region's edge cuts off and that touch nothing are left out and counted
(`built.fragments_removed`).

## Graded density

| `grading.mode` | Density follows |
|---|---|
| `uniform` (default) | one value |
| `distance` | the distance from `from`: `"boundary"` (the inner region's bounding box), `{"point": [x, y, z]}` or `{"plane": {"origin", "normal"}}`, reaching the second density `over` millimetres away |
| `stress` | the von Mises field of a current static strength study of the body (`study=`): density[0] where there is no stress, density[1] at the peak, `exponent` shaping the curve |

For `stress`, the study's surface field (`form/fea`, the finest mesh) is resampled to a grid of at most 8 points a
side (the mean of the 8 nearest surface vertices, by inverse distance, divided by the peak) and that grid is kept in
the design's source, so a rebuild needs no study. The study must describe the body, so it is read before the lattice
goes in. A graded TPMS varies its level in space; graded struts each take the radius of the density at their middle.

## Properties

| Number | How it is known |
|---|---|
| Relative density | **computed (unit cell)**: a smoothed count on the cell (the union of struts and node spheres, or the level set). Beside it the first-order strut formula π r² L / a³, or for a sheet the thin-wall estimate A t / a from the published area of the minimal surface. Once built: **measured on the built solid**. |
| Stiffness, strength | **computed (scaling law)**: Gibson and Ashby, E* / Es = C ρⁿ and σ* / σys = Cs ρᵐ, with the class of the cell. |
| Stiffness of one cell by FE | **computed** (`verify=True`): a periodic frame of Timoshenko beams for struts; periodic voxels for a TPMS (needs SciPy). Returned beside the law with the difference. |

The scaling laws:

| Class | E* / Es | σ* / σys | Source |
|---|---|---|---|
| bending | ρ² | 0.3 ρ^1.5 | Gibson and Ashby, *Cellular Solids*, 2nd ed. (1997), eqs 5.6a and 5.27a |
| stretch | ρ / 3 | ρ / 3 | Ashby, Phil. Trans. R. Soc. A 364 (2006) 15-30 |
| octet, along a cell axis | ρ / 9 | ρ / 3 | Deshpande, Fleck and Ashby, J. Mech. Phys. Solids 49 (2001) 1747-1769 |

The class of each cell: `bcc` and `kelvin` bending, `fcc` stretch, `octet` its own law (the exponent of the frame
model, recomputed by the tests: 2.0, 2.0, 1.0, 1.0); a sheet TPMS stretch and a network TPMS bending (Form Studio's
voxel model, and Al-Ketan, Rowshan and Abu Al-Rub, Additive Manufacturing 19 (2018) 167-183).

A scaling law is an order of magnitude with no direction. The frame model shows how far off it can be: a `bcc`
lattice loaded along a cell axis is several times more compliant than C = 1 says. Ask for `verify=True` when the
number matters, and read the difference it reports.

## Printability

Given `process=` (fdm, sla, sls, mjf, lpbf):

- **Thinnest strut or wall** against the process's sourced thinnest-wall limit (`form/dfm/rules/*.toml`), and for FDM
  against the nozzle.
- **Trapped resin or powder**, for sla, sls, mjf and lpbf: the closed voids of the built solid are counted. A skin
  seals the lattice's open space, so a filled, skinned part fails until escape holes are cut; the table's hole
  diameter is quoted.
- **Pores** (the largest sphere that fits in the open space) against the escape hole the table asks for.
- A sheet TPMS divides the space into **two channel systems that never meet**: each needs its own way out.

## Verification

`tests/test_lattice.py`. Numbers measured on this machine on 2026-11-28:

| Check | Reference | Result |
|---|---|---|
| Network TPMS at level 0, all four | exactly 0.5 (f changes sign under a rigid motion) | 0.500000 |
| Area of the level-0 surface per cell | Schwarz P 2.3451, gyroid 3.0915, Schwarz D 3.8378 (Schoen 1970; Jung and Torquato 2005, Table I) | 2.3532, 3.0931, 3.8416: within 0.35 % |
| Thin sheet density | area × wall | within 4 % at a wall of 0.03 a |
| Strut length per cell | 4√3, 6√2, 12√2, 6√2 | equal to 1e-9 |
| Octet truss, first order | 6√2 π (r / l)² (Deshpande, Fleck and Ashby 2001) | equal |
| Gibson-Ashby | the formula, each class | equal |
| Octet E by the frame model, r / a = 0.01 | ρ / 9 | 0.000593 against 0.000592 |
| Frame exponent d ln E / d ln ρ | 2, 1, 1, 2 for bcc, fcc, octet, kelvin | 1.997, 1.003, 1.003, 1.980 |
| Built TPMS density, 2 × 2 × 2 cells with a skin | the cell's (0.300) | within 0.004 for gyroid, P, D network, Neovius |
| Built octet density (exact B-rep) | the cell's | within 3 % |
| Marching tetrahedra, a sphere | 4/3 π r³ and 4 π r² | within 1 % |

## What it does not do

- No NURBS fit of a TPMS: its faces are planar triangles in both outputs.
- No 3MF beam-lattice export.
- The stress grading reads the study's surface field, not the stress inside the body.
- The scaling law says nothing about buckling of slender struts, fatigue or the knock-down of printed material.
- The frame model leaves the node spheres' material out, so it reads low for stubby struts; the voxel model has a
  thin wall only one or two voxels thick and states the change from a coarser grid as its error.
