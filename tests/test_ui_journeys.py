"""The desktop app, used the way a person uses it: every journey in tests/journeys/ runs in the real window with
real synthetic mouse and key events (form/app/uitest.py) and asserts outcomes in the engine.

Skipped when PySide6 or a display is missing, or with FORM_SKIP_UI=1. Each journey gets its own process, data
folder, window settings and a stand-in agent CLI; nothing here calls a model or the network.

    python -m unittest tests.test_ui_journeys                 # all of them (a few minutes)
    python -m unittest tests.test_ui_journeys.Journeys.test_design
    FORM_UI_SHOTS=.dev/uitest python -m unittest ...          # keep the screenshots
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
JOURNEYS = HERE / "journeys"


def _why_not() -> str:
    if os.environ.get("FORM_SKIP_UI") == "1":
        return "FORM_SKIP_UI=1"
    if importlib.util.find_spec("PySide6") is None:
        return "PySide6 is not installed"
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "no display"
    if os.environ.get("CI") and os.environ.get("FORM_UI_TESTS") != "1":
        return "CI without FORM_UI_TESTS=1"
    return ""


def run_journey(script: str, size: str = "1440x900", env_extra: dict | None = None, timeout: int = 900):
    """Run one journey file (or file::function) in its own app process. Returns (returncode, output)."""
    path = JOURNEYS / script.partition("::")[0]
    mode = "fresh"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATA ="):
            mode = line.split("=", 1)[1].strip().strip("\"'")
    with tempfile.TemporaryDirectory(prefix="form-ui-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        if mode != "empty":          # setup already seen: the journey starts on Home, not on the first-run screen
            (data / ".form-setup.json").write_text(json.dumps({"ts": 1, "version": "test", "how": "done"}), encoding="utf-8")
        env = dict(os.environ, FORM_DATA=str(data), FORM_CONFIG=str(Path(tmp) / "studio.toml"), FORM_NO_UPDATE_CHECK="1",
                   FORM_UITEST_AGENT=str(HERE / "fixtures" / "fake_agent.py"), FORM_UITEST_TMP=tmp,
                   FORM_UITEST_OUT=os.environ.get("FORM_UI_SHOTS") or str(Path(tmp) / "shots"), FORM_REDUCED_MOTION="0")
        if os.environ.get("FORM_UI_STUDIO_TOML"):      # CI: a studio.toml that pins a slicer and presets for every journey
            (Path(tmp) / "studio.toml").write_text(Path(os.environ["FORM_UI_STUDIO_TOML"]).read_text(encoding="utf-8"), encoding="utf-8")
        env.update(env_extra or {})
        r = subprocess.run([sys.executable, "-m", "form.app", "--uitest", str(JOURNEYS / script), "--size", size],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-6000:]


@unittest.skipIf(_why_not(), _why_not())
class Journeys(unittest.TestCase):
    def journey(self, script, **kw):
        rc, out = run_journey(script, **kw)
        self.assertEqual(rc, 0, f"\n{script} failed:\n{out}")

    def test_first_run(self):
        self.journey("first_run.py")

    def test_design(self):
        self.journey("design.py")

    def test_viewport_tools(self):
        self.journey("tools.py")

    def test_fit_prove_release(self):
        self.journey("prove_release.py")

    def test_conversations(self):
        self.journey("chat.py")

    def test_home(self):
        self.journey("home.py")

    def test_sheets_palette_shortcuts(self):
        # installs and the upgrade are simulated, one item is reported missing so there is something to install,
        # and a newer release is pretended so the update sheet has something to offer
        self.journey("shell.py", env_extra={"FORM_INSTALL_FAKE": "0.6", "FORM_SETUP_PRETEND_MISSING": "openscad,parts",
                                            "FORM_FAKE_LATEST": "99.0.0"})

    def test_smallest_window(self):
        self.journey("sizes.py", size="1120x700")

    def test_large_window(self):
        self.journey("sizes.py", size="1728x1117")


if __name__ == "__main__":
    unittest.main()
