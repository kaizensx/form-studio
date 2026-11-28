"""Service preflight: would a cutting and bending service accept this part as it is? Checked against the service's
published materials, thicknesses and limits (form/sheet/services/<id>.toml, every value with its page and the date
it was read). Nothing is uploaded and nothing is ordered: the result says what to fix before a person sends it.

    preflight(flat, "sendcutsend", material="al_5052_h32", t=3.175)   # flat: an unfold result or a cut-file check
"""
from __future__ import annotations

import datetime as _dt

from . import tables

IN = 25.4


def _row(rid, title, status, value=None, limit=None, source=None, quote=None, note=None, unit="") -> dict:
    r = {"id": rid, "title": title, "status": status, "value": value, "limit": limit, "unit": unit}
    if source:
        r["source"] = source
    if quote:
        r["quote"] = quote
    if note:
        r["note"] = note
    return r


def find_material(svc: dict, name: str | None) -> dict | None:
    if not name:
        return None
    key = str(name).strip().lower().replace("_", " ").replace("-", " ")
    for m in svc["materials"].values():
        if key in (m["id"].replace("_", " "), m["label"].lower()) or key in [a.lower().replace("-", " ") for a in m.get("aliases", [])]:
            return m
    return None


def preflight(flat: dict, service: str = "sendcutsend", material: str | None = None, t: float | None = None,
              cut_rows: list | None = None, today: _dt.date | None = None) -> dict:
    """Rows (pass, fail, warn, not_checked) for one part against one service's table.

    flat: {"t", "bends": [{"angle", ...}], "size_mm": [w, h], "holes": [d, ...]} (an unfold result works);
    cut_rows: rows of the laser cut-file check (form/sheet/cutcheck.py) to carry over."""
    svc = tables.service(service)
    src = svc["sources"]
    lim = svc["limits"]
    rows = []
    t = float(t if t is not None else flat.get("t") or 0.0) or None
    m = find_material(svc, material)
    if not material:
        rows.append(_row("svc.material", "Material offered", "not_checked", note="No material given (one of: " +
                         ", ".join(x["id"] for x in svc["materials"].values()) + ")."))
    elif m is None:
        rows.append(_row("svc.material", "Material offered", "fail", value=material,
                         note="Not in the table Form Studio holds for this service (" +
                         ", ".join(x["label"] for x in svc["materials"].values()) + "); the service may offer more."))
    else:
        rows.append(_row("svc.material", "Material offered", "pass", value=m["label"], source=tables.source_text(m["source"], src)))
    near = None
    if m and t:
        ths = [x * IN for x in m["thicknesses_in"]]
        near = min(ths, key=lambda x: abs(x - t))
        ok = abs(near - t) <= lim["thickness_match_mm"]
        rows.append(_row("svc.thickness", "Thickness offered", "pass" if ok else "fail", value=round(t, 4),
                         limit=round(near, 4), unit="mm", source=tables.source_text(m["source"], src),
                         note=None if ok else f"Nearest listed: {near:.3f} mm ({near / IN:.3f} in). Listed: " +
                         ", ".join(f"{x:.3f}" for x in m["thicknesses_in"]) + " in."))
    elif not t:
        rows.append(_row("svc.thickness", "Thickness offered", "not_checked", note="No thickness."))
    bends = flat.get("bends") or []
    size = flat.get("size_mm")
    if bends:
        if m and t:
            okb = t <= m["bend_max_in"] * IN + lim["thickness_match_mm"]
            rows.append(_row("svc.bend_thickness", "Bending offered at this thickness", "pass" if okb else "fail",
                             value=round(t, 4), limit=round(m["bend_max_in"] * IN, 4), unit="mm",
                             source=tables.source_text(m["source"], src)))
        amax = max(float(b["angle"]) for b in bends)
        rows.append(_row("svc.bend_angle", "Bend angle", "pass" if amax <= lim["bend_max_angle"] + 1e-9 else "fail",
                         value=round(amax, 3), limit=lim["bend_max_angle"], unit="°",
                         source=tables.source_text(lim["bend_angle_source"], src), quote=lim["bend_angle_quote"]))
        if size:
            w, h = sorted(size)
            mn = sorted(x * IN for x in lim["bend_min_flat_in"])
            mx = sorted(x * IN for x in lim["bend_max_flat_in"])
            st = "pass" if (w >= mn[0] - 1e-6 and h >= mn[1] - 1e-6 and w <= mx[0] + 1e-6 and h <= mx[1] + 1e-6) else "fail"
            rows.append(_row("svc.bend_flat_size", "Flat size for a bent part", st, value=[round(w, 3), round(h, 3)],
                             limit={"min": [round(x, 3) for x in mn], "max": [round(x, 3) for x in mx]}, unit="mm",
                             source=tables.source_text(lim["bend_flat_source"], src), quote=lim["bend_flat_quote"]))
        rows.append(_row("svc.bend_radius", "Bend radius and K-factor", "info", source=tables.source_text(lim["radius_source"], src),
                         quote=lim["radius_note"], note="The service bends with its own radius and K-factor per thickness: "
                         "its flat pattern can differ from this one by the difference in bend allowance."))
    elif size:
        rows.append(_row("svc.flat_size", "Flat part size", "not_checked", value=[round(x, 3) for x in sorted(size)],
                         note=lim["max_flat_note"]))
    if t and flat.get("holes"):
        hmin = min(flat["holes"])
        need = lim["laser_min_hole"] * t
        rows.append(_row("svc.hole", "Smallest hole (laser)", "pass" if hmin >= need - 1e-9 else "fail", value=round(hmin, 4),
                         limit=round(need, 4), unit="mm", source=tables.source_text(lim["laser_min_hole_source"], src),
                         quote=lim["laser_min_hole_quote"]))
    for r in cut_rows or []:
        if r["id"].startswith("cut."):
            rows.append({k: r.get(k) for k in ("id", "title", "status", "value", "unit", "quote", "reason", "note")
                         if r.get(k) is not None} | {"source": (r.get("source_ref") or {}).get("title", r.get("source"))})
    age = tables.age_days(svc["service"]["read"], today)
    stale = age is not None and age > tables.STALE_DAYS
    sts = [r["status"] for r in rows]
    verdict = "fail" if "fail" in sts else ("not proven" if "not_checked" in sts else ("warn" if "warn" in sts else "pass"))
    head = f"{svc['service']['label']} preflight: {verdict}"
    if stale:
        head += f" (table read {age} days ago: check the service's pages again)"
    return {"service": svc["service"]["id"], "label": svc["service"]["label"], "verdict": verdict, "rows": rows,
            "headline": head, "table_read": svc["service"]["read"], "table_age_days": age, "stale": stale,
            "note": svc["service"].get("note", ""), "sent": False, "ordered": False,
            "nothing_sent": "Nothing was uploaded and nothing was ordered: this is a check against the service's "
                            "published limits, for a person to act on.",
            "sources": [tables.source_text(k, src) for k in src], "digest": tables.service_digest(service)}
