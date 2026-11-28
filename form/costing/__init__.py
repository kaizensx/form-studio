"""Cost per process with sourced rates: FDM, SLA, SLS, MJF, metal LPBF, CNC, injection moulding, sheet metal and the
purchased parts, each built from its drivers, with quantity curves and the crossovers between processes.

    from form import costing
    costing.estimate(st, p, "cnc", quantities=[1, 10, 100])     # one process: lines, totals, the curve
    costing.compare(st, p)                                       # every process that applies, curves and crossovers
    costing.cost(st, p, "injection", quantity=5000)              # one number (or None): per part, for optimise
    costing.objective("auto", 1000)                              # a callable (st, p) -> float for a Pareto front

Drivers come from what Form Studio already knows about the design, each with its evidence:
  * the B-rep (volume, area, bounding box, faces): computed;
  * the slicer's grams and hours for FDM, when there is a current slice: simulated (else estimated from the volume);
  * manufacturability (form/dfm): projected area, walls, side actions for moulding; setups for CNC: computed;
  * CAM (form/cam): the simulated cycle time when the program is current (else estimated from removed volume);
  * the sheet unfold (form/sheet): flat area, thickness, cut length, contours, bends: computed;
  * the parts list (form/bom.py) for purchased parts, priced only where the person gave a price.
Rates come from form/costing/rates.toml (sourced, cited and dated, or assumed process parameters) and the person's
shop (specified). A line without a value is never guessed: it is left out of the totals and says what to set.
"""
from __future__ import annotations

import math
import time

from . import models, rates as rates_mod
from .models import LABELS, PROCESSES, drv

VERSION = 1
QUANTITIES = (1, 10, 100, 1000, 10000)
NOTE = ("A quote-style estimate (class C: for comparing designs and processes, not a quote). Each line shows its "
        "formula and the evidence of every input: sourced (published, cited, dated), specified (yours), assumed (a "
        "process parameter no source states), computed or simulated (from the design).")
RESIN_DFM = {"ABS": "abs", "HDPE": "pe", "POM": "acetal", "PA66": "nylon", "PC": "pc", "PP_TALC40": "pp", "PP": "pp"}
MATERIAL_RESIN = {"ABS": "ABS", "ASA": "ABS", "PC": "PC", "PA": "PA66", "NYLON-PA6": "PA66", "POM": "POM"}
METALS = ("AL-6061", "AL-7075", "STEEL", "STAINLESS", "BRASS", "COPPER", "TITANIUM", "STEEL-4140")


def _err(msg, hint=""):
    from ..studio import StudioError
    return StudioError(msg, hint)


def process_id(name: str) -> str:
    s = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    s = {"moulding": "injection", "molding": "injection", "injection_moulding": "injection", "im": "injection",
         "sheet": "sheet_metal", "laser": "sheet_metal", "metal": "lpbf", "dmls": "lpbf", "slm": "lpbf",
         "resin": "sla", "milling": "cnc", "parts": "purchased"}.get(s, s)
    if s not in PROCESSES + ("purchased",):
        raise _err(f"Unknown process “{name}”.", "Processes: " + ", ".join(PROCESSES) + ", purchased.")
    return s


def clean_quantities(q) -> list:
    if q in (None, "", []):
        return list(QUANTITIES)
    if isinstance(q, (int, float)):
        q = [q]
    if isinstance(q, str):
        q = [x for x in q.replace(";", ",").split(",") if x.strip()]
    out = sorted({int(float(x)) for x in q})
    if not out or out[0] < 1 or out[-1] > 10 ** 8 or len(out) > 40:
        raise _err("Quantities are whole numbers from 1 to 100,000,000 (at most 40 of them).")
    return out


# ---- drivers from the design ----------------------------------------------------------------------------------

# A candidate of a search (inverse design) is built by the kernel but never saved, so it has no slice, no CAM
# simulation, no manufacturability check and no unfold of its own. These processes are costed from its volume and
# bounding box alone; moulding and sheet metal need a check of each candidate's solid, which a search does not run.
CANDIDATE_PROCESSES = ("fdm", "sla", "sls", "mjf", "lpbf", "cnc")


class Design:
    """What the cost models read from one revision, measured once and shared by every process.

    candidate: {"volume_mm3", "size": [x, y, z]} of a built, unsaved candidate (inverse design): the B-rep drivers
    are the candidate's; nothing is read from a slice or a CAM simulation of the head revision. dfm_cache: a dict
    kept across candidates, so the head's manufacturability (CNC setups) is measured once per search."""

    def __init__(self, st, p: dict, options: dict | None = None, candidate: dict | None = None,
                 dfm_cache: dict | None = None):
        from .. import materials
        self.st, self.p, self.o = st, p, dict(options or {})
        self.candidate = dict(candidate) if candidate else None
        if self.candidate:
            size = [float(x) for x in self.candidate["size"]]
            self.s = {"volume_mm3": float(self.candidate["volume_mm3"]), "bbox": [[0.0, 0.0, 0.0], size], "faces": None}
        else:
            self.s = st.head_summary(p)
        lo, hi = self.s["bbox"]
        self.size = [float(b - a) for a, b in zip(lo, hi)]
        self.mat = materials.resolved(p)["material"]
        self.mat_info = materials.info(self.mat) if self.mat else None
        self.rev = st.rev(p)["n"]
        self.notes: list = []
        self._dfm: dict = dfm_cache if dfm_cache is not None else {}

    # B-rep
    def volume(self):
        return drv("volume_mm3", self.s["volume_mm3"], "mm³", "computed (B-rep)",
                   "the candidate's solid" if self.candidate else "the design's solid", "Volume")

    def faces(self):
        return drv("faces", self.s.get("faces"), "faces", "computed (B-rep)", "faces of the design's solid", "Faces")

    def density(self, fallback: str, why: str, accept=None):
        """The design's material density when it suits the process, else the fallback material's, labelled assumed."""
        from .. import material_library as ml
        key = self.mat if self.mat and (accept is None or accept(self.mat)) else None
        if key:
            d = ml.density(key)
            return drv("density_g_cm3", d["value"] / 1000, "g/cm³", d["evidence"], d["source"], f"Density ({key})"), key
        d = ml.density(fallback)
        return drv("density_g_cm3", d["value"] / 1000, "g/cm³", "assumed",
                   f"{fallback} as a stand-in ({why}); {d['source']}", f"Density ({fallback}, assumed)"), fallback

    # manufacturability (cached by form/dfm)
    def dfm(self, process: str, options: dict) -> tuple[dict, dict]:
        from .. import dfm
        k = (process, tuple(sorted(options.items())))
        if k not in self._dfm:
            res = dfm.check(self.st, self.p, process, options, overlay_file=False)
            o = dfm.options_for(self.st, self.p, process, options)
            meas, _gk = dfm.measured(self.st, self.p, process, o)
            self._dfm[k] = (res, meas.get("measures") or {})
        return self._dfm[k]


def _measure(measures: dict, key: str, agg=max):
    m = measures.get(key) or {}
    vals = [it["value"] for it in m.get("items", []) if isinstance(it.get("value"), (int, float))]
    return (agg(vals) if vals else None), m.get("state")


def drivers(D: Design, process: str, R) -> dict:
    """The drivers of one process, each with its evidence (see models.py)."""
    if D.candidate and process not in CANDIDATE_PROCESSES:
        raise _err(f"{LABELS[process]} is not costed for a search candidate: it needs a check of each candidate's solid "
                   "(manufacturability or the unfold), which a search does not run. Nothing was made up.",
                   "Cost processes for a search: " + ", ".join(CANDIDATE_PROCESSES) + ". Cost the variant you keep with "
                   "estimate_cost.")
    o = D.o.get(process) or {}
    vol = D.volume()
    d: dict = {"volume_mm3": vol}
    if process == "fdm":
        kind = (D.mat_info or {}).get("kind")
        key = D.mat if kind == "filament" else None
        sliced = None
        if D.p.get("purpose") == "print" and not D.candidate:
            try:
                from .. import cost as legacy
                sliced = legacy.project(D.st, D.p, with_materials=False)
            except Exception:                    # noqa: BLE001 - no current slice: estimate from the volume
                sliced = None
        if sliced and sliced["per_plate_as_sliced"].get("filament_g") is not None:
            pl = sliced["per_plate_as_sliced"]
            d["grams"] = drv("grams", pl["filament_g"], "g", "simulated", f"{sliced.get('slicer')}'s slice of r{sliced.get('rev')}", "Filament")
            d["hours"] = drv("hours", (pl.get("time_s") or 0) / 3600 if pl.get("time_s") is not None else None, "h", "simulated",
                             f"{sliced.get('slicer')}'s slice of r{sliced.get('rev')}", "Print time")
            key = key or sliced["filament"].get("filament_type")
            if sliced["filament"].get("price_per_kg") is not None:
                d["price_per_kg"] = {"id": "fdm.material." + (key or ""), "value": sliced["filament"]["price_per_kg"],
                                     "evidence": "specified", "source": sliced["filament"]["price_source"]
                                     + f" (taken as {R.currency})", "unit": f"{R.currency}/kg"}
        else:
            dens, k2 = D.density("PLA", "no filament is set for the design",
                                 lambda m: (D.mat_info or {}).get("kind") == "filament")
            key = key or k2
            sf, rate = R.get("fdm.solid_fraction"), R.get("fdm.rate_g_h")
            g = vol["value"] / 1000 * dens["value"] * sf["value"]
            d["grams"] = drv("grams", g, "g", "estimated", f"volume × {dens['value']:.3g} g/cm³ × {sf['value']:g} (assumed; no slice)", "Filament")
            d["hours"] = drv("hours", g / rate["value"], "h", "estimated", f"grams / {rate['value']:g} g/h (assumed; no slice)", "Print time")
            D.notes.append("FDM: grams and hours are estimated from the candidate's volume (a search slices nothing)."
                           if D.candidate else
                           "FDM: no current slice, so grams and hours are estimated from the volume; slice the design for the slicer's numbers.")
        d["material_key"] = key or "PLA"
        try:
            from .. import cost as legacy
            prefs = legacy.load_prefs(D.st.cfg)
            if d.get("price_per_kg") is None and d["material_key"] in prefs.get("prices", {}):
                d["price_per_kg"] = {"id": "fdm.material." + d["material_key"], "value": prefs["prices"][d["material_key"]],
                                     "evidence": "specified", "unit": f"{R.currency}/kg",
                                     "source": f"your filament price for print cost (taken as {R.currency})"}
        except Exception:                        # noqa: BLE001
            pass
    elif process in ("sls", "mjf"):
        d["density_g_cm3"], _k = D.density("PA", "no polyamide is set for the design; PA filament's datasheet density",
                                           lambda m: m in ("PA", "NYLON-PA6", "PA-CF"))
    elif process == "lpbf":
        d["density_g_cm3"], k = D.density("STAINLESS", "no metal is set for the design; the powder priced is 316L",
                                          lambda m: m in METALS)
        if k != "STAINLESS":
            d["powder_price"] = R.material("lpbf.powder.", k)
    elif process == "cnc":
        d["density_g_cm3"], k = D.density("AL-6061", "no machinable material is set for the design",
                                          lambda m: (D.mat_info or {}).get("kind") == "engineering")
        d["material_key"] = k
        m = R.get("cnc.margin_mm")
        box = math.prod(s + 2 * m["value"] for s in D.size)
        d["stock_mm3"] = drv("stock_mm3", box, "mm³", "computed",
                             "bounding box " + " × ".join(f"{s:.1f}" for s in D.size) + f" mm + {m['value']:g} mm a side (assumed)",
                             "Stock volume")
        cyc = None
        try:
            from .. import cam
            if D.candidate:
                raise LookupError("a candidate has no CAM simulation")
            stt = cam.status(D.st, D.p)
            if stt.get("state") == "current" and stt.get("simulation", {}).get("cycle_time_s") is not None:
                cyc = drv("cycle_s", stt["simulation"]["cycle_time_s"], "s", "simulated",
                          f"the current CAM simulation ({stt.get('dialect')}), not proven on a machine", "Cycle time")
        except Exception:                        # noqa: BLE001
            cyc = None
        if cyc is None:
            mrr = R.get("cnc.mrr_cm3_min")
            removed = max(0.0, box - vol["value"])
            cyc = drv("cycle_s", removed / 1000 / mrr["value"] * 60, "s", "estimated",
                      f"removed {removed / 1000:.4g} cm³ / {mrr['value']:g} cm³/min (assumed; no current CAM simulation)", "Cycle time")
            D.notes.append("CNC: no current CAM simulation, so the cycle time is estimated from the removed volume; "
                           "cam_plan and cam_post give the simulated time.")
        d["cycle_s"] = cyc
        opts = {"tool_d": float(o.get("tool_d", 6)), "material": "metal" if D.mat in METALS else "plastic", **{
            k: v for k, v in o.items() if k in ("axes", "tool_d", "material")}}
        n = None
        try:
            res, meas = D.dfm("cnc", opts)
            n, state = _measure(meas, "setups")
            if n is not None:
                d["setups"] = drv("setups", n, "setups", "computed (manufacturability, B-rep)",
                                  f"the fewest setups for a {opts['tool_d']:g} mm cutter"
                                  + (f", measured on r{D.rev} (a candidate's sizes are taken not to change it)"
                                     if D.candidate else ""), "Setups")
        except Exception as e:                   # noqa: BLE001
            D.notes.append(f"CNC: setups not measured ({getattr(e, 'msg', e)}); one is assumed.")
        if n is None:
            d["setups"] = drv("setups", 1, "setups", "assumed", "manufacturability did not count setups", "Setups")
    elif process == "injection":
        resin = str(o.get("resin") or MATERIAL_RESIN.get(D.mat or "", "") or "ABS").upper()
        if not o.get("resin") and D.mat not in MATERIAL_RESIN:
            D.notes.append("Moulding: no resin is set; ABS is assumed (pass options.injection.resin).")
        d["resin"] = resin
        d["cavities"] = int(o.get("cavities") or 1)
        d["faces"] = D.faces()
        dopts = {"resin": RESIN_DFM.get(resin, "abs"), "cavities": d["cavities"]}
        if o.get("pull"):
            dopts["pull"] = o["pull"]
        try:
            res, meas = D.dfm("injection", dopts)
            data = res.get("data") or {}
            src = "manufacturability for injection (B-rep)"
            d["projected_mm2"] = drv("projected_mm2", data.get("projected_mm2"), "mm²", "computed (B-rep)",
                                     f"{src}, pull {data.get('pull_name', '')}", "Projected area")
            hmax, _s = _measure(meas, "wall_max_mm")
            d["wall_max_mm"] = drv("wall_max_mm", hmax, "mm", "computed (B-rep)", f"{src}: the thickest wall", "Thickest wall")
            d["side_actions"] = drv("side_actions", len(data.get("side_actions") or []), "side actions",
                                    "computed (B-rep)", src, "Side actions")
            pull = data.get("pull") or [0, 0, 1]
            ax = max(range(3), key=lambda i: abs(pull[i]))
            d["depth_mm"] = drv("depth_mm", D.size[ax], "mm", "computed (B-rep)", "bounding box along the pull", "Depth")
            d["plan_mm"] = sorted((D.size[i] for i in range(3) if i != ax), reverse=True)
            tons = (meas.get("tonnage_t") or {}).get("items") or []
            if tons:
                D.notes.append(f"Moulding: manufacturability's clamp estimate (RJG, 2-10 t/in²) is {tons[0]['start_kN']} kN "
                               f"(range {tons[0]['range_kN'][0]}-{tons[0]['range_kN'][1]} kN); the machine here is chosen by BDK's method.")
        except Exception as e:                   # noqa: BLE001
            for k in ("projected_mm2", "wall_max_mm", "side_actions", "depth_mm"):
                d[k] = drv(k, None, "", "missing", f"manufacturability for injection failed: {getattr(e, 'msg', e)}")
            d["plan_mm"] = None
        if o.get("resin_price") is not None:
            d["resin_price"] = {"id": "im.resin." + resin, "value": float(o["resin_price"]), "evidence": "specified",
                                "source": "given for this estimate", "unit": f"{R.currency}/kg"}
        if resin not in rates_mod.table().get("im_resin", {}):
            d["density_g_cm3"], _k = D.density("ABS", "no processing data for the resin", None)
    elif process == "sheet_metal":
        from .. import sheet
        from ..sheet import geom2d
        k = "aluminium" if (D.mat or "").startswith("AL-") else "steel"
        d["material_key"] = k
        d["density_g_cm3"], _k = D.density("AL-6061" if k == "aluminium" else "STEEL", "no sheet material is set",
                                           lambda m: m in METALS)
        try:
            u = sheet.unfolded(D.st, D.p, o.get("sheet") or None)
        except Exception as e:                   # noqa: BLE001
            u = {"ok": False, "reasons": [{"why": str(getattr(e, "msg", e))}]}
        if not u.get("ok"):
            why = "; ".join(r.get("why", "") for r in u.get("reasons") or []) or "it does not unfold"
            for kk in ("flat_mm2", "t_mm", "cut_mm", "pierces", "bends"):
                d[kk] = drv(kk, None, "", "missing", f"the design is not a sheet-metal part ({why})")
        else:
            src = "the sheet unfold (B-rep, folded back)"
            d["flat_mm2"] = drv("flat_mm2", u.get("area_mm2"), "mm²", "computed", src, "Flat area")
            d["t_mm"] = drv("t_mm", u.get("t"), "mm", "computed", src, "Thickness")
            d["cut_mm"] = drv("cut_mm", sum(geom2d.length(e) for e in u.get("entities") or []), "mm", "computed", src, "Cut length")
            d["pierces"] = drv("pierces", len(u.get("loops") or []), "contours", "computed", src, "Pierces")
            d["bends"] = drv("bends", len(u.get("bends") or []), "bends", "computed", src, "Bends")
    return d


# ---- one process, every process ---------------------------------------------------------------------------------

def _run(D: Design, process: str, R) -> dict:
    t = rates_mod.table()
    if process == "purchased":
        from .. import bom
        b = bom.build(D.st, D.p, made=False)
        return models.purchased([{"designation": g["designation"], "quantity": g["quantity"]} for g in b["purchased"]], R)
    d = drivers(D, process, R)
    if process == "injection":
        res = models.injection(d, R, t.get("im_resin", {}), t.get("im_machine", []))
    else:
        res = getattr(models, process)(d, R)
    res["drivers"] = {k: x for k, x in d.items() if isinstance(x, dict) and "evidence" in x}
    return res


def _finish(res: dict, quantities: list) -> dict:
    res["totals"] = models.totals(res, quantities)
    return res


def estimate(st, p: dict, process: str, quantities=None, options: dict | None = None, shop: str | None = None,
             currency: str | None = None, overrides: dict | None = None, candidate: dict | None = None,
             dfm_cache: dict | None = None) -> dict:
    """One process: its lines (fixed and per part), totals, and cost per part at each quantity."""
    pid = process_id(process)
    qs = clean_quantities(quantities)
    R = rates_mod.Rates(st.cfg, shop, currency, overrides)
    D = Design(st, p, options, candidate, dfm_cache)
    res = _finish(_run(D, pid, R), qs)
    return {"project": p["id"], "rev": D.rev, "shop": R.shop_id, "currency": R.currency, "quantities": qs,
            **res, "notes": res["notes"] + D.notes, "note": NOTE, "rates_digest": rates_mod.digest(),
            "computed_at": time.time()}


def default_processes(st, p: dict) -> list:
    """Processes worth comparing for this design: every printing technology, CNC and moulding, plus sheet metal when
    the design is (or says it is) a sheet-metal part."""
    from .. import dfm
    out = ["fdm", "sla", "sls", "mjf", "lpbf", "cnc", "injection"]
    if dfm.default_process(p) == "sheet_metal" or (p.get("process") or "") == "sheet_metal":
        out.append("sheet_metal")
    return out


def compare(st, p: dict, processes=None, quantities=None, options: dict | None = None, shop: str | None = None,
            currency: str | None = None, overrides: dict | None = None, candidate: dict | None = None,
            dfm_cache: dict | None = None) -> dict:
    """Cost per part against quantity for several processes, the cheapest at each quantity, and the crossovers
    ("moulding beats FDM above ~N parts"), every number with its evidence. Purchased parts are added to every route."""
    qs = clean_quantities(quantities)
    procs = [process_id(x) for x in (processes or default_processes(st, p))]
    procs = [x for x in procs if x != "purchased"]
    if candidate and processes is None:
        procs = [x for x in procs if x in CANDIDATE_PROCESSES]
    R = rates_mod.Rates(st.cfg, shop, currency, overrides)
    D = Design(st, p, options, candidate, dfm_cache)
    rows = {}
    for pr in procs:
        try:
            rows[pr] = _finish(_run(D, pr, R), qs)
        except Exception as e:                   # noqa: BLE001 - one process failing does not hide the others
            rows[pr] = {"process": pr, "label": LABELS[pr], "error": str(getattr(e, "msg", e)), "lines": [],
                        "totals": None}
    bought = _finish(_run(D, "purchased", R), qs)
    crossings = []
    for i, a in enumerate(procs):
        for b in procs[i + 1:]:
            ta, tb = (rows[a].get("totals"), rows[b].get("totals"))
            if not ta or not tb:
                continue
            for lo, hi in ((a, b), (b, a)):
                q = models.crossover(rows[lo]["totals"], rows[hi]["totals"])
                if q is not None and q >= 1:
                    crossings.append(_crossing(rows, lo, hi, q, R.currency))
    crossings.sort(key=lambda c: c["quantity"])
    cheapest = []
    for j, q in enumerate(qs):
        best = sorted(((r["totals"]["curve"][j]["per_part"], pr) for pr, r in rows.items() if r.get("totals")
                       and r["totals"]["complete"]), key=lambda x: x[0])
        cheapest.append({"quantity": q, "process": best[0][1] if best else None,
                         "per_part": round(best[0][0], 4) if best else None,
                         "complete_only": True})
    full = {pr: r["totals"] for pr, r in rows.items() if r.get("totals") and r["totals"]["complete"]}
    switches = [{**_crossing(rows, a, b, q, R.currency), "on_cheapest": True} for a, b, q in models.envelope(full)]
    return {"project": p["id"], "rev": D.rev, "shop": R.shop_id, "currency": R.currency, "quantities": qs,
            "processes": rows, "purchased": bought, "crossovers": crossings, "cheapest": cheapest,
            "switches": switches, "cheapest_at_1": cheapest[0]["process"] if qs[0] == 1 else None,
            "notes": D.notes, "note": NOTE + " Crossovers use counted lines only; a process with lines not counted "
                                              "says so beside its crossing.",
            "rates_digest": rates_mod.digest(), "computed_at": time.time()}


def _crossing(rows, lo, hi, q, cur) -> dict:
    a, b = rows[lo], rows[hi]
    ta, tb = a["totals"], b["totals"]
    ev = sorted({e for r in (a, b) for ln in r["lines"] if ln["amount"] is not None for e in ln["evidence"]})
    partial = [f"{r['label']}: {', '.join(r['totals']['not_counted'])}" for r in (a, b) if r["totals"]["not_counted"]]
    n = math.ceil(q)
    return {"cheaper_above": hi, "than": lo, "quantity": round(q, 2), "from_part": n,
            "text": f"{LABELS[hi]} costs less per part than {LABELS[lo]} from about {f'{n:,}'.replace(',', ' ')} parts",
            "math": (f"({tb['fixed']:.2f} − {ta['fixed']:.2f}) / ({ta['per_part_variable']:.4f} − "
                     f"{tb['per_part_variable']:.4f}) = {q:.1f} parts ({cur})"),
            "evidence": ev, "assumed_share": {lo: ta["assumed_share"], hi: tb["assumed_share"]},
            **({"not_counted": partial} if partial else {})}


# ---- for optimise and inverse design (wave AB) ----------------------------------------------------------------

def point(st, p: dict, process: str = "auto", quantity: int = 1, options: dict | None = None, shop: str | None = None,
          currency: str | None = None, candidate: dict | None = None, dfm_cache: dict | None = None,
          complete_only: bool = True) -> dict:
    """Cost per part at `quantity` with how it is known: {value (None when it cannot be costed in full: never a
    guess), process, currency, shop, evidence (the classes of the counted lines' inputs: sourced, specified, assumed,
    computed, simulated, estimated), assumed_share, not_counted, rates_digest}. process "auto" is the cheapest
    process whose lines are all counted (for a candidate: of CANDIDATE_PROCESSES)."""
    q = int(quantity)
    if process in ("auto", "", None):
        r = compare(st, p, None, [q], options, shop, currency, candidate=candidate, dfm_cache=dfm_cache)
        c = r["cheapest"][0]
        row = r["processes"].get(c["process"]) if c["process"] else None
        val, pid = c["per_part"], c["process"]
    else:
        pid = process_id(process)
        row = estimate(st, p, pid, [q], options, shop, currency, candidate=candidate, dfm_cache=dfm_cache)
        r = row
        val = row["totals"]["curve"][0]["per_part"]
        if complete_only and not row["totals"]["complete"]:
            val = None
    tot = (row or {}).get("totals") or {}
    ev = sorted({e for ln in (row or {}).get("lines", []) if ln.get("amount") is not None for e in ln["evidence"]})
    return {"value": val, "process": pid, "label": LABELS.get(pid) if pid else None, "quantity": q,
            "currency": r["currency"], "shop": r["shop"], "evidence": ev, "assumed_share": tot.get("assumed_share"),
            "not_counted": tot.get("not_counted") or [], "rates_digest": rates_mod.digest()}


def cost(st, p: dict, process: str = "auto", quantity: int = 1, options: dict | None = None, shop: str | None = None,
         currency: str | None = None, complete_only: bool = True, candidate: dict | None = None,
         dfm_cache: dict | None = None) -> float | None:
    """Cost per part at `quantity` in the shop's currency, for an objective: one process, or "auto" for the cheapest
    process whose lines are all counted. None when nothing can be costed in full (never a guess)."""
    return point(st, p, process, quantity, options, shop, currency, candidate, dfm_cache, complete_only)["value"]


def objective(process: str = "auto", quantity: int = 1, **kw):
    """A callable (st, p, candidate=None) -> float | None for optimise / a Pareto front: cost per part at a
    quantity. f.point(st, p, candidate=None) returns the value with its evidence (see point())."""
    def f(st, p, candidate=None):
        return cost(st, p, process, quantity, candidate=candidate, **kw)

    def pt(st, p, candidate=None):
        return point(st, p, process, quantity, candidate=candidate, **kw)
    f.__name__ = f"cost_{process}_{quantity}"
    f.unit = "per part"
    f.point = pt
    f.process, f.quantity = process, int(quantity)
    return f


# ---- summaries ----------------------------------------------------------------------------------------------------

def brief(res: dict) -> dict:
    """A compact result for MCP and the CLI: totals, the curve, what is not counted, and the lines without inputs."""
    def one(r):
        if not r.get("totals"):
            return {k: r.get(k) for k in ("process", "label", "error")}
        return {"process": r["process"], "label": r["label"], "fixed": r["totals"]["fixed"],
                "per_part_variable": r["totals"]["per_part_variable"], "curve": r["totals"]["curve"],
                "not_counted": r["totals"]["not_counted"], "assumed_share": r["totals"]["assumed_share"],
                "lines": [{k: ln.get(k) for k in ("item", "basis", "amount", "formula", "evidence", "needs") if ln.get(k) is not None}
                          for ln in r["lines"]], **({k: r[k] for k in ("clamp_kN", "cycle_s", "resin", "cavities") if k in r})}
    if "processes" in res:
        return {**{k: res[k] for k in ("project", "rev", "shop", "currency", "quantities", "switches", "crossovers",
                                       "cheapest", "notes", "note")},
                "processes": {k: one(r) for k, r in res["processes"].items()}, "purchased": one(res["purchased"])}
    return {**{k: res[k] for k in ("project", "rev", "shop", "currency", "quantities", "notes", "note") if k in res}, **one(res)}


def headline(res: dict) -> str:
    cur = res["currency"]
    ch = [c for c in res.get("cheapest", []) if c["process"]]
    bits = [f"{c['quantity']}: {LABELS[c['process']].split(' (')[0]} {c['per_part']:.2f} {cur}" for c in ch[:1] + ch[-1:]]
    x = res.get("switches") or []
    return " · ".join(bits) + "".join(f" · {s['text']}" for s in x[:2])


# ---- the Bench (form/studies.py registers a provider's register_studies) ------------------------------------------

def _bench_key(ctx) -> str:
    from ..studio import H
    sh = rates_mod.shops(ctx.st.cfg)
    cam_k = (ctx.p.get("cam") or {}).get("sim_key")
    return H("cost-process", VERSION, ctx.keys["geometry"], rates_mod.digest(), sh, ctx.p.get("appearance"),
             ctx.p.get("material"), ctx.p.get("process"), cam_k, ctx.keys.get("slice"))


def _bench_run(ctx) -> dict:
    opts = getattr(ctx, "opts", None) or {}
    res = compare(ctx.st, ctx.p, opts.get("processes"), opts.get("quantities"), opts.get("options"))
    b = brief(res)
    return {"headline": headline(res), "evidence": "sourced × specified × assumed (each line says which)",
            "detail": "; ".join(c["text"] for c in res["switches"]) or "The cheapest process does not change with quantity.",
            "data": b}


def register_studies(register) -> None:
    """The Bench's "Cost" entry in Make: every process's cost per part against quantity, with the crossovers."""
    from ..studies import Study
    register(Study("cost.process", "route", "Cost per process",
                   "Cost per part against quantity for printing, CNC, moulding and sheet metal, each rate sourced and "
                   "dated, yours, or labelled assumed; where one process overtakes another.",
                   "sourced × specified × assumed", run=_bench_run, key=_bench_key,
                   inputs=("geometry", "materials", "rates table", "your shop's rates", "slice", "CAM simulation"),
                   tool="estimate_cost", heavy=True, order=90))     # after every process's route, before Release
