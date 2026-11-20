"""Files the app reads at run time as data must ship in the packaged app, not only as importable modules."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackagedData(unittest.TestCase):
    def test_exemplar_sources_ship_as_files(self):
        # design_examples reads each exemplar's source text; PyInstaller keeps .py files only as bytecode unless listed
        spec = (ROOT / "packaging" / "form.spec").read_text(encoding="utf-8")
        self.assertIn('"form/exemplars"', spec)
        from form import exemplars
        self.assertGreaterEqual(len(exemplars.catalogue()), 12)

    def test_chat_attachments_accept_meshes(self):
        talk = (ROOT / "form" / "app" / "qml" / "Form" / "Talk.qml").read_text(encoding="utf-8")
        for ext in ("*.stl", "*.3mf", "*.obj", "*.step"):
            self.assertIn(ext, talk)


if __name__ == "__main__":
    unittest.main()
