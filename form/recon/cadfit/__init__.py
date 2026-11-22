"""CADFit as one more mesh-to-CAD candidate: optional, off unless `[recon] cadfit = true`, run in a child process with
a hard deadline.

CADFit (github.com/ghadinehme/CADFit; Nehme, Whalen, Ahmed, "CADFit: Precise Mesh-to-CAD Program Generation with
Hybrid Optimization", ICML 2026) searches for a CAD program by IoU: sketches read from planar and axis slices of the
mesh, extrusion heights and revolve axes measured against its surface, then a greedy search over extrusions and
revolves with beam refinement and backward pruning. Its code is CC BY-NC 4.0 and is included here with its author's
permission (PERMISSION.md); Form Studio's MIT licence does not cover this folder.

    1. driver.py      CADFit's steps in one child process, in a work folder of its own; killed at the deadline
    2. cqrun.py       its CadQuery program read (never run as a program) as a tree of extrusions
    3. translate      placed exactly where CADFit's normalisation says, snapped to the mesh, values pooled into Params
                      (learned/translate.py, the same translation the learned engine uses)
    4. candidate()    built as the Studio builds it and verified against the mesh (valid, one solid, within the limit)

A candidate that does not verify is reported and never returned as the result. Off, or without its libraries
(trimesh, manifold3d, scikit-learn, scipy: `pip install form-studio[cadfit]`), nothing changes. This module imports
none of them: they are imported only in the child process.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import time
from pathlib import Path

NAME = "CADFit"
SOURCE = "https://github.com/ghadinehme/CADFit"
COMMIT = "227a7acdc6972c646859d7e12da279e6e4ae2789"
LICENCE = "CC BY-NC 4.0 (non-commercial; included with the author's permission, see form/recon/cadfit/PERMISSION.md)"
LIBRARIES = ("trimesh", "manifold3d", "sklearn", "scipy")
SHARE = 0.25                 # of the reconstruction budget CADFit may use
SECONDS = (20.0, 120.0)      # ... but at least / at most this many seconds
MIN_IOU = 0.97               # CADFit's own IoU below which its program cannot be within a tolerance: not built or verified
ENGINE_TEXT = (
    "{name}: reconstructed from a mesh by Form Studio with CADFit (Nehme, Whalen, Ahmed; CC BY-NC 4.0, used with the "
    "author's permission), {n} sketch extrusions placed and snapped on the mesh; every level, side and diameter is a Param.",
    "Rebuilt from a mesh with CADFit; sketches extruded between levels, snapped to the mesh.",
    "Sketch extrusions found by CADFit's IoU search, snapped to the mesh.",
)


def enabled() -> bool:
    """Is the CADFit candidate asked for? $FORM_RECON_CADFIT (1/0) first, else `[recon] cadfit` (default false)."""
    env = os.environ.get("FORM_RECON_CADFIT")
    if env is not None and env.strip() != "":
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        from ... import config
        return bool(config.load().get("recon", {}).get("cadfit", False))
    except Exception:                                   # noqa: BLE001
        return False


def _bundled() -> bool:
    """Is CADFit's search code here? The packaged app leaves it out (packaging/form.spec CADFIT_ONLY)."""
    try:
        return all(importlib.util.find_spec(f"{__name__}.{m}") is not None for m in ("driver", "cqrun", "vendor"))
    except Exception:                                   # noqa: BLE001
        return False


def status() -> dict:
    """Enabled, and are its code and libraries there? Imports none of them."""
    missing = []
    for m in LIBRARIES:
        try:
            if importlib.util.find_spec(m) is None:
                missing.append(m)
        except (ImportError, ValueError):
            missing.append(m)
    bundled = _bundled()
    out = {"name": NAME, "enabled": enabled(), "installed": bool(bundled and not missing), "bundled": bundled,
           "licence": LICENCE, "source": SOURCE, "commit": COMMIT}
    if missing:
        out["missing_libraries"] = missing
    if missing or not bundled:
        out["needs"] = "form-studio[cadfit]"
    return out


def seconds_for(budget_s: float) -> float:
    """CADFit's fixed slice of a reconstruction budget."""
    return float(min(SECONDS[1], max(SECONDS[0], SHARE * float(budget_s))))


def _child(conn, stl, work, seconds):                   # pragma: no cover - runs in the child process
    """The child process: CADFit's pipeline. Every improvement is sent as it is found (the last one sent is the
    result when the process is killed at its deadline), then the final result."""
    def send(d):
        try:
            conn.send(d)
        except Exception:                               # noqa: BLE001
            pass
    try:
        from . import driver
        res = driver.run(Path(stl), Path(work), emit=send, deadline=time.perf_counter() + 0.9 * float(seconds))
    except BaseException as e:                         # noqa: BLE001
        res = {"error": f"{type(e).__name__}: {e}"[:300], "final": True}
    send(res)
    conn.close()


def _entry(runner, parent_pid, *args):                 # pragma: no cover - runs in the child process
    """The child's entry: end with the parent (a killed kernel worker leaves no CADFit search running), then run."""
    import threading

    def watch():
        while True:
            time.sleep(1.0)
            if os.getppid() != parent_pid:
                os._exit(1)
    threading.Thread(target=watch, daemon=True).start()
    try:
        os.dup2(2, 1)                                   # stdout may be an MCP stdio channel: never write to it
    except OSError:
        pass
    (runner or _child)(*args)


def _search(V, F, seconds: float, runner=None) -> dict:
    """CADFit's search in a child process, killed at `seconds` (a hard deadline). Returns the last result the child
    sent (its best program so far when it was killed, with "timed_out") plus "seconds"."""
    import multiprocessing as mp

    t0 = time.perf_counter()
    end = t0 + max(0.0, float(seconds))
    work = Path(tempfile.mkdtemp(prefix="form-cadfit-"))
    p = None
    try:
        stl = work / "part.stl"
        _write_stl(stl, V, F)
        from ..bounded import _children_allowed
        ctx = mp.get_context("spawn")                   # as form/recon/bounded.py: never a fork (macOS, OCCT threads)
        a, b = ctx.Pipe(duplex=False)
        # the kernel worker that runs a reconstruction is a daemon, and multiprocessing refuses children of a daemon:
        # the child is a daemon itself and watches its parent (_entry), so lifting the rule for the start is safe
        with _children_allowed():
            p = ctx.Process(target=_entry, args=(runner, os.getpid(), b, str(stl), str(work / "run"), float(seconds)),
                            daemon=True, name="form-cadfit")
            p.start()
        b.close()
        res = None
        while True:
            wait = end - time.perf_counter()
            if wait <= 0 or not a.poll(wait):
                break
            try:
                msg = a.recv()
            except (EOFError, OSError):
                break
            if isinstance(msg, dict):
                res = msg
                if msg.get("final"):
                    break
        timed_out = p.is_alive() and not (res or {}).get("final")
        if p.is_alive():
            p.kill()
        p.join(5)
        if res is None:
            res = ({"error": f"CADFit found nothing within its {seconds:.0f} s"} if timed_out else
                   {"error": f"the CADFit process ended without a result (exit code {p.exitcode})"})
        res = dict(res)
        if timed_out:
            res["timed_out"] = True
        res["seconds"] = round(time.perf_counter() - t0, 2)
        return res
    finally:
        if p is not None and p.is_alive():
            p.kill()
        shutil.rmtree(work, ignore_errors=True)


def _write_stl(path, V, F):
    """A binary STL of (V, F), with no library."""
    import struct

    import numpy as np
    V, F = np.asarray(V, dtype=float), np.asarray(F, dtype=np.int64)
    T = V[F]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    rec = np.zeros(len(F), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, T
    with open(path, "wb") as f:
        f.write(b"Form Studio CADFit input".ljust(80, b" "))
        f.write(struct.pack("<I", len(F)))
        f.write(rec.tobytes())


def plan(script: str):
    """CADFit's program (CadQuery text) as the learned engine's plan (learned/cq.Solid): extrusions joined by union and
    cut. A revolve is refused (Unsupported): it has no translation to Params yet."""
    import numpy as np
    from ..learned import cq
    from . import cqrun
    op = cqrun.program(script)

    def items(loops):
        from ._compat import _inside
        order = sorted(range(len(loops)), key=lambda i: -loops[i].area())
        pts = [lp.points() for lp in loops]
        depth = {}
        for k, i in enumerate(order):
            depth[i] = sum(1 for j in order[:k] if _inside(pts[j], pts[i]).mean() > 0.9)
        out = []
        for i in order:
            lp, mode = loops[i], ("s" if depth[i] % 2 else "a")
            if lp.circle is not None:
                out.append(cq.Item("circle", mode=mode, c=(lp.circle[0], lp.circle[1]), r=lp.circle[2]))
            else:
                out.append(cq.Item("path", mode=mode, segs=[tuple(s) for s in lp.segs]))
        return out

    def walk(o):
        t = o.node
        if t[0] == "extrude":
            pl, loops, h = t[1], t[2], t[3]
            return cq.Solid(("extrude", cq.Extrude(cq.Plane(np.asarray(pl.origin, float), np.asarray(pl.x, float),
                                                            np.asarray(pl.n, float)), items(loops), min(0.0, h),
                                                   max(0.0, h))))
        if t[0] == "revolve":
            raise cq.Unsupported("CADFit's program has a revolve, which is not translated to Params yet")
        return cq.Solid(("union" if t[0] in ("add", "union") else "cut", walk(t[1]), walk(t[2])))
    return walk(op)


MIN_RUN_S = 3.0               # less time than this left before the reconstruction's hard deadline: CADFit is not started


def candidate(mesh, budget_s: float, tol: float = 0.02, name: str = "part", limit=None, search=None,
              left_s: float | None = None) -> dict:
    """One more reconstruction candidate from CADFit, within its fixed slice of `budget_s` (seconds_for), built and
    verified like the program route's. `mesh` is (V, F). Returns the shape of program.recipe: {"report", "source",
    "verified", "shape", "P", "T", "cmp", "refs", "params"}; the report always says why a candidate was not verified.
    `search(V, F, seconds)` replaces the child-process search (tests). `left_s` is the time left before the
    reconstruction's hard deadline: the slice never exceeds it (its minimum included). Never raises."""
    import numpy as np
    t0 = time.perf_counter()
    V, F = (np.asarray(mesh[0], dtype=float), np.asarray(mesh[1]))
    limit = tol if limit is None else limit
    secs = seconds_for(budget_s)
    if left_s is not None:
        secs = max(0.0, min(secs, float(left_s)))
    rep = {"method": f"{NAME} (IoU search over extrusions and revolves)", "engine": NAME, "licence": LICENCE,
           "commit": COMMIT, "seconds_allowed": round(secs, 1)}

    def done(**k):
        rep.update(k)
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep, "verified": False}
    try:
        st = status()
        if search is None and not st.get("bundled", True):
            return done(error="CADFit is not part of this build of Form Studio: it needs form-studio[cadfit] "
                              "(run Form Studio from source with pip install form-studio[cadfit])")
        if search is None and not st["installed"]:
            return done(error=f"CADFit needs {', '.join(st['missing_libraries'])}: it needs form-studio[cadfit] "
                              "(pip install form-studio[cadfit])")
        if secs < MIN_RUN_S:
            return done(error=f"CADFit was not started: {secs:.1f} s were left before the reconstruction's deadline",
                        timed_out=True)
        got = (search or _search)(V, F, secs)
    except Exception as e:                              # noqa: BLE001
        return done(error=f"CADFit did not run: {type(e).__name__}: {e}"[:300])
    rep["search_seconds"] = got.get("seconds")
    for k in ("iou", "steps", "passes", "timed_out"):
        if got.get(k) is not None:
            rep[k if k != "iou" else "cadfit_iou"] = got[k]
    if not got.get("script"):
        return done(error=got.get("error") or "CADFit returned no program")
    if got.get("iou") is not None and float(got["iou"]) < MIN_IOU:
        return done(error=f"CADFit's best program overlaps the mesh by IoU {float(got['iou']):.3f}; below {MIN_IOU:g} it "
                          "cannot be within the tolerance, so it was not translated or verified")
    from ..learned import cq, translate
    try:
        pl = plan(got["script"])
        lo, hi = V.min(axis=0), V.max(axis=0)          # CADFit's normalisation (iou.normalize_mesh), undone exactly
        md = float((hi - lo).max())
        src, info = translate.source(pl, V, tol, name=name, place=(md / 2.0, (lo + hi) / 2.0), engine=ENGINE_TEXT)
    except cq.Unsupported as e:
        return done(error=f"CADFit's program could not be read as sketch extrusions: {e}"[:300])
    except Exception as e:                              # noqa: BLE001
        return done(error=f"CADFit's program could not be placed on the mesh: {type(e).__name__}: {e}"[:300])
    pool = info.pop("_pool")
    rep.update({k: (round(v, 6) if isinstance(v, float) else v) for k, v in info.items()})
    from .. import program, solid, verify
    try:
        stages, _ = program.build_stages(src)
        shape = stages[-1].shape
        ck = solid.check(shape.wrapped)
        fl = []
        P, T = solid.tessellate(shape, max(tol / 10, 1e-4), faces_out=fl)
        diag = float(np.linalg.norm(np.ptp(V, axis=0)))
        cmp = verify.compare(V, F, P, T, spacing=max(diag / 200, 1e-3), shape=shape.wrapped, check_above=limit, faces=fl)
    except Exception as e:                              # noqa: BLE001
        rep["error"] = f"The translated recipe did not build: {type(e).__name__}: {e}"[:300]
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep, "verified": False, "source": src}
    ok = bool(ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit)
    rep.update({"kind": "cadfit", "base": "sketches and extrusions", "valid": ck["valid"], "solids": ck["solids"],
                "volume_mm3": round(ck["volume_mm3"], 4), "verified": ok,
                # every face of the result is made by a feature: no part of it is kept as the mesh
                "editable_pct": 100.0 if ok else 0.0, "driven_by_params_pct": 100.0 if ok else 0.0,
                "params": len(pool.params), "param_table": [dict(q) for q in pool.params],
                **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")}})
    if not ok:
        rep["error"] = (f"The CADFit candidate is {cmp['hausdorff_mm']:.4f} mm from the mesh (limit {limit:.4f} mm)"
                        if ck["valid"] and ck["solids"] == 1 else
                        f"The CADFit candidate is not one valid solid ({ck['solids']} solids, valid {ck['valid']}).")
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    return {"report": rep, "source": src, "verified": ok, "shape": shape.wrapped, "P": P, "T": T, "cmp": cmp,
            "refs": {}, "params": pool.params}


REPORT_KEYS = ("engine", "verified", "hausdorff_mm", "params", "cadfit_iou", "search_seconds", "seconds", "timed_out",
               "error")


def offer(prog, V, F, tol, name, say, budget_s, rep, better, left_s: float | None = None):
    """The pipeline's hook (pipeline.py): when enabled, CADFit's candidate beside the program route's `prog`; it
    replaces `prog` only when it verifies and `better(candidate, prog)`. Disabled: returns `prog` and touches nothing.
    `left_s`: seconds left before the reconstruction's hard deadline."""
    if not enabled():
        return prog
    say({"stage": "layer2", "text": "Searching for a CAD program with CADFit", "fraction": 0.35})
    c = candidate((V, F), budget_s, tol=tol, name=name, limit=tol, left_s=left_s)
    rep["cadfit"] = {"status": "enabled", **{k: c["report"].get(k) for k in REPORT_KEYS
                                             if c["report"].get(k) is not None}}
    if c.get("verified") and better(c, prog):
        c["report"]["also_tried"] = [{k: prog["report"].get(k) for k in (
            "method", "verified", "hausdorff_mm", "editable_pct", "error") if prog["report"].get(k) is not None}]
        rep["cadfit"]["chosen"] = True
        return c
    return prog
