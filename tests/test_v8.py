"""v8: designs written as code, multi-part, document reading, chat stream parsing. Real kernel, temp data folder."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

TMP = tempfile.mkdtemp(prefix="form-v8-")

from form import chat, config, documents  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402


class Designs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_example_builds_two_parts_and_pipeline_runs(self):
        p = self.st.create_design("Box", EXAMPLE)
        job = self.st.run_sync(p["id"], ["geometry", "exports", "checks"])
        self.assertEqual(job["state"], "done", job)
        ch = self.st.read(p, "checks", self.st.keys(p)["checks"])
        solid = next(c for c in ch["checks"] if c["id"] == "solid")
        self.assertEqual((solid["status"], solid["label"]), ("PASS", "2 valid parts"))

    def test_update_keeps_history_and_values(self):
        p = self.st.create_design("Box2", EXAMPLE, values={"inner_w": 70})
        src = EXAMPLE.replace('Param("wall", "Wall", 2.0,', 'Param("wall", "Wall", 2.5,') + "\n# v2\n"
        p = self.st.update_design(self.st.load(p["id"]), src, "thicker default wall")
        self.assertEqual(p["head"], 2)
        self.assertNotEqual(self.st.rid(p, 1), self.st.rid(p, 2))
        self.assertEqual(self.st.rev(p)["values"]["inner_w"], 70)          # saved values survive a code change
        self.assertIn("# v2", self.st.source_text(p))
        self.assertNotIn("# v2", self.st.source_text(p, 1))
        p = self.st.checkout(p, 1)
        self.assertEqual(p["recipe"], self.st.rid(p, 1))

    def test_bad_source_is_a_clear_error(self):
        with self.assertRaises(StudioError) as cm:
            self.st.create_design("Bad", "from form.recipes.base import Recipe\nx = (")
        self.assertIn("line", str(cm.exception))
        with self.assertRaises(StudioError):
            self.st.create_design("NoClass", "x = 1\n")
        with self.assertRaises(StudioError):                                  # declares 1 part, builds 2
            self.st.create_design("Parts", EXAMPLE.replace("solids = 2", "solids = 1"))

    def test_declared_provenance(self):
        src = EXAMPLE.replace('Param("inner_w", "Inner width", 60, 20, 150, 0.5, "mm", "brief", "body", "What it must hold."),',
                              'Param("inner_w", "Inner width", 60, 20, 150, 0.5, "mm", "brief", "body", "Vendor drawing", "specified"),')
        p = self.st.create_design("Prov", src)
        self.assertEqual(self.st.rev(p)["provenance"]["inner_w"]["source"], "specified")
        self.assertEqual(self.st.rev(p)["provenance"]["wall"]["source"], "assumed")


class Documents(unittest.TestCase):
    def test_pdf_pages_render_as_images(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "drawing.pdf"
            Image.new("RGB", (600, 400), (255, 255, 255)).save(pdf)
            f = documents.fetch(str(pdf), Path(d) / "store")
            r = documents.render(f, "1")
            self.assertEqual((r["page_count"], len(r["images"])), (1, 1))
            self.assertEqual(Image.open(__import__("io").BytesIO(r["images"][0])).format, "PNG")
            with self.assertRaises(ValueError):
                documents.fetch("http://example.com/x.pdf", Path(d))          # https only


class ChatStream(unittest.TestCase):
    def test_events_and_live_progress(self):
        c = chat.Chat({"chat": {}, "_path": "/nonexistent"}, Path(TMP), "/bin/false")
        j = chat.ChatJob("hi", None, None)
        lines = [
            {"type": "system", "subtype": "init", "session_id": "s1", "model": "opus"},
            {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "mcp__form__create_design"}}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "x" * 1200}}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__form__create_design",
                                                           "input": {"name": "Case", "source": "a\nb\nc"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "ok"}]}]}},
            {"type": "result", "total_cost_usd": 0.5, "num_turns": 3, "session_id": "s1"},
        ]
        for i, e in enumerate(lines):
            c._event(j, json.dumps(e))
            if i == 2:
                self.assertEqual((j.live["name"], j.live["chars"]), ("create_design", 1200))
        kinds = [e["t"] for e in j.events]
        self.assertEqual(kinds, ["user", "start", "tool", "result", "end"])
        self.assertEqual(j.session, "s1")
        self.assertIn("source=<3 lines>", j.events[2]["input"])


if __name__ == "__main__":
    unittest.main()
