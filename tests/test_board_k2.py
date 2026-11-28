"""Schematic, placement and routing on KiCad's file formats (form/board, wave K2).

Every board and library here is synthetic (form.board.synth, form.board.kicad.write_fixture): made-up numbers, no
KiCad needed. What is tested:

- the S-expression writer gives back the tree it read, atom for atom, for a board and for a schematic;
- a schematic's netlist is the one its wires, junctions, labels and power symbols describe; Form Studio's ERC subset
  finds an open pin, a power pin nothing drives and two outputs on one net, and never calls itself KiCad's;
- the router completes synthetic boards with no clearance violation, measured here by a second, separate formula
  (segment to segment distance, form.board.kicad._seg_dist) as well as by Form Studio's own geometric check; a net
  that cannot be finished is reported with the pad it could not reach; a congested board that the first pass cannot
  finish is finished by rip-up and reroute, and by negotiated congestion on its own; routing twice gives the same
  file;
- the geometric check itself finds planted violations;
- placement honours fixed connectors, keep-outs, heights and the outline;
- the Specctra .dsn and .ses are written and read, and Freerouting is only ever run when it is installed and on.
Paths that need KiCad's kicad-cli are skipped when it is not installed; nothing here pretends KiCad ran."""
import json
import math
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = tempfile.mkdtemp(prefix="form-board-k2-")

from form.board import drc, geom, kicad, kicad_cli, pcb, place, route, schematic, sexpr, specctra, synth  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def tmp(name: str) -> Path:
    return Path(TMP) / name


def libs() -> schematic.Libraries:
    return schematic.Libraries([synth.symbol_library(tmp("Form.kicad_sym"))], standard=False)


def demo_schematic() -> schematic.Schematic:
    """A connector, a regulator, an MCU driving an LED through a resistor, a decoupling capacitor."""
    sch = schematic.Schematic.new("demo")
    sch.apply([
        {"op": "place", "lib_id": "Form:CONN2", "at": [50, 50], "ref": "J1", "footprint": "Form:Header_1x02"},
        {"op": "place", "lib_id": "Form:REG", "at": [80, 50], "footprint": "Form:SOT-223"},
        {"op": "place", "lib_id": "Form:MCU", "at": [120, 50], "footprint": "Form:MCU_6"},
        {"op": "place", "lib_id": "Form:R_Small", "at": [150, 40], "value": "330", "footprint": "Form:R_0603"},
        {"op": "place", "lib_id": "Form:LED", "at": [165, 60], "footprint": "Form:LED_0603"},
        {"op": "place", "lib_id": "Form:C", "at": [100, 70], "value": "100n", "footprint": "Form:C_0603"},
        {"op": "annotate"},
        {"op": "net", "name": "VIN", "pins": ["J1.1", "U1.1"]},
        {"op": "power", "lib_id": "Form:GND", "pin": "J1.2"}, {"op": "power", "lib_id": "Form:GND", "pin": "U1.2"},
        {"op": "power", "lib_id": "Form:GND", "pin": "U2.2"}, {"op": "power", "lib_id": "Form:GND", "pin": "C1.2"},
        {"op": "power", "lib_id": "Form:GND", "pin": "D1.1"},
        {"op": "net", "name": "+3V3", "pins": ["U1.3", "U2.1", "C1.1"], "kind": "global"},
        {"op": "net", "name": "LED", "pins": ["U2.3", "R1.1"]},
        {"op": "connect", "from": "R1.2", "to": "D1.2"},
        {"op": "annotate"},
    ], libs())
    return sch


class Writer(unittest.TestCase):
    def test_a_board_is_written_back_atom_for_atom(self):
        f = kicad.write_fixture(tmp("rt.kicad_pcb"))
        tree = sexpr.parse(f.read_text(encoding="utf-8"))
        again = sexpr.parse(sexpr.dump(tree))
        self.assertTrue(sexpr.same(tree, again))
        self.assertEqual(sexpr.dump(again), sexpr.dump(tree))             # and writing is stable

    def test_quoted_and_bare_atoms_keep_their_kind(self):
        t = sexpr.parse('(a (layer "F.Cu") (layer F.Cu) (s "x \\"y\\"\\n z") (e "") (n -0.5 1e3))')
        u = sexpr.parse(sexpr.dump(t))
        self.assertTrue(sexpr.same(t, u))
        self.assertFalse(sexpr.same(sexpr.parse('(a "b")'), sexpr.parse("(a b)")))
        self.assertEqual(sexpr.sym(0.30000000001), "0.3")
        self.assertEqual(sexpr.sym(-0.0), "0")

    def test_the_board_model_is_the_same_after_a_round_trip(self):
        f = kicad.write_fixture(tmp("rt2.kicad_pcb"))
        doc = pcb.Pcb.load(f)
        g = doc.save(tmp("rt2-out.kicad_pcb"))
        a, b = kicad.read(f), kicad.read(g)
        for k in ("size", "outline", "holes", "components", "keepouts", "copper", "mounting_holes"):
            self.assertEqual(a[k], b[k], k)

    def test_segments_and_vias_written_are_read_back(self):
        doc = pcb.Pcb.load(kicad.write_fixture(tmp("rt3.kicad_pcb")))
        n0, v0 = len(doc.tracks()), len(doc.vias())
        nid = doc.net_id("GND")
        doc.add_segment((110.0, 110.0), (112.5, 112.5), 0.25, "B.Cu", nid)
        doc.add_via((112.5, 112.5), 0.6, 0.3, nid)
        again = pcb.Pcb.load(doc.save(tmp("rt3-out.kicad_pcb")))
        t = again.tracks()[-1]
        self.assertEqual((len(again.tracks()), len(again.vias())), (n0 + 1, v0 + 1))
        self.assertEqual((t["a"], t["b"], t["w"], t["layer"], t["net"]), ((110.0, 110.0), (112.5, 112.5), 0.25, "B.Cu", nid))
        self.assertEqual(again.vias()[-1]["at"], (112.5, 112.5))
        self.assertEqual(again.clear_routes({nid}), 4)                 # the fixture's GND track and via, and these two

    def test_moving_a_footprint_moves_its_pads_and_turns_them(self):
        doc = synth.header_to_ic()
        before = {p["num"]: (p["x"], p["y"]) for p in doc.footprint("R1")["pads"]}
        doc.move_footprint("R1", 120.0, 110.0, 90.0)
        after = {p["num"]: (round(p["x"], 6), round(p["y"], 6), p["angle"]) for p in doc.footprint("R1")["pads"]}
        self.assertNotEqual(before["1"], after["1"][:2])
        self.assertEqual(after["1"], (120.0, 110.8, 90.0))             # (-0.8, 0) turned 90 degrees on KiCad's sheet
        self.assertEqual(after["2"], (120.0, 109.2, 90.0))


class Rules(unittest.TestCase):
    def test_net_classes_come_from_the_project_file(self):
        f = synth.header_to_ic(tmp("rules.kicad_pcb")).path
        f.with_suffix(".kicad_pro").write_text(json.dumps({
            "board": {"design_settings": {"rules": {"min_copper_edge_clearance": 0.3, "min_clearance": 0.15}}},
            "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.2, "via_diameter": 0.6, "via_drill": 0.3},
                                         {"name": "Power", "clearance": 0.25, "track_width": 0.5, "via_diameter": 0.8, "via_drill": 0.4}],
                             "netclass_patterns": [{"netclass": "Power", "pattern": "VCC"}, {"netclass": "Power", "pattern": "GN*"}]}}))
        doc = pcb.Pcb.load(f)
        self.assertEqual(doc.rules.for_net("VCC")["track_width"], 0.5)
        self.assertEqual(doc.rules.for_net("GND")["class"], "Power")
        self.assertEqual(doc.rules.for_net("D0")["clearance"], 0.15)
        self.assertEqual(doc.rules.board["min_copper_edge_clearance"], 0.3)
        self.assertIn("specified", doc.rules.describe()["source"])
        r = route.route(doc)
        self.assertTrue(r["complete"], r["unrouted"])
        self.assertEqual(r["check"]["total"], 0, r["check"]["rows"][:3])
        widths = {t["net"]: t["w"] for t in doc.tracks()}
        self.assertEqual(widths[doc.net_id("VCC", create=False)], 0.5)
        self.assertEqual(widths[doc.net_id("D0", create=False)], 0.2)
        self.assertTrue(all(v["size"] in (0.6, 0.8) for v in doc.vias()))

    def test_without_a_project_file_the_defaults_are_said_to_be_assumed(self):
        d = synth.rooms().rules.describe()
        self.assertIn("assumed", d["source"])
        self.assertEqual(d["classes"]["Default"]["track_width"], 0.2)


class Geometry(unittest.TestCase):
    def test_gaps_in_closed_form(self):
        a = geom.capsule((0, 0), (10, 0), 0.2)
        self.assertAlmostEqual(geom.gap(a, geom.capsule((0, 1), (10, 1), 0.2)), 0.8)
        self.assertAlmostEqual(geom.gap(a, geom.circle((5, 2), 1.0)), 1.4)
        self.assertAlmostEqual(geom.gap(a, geom.capsule((5, -3), (5, 3), 0.2)), -0.2)            # they cross
        rect, exact = geom.pad_shape("rect", (5, 2), 2.0, 1.0)
        self.assertTrue(exact)
        self.assertAlmostEqual(geom.gap(a, rect), 1.4)
        rr, exact = geom.pad_shape("roundrect", (0, 0), 2.0, 1.0, 0.0, 0.25)
        self.assertTrue(exact)
        self.assertAlmostEqual(geom.pt_gap((1.0 + 0.3, 0), rr), 0.3)                              # flat side
        corner = math.hypot(1.0 - 0.75, 0.5 - 0.25) - 0.25                                        # past the corner's arc
        self.assertAlmostEqual(geom.pt_gap((1.0, 0.5), rr), corner)
        oval, _ = geom.pad_shape("oval", (0, 0), 1.0, 2.1, 90.0)
        self.assertAlmostEqual(geom.pt_gap((2.0, 0), oval), 2.0 - 1.05)                           # turned on its side
        self.assertFalse(geom.pad_shape("custom", (0, 0), 1, 1)[1])

    def test_the_grid_pitch_packs_tracks_at_their_rule(self):
        g = route.auto_pitch(0.4)
        k = round(0.4 / g)
        self.assertGreaterEqual(k * g, math.sqrt(0.4 ** 2 + g * g / 2))                # k cells apart is legal
        self.assertLess(k * g - 0.4, 0.02)                                             # and wastes under 0.02 mm


class Schematics(unittest.TestCase):
    def test_the_file_is_written_back_atom_for_atom(self):
        sch = demo_schematic()
        f = sch.save(tmp("demo.kicad_sch"))
        again = schematic.Schematic.load(f)
        self.assertTrue(sexpr.same(sch.tree, again.tree))
        self.assertEqual(schematic.Schematic.public(again.netlist()), schematic.Schematic.public(sch.netlist()))
        self.assertEqual(again.save(tmp("demo2.kicad_sch")).read_text(), f.read_text())

    def test_the_netlist(self):
        nl = demo_schematic().netlist()
        nets = {n["name"]: sorted(f"{x['ref']}.{x['pin']}" for x in n["nodes"]) for n in nl["nets"]}
        self.assertEqual(nets["VIN"], ["J1.1", "U1.1"])
        self.assertEqual(nets["GND"], ["C1.2", "D1.1", "J1.2", "U1.2", "U2.2"])
        self.assertEqual(nets["+3V3"], ["C1.1", "U1.3", "U2.1"])
        self.assertEqual(nets["LED"], ["R1.1", "U2.3"])
        self.assertEqual(nets["Net-(D1-A)"], ["D1.2", "R1.2"])
        self.assertEqual(nets["unconnected-(U2-PA1)"], ["U2.4"])
        self.assertEqual(sum(len(v) for v in nets.values()), 2 + 3 + 6 + 2 + 2 + 2)   # every pin of every part, once
        comps = {c["ref"]: c for c in nl["components"]}
        self.assertEqual(sorted(comps), ["C1", "D1", "J1", "R1", "U1", "U2"])
        self.assertEqual((comps["R1"]["value"], comps["R1"]["footprint"]), ("330", "Form:R_0603"))
        types = {(x["ref"], x["pin"]): x["type"] for n in nl["nets"] for x in n["nodes"]}
        self.assertEqual(types[("U1", "3")], "power_out")

    def test_wires_junctions_and_crossings(self):
        """Hand-written: two wires that cross join only where a junction is; a wire end on a wire joins; pins turn
        with their symbol (KiCad's orientation matrices) and flip with its mirror."""
        lib = ('(symbol "T:P" (symbol "P_1_1" (pin passive line (at 5.08 2.54 180) (length 2.54) (name "A") (number "1"))'
               ' (pin passive line (at -5.08 0 0) (length 2.54) (name "B") (number "2"))))')

        def part(ref, x, y, rot, mirror=""):
            m = f" (mirror {mirror})" if mirror else ""
            return (f'(symbol (lib_id "T:P") (at {x} {y} {rot}){m} (unit 1) (property "Reference" "{ref}" (at 0 0 0))'
                    f' (property "Value" "P" (at 0 0 0)))')
        text = ('(kicad_sch (version 20231120) (generator "t") (uuid "u") (lib_symbols ' + lib + ") " +
                part("A", 100, 100, 0) + part("B", 100, 150, 90) + part("C", 150, 100, 180, "x") + part("D", 150, 150, 270, "y") +
                # A.1 at (105.08, 97.46): a wire to x=120, crossing a vertical wire at (110, 97.46) with no junction
                '(wire (pts (xy 105.08 97.46) (xy 120 97.46)))'
                '(wire (pts (xy 110 90) (xy 110 110)))'
                # a second pair that does have a junction, and a wire ending on another wire
                '(wire (pts (xy 94.92 100) (xy 80 100)))'
                '(wire (pts (xy 85 90) (xy 85 110)))'
                '(junction (at 85 100))'
                '(wire (pts (xy 110 110) (xy 110 120) (xy 85 120)))'
                '(wire (pts (xy 85 110) (xy 85 130)))'
                '(label "TOP" (at 120 97.46 0)) (label "CROSS" (at 110 90 0)) (label "LEFT" (at 80 100 0))'
                ')')
        sch = schematic.Schematic(sexpr.parse(text))
        at = {s["ref"]: {p["number"]: p["at"] for p in s["pins"]} for s in sch.symbols()}
        self.assertEqual(at["A"], {"1": (105.08, 97.46), "2": (94.92, 100.0)})
        self.assertEqual(at["B"], {"1": (97.46, 144.92), "2": (100.0, 155.08)})          # 90: (x, y) -> (-y, -x)
        self.assertEqual(at["C"], {"1": (144.92, 97.46), "2": (155.08, 100.0)})          # 180 then mirrored about x
        self.assertEqual(at["D"], {"1": (147.46, 155.08), "2": (150.0, 144.92)})         # 270 then mirrored about y
        nets = {n["name"]: sorted(f"{x['ref']}.{x['pin']}" for x in n["nodes"]) for n in sch.netlist()["nets"]}
        self.assertEqual(nets["TOP"], ["A.1"])                       # the crossing without a junction does not join
        self.assertNotIn("A.1", nets.get("CROSS", []))
        self.assertEqual(nets["CROSS"], ["A.2"])                     # ... but the junction, the corner and the T do:
        self.assertNotIn("LEFT", nets)                               # LEFT and CROSS are one net, named once
        both = next(n for n in sch.netlist()["nets"] if n["name"] == "CROSS")
        self.assertEqual(both["also"], ["LEFT"])

    def test_erc_subset_finds_what_it_claims_and_says_whose_it_is(self):
        e = demo_schematic().erc()
        self.assertIn("not KiCad's ERC", e["by"])
        self.assertIn("not KiCad's ERC", e["headline"])
        self.assertTrue(e["not_checked"])
        kinds = [(r["type"], r["items"][0].get("ref"), r["items"][0].get("pin")) for r in e["rows"]]
        self.assertIn(("pin_not_connected", "U2", "4"), kinds)
        self.assertIn(("pin_not_connected", "U2", "5"), kinds)
        self.assertNotIn(("pin_not_connected", "U2", "6"), kinds)                 # a no-connect pin may be open
        driven = {r["description"].split(":")[0] for r in e["rows"] if r["type"] == "power_pin_not_driven"}
        self.assertEqual(driven, {"Net GND", "Net VIN"})                           # +3V3 has the regulator's output

    def test_a_power_flag_and_a_no_connect_mark_clear_their_findings(self):
        sch = demo_schematic()
        sch.apply([{"op": "power", "lib_id": "Form:PWR_FLAG", "pin": "J1.1"}, {"op": "power", "lib_id": "Form:PWR_FLAG", "pin": "J1.2"},
                   {"op": "no_connect", "pin": "U2.4"}, {"op": "net", "name": "BTN", "pins": ["U2.5", "U2.4"]}], libs())
        e = sch.erc()
        self.assertFalse([r for r in e["rows"] if r["type"] == "power_pin_not_driven"], e["rows"])
        self.assertIn("no_connect_connected", [r["type"] for r in e["rows"]])      # marked open, then connected

    def test_two_outputs_on_one_net_are_a_conflict(self):
        sch = demo_schematic()
        sch.apply([{"op": "net", "name": "CLASH", "pins": ["U2.4", "U1.3"]}], libs())
        rows = [r for r in sch.erc()["rows"] if r["type"] == "conflicting_drivers"]
        self.assertEqual(len(rows), 1)
        self.assertEqual({(i["ref"], i["pin"]) for i in rows[0]["items"]}, {("U2", "4"), ("U1", "3")})
        self.assertEqual(rows[0]["severity"], "error")

    def test_operations_are_all_or_nothing(self):
        sch = demo_schematic()
        before = sexpr.dump(sch.tree)
        with self.assertRaises(ValueError) as cm:
            sch.apply([{"op": "set", "ref": "R1", "name": "Value", "value": "1k"}, {"op": "no_connect", "pin": "R9.1"}], libs())
        self.assertIn("Nothing was changed", str(cm.exception))
        self.assertEqual(sexpr.dump(sch.tree), before)
        with self.assertRaises(ValueError):
            sch.apply([{"op": "place", "lib_id": "Form:NOPE", "at": [10, 10]}], libs())

    def test_a_wire_that_would_run_over_another_pin_is_refused(self):
        sch = schematic.Schematic.new("w")
        sch.apply([{"op": "place", "lib_id": "Form:R", "at": [100, 50], "ref": "R1"},
                   {"op": "place", "lib_id": "Form:R", "at": [100, 70], "ref": "R2"}], libs())
        with self.assertRaises(ValueError) as cm:                                    # R1.1 down to R2.2 passes R1.2 and R2.1
            sch.apply([{"op": "connect", "from": "R1.1", "to": "R2.2"}], libs())
        self.assertIn("another pin", str(cm.exception))

    def test_libraries_resolve_extends_and_search(self):
        L = libs()
        self.assertIn("R_Small", L.names("Form"))
        s = L.symbol("Form:R_Small")
        self.assertEqual(s[1], "Form:R_Small")
        self.assertEqual([p["number"] for p in schematic.lib_pins(s)], ["1", "2"])    # the parent's pins
        self.assertEqual([x["lib_id"] for x in L.search("form led")], ["Form:LED"])
        with self.assertRaises(KeyError):
            L.symbol("Nope:R")
        self.assertFalse(schematic.Libraries([], standard=False).status()["available"])

    def test_a_schematic_becomes_a_board_with_its_footprints_and_nets(self):
        nl = demo_schematic().netlist()
        synth.footprint_library(TMP)
        doc, info = pcb.from_netlist(nl, (40.0, 30.0), [Path(TMP)])
        self.assertEqual(info["missing"], [])
        self.assertEqual(sorted(info["placed"]), ["C1", "D1", "J1", "R1", "U1", "U2"])
        pads = {(p["ref"], p["num"]): p["net_name"] for p in doc.pads()}
        self.assertEqual(pads[("U1", "3")], "+3V3")
        self.assertEqual(pads[("D1", "1")], "GND")
        self.assertEqual(pads[("U2", "6")], "unconnected-(U2-NC)")
        nl["components"][0]["footprint"] = "Form:Missing"
        _doc, info = pcb.from_netlist(nl, (40.0, 30.0), [Path(TMP)])
        self.assertEqual([m["ref"] for m in info["missing"]], ["C1"])               # listed, not substituted


def independent_gaps(doc: pcb.Pcb) -> float:
    """The smallest copper gap between tracks of different nets on one layer, by a formula that is not the
    checker's: segment to segment distance (form.board.kicad._seg_dist) less the two half widths."""
    ts = doc.tracks()
    best = math.inf
    for i, a in enumerate(ts):
        for b in ts[i + 1:]:
            if a["net"] != b["net"] and a["layer"] == b["layer"]:
                best = min(best, kicad._seg_dist(a["a"], a["b"], b["a"], b["b"]) - a["w"] / 2 - b["w"] / 2)
    return best


def octilinear(doc: pcb.Pcb, tol: float = 1e-6) -> int:
    """How many tracks are not horizontal, vertical or at 45 degrees."""
    bad = 0
    for t in doc.tracks():
        dx, dy = abs(t["b"][0] - t["a"][0]), abs(t["b"][1] - t["a"][1])
        if not (dx < tol or dy < tol or abs(dx - dy) < tol):
            bad += 1
    return bad


class Router(unittest.TestCase):
    def test_a_two_layer_board_routes_to_completion_with_no_violations(self):
        doc = synth.header_to_ic()
        r = route.route(doc)
        self.assertTrue(r["complete"], r["unrouted"])
        self.assertEqual((r["routed"], r["nets"]), (16, 16))
        c = r["check"]
        self.assertIn("not KiCad's DRC", c["by"])
        self.assertEqual(c["total"], 0, c["rows"][:3])
        self.assertEqual(c["unconnected"], [])
        self.assertGreaterEqual(c["min_clearance"]["gap_mm"], 0.2)
        self.assertGreaterEqual(independent_gaps(doc), 0.2 - 1e-6)
        self.assertGreater(r["vias"], 0)                                   # the nets cross: it needs the other side
        self.assertTrue(c["not_checked"])
        # the written file reads back to the same copper, and the model of the board still reads
        f = doc.save(tmp("routed.kicad_pcb"))
        again = pcb.Pcb.load(f)
        self.assertEqual(len(again.tracks()), r["segments"])
        self.assertEqual(len(again.vias()), r["vias"])
        self.assertEqual(drc.check(again)["total"], 0)
        self.assertEqual(kicad.read(f)["copper"]["tracks"], r["segments"])

    def test_the_same_board_routes_to_the_same_file(self):
        a, b = synth.header_to_ic(), synth.header_to_ic()
        route.route(a)
        route.route(b)
        self.assertEqual(a.text(), b.text())

    def test_pull_tight_leaves_straight_and_45_degree_tracks_and_fewer_of_them(self):
        raw, tight = synth.header_to_ic(), synth.header_to_ic()
        r0 = route.route(raw, smooth=False)
        r1 = route.route(tight)
        self.assertLess(r1["segments"], r0["segments"] / 3)
        self.assertLessEqual(r1["length_mm"], r0["length_mm"] + 1e-6)
        self.assertEqual(r1["check"]["total"], 0)
        # only the short leads from the grid onto a pad's centre are at another angle
        centres = {(round(p["x"], 6), round(p["y"], 6)) for p in tight.pads()}
        self.assertGreater(octilinear(tight), 0)
        for t in tight.tracks():
            dx, dy = abs(t["b"][0] - t["a"][0]), abs(t["b"][1] - t["a"][1])
            if not (dx < 1e-6 or dy < 1e-6 or abs(dx - dy) < 1e-6):
                self.assertIn(t["b"], centres, t)
                self.assertLess(math.hypot(dx, dy), 1.0)

    def test_a_pad_that_cannot_be_reached_is_reported_not_dropped(self):
        doc = synth.header_to_ic(unrouted_extra=True)
        r = route.route(doc)
        self.assertFalse(r["complete"])
        self.assertEqual(r["routed"], 15)
        (u,) = r["unrouted"]
        self.assertEqual((u["net"], u["pads_not_joined"]), ("D0", ["TP1.1"]))
        self.assertEqual(u["pads_joined"], ["J1.3", "U1.3"])               # what could be joined was
        self.assertTrue(u["why"])
        self.assertEqual(r["check"]["total"], 0)
        self.assertEqual(r["check"]["unconnected_total"], 1)               # and the check counts it too
        self.assertFalse(r["check"]["ok"])

    def test_rip_up_finishes_a_board_the_first_pass_cannot(self):
        first = route.route(synth.rooms(), layers=("F.Cu",), strategy="ripup", max_rips=0)
        self.assertEqual(first["routed"], 1)                                # without rip-up, net B has no way
        self.assertEqual([u["net"] for u in first["unrouted"]], ["B"])
        doc = synth.rooms()
        r = route.route(doc, layers=("F.Cu",), strategy="ripup")
        self.assertTrue(r["complete"], r["unrouted"])
        self.assertGreaterEqual(r["stats"]["ripped"], 1)
        self.assertEqual(r["stats"]["negotiation_iterations"], 0)
        self.assertEqual(r["check"]["total"], 0, r["check"]["rows"][:3])
        self.assertEqual(r["vias"], 0)
        self.assertGreaterEqual(independent_gaps(doc), 0.2 - 1e-6)

    def test_negotiated_congestion_finishes_it_on_its_own(self):
        doc = synth.rooms()
        r = route.route(doc, layers=("F.Cu",), strategy="negotiated")
        self.assertTrue(r["complete"], r["unrouted"])
        self.assertEqual(r["stats"]["ripped"], 0)
        self.assertGreater(r["stats"]["negotiation_iterations"], 1)         # it took more than one round of sharing
        self.assertEqual(r["check"]["total"], 0, r["check"]["rows"][:3])
        self.assertEqual(r["check"]["unconnected"], [])

    def test_a_full_channel(self):
        doc = synth.channel(n=8, slack=0.05)
        r = route.route(doc, layers=("F.Cu",))
        self.assertTrue(r["complete"], r["unrouted"])
        self.assertEqual(r["check"]["total"], 0)
        self.assertGreaterEqual(independent_gaps(doc), 0.2 - 1e-6)

    def test_lee_wavefront_routes_too(self):
        doc = synth.rooms()
        r = route.route(doc, layers=("F.Cu",), algorithm="lee")
        self.assertTrue(r["complete"])
        self.assertGreater(r["stats"]["lee_searches"], 0)
        self.assertEqual(r["stats"]["astar_searches"], 0)
        self.assertEqual(r["check"]["total"], 0)

    def test_tracks_already_on_the_board_are_kept_and_respected(self):
        doc = synth.header_to_ic()
        route.route(doc, nets=["VCC", "GND"])
        kept = [(t["a"], t["b"], t["net"]) for t in doc.tracks()]
        r = route.route(doc)
        self.assertEqual(r["nets"], 14)
        self.assertEqual(r["already_joined"], ["GND", "VCC"])
        self.assertTrue(r["complete"], r["unrouted"])
        self.assertEqual([(t["a"], t["b"], t["net"]) for t in doc.tracks()][:len(kept)], kept)
        self.assertEqual(r["check"]["total"], 0, r["check"]["rows"][:3])
        self.assertEqual(r["check"]["unconnected"], [])

    def test_keep_outs_and_the_edge_are_respected(self):
        doc = synth.rooms()
        route.route(doc, layers=("F.Cu",))
        walls = [z["polygon"] for z in doc.keepouts()]
        for t in doc.tracks():
            for w in walls:
                self.assertFalse(geom.inside(t["a"], w) or geom.inside(t["b"], w))
                self.assertGreaterEqual(geom.poly_seg_dist(w, t["a"], t["b"]), t["w"] / 2 - 1e-6)
            for q in (t["a"], t["b"]):
                self.assertTrue(100.6 - 1e-6 <= q[0] <= 129.4 + 1e-6 and 100.6 - 1e-6 <= q[1] <= 119.4 + 1e-6, q)


class Checker(unittest.TestCase):
    """The check has to find what is wrong before its "no findings" means anything."""

    def test_planted_violations_are_found(self):
        doc = synth.header_to_ic()
        a, b = doc.net_id("D0", create=False), doc.net_id("D1", create=False)
        doc.add_segment((110.0, 127.0), (116.0, 127.0), 0.2, "F.Cu", a)
        doc.add_segment((110.0, 127.35), (116.0, 127.35), 0.2, "F.Cu", b)          # 0.15 mm of copper gap
        doc.add_segment((138.0, 128.0), (139.9, 128.0), 0.2, "F.Cu", a)            # 0.0 mm from the edge
        doc.add_via((110.0, 127.0), 0.6, 0.3, a)
        c = drc.check(doc)
        kinds = {r["type"] for r in c["rows"]}
        self.assertLessEqual({"clearance", "edge"}, kinds)
        gap = next(r for r in c["rows"] if r["type"] == "clearance" and "track" in r["items"][0] and "track" in r["items"][1])
        self.assertAlmostEqual(gap["measured_mm"], 0.15, places=4)
        self.assertEqual(gap["required_mm"], 0.2)
        self.assertFalse(c["ok"])
        self.assertTrue(any(u["net"] == "D0" for u in c["unconnected"]))

    def test_a_track_in_a_keep_out_and_over_a_hole(self):
        doc = synth.rooms()
        n = doc.net_id("A", create=False)
        doc.add_segment((105.0, 109.0), (105.0, 111.0), 0.2, "F.Cu", n)             # through the wall
        pcb.add_part(doc, "H1", (120.0, 105.0), [{"num": "", "at": (0, 0), "size": (2.2, 2.2), "shape": "circle",
                                                  "kind": "np_thru_hole", "drill": 2.2}])
        doc.add_segment((118.0, 105.0), (118.7, 105.0), 0.2, "F.Cu", n)             # 0.1 mm from the hole's wall
        c = drc.check(doc)
        self.assertIn("keepout", {r["type"] for r in c["rows"]})
        hole = next(r for r in c["rows"] if r["type"] == "hole_clearance")
        self.assertAlmostEqual(hole["measured_mm"], 0.1, places=4)

    def test_the_fixture_boards_planted_short_is_found(self):
        c = drc.check(pcb.Pcb.load(kicad.write_fixture(tmp("short.kicad_pcb"))))    # its VBUS track runs over a GND pad
        self.assertTrue(any("C1.2" in " ".join(r["items"]) and r["measured_mm"] < 0 for r in c["rows"]), c["rows"])

    def test_connections(self):
        doc = synth.rooms()
        self.assertEqual(drc.check(doc)["unconnected_total"], 2)
        n = doc.net_id("B", create=False)
        doc.add_segment((125.0, 103.0), (126.0, 103.0), 0.2, "F.Cu", n)             # leaves the pad, reaches nothing
        self.assertEqual(drc.check(doc)["unconnected_total"], 2)


class Placement(unittest.TestCase):
    def board(self):
        doc = pcb.blank(40.0, 30.0)
        two = lambda a, b: [{"num": "1", "at": (-0.8, 0), "size": (0.8, 0.95), "net": a}, {"num": "2", "at": (0.8, 0), "size": (0.8, 0.95), "net": b}]
        pcb.add_part(doc, "J1", (104.0, 115.0), [{"num": "1", "at": (0, -1.27), "size": (1.7, 1.7), "kind": "thru_hole", "net": "VIN"},
                                                 {"num": "2", "at": (0, 1.27), "size": (1.7, 1.7), "kind": "thru_hole", "net": "GND"}],
                     lib="Connector:Header", height=8.5)
        # everything else piled on one spot, far from the connector
        pcb.add_part(doc, "R1", (135.0, 125.0), two("VIN", "A"), lib="Form:R_0603", height=0.55)
        pcb.add_part(doc, "R2", (135.0, 125.0), two("A", "B"), lib="Form:R_0603", height=0.55)
        pcb.add_part(doc, "C1", (135.2, 125.3), two("B", "GND"), lib="Form:C_0603", height=0.9)
        pcb.add_part(doc, "C2", (135.0, 125.0), two("VIN", "GND"), lib="Form:C_tall", height=7.0)
        return doc

    def test_overlaps_are_found_then_placed_away(self):
        doc = self.board()
        cons = place.constraints(doc, max_height=10.0, fixed={"J1": "its opening in the wall"})
        before = place.check(doc, cons)
        self.assertFalse(before["ok"])
        self.assertIn("overlap", {r["type"] for r in before["rows"]})
        r = place.place(doc, cons)
        self.assertTrue(r["complete"], r["check"]["rows"])
        self.assertTrue(r["check"]["ok"])
        self.assertNotIn("J1", [m["ref"] for m in r["moved"]])               # the fixed connector did not move
        self.assertEqual((doc.footprint("J1")["x"], doc.footprint("J1")["y"]), (104.0, 115.0))
        self.assertLess(r["wire_length_mm"]["after"], r["wire_length_mm"]["before"])
        self.assertIn("not a 3D fit", r["check"]["evidence"])
        again = pcb.Pcb.load(doc.save(tmp("placed.kicad_pcb")))
        self.assertTrue(place.check(again, place.constraints(again, max_height=10.0, fixed={"J1": "x"}))["ok"])

    def test_keep_outs_height_zones_and_the_outline(self):
        doc = self.board()
        ko = [{"circle": [[125.0, 115.0], 5.0], "side": "both", "why": "a standoff"}]
        cons = place.constraints(doc, max_height=10.0, fixed={"J1": "x"}, keepouts=ko)
        low = [(108, 100), (140, 100), (140, 118), (108, 118)]
        cons.zones.append({"polygon": low, "side": "top", "max_h": 2.0,
                           "why": "under the lid's lip"})
        r = place.place(doc, cons)
        self.assertTrue(r["complete"], r["check"]["rows"])
        for f in doc.footprints():
            rect = place._rect({"box": f["box"]}, f["x"], f["y"], f["rot"])
            if f["ref"] != "J1":
                self.assertFalse(place._rect_circle(rect, (125.0, 115.0), 5.0), f["ref"])
                self.assertTrue(100.5 - 1e-6 <= rect[0] and rect[2] <= 139.5 + 1e-6 and 100.5 - 1e-6 <= rect[1] and rect[3] <= 129.5 + 1e-6)
        c2 = doc.footprint("C2")                                           # the tall one is out of the low zone
        self.assertFalse(place._rect_hits_poly(place._rect({"box": c2["box"]}, c2["x"], c2["y"], c2["rot"]), low))
        rects = [(f["ref"], place._rect({"box": f["box"]}, f["x"], f["y"], f["rot"])) for f in doc.footprints()]
        for i, (ra, a) in enumerate(rects):
            for rb, b in rects[i + 1:]:
                ox, oy = place._overlap(a, b)
                self.assertFalse(ox > 1e-9 and oy > 1e-9, (ra, rb))

    def test_too_tall_everywhere_is_reported_and_left_where_it_was(self):
        doc = self.board()
        cons = place.constraints(doc, max_height=5.0, fixed={"J1": "x"})
        r = place.place(doc, cons)
        self.assertEqual([n["ref"] for n in r["not_placed"]], ["C2"])
        self.assertFalse(r["complete"])
        self.assertEqual((doc.footprint("C2")["x"], doc.footprint("C2")["y"]), (135.0, 125.0))
        self.assertIn("height", {x["type"] for x in r["check"]["rows"]})

    def test_a_part_without_a_height_is_not_checked_not_passed(self):
        doc = self.board()
        pcb.add_part(doc, "U9", (120.0, 110.0), [{"num": "1", "at": (0, 0), "size": (1, 1), "net": "A"}])
        c = place.check(doc, place.constraints(doc, max_height=10.0))
        self.assertEqual(c["height_not_checked"], ["U9"])
        self.assertIn("not checked", c["headline"])

    def test_constraints_from_the_board_and_its_enclosure(self):
        from form.board import api
        f = kicad.write_fixture(tmp("cons.kicad_pcb"))
        board = api.read(f)
        layout = {"H": 20.0, "board_top": 7.6, "board_z": 6.0, "cavity": [-41.0, -26.0, 41.0, 26.0]}
        values = {"floor": 2.0, "standoff_d": 7.0, "lip_h": 2.5, "lip_wall": 1.6, "lip_clearance": 0.25}
        cons = place.constraints(pcb.Pcb.load(f), board, layout, values)
        d = cons.describe()
        self.assertEqual(list(d["fixed"]), ["J1"])                           # the USB-C receptacle on the front edge
        self.assertIn("opening", d["fixed"]["J1"])
        self.assertEqual(d["max_height_mm"], {"top": 12.4, "bottom": 4.0})
        self.assertEqual(len([k for k in d["keepouts"] if "standoff" in k["why"]]), 4)
        self.assertEqual(len([k for k in d["keepouts"] if "screw" in k["why"]]), 4)
        self.assertEqual({z["max_h"] for z in d["height_zones"]}, {9.9})
        stand = next(k for k in d["keepouts"] if "standoff under H1" in k["why"])
        self.assertEqual(stand["circle"], [[103.5, 103.5], 3.8])             # in the board file's own coordinates


class Specctra(unittest.TestCase):
    def test_the_design_file_has_the_board(self):
        doc = synth.header_to_ic()
        info = specctra.write_dsn(doc, tmp("ic.dsn"))
        text = tmp("ic.dsn").read_text()
        self.assertIn('(string_quote ")', text)
        import re
        tree = sexpr.parse(re.sub(r"\(\s*string_quote\s+\"\s*\)", "", text))
        self.assertEqual(sexpr.head(tree), "pcb")
        net = sexpr.first(tree, "network")
        nets = {str(sexpr.atoms(n)[0]): [str(a) for a in sexpr.atoms(sexpr.first(n, "pins"))] for n in sexpr.children(net, "net")}
        self.assertEqual(len(nets), 16)
        self.assertEqual(info["nets"], 16)
        self.assertEqual(sorted(nets["D0"]), ["J1-3", "U1-3"])
        self.assertEqual(len(sexpr.children(sexpr.first(tree, "placement"), "component")), 11)
        b = sexpr.atoms(sexpr.first(sexpr.first(sexpr.first(tree, "structure"), "boundary"), "path"))
        self.assertEqual([str(x) for x in b[2:6]], ["100000", "-100000", "140000", "-100000"])        # um, y up
        rule = sexpr.first(sexpr.first(tree, "structure"), "rule")
        self.assertEqual(str(sexpr.value(rule, "width")), "200")

    def test_a_session_becomes_segments_and_vias(self):
        doc = synth.rooms()
        ses = tmp("rooms.ses")
        ses.write_text('(session rooms.ses (base_design rooms.dsn) (placement (resolution um 10)) (was_is)\n'
                       ' (routes (resolution um 10) (parser (string_quote ") (host_cad "x"))\n'
                       '  (library_out (padstack "Via[0-1]_600:300_um" (shape (circle F.Cu 6000 0 0)) (attach off)))\n'
                       '  (network_out (net A (wire (path F.Cu 2000 1100000 -1070000 1100000 -1050000 1120000 -1030000))\n'
                       '    (via "Via[0-1]_600:300_um" 1120000 -1030000)) (net NOPE (wire (path F.Cu 2000 0 0 10 10))))))\n')
        s = specctra.read_ses(ses)
        self.assertEqual(s["wires"][0]["points"], [(110.0, 107.0), (110.0, 105.0), (112.0, 103.0)])
        self.assertEqual(s["wires"][0]["width"], 0.2)
        r = specctra.apply_ses(doc, s)
        self.assertEqual((r["segments"], r["vias"]), (2, 1))
        self.assertEqual(r["skipped"], ["wire of NOPE"])                    # a net the board does not have: said
        self.assertEqual(doc.vias()[0]["size"], 0.6)
        self.assertEqual(doc.vias()[0]["drill"], 0.3)

    def test_freerouting_is_never_run_unless_installed_and_switched_on(self):
        from form import installer, use
        self.assertFalse(use.SWITCHES["freerouting"]["default"])
        s = installer.get("freerouting")
        self.assertEqual((s.level, s.licence), ("optional", "GPL-3.0"))
        self.assertFalse(any(m.commands for m in installer.methods_for(s, "darwin", which=lambda n: "/x/" + n)))
        old = {k: os.environ.get(k) for k in ("FORM_FREEROUTING", "FORM_USE_FREEROUTING")}
        try:
            os.environ["FORM_FREEROUTING"] = str(tmp("no-such-freerouting"))
            os.environ.pop("FORM_USE_FREEROUTING", None)
            st = specctra.status({})
            self.assertFalse(st["available"])
            self.assertIn("not installed", st["reason"])
            doc = synth.rooms()
            r = specctra.run(doc, tmp("fr"), {})
            self.assertFalse(r["ran"])
            self.assertEqual(doc.tracks(), [])
            fake = tmp("freerouting-fake")
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            os.environ["FORM_FREEROUTING"] = str(fake)
            st = specctra.status({"use": {"freerouting": False}})
            self.assertFalse(st["available"])                               # installed, but off until switched on
            self.assertIn("switched off", st["reason"])
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    @unittest.skipIf(sys.platform.startswith("win"), "the stand-in program is a shell script")
    def test_the_exchange_with_a_stand_in_program(self):
        """Not Freerouting: a script that takes the same arguments and writes a session, to exercise the hand-over."""
        fake = tmp("freerouting-standin")
        fake.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do case "$1" in -do) out="$2"; shift;; esac; shift; done\n'
                        'cat > "$out" <<EOF\n(session s (routes (resolution um 10) (network_out (net A (wire (path F.Cu 2000 '
                        '1100000 -1070000 1100000 -1085000))))))\nEOF\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        old = {k: os.environ.get(k) for k in ("FORM_FREEROUTING", "FORM_USE_FREEROUTING")}
        try:
            os.environ["FORM_FREEROUTING"], os.environ["FORM_USE_FREEROUTING"] = str(fake), "1"
            doc = synth.rooms()
            r = specctra.run(doc, tmp("fr2"), {})
            self.assertTrue(r["ran"], r)
            self.assertEqual(r["segments"], 1)
            self.assertTrue((tmp("fr2") / "board.dsn").is_file())
            self.assertEqual(r["cmd"][1:3], ["-de", str(tmp("fr2") / "board.dsn")])
            self.assertEqual(drc.check(doc)["unconnected_total"], 2)        # one stub joins nothing, and the check says so
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class OnFiles(unittest.TestCase):
    """k2 on files outside a design: the file given is never changed."""

    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        os.environ["FORM_KICAD_CLI"] = str(Path(TMP) / "no-such-kicad-cli")
        from form import config
        from form.studio import Studio
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("FORM_KICAD_CLI", None)
        cls.st.kernel.stop()

    def test_route_writes_beside_and_says_who_checked(self):
        from form.board import k2
        from form.studio import StudioError
        f = synth.header_to_ic(tmp("file.kicad_pcb")).path
        before = f.read_bytes()
        r = k2.route(self.st, file=str(f))
        self.assertEqual(f.read_bytes(), before)
        self.assertEqual(Path(r["file"]).name, "file-routed.kicad_pcb")
        self.assertTrue(r["complete"])
        self.assertEqual(r["checked_by"], [drc.BY])
        self.assertFalse(r["kicad_drc"]["ran"])                              # KiCad is not here: said, not faked
        self.assertIn("not KiCad's", r["kicad_drc"]["why"])
        self.assertIn("KiCad DRC not run", r["headline"])
        with self.assertRaises(StudioError):
            k2.route(self.st, file=str(f))                                   # the result exists: not overwritten
        with self.assertRaises(StudioError):
            k2.route(self.st, file=str(f), out=str(f))                       # never over the file given
        r = k2.route(self.st, file=str(f), engine="freerouting", out=str(tmp("fr-out.kicad_pcb")))
        self.assertFalse(r["ran"])
        self.assertFalse(r["changed"])
        self.assertFalse(tmp("fr-out.kicad_pcb").exists())

    def test_schematic_actions(self):
        from form.board import k2
        lib = str(synth.symbol_library(tmp("Form.kicad_sym")))
        f = tmp("new.kicad_sch")
        r = k2.schematic(self.st, "edit", file=str(f), libraries=[lib], ops=[
            {"op": "place", "lib_id": "Form:R", "at": [100, 50]}, {"op": "place", "lib_id": "Form:C", "at": [120, 50]},
            {"op": "annotate"}, {"op": "net", "name": "X", "pins": ["R1.1", "C1.1"]}])
        self.assertTrue(f.is_file())
        self.assertIn("not KiCad's ERC", r["erc"]["by"])
        nl = k2.schematic(self.st, "netlist", file=str(f))
        self.assertEqual({n["name"]: len(n["nodes"]) for n in nl["nets"]}["X"], 2)
        json.dumps(nl)
        e = k2.schematic(self.st, "erc", file=str(f))
        self.assertFalse(e["kicad"]["ran"])
        self.assertIn("KiCad ERC not run", e["headline"])
        self.assertEqual(e["form"]["total"], 2)                              # R1.2 and C1.2 are open
        before = f.read_bytes()
        r2 = k2.schematic(self.st, "edit", file=str(f), libraries=[lib], ops=[{"op": "net", "name": "Y", "pins": ["R1.2", "C1.2"]}])
        self.assertEqual(f.read_bytes(), before)                             # an existing file is not written over
        self.assertEqual(Path(r2["file"]).name, "new-edited.kicad_sch")
        self.assertEqual(r2["erc"]["total"], 0)
        s = k2.schematic(self.st, "symbols", libraries=[lib], query="Form:REG")
        self.assertEqual([p["type"] for p in s["pins"]], ["power_in", "power_in", "power_out"])

    def test_cli_route_prints_json(self):
        f = synth.rooms(tmp("cli.kicad_pcb")).path
        env = {**os.environ, "PYTHONPATH": str(ROOT), "FORM_DATA": TMP, "FORM_KICAD_CLI": str(Path(TMP) / "no-such-kicad-cli")}
        out = subprocess.run([sys.executable, "-m", "form", "board", "route", str(f), "--layers", "F.Cu", "--out",
                              str(tmp("cli-out.kicad_pcb"))], capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        r = json.loads(out.stdout)
        self.assertTrue(r["complete"])
        self.assertEqual(r["routed"], 2)
        out = subprocess.run([sys.executable, "-m", "form", "board", "copper", str(tmp("cli-out.kicad_pcb"))],
                             capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(json.loads(out.stdout)["total"], 0)


class InADesign(unittest.TestCase):
    """The board of a design: placed against its enclosure and routed in the design's own copy."""

    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        os.environ["FORM_KICAD_CLI"] = str(Path(TMP) / "no-such-kicad-cli")
        from form import config
        from form.board import api
        from form.studio import Studio
        cls.st = Studio(config.load())
        d = Path(TMP) / "src"
        d.mkdir(exist_ok=True)
        cls.src = kicad.write_fixture(d / "prod.kicad_pcb")
        cls.src_bytes = cls.src.read_bytes()
        cls.imp = api.import_board(cls.st, str(cls.src), name="K2 box")
        cls.pid = cls.imp["project"]

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("FORM_KICAD_CLI", None)
        cls.st.kernel.stop()

    def test_1_placement_reads_the_enclosure(self):
        from form.board import k2
        r = k2.place(self.st, project=self.pid, check_only=True)
        c = r["constraints"]
        self.assertIn("J1", c["fixed"])
        self.assertIn("opening", c["fixed"]["J1"])
        self.assertIsNotNone(c["max_height_mm"]["top"])
        self.assertGreaterEqual(c["max_height_mm"]["top"], 10.0)             # the 10 mm capacitor plus headroom
        self.assertTrue(any("lip" in z["why"] for z in c["height_zones"]))
        self.assertEqual(len([k for k in c["keepouts"] if "standoff" in k["why"]]), 4)
        self.assertTrue(r["check"]["ok"], r["check"]["rows"])

    def test_2_the_bench_lists_the_new_entries(self):
        from form import studies
        reg = {s.id: s for s in studies.registry()}
        self.assertLessEqual({"board.copper", "board.placement", "board.schematic"}, set(reg))
        ctx = studies.Ctx(self.st, self.st.load(self.pid))
        r = reg["board.placement"].run(ctx)
        self.assertIn("computed", r["evidence"])
        self.assertTrue(reg["board.copper"].key(ctx))

    def test_3_routing_changes_the_designs_copy_only(self):
        from form.board import api, k2
        p = self.st.load(self.pid)
        key0 = p["board"]["key"]
        r = k2.route(self.st, project=self.pid)
        self.assertEqual(self.src.read_bytes(), self.src_bytes)              # the person's file is as it was
        d = api.board_dir(self.st, self.pid)
        self.assertEqual(Path(r["file"]), d / "prod.kicad_pcb")
        self.assertTrue((d / "history" / r["kept_previous"]).is_file())
        self.assertEqual((d / "history" / r["kept_previous"]).read_bytes(), self.src_bytes)
        self.assertEqual(r["unrouted"], [])
        self.assertEqual(r["check"]["unconnected"], [])
        # the fixture's own short (its VBUS track over a GND pad) is still reported; the router added none
        self.assertTrue(r["check"]["rows"])
        self.assertTrue(all("C1.2" in " ".join(x["items"]) or "at 120.000, 120.000" in " ".join(x["items"]) for x in r["check"]["rows"]),
                        r["check"]["rows"])
        self.assertFalse(r["kicad_drc"]["ran"])
        p = self.st.load(self.pid)
        self.assertNotEqual(p["board"]["key"], key0)                         # so the board's Bench entries go stale
        self.assertGreater(api.load(self.st, p)["copper"]["tracks"], 2)

    def test_4_copper_check_of_the_design(self):
        from form.board import k2
        c = k2.copper_check(self.st, self.st.load(self.pid))
        self.assertIn("not KiCad's DRC", c["by"])
        self.assertEqual(c["unconnected"], [])


class Honest(unittest.TestCase):
    def test_no_result_of_form_studios_claims_to_be_kicads(self):
        self.assertNotIn("KiCad DRC", drc.BY.replace("not KiCad's DRC", ""))
        self.assertNotEqual(drc.BY, kicad_cli.parse_drc({})["by"])
        self.assertNotEqual(schematic.ERC_BY, kicad_cli.parse_erc({})["by"])

    @unittest.skipUnless(kicad_cli.find(), "KiCad's kicad-cli is not installed")
    def test_kicads_own_drc_on_a_routed_board(self):
        doc = synth.header_to_ic(tmp("kdrc.kicad_pcb"))
        route.route(doc)
        f = doc.save(tmp("kdrc-routed.kicad_pcb"))
        r = kicad_cli.drc(kicad_cli.find(), f, tmp("kdrc"))
        self.assertTrue(r["ran"], r)
        self.assertEqual(r["by"], "KiCad DRC")
        bad = [x for x in r["rows"] if x["type"] in ("clearance", "shorting_items", "tracks_crossing", "unconnected_items")]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
