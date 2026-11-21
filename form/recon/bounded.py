"""Run one step of the reconstruction in a child process with a hard time limit.

OpenCascade calls cannot be interrupted: one sewing or one defeaturing can run for minutes (or crash the process),
and nothing in Python can stop it. A step that must not outlive the reconstruction's budget runs here instead: in a
fresh child process (`python -m form.recon.bounded`; not a fork, which deadlocks on macOS once numpy's and
OpenCascade's threads exist) that gets its inputs as a pickle (shapes as BRep text), sends its progress back line by
line and its result as a pickle, and is killed when its time is up. The parent then knows exactly what was cut short
and goes on with what it has.

    out = run(fn, args, kwargs, timeout_s, progress)    ->  {"status": "ok" | "timeout" | "crash" | "error",
                                                              "value", "seconds", "error"}

`fn` must be a module-level function that takes `progress=`. In a packaged app (no Python to start) or with
FORM_RECON_BOUNDED=0 the step runs in this process without a limit, and says so ("unbounded").
"""
from __future__ import annotations

import io
import json
import os
import pickle
import select
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _shape_from_brep(text: str):
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    sh = TopoDS_Shape()
    BRepTools.Read_s(sh, io.BytesIO(text.encode("latin-1")), BRep_Builder())
    return sh


def _b3d_from_brep(text: str):
    from build123d import Shape
    return Shape.cast(_shape_from_brep(text))


def _brep(shape) -> str:
    from OCP.BRepTools import BRepTools
    buf = io.BytesIO()
    BRepTools.Write_s(shape, buf)
    return buf.getvalue().decode("latin-1")


class _Pickler(pickle.Pickler):
    """Pickles shapes as BRep text; any other OCP object (a Geom surface cached on a fit) becomes None."""

    def reducer_override(self, obj):
        mod = type(obj).__module__ or ""
        if mod.startswith("build123d") and getattr(obj, "wrapped", None) is not None and hasattr(obj, "is_valid"):
            return _b3d_from_brep, (_brep(obj.wrapped),)
        if not mod.startswith("OCP"):
            return NotImplemented
        from OCP.TopoDS import TopoDS_Shape
        if isinstance(obj, TopoDS_Shape):
            return _shape_from_brep, (_brep(obj),)
        return type(None), ()


def _dump(obj, path):
    with open(path, "wb") as f:
        _Pickler(f, protocol=pickle.HIGHEST_PROTOCOL).dump(obj)


def available() -> bool:
    return not getattr(sys, "frozen", False) and os.environ.get("FORM_RECON_BOUNDED", "1") != "0"


def run(fn, args=(), kwargs=None, timeout_s: float = 60.0, progress=None) -> dict:
    """fn(*args, **kwargs, progress=...) in a child process, stopped after timeout_s seconds."""
    kwargs = dict(kwargs or {})
    t0 = time.perf_counter()
    if not available():
        try:
            return {"status": "unbounded", "value": fn(*args, **kwargs, progress=progress),
                    "seconds": round(time.perf_counter() - t0, 2)}
        except Exception as e:                          # noqa: BLE001
            return {"status": "error", "error": f"{type(e).__name__}: {e}"[:300], "seconds": round(time.perf_counter() - t0, 2)}
    if timeout_s <= 0:
        return {"status": "timeout", "seconds": 0.0, "error": "had no time left in the budget"}
    td = Path(tempfile.mkdtemp(prefix="form-recon-"))
    src, dst = td / "in.pickle", td / "out.pickle"
    try:
        _dump({"module": fn.__module__, "name": fn.__name__, "args": args, "kwargs": kwargs}, src)
        env = dict(os.environ)
        root = str(Path(__file__).resolve().parents[2])          # the folder holding the `form` package
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        proc = subprocess.Popen([sys.executable, "-m", "form.recon.bounded", str(src), str(dst)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        fd = proc.stdout.fileno()
        buf = b""
        while True:
            left = t0 + timeout_s - time.perf_counter()
            if left <= 0:
                proc.kill()
                proc.wait()
                proc.stdout.close()
                return {"status": "timeout", "seconds": round(time.perf_counter() - t0, 2),
                        "error": f"was stopped after {timeout_s:.0f} s (the time budget)"}
            ready, _, _ = select.select([fd], [], [], min(0.25, left))
            if ready:
                chunk = os.read(fd, 65536)
                if chunk:
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for ln in lines:
                        if progress is not None and ln.startswith(b"{"):
                            try:
                                progress(json.loads(ln))
                            except Exception:           # noqa: BLE001
                                pass
                elif proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break
        proc.wait()
        proc.stdout.close()
        secs = round(time.perf_counter() - t0, 2)
        if proc.returncode < 0:
            return {"status": "crash", "seconds": secs, "error": f"crashed (signal {-proc.returncode})"}
        if proc.returncode != 0 or not dst.exists():
            return {"status": "crash", "seconds": secs, "error": f"exited with code {proc.returncode}"}
        with open(dst, "rb") as f:
            got = pickle.load(f)
        if got["error"]:
            return {"status": "error", "seconds": secs, "error": got["error"]}
        return {"status": "ok", "value": got["value"], "seconds": secs}
    finally:
        for p in (src, dst):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            td.rmdir()
        except OSError:
            pass


def _child(src: str, dst: str) -> int:
    import importlib
    with open(src, "rb") as f:
        job = pickle.load(f)
    out = sys.stdout

    def say(d):
        try:
            out.write(json.dumps(d, default=str) + "\n")
            out.flush()
        except Exception:                               # noqa: BLE001
            pass
    try:
        fn = getattr(importlib.import_module(job["module"]), job["name"])
        val, err = fn(*job["args"], **job["kwargs"], progress=say), None
    except Exception as e:                              # noqa: BLE001
        val, err = None, f"{type(e).__name__}: {e}"[:300] + "\n" + traceback.format_exc()[-1500:]
    _dump({"value": val, "error": err}, dst)
    return 0


if __name__ == "__main__":
    from form.recon import bounded as _self             # the module by its name, so the pickles name it so too
    sys.exit(_self._child(sys.argv[1], sys.argv[2]))
