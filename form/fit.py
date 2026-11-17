"""Fit under uncertainty, printer calibration, and the next most useful evidence.

Everything here is a statistical model with stated inputs. It reports where
each input came from so a modelled yield is never read as a measured one.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from . import fsutil

PRIOR_SIGMA = 0.15       # mm, assumed spread of an uncalibrated FDM internal width
SIGMA_BY_SOURCE = {"measured": 0.03, "specified": 0.10, "photo": 0.60, "assumed": 0.30, "calibrated": 0.05}


def cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def window_yield(mean: float, sd: float, lo: float, hi: float) -> float:
    if sd <= 0:
        return float(lo <= mean <= hi)
    return max(0.0, min(1.0, cdf((hi - mean) / sd) - cdf((lo - mean) / sd)))


class Calibration:
    """Studio-wide record of nominal-vs-measured internal widths per printer profile."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {"schema": "form-calibration/1", "records": []}

    def records(self) -> list:
        return self._load()["records"]

    def add(self, profile: str, pairs: list, source: str, note: str = "", ref: dict | None = None) -> dict:
        clean = []
        for p in pairs:
            n, m = float(p["nominal"]), float(p["measured"])
            if not (math.isfinite(n) and math.isfinite(m)) or n <= 0 or m <= 0 or abs(m - n) > 3:
                raise ValueError(f"Measurement {m} for nominal {n} is not plausible (differs by more than 3 mm).")
            clean.append({"nominal": n, "measured": m})
        if not clean:
            raise ValueError("Enter at least one measured width.")
        data = self._load()
        rec = {"id": uuid.uuid4().hex[:8], "ts": time.time(), "profile": profile, "source": source,
               "pairs": clean, "note": note, "ref": ref or {}}
        data["records"].append(rec)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        fsutil.replace(tmp, self.path)
        return rec

    def remove(self, rec_id: str) -> None:
        data = self._load()
        data["records"] = [r for r in data["records"] if r["id"] != rec_id]
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def correction(self, profile: str) -> dict:
        devs = [p["measured"] - p["nominal"] for r in self.records() if r["profile"] == profile for p in r["pairs"]]
        n = len(devs)
        if n == 0:
            return {"profile": profile, "n": 0, "bias": 0.0, "sigma": PRIOR_SIGMA, "sigma_effective": PRIOR_SIGMA,
                    "source": "assumed", "note": f"No calibration for this profile. Using an assumed ±{PRIOR_SIGMA} mm spread and zero bias."}
        bias = sum(devs) / n
        if n >= 3:
            sd = max(math.sqrt(sum((d - bias) ** 2 for d in devs) / (n - 1)), 0.02)
            src = "calibrated"
            note = f"From {n} measured widths on this profile."
        else:
            sd, src = PRIOR_SIGMA, "partly calibrated"
            note = f"Only {n} measurement(s): bias is used, spread still assumed ±{PRIOR_SIGMA} mm."
        eff = math.hypot(sd, sd / math.sqrt(n))
        return {"profile": profile, "n": n, "bias": bias, "sigma": sd, "sigma_effective": eff, "source": src, "note": note}

    def fingerprint(self, profile: str) -> str:
        c = self.correction(profile)
        return f"{c['n']}:{c['bias']:.4f}:{c['sigma']:.4f}"


def mating_sigma(prov: dict | None) -> tuple[float, str]:
    prov = prov or {}
    src = prov.get("source", "assumed")
    s = prov.get("sigma")
    if isinstance(s, (int, float)) and s >= 0:
        return float(s), src
    return SIGMA_BY_SOURCE.get(src, 0.3), src


def analyse(recipe, values: dict, provenance: dict, window: dict, corr: dict) -> dict | None:
    f = recipe.fit
    if not f:
        return None
    derived = {d["key"]: d["value"] for d in recipe.derived(values)}
    cavity, mating = derived[f["cavity"]], values[f["mating"]]
    s_m, src_m = mating_sigma(provenance.get(f["mating"]))
    s_p = corr["sigma_effective"]
    mean = cavity + corr["bias"] - mating
    sd = math.hypot(s_p, s_m)
    lo, hi = window["gap_min"], window["gap_max"]
    y = window_yield(mean, sd, lo, hi)
    target = (lo + hi) / 2
    best_clear = max(0.0, (target - corr["bias"]) / 2)
    return {
        "label": f["label"], "cavity_key": f["cavity"], "mating_key": f["mating"], "clearance_key": f["clearance"],
        "mating_label": recipe.spec(f["mating"]).label,
        "cavity_nominal": cavity, "mating": mating, "nominal_gap": cavity - mating,
        "expected_gap": mean, "sd": sd, "interval": [mean - 2 * sd, mean + 2 * sd],
        "window": [lo, hi], "yield": y,
        "p_tight": cdf((lo - mean) / sd) if sd > 0 else float(mean < lo),
        "p_loose": 1 - cdf((hi - mean) / sd) if sd > 0 else float(mean > hi),
        "sources": {
            "mating": {"sigma": s_m, "source": src_m, "share": (s_m ** 2 / sd ** 2) if sd else 0},
            "printer": {"sigma": s_p, "bias": corr["bias"], "source": corr["source"], "n": corr["n"],
                        "share": (s_p ** 2 / sd ** 2) if sd else 0, "note": corr["note"]},
        },
        "recommended_clearance": round(best_clear, 3),
        "current_clearance": values[f["clearance"]],
        "yield_at_recommended": window_yield(target, sd, lo, hi),
        "model": "Independent normal errors. Total gap = printed cavity − device. A model, not a measured success rate.",
    }


def next_actions(fit: dict | None, costs: dict) -> list[dict]:
    """Rank what to do next by modelled yield gained. Costs are slicer estimates when available."""
    if not fit:
        return []
    lo, hi = fit["window"]
    target = (lo + hi) / 2
    s_m, s_p = fit["sources"]["mating"]["sigma"], fit["sources"]["printer"]["sigma"]
    now = fit["yield"]
    centred = lambda sm, sp: window_yield(target, math.hypot(sm, sp), lo, hi)
    acts = []
    if fit["sources"]["mating"]["source"] != "measured":
        what = fit.get("mating_label", "Device width")
        acts.append({"id": "measure", "title": f"Measure the {what.lower()} with calipers",
                     "why": f"{what} is {fit['sources']['mating']['source']} (±{s_m:.2f} mm) and drives "
                            f"{fit['sources']['mating']['share']*100:.0f}% of the fit uncertainty.",
                     "after": centred(SIGMA_BY_SOURCE["measured"], s_p), "cost": "about a minute", "cost_s": 60, "stage": "brief"})
    if fit["sources"]["printer"]["source"] != "calibrated":
        c = costs.get("coupon")
        acts.append({"id": "coupon", "title": "Print and measure the fit coupon",
                     "why": "This printer profile has no measured bias or spread; Form Studio is assuming them. "
                            "The result is reused by every later design on this profile.",
                     "after": centred(s_m, 0.06), "cost": _cost(c), "cost_s": (c or {}).get("time_s"), "stage": "fit"})
    c = costs.get("test_piece")
    if now < 0.98:
        acts.append({"id": "test_piece", "title": "Print the pocket ring",
                     "why": "A 6 mm slice of the real pocket. Tests this exact interface for a fraction of the full print.",
                     "after": centred(min(s_m, 0.05), 0.06), "cost": _cost(c), "cost_s": (c or {}).get("time_s"), "stage": "fit"})
    if fit["yield_at_recommended"] - now > 0.01:
        acts.append({"id": "recentre", "title": f"Set clearance to {fit['recommended_clearance']:.2f} mm per side",
                     "why": "Centres the expected gap in your acceptance window using the bias known so far.",
                     "after": fit["yield_at_recommended"], "cost": "no print", "cost_s": 0, "stage": "shape",
                     "change": {fit["clearance_key"]: fit["recommended_clearance"]}})
    c = costs.get("part")
    acts.append({"id": "print", "title": "Print the part",
                 "why": "The only physical proof. Sensible once the modelled yield is high.",
                 "after": now, "cost": _cost(c), "cost_s": (c or {}).get("time_s"), "stage": "print"})
    for a in acts:
        a["gain"] = a["after"] - now
    free = {"measure", "recentre"}       # no print needed: do these before spending filament
    acts.sort(key=lambda a: (a["id"] == "print", not (a["gain"] > 0.005), a["id"] not in free, -a["gain"]))
    if now >= 0.95:
        acts.sort(key=lambda a: a["id"] != "print")
    return acts


def _cost(c: dict | None) -> str:
    if not c:
        return "not sliced yet"
    parts = []
    if c.get("time_s") is not None:             # some slicers write no time estimate into the G-code
        m = int(round(c["time_s"] / 60))
        parts.append(f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min")
    if c.get("filament_g") is not None:
        parts.append(f"{c['filament_g']:.1f} g")
    return " · ".join(parts) + " (slicer estimate)" if parts else "sliced, no estimate from the slicer"
