"""The conversation column and the viewport's state machines, loaded offscreen (QT_QPA_PLATFORM=offscreen).

The window is the real interface (python -m form.app --check) over a real engine and a temporary data folder; a script
run inside it throws (a QML warning, so --check fails) when something is wrong.

- A long saved conversation (tests/fixtures/conversations/long_mixed.jsonl: the event mix of a real one, 132 events
  with tools, an ask and its answer, suggestions and revision changes, with every text replaced) opens with every
  message drawn. A ListView add transition stopped by the feed jumping to its end used to leave messages at opacity
  0: an empty column with only the last footer.
- Compare (an older revision as a ghost) ends from the reply card's Compare again, the Done on the viewport's
  "Comparing" chip, Esc, another stage, and showing another revision. compareChange used to switch the stage (which
  ended it) and then compare again, so it never went off.
- The "Building <feature>" caption of a streamed build goes once the build is saved, even when the saved head never
  took over (a commit that arrived with its last stages), and never sits under the dock's refinement panel.

Skipped without PySide6, or with FORM_SKIP_UI=1."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "conversations" / "long_mixed.jsonl"
CID = "f1a7e5c0a1b2"

# shared by the scripts below: find an item by objectName, run later, fail loudly
LIB = textwrap.dedent("""
    var win = this
    function find(it, n) {
        if (!it) return null
        if (it.objectName === n) return it
        var ch = it.children || []
        for (var i = 0; i < ch.length; i++) { var r = find(ch[i], n); if (r) return r }
        if (it.contentItem && it.contentItem !== it) return find(it.contentItem, n)
        return null
    }
    function later(ms, fn) {
        var t = Qt.createQmlObject("import QtQuick; Timer { interval: " + ms + " }", win)
        t.triggered.connect(function () { try { fn() } catch (e) { console.warn("TALKUI " + e); throw e } })
        t.start()
    }
""")

FEED = "(function () {" + LIB + textwrap.dedent("""
    Store.openConv("CID")
    later(3500, function () {
        if (Store.chatItems.length !== 91) throw new Error("TALKUI the conversation loaded " + Store.chatItems.length + " items, not 91")
        var feed = find(win.contentItem, "talkFeed")
        if (!feed || !feed.visible) throw new Error("TALKUI the feed is not shown")
        var talk = find(win.contentItem, "talk"), want = talk.build().length
        if (feed.count !== want || want < 50) throw new Error("TALKUI the feed has " + feed.count + " blocks, want " + want)
        // it opened at its end, and what is there is drawn
        var last = feed.itemAtIndex(feed.count - 1)
        if (!last || last.opacity < 0.99) throw new Error("TALKUI the newest block is not drawn")
        // every block, scrolled to, is there and fully drawn
        feed.stick = false
        var bad = []
        for (var j = 0; j < feed.count; j++) {
            feed.positionViewAtIndex(j, ListView.Contain)
            var d = feed.itemAtIndex(j)
            if (!d) { bad.push(j + " missing"); continue }
            if (d.opacity < 0.99 || d.height <= 0) bad.push(j + " (" + d.k + ") opacity " + d.opacity.toFixed(2) + " height " + d.height)
        }
        if (bad.length) throw new Error("TALKUI blocks not drawn: " + bad.join(", "))
        console.warn("TALKUI feed done")
    })
""") + "}).call(this)"


# a design with two revisions, for Compare and the caption
PREP = textwrap.dedent("""
    import json
    from form import config
    from form.studio import Studio
    if __name__ == "__main__":             # the kernel's worker processes import this file again
        st = Studio(config.load())
        p = st.create("Coupon", "coupon")
        st.commit(st.load(p["id"]), {"wall": 5.0}, "thicker wall")
        st.kernel.stop()
        print(json.dumps({"id": p["id"]}))
""")

COMPARE = "(function () {" + LIB + textwrap.dedent("""
    var ch = { project: Store.pid, from: 1, to: 2 }
    // comparing is a wipe: the other revision is drawn as a solid right of a line that can be dragged
    function wipe() { var w = find(win.contentItem, "compareWipe"); return !!w && w.visible && Store.viewer.wipeOn && Store.viewer.wipeX >= 0 }
    function on(what) {
        if (!Store.compare || Store.compare.rev !== 1) throw new Error("TALKUI compare did not start: " + what)
        if (!wipe()) throw new Error("TALKUI comparing shows no wipe line: " + what)
    }
    function off(what) {
        if (Store.compare) throw new Error("TALKUI compare did not end: " + what)
        if (wipe() || Store.viewer.alt) throw new Error("TALKUI the wipe stayed after comparing ended: " + what)
    }
    if (Store.project.head !== 2) throw new Error("TALKUI the design has head " + Store.project.head)
    Store.setStage("fit")
    Store.compareChange(ch)                          // from another stage: it goes to Shape and compares
    later(1500, function () {
        on("Compare on the reply card")
        if (Store.stage !== "shape") throw new Error("TALKUI compare did not go to Shape")
        var chip = find(win.contentItem, "compareChip")
        if (!chip || !chip.visible) throw new Error("TALKUI the Comparing chip is not shown")
        Store.compareChange(ch); off("Compare clicked again")
        Store.compareChange(ch)
    })
    later(3000, function () {
        on("Compare after toggling off")
        find(win.contentItem, "compareDone").clicked(); off("Done on the chip")
        Store.compareWith(1)
    })
    later(4500, function () { on("compareWith"); win.esc(); off("Esc"); Store.compareWith(1) })
    later(6000, function () { on("compareWith"); Store.setStage("fit"); off("another stage"); Store.setStage("shape"); Store.compareWith(1) })
    later(7500, function () { on("compareWith"); Store.showRev(1) })
    later(9000, function () { off("showing another revision"); Store.endScrub(); console.warn("TALKUI compare done") })
""") + "}).call(this)"

CAPTION = "(function () {" + LIB + textwrap.dedent("""
    var cap = find(win.contentItem, "buildCaption")
    function shown() { return cap.visible && cap.opacity > 0.5 }
    function rect(it) { var p = it.mapToItem(null, 0, 0); return { x: p.x, y: p.y, w: it.width, h: it.height } }
    function hits(a, b) { return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h }
    // a build of this design streamed to its 5th of 6 stages, and its commit was handled (handed to the head)
    Store.building = { draft: "draft-test", project: Store.pid, feature: "keeper", label: "A long cable keeper label", at: 5, of: 6, index: 5 }
    Store._endDraft("draft-test"); Store._handoff = true
    // the dock shows the refinement panel at the same time
    Store.refine = { state: "failed", changes: [], error: "Nothing helped enough", stage: "" }
    later(700, function () {
        if (!shown()) throw new Error("TALKUI the caption is not shown while building")
        var rp = find(win.contentItem, "refinePanel")
        if (!rp || !rp.visible) throw new Error("TALKUI the refinement panel is not shown")
        if (hits(rect(cap), rect(rp))) throw new Error("TALKUI the caption " + JSON.stringify(rect(cap)) + " overlaps the refinement panel " + JSON.stringify(rect(rp)))
    })
    later(4500, function () {
        if (Store.building) throw new Error("TALKUI the caption of a saved build stayed: " + Store.buildingText)
        if (shown()) throw new Error("TALKUI the caption is still on screen")
        // a build nobody saved: cleared once the reply has ended (no reply runs here)
        Store.building = { draft: "draft-test2", project: Store.pid, feature: "rim", label: "Rim", at: 2, of: 4, index: 2 }
    })
    later(8500, function () {
        if (Store.building) throw new Error("TALKUI the caption of an unsaved build stayed: " + Store.buildingText)
        console.warn("TALKUI caption done")
    })
""") + "}).call(this)"


def _why_not() -> str:
    if os.environ.get("FORM_SKIP_UI") == "1":
        return "FORM_SKIP_UI=1"
    if importlib.util.find_spec("PySide6") is None:
        return "PySide6 is not installed"
    return ""


def _env(tmp: Path) -> dict:
    data = tmp / "data"
    data.mkdir()
    (data / ".form-setup.json").write_text(json.dumps({"ts": 1, "version": "test", "how": "done"}))
    return dict(os.environ, FORM_DATA=str(data), FORM_CONFIG=str(tmp / "studio.toml"), FORM_NO_UPDATE_CHECK="1",
                FORM_NO_AUTO_SETUP="1", FORM_PROVIDERS_OFFLINE="1", FORM_SECRETS=str(tmp / "secrets.json"),
                PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen")


def _saved_conversation(data: Path) -> None:
    d = data / ".conversations" / CID
    d.mkdir(parents=True)
    shutil.copy(FIXTURE, d / "events.jsonl")
    evs = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    meta = {"id": CID, "title": "A long conversation", "title_auto": False, "thread": CID, "parent": None,
            "fork_event": None, "fork_reason": "", "project": None, "agent": "claude", "model": "default",
            "effort": "", "session": None, "session_agent": None, "resolved_model": None, "resolved_agent": None,
            "created": evs[0]["ts"], "updated": evs[-1]["ts"], "pinned": False,
            "cost_usd": sum(e.get("cost_usd", 0) for e in evs if e["t"] == "end"), "cost_known": True,
            "messages": sum(e["t"] == "user" for e in evs), "events": len(evs), "preview": "", "designs": []}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _design(env: dict, tmp: Path) -> str:
    prep = tmp / "prep.py"
    prep.write_text(PREP, encoding="utf-8")
    r = subprocess.run([sys.executable, str(prep)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise AssertionError(r.stderr[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])["id"]


def _run(env: dict, js: str, after: int, extra=()) -> str:
    r = subprocess.run([sys.executable, "-m", "form.app", "--check", "--wait", "3000", *extra, "--eval", js,
                        "--after", str(after)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    return out if r.returncode == 0 else out + f"\n(exit {r.returncode})"


class FixtureShape(unittest.TestCase):
    """Without Qt: the fixture keeps the event mix that showed the bug, and nothing private."""

    def test_event_mix(self):
        evs = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
        kinds = {}
        for e in evs:
            kinds[e["t"]] = kinds.get(e["t"], 0) + 1
        self.assertEqual(kinds, {"tool": 41, "result": 41, "text": 20, "user": 8, "start": 8, "end": 8, "suggest": 4,
                                 "ask": 1, "answer": 1})
        text = FIXTURE.read_text(encoding="utf-8")
        for private in ("/Users/", "attachments", "IMG_", "\"img\""):
            self.assertNotIn(private, text)


@unittest.skipIf(_why_not(), _why_not())
class TalkOffscreen(unittest.TestCase):
    def test_long_saved_conversation_is_drawn(self):
        with tempfile.TemporaryDirectory(prefix="form-talkui-") as tmp:
            env = _env(Path(tmp))
            _saved_conversation(Path(env["FORM_DATA"]))
            out = _run(env, FEED.replace("CID", CID), 5000)
            self.assertIn("TALKUI feed done", out, out[-4000:])
            self.assertNotIn("(exit", out, out[-4000:])

    def test_compare_and_build_caption(self):
        with tempfile.TemporaryDirectory(prefix="form-talkui-") as tmp:
            env = _env(Path(tmp))
            pid = _design(env, Path(tmp))
            for js, after, done in ((COMPARE, 10000, "TALKUI compare done"), (CAPTION, 9500, "TALKUI caption done")):
                # a narrow window: the caption and the dock compete for the top of the viewport
                out = _run(env, js, after, ["--project", pid, "--stage", "shape", "--size", "1000x720", "--wait", "6000"])
                self.assertIn(done, out, out[-4000:])
                self.assertNotIn("(exit", out, out[-4000:])


if __name__ == "__main__":
    unittest.main()
