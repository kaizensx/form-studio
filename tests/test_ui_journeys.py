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


_SPEED: list[float] = []


def _speed() -> float:
    """How many times slower than the reference machine this one is (tests/machine.py), measured once; 1.0 when the
    kernel is not there to measure with."""
    if not _SPEED:
        try:
            sys.path.insert(0, str(HERE))
            import machine
            _SPEED.append(machine.speed())
        except Exception:                                # noqa: BLE001
            _SPEED.append(1.0)
        print(f"interface journeys: machine speed {_SPEED[0]:.2f}", flush=True)
    return _SPEED[0]


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
                   FORM_SECRETS=str(Path(tmp) / "secrets.json"),          # never the user's own agent keys
                   FORM_NO_AUTO_SETUP="1",                                 # first start never installs for real in a test
                   FORM_PROVIDERS_OFFLINE="1",                             # a test key is never sent to a real model provider
                   FORM_UITEST_OUT=os.environ.get("FORM_UI_SHOTS") or str(Path(tmp) / "shots"), FORM_REDUCED_MOTION="0",
                   FORM_REFINE="off")          # design refinement only in the journeys about it (env_extra FORM_REFINE="on")
        if os.environ.get("FORM_UI_STUDIO_TOML"):      # CI: a studio.toml that pins a slicer and presets for every journey
            (Path(tmp) / "studio.toml").write_text(Path(os.environ["FORM_UI_STUDIO_TOML"]).read_text(encoding="utf-8"), encoding="utf-8")
        env.update(env_extra or {})
        env.setdefault("FORM_UITEST_SLOW", f"{_speed():.2f}")      # the waits follow the machine (form/app/uitest.py)
        # the app's own watchdog ends a journey that hangs and prints every thread's stack; it goes first, so the
        # stacks are in the output
        env.setdefault("FORM_UITEST_WATCHDOG", str(max(60, timeout - 60)))
        sys.path.insert(0, str(ROOT))
        from form import fsutil
        try:
            r = subprocess.run([sys.executable, "-m", "form.app", "--uitest", str(JOURNEYS / script), "--size", size],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
            rc, out = r.returncode, r.stdout + r.stderr
        except subprocess.TimeoutExpired as e:

            def text(x):
                return x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
            rc, out = -1, text(e.stdout) + text(e.stderr) + f"\nThe journey did not end in {timeout} s and was stopped."
        fsutil.rmtree(data, 20)              # retried: on Windows a folder frees a moment after the last process in it ends
        return rc, out[-6000:]


@unittest.skipIf(_why_not(), _why_not())
class Journeys(unittest.TestCase):
    def journey(self, script, **kw):
        rc, out = run_journey(script, **kw)
        self.assertEqual(rc, 0, f"\n{script} failed:\n{out}")

    def test_first_run(self):
        self.journey("first_run.py")

    def test_sources(self):                 # Sources from the tool log, the plan card, the live line, the hand-edit note, a saved prompt
        self.journey("sources.py")

    def test_design(self):
        self.journey("design.py")

    def test_direction_i(self):             # four modes, the Overview, Fit as a study, the view cube, the legend strip
        self.journey("direction_i.py")

    def test_direction_i_light(self):       # the same on paper, in a 1280 x 800 window
        self.journey("direction_i.py", size="1280x800", env_extra={"FORM_APPEARANCE": "light"})

    def test_lightdesk(self):               # the room: panes never overlap, the bar and its keys, the cue and the program during a build
        self.journey("lightdesk.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_lightdesk_small(self):         # the smallest window: the same panes, still clear of each other
        self.journey("lightdesk.py", size="1120x700", env_extra={"FORM_APPEARANCE": "dark"})

    def test_lightdesk_light(self):         # the same on paper
        self.journey("lightdesk.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_viewport_tools(self):
        self.journey("tools.py")

    def test_viewport_stress(self):         # orbit, pan and zoom to extremes with panels toggling: never a black view
        self.journey("viewport_stress.py")

    def test_remodel(self):                 # a faceted solid drawn smooth; Rebuild as editable CAD starts the remodel brief
        self.journey("remodel.py")

    def test_stage_use(self):               # the first click folds the column; the bar prompt is written in; the caret; Refinement; the tab; the cue's glass; the part stays centred
        self.journey("stage_use.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_stage_use_small(self):         # the same in the smallest window, on paper
        self.journey("stage_use.py", size="1100x700", env_extra={"FORM_APPEARANCE": "light"})

    def test_stage_frame(self):             # a tall part (vase, hook, box with its lid open or pulled apart) stands whole in the free stage over the bar's suggestions
        self.journey("stage_frame.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_stage_frame_mid(self):         # the same in a 1280 x 800 window, on paper
        self.journey("stage_frame.py", size="1280x800", env_extra={"FORM_APPEARANCE": "light"})

    def test_stage_frame_small(self):       # and in the smallest window
        self.journey("stage_frame.py", size="1100x700", env_extra={"FORM_APPEARANCE": "light"})

    def test_designing_stage(self):         # while a design is made: the words in the middle of the free stage; the conversation glides to its column once it outgrows the panel; a long question with every reply in view
        self.journey("designing_stage.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_designing_stage_mid(self):
        self.journey("designing_stage.py", size="1280x800", env_extra={"FORM_APPEARANCE": "light"})

    def test_designing_stage_small(self):   # the smallest window, on paper
        self.journey("designing_stage.py", size="1100x700", env_extra={"FORM_APPEARANCE": "light"})

    def test_designing_stage_wide(self):    # a wide window: the block is on the stage's middle, not left of it
        self.journey("designing_stage.py", size="2000x1100", env_extra={"FORM_APPEARANCE": "dark"})

    def test_viewport_calm(self):           # orbit, zoom, rebuilds and slider drags never blink; a build grows in by feature
        self.journey("viewport_calm.py")

    def test_viewport_parts_calm(self):     # eight assembled parts: slider drags and orbits never blink; drafts keep the part nodes
        self.journey("viewport_parts_calm.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_viewport_light(self):          # every view, elevation and zoom keeps the part lit; orbit and zoom never flash
        self.journey("viewport_light.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_viewport_light_light(self):    # the same in the light appearance
        self.journey("viewport_light.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_build_stages(self):            # an agent's build is drawn stage by stage before it is saved, then the saved design
        self.journey("build_stages.py")

    def test_refine(self):                  # a design refined in the background: the panel, its changes, undo one, Settings
        self.journey("refine.py", env_extra={"FORM_APPEARANCE": "dark", "FORM_REFINE": "on"})

    def test_refine_light(self):            # the same in the light appearance
        self.journey("refine.py", env_extra={"FORM_APPEARANCE": "light", "FORM_REFINE": "on"})

    def test_game_asset(self):              # Make it for: Game asset; build in Blender, switch LODs, export for Unreal
        self.journey("game_asset.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_game_asset_light(self):        # the same in the light appearance
        self.journey("game_asset.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_isolation(self):              # another conversation never takes over; concepts in the feed; the printer on top
        self.journey("isolation.py")

    def test_bench(self):                  # the Bench: every study, route and document with its state; run, open, stale, palette
        self.journey("bench.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_bench_small_light(self):      # the same in the smallest window, on paper
        self.journey("bench.py", size="1100x700", env_extra={"FORM_APPEARANCE": "light"})

    def test_results(self):                # results drawn on the part: strength, manufacturability, CNC, flat pattern, motion, the sheet
        self.journey("results.py", env_extra={"FORM_APPEARANCE": "dark"}, timeout=1200)

    def test_results_small_light(self):    # the same in the smallest window, on paper
        self.journey("results.py", size="1100x700", env_extra={"FORM_APPEARANCE": "light"}, timeout=1200)

    def test_maker_tools(self):
        self.journey("maker_tools.py")

    def test_modelling(self):               # the Program by hand: roll back, suppress, rename, depends, moves; a fillet on a picked edge
        self.journey("modelling.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_modelling_light(self):         # the same on paper
        self.journey("modelling.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_modelling_small(self):         # the smallest window: Preview and Add stay in view, pinned at the pane's foot
        self.journey("modelling.py", size="1120x700", env_extra={"FORM_APPEARANCE": "dark"})

    def test_stack_topology(self):          # the tolerance loop and the topology run on the part, from real engine runs
        self.journey("stack_topology.py")

    def test_stage_idle(self):              # a still workspace draws nothing, active or not, in every mode; the caret alone blinks
        self.journey("stage_idle.py")

    def test_dock_modes(self):              # the dock by mode, the capsule in one place, the modes' keys, idle redraws
        self.journey("dock_modes.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_dock_modes_light(self):        # the same on paper, at 1280 x 800
        self.journey("dock_modes.py", size="1280x800", env_extra={"FORM_APPEARANCE": "light"})

    def test_dock_modes_small(self):        # 1100 x 700: the Design group still ends above the window's foot
        self.journey("dock_modes.py", size="1100x700", env_extra={"FORM_APPEARANCE": "dark"})

    def test_pro_frame(self):               # the labelled ribbon per mode, Hide remembered, the document tabs, the project rail
        self.journey("pro_frame.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_pro_frame_light(self):         # the same on paper, at 1280 x 800
        self.journey("pro_frame.py", size="1280x800", env_extra={"FORM_APPEARANCE": "light"})

    def test_bracket_by_hand(self):        # Wave B acceptance: the bracket from Start blank, sketched on the part (L profile, a pocket on a face), timed (< 120 s)
        self.journey("bracket_by_hand.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_bracket_by_hand_light(self):
        self.journey("bracket_by_hand.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_new_tools(self):              # 12.3: a boss at a face, every printer compared, a turntable, Open in <Slicer>
        # real slicers where they are installed (macOS here); elsewhere a stand-in OrcaSlicer that copies a fixture G-code
        # and writes the project 3MF its CLI writes. Opening the slicer app is recorded, never done (FORM_FAKE_LAUNCH).
        sys.path.insert(0, str(HERE))
        from test_plates import REAL
        tmp = Path(tempfile.mkdtemp(prefix="form-ui-tools-"))
        launch = {"FORM_FAKE_LAUNCH": str(tmp / "launch.jsonl")}
        if REAL:
            return self.journey("new_tools.py", env_extra=launch)
        import stat
        from test_slicers import FIX, NOWHERE
        from form.adapters import SLICERS
        py = tmp / "stand_in.py"
        py.write_text("import sys, shutil, os, json, zipfile\nargs = sys.argv[1:]\nif args == ['--help']:\n    print('OrcaSlicer-2.5.1:'); sys.exit(0)\n"
                      f"out = args[args.index('--outputdir') + 1]\nshutil.copyfile({str(FIX / 'orca' / 'generic_printer.gcode')!r}, "
                      "os.path.join(out, 'plate_1.gcode'))\n"
                      "merged = {}\n"
                      "for f in args[args.index('--load-settings') + 1].split(';') + [args[args.index('--load-filaments') + 1]]:\n"
                      "    merged.update(json.load(open(f)))\n"
                      "merged['different_settings_to_system'] = ['', '', '']\n"
                      "with zipfile.ZipFile(os.path.join(out, 'plate.3mf'), 'w') as z:\n"
                      "    z.writestr('Metadata/project_settings.config', json.dumps(merged))\n", encoding="utf-8")
        if os.name == "nt":
            app = tmp / "orca.cmd"
            app.write_text(f'@"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
        else:
            app = tmp / "orca"
            app.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
            app.chmod(app.stat().st_mode | stat.S_IEXEC)
        toml = tmp / "studio.toml"
        toml.write_text(f'[slicer]\nkind = "orca"\napp = {json.dumps(NOWHERE)}\n'
                        f'[slicer.orca]\napp = {json.dumps(str(app))}\nconfig_dir = {json.dumps(str(FIX / "orca" / "config"))}\n'
                        + "".join(f"[slicer.{k}]\napp = {json.dumps(NOWHERE)}\n" for k in SLICERS if k not in ("bambu", "orca")),
                        encoding="utf-8")
        from unittest import mock
        with mock.patch.dict(os.environ, {"FORM_UI_STUDIO_TOML": str(toml)}):
            self.journey("new_tools.py", env_extra=launch)

    def test_lighter_replace(self):        # 12.3: make it lighter (real checks, real slices), replace a broken part
        self.journey("lighter_replace.py")

    def test_assembly_chain(self):         # a joint slider moves the whole chain; exploded follows the tree
        self.journey("assembly_chain.py")

    def test_drag_edit(self):               # Cmd-drag a face: the parameter behind it changes, live, with its impact
        self.journey("drag_edit.py")

    def test_inspect(self):                 # measuring on parts in every view, annotations, colours and materials
        self.journey("inspection.py")

    def test_fit_prove_release(self):
        self.journey("prove_release.py")

    def test_conversations(self):
        self.journey("chat.py")

    def test_chat_ask_fix(self):
        self.journey("chat_ask.py")

    def test_home(self):
        self.journey("home.py")

    def test_open_conversation(self):        # a conversation opens its design; a strip for several; "No design yet"
        self.journey("open_conv.py")

    def test_open_conversation_small(self):
        self.journey("open_conv.py", size="1120x700")

    def test_ground(self):                   # the studio floor; the plate and the printer only where printing matters
        self.journey("ground.py")

    def test_ground_small(self):
        self.journey("ground.py", size="1120x700")

    def test_start(self):                    # Home's start: blank, a photo, a sketch, concepts, a measurement
        self.journey("start.py")

    def test_import_and_whats_new(self):     # a project archive round trip, What's New once
        self.journey("starting.py")

    def test_busy_feedback(self):            # a slow action's busy button and activity bar
        self.journey("sharing.py")

    def test_sheets_palette_shortcuts(self):
        # installs and the upgrade are simulated, one item is reported missing so there is something to install,
        # and a newer release is pretended so the update sheet has something to offer
        self.journey("shell.py", env_extra={"FORM_INSTALL_FAKE": "0.6", "FORM_SETUP_PRETEND_MISSING": "openscad,parts",
                                            "FORM_FAKE_LATEST": "99.0.0",
                                            "FORM_UITEST_API_AGENTS": "1"})     # the provider rows on Settings › Agents & models

    def test_palette_everywhere(self):       # a row's preview, Tab: what was said inside conversations, settings by name
        self.journey("palette_everywhere.py")

    def test_printers(self):
        # Bambu Studio is a fixture folder; every other slicer points at a program that does not exist
        sys.path.insert(0, str(HERE))
        from test_printers import bambu_dir
        from test_slicers import NOWHERE
        from form.adapters import SLICERS
        tmp = Path(tempfile.mkdtemp(prefix="form-ui-printers-"))
        d = bambu_dir(tmp)
        toml = tmp / "studio.toml"
        toml.write_text(f'[slicer]\nkind = "bambu"\napp = {json.dumps(sys.executable)}\nconfig_dir = {json.dumps(str(d))}\n'
                        + "".join(f"[slicer.{k}]\napp = {json.dumps(NOWHERE)}\n" for k in SLICERS if k != "bambu"), encoding="utf-8")
        from unittest import mock
        with mock.patch.dict(os.environ, {"FORM_UI_STUDIO_TOML": str(toml)}):     # run_journey copies it into the run's folder
            self.journey("printers.py")

    # -- engine workstream: several plates, Design only (tests/journeys/plates.py, design_only.py) --
    def _no_slicers_toml(self, extra: str = "") -> Path:
        sys.path.insert(0, str(HERE))
        from test_slicers import NOWHERE
        from form.adapters import SLICERS
        tmp = Path(tempfile.mkdtemp(prefix="form-ui-engine-"))
        toml = tmp / "studio.toml"
        toml.write_text(extra + f'[slicer]\napp = {json.dumps(NOWHERE)}\n'
                        + "".join(f"[slicer.{k}]\napp = {json.dumps(NOWHERE)}\n" for k in SLICERS if k != "bambu"), encoding="utf-8")
        return toml

    def test_design_only(self):          # someone who prints but has no slicer: 3D printing is on, nothing slices
        from unittest import mock
        toml = self._no_slicers_toml('[general]\ncapabilities = ["core", "parts", "mesh", "print"]\n')
        with mock.patch.dict(os.environ, {"FORM_UI_STUDIO_TOML": str(toml)}):
            self.journey("design_only.py")

    # -- designing without a printer, and settings that apply at once (tests/journeys/no_printer.py, settings_live.py) --
    def test_no_printer(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"FORM_UI_STUDIO_TOML": str(self._no_slicers_toml())}):
            self.journey("no_printer.py")

    def test_settings_live(self):
        sys.path.insert(0, str(HERE))
        from test_printers import bambu_dir
        from test_slicers import NOWHERE
        from form.adapters import SLICERS
        tmp = Path(tempfile.mkdtemp(prefix="form-ui-settings-"))
        d = bambu_dir(tmp)
        toml = tmp / "studio.toml"
        toml.write_text(f'[slicer]\nkind = "bambu"\napp = {json.dumps(sys.executable)}\nconfig_dir = {json.dumps(str(d))}\n'
                        + "".join(f"[slicer.{k}]\napp = {json.dumps(NOWHERE)}\n" for k in SLICERS if k != "bambu"), encoding="utf-8")
        from unittest import mock
        with mock.patch.dict(os.environ, {"FORM_UI_STUDIO_TOML": str(toml)}):
            self.journey("settings_live.py")

    def test_plates(self):
        # a stand-in OrcaSlicer that copies a fixture G-code: the same on every machine
        import stat
        sys.path.insert(0, str(HERE))
        from test_slicers import FIX, NOWHERE
        from form.adapters import SLICERS
        tmp = Path(tempfile.mkdtemp(prefix="form-ui-plates-"))
        py = tmp / "stand_in.py"
        py.write_text("import sys, shutil, os\nargs = sys.argv[1:]\nif args == ['--help']:\n    print('OrcaSlicer-2.5.1:'); sys.exit(0)\n"
                      f"out = args[args.index('--outputdir') + 1]\nshutil.copyfile({str(FIX / 'orca' / 'generic_printer.gcode')!r}, "
                      "os.path.join(out, 'plate_1.gcode'))\n", encoding="utf-8")
        if os.name == "nt":                  # Windows starts a .cmd file, not a shell script
            app = tmp / "orca.cmd"
            app.write_text(f'@"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
        else:
            app = tmp / "orca"
            app.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
            app.chmod(app.stat().st_mode | stat.S_IEXEC)
        toml = tmp / "studio.toml"
        toml.write_text(f'[printer]\nenvelope_mm = [180, 180, 180]\n[slicer]\nkind = "orca"\napp = {json.dumps(NOWHERE)}\n'
                        f'[slicer.orca]\napp = {json.dumps(str(app))}\nconfig_dir = {json.dumps(str(FIX / "orca" / "config"))}\n'
                        + "".join(f"[slicer.{k}]\napp = {json.dumps(NOWHERE)}\n" for k in SLICERS if k not in ("bambu", "orca")),
                        encoding="utf-8")
        from unittest import mock
        with mock.patch.dict(os.environ, {"FORM_UI_STUDIO_TOML": str(toml)}):
            self.journey("plates.py")

    @unittest.skipUnless(sys.platform == "darwin" or os.environ.get("FORM_UI_REAL_SLICER") == "1",
                         "the real slicer journey runs where a slicer is installed (macOS here, or FORM_UI_REAL_SLICER=1)")
    def test_plates_real_slicer(self):
        sys.path.insert(0, str(HERE))
        from test_plates import REAL
        if not REAL:
            self.skipTest("no Bambu Studio or OrcaSlicer with a printer selected")
        self.journey("plates.py")

    def test_api_agents(self):
        self.journey("agents.py", env_extra={"FORM_UITEST_API_AGENTS": "1"})

    def test_custom_providers(self):          # a provider added by address, and a model menu with hundreds of models
        self.journey("providers.py", env_extra={"FORM_UITEST_API_AGENTS": "1"})

    def test_install_flow(self):
        self.journey("install.py", env_extra={"FORM_INSTALL_FAKE": "3", "FORM_SETUP_PRETEND_MISSING": "parts,claude.signin",
                                              "FORM_NO_AUTO_SETUP": ""})

    def test_software_engines(self):        # one Install per engine row; a non-commercial licence is confirmed first
        self.journey("software_engines.py", env_extra={"FORM_INSTALL_MOCK_DOWNLOADS": "1"})

    def test_settings_tour(self):           # every Settings page from the rail, the Use switch, search across pages
        self.journey("settings_tour.py", env_extra={"FORM_APPEARANCE": "dark"})

    def test_settings_tour_light(self):     # the same in the light appearance
        self.journey("settings_tour.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_backups(self):                 # Settings › Backups: back up now, listed and verified, Recently deleted, put back
        self.journey("backups.py", env_extra={"FORM_APPEARANCE": "light"})

    def test_ui_tree(self):                 # the item tree as data, never a password field's text
        self.journey("ui_tree.py", env_extra={"FORM_UITEST_API_AGENTS": "1"})

    def test_a_failure_writes_the_tree_beside_its_screenshot(self):
        with tempfile.TemporaryDirectory(prefix="form-ui-out-") as out:
            rc, log = run_journey("ui_tree.py::deliberate_failure", env_extra={"FORM_UITEST_OUT": out})
            self.assertEqual(rc, 1, log)
            png, dump = Path(out) / "fail-ui_tree-deliberate_failure.png", Path(out) / "fail-ui_tree-deliberate_failure.json"
            self.assertTrue(png.exists(), log)
            t = json.loads(dump.read_text(encoding="utf-8"))
            self.assertEqual(t["root"]["className"], "QQuickRootItem")
            self.assertIn("tree: ", log)

    def test_smallest_window(self):
        self.journey("sizes.py", size="1120x700")

    def test_large_window(self):
        self.journey("sizes.py", size="1728x1117")


if __name__ == "__main__":
    unittest.main()
