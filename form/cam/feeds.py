"""Spindle speed and feed for an operation: chip load × flutes × RPM, from a table that names its source.

    RPM  = 3.82 × SFM / D[in]                    (the source's own formula; 3.82 = 12 / π)
    feed = RPM × chip load [in/tooth] × flutes   (inches per minute; × 25.4 for mm/min)

SFM and chip load come from form/cam/feeds.toml, where every row quotes the line it was read from. The start is the
low end of the source's SFM range. The chip load for a diameter between two the source lists is interpolated
linearly between them; outside the listed diameters it is not extended and the value is `assumed`.

Every number carries where it came from:

    sourced     read from the table (the source is named)
    computed    arithmetic on sourced numbers (RPM from SFM, the feed from the chip load, chip thinning)
    specified   the person gave it
    assumed     a rule of thumb nobody published here or the person did not confirm (plunge feeds, drills,
                chamfer mills, a material with no row, a spindle limit that was not stated)

A program with an assumed speed or feed is planned and simulated like any other, and cannot be released.
"""
from __future__ import annotations

import math
import tomllib
from functools import lru_cache
from pathlib import Path

VERSION = 1
SFM_FACTOR = 3.82


@lru_cache(maxsize=1)
def table() -> dict:
    t = tomllib.loads((Path(__file__).with_name("feeds.toml")).read_text(encoding="utf-8"))
    for sid, s in t["sources"].items():
        s["id"] = sid
    return t


def digest() -> str:
    import hashlib
    return hashlib.sha256((Path(__file__).with_name("feeds.toml")).read_bytes()).hexdigest()[:12]


def source_text(s: dict) -> str:
    return f"{s['publisher']}, “{s['title']}” ({s['url']}; {s['published']}, read {s['read']})"


def material(name: str | None) -> dict | None:
    """The table's row for a material name or alias, or None when no source here covers it."""
    k = str(name or "").strip().lower().replace(" ", "_")
    if not k:
        return None
    for m in table()["materials"]:
        if k == m["id"] or k in m.get("aliases", []):
            return m
    return None


def materials() -> list:
    return [{"id": m["id"], "label": m["label"], "sfm": m["sfm"], "source": m["source"]} for m in table()["materials"]]


def chipload_in(m: dict, d_mm: float) -> tuple[float | None, str]:
    """The chip load (in/tooth) for a diameter: (value, how). Linear between the source's diameters."""
    rows = sorted((float(k), v) for k, v in m["chipload_in"].items())
    d = d_mm / 25.4
    if d < rows[0][0] - 1e-9 or d > rows[-1][0] + 1e-9:
        return None, f"the source lists {rows[0][0]:g} to {rows[-1][0]:g} in; Ø{d_mm:g} mm is outside it"
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        if d0 - 1e-9 <= d <= d1 + 1e-9:
            if abs(d - d0) < 1e-9:
                return c0, f"the source's {d0:g} in column"
            if abs(d - d1) < 1e-9:
                return c1, f"the source's {d1:g} in column"
            c = c0 + (c1 - c0) * (d - d0) / (d1 - d0)
            return c, f"between the source's {d0:g} in ({c0:g}) and {d1:g} in ({c1:g}) columns, linear"
    return rows[0][1], f"the source's {rows[0][0]:g} in column"


def thinning(ae: float, d: float) -> float:
    """Radial chip thinning: with a radial cut ae under half the diameter the chip is thinner than the feed per
    tooth by sqrt(1 − (1 − 2·ae/D)²) (geometry of the cutter's arc), so the feed that keeps the chip load is the
    reciprocal times larger."""
    if ae >= d / 2 or ae <= 0:
        return 1.0
    return 1.0 / math.sqrt(1.0 - (1.0 - 2.0 * ae / d) ** 2)


def for_op(tool, material_name: str | None, machine: dict, given: dict | None = None, ae: float | None = None,
           thin: bool = False) -> dict:
    """Speed and feed for one operation with one tool.

    given: the person's own numbers for this operation (rpm, feed, plunge), each then `specified`.
    Returns {rpm, feed (mm/min), plunge (mm/min), chipload_mm, sfm, provenance: {rpm, feed, plunge}, source, calc,
    assumed: [what is assumed and why]}."""
    given = {k: v for k, v in (given or {}).items() if v not in (None, "", 0)}
    m = material(material_name)
    max_rpm = float(machine.get("max_rpm") or 0)
    prov, assumed, calc, src = {}, [], [], None
    rpm = feed = cl_mm = sfm = None
    end_mill = tool.kind in ("flat", "ball", "bull")
    if m and end_mill:
        src = table()["sources"][m["source"]]
        sfm = float(m["sfm"][0])
        rpm = SFM_FACTOR * sfm / (tool.d / 25.4)
        calc.append(f"RPM = 3.82 × {sfm:g} SFM / {tool.d / 25.4:.4f} in = {rpm:.0f}")
        prov["rpm"] = "computed"
        if max_rpm and rpm > max_rpm:
            calc.append(f"limited to the machine's {max_rpm:.0f} RPM")
            rpm = max_rpm
        cl, how = chipload_in(m, tool.d)
        if cl is not None:
            feed = rpm * cl * tool.flutes * 25.4
            cl_mm = cl * 25.4
            calc.append(f"chip load {cl:g} in/tooth ({how})")
            calc.append(f"feed = {rpm:.0f} × {cl:g} × {tool.flutes} flutes = {feed / 25.4:.2f} in/min = {feed:.0f} mm/min")
            prov["feed"] = "computed"
            if thin and ae:
                k = thinning(ae, tool.d)
                if k > 1.0:
                    feed *= k
                    calc.append(f"× {k:.3f} for chip thinning at a radial cut of {ae:g} mm (geometry) = {feed:.0f} mm/min")
        else:
            assumed.append(f"feed: {how}")
    if "rpm" in given:
        rpm, prov["rpm"] = float(given["rpm"]), "specified"
    if "feed" in given:
        feed, prov["feed"] = float(given["feed"]), "specified"
    if rpm is None:
        # no sourced speed: a low spindle speed that only a person's number replaces
        rpm = min(max_rpm or 10000.0, 10000.0)
        prov["rpm"] = "assumed"
        assumed.append("rpm: " + ("no source here covers " + tool.kind + " tools" if m else
                                  f"no source here covers the material “{material_name or 'not stated'}”"))
    if feed is None:
        # 0.01 × D per tooth, a placeholder that says so
        cl_mm = 0.01 * tool.d if tool.kind != "drill" else None
        feed = rpm * (0.01 * tool.d) * (tool.flutes if tool.kind != "drill" else 1)
        prov["feed"] = "assumed"
        if not any(a.startswith("feed") for a in assumed):
            assumed.append("feed: " + ("no source here covers " + tool.kind + " tools" if m else
                                       f"no source here covers the material “{material_name or 'not stated'}”"))
    if "plunge" in given:
        plunge, prov["plunge"] = float(given["plunge"]), "specified"
    else:
        plunge = feed if tool.kind == "drill" else feed / 3.0
        prov["plunge"] = "assumed" if tool.kind != "drill" else prov["feed"]
        if tool.kind != "drill":
            assumed.append("plunge: a third of the feed, a rule of thumb with no source here")
    mf = float(machine.get("max_feed") or 0)
    if mf:
        if feed > mf:
            calc.append(f"feed limited to the machine's {mf:.0f} mm/min")
        feed, plunge = min(feed, mf), min(plunge, mf)
    return {"rpm": round(rpm), "feed": round(feed, 1), "plunge": round(plunge, 1),
            "chipload_mm": round(cl_mm, 5) if cl_mm else None, "sfm": sfm, "provenance": prov,
            "source": source_text(src) if src else None, "material": m["id"] if m else None,
            "calc": "; ".join(calc), "assumed": assumed}
