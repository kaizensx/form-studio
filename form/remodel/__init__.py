"""Reference parts an agent rebuilds as clean CAD: read a mesh like an engineer, then compare the rebuild with it.

The deterministic route (form/recon) turns a mesh into CAD by itself. Real parts often need judgement: what a strip
between two planes is for, which walls are rails, how three parts move together. This package gives an agent what
an engineer would measure before modelling, and checks the result:

    analyze.py     analyze_reference: principal axes, dimensioned sections (images and vector outlines), features
                   with sizes (holes, bosses, slots, pockets, walls, rails and grooves, steps, ramps, fillets,
                   chamfers, detail areas), symmetry, wall thicknesses and draft
    mechanism.py   analyze_assembly: contacts and mating surfaces between parts, slide and turn axes, clearances,
                   the range of travel, and couplings (a rack on a gear, a ramp on a follower)
    compare.py     compare_to_reference: two-sided Hausdorff between a design (or one part of it) and the mesh, a
                   deviation picture, the worst regions named by where they are, and per-feature differences
    sections.py    plane sections of a triangle mesh as closed loops, measured and drawn with dimensions
    occupancy.py   inside-or-outside of a closed mesh on a grid (for travel and interference)

numpy, scipy and Pillow only: no OCCT, so the MCP server, the CLI and the app's engine can run it directly.
Evidence class: computed (measured on the mesh as given; the mesh's own chord error is part of the input).
"""
from __future__ import annotations

VERSION = 2          # part of every cached analysis's name: change what is measured, change this
