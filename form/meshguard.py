"""OCCT's mesher in a child process, so a mesh that never finishes cannot stop an export.

BRepMesh can run for minutes on one face at a fine absolute deflection (a design that meshed in 2.5 s at 0.02 mm did
not finish in 5 minutes at 0.01 mm) and cannot be interrupted inside the kernel worker. form/meshclose.py writes the
shape once as a BRep file and asks this module, in a child process (`python -m form.meshguard`, which the packaged
app also runs), for the triangles of one solid or of all of them; the parent waits with a timeout and kills a child
that runs over.

    python -m form.meshguard SHAPE.brep OUT_DIR TOL ANG PIECE FACES_ALONE

PIECE: index of the solid, or -1 for every solid. FACES_ALONE=1: after meshing the solid, mesh the faces that got
no triangles one by one at finer settings. Writes OUT_DIR/<k>.stl per solid and OUT_DIR/info.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def write_brep(shape, path) -> None:
    from OCP.BRepTools import BRepTools
    BRepTools.Write_s(shape.wrapped, str(path))


def _read(path):
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    from build123d import Compound
    sh = TopoDS_Shape()
    BRepTools.Read_s(sh, str(path), BRep_Builder())
    return Compound(sh)


def run(brep: Path, piece: int, tol: float, ang: float, faces_alone: bool, timeout: float):
    """[(triangles (n, 3, 3), faces without triangles)] for the requested solid(s), or None when the mesher did not
    finish in `timeout` seconds (the child is killed)."""
    import numpy as np
    out = Path(tempfile.mkdtemp(prefix="form-meshguard-"))
    cmd = [sys.executable, "-m", "form.meshguard", str(brep), str(out), repr(tol), repr(ang), str(piece),
           "1" if faces_alone else "0"]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1])] +
                                                       ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=max(1.0, timeout), env=env)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or b"").decode("utf-8", "replace").strip()[-300:] or f"exit {p.returncode}")
        info = json.loads((out / "info.json").read_text(encoding="utf-8"))
        res = []
        for k, missing in enumerate(info["missing"]):
            raw = np.fromfile(str(out / f"{k}.stl"), dtype=np.uint8)
            n = int(raw[80:84].view(np.uint32)[0]) if raw.size >= 84 else 0
            V = (np.ascontiguousarray(raw[84:84 + 50 * n].reshape(n, 50)[:, 12:48]).view(np.float32)
                 .reshape(n, 3, 3).astype(np.float64)) if n else np.zeros((0, 3, 3))
            res.append((V, int(missing)))
        return res
    except subprocess.TimeoutExpired:
        return None
    finally:
        import shutil
        shutil.rmtree(out, ignore_errors=True)


def main(argv) -> int:
    brep, out, tol, ang, piece, alone = argv[0], Path(argv[1]), float(argv[2]), float(argv[3]), int(argv[4]), argv[5] == "1"
    from form import meshclose
    shape = _read(brep)
    pieces = meshclose._pieces(shape)
    targets = pieces if piece < 0 else [pieces[piece]]
    if piece < 0:
        meshclose._mesh(shape, tol, ang)
    else:
        meshclose._mesh(targets[0], tol, ang)
    missing = []
    for k, solid in enumerate(targets):
        V, miss = meshclose._triangles(solid)
        if alone and miss:
            for t, a in ((tol / 2, ang), (tol / 5, ang / 2), (tol / 20, ang / 2), (tol / 50, ang / 4)):
                for f in miss:
                    meshclose._mesh(f, t, a, clean=False)
                V, miss = meshclose._triangles(solid)
                if not miss:
                    break
        meshclose.write(out / f"{k}.stl", [V])
        missing.append(len(miss))
    (out / "info.json").write_text(json.dumps({"missing": missing}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
