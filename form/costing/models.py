"""The cost models, one per process, as plain functions of their drivers and the shop's rates.

Each model returns lines, each either **fixed** (once per order: tooling, setups, programming) or **per part**, with
the formula written out with its numbers, the amount in the shop's currency, and the evidence of every input. A line
whose input has no value (a money rate nobody published and the person has not set, a driver that was not measured)
has amount None and says what it needs; the totals then list it under ``not_counted`` and never guess it.

Drivers are dicts ``{"value": x, "evidence": "...", "source": "..."}`` (mm, mm², mm³, s, g) gathered by
form/costing/__init__.py from the design: the B-rep (volume, area, bounding box, faces), the slicer (grams, time),
manufacturability (projected area, walls, setups, side actions), CAM (cycle time), the sheet unfold (flat area, cut
length, bends) and the parts list. Everything here is arithmetic, so each model is checked against a hand calculation
in tests/test_costing.py.

Injection moulding follows Boothroyd, Dewhurst and Knight, *Product Design for Manufacture and Assembly*, ch. 8:
clamp force from the projected shot area and half the injection pressure; the smallest machine of Table 8.4 that
holds it; cycle = fill (Eq. 8.3) + cooling (Eq. 8.5) + resetting (Eq. 8.7); mould = mould base (Eq. 8.8) + cavity and
core points (Eqs. 8.10, 8.11, 8.13, side-pulls, finish) × the mould maker's rate, × n^0.7 for n cavities (Eq. 8.16).
"""
from __future__ import annotations

import math

LABELS = {"fdm": "FDM printing", "sla": "Resin printing (SLA)", "sls": "Powder bed (SLS)", "mjf": "Multi Jet Fusion (MJF)",
          "lpbf": "Metal printing (LPBF)", "cnc": "CNC milling, 3-axis", "injection": "Injection moulding",
          "sheet_metal": "Sheet metal (laser and brake)", "purchased": "Purchased parts"}
PROCESSES = ("fdm", "sla", "sls", "mjf", "lpbf", "cnc", "injection", "sheet_metal")


class Ledger:
    """Lines of one process, in one currency."""

    def __init__(self, process: str, currency: str):
        self.process, self.currency = process, currency
        self.lines: list = []
        self.notes: list = []

    def add(self, item: str, basis: str, amount, formula: str, inputs: list, needs: str | None = None) -> dict:
        ins = [_brief(x) for x in inputs if x is not None]
        miss = [x for x in inputs if x is not None and x.get("value") is None]
        if miss and needs is None:
            needs = "; ".join(sorted({m.get("needs") or f"{m.get('id')} has no value" for m in miss}))
        if amount is not None and not math.isfinite(float(amount)):
            amount = None
        ln = {"item": item, "basis": basis, "amount": None if (miss or amount is None) else round(float(amount), 6),
              "currency": self.currency, "formula": formula, "evidence": sorted({i["evidence"] for i in ins}),
              "inputs": ins}
        if needs and ln["amount"] is None:
            ln["needs"] = needs
        self.lines.append(ln)
        return ln

    def result(self, extra: dict | None = None) -> dict:
        return {"process": self.process, "label": LABELS.get(self.process, self.process), "currency": self.currency,
                "lines": self.lines, "notes": self.notes, **(extra or {})}


def _brief(x: dict) -> dict:
    keep = ("id", "label", "value", "unit", "evidence", "source", "why", "applies", "quote", "url", "converted",
            "value_original", "currency_original", "source_note", "needs")
    return {k: x[k] for k in keep if k in x and x[k] is not None}


def drv(did: str, value, unit: str, evidence: str, source: str = "", label: str = "") -> dict:
    """A driver: a quantity measured on the design (or estimated), with how it is known."""
    d = {"id": did, "label": label or did, "value": None if value is None else float(value), "unit": unit,
         "evidence": evidence}
    if source:
        d["source"] = source
    if value is None:
        d["needs"] = source or f"{did} was not measured"
    return d


def v(x) -> float:
    return x["value"] if x and x.get("value") is not None else float("nan")


def _ok(*xs) -> bool:
    return all(x is not None and x.get("value") is not None for x in xs)


def _f(x: float, n: int = 4) -> str:
    return f"{x:.{n}g}" if isinstance(x, (int, float)) and math.isfinite(x) else "?"


# ---- additive ---------------------------------------------------------------------------------------------------

def fdm(d: dict, R) -> dict:
    """material (grams × price/kg) + machine (hours × (printer price / life hours)) + electricity + labour."""
    L = Ledger("fdm", R.currency)
    g, h = d.get("grams"), d.get("hours")
    price = d.get("price_per_kg") or R.material("fdm.material.", d.get("material_key") or "PLA")
    L.add("Filament", "part", v(g) / 1000 * v(price), f"{_f(v(g))} g / 1000 × {_f(v(price))} {R.currency}/kg", [g, price])
    pp, life = R.get("fdm.printer_price"), R.get("fdm.life_h")
    L.add("Printer time (write-off)", "part", v(h) * v(pp) / v(life),
          f"{_f(v(h))} h × {_f(v(pp))} {R.currency} / {_f(v(life))} h", [h, pp, life])
    w, el = R.get("fdm.power_w"), R.get("electricity")
    L.add("Electricity", "part", v(w) / 1000 * v(h) * v(el), f"{_f(v(w))} W / 1000 × {_f(v(h))} h × {_f(v(el))} {R.currency}/kWh",
          [w, h, el])
    _labour(L, R, "fdm.post_min", "Labour per part (supports, check)")
    _setup(L, R, "print.setup_min", "Build job setup")
    return L.result()


def _labour(L, R, rid: str, item: str, hours_key: bool = False):
    t, lab = R.get(rid), R.get("labour")
    hrs = v(t) if hours_key else v(t) / 60
    L.add(item, "part", hrs * v(lab), f"{_f(v(t))} {'h' if hours_key else 'min / 60'} × {_f(v(lab))} {R.currency}/h", [t, lab])


def _setup(L, R, rid: str, item: str, count=None):
    t, lab = R.get(rid), R.get("labour")
    n = v(count) if count is not None else 1.0
    txt = f"{_f(n)} × " if count is not None else ""
    L.add(item, "fixed", n * v(t) / 60 * v(lab), f"{txt}{_f(v(t))} min / 60 × {_f(v(lab))} {R.currency}/h",
          [count, t, lab] if count is not None else [t, lab])


def _machine_from_price(L, R, hours, price_id, life_id, item):
    pp, life = R.get(price_id), R.get(life_id)
    L.add(item, "part", v(hours) * v(pp) / v(life), f"{_f(v(hours))} h × {_f(v(pp))} {R.currency} / {_f(v(life))} h",
          [hours, pp, life])


def sla(d: dict, R) -> dict:
    """resin (volume × support factor × price/L) + machine (volume / build rate × write-off) + labour."""
    L = Ledger("sla", R.currency)
    vol, sf, pr = d["volume_mm3"], R.get("sla.support_factor"), R.get("sla.resin_per_l")
    L.add("Resin", "part", v(vol) / 1e6 * v(sf) * v(pr),
          f"{_f(v(vol) / 1000)} cm³ / 1000 × {_f(v(sf))} × {_f(v(pr))} {R.currency}/L", [vol, sf, pr])
    rate = R.get("sla.rate_cm3_h")
    hours = drv("hours", v(vol) / 1000 / v(rate) if _ok(vol, rate) else None, "h", "estimated",
                f"volume / {_f(v(rate))} cm³/h (assumed)", "Print hours")
    _machine_from_price(L, R, hours, "sla.printer_price", "sla.life_h", "Printer time (write-off)")
    _labour(L, R, "sla.post_min", "Labour per part (wash, cure, supports)")
    _setup(L, R, "print.setup_min", "Build job setup")
    return L.result({"hours": hours})


def _powder(process: str, d: dict, R, price_id: str, factor_id: str, rate_id: str) -> tuple:
    L = Ledger(process, R.currency)
    vol, dens = d["volume_mm3"], d["density_g_cm3"]
    pf, pr = R.get(factor_id), R.get(price_id)
    grams = v(vol) / 1000 * v(dens)
    L.add("Powder", "part", grams / 1000 * v(pf) * v(pr),
          f"{_f(v(vol) / 1000)} cm³ × {_f(v(dens))} g/cm³ / 1000 × {_f(v(pf))} × {_f(v(pr))} {R.currency}/kg",
          [vol, dens, pf, pr])
    rate = R.get(rate_id)
    hours = drv("hours", v(vol) / 1000 / v(rate) if _ok(vol, rate) else None, "h",
                "estimated" if rate.get("evidence") == "assumed" else "computed",
                f"volume / {_f(v(rate))} cm³/h ({rate.get('evidence')})", "Build hours")
    return L, hours, rate


def sls(d: dict, R) -> dict:
    L, hours, _r = _powder("sls", d, R, "sls.powder_per_kg", "sls.powder_factor", "sls.rate_cm3_h")
    _machine_from_price(L, R, hours, "sls.printer_price", "sls.life_h", "Printer time (write-off)")
    _labour(L, R, "powder.post_min", "Labour per part (depowder, blast)")
    _setup(L, R, "print.setup_min", "Build job setup")
    return L.result({"hours": hours})


def mjf(d: dict, R) -> dict:
    L, hours, _r = _powder("mjf", d, R, "mjf.powder_per_kg", "mjf.powder_factor", "mjf.rate_cm3_h")
    m = R.get("mjf.machine_per_h")
    L.add("Machine time", "part", v(hours) * v(m), f"{_f(v(hours))} h × {_f(v(m))} {R.currency}/h", [hours, m])
    _labour(L, R, "powder.post_min", "Labour per part (depowder, blast)")
    _setup(L, R, "print.setup_min", "Build job setup")
    return L.result({"hours": hours})


def lpbf(d: dict, R) -> dict:
    L, hours, _r = _powder("lpbf", d, R, "lpbf.powder_per_kg", "lpbf.powder_factor", "lpbf.rate_cm3_h")
    m = R.get("lpbf.machine_per_h")
    L.add("Machine time", "part", v(hours) * v(m), f"{_f(v(hours))} h × {_f(v(m))} {R.currency}/h", [hours, m])
    _labour(L, R, "lpbf.post_h", "Labour per part (plate, supports, handling)", hours_key=True)
    _setup(L, R, "print.setup_min", "Build job setup")
    return L.result({"hours": hours})


# ---- CNC --------------------------------------------------------------------------------------------------------

def cnc(d: dict, R) -> dict:
    """stock + setups × setup time + cycle time × (machine + operator) + tool wear; programming once."""
    L = Ledger("cnc", R.currency)
    box, dens = d["stock_mm3"], d["density_g_cm3"]
    sp = d.get("stock_price") or R.material("cnc.stock.", d.get("material_key"))
    kg = v(box) / 1000 * v(dens) / 1000
    L.add("Stock", "part", kg * v(sp), f"{_f(v(box) / 1000)} cm³ × {_f(v(dens))} g/cm³ = {_f(kg)} kg × {_f(v(sp))} {R.currency}/kg",
          [box, dens, sp])
    cyc, mach, lab = d["cycle_s"], R.get("cnc.machine_per_h"), R.get("labour")
    run = v(cyc) / 3600 * (v(mach) + v(lab))
    L.add("Machining", "part", run, f"{_f(v(cyc))} s / 3600 × ({_f(v(mach))} + {_f(v(lab))}) {R.currency}/h", [cyc, mach, lab])
    tw = R.get("cnc.tool_wear")
    L.add("Tool wear", "part", run * v(tw), f"{_f(v(tw))} × machining", [cyc, mach, lab, tw])
    _setup(L, R, "cnc.setup_min", "Setups", d["setups"])
    _setup(L, R, "cnc.program_min", "Programming (once)")
    return L.result()


# ---- injection moulding -----------------------------------------------------------------------------------------

def im_machine(table: list, clamp_kN: float, shot_cm3: float) -> dict | None:
    """The smallest machine of BDK Table 8.4 whose clamp force and shot size are enough, else None."""
    ok = [m for m in sorted(table, key=lambda m: m["clamp_kN"]) if m["clamp_kN"] >= clamp_kN and m["shot_cm3"] >= shot_cm3]
    return ok[0] if ok else None


def cooling_s(h_mm: float, alpha: float, Ti: float, Tm: float, Tx: float) -> float:
    """BDK Eq. 8.5 (the first term of the series solution, Ballman and Shusman):
    t_c = h² / (π² α) · ln[(4/π) (Ti − Tm) / (Tx − Tm)], h in mm, α in mm²/s."""
    return h_mm ** 2 / (math.pi ** 2 * alpha) * math.log(4 / math.pi * (Ti - Tm) / (Tx - Tm))


def fill_s(shot_cm3: float, p_bar: float, power_kW: float) -> float:
    """BDK Eq. 8.3: t_f = 2 V_s p_j / P_j (V_s m³, p_j N/m², P_j W)."""
    return 2 * shot_cm3 * 1e-6 * p_bar * 1e5 / (power_kW * 1e3)


def reset_s(depth_cm: float, dry_cycle_s: float, stroke_cm: float) -> float:
    """BDK Eq. 8.7: t_r = 1 + 1.75 t_d [(2D + 5) / L_s]^½."""
    return 1 + 1.75 * dry_cycle_s * math.sqrt((2 * depth_cm + 5) / stroke_cm)


def mould_base_usd(plate_area_cm2: float, plate_thick_cm: float) -> float:
    """BDK Eq. 8.8: C_b = 1000 + 0.45 A_c h_p^0.4 (US dollars of the book's date)."""
    return 1000 + 0.45 * plate_area_cm2 * plate_thick_cm ** 0.4


def plate(len_cm: float, wid_cm: float, cavities: int, side_actions: int) -> tuple[float, float, int, int]:
    """Cavity plate size: the cavities in a near-square grid with 7.5 cm between them and to the edges (BDK); each
    side action needs 7.5 cm more on its side (up to four). Returns (length, width, columns, rows) in cm."""
    n = max(1, int(cavities))
    cols = math.ceil(math.sqrt(n)) if side_actions < 2 else n          # two side-pulls: one row (BDK)
    rows = math.ceil(n / cols)
    a = cols * len_cm + (cols + 1) * 7.5 + 7.5 * min(side_actions, 2)
    b = rows * wid_cm + (rows + 1) * 7.5 + 7.5 * max(0, min(side_actions, 4) - 2)
    return a, b, cols, rows


def injection(d: dict, R, resins: dict, machines: list) -> dict:
    L = Ledger("injection", R.currency)
    n = int(d.get("cavities") or 1)
    resin_id = d.get("resin") or "ABS"
    rz = resins.get(resin_id)
    Ap, vol, hmax, depth = d["projected_mm2"], d["volume_mm3"], d["wall_max_mm"], d["depth_mm"]
    size = d["plan_mm"]                                     # part size across the pull, mm [a, b]
    sides = int(v(d["side_actions"])) if _ok(d["side_actions"]) else 0
    runner = R.get("im.runner_fraction")
    usd = R.fx("USD")[0]
    usd_how = R.fx("USD")[1]
    usd_d = drv("fx_usd", usd, f"{R.currency}/USD", (usd_how or {}).get("evidence", "identity") if usd else "missing",
                (usd_how or {}).get("rate", "") if usd else f"an exchange rate between USD and {R.currency}",
                "USD to the shop's currency") if R.currency != "USD" else drv("fx_usd", 1.0, "1", "identity")
    out: dict = {"resin": resin_id, "cavities": n}
    if rz is None:
        L.notes.append(f"No processing data for {resin_id} in BDK Table 8.5: cycle time not estimated. Resins with "
                       "data: " + ", ".join(sorted(resins)) + ".")
    # clamp, shot, machine
    if _ok(Ap, vol, runner) and rz:
        shot_area = n * v(Ap) / 100 * (1 + v(runner))                         # cm²
        clamp = shot_area * rz["p_bar"] * 0.5 / 100                             # kN: cm² × bar × 10 N/cm²/bar / 1000
        shot = n * v(vol) / 1000 * (1 + v(runner))                              # cm³
        mach = im_machine(machines, clamp, shot)
        out.update(clamp_kN=round(clamp, 1), shot_cm3=round(shot, 2),
                   clamp_formula=f"{n} × {_f(v(Ap) / 100)} cm² × (1 + {_f(v(runner))}) × ({rz['p_bar']} bar / 2) / 100 = {_f(clamp)} kN",
                   machine=mach)
        if mach is None:
            L.notes.append(f"No machine in BDK Table 8.4 holds {clamp:.0f} kN and {shot:.0f} cm³: fewer cavities.")
    else:
        mach = None
    # cycle
    if mach and _ok(hmax, depth):
        tf = fill_s(out["shot_cm3"], rz["p_bar"], mach["power_kW"])
        tc = cooling_s(v(hmax), rz["alpha"], rz["Ti"], rz["Tm"], rz["Tx"])
        tr = reset_s(v(depth) / 10, mach["dry_cycle_s"], mach["stroke_cm"])
        out.update(fill_s=round(tf, 3), cooling_s=round(tc, 3), reset_s=round(tr, 3), cycle_s=round(tf + tc + tr, 3),
                   cycle_formula=(f"fill 2 × {_f(out['shot_cm3'])} cm³ × {rz['p_bar']} bar / {mach['power_kW']} kW = {_f(tf)} s; "
                                  f"cooling {_f(v(hmax))}² / (π² × {rz['alpha']}) × ln(4/π × ({rz['Ti']} − {rz['Tm']}) / "
                                  f"({rz['Tx']} − {rz['Tm']})) = {_f(tc)} s; resetting 1 + 1.75 × {mach['dry_cycle_s']} × "
                                  f"√((2 × {_f(v(depth) / 10)} + 5) / {mach['stroke_cm']}) = {_f(tr)} s"))
        cyc = drv("cycle_s", out["cycle_s"], "s", "computed (BDK Eqs. 8.3, 8.5, 8.7)", out["cycle_formula"], "Cycle time")
        mrate = drv("im.machine_rate", mach["rate_usd_h"] * usd if usd else None, f"{R.currency}/h", "sourced",
                    f"BDK Table 8.4: {mach['clamp_kN']} kN at {mach['rate_usd_h']} USD/h (book date)", "Machine rate")
        L.add("Moulding machine", "part", v(cyc) / 3600 * v(mrate) / n,
              f"{_f(v(cyc))} s / 3600 × {_f(v(mrate))} {R.currency}/h / {n} cavit{'y' if n == 1 else 'ies'}", [cyc, mrate, usd_d])
        op, lab = R.get("im.operator_share"), R.get("labour")
        if v(op) > 0:
            L.add("Operator", "part", v(cyc) / 3600 * v(op) * v(lab) / n,
                  f"{_f(v(cyc))} s / 3600 × {_f(v(op))} × {_f(v(lab))} {R.currency}/h / {n}", [cyc, op, lab])
    else:
        L.add("Moulding machine", "part", None, "cycle time × machine rate / cavities", [hmax, depth],
              needs=("the thickest wall and the part depth (manufacturability for injection)" if not _ok(hmax, depth)
                     else "a machine and processing data for this resin"))
    # material
    rp = d.get("resin_price") or R.material("im.resin.", resin_id)
    sg = drv("sg", rz["sg"] if rz else d.get("density_g_cm3", {}).get("value") if d.get("density_g_cm3") else None,
             "g/cm³", "sourced" if rz else (d.get("density_g_cm3") or {}).get("evidence", "missing"),
             "BDK Table 8.5" if rz else (d.get("density_g_cm3") or {}).get("source", ""), "Specific gravity")
    L.add("Resin", "part", v(vol) / 1000 * v(sg) / 1000 * v(rp),
          f"{_f(v(vol) / 1000)} cm³ × {_f(v(sg))} g/cm³ / 1000 × {_f(v(rp))} {R.currency}/kg", [vol, sg, rp])
    L.notes.append("Runner material is taken as reground; scrap, colourant and packing are not counted.")
    # mould
    if _ok(Ap, depth) and size:
        a, b, cols, rows = plate(size[0] / 10, size[1] / 10, n, sides)
        Ac, hp = a * b, v(depth) / 10 + 15
        cb = mould_base_usd(Ac, hp)
        out["mould_base"] = {"plate_cm": [round(a, 2), round(b, 2)], "grid": [cols, rows], "Ac_cm2": round(Ac, 2),
                             "hp_cm": round(hp, 2), "usd": round(cb, 2)}
        base_d = drv("im.mould_base", cb, "USD", "computed (BDK Eq. 8.8)",
                     f"1000 + 0.45 × {_f(Ac)} cm² × {_f(hp)}^0.4 cm = {_f(cb)} USD", "Mould base")
        L.add("Mould base", "fixed", cb * usd if usd else None, f"{_f(cb)} USD × {_f(usd)} {R.currency}/USD", [base_d, usd_d])
        apc = v(Ap) / 100
        faces = d.get("faces")
        X = 0.01 * v(faces) if _ok(faces) else float("nan")
        me = 2.5 * apc ** 0.5
        ex = R.get("im.cavity_exponent")
        mpo = 5 + 0.085 * apc ** v(ex)
        mx = 45 * X ** 1.27
        fin = R.get("im.appearance")
        pts = me + mx + mpo + 65 * sides + v(fin) * (mx + mpo)
        out["points"] = {"ejection": round(me, 3), "complexity": round(mx, 3), "X": X, "area": round(mpo, 3),
                         "side_pulls": 65 * sides, "finish": round(v(fin) * (mx + mpo), 3), "total": round(pts, 3)}
        pts_d = drv("im.points", pts if math.isfinite(pts) else None, "h", "computed (BDK Eqs. 8.10, 8.11, 8.13)",
                    f"ejection 2.5 × {_f(apc)}^0.5 = {_f(me)}; complexity 45 × {_f(X)}^1.27 = {_f(mx)} (X = 0.01 × "
                    f"{_f(v(faces))} faces, estimated); area 5 + 0.085 × {_f(apc)}^{_f(v(ex))} = {_f(mpo)}; side-pulls 65 × "
                    f"{sides}; finish {_f(v(fin))} × ({_f(mx)} + {_f(mpo)})", "Cavity and core hours")
        mm, mexp = R.get("im.mould_maker_per_h"), R.get("im.multicavity_m")
        L.add("Cavities and cores", "fixed", v(pts_d) * v(mm) * n ** v(mexp),
              f"{_f(v(pts_d))} h × {_f(v(mm))} {R.currency}/h × {n}^{_f(v(mexp))}", [pts_d, faces, mm, mexp, ex, fin])
        L.notes.append("Complexity counts every B-rep face as one surface patch (X = 0.01 per face); holes and "
                       "depressions are not counted apart. Mould costs are in the book's dollars, not adjusted for inflation.")
    else:
        L.add("Mould", "fixed", None, "mould base + cavities and cores", [Ap, depth],
              needs="the projected area and depth (manufacturability for injection)")
    return L.result(out)


# ---- sheet metal ------------------------------------------------------------------------------------------------

def sheet_metal(d: dict, R) -> dict:
    """material (flat area × t × utilisation × density × price/kg) + cut (length / speed + pierces) × laser rate
    + bends × time per bend × (brake + operator); setup once per batch."""
    L = Ledger("sheet_metal", R.currency)
    area, t, dens = d["flat_mm2"], d["t_mm"], d["density_g_cm3"]
    ut = R.get("sheet.utilisation")
    pr = d.get("sheet_price") or R.material("sheet.material.", d.get("material_key") or "steel")
    kg = v(area) * v(t) / 1000 * v(ut) * v(dens) / 1000
    L.add("Sheet", "part", kg * v(pr), f"{_f(v(area))} mm² × {_f(v(t))} mm × {_f(v(ut))} × {_f(v(dens))} g/cm³ = {_f(kg)} kg "
          f"× {_f(v(pr))} {R.currency}/kg", [area, t, ut, dens, pr])
    cut, pierces = d["cut_mm"], d["pierces"]
    sp, ps, lr = R.get("sheet.cut_mm_min"), R.get("sheet.pierce_s"), R.get("sheet.laser_per_h")
    secs = v(cut) / v(sp) * 60 + v(pierces) * v(ps)
    L.add("Laser cutting", "part", secs / 3600 * v(lr),
          f"({_f(v(cut))} mm / {_f(v(sp))} mm/min × 60 + {_f(v(pierces))} × {_f(v(ps))} s) / 3600 × {_f(v(lr))} {R.currency}/h",
          [cut, sp, pierces, ps, lr])
    nb, bs, br, lab = d["bends"], R.get("sheet.bend_s"), R.get("sheet.brake_per_h"), R.get("labour")
    if _ok(nb) and v(nb) == 0:
        L.add("Bending", "part", 0.0, "no bends", [nb])
    else:
        L.add("Bending", "part", v(nb) * v(bs) / 3600 * (v(br) + v(lab)),
              f"{_f(v(nb))} × {_f(v(bs))} s / 3600 × ({_f(v(br))} + {_f(v(lab))}) {R.currency}/h", [nb, bs, br, lab])
    _setup(L, R, "sheet.setup_min", "Batch setup")
    return L.result()


# ---- purchased parts --------------------------------------------------------------------------------------------

def purchased(items: list, R) -> dict:
    L = Ledger("purchased", R.currency)
    for it in items:
        q = drv("qty", it["quantity"], "each", "computed", "the parts list (form/bom.py)", "Quantity")
        pr = R.part_price(it["designation"])
        L.add(it["designation"], "part", v(q) * v(pr), f"{int(v(q))} × {_f(v(pr))} {R.currency}", [q, pr])
    if not items:
        L.notes.append("Nothing to buy: no standard parts are placed or declared.")
    return L.result()


# ---- totals and curves ------------------------------------------------------------------------------------------

def totals(res: dict, quantities: list) -> dict:
    """Fixed and per-part sums of the counted lines, and cost per part at each quantity: fixed / q + per part.
    assumed_share: the share of the counted amount (fixed + one part) in lines with at least one assumed input."""
    fixed = [ln for ln in res["lines"] if ln["basis"] == "fixed"]
    part = [ln for ln in res["lines"] if ln["basis"] == "part"]
    F = sum(ln["amount"] for ln in fixed if ln["amount"] is not None)
    V = sum(ln["amount"] for ln in part if ln["amount"] is not None)
    missing = [ln["item"] for ln in res["lines"] if ln["amount"] is None]
    touched = sum(ln["amount"] or 0 for ln in res["lines"] if "assumed" in ln["evidence"])
    curve = [{"quantity": int(q), "per_part": round(F / q + V, 6), "order": round(F + V * q, 4)} for q in quantities]
    return {"fixed": round(F, 4), "per_part_variable": round(V, 6), "curve": curve, "not_counted": missing,
            "complete": not missing,
            "assumed_share": round(touched / (F + V), 4) if (F + V) > 0 else None}


def crossover(a: dict, b: dict) -> float | None:
    """The quantity above which b costs less per part than a (fixed / q + per part), or None when they never cross
    in that direction. a and b are totals() results."""
    Fa, Va, Fb, Vb = a["fixed"], a["per_part_variable"], b["fixed"], b["per_part_variable"]
    if Vb >= Va or Fb <= Fa:
        return None                       # b is never cheaper per part at volume, or already cheaper at q = 1
    return (Fb - Fa) / (Va - Vb)


def envelope(tot: dict) -> list:
    """Where the cheapest process changes as quantity grows: [(from, to, quantity), ...] along the lower envelope of
    per-part cost (fixed / q + per part) of the processes given ({process: totals()}), starting at one part."""
    if not tot:
        return []
    cur = min(tot, key=lambda k: tot[k]["fixed"] + tot[k]["per_part_variable"])
    q0, out = 1.0, []
    while True:
        nxt = [(q, k) for k in tot if k != cur for q in [crossover(tot[cur], tot[k])] if q is not None and q >= q0]
        if not nxt:
            return out
        q, k = min(nxt)
        out.append((cur, k, q))
        cur, q0 = k, q
