"""3MF as Bambu Studio, Orca Slicer and MakerWorld write it (production extension), read into named, placed parts.

Found in the audit: meshes in 3D/Objects/object_N.model (reached through p:path) were ignored by the old reader, so
every part of a Bambu file landed untransformed at the origin, flattened into one nameless soup.

Fixtures: tests/fixtures/3mf/*.3mf were written by Bambu Studio 2.9 and Orca Slicer from two boxes (a 20 mm cube and a
40 x 8 x 6 mm bar, arranged by the slicer); threemf_fixtures.bambu_style builds a three-object file with a modifier
volume, two plates and two filament colours."""
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("FORM_SKIP_UI", "1")

from form.recon import mesh  # noqa: E402

from threemf_fixtures import bambu_style, expected  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "3mf"
SIZES = {"cube.stl": (20.0, 20.0, 20.0), "bar.stl": (40.0, 8.0, 6.0)}


def slicer_bbox(path: Path, name: str):
    """Where the slicer put an object, read straight from the file without any 3MF reader: the build item's
    translation, the component's offset and the part's own extent (its mesh is centred on its origin)."""
    with zipfile.ZipFile(path) as z:
        root = z.read("3D/3dmodel.model").decode()
        settings = z.read("Metadata/model_settings.config").decode()
    oid = re.search(r'<object id="(\d+)"[^>]*>\s*<metadata key="name" value="' + re.escape(name), settings).group(1)
    t = re.search(r'<item objectid="' + oid + r'"[^>]*transform="([^"]+)"', root).group(1).split()
    tx, ty, tz = (float(v) for v in t[9:12])
    sx, sy, sz = SIZES[name]
    comp = re.search(r'<object id="' + oid + r'"[^>]*>\s*<components>\s*<component [^>]*transform="([^"]+)"', root)
    cx, cy, cz = (float(v) for v in comp.group(1).split()[9:12])   # the part's offset inside its object
    return [[tx + cx - sx / 2, ty + cy - sy / 2, tz + cz - sz / 2], [tx + cx + sx / 2, ty + cy + sy / 2, tz + cz + sz / 2]]


class SlicerFiles(unittest.TestCase):
    def test_bambu_studio_and_orca_files(self):
        for f in ("bambustudio-2.9-two-objects.3mf", "orcaslicer-two-objects.3mf"):
            with self.subTest(f):
                parts, info = mesh.read_parts(FIX / f)
                self.assertEqual([p.name for p in parts], ["cube.stl", "bar.stl"])
                self.assertEqual(info["format"], "3mf (millimeter)")
                for p in parts:
                    self.assertEqual(p.info["reader"], "lib3mf")
                    self.assertEqual(p.info["plate"], 1)
                    self.assertTrue(re.fullmatch(r"#[0-9A-F]{6}", p.info["colour"]))
                    got = p.T.reshape(-1, 3)
                    want = np.array(slicer_bbox(FIX / f, p.name))
                    np.testing.assert_allclose([got.min(0), got.max(0)], want, atol=1e-3)
                # the parts are apart, not stacked at the origin (what the old reader did)
                a, b = (p.T.reshape(-1, 3) for p in parts)
                self.assertTrue((a.min(0)[:2] > 1).all() and (b.min(0)[:2] > 1).all())

    def test_the_plain_reader_agrees(self):
        for f in sorted(FIX.glob("*.3mf")):
            with self.subTest(f.name), mock.patch.object(mesh, "_3mf_lib3mf", side_effect=ImportError("no lib3mf")):
                plain, _ = mesh.read_parts(f)
            lib, _ = mesh.read_parts(f)
            self.assertEqual([p.name for p in plain], [p.name for p in lib])
            self.assertEqual(plain[0].info["reader"], "xml")
            for x, y in zip(plain, lib):
                np.testing.assert_allclose(x.T, y.T, atol=1e-4)


class BambuStyle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = bambu_style(self.tmp / "multi.3mf")

    def check(self, parts):
        want = expected()
        self.assertEqual([p.name for p in parts], [w["name"] for w in want])
        for p, w in zip(parts, want):
            P = p.T.reshape(-1, 3)
            np.testing.assert_allclose([P.min(0), P.max(0)], w["bbox"], atol=1e-3)
            self.assertEqual(len(p.T), w["triangles"])          # the modifier volume is not geometry
            self.assertEqual((p.info["plate"], p.info["colour"]), (w["plate"], w["colour"]))

    def test_named_parts_in_place_with_plates_and_colours(self):
        parts, info = mesh.read_parts(self.f)
        self.check(parts)
        self.assertEqual([x["name"] for x in info["parts"]], ["Base plate", "Bracket", "Knob"])
        T, info2 = mesh.read_triangles(self.f)                  # the whole file, every part where it belongs
        self.assertEqual(len(T), 36)
        self.assertEqual(info2["triangles_in"], 36)

    def test_without_lib3mf(self):
        with mock.patch.object(mesh, "_3mf_lib3mf", side_effect=ImportError("no lib3mf")):
            parts, _ = mesh.read_parts(self.f)
        self.check(parts)

    def test_a_missing_object_file_is_said(self):
        bad = self.tmp / "bad.3mf"
        with zipfile.ZipFile(self.f) as z, zipfile.ZipFile(bad, "w") as out:
            for n in z.namelist():
                if n != "3D/Objects/object_1.model":
                    out.writestr(n, z.read(n))
        with self.assertRaises(ValueError) as e:
            mesh.read_parts(bad)
        self.assertIn("object_1.model", str(e.exception))


class OtherFormats(unittest.TestCase):
    def test_obj_objects_stay_apart_and_stl_is_one_part(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "two.obj").write_text("o left\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no right\nv 5 0 0\nv 6 0 0\nv 5 1 0\n"
                                     "v 6 1 0\nf 4 5 7 6\n")
        parts, info = mesh.read_parts(tmp / "two.obj")
        self.assertEqual([(p.name, len(p.T)) for p in parts], [("left", 1), ("right", 2)])
        self.assertEqual(len(info["parts"]), 2)
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
        F = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]])
        mesh.write_stl(tmp / "t.stl", V, F)
        parts, info = mesh.read_parts(tmp / "t.stl")
        self.assertEqual((len(parts), parts[0].name, info["triangles_in"]), (1, "t", 4))
        self.assertNotIn("parts", info)
        self.assertEqual(mesh.stl_triangle_count(tmp / "t.stl"), 4)


if __name__ == "__main__":
    unittest.main()
