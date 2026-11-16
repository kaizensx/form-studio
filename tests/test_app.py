"""The desktop app: things that can be checked without opening a window."""
import base64
import re
import unittest
from pathlib import Path

import numpy as np

QML = Path(__file__).resolve().parents[1] / "form" / "app" / "qml"

try:
    import PySide6  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


class AppFiles(unittest.TestCase):
    def test_every_registered_component_exists(self):
        for line in (QML / "Form" / "qmldir").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[-1].endswith(".qml"):
                self.assertTrue((QML / "Form" / parts[-1]).is_file(), parts[-1])

    def test_every_sheet_and_stage_file_exists(self):
        for host in ("SheetHost.qml", "Workspace.qml"):
            for name in re.findall(r'"(\w+\.qml)"', (QML / "Form" / host).read_text(encoding="utf-8")):
                self.assertTrue((QML / "Form" / name).is_file(), f"{host} loads {name}")

    def test_font_sizes_are_whole_pixels(self):
        for f in (QML / "Form").glob("*.qml"):
            for m in re.finditer(r"pixelSize:[^;\n}]*", f.read_text(encoding="utf-8")):
                self.assertNotRegex(m.group(0), r"\d\.\d", f"{f.name}: {m.group(0)}")

    def test_fonts_and_icon_ship(self):
        assets = QML.parent / "assets"
        for name in ("fonts/InstrumentSans.ttf", "fonts/GeistMono.ttf", "fonts/lucide.ttf", "icon.png", "icon.ico", "icon.icns"):
            self.assertTrue((assets / name).is_file(), name)

    def test_icon_names_used_are_defined(self):
        defined = set(re.findall(r'"(\w+)": "\\u', (QML / "Form" / "Icons.qml").read_text(encoding="utf-8")))
        for f in (QML / "Form").glob("*.qml"):
            for name in re.findall(r'\b(?:icon|name): "([a-z0-9_]+)"', f.read_text(encoding="utf-8")):
                if f.name != "Icons.qml":
                    self.assertIn(name, defined, f"{f.name} uses icon {name}")


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class Geometry(unittest.TestCase):
    def test_smooth_normals_point_out_of_a_flat_triangle(self):
        from form.app.geometry import smooth_normals
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        n = smooth_normals(pos, np.array([[0, 1, 2]], dtype=np.uint32))
        np.testing.assert_allclose(n, [[0, 0, 1]] * 3, atol=1e-6)

    def test_degenerate_input_does_not_divide_by_zero(self):
        from form.app.geometry import smooth_normals
        pos = np.zeros((3, 3), dtype=np.float32)
        n = smooth_normals(pos, np.array([[0, 1, 2]], dtype=np.uint32))
        self.assertTrue(np.isfinite(n).all())

    def test_b64_roundtrip(self):
        from form.app.geometry import _b64
        a = np.arange(6, dtype=np.float32)
        np.testing.assert_array_equal(_b64(base64.b64encode(a.tobytes()).decode(), np.float32), a)


if __name__ == "__main__":
    unittest.main()
