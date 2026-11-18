"""How a design starts (form/start.py, form/sketch.py, form/concepts.py): purpose, Blank, links, sketches, guided
measurements and concepts first. Real kernel builds for designs; a local HTTP server for links; the stand-in agent
(tests/fixtures/fake_agent.py) for the chat path. No model, no network beyond loopback."""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import ask, chat, concepts, config, sketch, start  # noqa: E402
from form.conversations import ConversationError, Conversations, kind_of  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402
from tests.test_chat_interactive import AskFake as Fake  # noqa: E402  (passes FORM_ASK_DIR on to the stand-in)
from tests.test_conversations import wait  # noqa: E402

_spec = importlib.util.spec_from_file_location("fake_agent", ROOT / "tests" / "fixtures" / "fake_agent.py")
fake_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake_agent)
TINY = [{"title": t, "rationale": why, "source": fake_agent._source(t, expr)} for t, (expr, why) in fake_agent.TINY.items()]
BROKEN = "from form.recipes.base import Recipe\n\nclass Design(Recipe):\n    title = 'x'\n    def build(self, v):\n        raise RuntimeError('no')\n"

SKETCH = {"version": 1, "units": "mm", "grid_mm": 5, "view": "top", "intent": "extrude", "depth_mm": 12, "notes": "a plate",
          "primitives": [{"id": "p1", "type": "rect", "a": [0, 0], "b": [60, 40]},
                         {"type": "circle", "c": [30, 20], "r": 4.004},
                         {"type": "arc", "c": [0, 0], "r": 10, "start_deg": 0, "end_deg": 90},
                         {"type": "path", "points": [[0, 0], [5, 5], [10, 0]]},
                         {"type": "line", "a": [0, 0], "b": [0, -5]},
                         {"type": "dim", "a": [0, 0], "b": [60, 0], "value": 62, "label": "width"},
                         {"type": "dim", "a": [0, 0], "b": [0, 40], "value": None, "label": "depth"}]}


class Env(unittest.TestCase):
    """One data folder and one Studio (with its kernel worker) per class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="form-start-"))
        cls.data = cls.tmp / "data"
        cls.data.mkdir()
        cls.env = mock.patch.dict(os.environ, {"FORM_DATA": str(cls.data), "FORM_CONFIG": str(cls.tmp / "none.toml")})
        cls.env.start()
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)


# ---- sketches ------------------------------------------------------------------------------------------------------

class Sketches(unittest.TestCase):
    def test_validate_normalises(self):
        s = sketch.validate(SKETCH)
        self.assertEqual([p["id"] for p in s["primitives"]], ["p1", "p2", "p3", "p4", "p5", "p6", "p7"])
        self.assertEqual(s["primitives"][1]["r"], 4.0)                     # rounded to 0.01 mm
        self.assertEqual(sketch.validate({"primitives": []})["view"], "top")

    def test_summary_bbox_counts_and_stated_dims(self):
        sm = sketch.summarize(SKETCH)
        self.assertEqual(sm["bbox_mm"], [[0.0, -5.0], [60.0, 40.0]])
        self.assertEqual(sm["counts"], {"rect": 1, "circle": 1, "arc": 1, "path": 1, "line": 1, "dim": 2})
        w, d = sm["dims"]
        self.assertEqual((w["value_mm"], w["source"], w["drawn_mm"]), (62.0, "stated by the user", 60.0))
        self.assertEqual((d["value_mm"], d["source"]), (40.0, "drawn length"))
        self.assertIn("width 62 mm (stated by the user; drawn 60 mm)", sm["text"])
        self.assertIn("extrude 12 mm", sm["text"])

    def test_arc_bbox_follows_its_sweep(self):
        sm = sketch.summarize({"primitives": [{"type": "arc", "c": [0, 0], "r": 10, "start_deg": 350, "end_deg": 10}]})
        self.assertAlmostEqual(sm["bbox_mm"][1][0], 10.0)                  # passes 0°: reaches x = r
        self.assertLess(sm["bbox_mm"][1][1], 2)                           # does not reach 90°

    def test_errors_are_clear(self):
        bad = {
            "unknown type": {"primitives": [{"type": "spline"}]},
            "finite": {"primitives": [{"type": "circle", "c": [0, float("nan")], "r": 1}]},
            "greater than 0": {"primitives": [{"type": "circle", "c": [0, 0], "r": 0}]},
            "at most 2000": {"primitives": [{"type": "line", "a": [0, 0], "b": [1, 1]}] * 2001},
            "5000 points": {"primitives": [{"type": "path", "points": [[i, 0] for i in range(2600)]}] * 2},
            "units": {"units": "in", "primitives": []},
            "point [x, y]": {"primitives": [{"type": "line", "a": [0], "b": [1, 1]}]},
            "finite number": {"primitives": [{"type": "line", "a": [True, 0], "b": [1, 1]}]},
        }
        for words, obj in bad.items():
            with self.assertRaises(ValueError, msg=words) as e:
                sketch.validate(obj)
            self.assertIn(words, str(e.exception))

    def test_sketch_attachment_keeps_its_kind(self):
        self.assertEqual(kind_of("a1b2c3-plate.sketch.json"), "sketch")
        self.assertEqual(kind_of("x.3mf"), "cad")
        with tempfile.TemporaryDirectory() as d:
            s = Conversations(Path(d))
            cid = s.create()["id"]
            rec = s.attach(cid, name="My plate.sketch.json", data=b"{}")
            self.assertEqual((rec["kind"], rec["file"][7:]), ("sketch", "My-plate.sketch.json"))
            with self.assertRaises(ConversationError):
                s.attach(cid, name="notes.json", data=b"{}")


# ---- purpose and Blank ---------------------------------------------------------------------------------------------

class PurposeAndBlank(Env):
    def test_blank_builds_with_its_purpose(self):
        p = start.blank(self.st, "My block", "model")
        self.assertEqual((p["name"], p["purpose"]), ("My block", "model"))
        self.assertEqual(self.st.rev(p)["values"], {"width": 60.0, "depth": 40.0, "height": 20.0, "corner_r": 3.0})
        s = self.st.head_summary(p)                                         # a real build in the kernel
        size = [round(b - a, 3) for a, b in zip(*s["bbox"])]
        self.assertEqual(size, [60.0, 40.0, 20.0])
        self.assertLess(s["volume_mm3"], 60 * 40 * 20)                     # the corners are rounded
        self.assertEqual(self.st.slice_mode(self.st.load(p["id"]))["why"], "purpose")
        p = start.set_purpose(self.st, p["id"], "print")
        self.assertEqual(p["purpose"], "print")
        kinds = [d["kind"] for d in self.st.load(p["id"])["decisions"]]
        self.assertIn("purpose", kinds)                                   # the same record Settings makes
        row = next(r for r in self.st.list() if r["id"] == p["id"])
        self.assertEqual((row["purpose"], row["concept"]), ("print", None))
        with self.assertRaises(StudioError):
            start.set_purpose(self.st, p["id"], "toy")

    def test_default_purpose(self):            # the engine's default (form/purpose.py), and the printer's name
        self.assertIn(start.state(self.st)["purpose"], start.PURPOSES)
        self.assertIn("available", start.state(self.st)["printer"])

    def test_purpose_lines(self):
        self.assertEqual(start.purpose_line("print", "A1 mini"), "Purpose: for 3D printing on A1 mini")
        self.assertEqual(start.purpose_line("model", "A1 mini"),
                         "Purpose: just a 3D model, no printer: do not slice; print checks do not apply.")
        self.assertEqual(start.purpose_line(None, "x"), "")


# ---- links ---------------------------------------------------------------------------------------------------------

class Links(Env):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.www = cls.tmp / "www"
        (cls.www / "files").mkdir(parents=True)
        (cls.www / "files" / "part.stl").write_bytes(b"solid x\nendsolid x\n")
        (cls.www / "page.html").write_text("<html>model page</html>")
        (cls.www / "fake.stl").write_text("<html>not a file</html>")
        cls.hits = []
        www, hits = cls.www, cls.hits

        class H(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(www), **kw)

            def log_message(self, *a):
                pass

            def do_GET(self):
                hits.append(self.path)
                if self.path == "/go.stl":                                 # a redirect to the file
                    self.send_response(302)
                    self.send_header("Location", "/files/part.stl")
                    self.end_headers()
                    return
                if self.path == "/fake.stl":
                    body = b"<html>not a file</html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                super().do_GET()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        super().tearDownClass()

    def setUp(self):
        self.cid = Conversations(self.data).create()["id"]
        del self.hits[:]

    def test_a_file_link_downloads_and_attaches(self):
        got = start.fetch(self.st, self.cid, self.base + "/go.stl")
        (rec,) = got["attachments"]
        self.assertEqual((rec["kind"], rec["name"]), ("cad", "go.stl"))
        self.assertEqual(got["fetched"], {"url": self.base + "/go.stl", "host": "127.0.0.1", "bytes": 19, "name": "go.stl"})
        f = Conversations(self.data).attachment(self.cid, rec["file"])
        self.assertEqual(f.read_bytes(), b"solid x\nendsolid x\n")
        self.assertEqual(self.hits, ["/go.stl", "/files/part.stl"])

    def test_a_page_link_downloads_nothing(self):
        got = start.fetch(self.st, self.cid, self.base + "/page.html")
        self.assertEqual(got, {"link": {"url": self.base + "/page.html", "host": "127.0.0.1", "kind": "page"}})
        self.assertEqual(self.hits, [])
        self.assertEqual(start.fetch(self.st, self.cid, "https://example.com/thing/123")["link"]["kind"], "page")

    def test_refusals(self):
        for url in ("file:///etc/hosts.stl", "ftp://x/y.stl", "javascript:alert(1)", ""):
            with self.assertRaises(StudioError) as e:
                start.fetch(self.st, self.cid, url)
            self.assertIn("http", str(e.exception))
        with self.assertRaises(StudioError) as e:
            start.fetch(self.st, self.cid, self.base + "/fake.stl")        # a web page behind a file name
        self.assertIn("web page", str(e.exception))
        with self.assertRaises(StudioError) as e:
            start.fetch(self.st, self.cid, self.base + "/missing.stl")
        self.assertIn("404", str(e.exception))
        self.assertTrue(e.exception.hint)
        with mock.patch.object(start, "MAX_FETCH", 5), self.assertRaises(StudioError) as e:
            start.fetch(self.st, self.cid, self.base + "/files/part.stl")
        self.assertIn("larger than", str(e.exception))
        with self.assertRaises(StudioError):
            start.fetch(self.st, "000000000000", self.base + "/files/part.stl")


# ---- the chat path: prompt, purpose, sketch, measurement ------------------------------------------------------------

class ChatPath(Env):
    def setUp(self):
        self.fake = Fake(self.data)
        cfg = {"chat": {"agent": "fake", "model": "default", "effort": ""}, "_path": str(self.tmp / "studio.toml"),
               "printer": {"name": "Test printer"}}
        self.chat = chat.Chat(cfg, self.data, "/nonexistent/form-mcp", adapters={"fake": self.fake})
        self.st.chat = self.chat

    def tearDown(self):
        for j in self.chat.running():
            self.chat.stop(j.id)
            wait(j, 5)

    def reply(self, job):
        return "\n".join(e["text"] for e in job.events if e["t"] == "text")

    def test_prompt_inlines_the_sketch_and_says_the_purpose(self):
        cid = self.chat.store.create(None, "fake")["id"]
        a1 = self.chat.store.attach(cid, name="plate.sketch.json", data=json.dumps(sketch.validate(SKETCH)).encode())
        a2 = self.chat.store.attach(cid, name="photo.png", data=b"\x89PNG\r\n\x1a\n")
        a3 = self.chat.store.attach(cid, name="model.3mf", data=b"PK")
        job = wait(self.chat.send("A plate like this", cid, attachments=[a1["id"], a2["id"], a3["id"]], purpose="model"))
        msg = self.fake.runs[-1].message
        self.assertIn(chat.Chat.SKETCH_HEADING, msg)
        inline = json.loads(msg.split(chat.Chat.SKETCH_HEADING, 1)[1].splitlines()[1])
        self.assertEqual(len(inline["primitives"]), 7)
        self.assertIn("Purpose: just a 3D model, no printer: do not slice; print checks do not apply.", msg)
        self.assertIn("cannot import 3MF", msg)                           # said, not faked
        self.assertEqual([f.name for f in self.fake.runs[-1].images], [a2["file"]])
        text = self.reply(job)
        self.assertIn("I received: plate.sketch.json (sketch), photo.png (image), model.3mf (cad)", text)
        self.assertIn("Sketch: 7 primitives", text)
        self.assertIn("Purpose: just a 3D model", text)
        self.assertEqual(self.chat.store.meta(cid)["purpose"], "model")
        wait(self.chat.send("and again", cid))                            # the conversation keeps its purpose
        self.assertIn("Purpose: just a 3D model", self.fake.runs[-1].message)
        job = wait(self.chat.send("For the printer", purpose="print"))
        self.assertIn("Purpose: for 3D printing on Test printer", self.reply(job))
        with self.assertRaises(RuntimeError):
            self.chat.send("x", purpose="toy")

    def test_a_long_sketch_is_cut_by_whole_primitives(self):
        big = {"primitives": [{"type": "line", "a": [i, 0], "b": [i, 10]} for i in range(1500)]}
        cid = self.chat.store.create(None, "fake")["id"]
        a = self.chat.store.attach(cid, name="big.sketch.json", data=json.dumps(sketch.validate(big)).encode())
        job = wait(self.chat.send("big", cid, attachments=[a["id"]]))
        block = self.fake.runs[-1].message.split(chat.Chat.SKETCH_HEADING, 1)[1].splitlines()[1]
        self.assertLessEqual(len(block), chat.Chat.SKETCH_CHARS)
        self.assertTrue(json.loads(block)["truncated"])
        self.assertIn("Sketch: 1500 primitives", self.reply(job))

    def test_measurement_round_trip_commits_with_provenance(self):
        p = start.blank(self.st, "Measured block", "print")
        time.sleep(0.01)
        job = self.chat.send("measure the block")
        t0 = time.time()
        while not job.waiting and time.time() - t0 < 30:
            time.sleep(0.05)
        q = job.waiting
        self.assertIsNotNone(q, job.events)
        self.assertEqual((q["kind"], q["project"], q["param"], q["unit"]), ("measure", p["id"], "width", "mm"))
        self.assertEqual((q["tolerance_mm"], q["diagram"], q["current"]), (0.1, {"shape": "box", "axis": "x"}, 60.0))
        self.assertEqual(q["choices"], list(ask.METHODS))
        self.assertIn("widest", q["where"])
        with self.assertRaises(ConversationError):                        # a number is needed
            start.answer(self.st, job.conversation, q["id"], "", [], {"method": "calipers"})
        with self.assertRaises(ConversationError):                        # and how it was measured
            start.answer(self.st, job.conversation, q["id"], "52", [])
        ev = start.answer(self.st, job.conversation, q["id"], "", [], {"value": 52.3, "method": "calipers"})
        self.assertEqual((ev["value"], ev["method"], ev["source"], ev["rev"]), (52.3, "calipers", "measured", 2))
        wait(job)
        self.assertIn("You measured: 52.3 mm with calipers", self.reply(job))
        p = self.st.load(p["id"])
        head = self.st.rev(p)
        self.assertEqual((p["head"], head["values"]["width"], head["origin"]), (2, 52.3, "user"))
        self.assertEqual(head["provenance"]["width"],
                         {"source": "measured", "sigma": 0.05, "instrument": "calipers", "note": "Measured with calipers"})
        a = json.loads(next(self.chat.ask_dir(job.conversation).glob("*.a.json")).read_text())
        self.assertEqual((a["value"], a["rev"], a["source"]), (52.3, 2, "measured"))
        saved = [e for e in self.chat.store.events(job.conversation) if e["t"] == "answer"]
        self.assertEqual(saved[-1]["rev"], 2)

    def test_an_estimate_stays_assumed(self):
        p = start.blank(self.st, "Estimated block", "print")
        rec = start.apply_measurement(self.st, p["id"], "depth", 41, "estimate")
        self.assertEqual(rec["source"], "assumed")
        prov = self.st.rev(self.st.load(p["id"]))["provenance"]["depth"]
        self.assertEqual(prov["source"], "assumed")
        self.assertNotIn("sigma", prov)
        rec = start.apply_measurement(self.st, p["id"], "depth", 41, "ruler")
        self.assertEqual(self.st.rev(self.st.load(p["id"]), rec["rev"])["provenance"]["depth"]["sigma"], 0.5)
        for bad in (("nope", 1, "ruler"), ("depth", "x", "ruler"), ("depth", 41, "laser")):
            with self.assertRaises(StudioError):
                start.apply_measurement(self.st, p["id"], *bad)

    def test_measure_question_record_and_result(self):
        q = ask.measure_question("How wide?", "p", "w", where="  across  ", tolerance_mm=0.2,
                                 diagram={"shape": "hole", "axis": "d"}, image="0123456789.png", mark=[0, 0.2, 1.5, 0.5])
        self.assertEqual((q["kind"], q["where"], q["mark"], q["image"]), ("measure", "across", [0, 0.2, 1.0, 0.5], "0123456789.png"))
        with self.assertRaises(ask.AskError):
            ask.measure_question("How wide?", "p", "w", diagram={"shape": "star"})
        self.assertIsNone(ask.measure_question("x", "p", "w", image="../etc/passwd")["image"])
        r = ask.measure_result(q, "answered", {"text": "52,5 mm", "choices": ["tape"]})
        self.assertEqual((r["value"], r["method"], r["source"]), (52.5, "tape", "measured"))
        self.assertFalse(ask.measure_result(q, "closed", {"reason": "timeout"})["answered"])

    def test_concepts_through_the_stand_in_agent(self):
        with mock.patch.dict(os.environ, {"FORM_DATA": str(self.data)}):
            job = wait(self.chat.send("concepts for a desk hook", purpose="model"), 120)
        self.assertEqual(job.state, "done", job.error)
        self.assertIn("Concepts: A Block, B Disc, C Bracket", self.reply(job))
        res = next(e for e in job.events if e["t"] == "result" and e.get("name") == "propose_concepts")
        g = concepts.board(self.st, res["concepts"]["group"])
        self.assertEqual([m["letter"] for m in g["members"]], ["A", "B", "C"])
        self.assertTrue(all(self.st.load(m["project"])["purpose"] == "model" for m in g["members"]))


# ---- concepts ------------------------------------------------------------------------------------------------------

class Concepts(Env):
    def test_create_board_pick_and_trash(self):
        acts0 = len(self.st.activity_since(0, 10000))
        b = concepts.create(self.st, "Cable clip", TINY + [{"title": "Broken", "source": BROKEN}], "Holds a cable.",
                            purpose="print")
        self.assertEqual([m["letter"] for m in b["members"]], ["A", "B", "C"])
        self.assertEqual([f["letter"] for f in b["failed"]], ["D"])
        self.assertTrue(b["failed"][0]["error"]["message"])
        a = b["members"][0]
        self.assertEqual((a["name"], a["title"], a["numbers"]["size_mm"], a["numbers"]["evidence"]),
                         ("Cable clip · A", "Block", [30.0, 18.0, 8.0], "computed"))
        self.assertAlmostEqual(a["numbers"]["volume_cm3"], 4.32, places=2)
        p = self.st.load(a["project"])
        self.assertEqual(p["concept"], {"group": b["id"], "letter": "A", "title": "Block", "rationale": a["rationale"]})
        self.assertEqual(p["purpose"], "print")
        acts = self.st.activity_since(0, 10000)[acts0:]
        self.assertTrue(any(e["kind"] == "concepts" and e.get("group") == b["id"] for e in acts))
        self.assertIn(b["id"], [g["id"] for g in concepts.groups(self.st)])

        more = concepts.create(self.st, "Cable clip", TINY[:1], group=b["id"])  # a mix the person asked for
        self.assertEqual([m["letter"] for m in more["members"]], ["A", "B", "C", "E"])
        with self.assertRaises(StudioError):
            concepts.create(self.st, "Cable clip", TINY + TINY[:1], group=b["id"])     # more than 6 in all

        picked = b["members"][1]["project"]
        r = concepts.pick(self.st, b["id"], picked)
        self.assertEqual(r["picked"], picked)
        self.assertEqual(sorted(r["trashed"]), sorted(m["project"] for m in more["members"] if m["project"] != picked))
        self.assertEqual(self.st.load(picked)["name"], "Cable clip")
        self.assertTrue(any("Picked concept B: Disc from 4 concepts" in d["text"] for d in self.st.load(picked)["decisions"]))
        for pid in r["trashed"]:
            self.assertFalse((self.data / pid).exists())
            self.assertTrue(any(d.name.startswith(pid + "-") for d in (self.data / ".trash").iterdir()))
        self.assertEqual(concepts.board(self.st, b["id"])["state"], "picked")
        self.assertNotIn(b["id"], [g["id"] for g in concepts.groups(self.st)])
        self.assertIn(b["id"], [g["id"] for g in concepts.groups(self.st, "picked")])
        with self.assertRaises(StudioError) as e:
            concepts.pick(self.st, b["id"], picked)
        self.assertEqual(e.exception.status, 409)

    def test_keep_others_and_refusals(self):
        b = concepts.create(self.st, "Shelf pin", TINY[:2])
        r = concepts.pick(self.st, b["id"], b["members"][0]["project"], keep_others=True)
        self.assertEqual((r["trashed"], r["kept"]), ([], [b["members"][1]["project"]]))
        self.assertTrue(self.st.load(b["members"][1]["project"]))
        with self.assertRaises(StudioError):
            concepts.create(self.st, "One only", TINY[:1])
        with self.assertRaises(StudioError) as e:
            concepts.create(self.st, "All broken", [{"title": "x", "source": BROKEN}, {"title": "y", "source": BROKEN}])
        self.assertIn("None of the concepts built", str(e.exception))
        with self.assertRaises(StudioError):
            concepts.board(self.st, "../../etc")

    def test_http_routes(self):
        from form.server import make_handler
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api"

        def call(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json", "Connection": "close"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                return json.loads(e.read())
        try:
            self.assertIn(call("/start")["purpose"], start.PURPOSES)
            self.assertIn("error", call("/start/blank", {"name": "Toy", "purpose": "toy"}))
            got = call("/start/blank", {"name": "Route block", "purpose": "model"})
            self.assertTrue(got["job"])
            self.assertEqual(self.st.load(got["id"])["purpose"], "model")
            row = call(f"/projects/{got['id']}/purpose", {"purpose": "print"})
            self.assertEqual((row["id"], row["purpose"]), (got["id"], "print"))
            b = concepts.create(self.st, "Route hook", TINY[:2])
            self.assertIn(b["id"], [g["id"] for g in call("/concepts")["groups"]])
            self.assertEqual(call(f"/concepts/{b['id']}")["name"], "Route hook")
            r = call(f"/concepts/{b['id']}/pick", {"project": b["members"][0]["project"], "keep_others": True})
            self.assertEqual(r["picked"], b["members"][0]["project"])
            cid = self.st.chat.store.create()["id"]
            sk = call(f"/conversations/{cid}/sketch", {"sketch": SKETCH, "name": "plate"})
            self.assertEqual((sk["attachments"][0]["kind"], sk["attachments"][0]["name"]), ("sketch", "plate.sketch.json"))
            self.assertEqual(sk["summary"]["counts"]["dim"], 2)
            self.assertIn("could not be read", call(f"/conversations/{cid}/sketch", {"sketch": {"primitives": [{"type": "x"}]}})["error"]["message"])
            self.assertEqual(call(f"/conversations/{cid}/fetch", {"url": "https://example.com/a"})["link"]["kind"], "page")
            # a measurement card's picture, served from the ask folder
            folder = self.st.chat.ask_dir(cid)
            qid = ask.new_id()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{qid}.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
            ask.post(folder, ask.measure_question("How wide?", None, None, image=f"{qid}.png"), qid=qid)
            with urllib.request.urlopen(f"{base}/conversations/{cid}/ask/{qid}/image", timeout=10) as r:
                self.assertEqual(r.read(), b"\x89PNG\r\n\x1a\nxx")
            ans = call(f"/conversations/{cid}/answer", {"id": qid, "measure": {"value": 12, "method": "ruler"}})
            self.assertEqual((ans["value"], ans["method"], ans["source"], ans["rev"]), (12.0, "ruler", "measured", None))
        finally:
            httpd.shutdown()


# ---- MCP and CLI -------------------------------------------------------------------------------------------------

class McpAndCli(unittest.TestCase):
    def test_mcp_tools(self):
        asyncio.run(self._mcp())

    async def _mcp(self):
        from mcp import Client, StdioServerParameters
        from tests.test_mcp import data
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "FORM_CONFIG": str(Path(d) / "none.toml"), "PYTHONPATH": str(ROOT),
                   "FORM_PURPOSE": "model"}
            env.pop(ask.ENV_DIR, None)
            params = StdioServerParameters(command=sys.executable, args=["-m", "form.mcp_server", "--no-bench"], env=env, cwd=str(ROOT))
            async with Client(params) as c:
                tools = {t.name for t in (await c.list_tools()).tools}
                self.assertTrue({"propose_concepts", "pick_concept", "list_concepts", "ask_measurement"} <= tools)
                b = data(await c.call_tool("propose_concepts", {"name": "Mug rest", "concepts": TINY[:2], "run": False}))
                self.assertEqual(len(b["members"]), 2)
                self.assertIn("pick_concept", b["note"])
                pid = b["members"][0]["project"]
                self.assertEqual(json.loads((Path(d) / pid / "project.json").read_text())["purpose"], "model")
                self.assertEqual(data(await c.call_tool("list_concepts", {}))["groups"][0]["id"], b["id"])
                m = data(await c.call_tool("ask_measurement", {"project": pid, "param": "size", "question": "How big?"}))
                self.assertEqual((m["answered"], m["reason"], m["current"]), (False, "no_user", 30.0))
                bad = await c.call_tool("ask_measurement", {"project": pid, "param": "nope", "question": "?"})
                self.assertTrue(bad.is_error)
                r = data(await c.call_tool("pick_concept", {"group": b["id"], "project": pid}))
                self.assertEqual(r["picked"], pid)

    def test_cli_start_blank_and_concepts(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "FORM_DATA": d, "FORM_CONFIG": str(Path(d) / "none.toml"), "PYTHONPATH": str(ROOT)}
            run = lambda *a: subprocess.run([sys.executable, "-m", "form", *a], env=env, cwd=str(ROOT),  # noqa: E731
                                            capture_output=True, text=True, timeout=180)
            r = run("start", "--blank", "--name", "CLI block", "--purpose", "model")
            self.assertEqual(r.returncode, 0, r.stderr)
            got = json.loads(r.stdout)
            self.assertEqual((got["name"], got["purpose"]), ("CLI block", "model"))
            self.assertEqual(json.loads(run("concepts").stdout), {"groups": []})
            with mock.patch.dict(os.environ, {"FORM_DATA": d, "FORM_CONFIG": env["FORM_CONFIG"]}):
                st = Studio(config.load())
                try:
                    b = concepts.create(st, "CLI hook", TINY[:2])
                finally:
                    st.kernel.stop()
            self.assertEqual(json.loads(run("concepts").stdout)["groups"][0]["id"], b["id"])
            board = json.loads(run("concepts", b["members"][1]["project"]).stdout)     # by a member's project
            self.assertEqual(board["id"], b["id"])
            r = json.loads(run("concepts", "pick", b["id"], b["members"][1]["project"], "--keep-others").stdout)
            self.assertEqual((r["picked"], r["trashed"]), (b["members"][1]["project"], []))
            self.assertEqual(run("concepts", "nothing-here").returncode, 2)
            self.assertNotEqual(run("start").returncode, 0)


if __name__ == "__main__":
    unittest.main()
