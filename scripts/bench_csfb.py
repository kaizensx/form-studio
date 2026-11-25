"""Form Studio's contract and proof sheet on the specifications of an outside benchmark, with a scripted stand-in agent.

    .venv/bin/python scripts/bench_csfb.py TASKS_DIR [--json out.json]

TASKS_DIR is the tasks/ folder of github.com/rodriguescarson/cad-silent-failure-bench ("Done Is Not Correct",
arXiv 2611.10063; task specifications CC BY 4.0): 13 JSON files, each a natural-language specification and the
machine-checkable requirements the paper's oracle grades. Only those JSON files are read. Nothing from that
repository is executed: not its harness, not its reference solutions, not its recorded attempts.

No model runs here. The "agent" is this script: for every task it holds one parametric design written for this
bench (below), built twice: with the values that meet the specification, and with one seeded fault of the kind a
valid-looking solid hides (a radius taken for a diameter, a hole missing, a pattern on the wrong circle, a feature
on the wrong side). The faults were chosen before the results were seen; some are expected to be missed.

What is measured, per task and in total:
  * compile   how many of the oracle's requirements Form Studio's brief compiler reads from the words alone
              (form.contract.compile_brief), and how many can be said at all as typed assertions (what an agent
              passes as design_brief(assertions=...)); requirements about the mass centre cannot;
  * correct   the design that meets the specification: is its proof sheet green (a red row here is a false alarm);
  * fault     the seeded fault: does the sheet show a FAIL (caught), under the contract read from the words and
              under the typed contract with the oracle's own tolerances;
  * the two edit tasks (T4) are made with edit_design ops on the base design, and report what was built again.

Without a contract every one of these builds is "done": a valid solid, one part. That is the before.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HEAD = '''from build123d import Align, Box, Cylinder, PolarLocations, Pos, Rot
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param

A = (Align.CENTER, Align.CENTER, Align.MIN)


def P(key, label, default, lo, hi, feature_id):
    return Param(key, label, default, lo, hi, 0.5, "mm", "form", feature_id)

'''

SLEEVE = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Sleeve", "A cylinder with a bore."
    params = [P("od", "Outside diameter", 30, 5, 200, "body"), P("bore", "Bore", 20, 0, 190, "bore"),
              P("h", "Length", 40, 1, 200, "body")]

    @feature("Body")
    def body(self, v, body):
        return Cylinder(v["od"] / 2, v["h"], align=A)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(v["bore"] / 2, v["h"], align=A) if v["bore"] > 0 else body
'''

FLANGE = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Flange", "A disc with a bore and a bolt circle."
    params = [P("od", "Outside diameter", 120, 20, 300, "disc"), P("t", "Thickness", 14, 2, 60, "disc"),
              P("bore", "Bore", 40, 2, 200, "bore"), P("n", "Bolt holes", 6, 2, 16, "holes"),
              P("hole_d", "Bolt hole", 11, 2, 30, "holes"), P("pcd", "Bolt circle", 95, 10, 280, "holes")]

    @feature("Disc")
    def disc(self, v, body):
        return Cylinder(v["od"] / 2, v["t"], align=A)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Cylinder(v["bore"] / 2, v["t"], align=A)

    @feature("Bolt holes", role="interface")
    def holes(self, v, body):
        for loc in PolarLocations(v["pcd"] / 2, int(v["n"])):
            body = body - loc * Cylinder(v["hole_d"] / 2, v["t"], align=A)
        return body
'''

PLATE = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Plate", "A square plate with four holes."
    params = [P("side", "Side", 80, 20, 300, "plate"), P("t", "Thickness", 8, 2, 40, "plate"),
              P("hole_d", "Hole", 9, 2, 30, "holes"), P("pitch", "Hole spacing", 50, 10, 280, "holes")]

    @feature("Plate")
    def plate(self, v, body):
        return Box(v["side"], v["side"], v["t"], align=A)

    @feature("Holes", role="interface")
    def holes(self, v, body):
        for sx in (-1, 1):
            for sy in (-1, 1):
                body = body - Pos(sx * v["pitch"] / 2, sy * v["pitch"] / 2, 0) * Cylinder(v["hole_d"] / 2, v["t"], align=A)
        return body
'''

CBORE = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Counterbored plate", "A square plate with one counterbored hole."
    params = [P("side", "Side", 70, 20, 300, "plate"), P("t", "Thickness", 12, 2, 40, "plate"),
              P("hole_d", "Through hole", 11, 2, 30, "hole"), P("cb_d", "Counterbore", 20, 3, 60, "counterbore"),
              P("cb_depth", "Counterbore depth", 6, 1, 30, "counterbore"), P("from_top", "From the top face", 1, 0, 1, "counterbore")]

    @feature("Plate")
    def plate(self, v, body):
        return Box(v["side"], v["side"], v["t"], align=A)

    @feature("Through hole", role="interface")
    def hole(self, v, body):
        return body - Cylinder(v["hole_d"] / 2, v["t"], align=A)

    @feature("Counterbore", role="interface")
    def counterbore(self, v, body):
        z = v["t"] - v["cb_depth"] if v["from_top"] >= 0.5 else 0
        return body - Pos(0, 0, z) * Cylinder(v["cb_d"] / 2, v["cb_depth"], align=A)
'''

HUBBED = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Hubbed disc", "A disc with a coaxial hub and a bore."
    params = [P("disc_d", "Disc diameter", 60, 10, 300, "disc"), P("disc_t", "Disc thickness", 6, 1, 60, "disc"),
              P("hub_d", "Hub diameter", 30, 5, 200, "hub"), P("total_h", "Overall height", 30, 2, 200, "hub"),
              P("bore", "Bore", 20, 2, 190, "bore"), P("bore_stop", "Bore stops short by", 0, 0, 50, "bore")]

    @feature("Disc")
    def disc(self, v, body):
        return Cylinder(v["disc_d"] / 2, v["disc_t"], align=A)

    @feature("Hub")
    def hub(self, v, body):
        return body + Pos(0, 0, v["disc_t"]) * Cylinder(v["hub_d"] / 2, v["total_h"] - v["disc_t"], align=A)

    @feature("Bore", role="interface")
    def bore(self, v, body):
        return body - Pos(0, 0, v["bore_stop"]) * Cylinder(v["bore"] / 2, v["total_h"] - v["bore_stop"], align=A)
'''

LBRACKET = HEAD + '''
class Design(FeatureDesign):
    title, summary = "L-bracket", "A base plate and a wall, one hole in each."
    params = [P("w", "Width", 60, 10, 300, "base"), P("d", "Depth", 40, 10, 300, "base"), P("h", "Height", 40, 10, 300, "wall"),
              P("t", "Thickness", 8, 2, 30, "base"), P("hole_d", "Hole", 8, 2, 30, "base_hole"),
              P("wall_hole", "Hole in the wall", 1, 0, 1, "wall_hole")]

    @feature("Base plate")
    def base(self, v, body):
        return Box(v["w"], v["d"], v["t"], align=A)

    @feature("Wall")
    def wall(self, v, body):
        return body + Pos(0, -v["d"] / 2 + v["t"] / 2, 0) * Box(v["w"], v["t"], v["h"], align=A)

    @feature("Hole in the base", role="interface")
    def base_hole(self, v, body):
        return body - Pos(0, -v["d"] / 2 + 28, 0) * Cylinder(v["hole_d"] / 2, v["t"], align=A)

    @feature("Hole in the wall", role="interface")
    def wall_hole(self, v, body):
        if v["wall_hole"] < 0.5:
            return body
        return body - Pos(0, -v["d"] / 2 + v["t"], 24) * Rot(90, 0, 0) * Cylinder(v["hole_d"] / 2, v["t"], align=A)
'''

PIN = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Stepped pin", "Three coaxial sections end to end."
    params = [P("d1", "First diameter", 12, 2, 100, "first"), P("l1", "First length", 20, 1, 200, "first"),
              P("d2", "Second diameter", 10, 2, 100, "second"), P("l2", "Second length", 25, 1, 200, "second"),
              P("d3", "Third diameter", 8, 2, 100, "third"), P("l3", "Third length", 15, 1, 200, "third")]

    @feature("First section")
    def first(self, v, body):
        return Cylinder(v["d1"] / 2, v["l1"], align=A)

    @feature("Second section")
    def second(self, v, body):
        return body + Pos(0, 0, v["l1"]) * Cylinder(v["d2"] / 2, v["l2"], align=A)

    @feature("Third section")
    def third(self, v, body):
        return body + Pos(0, 0, v["l1"] + v["l2"]) * Cylinder(v["d3"] / 2, v["l3"], align=A)
'''

SHAFT = HEAD + '''
class Design(FeatureDesign):
    title, summary = "Stepped shaft", "A central section with a bearing seat at each end."
    params = [P("total", "Total length", 120, 10, 400, "centre"), P("d", "Central diameter", 40, 5, 200, "centre"),
              P("seat_d", "Seat diameter", 30, 2, 200, "seats"), P("seat_l", "Seat length", 20, 1, 100, "seats"),
              P("both", "A seat at both ends", 1, 0, 1, "seats")]

    @feature("Central section")
    def centre(self, v, body):
        return Cylinder(v["d"] / 2, v["total"], align=A)

    @feature("Bearing seats", role="interface")
    def seats(self, v, body):
        def ring(z):
            return Pos(0, 0, z) * (Cylinder(v["d"] / 2 + 1, v["seat_l"], align=A) - Cylinder(v["seat_d"] / 2, v["seat_l"], align=A))
        body = body - ring(0)
        return body - ring(v["total"] - v["seat_l"]) if v["both"] >= 0.5 else body
'''

# task id -> (design, values that meet the specification, the seeded fault, what the fault is, expected to be caught?)
AGENT = {
    "T1-bushing": (SLEEVE, {"od": 30, "bore": 20, "h": 40}, {"bore": 10}, "the bore radius taken for its diameter"),
    "T1-collar": (SLEEVE, {"od": 45, "bore": 25, "h": 15}, {"bore": 0}, "no bore at all"),
    "T1-washer": (SLEEVE, {"od": 40, "bore": 21, "h": 3}, {"bore": 10.5}, "the hole radius taken for its diameter"),
    "T1-flange-6bolt": (FLANGE, {}, {"n": 4}, "four bolt holes instead of six"),
    "T1-plate-4holes": (PLATE, {}, {"pitch": 40}, "holes on a 40 mm square instead of 50 mm"),
    "T2-counterbore-plate": (CBORE, {}, {"from_top": 0}, "the counterbore on the bottom face"),
    "T2-flanged-bushing": (HUBBED, {"disc_d": 60, "disc_t": 6, "hub_d": 30, "total_h": 30, "bore": 20}, {"hub_d": 35},
                           "hub Ø35 instead of Ø30"),
    "T2-pulley-blank": (HUBBED, {"disc_d": 80, "disc_t": 16, "hub_d": 32, "total_h": 36, "bore": 16}, {"bore_stop": 5},
                        "the bore stops 5 mm short (blind)"),
    "T2-lbracket": (LBRACKET, {}, {"wall_hole": 0}, "the hole in the wall is missing"),
    "T2-stepped-pin": (PIN, {}, {"d2": 11}, "middle section Ø11 instead of Ø10"),
    "T2-stepped-shaft": (SHAFT, {}, {"both": 0}, "a bearing seat at one end only"),
    "T4-bushing-bore-edit": (SLEEVE, {"od": 30, "bore": 24, "h": 40}, {"bore": 22}, "bore enlarged to Ø22, not Ø24"),
    "T4-flange-8bolt-edit": (FLANGE, {"n": 8}, {"n": 8, "pcd": 90}, "eight holes, but the bolt circle moved to Ø90"),
}
EDIT_BASE = {"T4-bushing-bore-edit": {"od": 30, "bore": 20, "h": 40}, "T4-flange-8bolt-edit": {}}


def typed(task: dict) -> tuple[list, list]:
    """(the oracle's requirements as Form assertions, with its tolerances; those that cannot be said)."""
    from form import contract as C
    out, cannot = [], []
    for c in task["checks"]:
        k, prop = c["kind"], c.get("property") or ""
        if k == "true" and prop == "valid_solid":
            continue                                       # every Form Studio build is checked for this already
        if k == "equal" and prop == "solid_count":
            out.append({**C.part_count(int(c["target"])), "id": c["id"]})
        elif k == "approx" and prop in ("bbox_x", "bbox_y", "bbox_z"):
            out.append({**C.extent(c["target"], prop[-1], tol=c["tol"]), "id": c["id"]})
        elif k == "approx" and prop in ("bbox_xy_max", "bbox_xy_min"):
            out.append({**C.extent(c["target"], tol=c["tol"]), "id": c["id"]})
        elif k == "range" and prop == "volume":
            if c.get("lo") is not None:
                out.append({**C.volume(c["lo"], "min", tol=0), "id": c["id"] + "_lo"})
            if c.get("hi") is not None:
                out.append({**C.volume(c["hi"], "max", tol=0), "id": c["id"] + "_hi"})
        elif k == "cylinder_count":
            out.append({**C.cylinder(2 * c["radius"], tol=2 * c["radius_tol"], count=int(c["target"]),
                                     length=c.get("height"), length_tol=c.get("height_tol")), "id": c["id"]})
        elif k == "bolt_circle":
            out.append({**C.bolt_circle(int(c["target"]), 2 * c["radius"], c["pcd"],
                                        tol=min(2 * c["radius_tol"], c["pcd_tol"])), "id": c["id"]})
        else:
            cannot.append(f"{c['id']} ({k} {prop}): {c.get('desc', '')}")
    return out, cannot


def covered(task: dict, read: list) -> tuple[int, int]:
    """(how many of the oracle's stated requirements the contract read from the words speaks to, of how many).
    Requirements the specification does not state in words (a valid solid, one body, the volume band, the mass
    centre) are not counted: there is nothing to read."""
    n = hit = 0
    for c in task["checks"]:
        k, prop = c["kind"], c.get("property") or ""
        if k in ("true", "equal", "range") or prop.startswith("com_"):
            continue
        n += 1
        if k == "bolt_circle":
            hit += any(a["kind"] == "bolt_circle" and a["count"] == c["target"] and abs(a["circle_d"] - c["pcd"]) < 1e-6
                       for a in read)
        elif k == "cylinder_count":
            hit += any(a["kind"] in ("cylinder", "hole_count") and abs(a["d"] - 2 * c["radius"]) < 1e-6 for a in read)
        elif k == "approx":
            t = c["target"]
            hit += any((a["kind"] == "extent" and abs(a["mm"] - t) < 1e-6) or (a["kind"] == "bbox" and t in a["size"])
                       or (a["kind"] == "cylinder" and prop.startswith("bbox_xy") and abs(a["d"] - t) < 1e-6) for a in read)
    return int(hit), n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    os.environ["FORM_DATA"] = tempfile.mkdtemp(prefix="form-csfb-")
    from form import config, contract as C, edits, staged
    from form.studio import Studio, StudioError
    st = Studio(config.load())
    rows = []
    try:
        for f in sorted(Path(a.tasks).glob("*.json")):
            task = json.loads(f.read_text(encoding="utf-8"))
            tid = task["id"]
            if tid not in AGENT:
                continue
            src, good, bad, what = AGENT[tid]
            words = task["nl_spec"].split("```")[0]
            read = C.compile_brief({"goal": words})
            full, cannot = typed(task)
            full_c = C.compile_brief({"goal": ""}, full)
            hit, of = covered(task, read["assertions"])
            row = {"task": tid, "seeded": what, "read_from_words": [x["text"] for x in read["assertions"]],
                   "oracle_requirements": len(task["checks"]), "stated_in_words": of, "read": hit,
                   "typed": len(full), "cannot_be_said": cannot}

            def sheet(pid, con):
                staged.attach(st, pid, brief={"id": "b-" + "0" * 8, "contract": con})
                s = C.prove(st, st.load(pid))
                return {"green": s["green"], "fail": [r["requirement"] + ": " + str(r["measured_text"]) for r in s["rows"]
                                                       if r["status"] == "FAIL"],
                        "unproven": sum(1 for r in s["rows"] if r["status"] == "UNPROVEN"), "rows": len(s["rows"])}
            for label, vals in (("correct", good), ("fault", {**good, **bad})):
                try:
                    if tid in EDIT_BASE and label == "correct":
                        p = st.create_design(f"{tid} base", src, values=EDIT_BASE[tid], purpose="model")
                        base_chars = len(json.dumps({"project": p["id"], "source": src}))
                        ops = [{"op": "set_param", "param": k, "value": v} for k, v in vals.items() if EDIT_BASE[tid].get(k) != v]
                        e = edits.edit(st, p, ops, expect_head=1)
                        p = e["project"]
                        row["edit"] = {"ops_chars": len(json.dumps({"project": p["id"], "expect_head": 1, "ops": ops})),
                                       "whole_file_chars": base_chars,
                                       "built": [x["feature"] for x in e["changed"] if x["status"] == "built"],
                                       "reused": e["reused"]}
                    else:
                        p = st.create_design(f"{tid} {label}", src, values=vals, purpose="model")
                    row[label] = {"words": sheet(p["id"], read), "typed": sheet(p["id"], full_c), "builds": True}
                except StudioError as err:
                    row[label] = {"builds": False, "error": str(err)[:200]}
            rows.append(row)
            c, x = row["correct"], row["fault"]
            print(f"{tid:<22} read {hit}/{of} typed {len(full)}/{len(full) + len(cannot)} | correct: words "
                  f"{'green' if c['words']['green'] else 'RED'} typed {'green' if c['typed']['green'] else 'RED'} | "
                  f"fault ({what}): words {'caught' if x['words']['fail'] else 'missed'}, typed "
                  f"{'caught' if x['typed']['fail'] else 'missed'}", flush=True)
    finally:
        st.kernel.stop()
    ok = [r for r in rows if r["correct"].get("builds") and r["fault"].get("builds")]
    tot = {"tasks": len(rows), "built_both": len(ok),
           "oracle_requirements": sum(r["oracle_requirements"] for r in rows),
           "stated_in_words": sum(r["stated_in_words"] for r in rows), "read_from_words": sum(r["read"] for r in rows),
           "said_as_typed_assertions": sum(r["typed"] for r in rows), "cannot_be_said": sum(len(r["cannot_be_said"]) for r in rows),
           "correct_green": {k: sum(1 for r in ok if r["correct"][k]["green"]) for k in ("words", "typed")},
           "false_alarm_rows": {k: sum(len(r["correct"][k]["fail"]) for r in ok) for k in ("words", "typed")},
           "faults_caught": {k: sum(1 for r in ok if r["fault"][k]["fail"]) for k in ("words", "typed")},
           "faults_missed": {k: [r["task"] + ": " + r["seeded"] for r in ok if not r["fault"][k]["fail"]] for k in ("words", "typed")},
           "without_a_contract": "every build here is a valid single solid: all 13 faults are silent"}
    print(json.dumps(tot, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps({"totals": tot, "rows": rows}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
