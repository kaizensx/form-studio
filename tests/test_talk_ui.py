"""The conversation column and the viewport's state machines, loaded offscreen (QT_QPA_PLATFORM=offscreen).

The window is the real interface (python -m form.app --check) over a real engine and a temporary data folder; a script
run inside it throws (a QML warning, so --check fails) when something is wrong.

- A long saved conversation (tests/fixtures/conversations/long_mixed.jsonl: the event mix of a real one, 132 events
  with tools, an ask and its answer, suggestions and revision changes, with every text replaced) opens with every
  message drawn. A ListView add transition stopped by the feed jumping to its end used to leave messages at opacity
  0: an empty column with only the last footer.

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


if __name__ == "__main__":
    unittest.main()
