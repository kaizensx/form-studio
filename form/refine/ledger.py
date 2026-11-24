"""The refinement ledger: what each operator did on this machine, so the search tries the ones that work first.

    led = ledger.Ledger.open()                     # <data dir>/refine_ledger.json
    led.prior("mouse", "clean_consumer", "parting_line")   # 1.0 untried; > 1 it tends to help; < 1 it rarely does
    led.record("mouse", "clean_consumer", "parting_line", accepted=True, gain=0.06)
    led.save(); led.reset()

Per (product class, style, operator): tries, accepts and the mean gain of the accepted tries. The prior is a smoothed
acceptance rate times a smoothed gain, relative to an untried operator (both with pseudo-counts, so one lucky or
unlucky try moves it a little, many tries move it a lot), bounded to 0.25-2.5. The file stays in the local data
directory: it is never uploaded, never part of a project, and reset() (the settings' reset control) empties it.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

FILE = "refine_ledger.json"
VERSION = 1
PRIOR_ACCEPT = 0.3                 # assumed acceptance rate of an untried operator
PRIOR_GAIN = 0.03                  # assumed mean gain (deficit total) of an accepted try
K = 4.0                            # pseudo-tries behind the assumed values
BOUNDS = (0.25, 2.5)
_lock = threading.Lock()


def data_dir() -> Path:
    from ..config import load
    return Path(load()["data"]["dir"])


def _key(product_class: str | None, style: str | None, op: str) -> str:
    return f"{product_class or '-'}|{style or '-'}|{op}"


class Ledger:
    def __init__(self, path: Path | None = None, rows: dict | None = None):
        self.path = path
        self.rows: dict = rows or {}

    @classmethod
    def open(cls, path: Path | str | None = None) -> "Ledger":
        p = Path(path) if path else data_dir() / FILE
        rows = {}
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("version") == VERSION:
                rows = d.get("rows") or {}
        except (OSError, ValueError):
            pass
        return cls(p, rows)

    @classmethod
    def memory(cls) -> "Ledger":
        """A ledger that is never written (tests, a run with learning off)."""
        return cls(None, {})

    def row(self, product_class, style, op) -> dict:
        return self.rows.get(_key(product_class, style, op)) or {"tries": 0, "accepts": 0, "gain_sum": 0.0}

    def record(self, product_class, style, op, accepted: bool, gain: float = 0.0) -> None:
        r = dict(self.row(product_class, style, op))
        r["tries"] += 1
        if accepted:
            r["accepts"] += 1
            r["gain_sum"] = round(r["gain_sum"] + max(0.0, float(gain)), 6)
        r["mean_gain"] = round(r["gain_sum"] / r["accepts"], 6) if r["accepts"] else 0.0
        self.rows[_key(product_class, style, op)] = r

    def prior(self, product_class, style, op) -> float:
        """Smoothed priority multiplier. Falls back from (class, style) to (any class, style) when the exact pair is
        untried, so what a style learned on one product helps the next."""
        r = self.row(product_class, style, op)
        if not r["tries"] and product_class:
            agg = {"tries": 0, "accepts": 0, "gain_sum": 0.0}
            suffix = f"|{style or '-'}|{op}"
            for k, v in self.rows.items():
                if k.endswith(suffix):
                    for f in agg:
                        agg[f] += v.get(f, 0)
            r = agg
        rate = (r["accepts"] + K * PRIOR_ACCEPT) / (r["tries"] + K)
        gain = (r["gain_sum"] + K * PRIOR_GAIN) / (r["accepts"] + K)
        p = (rate / PRIOR_ACCEPT) * (gain / PRIOR_GAIN)
        return round(min(BOUNDS[1], max(BOUNDS[0], p)), 4)

    def save(self) -> None:
        if self.path is None:
            return
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"version": VERSION, "rows": self.rows}, indent=1, sort_keys=True),
                           encoding="utf-8")
            os.replace(tmp, self.path)

    def reset(self) -> None:
        self.rows = {}
        if self.path is not None:
            self.path.unlink(missing_ok=True)

    def summary(self) -> list[dict]:
        out = []
        for k, r in sorted(self.rows.items()):
            c, s, o = k.split("|", 2)
            out.append({"product_class": None if c == "-" else c, "style": None if s == "-" else s, "operator": o,
                        **r, "prior": self.prior(None if c == "-" else c, None if s == "-" else s, o)})
        return out


def reset(path: Path | str | None = None) -> None:
    """Empty the local ledger (the settings' reset control)."""
    Ledger.open(path).reset()
