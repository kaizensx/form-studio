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


START_S = 180.0          # a child that has not loaded the kernel and read the shape by then is stopped


def run(brep: Path, piece: int, tol: float, ang: float, faces_alone: bool, timeout: float, stats: dict | None = None):
    """[(triangles (n, 3, 3), faces without triangles)] for the requested solid(s), or None when the mesher did not
    finish in `timeout` seconds (the child is killed).

    `timeout` is the mesher's time: it starts when the child has loaded the CAD kernel and read the shape (it
    writes OUT_DIR/ready then). Starting a process and loading the kernel takes 1 s on one machine and 15 s on
    another (a Windows machine with a virus scanner, a CI runner); counted against the mesher, every setting "did
    not finish" there and no STL could be made. stats["start_s"] gets what the start took."""
    import time

    import numpy as np
    out = Path(tempfile.mkdtemp(prefix="form-meshguard-"))
    cmd = [sys.executable, "-m", "form.meshguard", str(brep), str(out), repr(tol), repr(ang), str(piece),
           "1" if faces_alone else "0"]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1])] +
                                                       ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    err = out / "stderr.txt"
    p = None
    try:
        t0 = time.monotonic()
        with open(err, "wb") as ef:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=ef, env=env)
            ready = out / "ready"
            while p.poll() is None and not ready.exists():
                if time.monotonic() - t0 > START_S:
                    return None
                time.sleep(0.02)
            if stats is not None:
                stats["start_s"] = time.monotonic() - t0
            try:
                p.wait(timeout=max(1.0, timeout))
            except subprocess.TimeoutExpired:
                return None
        if p.returncode != 0:
            raise RuntimeError(err.read_bytes().decode("utf-8", "replace").strip()[-300:] or f"exit {p.returncode}")
        info = json.loads((out / "info.json").read_text(encoding="utf-8"))
        res = []
        for k, missing in enumerate(info["missing"]):
            raw = np.fromfile(str(out / f"{k}.stl"), dtype=np.uint8)
            n = int(raw[80:84].view(np.uint32)[0]) if raw.size >= 84 else 0
            V = (np.ascontiguousarray(raw[84:84 + 50 * n].reshape(n, 50)[:, 12:48]).view(np.float32)
                 .reshape(n, 3, 3).astype(np.float64)) if n else np.zeros((0, 3, 3))
            res.append((V, int(missing)))
        return res
    finally:
        if p is not None and p.poll() is None:
            p.kill()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                pass
        import shutil
        shutil.rmtree(out, ignore_errors=True)


def main(argv) -> int:
    brep, out, tol, ang, piece, alone = argv[0], Path(argv[1]), float(argv[2]), float(argv[3]), int(argv[4]), argv[5] == "1"
    from form import meshclose
    shape = _read(brep)
    pieces = meshclose._pieces(shape)
    (out / "ready").write_text("", encoding="utf-8")       # the kernel is loaded and the shape read: the mesher's time starts
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
