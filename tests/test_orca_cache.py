"""OrcaSlicer's packed vendor presets (<vendor>.opc, OrcaSlicer 2.5+): the reader and the adapter using it.

The synthetic caches are written here by a small writer that follows the same layout as
OrcaSlicer's source (src/libslic3r/PresetCacheFormat.cpp at v2.5.1). The last class reads the
cache of a real installed OrcaSlicer and is skipped where there is none.
"""
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from form.adapters import orca, orca_cache as oc
from tests.test_slicers import base_cfg

V = oc.VECTOR


# ---- a writer for test caches -------------------------------------------------------------------

def _s(text: str) -> bytes:
    b = text.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _strs(items) -> bytes:
    return struct.pack("<Q", len(items)) + b"".join(_s(i) for i in items)


def _val(typ: int, v, enum_index) -> bytes:
    """Encode one option value. Vectors are Python lists; float-or-percent is (value, is_percent)."""
    if typ in (oc.FLOAT, oc.PERCENT):
        return struct.pack("<d", v)
    if typ == oc.INT:
        return struct.pack("<i", v)
    if typ == oc.STRING:
        return _s(v)
    if typ == oc.FLOAT_OR_PERCENT:
        return struct.pack("<dB", v[0], v[1])
    if typ == oc.POINT:
        return struct.pack("<2d", *v)
    if typ == oc.POINT3:
        return struct.pack("<3d", *v)
    if typ == oc.BOOL:
        return struct.pack("<B", v)
    if typ in (oc.FLOAT + V, oc.PERCENT + V):
        return struct.pack(f"<Q{len(v)}d", len(v), *v)
    if typ == oc.INT + V:
        return struct.pack(f"<Q{len(v)}i", len(v), *v)
    if typ == oc.STRING + V:
        return _strs(v)
    if typ == oc.FLOAT_OR_PERCENT + V:
        return struct.pack("<Q", len(v)) + b"".join(struct.pack("<dB", a, b) for a, b in v)
    if typ == oc.POINT + V:
        return struct.pack("<Q", len(v)) + b"".join(struct.pack("<2d", *p) for p in v)
    if typ == oc.BOOL + V:
        return struct.pack(f"<Q{len(v)}B", len(v), *v)
    if typ == oc.POINTS_GROUPS:
        return struct.pack("<Q", len(v)) + b"".join(_val(oc.POINT + V, g, enum_index) for g in v)
    if typ == oc.INTS_GROUPS:
        return struct.pack("<Q", len(v)) + b"".join(_val(oc.INT + V, g, enum_index) for g in v)
    if typ in (oc.ENUM, oc.ENUM + V):
        items = [v] if typ == oc.ENUM else v
        out = struct.pack("<I", len(items))
        for item in items:
            if isinstance(item, int):           # a value the writer could not name
                out += struct.pack("<Hi", 0, item)
            else:
                out += struct.pack("<H", enum_index[item])
        return out
    raise AssertionError(typ)


def build_body(vendor="Test", version="1.2.3", types=None, presets=None, stamp=oc.FORMAT_VERSION, models=("Cube One",)):
    """types: {key: option type}; presets: {kind: [dict(name=, config={key: raw value}, inherits=, includes=)]}."""
    types, presets = types or {}, presets or {}
    keys = list(types)
    enums = [""]
    for plist in presets.values():
        for p in plist:
            for k, v in p.get("config", {}).items():
                if types[k] in (oc.ENUM, oc.ENUM + V):
                    for item in ([v] if types[k] == oc.ENUM else v):
                        if isinstance(item, str) and item not in enums:
                            enums.append(item)
    enum_index = {n: i for i, n in enumerate(enums)}
    b = struct.pack("<I", stamp) + _s(vendor) + _s(version)
    b += _strs(keys) + struct.pack(f"<Q{len(keys)}H", len(keys), *[types[k] for k in keys]) + _strs(enums)
    # map<string, VendorProfile>: one vendor with its printer models
    b += struct.pack("<Q", 1) + _s(vendor)
    b += _s(vendor) + _s(vendor) + _s(version) + _s("") + _s("")
    b += struct.pack("<Q", len(models))
    for m in models:
        b += _s(m) + _s(m) + _s("M1") + struct.pack("<B", 0) + _s("fam")
        b += _strs(["0.4"]) + _strs(["Test PLA"]) + _strs([]) + b"".join(_s("") for _ in range(9))
    b += _strs(["Test PLA"]) + _strs([])
    for kind in oc.KINDS:
        plist = presets.get(kind, [])
        b += struct.pack("<I", len(plist))
        for p in plist:
            cfg = p.get("config", {})
            b += _s(p["name"]) + _s(f"{kind}/{p['name']}.json") + struct.pack("<I", len(cfg))
            for k, v in cfg.items():
                b += struct.pack("<H", keys.index(k)) + _val(types[k], v, enum_index)
            b += _s(p.get("inherits", "")) + _strs(p.get("includes", [])) + _s(p.get("description", ""))
            b += _s(p.get("instantiation", "true")) + _s(p.get("setting_id", "")) + _s(p.get("filament_id", ""))
            b += _strs(p.get("renamed_from", []))
    return b + struct.pack("<Q", 0)


def frame(body: bytes, version=oc.FORMAT_VERSION, crc=None, size=None) -> bytes:
    crc = zlib.crc32(body) & 0xFFFFFFFF if crc is None else crc
    return oc.HEADER.pack(oc.MAGIC, version, len(body) if size is None else size, crc) + body


TYPES = {
    "layer_height": oc.FLOAT, "wall_loops": oc.INT, "machine_start_gcode": oc.STRING,
    "sparse_infill_density": oc.PERCENT, "line_width": oc.FLOAT_OR_PERCENT, "best_object_pos": oc.POINT,
    "anchor": oc.POINT3, "enable_support": oc.BOOL, "nozzle_diameter": oc.FLOAT + V,
    "nozzle_temperature": oc.INT + V, "filament_type": oc.STRING + V, "fan_min_speed": oc.PERCENT + V,
    "retract_lift": oc.FLOAT_OR_PERCENT + V, "printable_area": oc.POINT + V, "wipe": oc.BOOL + V,
    "exclude_areas": oc.POINTS_GROUPS, "groups": oc.INTS_GROUPS, "gcode_flavor": oc.ENUM,
    "z_hop_types": oc.ENUM + V, "printable_height": oc.FLOAT, "filament_density": oc.FLOAT + V,
    "compatible_printers": oc.STRING + V, "machine_end_gcode": oc.STRING,
}
NAN = float("nan")
PRESETS = {
    "process": [
        {"name": "fdm_process_common", "instantiation": "false",
         "config": {"layer_height": 0.2, "wall_loops": 2, "sparse_infill_density": 15.0, "enable_support": 0,
                    "line_width": (0.42, 0)}},
        {"name": "0.16mm Fine @Cube", "inherits": "fdm_process_common", "setting_id": "GP1",
         "config": {"layer_height": 0.16, "line_width": (105.0, 1), "compatible_printers": ["Cube One 0.4 nozzle"]}},
    ],
    "filament": [
        {"name": "Test PLA", "filament_id": "GFL99",
         "config": {"filament_type": ["PLA"], "filament_density": [1.24], "nozzle_temperature": [220, oc.INT_NIL],
                    "fan_min_speed": [60.0, NAN], "retract_lift": [(0.4, 0), (50.0, 1), (NAN, 0)],
                    "wipe": [1, 0, oc.BOOL_NIL], "z_hop_types": ["Spiral Lift", 7, oc.INT_NIL]}},
    ],
    "machine": [
        {"name": "fdm_machine_common", "instantiation": "false",
         "config": {"gcode_flavor": "marlin", "printable_height": 250.0, "machine_start_gcode": "G28\nG1 Z5",
                    "machine_end_gcode": "M84"}},
        {"name": "Cube template end", "instantiation": "false", "config": {"machine_end_gcode": "; template end\nM104 S0"}},
        {"name": "Cube One 0.4 nozzle", "inherits": "fdm_machine_common", "includes": ["Cube template end"],
         "config": {"nozzle_diameter": [0.4], "printable_area": [(0, 0), (180, 0), (180, 180), (0, 180)],
                    "printable_height": 180.0, "best_object_pos": (0.7, 0.5), "anchor": (1, 2.5, -3),
                    "exclude_areas": [[(0, 0), (18, 0)], []], "groups": [[1, 2], [3]]}},
    ],
}


def synthetic() -> bytes:
    return frame(build_body(types=TYPES, presets=PRESETS))


class ReadsCache(unittest.TestCase):
    def test_round_trip_of_every_option_type(self):
        c = oc.parse(synthetic())
        self.assertEqual((c.vendor, c.version, c.format_version, c.parse_errors), ("Test", "1.2.3", 2, 0))
        self.assertEqual({k: list(v) for k, v in c.presets.items()},
                         {k: [p["name"] for p in PRESETS[k]] for k in oc.KINDS})
        self.assertEqual(c.models[0]["name"], "Cube One")
        self.assertEqual(c.models[0]["variants"], ["0.4"])
        m = c.presets["machine"]["Cube One 0.4 nozzle"]
        self.assertEqual((m.inherits, m.includes, m.sub_path), ("fdm_machine_common", ["Cube template end"],
                                                               "machine/Cube One 0.4 nozzle.json"))
        self.assertEqual(m.config, {
            "nozzle_diameter": ["0.4"], "printable_area": ["0x0", "180x0", "180x180", "0x180"],
            "printable_height": "180", "best_object_pos": "0.7,0.5", "anchor": "1,2.5,-3",
            "exclude_areas": ["0x0,18x0", ""], "groups": ["1,2", "3"]})
        base = c.presets["machine"]["fdm_machine_common"].config
        self.assertEqual(base["gcode_flavor"], "marlin")
        self.assertEqual(base["machine_start_gcode"], "G28\nG1 Z5")          # verbatim, as the JSON has it
        p = c.presets["process"]
        self.assertEqual(p["fdm_process_common"].config, {"layer_height": "0.2", "wall_loops": "2",
                                                          "sparse_infill_density": "15%", "enable_support": "0",
                                                          "line_width": "0.42"})
        self.assertEqual(p["0.16mm Fine @Cube"].config["line_width"], "105%")
        self.assertEqual(p["0.16mm Fine @Cube"].setting_id, "GP1")
        f = c.presets["filament"]["Test PLA"]
        self.assertEqual(f.filament_id, "GFL99")
        self.assertEqual(f.config, {
            "filament_type": ["PLA"], "filament_density": ["1.24"], "nozzle_temperature": ["220", "nil"],
            "fan_min_speed": ["60%", "nil"], "retract_lift": ["0.4", "50%", "nil"], "wipe": ["1", "0", "nil"],
            "z_hop_types": ["Spiral Lift", "7", "nil"]})

    def test_preset_as_json(self):
        j = oc.parse(synthetic()).presets["machine"]["Cube One 0.4 nozzle"].to_json()
        self.assertEqual((j["type"], j["name"], j["inherits"], j["from"], j["instantiation"]),
                         ("machine", "Cube One 0.4 nozzle", "fdm_machine_common", "system", "true"))
        self.assertEqual(j["include"], ["Cube template end"])
        self.assertEqual(j["nozzle_diameter"], ["0.4"])
        json.dumps(j)

    def test_numbers_print_as_the_slicer_prints_them(self):
        for v, text in ((0.4, "0.4"), (180.0, "180"), (0.0, "0"), (1.24, "1.24"), (0.1 + 0.2, "0.3"),
                        (1234567.0, "1.23457e+06"), (-2.5, "-2.5"), (0.00001, "1e-05")):
            self.assertEqual(oc.num(v), text)

    def test_rejects_wrong_magic_and_short_files(self):
        data = synthetic()
        for bad in (b"", data[:10], b"PK\x03\x04" + data[4:], b"{" + data[1:]):
            with self.assertRaises(oc.CacheError) as e:
                oc.parse(bad)
            self.assertNotIsInstance(e.exception, oc.CacheTooNew)
            self.assertIn("Not an OrcaSlicer preset cache", str(e.exception))

    def test_newer_format_is_named_not_guessed(self):
        body = build_body(types=TYPES, presets=PRESETS)
        with self.assertRaises(oc.CacheTooNew) as e:
            oc.parse(frame(body, version=3))
        self.assertIn("format version 3", str(e.exception))
        self.assertIn("newer", str(e.exception))
        with self.assertRaises(oc.CacheTooNew) as e:
            oc.parse(frame(body, version=1))
        self.assertIn("older", str(e.exception))
        with self.assertRaises(oc.CacheTooNew):                 # header says 2, the body's own stamp does not
            oc.parse(frame(build_body(types=TYPES, presets=PRESETS, stamp=3)))

    def test_rejects_bad_crc_and_wrong_size(self):
        body = build_body(types=TYPES, presets=PRESETS)
        flipped = bytearray(frame(body))
        flipped[200] ^= 0x01
        with self.assertRaises(oc.CacheError) as e:
            oc.parse(bytes(flipped))
        self.assertIn("CRC", str(e.exception))
        with self.assertRaises(oc.CacheError) as e:
            oc.parse(frame(body)[:-7])
        self.assertIn("truncated", str(e.exception))
        with self.assertRaises(oc.CacheError):
            oc.parse(frame(body) + b"\0")
        with self.assertRaises(oc.CacheError):
            oc.parse(frame(body, size=2 ** 60))
        with self.assertRaises(oc.CacheError):
            oc.parse(frame(b""))

    def test_body_cut_anywhere_is_an_error_never_a_crash(self):
        """A body that ends early but carries a matching CRC (a writer bug, or an attack)."""
        body = build_body(types=TYPES, presets=PRESETS)
        for cut in list(range(0, 80)) + list(range(80, len(body), 37)):
            with self.assertRaises(oc.CacheError, msg=f"cut at {cut}"):
                oc.parse(frame(body[:cut]))
        with self.assertRaises(oc.CacheError):
            oc.parse(frame(body + b"\0\0"))                     # bytes left over

    def test_lengths_larger_than_the_file_are_refused_before_allocating(self):
        head = struct.pack("<I", 2) + _s("Test") + _s("1.0.0")
        for tail in (struct.pack("<Q", 2 ** 62),                               # key count
                     struct.pack("<Q", 1) + struct.pack("<Q", 2 ** 40) + b"x",  # one key, absurd length
                     ):
            with self.assertRaises(oc.CacheError) as e:
                oc.parse(frame(head + tail))
            self.assertIn("larger than the file", str(e.exception))
        with self.assertRaises(oc.CacheError):                  # vendor name longer than a stamp may be
            oc.parse(frame(struct.pack("<I", 2) + _s("V" * 5000) + _s("1.0.0") + b"\0" * 64))

    def test_bad_dictionary_and_indices(self):
        body = build_body(types={"mystery": 12}, presets={"process": [{"name": "p", "config": {}}]})
        self.assertEqual(oc.parse(frame(body)).presets["process"]["p"].config, {})     # unused: harmless
        raw = struct.pack("<I", 2) + _s("T") + _s("1") + _strs(["a"]) + struct.pack("<QH", 1, 12) + _strs([""])
        raw += struct.pack("<Q", 0)                                                     # no vendor profiles
        entry = _s("p") + _s("") + struct.pack("<IH", 1, 0)
        with self.assertRaises(oc.CacheError) as e:                                     # a value of unknown type
            oc.parse(frame(raw + struct.pack("<I", 1) + entry + b"\0" * 80))
        self.assertIn("option type 12", str(e.exception))
        entry = _s("p") + _s("") + struct.pack("<IH", 1, 9)
        with self.assertRaises(oc.CacheError) as e:                                     # index past the dictionary
            oc.parse(frame(raw + struct.pack("<I", 1) + entry + b"\0" * 80))
        self.assertIn("past the end", str(e.exception))
        no_slot = struct.pack("<I", 2) + _s("T") + _s("1") + _strs([]) + struct.pack("<Q", 0) + _strs([])
        with self.assertRaises(oc.CacheError):
            oc.parse(frame(no_slot + b"\0" * 40))

    def test_find_skips_damaged_caches_and_reports_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Broken.opc").write_bytes(frame(build_body(types=TYPES, presets=PRESETS), crc=1))
            (d / "Newer.opc").write_bytes(frame(build_body(types=TYPES, presets=PRESETS), version=9))
            (d / "Test.opc").write_bytes(synthetic())
            preset, path, problems = oc.find([d / "missing", d], "filament", "Test PLA")
            self.assertEqual(preset.name, "Test PLA")
            self.assertEqual(len(problems), 2)
            self.assertTrue(any("format version 9" in p for p in problems), problems)
            self.assertEqual(oc.find([d], "machine", "Test PLA")[0], None)     # right name, wrong kind
            self.assertEqual(oc.find([d], "filament", "Nope"), (None, None, []))
            with self.assertRaises(oc.CacheTooNew):
                oc.read(d / "Newer.opc")
            self.assertIs(oc.read(d / "Test.opc"), oc.read(d / "Test.opc"))    # decoded once per file version


class AdapterUsesCache(unittest.TestCase):
    """The OrcaSlicer adapter with no system JSON at all, only a packed vendor cache."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "system").mkdir()
        (self.dir / "system" / "Test.opc").write_bytes(synthetic())

    def conf(self, data):
        (self.dir / "OrcaSlicer.conf").write_text(json.dumps(data) + "\n# MD5 checksum 0\n", encoding="utf-8")

    def cfg(self, **presets):
        return base_cfg(orca={"app": sys.executable, "config_dir": str(self.dir), **presets})

    def test_pinned_presets_flatten_through_the_cache(self):
        r = orca.resolve(self.cfg(machine="Cube One 0.4 nozzle", process="0.16mm Fine @Cube", filament="Test PLA"))
        self.assertTrue(r["available"], r["reason"])
        m = r["presets"]["machine"]["data"]
        self.assertEqual(m["gcode_flavor"], "marlin")                           # from the parent
        self.assertEqual(m["machine_start_gcode"], "G28\nG1 Z5")
        self.assertEqual(m["machine_end_gcode"], "; template end\nM104 S0")     # the include beats the parent
        self.assertEqual(m["printable_height"], "180")                          # the preset beats both
        self.assertEqual((m["name"], m["from"], m["printer_settings_id"]), ("Cube One 0.4 nozzle", "system",
                                                                            "Cube One 0.4 nozzle"))
        self.assertNotIn("inherits", m)
        self.assertNotIn("include", m)
        self.assertEqual(m["instantiation"], "true")                            # not the template's "false"
        p = r["presets"]["process"]["data"]
        self.assertEqual((p["layer_height"], p["wall_loops"], p["line_width"]), ("0.16", "2", "105%"))
        self.assertEqual(r["envelope_mm"], [180.0, 180.0, 180.0])
        self.assertEqual((r["nozzle_mm"], r["layer_height_mm"]), (0.4, 0.16))
        self.assertEqual(r["summary"]["filament_type"], "PLA")
        json.dumps(r["presets"])                                                # what the CLI is handed

    def test_current_selection_comes_from_orca_presets(self):
        self.conf({"presets": {"filaments": None, "machine": "Cube One 0.4 nozzle"},
                   "orca_presets": [{"machine": "Other", "process": "x", "filament": "y"},
                                    {"machine": "Cube One 0.4 nozzle", "process": "0.16mm Fine @Cube",
                                     "filament": "Test PLA"}]})
        r = orca.resolve(self.cfg())
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual({k: v["name"] for k, v in r["presets"].items()},
                         {"machine": "Cube One 0.4 nozzle", "process": "0.16mm Fine @Cube", "filament": "Test PLA"})
        self.assertEqual(set(r["source"].values()), {"OrcaSlicer current selection"})

    def test_incomplete_selection_says_what_is_missing(self):
        self.conf({"presets": {"filaments": None, "machine": "Cube One 0.4 nozzle"}})
        r = orca.resolve(self.cfg())
        self.assertFalse(r["available"])
        self.assertIn("“Cube One 0.4 nozzle” selected but no process preset saved for it", r["reason"])
        self.assertIn("[slicer.orca].process", r["reason"])
        (self.dir / "OrcaSlicer.conf").unlink()
        r = orca.resolve(self.cfg())
        self.assertIn("no saved selection yet", r["reason"])
        self.assertIn("[slicer.orca].machine", r["reason"])

    def test_user_preset_inherits_from_a_cached_system_preset(self):
        user = self.dir / "user" / "default" / "process"
        user.mkdir(parents=True)
        (user / "My fine.json").write_text(json.dumps({
            "name": "My fine", "inherits": "0.16mm Fine @Cube", "from": "User", "wall_loops": "4"}), encoding="utf-8")
        r = orca.resolve(self.cfg(machine="Cube One 0.4 nozzle", process="My fine", filament="Test PLA"))
        self.assertTrue(r["available"], r["reason"])
        p = r["presets"]["process"]["data"]
        self.assertEqual((p["wall_loops"], p["layer_height"], p["sparse_infill_density"]), ("4", "0.16", "15%"))

    def test_missing_preset_names_the_caches_that_were_searched(self):
        r = orca.resolve(self.cfg(machine="No such printer", process="0.16mm Fine @Cube", filament="Test PLA"))
        self.assertFalse(r["available"])
        self.assertIn("“No such printer” was not found", r["reason"])
        self.assertIn("*.opc", r["reason"])
        self.assertIn(str(self.dir / "system"), r["reason"])

    def test_parents_come_from_the_presets_own_vendor(self):
        """"fdm_process_common" exists in most vendors with different values. Another vendor's must
        never be used, whatever the file order; the filament library is the one shared source."""
        other = {"process": [{"name": "fdm_process_common", "config": {"layer_height": 0.3, "wall_loops": 9}}],
                 "machine": [{"name": "fdm_machine_common", "config": {"gcode_flavor": "klipper",
                                                                       "printable_height": 999.0}}],
                 "filament": [{"name": "fdm_filament_pla", "config": {"filament_density": [9.99]}}]}
        (self.dir / "system" / "Aaa.opc").write_bytes(frame(build_body(vendor="Aaa", types=TYPES, presets=other)))
        library = {"filament": [{"name": "fdm_filament_pla", "instantiation": "false",
                                 "config": {"filament_density": [1.24], "filament_type": ["PLA"]}}]}
        (self.dir / "system" / "OrcaFilamentLibrary.opc").write_bytes(
            frame(build_body(vendor="OrcaFilamentLibrary", types=TYPES, presets=library)))
        mine = {k: list(v) for k, v in PRESETS.items()}
        mine["filament"] = [{"name": "Cube PLA", "inherits": "fdm_filament_pla", "config": {"nozzle_temperature": [215]}}]
        (self.dir / "system" / "Test.opc").write_bytes(frame(build_body(types=TYPES, presets=mine)))
        r = orca.resolve(self.cfg(machine="Cube One 0.4 nozzle", process="0.16mm Fine @Cube", filament="Cube PLA"))
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual(r["presets"]["process"]["data"]["wall_loops"], "2")
        self.assertEqual(r["presets"]["machine"]["data"]["gcode_flavor"], "marlin")
        self.assertEqual(r["presets"]["filament"]["data"]["filament_density"], ["1.24"])       # from the library
        # a parent that only another vendor has is an error, not a silent borrow
        mine["filament"] = [{"name": "Cube PLA", "inherits": "fdm_filament_pla", "config": {}}]
        (self.dir / "system" / "OrcaFilamentLibrary.opc").unlink()
        r = orca.resolve(self.cfg(machine="Cube One 0.4 nozzle", process="0.16mm Fine @Cube", filament="Cube PLA"))
        self.assertFalse(r["available"])
        self.assertIn("“fdm_filament_pla” was not found. It is a parent of a preset in", r["reason"])

    def test_a_named_preset_prefers_the_printers_vendor(self):
        clash = {"process": [{"name": "0.16mm Fine @Cube", "config": {"layer_height": 0.99}}]}
        (self.dir / "system" / "Aaa.opc").write_bytes(frame(build_body(vendor="Aaa", types=TYPES, presets=clash)))
        r = orca.resolve(self.cfg(machine="Cube One 0.4 nozzle", process="0.16mm Fine @Cube", filament="Test PLA"))
        self.assertTrue(r["available"], r["reason"])
        self.assertEqual(r["layer_height_mm"], 0.16)

    def test_too_new_cache_is_reported_in_the_reason(self):
        (self.dir / "system" / "Test.opc").write_bytes(frame(build_body(types=TYPES, presets=PRESETS), version=3))
        r = orca.resolve(self.cfg(machine="Cube One 0.4 nozzle", process="0.16mm Fine @Cube", filament="Test PLA"))
        self.assertFalse(r["available"])
        self.assertIn("format version 3", r["reason"])

    def test_shipped_profiles_are_found_beside_the_program(self):
        for layout, exe in (("OrcaSlicer.app/Contents/Resources/profiles", "OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
                            ("win/resources/profiles", "win/orca-slicer.exe"),
                            ("opt/resources/profiles", "opt/bin/orca-slicer"),
                            ("usr/share/OrcaSlicer/profiles", "usr/bin/orca-slicer")):
            profiles, app = self.dir / "apps" / layout, self.dir / "apps" / exe
            profiles.mkdir(parents=True)
            app.parent.mkdir(parents=True, exist_ok=True)
            app.write_bytes(b"")
            found = orca.profile_dirs(app)
            self.assertEqual(len(found), 1, layout)
            self.assertTrue(found[0].samefile(profiles), layout)
        both = orca.cache_dirs(app, self.dir)
        self.assertEqual(len(both), 2)
        self.assertTrue(both[0].samefile(self.dir / "system") and both[1].samefile(profiles))
        self.assertEqual(len(orca.cache_dirs(app, self.dir / "never-opened")), 1)


REAL_DIRS = [Path("~/Library/Application Support/OrcaSlicer/system").expanduser(),
             Path("/Applications/OrcaSlicer.app/Contents/Resources/profiles"),
             Path("~/.config/OrcaSlicer/system").expanduser(),
             Path(r"C:\Program Files\OrcaSlicer\resources\profiles")]
REAL = next((d / "BBL.opc" for d in REAL_DIRS if (d / "BBL.opc").is_file()), None)


@unittest.skipUnless(REAL, "no installed OrcaSlicer with a BBL.opc vendor cache")
class RealInstalledCache(unittest.TestCase):
    def test_a1_mini_decodes_sanely(self):
        try:
            c = oc.read(REAL)
        except oc.CacheTooNew as e:
            self.skipTest(str(e))
        self.assertEqual(c.vendor, "BBL")
        self.assertRegex(c.version, r"^\d+\.\d+\.\d+")
        self.assertIn("Bambu Lab A1 mini", [m["name"] for m in c.models])
        for kind in oc.KINDS:
            self.assertGreater(len(c.presets[kind]), 20, kind)
        m = c.presets["machine"]["Bambu Lab A1 mini 0.4 nozzle"]
        self.assertEqual(m.config["nozzle_diameter"], ["0.4"])
        self.assertEqual(m.config["printable_area"], ["0x0", "180x0", "180x180", "0x180"])
        self.assertEqual(m.config["printable_height"], "180")
        self.assertTrue(m.inherits)
        self.assertIn("0.20mm Standard @BBL A1M", c.presets["process"])
        self.assertIn("Generic PLA @BBL A1M", c.presets["filament"])
        # every parent and include named by a machine preset exists as a machine preset in this cache
        for p in c.presets["machine"].values():
            for parent in [p.inherits, *p.includes]:
                if parent:
                    self.assertIn(parent, c.presets["machine"], p.name)


if __name__ == "__main__":
    unittest.main()
