"""Run steps of the reconstruction in a helper process with a hard time limit.

OpenCascade calls cannot be interrupted: one sewing or one defeaturing can run for minutes (or crash the process),
and nothing in Python can stop it. A step that must not outlive the reconstruction's budget runs in a helper
process instead, and the helper is killed when the step's time is up. The parent then knows exactly what was cut
short and goes on with what it has.

The helper is started the way the CAD kernel worker is (form/worker.py): a multiprocessing "spawn" process, which
works from source and in the packaged app alike (packaging/entry.py calls freeze_support). Never a fork: on macOS a
fork deadlocks once numpy's and OpenCascade's threads exist. One warm helper serves every step of a reconstruction
(`session()`): it is started at the beginning, imports the CAD kernel while the mesh is read, and is replaced only
after a step it ran was stopped or crashed. Inputs and results travel as pickles with shapes as BRep text.

    with session():
        out = run(fn, args, kwargs, timeout_s, progress)   ->  {"status": "ok" | "timeout" | "crash" | "error",
                                                                 "value", "seconds", "error"}

`fn` must be a module-level function that takes `progress=`. With FORM_RECON_BOUNDED=0 a step runs in this process
without a limit, and says so ("unbounded").
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import os
import pickle
import threading
import time
import traceback


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


def _dumps(obj) -> bytes:
    buf = io.BytesIO()
    _Pickler(buf, protocol=pickle.HIGHEST_PROTOCOL).dump(obj)
    return buf.getvalue()


def available() -> bool:
    return os.environ.get("FORM_RECON_BOUNDED", "1") != "0"


@contextlib.contextmanager
def _children_allowed():
    """The CAD kernel worker is a daemon process, and multiprocessing refuses children of a daemon. The helper is
    made a daemon itself (it ends with the worker) and watches its parent, so lifting the rule here is safe."""
    cp = mp.current_process()
    was = cp._config.get("daemon")
    cp._config["daemon"] = False
    try:
        yield
    finally:
        if was is None:
            cp._config.pop("daemon", None)
        else:
            cp._config["daemon"] = was


def _serve(conn, parent_pid):
    """The helper: run each step it is sent, report progress as it goes, until the pipe closes."""
    try:
        os.dup2(2, 1)                                   # stdout may be an MCP stdio channel: never write to it
    except OSError:
        pass

    def watch():                                        # the parent was killed: so is this
        while True:
            time.sleep(1.0)
            if os.getppid() != parent_pid:
                os._exit(1)
    threading.Thread(target=watch, daemon=True).start()
    try:
        import build123d  # noqa: F401                  # warm: the first step does not wait for the kernel import
    except Exception:                                   # noqa: BLE001
        pass
    import importlib
    while True:
        try:
            job = pickle.loads(conn.recv_bytes())
        except (EOFError, OSError, KeyboardInterrupt):
            return

        def say(d):
            try:
                conn.send_bytes(_dumps(("progress", d)))
            except Exception:                           # noqa: BLE001
                pass
        try:
            fn = getattr(importlib.import_module(job["module"]), job["name"])
            out = ("ok", fn(*job["args"], **job["kwargs"], progress=say))
        except Exception as e:                          # noqa: BLE001
            out = ("error", f"{type(e).__name__}: {e}"[:300] + "\n" + traceback.format_exc()[-1500:])
        try:
            conn.send_bytes(_dumps(out))
        except Exception as e:                          # noqa: BLE001
            conn.send_bytes(_dumps(("error", f"the result could not be sent back: {type(e).__name__}: {e}"[:300])))


class Helper:
    """One warm helper process; replaced after a step it ran was stopped or crashed."""

    def __init__(self):
        self.ctx = mp.get_context("spawn")
        self.proc = self.conn = None

    def start(self):
        if self.proc is not None and self.proc.is_alive():
            return
        parent, child = self.ctx.Pipe()
        with _children_allowed():
            self.proc = self.ctx.Process(target=_serve, args=(child, os.getpid()), daemon=True, name="form-recon")
            self.proc.start()
        child.close()
        self.conn = parent

    def kill(self):
        proc, self.proc, conn, self.conn = self.proc, None, self.conn, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if proc is not None and proc.is_alive():
            proc.kill()
            proc.join(5)

    def run(self, fn, args, kwargs, timeout_s, progress) -> dict:
        t0 = time.perf_counter()
        self.start()
        try:
            self.conn.send_bytes(_dumps({"module": fn.__module__, "name": fn.__name__, "args": args, "kwargs": kwargs}))
            while True:
                left = t0 + timeout_s - time.perf_counter()
                if left <= 0:
                    self.kill()
                    return {"status": "timeout", "seconds": round(time.perf_counter() - t0, 2),
                            "error": f"was stopped after {timeout_s:.0f} s (the time budget)"}
                if not self.conn.poll(min(0.25, left)):
                    if not self.proc.is_alive():
                        raise EOFError
                    continue
                kind, val = pickle.loads(self.conn.recv_bytes())
                if kind == "progress":
                    if progress is not None:
                        try:
                            progress(val)
                        except Exception:               # noqa: BLE001
                            pass
                    continue
                secs = round(time.perf_counter() - t0, 2)
                if kind == "error":
                    return {"status": "error", "seconds": secs, "error": val}
                return {"status": "ok", "value": val, "seconds": secs}
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
            code = self.proc.exitcode if self.proc is not None else None
            self.kill()
            why = f"crashed (signal {-code})" if isinstance(code, int) and code < 0 else f"stopped (exit code {code})"
            return {"status": "crash", "seconds": round(time.perf_counter() - t0, 2), "error": why}


_local = threading.local()


@contextlib.contextmanager
def session():
    """One warm helper for every bounded step inside; started now, ended on leaving."""
    if not available():
        yield None
        return
    h = Helper()
    h.start()
    prev = getattr(_local, "helper", None)
    _local.helper = h
    try:
        yield h
    finally:
        _local.helper = prev
        h.kill()


def run(fn, args=(), kwargs=None, timeout_s: float = 60.0, progress=None) -> dict:
    """fn(*args, **kwargs, progress=...) in the session's helper (or a helper of its own), stopped after timeout_s."""
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
    h = getattr(_local, "helper", None)
    if h is not None:
        return h.run(fn, args, kwargs, timeout_s, progress)
    h = Helper()
    try:
        return h.run(fn, args, kwargs, timeout_s, progress)
    finally:
        h.kill()
