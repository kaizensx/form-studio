"""Mesh to editable CAD: STL, OBJ or 3MF in, a verified solid and (where it fits) a feature recipe out.

    Layer 0  exact solid: one planar face per triangle, sewn and merged where coplanar     solid.py
    Layer 1  analytic faces (plane, cylinder, cone, sphere, torus) where they fit, frozen   segment.py, brep.py
             facets elsewhere, in one hybrid solid (beta)
    Layer 2  a build123d Recipe with Params: one extrusion or revolution, holes snapped to  features.py, holes.py
             standard sizes, patterns; rebuilt and compared with the mesh (beta)

Every layer is checked against the mesh (verify.py: two-sided Hausdorff, volume, deviation map). Readers and checks
(mesh.py, distance.py, fit.py, segment.py) are numpy and scipy only; the rest runs in the kernel worker.

Surfaces: the kernel op `reconstruct` (registered below), Studio.reconstruct / reconstruct_reference (project.py),
the MCP tool `reconstruct`, `form reconstruct FILE`, and "Make editable" on an imported mesh in the app.
"""
from __future__ import annotations


def op_reconstruct(path, out_dir, name=None, tolerance=0.02, layer=2, budget_s=240.0, fill_holes=True):
    """Kernel op: reconstruct a mesh file into out_dir and return the report. Reports progress while it runs."""
    from .. import kernel
    from . import pipeline
    return pipeline.reconstruct(path, out_dir, name=name, tolerance=tolerance, layer=layer, budget_s=budget_s,
                                progress=kernel.PROGRESS, fill_holes=fill_holes)


KERNEL_OPS = {"reconstruct": op_reconstruct}
