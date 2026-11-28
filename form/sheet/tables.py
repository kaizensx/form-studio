"""The bend table (form/sheet/tables/bend.toml) and the service tables (form/sheet/services/*.toml) as data, with
the K-factor chosen for one bend and where that number came from.

    kfactor(r, t, material="steel_mild", method="table", forming="air")   # {"K", "method", "source", "evidence", ...}
    kfactor(r, t, k=0.42)                                                  # a shop's own value: "specified"
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import math
import tomllib
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).with_name("tables")
SERVICES = Path(__file__).with_name("services")
STALE_DAYS = 90               # a service table read longer ago than this says so (docs/plans, wave H)


@lru_cache(maxsize=None)
def bend_table() -> dict:
    raw = tomllib.loads((DIR / "bend.toml").read_text(encoding="utf-8"))
    raw["sources"] = {s["id"]: s for s in raw.get("source", [])}
    raw["materials"] = {m["id"]: m for m in raw.get("material", [])}
    return raw


def digest() -> str:
    return hashlib.sha256((DIR / "bend.toml").read_bytes()).hexdigest()[:16]


def source_text(sid: str, sources: dict | None = None) -> str:
    s = (sources or bend_table()["sources"]).get(sid)
    if not s:
        return sid
    return f"{s['title']}, {s['publisher']} ({s.get('published', 'undated')}; read {s.get('read', '?')})"


def material(mid: str | None) -> dict | None:
    if not mid:
        return None
    key = str(mid).strip().lower().replace("-", "_").replace(" ", "_")
    mats = bend_table()["materials"]
    if key in mats:
        return mats[key]
    for m in mats.values():
        if key in (m["label"].lower().replace(" ", "_"),):
            return m
    return None


def default_radius(t: float, mid: str | None = None) -> dict:
    """The inside radius a bend gets when the design gives none: the material's r_default (t), with its source."""
    m = material(mid) or {"r_default": "t", "r_source": "fractory-bending"}
    r = float(t) if m["r_default"] == "t" else float(m["r_default"])
    return {"r": r, "source": source_text(m["r_source"]), "evidence": "rule"}


def kfactor(r: float, t: float, material_id: str | None = None, method: str | None = None,
            forming: str = "air", k: float | None = None) -> dict:
    """The K-factor of one bend, with its method, source and evidence class.

    method "value" (or k given): the person's or shop's number, evidence "specified".
    method "table": the generic table by forming (air, bottoming, coining), material class and r/t; needs a
    material (its class is Form Studio's reading, "assumed"); without one, the medium column, said so.
    method "din6935": K = (0.65 + 0.5·log10(r/t)) / 2, kept within [0, 0.5]."""
    tab = bend_table()
    kf = tab["kfactor"]
    if k is not None or method == "value":
        if k is None:
            raise ValueError("method value needs k.")
        k = float(k)
        if not 0.0 <= k <= 1.0:
            raise ValueError("A K-factor is between 0 and 1.")
        return {"K": k, "method": "value", "evidence": "specified", "source": "your value"}
    method = method or kf["default"]
    if t <= 0:
        raise ValueError("t must be positive.")
    rt = max(r, 0.0) / t
    if method == "din6935":
        d = kf["din6935"]
        if rt <= 0:
            K, note = d["cap"][0], "r = 0: log10 undefined, K at its lower cap 0"
        else:
            K = (0.65 + 0.5 * math.log10(rt)) / 2
            note = ""
        lo, hi = d["cap"]
        capped = K < lo or K > hi
        K = min(max(K, lo), hi)
        out = {"K": K, "method": "din6935", "evidence": "rule", "source": source_text(d["source"]),
               "r_over_t": round(rt, 4), "formula": d["formula"]}
        if capped or note:
            out["note"] = note or f"capped to [{lo}, {hi}] (cap unsourced)"
        return out
    if method != "table":
        raise ValueError(f"Unknown K-factor method {method!r}: table, din6935 or value.")
    d = kf["table"]
    forming = (forming or "air").lower()
    if forming not in ("air", "bottoming", "coining"):
        raise ValueError("forming is air, bottoming or coining.")
    m = material(material_id)
    cls = m["class"] if m else "medium"
    band = 0 if rt <= d["bands"][0] else (1 if rt <= d["bands"][1] else 2)
    K = float(d[forming][cls][band])
    out = {"K": K, "method": "table", "evidence": "rule", "source": source_text(d["source"]), "forming": forming,
           "class": cls, "class_evidence": (m or {}).get("class_source", "assumed"), "r_over_t": round(rt, 4),
           "band": ["r/t ≤ 1", "1 < r/t ≤ 3", "r/t > 3"][band]}
    if not m:
        out["note"] = ("No material given: the medium column was read." if not material_id
                       else f"Material {material_id!r} is not in the table: the medium column was read.")
    return out


def bend_allowance(theta_deg: float, r: float, t: float, K: float) -> float:
    return math.radians(theta_deg) * (r + K * t)


# ---- service tables --------------------------------------------------------------------------------------------

def services() -> list[str]:
    return sorted(p.stem for p in SERVICES.glob("*.toml"))


@lru_cache(maxsize=None)
def service(sid: str) -> dict:
    path = SERVICES / f"{sid}.toml"
    if not path.is_file():
        raise KeyError(sid)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    raw["sources"] = {s["id"]: s for s in raw.get("source", [])}
    raw["materials"] = {m["id"]: m for m in raw.get("material", [])}
    return raw


def service_digest(sid: str) -> str:
    return hashlib.sha256((SERVICES / f"{sid}.toml").read_bytes()).hexdigest()[:16]


def age_days(read: str, today: _dt.date | None = None) -> int | None:
    try:
        d = _dt.date.fromisoformat(str(read)[:10])
    except ValueError:
        return None
    return ((today or _dt.date.today()) - d).days
