"""Print physics: what the print orientation does to supports, time, strength, surface and warping.

    form/printphys/geom.py       pure numpy on the tessellation: overhang facets against the critical angle, support
                                 columns down to the plate or to the part, plate contact, tip-over, cusp height on
                                 the faces marked cosmetic, stress across the layers from a study's stress field;
                                 the geodesic grid and the Pareto front
    form/printphys/timemodel.py  a layer-time model from facet integrals and the slicer preset's speeds, with one
                                 calibration factor from a real slice when there is one (always stated)
    form/printphys/orient.py     the search (grid, then local refinement), the front, the pick written to the print
                                 setup, and the top candidates sliced for real with the model's error reported
    form/printphys/layers.py     a printed part as a transversely isotropic solid: in-plane values from the
                                 datasheet, Z from the datasheet's own Z specimens; what no source gives is given by
                                 the caller or assumed, and labelled so. The solver is form/fea (solve.py, core.py)
    form/printphys/warp.py       a first-order warp-risk indicator (Wang, Xi and Jin 2007), never a predicted lift
    form/printphys/tools.py      MCP: print_orient, print_strength, print_warp
    form/printphys/cli.py        `form print orient|strength|warp ...` (JSON)
    form/printphys/bench.py      Bench entries: Check (orientation front, layer-aware strength, warp risk) and Make
                                 (the orientation written to the print setup)

Every number says how it is known: computed (geometry on the tessellation), modelled (a stated model with its source),
simulated (a real slicer, or the FEA engine), specified (a datasheet value with its document) or assumed (said so).
docs/PRINT_PHYSICS.md has the methods, the sources and the verification numbers.
"""
from __future__ import annotations

VERSION = 1
CRITICAL_DEG = 45.0             # the steepest overhang, measured from vertical, printed without support
