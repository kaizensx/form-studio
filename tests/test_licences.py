"""Licences ship with what they cover: the package metadata names every licence in the wheel, each licence file it
lists exists, and the app's spec carries the same files."""
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PackageLicences(unittest.TestCase):
    def setUp(self):
        self.project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")

    def test_expression_names_every_licence_in_the_package(self):
        parts = set(self.project["license"].split(" AND "))
        self.assertEqual(parts, {"MIT", "CC-BY-NC-4.0", "Apache-2.0", "OFL-1.1", "ISC"})

    def test_license_files_exist(self):
        files = self.project["license-files"]
        for must in ("LICENSE", "form/recon/cadfit/LICENSE", "form/recon/cadfit/PERMISSION.md",
                     "form/exemplars/LICENSE-CADEvolve"):
            self.assertIn(must, files)
        for pattern in files:
            self.assertTrue(list(ROOT.glob(pattern)), pattern)

    def test_the_app_ships_the_same_licence_files(self):
        self.assertIn('("LICENSE", "PERMISSION.md")', self.spec)            # CADFit's folder, in engine_src
        self.assertIn('"LICENSE-CADEvolve"', self.spec)

    def test_threejs_materials_ships_its_licence(self):
        self.assertIn('copy_metadata("threejs_materials")', self.spec)

    def test_notices_cover_the_installable_engines(self):
        from form import engines
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("threejs-materials", notices)
        self.assertIn(f"uv** {engines.UV_VERSION}", notices)
        for eid, spec in engines.SPECS.items():
            self.assertIn(spec["label"], notices, eid)
            for pin in spec["pins"]:
                name, version = pin.split("==")
                self.assertIn(version, notices, pin)

    def test_readme_names_the_shipped_libraries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        licence = readme[readme.index("## Licence"):]
        for name in ("bd_warehouse", "bd_materials", "threejs-materials", "py_gearworks", "CC BY-NC 4.0"):
            self.assertIn(name, licence)


if __name__ == "__main__":
    unittest.main()
