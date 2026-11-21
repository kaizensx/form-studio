"""Kernel worker process and its supervisor.

The server never imports OCCT. It talks to long-lived workers over pipes (a KernelPool of them);
a timeout or crash kills the worker and the next call starts a fresh one.
"""
from __future__ import annotations

import multiprocessing as mp
import threading
import time
import traceback


class KernelFailure(Exception):
    def __init__(self, info: dict):
        super().__init__(info.get("message", "kernel failure"))
        self.info = info


def _serve(conn):
    import os
    try:
        os.dup2(2, 1)       # stdout may be an MCP stdio channel; the kernel must never write to it
    except OSError:
        pass
    from . import kernel
    from .recipes import RecipeError
    while True:
        try:
            msg = conn.recv()
        except (EOFError, KeyboardInterrupt):
            return
        op, kwargs = msg
        try:
            from .recipes import meshsolid                 # imported parts a design may read with self.reference()
            meshsolid.set_paths(kwargs.pop("_refs", None))
            from . import marks                            # label text, revision and nozzle for designs with marks
            marks.set_context(kwargs.pop("_mark", None))
            prog = kwargs.pop("_progress", False)            # True: stage meshes too; "events": feature events only
            kernel.PROGRESS = (lambda d: conn.send(("progress", d))) if prog else None
            kernel.PROGRESS_MESH = prog is True
            from . import featureprog                     # feature budgets stretch with the call's timeout under load
            featureprog.STRETCH = float(kwargs.pop("_stretch", 1.0) or 1.0)
            conn.send(("ok", kernel.OPS[op](**kwargs)))
        except RecipeError as e:
            conn.send(("recipe_error", e.public()))
        except Exception as e:  # report, keep serving
            conn.send(("error", {"message": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}))


FEATURE_GRACE = 10.0       # a feature still running this long past its budget is a hang in C++: stop the kernel


def _mark_hang(running: dict | None, info: dict) -> None:
    """Write down the feature that hung or crashed the kernel (form/featureprog.py hang_path), so its next build
    leaves it out at once."""
    f = (running or {}).get("hang_file")
    if not f:
        return
    import json
    import os
    try:
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({**{k: info[k] for k in ("feature", "s", "budget", "kind") if k in info}, "ts": time.time()}, fh)
        os.replace(tmp, f)
    except OSError:
        pass


class Kernel:
    def __init__(self):
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._proc = None
        self._conn = None
        self.restarts = 0
        self.last_failure = None

    def _start(self):
        parent, child = self._ctx.Pipe()
        self._proc = self._ctx.Process(target=_serve, args=(child,), daemon=True, name="form-kernel")
        self._proc.start()
        child.close()
        self._conn = parent

    def _kill(self, why: str):
        self.restarts += 1
        self.last_failure = {"when": time.time(), "why": why}
        try:
            if self._proc and self._proc.is_alive():
                self._proc.kill()
                self._proc.join(2)
        finally:
            self._proc = self._conn = None

    def call(self, op: str, timeout: float = 60, on_progress=None, **kwargs):
        """Run one kernel op. timeout covers the whole call; on_progress(dict) receives the op's progress reports."""
        with self._lock:
            if self._proc is None or not self._proc.is_alive():
                self._start()
            try:
                if on_progress is not None:
                    kwargs.setdefault("_progress", True)
                else:
                    kwargs.pop("_progress", None)
                self._conn.send((op, kwargs))
                end = time.monotonic() + timeout
                running = None                         # the feature the kernel is building now (featureprog events)
                fdead = None                           # when that feature is past its budget and the grace
                while True:
                    lim = end if fdead is None else min(end, fdead)
                    if not self._conn.poll(max(0.0, lim - time.monotonic())):
                        now = time.monotonic()
                        hang = None
                        if running is not None:
                            hang = {"feature": running.get("feature", ""), "s": round(now - running["t"], 1),
                                    "budget": running.get("budget"), "i": running.get("i"), "kind": "kill"}
                            _mark_hang(running, hang)
                        if hang is not None and fdead is not None and fdead <= end:
                            self._kill(f"{op}: feature {hang['feature']} ran {hang['s']:g} s, past its "
                                       f"{hang['budget']} s budget")
                            msg = (f"Feature {hang['feature']} did not finish: the geometry kernel was stopped after "
                                   f"{hang['s']:g} s (its budget is {hang['budget']} s) and restarted.")
                        else:
                            self._kill(f"{op} exceeded {timeout:g} s")
                            msg = f"The geometry kernel did not answer within {timeout:g} s and was restarted." + \
                                (f" It was building {hang['feature']} ({hang['s']:g} s on it)." if hang else "")
                        raise KernelFailure({"kind": "timeout", "message": msg,
                                             "hint": "Nothing was saved from that attempt. Your last committed revision is intact.",
                                             **({"feature": hang["feature"], "hang": hang} if hang else {})})
                    status, payload = self._conn.recv()
                    if status != "progress":
                        break
                    if isinstance(payload, dict) and payload.get("kind") == "feature_start":
                        running = {**payload, "t": time.monotonic()}
                        b = payload.get("budget")
                        fdead = running["t"] + float(b) + max(FEATURE_GRACE, 0.25 * float(b)) \
                            if isinstance(b, (int, float)) and b > 0 else None
                    elif isinstance(payload, dict) and payload.get("kind") == "feature_done":
                        running = fdead = None
                    if on_progress is not None:
                        try:
                            on_progress(payload)
                        except Exception:
                            pass
            except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
                self._kill(f"{op} crashed the kernel process")
                r = locals().get("running")
                hang = None
                if r:
                    hang = {"feature": r.get("feature", ""), "s": round(time.monotonic() - r["t"], 1),
                            "budget": r.get("budget"), "i": r.get("i"), "kind": "crash"}
                    _mark_hang(r, hang)
                raise KernelFailure({"kind": "crash", "message": "The geometry kernel stopped unexpectedly and was restarted."
                                     + (f" It was building {hang['feature']} ({hang['s']:g} s on it)." if hang else ""),
                                     "hint": "Nothing was saved from that attempt. Your last committed revision is intact.",
                                     **({"feature": hang["feature"], "hang": hang} if hang else {})})
        if status == "ok":
            return payload
        payload["kind"] = "recipe" if status == "recipe_error" else "internal"
        raise KernelFailure(payload)

    def stop(self):
        """End the worker now, also while a call is waiting on it (that call then fails as a crash). Never waits for
        the lock: at exit the warm-up ping can hold it for as long as the CAD kernel takes to import."""
        proc = self._proc
        if proc is not None and proc.is_alive():
            proc.kill()
            proc.join(5)
        if self._lock.acquire(timeout=1):
            try:
                if self._proc is proc:
                    self._proc = self._conn = None
            finally:
                self._lock.release()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()


def default_workers(cfg: dict | None = None) -> int:
    """How many kernel processes may run at once: FORM_KERNEL_WORKERS, or [kernel] workers in studio.toml, else one
    per performance core up to 4 (each worker holds its own OCCT and model cache, a few hundred MB)."""
    import os
    for v in (os.environ.get("FORM_KERNEL_WORKERS"), ((cfg or {}).get("kernel") or {}).get("workers")):
        try:
            if v not in (None, "", "auto"):
                return max(1, min(16, int(v)))
        except (TypeError, ValueError):
            pass
    n = 0
    try:                                                   # macOS: performance cores, not the efficiency ones
        import subprocess
        out = subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"], capture_output=True, text=True, timeout=2)
        n = int(out.stdout.strip() or 0)
    except Exception:
        n = 0
    if n <= 0:
        n = (os.cpu_count() or 2) // 2
    return max(1, min(4, n))


LOAD_STRETCH = 0.35        # extra share of a timeout per other busy worker: a helmet exemplar builds in 163 s alone
                           # and 268 s with four workers busy (+21% per extra worker); 0.35 leaves a margin over that


def scaled_timeout(timeout: float, busy: int, size: int = 4, load: float | None = None) -> float:
    """A kernel call's timeout under load. busy: workers of this pool running now, this call included. load: the
    machine's one-minute load average (default: read it), which also counts the other pools (each MCP server runs
    its own) and other programs. The quiet-machine timeout is stretched by LOAD_STRETCH for every other worker that
    competes for the cores, up to 3 others."""
    import os
    others = max(0, int(busy) - 1)
    try:
        load = os.getloadavg()[0] if load is None else float(load)
        per = max(1.0, (os.cpu_count() or 4) / max(1, size))  # cores a worker has when the pool is full
        others = max(others, int(load / per) - 1)
    except (OSError, AttributeError, ValueError):
        pass
    return float(timeout) * (1.0 + LOAD_STRETCH * min(3, others))


class KernelPool:
    """Several kernel workers, so independent builds run at the same time instead of queueing behind one process.

    Same interface as Kernel (call, stop, restarts, last_failure). A call goes to an idle worker; a call with a `key`
    (a built model's cache key) prefers the worker that built that key last, because each worker keeps its own cache
    of built models: a view followed by a summary, a selection or an export of the same design does not build it
    twice. Workers start on demand, so one call at a time never starts more than one. A worker that times out or
    crashes is restarted on its own; the others keep their caches."""

    AFFINITY = 64                                      # keys remembered per worker

    def __init__(self, size: int | None = None, cfg: dict | None = None):
        self.size = size or default_workers(cfg)
        self._cv = threading.Condition()
        self._workers: list[Kernel] = []
        self._busy: set[int] = set()
        self._keys: list[list[str]] = []

    @property
    def restarts(self) -> int:
        return sum(w.restarts for w in self._workers)

    @property
    def last_failure(self):
        fails = [w.last_failure for w in self._workers if w.last_failure]
        return max(fails, key=lambda f: f["when"]) if fails else None

    def status(self) -> dict:
        with self._cv:
            return {"size": self.size, "started": sum(1 for w in self._workers if w.alive()), "busy": len(self._busy),
                    "restarts": self.restarts}

    def _add(self) -> int:
        self._workers.append(Kernel())
        self._keys.append([])
        return len(self._workers) - 1

    def _pick(self, key: str | None) -> int:
        """Index of the worker for this call, marked busy; waits while every worker is busy."""
        with self._cv:
            while True:
                idle = [i for i in range(len(self._workers)) if i not in self._busy]
                own = [i for i, ks in enumerate(self._keys) if key and key in ks]
                if own and own[-1] in idle:
                    i = own[-1]
                    break
                if own and not idle and len(self._workers) >= self.size:
                    self._cv.wait()                    # the worker that has it is busy, and so is every other
                    continue
                warm = [j for j in idle if self._workers[j].alive()]
                if warm:                               # an idle worker that is already running
                    i = warm[0]
                    break
                if len(self._workers) < self.size:
                    i = self._add()
                    break
                if idle:
                    i = idle[0]
                    break
                self._cv.wait()
            self._busy.add(i)
            if key:
                ks = self._keys[i]
                if key in ks:
                    ks.remove(key)
                ks.append(key)
                del ks[:-self.AFFINITY]
            return i

    def _done(self, i: int) -> None:
        with self._cv:
            self._busy.discard(i)
            self._cv.notify_all()

    def call(self, op: str, timeout: float = 60, on_progress=None, **kwargs):
        """Run one kernel op on a free worker (see Kernel.call). The timeout is the time the op needs on a quiet
        machine; it is stretched by how many workers are busy at the same time (scaled_timeout), so a heavy build
        does not time out only because three others run beside it."""
        key = kwargs.get("key") if isinstance(kwargs.get("key"), str) else None
        i = self._pick(key)
        with self._cv:
            busy = len(self._busy)
        stretch = scaled_timeout(1.0, busy, self.size)
        if stretch > 1.0:
            kwargs["_stretch"] = stretch               # feature budgets in the worker stretch the same way
        try:
            return self._workers[i].call(op, timeout=timeout * stretch, on_progress=on_progress, **kwargs)
        except KernelFailure as e:
            if e.info.get("kind") in ("timeout", "crash"):
                with self._cv:
                    self._keys[i].clear()          # the restarted worker starts with an empty cache
            raise
        finally:
            self._done(i)

    def warm(self, n: int | None = None, timeout: float = 120) -> int:
        """Start up to n workers (default: all) at once, so a batch of builds does not pay for the CAD kernel's import
        one worker after another. Returns how many are running."""
        n = min(self.size, n or self.size)
        with self._cv:
            while len(self._workers) < n:
                self._add()
            cold = [i for i in range(n) if i not in self._busy and not self._workers[i].alive()]
            self._busy.update(cold)

        def ping(i):
            try:
                self._workers[i].call("ping", timeout=timeout)
            except Exception:
                pass
            finally:
                self._done(i)
        ts = [threading.Thread(target=ping, args=(i,), daemon=True, name=f"form-kernel-warm-{i}") for i in cold]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout + 5)
        return sum(1 for w in self._workers if w.alive())

    def map(self, op: str, calls: list[dict], timeout: float = 120) -> list:
        """Run op once per kwargs dict in calls, in parallel over the pool; results in order. A failed call's slot
        holds its KernelFailure (returned, not raised: the caller decides what a failure means)."""
        from concurrent.futures import ThreadPoolExecutor
        out: list = [None] * len(calls)

        def one(j):
            try:
                out[j] = self.call(op, timeout=timeout, **calls[j])
            except KernelFailure as e:
                out[j] = e
        if calls:
            with ThreadPoolExecutor(max_workers=max(1, min(self.size, len(calls)))) as ex:
                list(ex.map(one, range(len(calls))))
        return out

    def stop(self):
        """End every worker now (calls still waiting on one fail as a crash); the next call starts fresh ones."""
        for w in list(self._workers):
            try:
                w.stop()
            except Exception:
                pass
        with self._cv:
            self._keys = [[] for _ in self._workers]
            self._cv.notify_all()
