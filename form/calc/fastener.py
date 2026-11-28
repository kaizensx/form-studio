"""Bolted joints sized from the load: a simplified but correct core of VDI 2230 Part 1, and bosses with heat-set inserts.

What is computed as the guideline states it:

    permissible assembly preload   F_Mzul = A_0 · ν · R_p0.2 / √(1 + 3 · [(3/2) · (d_2/d_0) · (P/(π d_2) + 1.155 μ_G)]²)
    tightening torque              M_A = F_M · [0.16 P + 0.58 d_2 μ_G + (D_Km / 2) μ_K]
    clamp load against slipping    F_Kerf = F_Q / (q_F · μ_T)
    preload wanted                 F_Mmin = F_Kerf + (1 − Φ) F_A + F_Z,   F_Mmax = α_A · F_Mmin  ≤  F_Mzul
    working stress                 σ_red = √(σ_z² + 3 (k_τ τ)²),  σ_z = (F_Mzul + Φ F_A) / A_s,  k_τ = 0.5

What is simplified, and said on every sheet:

  * concentric clamping and loading, no bending, no temperature, static load (no fatigue check);
  * the clamp-load loss takes the whole axial load (Φ = 0 there) and the bolt's added load takes the full load factor
    Φ_K (load introduced under the head, n = 1): conservative on both sides;
  * the bolt's resilience uses the shank at its nominal area over the clamp length, with the guideline's substitute
    lengths for the head, the engaged thread and the nut; the plates use the deformation cone of an extensive joint;
  * thread stripping uses the shear area of the internal thread with the reduction factors C1 and C3 taken as 1, and
    the tapped material's shear strength as R_m / √3 (von Mises), because the guideline's ratio table is not embedded.

Friction is never a silent default: μ_G = μ_K = 0.12 is used only when the request gives none, it is labelled assumed,
and the torque is always printed with the friction it belongs to. The formula for F_Mzul and M_A reproduces published
VDI 2230 reference tables (docs/CALCULATORS.md).

Bosses: the hole, the insert and the least wall are the insert maker's published figures (form/hardware_tables.py:
CNC Kitchen). The datasheet gives no pull-out force, so none is quoted: the sheet gives a modelled upper bound from
the plastic's sourced strength, and says it is a bound.
"""
from __future__ import annotations

import math

from .. import hardware_tables as hw
from . import I, Sheet, choice, material_kind, material_prop, need, number

VDI = ("VDI 2230 Part 1:2015, Systematic calculation of highly stressed bolted joints: joints with one cylindrical bolt", "")
ISO898 = ("ISO 898-1:2013, Mechanical properties of fasteners made of carbon steel and alloy steel: bolts, screws and studs", "")
ISO3506 = ("ISO 3506-1:2020, Mechanical properties of corrosion-resistant stainless steel fasteners", "")
ISO724 = ("ISO 724 / ISO 68-1, ISO general-purpose metric screw threads: basic dimensions (d2 = d − 0.6495 P, d3 = d − 1.2269 P)", "")
ISO273 = (hw.ISO_273, "")
HEADS_SRC = ("ISO 4017 / ISO 4014 (hexagon head) and ISO 4762 (socket head): least bearing diameter d_w", "")
PITCH = {**hw.PITCH, "M8": 1.25, "M10": 1.5, "M12": 1.75, "M16": 2.0}            # ISO 261 coarse
HOLE = {**{k: v[1] for k, v in hw.CLEARANCE.items()}, "M8": 9.0, "M10": 11.0, "M12": 13.5, "M16": 17.5}   # ISO 273 medium
DW = {"hex": {"M2": 3.07, "M2.5": 4.07, "M3": 4.57, "M4": 5.88, "M5": 6.88, "M6": 8.88, "M8": 11.63, "M10": 14.63, "M12": 16.63, "M16": 22.49},
      "socket": {"M2": 3.48, "M2.5": 4.18, "M3": 5.07, "M4": 6.53, "M5": 8.03, "M6": 9.38, "M8": 12.33, "M10": 15.33, "M12": 17.23, "M16": 23.17}}
SIZES = tuple(PITCH)
# property class -> (R_p0.2 or R_eL min, R_m min) MPa, d <= 16 mm
GRADES = {"4.8": (340.0, 420.0, "iso898"), "8.8": (640.0, 800.0, "iso898"), "10.9": (940.0, 1040.0, "iso898"),
          "12.9": (1100.0, 1220.0, "iso898"), "A2-70": (450.0, 700.0, "iso3506")}
E_BOLT = 205000.0        # MPa, steel (VDI 2230 uses 205 000 for the bolt)
EMBED = {"thread": 3.0, "head_or_nut": 2.5, "interface": 1.5}      # µm, VDI 2230 Table 5, Rz < 10 µm, axial load
MU_DEFAULT = 0.12
ALPHA_DEFAULT = 1.6


def spec() -> dict:
    return {"id": "fastener", "title": "Bolted joint from the load", "standard": "VDI 2230 Part 1 (simplified core), ISO 898-1",
            "doc": "The screw size for an axial and a shear load per screw, with preload, tightening torque, working "
                   "stress and thread stripping in aluminium or plastic; or a boss with a heat-set insert. Writes the "
                   "plates with their holes, or the boss with its insert pocket.",
            "writes": "joint: two plates with clearance holes and counterbores (and tap holes); boss: a boss with the insert's pocket",
            "inputs": [
                I("kind", "What to size", "", "joint", "", ("joint", "boss")),
                I("size", "Screw size", "", None, "left out: the smallest that carries the load", SIZES),
                I("grade", "Property class", "", "8.8", "", tuple(GRADES)),
                I("axial", "Axial working load per screw F_A", "N", 0.0, "pulls the joint apart"),
                I("shear", "Shear load per screw F_Q", "N", 0.0, "carried by friction between the plates"),
                I("mu_interface", "Friction between the plates μ_T", "", None, "needed with a shear load; never assumed"),
                I("interfaces", "Slip planes q_F", "", 1, ""),
                I("alpha", "Tightening factor α_A", "", None, "scatter of the tool: about 1.6 for a torque wrench"),
                I("mu_thread", "Thread friction μ_G", "", None, ""),
                I("mu_head", "Head friction μ_K", "", None, ""),
                I("utilisation", "Share of the proof stress used on tightening ν", "", 0.9, ""),
                I("head", "Head", "", "socket", "", ("socket", "hex")),
                I("into", "What the screw goes into", "", "nut", "", ("nut", "tapped")),
                I("top_t", "Top plate thickness", "mm", 6.0, ""),
                I("bottom_t", "Bottom plate thickness", "mm", 8.0, ""),
                I("plate_material", "Plate material", "", None, "library key: modulus for the load factor, yield for the head pressure"),
                I("E_plate", "Plate modulus", "MPa", None, ""),
                I("tapped_material", "Tapped material", "", None, "library key: tensile strength for thread stripping; default the plate's"),
                I("Rm_tapped", "Tensile strength of the tapped material", "MPa", None, ""),
                I("engagement", "Thread engagement", "mm", None, "tapped; left out: the length at which the screw breaks before the thread strips"),
                I("phi", "Load factor Φ", "", None, "your own value instead of the computed one"),
                I("embed", "Embedding f_Z", "µm", None, "your own value instead of the table's"),
                I("bolts", "Screws in the row", "", 2, "geometry"),
                I("pitch", "Screw spacing", "mm", None, "geometry; default 4 d"),
                # boss
                I("material", "Boss material", "", None, "boss: a plastic of the library"),
                I("direction", "Pull direction of a printed boss", "", "z", "z: along the boss, across the layers", ("xy", "z")),
                I("insert", "Insert length", "", "standard", "", ("standard", "short")),
                I("safety", "Safety factor on the modelled pull-out bound", "", 3.0, ""),
            ]}


def thread(size: str) -> dict:
    """Basic thread geometry of a coarse ISO metric size (mm, mm²)."""
    need(size in PITCH, f"No thread data for {size}.", "Sizes: " + ", ".join(SIZES) + ".", ["size"])
    d, P = float(size[1:]), PITCH[size]
    d2, d3 = d - 0.649519 * P, d - 1.226869 * P
    d0 = (d2 + d3) / 2
    return {"d": d, "P": P, "d2": d2, "d3": d3, "d0": d0, "As": math.pi / 4 * d0 * d0, "AN": math.pi / 4 * d * d,
            "Ad3": math.pi / 4 * d3 * d3}


def preload_permissible(size: str, Rp: float, mu_G: float, nu: float = 0.9) -> float:
    """F_Mzul in N (VDI 2230 R7, shank bolt: the stress cross section governs)."""
    t = thread(size)
    k = 1.5 * (t["d2"] / t["d0"]) * (t["P"] / (math.pi * t["d2"]) + 1.155 * mu_G)
    return t["As"] * nu * Rp / math.sqrt(1 + 3 * k * k)


def torque(size: str, F: float, mu_G: float, mu_K: float, head: str = "hex") -> float:
    """M_A in N·mm for a preload F in N (VDI 2230 R13)."""
    t = thread(size)
    DKm = (DW[head][size] + HOLE[size]) / 2
    return F * (0.16 * t["P"] + 0.58 * t["d2"] * mu_G + DKm / 2 * mu_K)


def _cone(dW, dh, lK, E_P, tapped: bool) -> tuple[float, float]:
    """(δ_P in mm/N, tan φ) of an extensive clamped plate: VDI 2230 deformation cone, through-bolt (w = 1) or tapped (w = 2)."""
    w = 2 if tapped else 1
    bL, y, tan = lK / dW, 2.0, 0.5
    for _ in range(20):
        tan = (0.348 + 0.013 * math.log(bL) + 0.193 * math.log(y)) if tapped else (0.362 + 0.032 * math.log(bL / 2) + 0.153 * math.log(y))
        tan = max(tan, 0.1)
        y = (dW + w * lK * tan) / dW                  # the cone's largest diameter over the head diameter
    num = (dW + dh) * (dW + w * lK * tan - dh)
    den = (dW - dh) * (dW + w * lK * tan + dh)
    return 2 * math.log(num / den) / (w * E_P * math.pi * dh * tan), tan


def _joint_numbers(size: str, head: str, lK: float, E_P: float | None, tapped: bool, interfaces: int) -> dict:
    t = thread(size)
    d = t["d"]
    lSK = (0.5 if head == "hex" else 0.4) * d
    dS = (lSK / t["AN"] + lK / t["AN"] + 0.5 * d / t["Ad3"] + (0.33 if tapped else 0.4) * d / t["AN"]) / E_BOLT
    out = {"dS": dS, "dP": None, "phi": None, "tan": None}
    if E_P:
        out["dP"], out["tan"] = _cone(DW[head][size], HOLE[size], lK, E_P, tapped)
        out["phi"] = out["dP"] / (dS + out["dP"])
    out["fZ"] = EMBED["thread"] + EMBED["head_or_nut"] * (1 if tapped else 2) + EMBED["interface"] * interfaces
    return out


def run(inputs: dict) -> dict:
    return (_boss if choice(inputs, "kind", ("joint", "boss"), "joint") == "boss" else _joint)(inputs)


def _friction(s: Sheet, inputs: dict, vdi: str) -> tuple[float, float]:
    out = []
    for key, label in (("mu_thread", "Thread friction μ_G"), ("mu_head", "Head friction μ_K")):
        v = number(inputs, key, None, 0.02, 0.6)
        if v is None:
            v = s.assumed(key, label, MU_DEFAULT, "", "0.12: the middle of friction class B (0.08 to 0.16), typical of "
                          "lightly oiled or zinc-plated steel. Measure or look up your coating; preload for a given "
                          "torque moves by tens of per cent with it.", source=vdi)
        else:
            s.given(key, label, v, "")
        out.append(v)
    return out[0], out[1]


def _joint(inputs: dict) -> dict:
    s = Sheet("fastener", "Bolted joint", "VDI 2230 Part 1:2015 (simplified core)", inputs)
    vdi = s.source("vdi", *VDI)
    s.source("iso724", *ISO724)
    s.eq("thread", "d2 = d − 0.6495 P,  d3 = d − 1.2269 P,  d0 = (d2 + d3)/2,  A_s = π d0² / 4", "iso724")
    s.eq("preload", "F_Mzul = A_s · ν · R_p0.2 / √(1 + 3 · [(3/2) · (d2/d0) · (P/(π d2) + 1.155 μ_G)]²)", vdi,
         "R7: the tightening torque twists the bolt as it stretches it, so less than ν · R_p0.2 · A_s is available")
    s.eq("torque", "M_A = F_M · [0.16 P + 0.58 d2 μ_G + (D_Km/2) μ_K],  D_Km = (d_w + d_h)/2", vdi, "R13")
    s.eq("slip", "F_Kerf = F_Q / (q_F · μ_T)", vdi, "R2: the clamp load that carries the shear by friction")
    s.eq("embedding", "F_Z = f_Z / (δ_S + δ_P)", vdi, "R4: preload lost as the surfaces bed in; f_Z from Table 5")
    s.eq("required", "F_Mmin = F_Kerf + F_A + F_Z,  F_Mmax = α_A · F_Mmin", vdi,
         "R5, R6; simplified: the whole axial load is taken off the clamp load (Φ = 0 there)")
    s.eq("resilience", "δ_S = (l_SK + l_K)/(E_S A_N) + 0.5 d/(E_S A_d3) + l_M/(E_S A_N),   Φ_K = δ_P / (δ_S + δ_P)", vdi,
         "R3; simplified: shank at the nominal area over the clamp length; δ_P from the deformation cone of an extensive joint")
    s.eq("working", "σ_z = (F_Mzul + Φ F_A)/A_s,  τ = F_Mzul (d2/2)(P/(π d2) + 1.155 μ_G) / (π d0³/16),  σ_red = √(σ_z² + 3 (0.5 τ)²)", vdi, "R8")
    s.eq("pressure", "p = (F_Mzul + Φ F_A) / (π (d_w² − d_h²)/4)", vdi, "R10: pressure under the head")
    s.eq("strip", "m_eff = R_m,bolt · A_s / (τ_BM · π · d · [1/2 + (d − d2) tan 30° / P])", vdi,
         "the engagement at which the bolt breaks before the internal thread strips (Alexander's shear area); "
         "simplified: C1 = C3 = 1 and τ_BM = R_m / √3")
    head = choice(inputs, "head", ("socket", "hex"), "socket")
    into = choice(inputs, "into", ("nut", "tapped"), "nut")
    tapped = into == "tapped"
    grade = str(inputs.get("grade") or "8.8").upper().replace("A2-70", "A2-70")
    need(grade in GRADES, f"Unknown property class “{grade}”.", "Classes: " + ", ".join(GRADES) + ".", ["grade"])
    Rp, Rm, gsrc = GRADES[grade]
    gs = s.source(gsrc, *(ISO898 if gsrc == "iso898" else ISO3506))
    s.add("Rp", f"Proof (yield) stress of class {grade}", Rp, "MPa", "specified", source=gs, note="least value, d ≤ 16 mm")
    s.add("Rm_bolt", f"Tensile strength of class {grade}", Rm, "MPa", "specified", source=gs, note="least value")
    FA = number(inputs, "axial", 0.0, 0, 1e7)
    FQ = number(inputs, "shear", 0.0, 0, 1e7)
    s.given("axial", "Axial working load per screw F_A", FA, "N")
    s.given("shear", "Shear load per screw F_Q", FQ, "N")
    q = number(inputs, "interfaces", 1, 1, 6, whole=True)
    muT = number(inputs, "mu_interface", None, 0.02, 1.5)
    if FQ > 0:
        need(muT is not None, "A shear load needs the friction between the plates (mu_interface).",
             "It is never assumed: dry steel on steel is about 0.1 to 0.2, aluminium lower, plastics vary. Give your value.", ["mu_interface"])
        s.given("mu_interface", "Friction between the plates μ_T", muT, "")
        FK = s.computed("clamp_required", "Clamp load against slipping F_Kerf", FQ / (q * muT), "N", "slip")
    else:
        FK = 0.0
    muG, muK = _friction(s, inputs, vdi)
    nu = number(inputs, "utilisation", 0.9, 0.3, 1.0)
    (s.given if "utilisation" in inputs else lambda *a: s.add(*a, "specified", source=vdi, note="the guideline's usual 90 % of the proof stress"))("utilisation", "Share of the proof stress used ν", nu, "")
    aA = number(inputs, "alpha", None, 1.0, 4.0)
    if aA is None:
        aA = s.assumed("alpha", "Tightening factor α_A", ALPHA_DEFAULT, "", "a torque wrench with estimated friction: "
                       "the guideline's Table A8 gives about 1.4 to 1.6 (1.6 taken); by hand or with an impact driver it is 2.5 to 4",
                       source=vdi)
    else:
        s.given("alpha", "Tightening factor α_A", aA, "")
    top = number(inputs, "top_t", 6.0, 0.5, 500)
    bot = number(inputs, "bottom_t", 8.0, 0.5, 500)
    lK = top if tapped else top + bot
    s.given("top_t", "Top plate thickness", top, "mm") if "top_t" in inputs else s.assumed("top_t", "Top plate thickness", top, "mm", "6 mm, unless the request says otherwise")
    s.given("bottom_t", "Bottom plate thickness", bot, "mm") if "bottom_t" in inputs else s.assumed("bottom_t", "Bottom plate thickness", bot, "mm", "8 mm, unless the request says otherwise")
    s.eq("clamp", "l_K = clamped thickness (tapped: the top plate only)", "", "")
    s.computed("clamp_length", "Clamp length l_K", lK, "mm", "clamp")
    plate = inputs.get("plate_material") or None
    EP = material_prop(s, plate, "E", "E_plate", "Plate modulus", override=number(inputs, "E_plate", None, 10, 1e6), scale=1000.0, unit="MPa")
    phi_in = number(inputs, "phi", None, 0, 1)
    fz_in = number(inputs, "embed", None, 0, 200)

    def demand(size):
        j = _joint_numbers(size, head, lK, EP, tapped, q)
        fZ = fz_in if fz_in is not None else j["fZ"]
        FZ = fZ * 1e-3 / (j["dS"] + j["dP"]) if j["dP"] else None
        Fmin = FK + FA + (FZ or 0.0)
        return j, fZ, FZ, Fmin, aA * Fmin

    size = inputs.get("size")
    if size:
        size = str(size).upper()
        thread(size)
    else:
        for cand in SIZES:
            if preload_permissible(cand, Rp, muG, nu) >= demand(cand)[4]:
                size = cand
                break
        need(size, f"No size up to {SIZES[-1]} in class {grade} carries this load.", "Use more screws, a higher class, "
             "or a better tool (lower alpha).", ["axial", "shear"])
        s.note(f"{size} is the smallest coarse-thread size whose permissible preload covers α_A · F_Mmin.")
    t = thread(size)
    j, fZ, FZ, Fmin, Fmax = demand(size)
    s.add("size", "Screw", f"{size} × {t['P']:g}, class {grade}, {head} head", "", "specified" if inputs.get("size") else "computed",
          source="request" if inputs.get("size") and s.source("request", "given in the request") else "",
          equation="" if inputs.get("size") else "required")
    s.computed("stress_area", "Stress cross section A_s", t["As"], "mm²", "thread")
    s.add("d_w", "Head bearing diameter d_w", DW[head][size], "mm", "specified", source=s.source("heads", *HEADS_SRC))
    s.add("d_h", "Clearance hole d_h", HOLE[size], "mm", "specified", source=s.source("iso273", *ISO273), note="medium series")
    s.computed("resilience_bolt", "Bolt resilience δ_S", j["dS"], "mm/N", "resilience")
    if j["dP"]:
        s.computed("resilience_plates", "Plate resilience δ_P", j["dP"], "mm/N", "resilience")
        phi = s.given("phi", "Load factor Φ", phi_in, "") if phi_in is not None else s.computed("phi", "Load factor Φ_K", j["phi"], "", "resilience")
        if fz_in is not None:
            s.given("embed", "Embedding f_Z", fZ, "µm")
        else:
            s.add("embed", "Embedding f_Z", fZ, "µm", "specified", source=vdi,
                  note=f"Table 5, Rz < 10 µm, axial load: thread {EMBED['thread']:g}, each head or nut seat {EMBED['head_or_nut']:g}, each inner interface {EMBED['interface']:g}")
        s.computed("embed_loss", "Preload lost to embedding F_Z", FZ, "N", "embedding")
    else:
        phi = s.given("phi", "Load factor Φ", phi_in, "") if phi_in is not None else None
        s.missing("embed_loss", "Load factor and embedding loss", "No modulus for the plates: give plate_material (a "
                  "library key) or E_plate (MPa). Without it the embedding loss is left out of the preload wanted, "
                  "and the bolt's added load is taken as the whole axial load.")
        if phi is None:
            s.eq("phi_bound", "Φ ≤ 1", "", "with no plate stiffness the bolt is taken to carry the whole axial load: an upper bound")
            phi = s.computed("phi", "Load factor Φ (upper bound)", 1.0, "", "phi_bound")
    s.computed("preload_min", "Least preload wanted F_Mmin", Fmin, "N", "required")
    s.computed("preload_max", "Preload the tool may reach F_Mmax", Fmax, "N", "required")
    Fz = s.computed("preload_permissible", "Permissible assembly preload F_Mzul", preload_permissible(size, Rp, muG, nu), "N", "preload")
    MA = s.computed("torque", f"Tightening torque M_A (μ_G = {muG:g}, μ_K = {muK:g})", torque(size, Fz, muG, muK, head) / 1000.0, "N·m", "torque",
                    "tightens to F_Mzul; valid only with this friction")
    st = "PASS" if Fz >= Fmax else "FAIL"
    s.check("preload", "Preload", st, f"needs {Fmax / 1000:.2f} kN, {size} class {grade} allows {Fz / 1000:.2f} kN",
            "Even at the tool's low end (F_Mzul / α_A) the joint keeps the clamp load it needs."
            if st == "PASS" else "The screw cannot be tightened enough: larger size, higher class, more screws or a better tool.", "required")
    sz = (Fz + phi * FA) / t["As"]
    tau = Fz * (t["d2"] / 2) * (t["P"] / (math.pi * t["d2"]) + 1.155 * muG) / (math.pi * t["d0"] ** 3 / 16)
    red = s.computed("stress_working", "Working stress σ_red", math.sqrt(sz * sz + 3 * (0.5 * tau) ** 2), "MPa", "working")
    s.eq("sf", "S_F = R_p0.2 / σ_red", vdi, "R8")
    SF = s.computed("safety_yield", "Safety against yield S_F", Rp / red, "", "sf")
    s.check("yield", "Working stress", "PASS" if SF >= 1.0 else "FAIL", f"{red:.0f} MPa, S_F = {SF:.2f}",
            "The guideline asks for S_F ≥ 1.0 against the proof stress.", "working")
    p = s.computed("head_pressure", "Pressure under the head", (Fz + phi * FA) / (math.pi / 4 * (DW[head][size] ** 2 - HOLE[size] ** 2)), "MPa", "pressure")
    ys = material_prop(s, plate, "yield", "yield_plate", "Plate yield strength", unit="MPa") if plate else None
    if ys:
        s.check("pressure", "Pressure under the head", "PASS" if p <= ys else "WARN", f"{p:.0f} MPa, plate yield {ys:.0f} MPa",
                "Compared with the plate's sourced yield strength, a conservative stand-in for the guideline's limiting "
                "pressures (Table A9, not embedded). " + ("" if p <= ys else "Use a washer or a flanged head."), "pressure")
    else:
        s.missing("pressure_check", "Verdict on the pressure under the head", "No sourced yield strength for the plate: give plate_material.")
    eng = number(inputs, "engagement", None, 0.5, 500)
    if tapped:
        tm = inputs.get("tapped_material") or plate
        RmT = material_prop(s, tm, "uts", "Rm_tapped", "Tensile strength of the tapped material",
                            override=number(inputs, "Rm_tapped", None, 1, 5000), unit="MPa")
        if RmT:
            s.eq("shear_strength", "τ_BM = R_m / √3", "", "von Mises shear equivalent: a simplification, the guideline tabulates the ratio per material family")
            tauB = s.computed("shear_tapped", "Shear strength of the tapped thread τ_BM", RmT / math.sqrt(3), "MPa", "shear_strength")
            area_per_mm = math.pi * t["d"] * (0.5 + (t["d"] - t["d2"]) * math.tan(math.radians(30)) / t["P"])
            mreq = s.computed("engagement_required", "Engagement at which the screw breaks first", Rm * t["As"] / (tauB * area_per_mm), "mm", "strip",
                              f"{Rm * t['As'] / (tauB * area_per_mm) / t['d']:.2f} d; add the chamfer and run-out (about one pitch)")
            if eng is None:
                eng = mreq
                s.computed("engagement", "Thread engagement used", eng, "mm", "strip")
            else:
                s.given("engagement", "Thread engagement", eng, "mm")
            Fstrip = s.computed("strip_force", "Force that strips the tapped thread", tauB * area_per_mm * eng, "N", "strip")
            st = "PASS" if eng >= mreq * 0.999 else ("WARN" if Fstrip >= 1.25 * (Fz + phi * FA) else "FAIL")
            s.check("strip", "Thread stripping", st, f"{eng:.1f} mm engaged, {mreq:.1f} mm for full strength",
                    "PASS: the screw breaks before the thread strips. WARN: the thread strips first but carries the "
                    "preload with a margin of 1.25. FAIL: it strips on tightening.", "strip")
            if material_kind(tm)["kind"] == "filament" or material_kind(tm)["category"] == "plastic":
                s.caveat("A thread cut or formed in plastic relaxes: the preload falls over hours and with heat. Use "
                         "a heat-set insert (kind=boss) for anything undone more than a few times.")
        else:
            s.missing("strip", "Thread stripping", "No sourced tensile strength for the tapped material: give tapped_material or Rm_tapped (MPa).")
            eng = eng or 1.5 * t["d"]
    s.caveat("Simplified VDI 2230: concentric clamping and loading, static, no bending, no temperature, no fatigue "
             "check. For a joint whose failure matters, run the full guideline.")
    n = number(inputs, "bolts", 2, 1, 12, whole=True)
    pitch = number(inputs, "pitch", None, 1, 1000) or max(4 * t["d"], DW[head][size] * 2)
    need(not (tapped and bot < 1.0), "The bottom plate is too thin to tap.", "", ["bottom_t"])
    s.geometry("bolted_joint", {"d": t["d"], "top_t": top, "bottom_t": max(bot, (eng or 0) + 1.0) if tapped else bot,
                                "bolts": n, "pitch": pitch, "tapped": 1.0 if tapped else 0.0,
                                "engagement": eng or 0.0},
               f"{size} bolted joint", {"size": size, "head": head, "grade": grade},
               place={"feature": "boss", "options": {"size": size, "hole": "clearance"}} if size in ("M2", "M2.5", "M3", "M4", "M5") else None)
    return s.done(f"{size} class {grade}: preload {Fz / 1000:.2f} kN at {MA:.2f} N·m (μ = {muG:g}), needs {Fmax / 1000:.2f} kN, S_F {SF:.2f}")


def _boss(inputs: dict) -> dict:
    s = Sheet("fastener", "Boss with a heat-set insert", "insert maker's datasheet; modelled pull-out bound", inputs)
    ins = s.source("insert", hw.INSERT_SOURCE, "https://cnckitchen.store", "outer diameter, length, recommended hole and least wall")
    size = str(inputs.get("size") or "M3").upper()
    key = size + ("-short" if choice(inputs, "insert", ("standard", "short"), "standard") == "short" else "")
    need(key in hw.INSERTS, f"No heat-set insert data for {key}.", "Known: " + ", ".join(hw.INSERTS) + ".", ["size", "insert"])
    od, L, hole, wall = hw.INSERTS[key]
    s.given("size", "Screw size", size, "")
    s.add("insert_od", "Insert outer diameter", od, "mm", "specified", source=ins)
    s.add("insert_length", "Insert length", L, "mm", "specified", source=ins)
    s.add("hole_d", "Hole for the insert", hole, "mm", "specified", source=ins, note="the maker's recommended hole; the insert melts its way in")
    s.add("min_wall", "Least wall around the hole", wall, "mm", "specified", source=ins)
    s.eq("boss", "D_boss = d_hole + 2 · wall_min,  depth = L_insert + 1 mm", ins, "1 mm below the insert for displaced plastic (assumed)")
    bd = s.computed("boss_d", "Boss outer diameter", hole + 2 * wall, "mm", "boss")
    depth = s.computed("pocket_depth", "Pocket depth", L + 1.0, "mm", "boss")
    FA = number(inputs, "axial", 0.0, 0, 1e6)
    s.given("axial", "Axial working load F_A", FA, "N")
    material = inputs.get("material") or None
    direction = choice(inputs, "direction", ("xy", "z"), "z")
    uts = material_prop(s, material, "uts", "uts", "Tensile strength", direction=direction, unit="MPa") if material else None
    if uts:
        s.eq("pullout", "F_bound = π · d_insert · L_insert · R_m / √3", "",
             "Form Studio's model, not test data: the plastic sheared on a cylinder around the insert. An upper bound; "
             "knurl form, melt quality and layer bonding all lower it")
        Fb = s.computed("pullout_bound", "Pull-out, modelled upper bound", math.pi * od * L * uts / math.sqrt(3), "N", "pullout")
        SFk = number(inputs, "safety", 3.0, 1, 20)
        (s.given if "safety" in inputs else lambda *a: s.assumed(*a, "3 on a modelled bound for a printed boss, unless the request says otherwise"))("safety", "Safety factor on the bound", SFk, "")
        st = "PASS" if FA * SFk <= Fb else "FAIL"
        s.check("pullout", "Axial load against the modelled bound", st, f"{FA:.0f} N × {SFk:g} against {Fb:.0f} N",
                "A bound from a model. For a load that matters, pull-test an insert in your own print.", "pullout", evidence="assumed")
    else:
        s.missing("pullout_bound", "Pull-out force", "The insert's datasheet gives none, and no sourced strength is "
                  "known for the boss material: give material (a library plastic). No pull-out figure is quoted.")
    s.caveat("The insert maker publishes dimensions, not a pull-out force. None is quoted here as a rating.")
    s.geometry("insert_boss", {"d": float(size[1:]), "boss_d": bd, "height": max(depth + 1.0, 6.0), "short": 1.0 if key.endswith("short") else 0.0},
               f"{size} insert boss", {"size": key, "material": material or ""},
               place={"feature": "boss", "options": {"size": size, "hole": "insert", "outer_d": round(bd, 2), "height": round(max(depth + 1.0, 6.0), 2),
                                                     "hole_d": hole, "hole_depth": round(depth, 2)}} if size in ("M2", "M2.5", "M3", "M4", "M5") else None)
    return s.done(f"{key} insert: hole Ø{hole:g}, boss Ø{bd:g}, pocket {depth:g} mm deep"
                  + (f"; pull-out bound {s['pullout_bound']:.0f} N (modelled)" if uts else "; no pull-out figure (unsourced)"))
