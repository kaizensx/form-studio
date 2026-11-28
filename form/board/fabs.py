"""Board fabs' published capabilities, each value quoted from the fab's own capability page with the page and the date
it was read, and the board checked against them.

Only values the page states are here. A value a page does not state is absent, and its check says "not stated by
the fab", never a pass. A fab's minimum is its own claim about its standard process; it is a rule (source, date), not
a guarantee that a board will be made, and these pages change: read the page again before ordering.

Spacing is checked from what the board says it uses: the board's own minimum clearance rule (the .kicad_pro) and
the smallest gap between two tracks of different nets that Form Studio computed on the track segments. Pads, vias
and zones are spaced by KiCad's DRC (board_check with KiCad), which is the authority on spacing.
"""
from __future__ import annotations

READ = "2026-11-28"

# value: (mm, quoted text). Keys: trace, space, drill (plated / via), npth (non-plated), annular, annular_rec
# (recommended), board_min [w, d], board_max [w, d], thickness (list), drill_extra (below this costs more)
FABS = {
    "jlcpcb": {
        "name": "JLCPCB", "url": "https://jlcpcb.com/capabilities/pcb-capabilities", "read": READ,
        "process": {
            "2": {"label": "1-2 layers, 1 oz copper",
                  "trace": (0.10, "Min trace/space 1-2 layer 1 oz: 0.10 / 0.10 mm (4 / 4 mil)"),
                  "space": (0.10, "Min trace/space 1-2 layer 1 oz: 0.10 / 0.10 mm (4 / 4 mil)"),
                  "drill": (0.15, "Min via hole/diameter: 0.15/0.25 mm; drill 0.15 - 6.3 mm"),
                  "npth": (0.50, "Non-plated hole, min: 0.50 mm"),
                  "annular": (0.18, "2-layer 1 oz: absolute minimum 0.18 mm"),
                  "annular_rec": (0.25, "2-layer 1 oz: recommended 0.25 mm or above"),
                  "board_min": ([3, 3], "FR4: 3 x 3 mm"),
                  "board_max": ([670, 600], "2-layer FR4 (thickness >= 0.8 mm): 670 x 600 mm"),
                  "thickness": ([0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0], "FR-4: 0.4/0.6/0.8/1.0/1.2/1.6/2.0 mm")},
            "4": {"label": "multilayer, 1 oz copper",
                  "trace": (0.09, "Min trace/space multilayer 1 oz: 0.09 / 0.09 mm (3.5 / 3.5 mil)"),
                  "space": (0.09, "Min trace/space multilayer 1 oz: 0.09 / 0.09 mm (3.5 / 3.5 mil)"),
                  "drill": (0.15, "Min via hole/diameter: 0.15/0.25 mm"),
                  "npth": (0.50, "Non-plated hole, min: 0.50 mm"),
                  "annular": (0.15, "Multilayer 1 oz: absolute minimum 0.15 mm"),
                  "annular_rec": (0.20, "Multilayer 1 oz: recommended 0.20 mm or above"),
                  "board_min": ([3, 3], "FR4: 3 x 3 mm"),
                  "board_max": ([663, 593], "4-layer FR4: 663 x 593 mm"),
                  "thickness": ([0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0], "FR-4: 0.4/0.6/0.8/1.0/1.2/1.6/2.0 mm")},
        }},
    "pcbway": {
        "name": "PCBWay", "url": "https://www.pcbway.com/capabilities.html", "read": READ,
        "process": {
            "2": {"label": "standard PCB, 1-2 layers",
                  "trace": (0.10, "Min manufacturable trace is 4mil (0.1mm)"),
                  "space": (0.10, "Min manufacturable spacing is 4mil (0.1mm)"),
                  "drill": (0.15, "Min drill size is 0.15mm"),
                  "drill_extra": (0.20, "holes smaller than 0.2mm will be subject to extra charges"),
                  "annular": (0.15, "Min width for Annular Ring is 0.15mm (6mil)"),
                  "board_min": ([3, 3], "min 3*3mm"),
                  "board_max": ([600, 1200], "Single-sided and double-sided PCB: 600*1200mm"),
                  "thickness": ([0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0, 2.4, 2.6, 2.8, 3.0, 3.2], "0.2-3.2mm")},
            "4": {"label": "standard PCB, multilayer",
                  "trace": (0.10, "Min manufacturable trace is 4mil (0.1mm)"),
                  "space": (0.10, "Min manufacturable spacing is 4mil (0.1mm)"),
                  "drill": (0.15, "Min drill size is 0.15mm"),
                  "drill_extra": (0.20, "holes smaller than 0.2mm will be subject to extra charges"),
                  "annular": (0.15, "Min width for Annular Ring is 0.15mm (6mil)"),
                  "board_min": ([3, 3], "min 3*3mm"),
                  "board_max": ([560, 1150], "Multilayer PCB: 560*1150mm"),
                  "thickness": ([0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0, 2.4, 2.6, 2.8, 3.0, 3.2], "0.2-3.2mm")},
        }},
    "oshpark": {
        "name": "OSH Park", "url": "https://docs.oshpark.com/services/two-layer/", "read": READ,
        "process": {
            "2": {"label": "2 layer service",
                  "trace": (0.1524, "Trace width: 6mil (0.1524mm)"),
                  "space": (0.1524, "Trace spacing: 6mil (0.1524mm)"),
                  "drill": (0.254, "Minimum drill: 10mil (0.254mm)"),
                  "annular": (0.127, "Annular ring: 5mil (0.127mm)"),
                  "board_min": ([6.35, 6.35], "0.25in (6.35mm) by 0.25in (6.35mm)"),
                  "board_max": ([406.4, 558.8], "16in (406.4mm) by 22in (558.8mm)"),
                  "thickness": ([1.6], "63mil (1.6mm) nominal")},
            "4": {"label": "4 layer service", "url": "https://docs.oshpark.com/services/four-layer/",
                  "trace": (0.127, "Trace width: 5mil (0.127mm)"),
                  "space": (0.127, "Trace spacing: 5mil (0.127mm)"),
                  "drill": (0.254, "Minimum drill: 10mil (0.254mm)"),
                  "annular": (0.1016, "Annular ring: 4mil (0.1016mm)"),
                  "board_min": ([6.35, 6.35], "0.25in (6.35mm) by 0.25in (6.35mm)"),
                  "board_max": ([406.4, 558.8], "16in (406.4mm) by 22in (558.8mm)"),
                  "thickness": ([1.6], "63mil (1.6mm) nominal")},
        }},
}


def process_for(fab: str, layers: int) -> dict:
    f = FABS[fab]
    return f["process"]["2" if layers <= 2 else "4"]


def _row(fab, what, label, status, board_value, limit, quote, detail, url):
    return {"fab": fab, "check": what, "label": label, "status": status, "board": board_value, "fab_limit": limit,
            "detail": detail, "evidence": f"rule ({url}, read {READ}: “{quote}”)" if quote else "not stated by the fab"}


def check(board: dict, fabs: list[str] | None = None) -> dict:
    """Every chosen fab's limits against the board's own sizes. Rows say PASS, WARN (works, costs more or below the
    recommended value), FAIL, or NOT CHECKED (the board does not say, or the fab does not state it)."""
    cu = board.get("copper") or {}
    rules = board.get("rules") or {}
    layers = int(cu.get("layers") or 2)
    w, d = board["size"]
    t = board["thickness"]["value"]
    sp = (cu.get("track_spacing") or {}).get("gap")
    rule_clear = rules.get("min_clearance", rules.get("netclass_min_clearance"))
    drills = [x for x in (cu.get("min_via_drill"), cu.get("min_pth_drill")) if x]
    annular = [x for x in (cu.get("min_via_annular"), cu.get("min_pad_annular")) if x is not None]
    out = []
    for fid in fabs or list(FABS):
        if fid not in FABS:
            raise KeyError(f"Unknown fab “{fid}”: one of {', '.join(FABS)}.")
        f = FABS[fid]
        pr = process_for(fid, layers)
        url = pr.get("url", f["url"])
        rows = []

        def lim(k):
            return pr.get(k) or (None, "")

        def at_least(key, label, val, what):
            v, q = lim(key)
            if v is None:
                rows.append(_row(f["name"], key, label, "NOT CHECKED", val, None, "", "The fab's page does not state it.", url))
            elif val is None:
                rows.append(_row(f["name"], key, label, "NOT CHECKED", None, v, q, f"The board does not say its {what}.", url))
            else:
                ok = val >= v - 1e-9
                st = "PASS" if ok else "FAIL"
                extra = ""
                rec = pr.get(key + "_rec")
                if ok and rec and val < rec[0] - 1e-9:
                    st, extra = "WARN", f" Below the recommended {rec[0]:g} mm (“{rec[1]}”)."
                ex = pr.get("drill_extra") if key == "drill" else None
                if ok and ex and val < ex[0] - 1e-9:
                    st, extra = "WARN", f" Below {ex[0]:g} mm costs more (“{ex[1]}”)."
                rows.append(_row(f["name"], key, label, st, round(val, 4), v, q,
                                 f"Board {val:g} mm, fab minimum {v:g} mm.{extra}", url))
        at_least("trace", "Track width", cu.get("min_track_width"), "track widths (no tracks)")
        if sp is not None:
            at_least("space", "Track to track (computed on the tracks)", sp, "track spacing")
        if rule_clear is not None:
            r = len(rows)
            at_least("space", "Clearance rule (.kicad_pro)", rule_clear, "clearance rule")
            rows[r]["detail"] += " This is the rule the board is routed to; KiCad's DRC checks it everywhere."
        if sp is None and rule_clear is None:
            rows.append(_row(f["name"], "space", "Spacing", "NOT CHECKED", None, lim("space")[0], lim("space")[1],
                             "Spacing is measured by KiCad's DRC: run board_check with KiCad, or give the .kicad_pro.", url))
        at_least("drill", "Smallest plated or via drill", min(drills) if drills else None, "drill sizes (no plated holes)")
        if cu.get("min_npth_drill") is not None and pr.get("npth"):
            at_least("npth", "Smallest non-plated hole", cu["min_npth_drill"], "non-plated holes")
        at_least("annular", "Smallest annular ring", min(annular) if annular else None, "annular rings")
        (mn, qmn), (mx, qmx) = lim("board_min"), lim("board_max")
        if mn and mx:
            lo, hi = sorted((w, d)), sorted(mx)
            ok_min = min(w, d) >= min(mn) - 1e-9 and max(w, d) >= max(mn) - 1e-9
            ok_max = lo[0] <= hi[0] + 1e-9 and lo[1] <= hi[1] + 1e-9
            rows.append(_row(f["name"], "board_size", "Board size", "PASS" if ok_min and ok_max else "FAIL",
                             [w, d], {"min": mn, "max": mx}, f"{qmn}; {qmx}",
                             f"Board {w:g} × {d:g} mm; the fab makes {mn[0]:g} × {mn[1]:g} to {mx[0]:g} × {mx[1]:g} mm.", url))
        th, qth = lim("thickness")
        if th:
            ok = any(abs(t - x) < 0.051 for x in th)
            rows.append(_row(f["name"], "thickness", "Board thickness", "PASS" if ok else "WARN", t, th, qth,
                             f"Board {t:g} mm; the fab lists {', '.join(f'{x:g}' for x in th)} mm." +
                             ("" if ok else " Not a listed thickness: ask the fab."), url))
        bad = sum(r["status"] == "FAIL" for r in rows)
        warn = sum(r["status"] == "WARN" for r in rows)
        nc = sum(r["status"] == "NOT CHECKED" for r in rows)
        out.append({"fab": f["name"], "id": fid, "process": pr["label"], "url": url, "read": READ, "rows": rows,
                    "status": "FAIL" if bad else "WARN" if warn or nc else "PASS",
                    "headline": (f"{bad} below the fab's limits" if bad else
                                 "within the stated limits" + (f", {warn} to note" if warn else "") +
                                 (f", {nc} not checked" if nc else ""))})
    return {"layers": layers, "fabs": out,
            "note": "Each limit is the fab's published claim about its standard process, quoted with its page and the "
                    "date it was read. It is not an approval: read the page again and run KiCad's DRC before ordering."}
