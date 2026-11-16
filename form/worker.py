"""Kernel worker process and its supervisor.

The server never imports OCCT. It talks to one long-lived worker over a pipe;
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
            conn.send(("ok", kernel.OPS[op](**kwargs)))
        except RecipeError as e:
            conn.send(("recipe_error", e.public()))
        except Exception as e:  # report, keep serving
            conn.send(("error", {"message": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}))


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

    def call(self, op: str, timeout: float = 60, **kwargs):
        with self._lock:
            if self._proc is None or not self._proc.is_alive():
                self._start()
            try:
                self._conn.send((op, kwargs))
                if not self._conn.poll(timeout):
                    self._kill(f"{op} exceeded {timeout:g} s")
                    raise KernelFailure({"kind": "timeout", "message": f"The geometry kernel did not answer within {timeout:g} s and was restarted.",
                                         "hint": "Nothing was saved from that attempt. Your last committed revision is intact."})
                status, payload = self._conn.recv()
            except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
                self._kill(f"{op} crashed the kernel process")
                raise KernelFailure({"kind": "crash", "message": "The geometry kernel stopped unexpectedly and was restarted.",
                                     "hint": "Nothing was saved from that attempt. Your last committed revision is intact."})
        if status == "ok":
            return payload
        payload["kind"] = "recipe" if status == "recipe_error" else "internal"
        raise KernelFailure(payload)

    def stop(self):
        with self._lock:
            if self._proc and self._proc.is_alive():
                self._proc.kill()
            self._proc = self._conn = None
