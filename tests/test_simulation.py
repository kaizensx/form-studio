"""Print simulation, cost and plate packing.

The toolpaths come from a small G-code written here in the style Bambu Studio writes (layer markers, feature
names, M73 remaining-time markers) and from the PrusaSlicer fixture, which has no usable per-layer time markers.
Nothing in these tests runs a slicer.
"""
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from form import cost, packing, simulate, toolpath

FIX = Path(__file__).resolve().parent / "fixtures" / "slicers"


def square(x0, y0, s, e=0.05):
    pts = [(x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s), (x0, y0)]
    return [f"G1 X{x0} Y{y0} F6000"] + [f"G1 X{x:g} Y{y:g} E{e}" for x, y in pts]


def bambu_gcode(layers=6, minutes=10, marks=True) -> str:
    """`layers` layers of a 20 mm square wall with an infill cross; layer 3 has a bridge, layer 4 an overhang wall."""
    out = ["; HEADER_BLOCK_START", f"; model printing time: {minutes}m 0s; total estimated time: {minutes}m 0s",
           f"; total layer number: {layers}", "; total filament length [mm] : 1000.00", "; total filament weight [g] : 3.00",
           "; HEADER_BLOCK_END", "; CONFIG_BLOCK_START", "; filament_cost = 25", "; filament_density = 1.24",
           "; filament_diameter = 1.75", "; filament_type = PLA", "; line_width = 0.42", "; nozzle_diameter = 0.4",
           "; printable_area = 0x0,180x0,180x180,0x180", "; CONFIG_BLOCK_END", "M83", f"M73 P0 R{minutes}"]
    for i in range(layers):
        z = round(0.2 * (i + 1), 2)
        out += ["; CHANGE_LAYER", f"; Z_HEIGHT: {z}", "; LAYER_HEIGHT: 0.2", f"G1 Z{z} F600", "; FEATURE: Outer wall"]
        out += square(80, 80, 20)
        if marks:                                             # the counter drops once per layer, in the middle of it
            out.append(f"M73 P{int(100 * (i + 0.5) / layers)} R{minutes - 1 - i}")
        out += ["; FEATURE: Bridge" if i == 2 else "; FEATURE: Overhang wall" if i == 3 else "; FEATURE: Sparse infill"]
        out += ["G1 X80 Y80 F6000", "G1 X100 Y100 E0.07", "G1 X100 Y80 F6000", "G1 X80 Y100 E0.07"]
    return "\n".join(out) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def gcode(self, **kw) -> Path:
        f = self.dir / "plate_1.gcode"
        f.write_text(bambu_gcode(**kw), encoding="utf-8")
        return f


class ToolpathTest(Base):
    def test_layers_types_and_lengths(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        self.assertEqual(tp.layers, 6)
        self.assertEqual(tp.types, ["Outer wall", "Overhang wall", "Bridge", "Sparse infill"])
        self.assertEqual(len(tp.seg), 6 * 6)                              # 4 wall moves + 2 diagonals per layer
        self.assertAlmostEqual(float(tp.length[0]), 80 + 2 * math.hypot(20, 20), places=3)
        self.assertEqual(tp.layers_with(toolpath.BRIDGE_TYPES), [2])
        self.assertEqual(tp.layers_with(toolpath.OVERHANG_TYPES), [3])
        self.assertAlmostEqual(tp.width, 0.42)
        self.assertEqual(tp.bbox[0][:2], [80.0, 80.0])
        self.assertAlmostEqual(float(tp.h[3]), 0.2, places=5)

    def test_slicer_markers_place_the_time_and_sum_to_the_total(self):
        tp = toolpath.from_gcode(self.gcode(minutes=10), "bambu")
        self.assertEqual(tp.time_source, "slicer markers")
        self.assertAlmostEqual(float(tp.time.sum()), 600.0, places=6)
        self.assertAlmostEqual(float(tp.t0[-1]), 600.0, places=6)
        self.assertTrue(np.all(tp.time > 0))
        # the counter says 9 min remain after the first layer's wall: 60 s have passed at 80 mm of path
        # (the next marker is 60 s and one layer of path later), so the first layer ends at 60 + 60 × the rest of it
        L = float(tp.length[0])
        self.assertAlmostEqual(float(tp.t0[1]), 60.0 + 60.0 * (L - 80.0) / L, delta=0.01)
        self.assertEqual(tp.at(79.0 / L)["type"], "Outer wall")
        # start-up makes the first layer longer than a middle one, although both have the same path
        self.assertGreater(float(tp.time[0]), float(tp.time[2]))

    def test_without_markers_time_is_interpolated_by_path_length(self):
        tp = toolpath.from_gcode(self.gcode(minutes=12, marks=False), "bambu")
        self.assertEqual(tp.time_source, "interpolated")
        self.assertIn("Interpolated", tp.summary()["time_note"])
        self.assertAlmostEqual(float(tp.time.sum()), 720.0, places=6)
        np.testing.assert_allclose(tp.time, 720.0 * tp.length / tp.length.sum(), rtol=1e-9)

    def test_no_time_is_reported_as_unknown_not_invented(self):
        f = self.gcode()
        tp = toolpath.build(__import__("form.slicer", fromlist=["x"]).parse_layers(f, "bambu"), None)
        self.assertEqual(tp.time_source, "unknown")
        self.assertIsNone(tp.summary()["time_s"])
        self.assertIsNone(tp.at(1.5)["elapsed_s"])

    def test_prusa_fixture(self):
        tp = toolpath.from_gcode(FIX / "prusa" / "plate_1.gcode", "prusa")
        self.assertGreater(tp.layers, 0)
        if tp.total_time_s:
            self.assertAlmostEqual(float(tp.time.sum()), tp.total_time_s, places=4)

    def test_nozzle_position_and_time_round_trip(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        a = tp.at(2.0)
        self.assertEqual((a["layer"], a["x"], a["y"]), (2, 80.0, 80.0))
        self.assertAlmostEqual(a["z"], 0.6, places=5)
        mid = tp.at(2 + 10 / float(tp.length[2]))                         # 10 mm along the first wall
        self.assertAlmostEqual(mid["x"], 90.0, places=2)
        for pr in (0.0, 1.25, 3.5, 5.9):
            self.assertAlmostEqual(tp.progress_at_time(tp.at(pr)["elapsed_s"]), pr, delta=0.01)
        self.assertEqual(toolpath.parse_range("2:4", 6), (1, 3))
        self.assertEqual(toolpath.parse_range(None, 6), (0, 5))
        with self.assertRaises(ValueError):
            toolpath.parse_range("5:2", 6)

    def test_public_round_trip(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        d = json.loads(json.dumps(tp.public()))                           # as the app receives it
        back = toolpath.from_public(d)
        np.testing.assert_array_equal(back.seg, tp.seg)
        np.testing.assert_array_equal(back.seg_type, tp.seg_type)
        np.testing.assert_allclose(back.length, tp.length, rtol=1e-5)
        self.assertEqual(back.at(3.4)["type"], tp.at(3.4)["type"])
        self.assertEqual(d["bridge_layers"], [2])
        self.assertEqual(d["note"], "Simulated from the slicer's G-code. Not a print.")

    def test_ribbon_buffers(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        colors = {"Outer wall": (1.0, 0.0, 0.0), "Bridge": (0.0, 1.0, 0.0)}
        buf = toolpath.ribbon_buffers(tp, colors)
        n = len(tp.seg)
        self.assertEqual((buf["primitive"], buf["stride"], buf["vertices"], buf["moves"]), ("triangles", 36, n * 6, n))
        v = np.frombuffer(buf["vertex"], dtype=np.float32).reshape(n, 6, 9)
        idx = np.frombuffer(buf["index"], dtype=np.uint32)
        self.assertEqual(len(idx), n * 12)
        self.assertLess(int(idx.max()), n * 6)
        # the first move: +X along y = 80, layer top 0.2, eaves one layer height lower and half a width to each side
        first = v[0]
        self.assertAlmostEqual(float(first[1, 2]), 0.2, places=5)
        self.assertAlmostEqual(float(first[0, 2]), 0.0, places=5)
        self.assertAlmostEqual(float(first[0, 1] - first[2, 1]), 0.42, places=4)
        np.testing.assert_allclose(first[:, 3:6], [[1, 0, 0]] * 6)        # the colour given for its type
        self.assertEqual(float(first[0, 6]), float(tp.types.index("Outer wall")))
        # progress rises along the print and never reaches the next layer's number
        self.assertAlmostEqual(float(first[0, 7]), 0.0)
        prog = v[:, :, 7]
        self.assertTrue(np.all(prog[:, 3] >= prog[:, 0]))
        for l in range(tp.layers):
            a, b = tp.start[l], tp.start[l + 1]
            self.assertGreaterEqual(float(prog[a:b].min()), l)
            self.assertLess(float(prog[a:b].max()), l + 1)
        # a layer range builds only those layers; lines mode is two vertices per move
        part = toolpath.ribbon_buffers(tp, colors, 2, 3)
        self.assertEqual(part["moves"], int(tp.start[4] - tp.start[2]))
        self.assertAlmostEqual(part["bounds"][1][2], 0.8, places=5)
        lines = toolpath.ribbon_buffers(tp, colors, mode="line")
        self.assertEqual((lines["primitive"], lines["vertices"], lines["index"]), ("lines", n * 2, None))

    def test_stats_for_agents(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        s = toolpath.stats_at(tp, 2)
        self.assertEqual((s["layer"], s["layers"], s["has_bridge"], s["has_overhang_wall"]), (3, 6, True, False))
        self.assertAlmostEqual(s["elapsed_s"] + s["remaining_s"], 600.0, places=3)
        self.assertEqual(s["evidence"], "simulated")


class RasterTest(Base):
    def test_frames_build_up_and_are_labelled(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        imgs = [img for _, img in simulate.frames(tp, count=5, size=(240, 180))]
        self.assertEqual(len(imgs), 5)
        ink = [int((np.asarray(i.convert("L")) > 120).sum()) for i in imgs]
        self.assertGreater(ink[-1], ink[0])                               # more is drawn at the end than at the start
        png = simulate.png_at(tp, 3.0, size=(240, 180))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        only = simulate.image_at(tp, 6.0, size=(240, 180), only=["Bridge"])
        full = simulate.image_at(tp, 6.0, size=(240, 180))
        self.assertNotEqual(only.tobytes(), full.tobytes())

    def test_gif_respects_the_size_limit(self):
        tp = toolpath.from_gcode(self.gcode(), "bambu")
        info = simulate.save_gif(tp, self.dir / "sim.gif", count=8, size=(200, 150), max_bytes=4_000_000)
        self.assertTrue((self.dir / "sim.gif").exists())
        self.assertLessEqual(info["bytes"], 4_000_000)
        self.assertEqual(info["label"], "Simulated from the slicer's G-code. Not a print.")
        fr = simulate.save_frames(tp, self.dir / "frames", first=1, last=3, count=4, size=(200, 150))
        self.assertEqual(fr["frames"], 4)


class CostTest(Base):
    META = {"filament_g": 64.41, "time_s": 6122.0, "filament_mm": 21595.39}

    def test_no_price_is_never_invented(self):
        c = cost.estimate(self.META, {"filament_type": "PLA", "filament_cost": "0"}, {"prices": {}})
        self.assertIsNone(c["filament"]["cost"])
        self.assertIn("Set a price per kg for PLA", c["filament"]["needs"])
        self.assertIsNone(c["electricity"]["cost"])
        self.assertIsNone(c["per_plate_as_sliced"]["cost"])
        self.assertEqual(c["per_plate_as_sliced"]["not_counted"], ["filament", "electricity", "machine time"])

    def test_price_sources_and_maths(self):
        s = {"filament_type": "PLA", "filament_cost": "20"}
        c = cost.estimate(self.META, s, {"prices": {}})
        self.assertEqual(c["filament"]["price_source"], "the slicer's filament preset (filament_cost)")
        self.assertAlmostEqual(c["filament"]["cost"], 64.41 / 1000 * 20, places=4)
        c = cost.estimate(self.META, s, {"prices": {"PLA": 28.0}, "watts": 90.0, "kwh_price": 0.30, "machine_rate_per_h": 1.5})
        self.assertEqual(c["filament"]["price_source"], "your price for PLA")
        self.assertAlmostEqual(c["filament"]["cost"], 1.8035, places=4)
        self.assertAlmostEqual(c["electricity"]["kwh"], 0.09 * 6122 / 3600, places=4)
        self.assertAlmostEqual(c["electricity"]["cost"], 0.09 * 6122 / 3600 * 0.30, places=4)
        self.assertAlmostEqual(c["machine"]["cost"], 6122 / 3600 * 1.5, places=4)
        total = c["filament"]["cost"] + c["electricity"]["cost"] + c["machine"]["cost"]
        self.assertAlmostEqual(c["per_plate_as_sliced"]["cost"], total, places=3)
        self.assertEqual(c["filament"]["evidence"], ["simulated", "specified"])
        c = cost.estimate(self.META, s, {"prices": {"PLA": 28.0}}, copies=4, overrides={"price_per_kg": 10.0})
        self.assertAlmostEqual(c["filament"]["cost"], 0.6441, places=4)
        self.assertAlmostEqual(c["per_plate_of_copies"]["cost"], 4 * 0.6441, places=3)
        self.assertEqual(c["per_plate_of_copies"]["evidence"], "estimated")

    def test_prefs_file(self):
        cfg = {"data": {"dir": str(self.dir)}}
        self.assertEqual(cost.load_prefs(cfg)["prices"], {})
        cost.save_prefs(cfg, {"price_per_kg": 24.5, "filament_type": "PETG", "watts": 95, "currency": "EUR"})
        p = cost.load_prefs(cfg)
        self.assertEqual((p["prices"], p["watts"], p["currency"], p["kwh_price"]), ({"PETG": 24.5}, 95.0, "EUR", None))
        cost.save_prefs(cfg, {"price_per_kg": None, "filament_type": "PETG", "watts": ""})
        p = cost.load_prefs(cfg)
        self.assertEqual((p["prices"], p["watts"]), ({}, None))
        with self.assertRaises(ValueError):
            cost.save_prefs(cfg, {"kwh_price": -1})
        with self.assertRaises(ValueError):
            cost.save_prefs(cfg, {"price_per_kg": 20})                    # no filament type to attach it to

    def test_material_comparison_from_installed_presets(self):
        root = self.dir / "conf" / "system" / "BBL" / "filament"
        root.mkdir(parents=True)
        def preset(name, **kw):
            (root / f"{name}.json").write_text(json.dumps({"name": name, **kw}), encoding="utf-8")
        preset("Generic PLA @base", filament_type=["PLA"], filament_density=["1.24"], filament_cost=["20"])
        preset("Generic PLA @P", inherits="Generic PLA @base", instantiation="true", compatible_printers=["Printer P"])
        preset("Generic PETG @P", filament_type=["PETG"], filament_density=["1.27"], filament_cost=["0"],
               instantiation="true", compatible_printers=["Printer P"])
        preset("Support W @P", filament_type=["PLA-S"], filament_density=["1.3"], filament_is_support=["1"],
               instantiation="true", compatible_printers=["Printer P"])
        preset("Generic ABS @Q", filament_type=["ABS"], filament_density=["1.05"], instantiation="true", compatible_printers=["Printer Q"])
        info = {"kind": "bambu", "config_dir": str(self.dir / "conf"), "presets": {"machine": {"name": "Printer P"}}}
        mats = cost.installed_filaments(info)["materials"]
        self.assertEqual([m["type"] for m in mats], ["PLA", "PETG"])        # not the support, not the other printer's ABS
        self.assertEqual(mats[1]["preset_price_per_kg"], None)             # a zero cost in a preset is not a price
        vol = cost.filament_volume_cm3(21595.39, 1.75)
        self.assertAlmostEqual(vol, 51.94, places=1)
        rows = cost.compare_materials(vol, mats, {"prices": {"PETG": 30.0}}, "PLA", 64.41)
        self.assertEqual((rows[0]["current"], rows[0]["evidence"], rows[0]["grams"]), (True, "simulated", 64.41))
        self.assertAlmostEqual(rows[1]["grams"], vol * 1.27, places=1)
        self.assertEqual((rows[1]["price_source"], rows[1]["evidence"]), ("your price", "estimated"))
        self.assertAlmostEqual(rows[1]["cost"], rows[1]["grams"] / 1000 * 30, places=3)
        self.assertIn("re-slice to confirm", cost.MATERIALS_NOTE)
        self.assertEqual(cost.installed_filaments({"kind": "prusa"})["materials"], [])


class PackingTest(unittest.TestCase):
    def check(self, r):
        """Every placed part is on the bed, inside the margin, and no two are closer than the spacing."""
        bw, bh = r["bed_mm"]
        m, s = r["margin_mm"], r["spacing_mm"]
        for a in r["placed"]:
            self.assertGreaterEqual(a["x"], m - 1e-6)
            self.assertGreaterEqual(a["y"], m - 1e-6)
            self.assertLessEqual(a["x"] + a["w"], bw - m + 1e-6)
            self.assertLessEqual(a["y"] + a["h"], bh - m + 1e-6)
        for i, a in enumerate(r["placed"]):
            for b in r["placed"][i + 1:]:
                gap_x = max(b["x"] - (a["x"] + a["w"]), a["x"] - (b["x"] + b["w"]))
                gap_y = max(b["y"] - (a["y"] + a["h"]), a["y"] - (b["y"] + b["h"]))
                self.assertGreaterEqual(max(gap_x, gap_y), s - 1e-6)

    def test_copies_fit(self):
        r = packing.copies(30.6, 30.6, 4, (180, 180), 6, 2)
        self.assertTrue(r["fits"])
        self.assertEqual(len(r["placed"]), 4)
        self.check(r)
        self.assertEqual(r["max_copies"], 16)                             # 4 × 4 at a 36.6 mm pitch in 176 mm
        self.assertLessEqual(max(r["used_mm"]), 2 * 30.6 + 6 + 1e-6)       # a compact 2 × 2 block, not a row of four

    def test_copies_do_not_fit(self):
        r = packing.copies(85.7, 91.6, 4, (180, 180), 6, 2)                # two side by side need 177.4 of 176 mm
        self.assertFalse(r["fits"])
        self.assertEqual((len(r["placed"]), len(r["unplaced"]), r["max_copies"]), (1, 3, 1))
        self.assertTrue(packing.copies(85.7, 91.6, 4, (256, 256), 6, 2)["fits"])
        self.assertFalse(packing.copies(200, 10, 1, (180, 180))["fits"])   # longer than the bed either way

    def test_rotation_makes_room(self):
        # 100 × 40 parts on a 150 × 150 bed: three as rows, a fourth only fits turned... with turning allowed 4 fit
        with_turns = packing.copies(100, 40, 4, (150, 150), 5, 0)
        self.check(with_turns)
        without = packing.copies(100, 40, 4, (150, 150), 5, 0, rotate=False)
        self.assertEqual(len(without["placed"]), 3)
        self.assertGreaterEqual(len(with_turns["placed"]), len(without["placed"]))
        one = packing.copies(160, 60, 1, (70, 170), 5, 0)                  # fits only turned 90°
        self.assertTrue(one["fits"])
        self.assertTrue(one["placed"][0]["rotated"])
        self.assertEqual((one["placed"][0]["w"], one["placed"][0]["h"]), (60.0, 160.0))

    def test_mixed_parts(self):
        parts = [{"id": "box", "w": 64, "h": 51.4}, {"id": "lid", "w": 64, "h": 51.4}, {"id": "pin", "w": 8, "h": 40},
                 {"id": "tray", "w": 120, "h": 70}]
        r = packing.pack(parts, (180, 180), 6, 2)
        self.assertTrue(r["fits"])
        self.assertEqual({a["id"] for a in r["placed"]}, {"box", "lid", "pin", "tray"})
        self.check(r)
        self.assertEqual(r["evidence"], "computed")
        self.assertIn("one part per plate", r["note"])
        self.assertFalse(packing.pack(parts + [{"id": "slab", "w": 170, "h": 170}], (180, 180), 6, 2)["fits"])


if __name__ == "__main__":
    unittest.main()
