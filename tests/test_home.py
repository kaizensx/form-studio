"""Home and the new-design flow, without a window: learned starters, the recipe library (file and community installs),
project archives with their conversations, conversation export/import, What's New and the update channel."""
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from form import bundle, config, recipe_lib, starters, updates, whatsnew
from form.conversations import Conversations
from form.recipes import store_source
from form.studio import Studio, StudioError

BLOCK = '''from build123d import Box
from form.recipes.base import Feature, Param, Recipe, Stage


class Block(Recipe):
    title = "Test block"
    summary = "A plain block for tests."
    params = [Param("w", "Width", 20, 5, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 10, 5))]
'''
SCAD = "// Title: Washer\n// A flat washer.\nouter = 12; // [4:40]\ndifference() { cylinder(d=outer, h=2); cylinder(d=4, h=5); }\n"
PRESETS = [{"id": "remote-holder", "title": "Remote holder", "summary": "s", "closest_recipe": "dock", "material": {"suggested": "PLA"}},
           {"id": "organizer", "title": "Drawer organizer", "summary": "s", "closest_recipe": "gridfinity", "material": {"suggested": "PLA"}},
           {"id": "enclosure", "title": "Enclosure", "summary": "s", "closest_recipe": "enclosure", "material": {"suggested": "PETG"}}]


def make_studio(tmp):
    os.environ["FORM_DATA"] = str(tmp)
    return Studio(config.load())


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="form-home-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---- learned starters ------------------------------------------------------------------------------------------

class Starters(Tmp):
    NOW = 1_800_000_000.0

    def hist(self, *rows):
        return [{"id": f"p{i}", "name": n, "recipe": k, "kind": k, "preset": pr, "brief": b, "updated": self.NOW - age * 86400}
                for i, (n, k, pr, b, age) in enumerate(rows)]

    def test_a_new_folder_gets_the_defaults_in_order(self):
        out = starters.listing(self.tmp, [], PRESETS, now=self.NOW)
        self.assertFalse(out["history"])
        self.assertEqual([p["id"] for p in out["prompts"][:3]], ["d-gearbox", "d-pi5-case", "d-grip"])
        self.assertTrue(all(p["source"] == "suggested" for p in out["prompts"]))
        self.assertEqual([b["preset"] for b in out["briefs"]], ["remote-holder", "organizer", "enclosure"])

    def test_history_replaces_unrelated_defaults_with_learned_starters(self):
        h = self.hist(("Bravo bin", "gridfinity", "organizer", "", 1), ("Tool bin", "gridfinity", "", "", 3),
                      ("Desk dock", "dock", "", "A dock for my Pixel 8 on the desk, cable from the back", 2))
        out = starters.listing(self.tmp, h, PRESETS, {"gridfinity": "Gridfinity-style bin", "dock": "Device dock"},
                               {"printer": "Bambu Lab A1 mini", "material": "PETG"}, now=self.NOW)
        texts = [p["text"] for p in out["prompts"]]
        self.assertTrue(out["history"])
        self.assertIn("Another gridfinity-style bin like “Bravo bin”, in PETG for the Bambu Lab A1 mini", texts)
        self.assertIn("A dock for my Pixel 8 on the desk, cable from the back", texts)          # a recent brief
        ids = [p["id"] for p in out["prompts"]]
        self.assertIn("d-gridfinity", ids)                       # a default that matches what they make stays
        self.assertNotIn("d-hook", ids)                          # one that does not, goes
        self.assertNotIn("d-vase", ids)
        self.assertLess(ids.index(next(i for i in ids if i.startswith("l-kind-"))), ids.index("d-gridfinity"))
        self.assertEqual(out["briefs"][0]["preset"], "organizer")  # the template they used ranks first
        self.assertEqual(out["briefs"][0]["source"], "learned")
        rel = {b["preset"]: b["source"] for b in out["briefs"]}
        self.assertEqual(rel["remote-holder"], "related")         # a template close to what they make, not used yet

    def test_newer_designs_weigh_more(self):
        h = self.hist(("Old hook", "hook", "", "", 400), ("New knob", "knob", "", "", 0))
        kinds, _ = starters.affinity(h, self.NOW)
        self.assertGreater(kinds["knob"], kinds["hook"])
        self.assertGreaterEqual(kinds["hook"], 0.25)

    def test_pin_remove_edit_add_restore(self):
        root = self.tmp
        starters.pin(root, "d-hook")
        out = starters.listing(root, [], PRESETS, now=self.NOW)["prompts"]
        self.assertEqual(out[0]["id"], "d-hook")
        self.assertTrue(out[0]["pinned"])
        self.assertEqual(starters.remove(root, "d-pi5-case")["how"], "hidden")
        self.assertNotIn("d-pi5-case", [p["id"] for p in starters.listing(root, [], PRESETS, now=self.NOW)["prompts"]])
        mine = starters.add(root, "  A cable clip   for 6 mm cords ")
        self.assertEqual(mine["text"], "A cable clip for 6 mm cords")
        self.assertEqual(starters.add(root, "a cable clip for 6 mm cords")["id"], mine["id"])     # no duplicates
        ed = starters.edit(root, "d-hook", "The lightest wall hook that holds 8 kg")
        out = starters.listing(root, [], PRESETS, now=self.NOW)["prompts"]
        self.assertEqual(out[0]["id"], ed["id"])                 # the pin moves to your version
        self.assertNotIn("d-hook", [p["id"] for p in out])
        self.assertEqual(out[1]["text"], "A cable clip for 6 mm cords")      # yours rank above suggestions
        self.assertEqual(starters.remove(root, mine["id"])["how"], "deleted")
        self.assertEqual(starters.restore(root)["restored"], 2)
        self.assertIn("d-pi5-case", [p["id"] for p in starters.listing(root, [], PRESETS, now=self.NOW)["prompts"]])
        with self.assertRaises(starters.StarterError):
            starters.pin(root, "nope")
        with self.assertRaises(starters.StarterError):
            starters.add(root, "   ")
        self.assertTrue((root / starters.FILE).is_file())

    def test_use_counts_rank_a_starter_up(self):
        for _ in range(3):
            starters.used(self.tmp, "d-vase")
        out = starters.listing(self.tmp, [], PRESETS, now=time.time())["prompts"]
        self.assertEqual(out[0]["id"], "d-vase")

    def test_a_filled_brief_saved_as_a_template(self):
        t = starters.save_template(self.tmp, "remote-holder", {"width": "48", "thickness": "21", "mounting": "Screws", "nope": "x"},
                                   "Living-room remote")
        self.assertEqual(t["answers"], {"width": "48", "thickness": "21", "mounting": "Screws"})
        b = starters.listing(self.tmp, [], PRESETS, now=self.NOW)["briefs"]
        self.assertEqual(b[0]["id"], t["id"])
        self.assertEqual((b[0]["kind"], b[0]["source"], b[0]["title"]), ("template", "mine", "Living-room remote"))
        with self.assertRaises(starters.StarterError):
            starters.save_template(self.tmp, "remote-holder", {"mounting": "Glue"})
        with self.assertRaises(starters.StarterError):
            starters.save_template(self.tmp, "remote-holder", {})
        starters.remove(self.tmp, t["id"])
        self.assertNotIn(t["id"], [x["id"] for x in starters.listing(self.tmp, [], PRESETS)["briefs"]])

    def test_material_from_a_filament_name(self):
        self.assertEqual(starters.material_of("Bambu PLA Basic @BBL A1M"), "PLA")
        self.assertEqual(starters.material_of("Generic PETG HF"), "PETG")
        self.assertEqual(starters.material_of("Something"), "")

    def test_history_from_a_studio(self):
        st = make_studio(self.tmp)
        st.create("Hall hook", "hook", "A hook by the door for a 3 kg bag")
        h = starters.history(st)
        self.assertEqual((h[0]["kind"], h[0]["brief"]), ("hook", "A hook by the door for a 3 kg bag"))


# ---- recipe library ---------------------------------------------------------------------------------------------

class Library(Tmp):
    def test_inspect_reads_without_running(self):
        evil = BLOCK + "\nraise SystemExit('this must never run')\n"
        info = recipe_lib.inspect(evil.encode(), "block.py")
        self.assertEqual((info["kind"], info["title"], info["params"], info["problems"]), ("python", "Test block", 1, []))
        self.assertEqual(info["sha256"], hashlib.sha256(evil.encode()).hexdigest())
        bad = recipe_lib.inspect(b"def x(:\n", "x.py")
        self.assertIn("syntax", bad["problems"][0])
        none = recipe_lib.inspect(b"print('hi')\n", "x.py")
        self.assertIn("exactly one subclass", none["problems"][0])
        s = recipe_lib.inspect(SCAD.encode(), "washer.scad")
        self.assertEqual(s["kind"], "scad")
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.inspect(b"x", "x.stl")
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.inspect(b"#" * (recipe_lib.MAX_SOURCE + 1), "big.py")

    def test_install_needs_the_hash_that_was_shown_and_uninstall_removes_it(self):
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.install(self.tmp, BLOCK, "python", "0" * 64)
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.install(self.tmp, "print(1)\n", "python", recipe_lib.sha256("print(1)\n"))
        m = recipe_lib.install(self.tmp, BLOCK, "python", recipe_lib.sha256(BLOCK))
        self.assertEqual((m["id"], m["section"], m["title"]), ("test-block", "mine", "Test block"))
        self.assertEqual(recipe_lib.install(self.tmp, BLOCK, "python", recipe_lib.sha256(BLOCK))["id"], "test-block")   # same file once
        self.assertEqual([x["id"] for x in recipe_lib.mine(self.tmp)], ["test-block"])
        self.assertEqual(recipe_lib.source(self.tmp, "test-block")["source"], BLOCK)
        recipe_lib.uninstall(self.tmp, "test-block")
        self.assertEqual(recipe_lib.mine(self.tmp), [])
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.uninstall(self.tmp, "../etc")

    def index(self, *entries):
        return json.dumps({"version": 1, "generated": "2026-11-17T00:00:00Z", "recipes": list(entries)}).encode()

    def opener(self, files):
        calls = []

        def op(url, timeout):
            calls.append(url)
            v = files.get(url)
            if isinstance(v, Exception):
                raise v
            if v is None:
                raise OSError("404")
            return v
        op.calls = calls
        return op

    def test_community_preview_then_install_verifies_the_checksum(self):
        url = "https://raw.githubusercontent.com/x/y/main/block.py"
        sha = hashlib.sha256(BLOCK.encode()).hexdigest()
        op = self.opener({recipe_lib.INDEX_URL: self.index(
            {"id": "block", "title": "Block", "summary": "A block", "author": "ann", "tags": ["test"], "kind": "python",
             "builtin": False, "url": url, "sha256": sha, "preview": None},
            {"id": "dock", "title": "Device dock", "kind": "python", "builtin": True, "url": None, "sha256": None},
            {"title": "no id"}), url: BLOCK.encode()})
        com = recipe_lib.community(self.tmp, opener=op)
        self.assertEqual([r["id"] for r in com["recipes"]], ["block", "dock"])
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.install_community(self.tmp, "block", sha, opener=op)     # not reviewed yet
        pv = recipe_lib.community_preview(self.tmp, "block", opener=op)
        self.assertEqual((pv["sha256"], pv["verified"], pv["source"]), (sha, True, BLOCK))
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.install_community(self.tmp, "block", "f" * 64, opener=op)
        m = recipe_lib.install_community(self.tmp, "block", sha, opener=op)
        self.assertEqual((m["origin"], m["community_id"], m["author"]), ("community", "block", "ann"))
        lib = recipe_lib.everything(self.tmp, {}, opener=op)
        com_rows = {i["id"]: i for i in lib["items"] if i["section"] == "community"}
        self.assertTrue(com_rows["block"]["installed"])
        self.assertTrue(com_rows["dock"]["installed"])          # built in
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib.community_preview(self.tmp, "dock", opener=op)

    def test_a_tampered_download_is_refused(self):
        url = "https://example.org/block.py"
        op = self.opener({recipe_lib.INDEX_URL: self.index({"id": "block", "title": "Block", "kind": "python", "url": url,
                                                            "sha256": "a" * 64}), url: BLOCK.encode()})
        with self.assertRaises(recipe_lib.LibraryError) as cm:
            recipe_lib.community_preview(self.tmp, "block", opener=op)
        self.assertIn("does not match", str(cm.exception))
        self.assertEqual(recipe_lib.mine(self.tmp), [])

    def test_an_unreachable_empty_or_strange_index_is_an_empty_list(self):
        for files in ({}, {recipe_lib.INDEX_URL: self.index()}, {recipe_lib.INDEX_URL: b"<html>"},
                      {recipe_lib.INDEX_URL: json.dumps({"version": 9, "recipes": []}).encode()}):
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp.mkdir()
            com = recipe_lib.community(self.tmp, opener=self.opener(files))
            self.assertEqual(com["recipes"], [])
        self.assertTrue(com["error"])

    def test_browsing_never_waits_for_the_network(self):
        def boom(url, timeout):
            raise AssertionError("the network was used")
        lib = recipe_lib.everything(self.tmp, {}, opener=boom, online=False)
        self.assertEqual(lib["items"], [])

    def test_a_local_index_for_development(self):
        fx = Path(__file__).resolve().parent / "fixtures" / "community" / "index.json"
        os.environ["FORM_RECIPES_INDEX"] = str(fx)
        try:
            com = recipe_lib.community(self.tmp)
            self.assertEqual([r["id"] for r in com["recipes"]], ["cable-clip", "dock"])
            pv = recipe_lib.community_preview(self.tmp, "cable-clip")
            self.assertTrue(pv["verified"])
            self.assertEqual(recipe_lib.install_community(self.tmp, "cable-clip", pv["sha256"])["title"], "Cable clip")
        finally:
            del os.environ["FORM_RECIPES_INDEX"]
        self.assertIsNone(recipe_lib._norm({"id": "x", "title": "X", "url": "file:x.py"})["url"])   # only with the variable

    def test_http_urls_are_never_read(self):
        with self.assertRaises(recipe_lib.LibraryError):
            recipe_lib._download("http://example.org/x.py", 10, opener=lambda u, t: b"")

    def test_search_sections_tags_and_sort(self):
        from form.recipes import registry
        items = recipe_lib.builtins(registry())
        self.assertNotIn("dock", [i["id"] for i in items])         # legacy recipes build, but are not listed
        recipe_lib.install(self.tmp, BLOCK, "python", recipe_lib.sha256(BLOCK), {"tags": ["test"]})
        items += recipe_lib.mine(self.tmp)
        self.assertEqual([i["id"] for i in recipe_lib.search(items, "skadis")], ["pegboard"])
        self.assertEqual([i["id"] for i in recipe_lib.search(items, section="mine")], ["test-block"])
        self.assertEqual({i["id"] for i in recipe_lib.search(items, tag="Wall & desk")}, {"pegboard", "cable_organizer", "desk_hanger", "shelf_bracket"})
        self.assertEqual(recipe_lib.search(items)[0]["section"], "builtin")
        self.assertEqual(recipe_lib.search(items, sort="recent")[0]["id"], "test-block")
        self.assertIn({"tag": "storage", "count": 4}, recipe_lib.tags(items))

    def test_a_design_from_an_installed_recipe(self):
        st = make_studio(self.tmp)
        recipe_lib.install(st.root, BLOCK, "python", recipe_lib.sha256(BLOCK))
        try:
            p = recipe_lib.create_from(st, "test-block", "My block")
            self.assertTrue(p["recipe"].startswith("src:"))
            self.assertEqual(p["name"], "My block")
        finally:
            st.kernel.stop()


# ---- archives and conversations ----------------------------------------------------------------------------------

class Archives(Tmp):
    def setUp(self):
        super().setUp()
        self.st = make_studio(self.tmp / "a")

    def project_with_conversation(self):
        st = self.st
        rid = store_source(st.sources, BLOCK)
        st.recipes[rid]                                                    # loads the design code, as create_design does
        p = st.create("Shelf block", rid, "A block for the shelf")
        store = Conversations(st.root)
        c = store.create(p["id"], "claude", "default", "")
        store.append(c["id"], {"t": "user", "text": "Make it 30 mm wide"})
        store.append(c["id"], {"t": "tool", "id": "t1", "name": "preview_change", "input": {}})
        store.append(c["id"], {"t": "text", "text": "Previewed **30 mm**."})
        store.append(c["id"], {"t": "end", "cost_usd": 0.02})
        store.attach(c["id"], name="photo.png", data=b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        other = store.create(None, "claude", "default", "")              # not about this design: not exported
        return p, c, other

    def test_round_trip_with_conversations_and_design_code(self):
        p, c, other = self.project_with_conversation()
        f = bundle.export_project(self.st, p["id"], self.tmp / "out" / "shelf.formstudio")
        names = zipfile.ZipFile(f).namelist()
        self.assertIn("manifest.json", names)
        self.assertIn("project/project.json", names)
        self.assertTrue(any(n.startswith("sources/") and n.endswith(".py") for n in names))
        self.assertIn(f"conversations/{c['id']}/events.jsonl", names)
        self.assertNotIn(f"conversations/{other['id']}/meta.json", names)

        st2 = make_studio(self.tmp / "b")                                  # another computer: empty data folder
        res = bundle.import_bytes(st2, f.read_bytes())
        self.assertEqual((res["id"], res["renamed_from"]), (p["id"], None))
        q = st2.load(res["id"])
        self.assertEqual(q["recipe"], p["recipe"])
        self.assertEqual(st2.recipes[p["recipe"]].title, "Test block")      # the design code came along
        convs = Conversations(st2.root).list(project=res["id"])
        self.assertEqual(len(convs), 1)
        ev = Conversations(st2.root).events(convs[0]["id"])
        self.assertEqual([e["t"] for e in ev], ["user", "tool", "text", "end"])
        self.assertTrue((Conversations(st2.root).dir(convs[0]["id"]) / "files").is_dir())

        res2 = bundle.import_bytes(st2, f.read_bytes())                   # again: everything gets new ids
        self.assertEqual(res2["renamed_from"], p["id"])
        self.assertNotEqual(res2["id"], p["id"])
        self.assertEqual(len(Conversations(st2.root).list(project=res2["id"])), 1)
        self.assertNotEqual(res2["conversations"][0]["id"], res["conversations"][0]["id"])
        self.assertEqual(len(Conversations(st2.root).list(project=res["id"])), 1)   # the first import is untouched

    def zip_with(self, extra: dict, manifest=None, drop=()):
        p, _, _ = self.project_with_conversation()
        src = zipfile.ZipFile(bundle.export_project(self.st, p["id"]))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in src.namelist():
                if n in drop:
                    continue
                z.writestr(n, json.dumps(manifest) if (n == "manifest.json" and manifest is not None) else src.read(n))
            for n, data in extra.items():
                z.writestr(n, data)
        return buf.getvalue()

    def test_unsafe_or_wrong_archives_are_refused_before_anything_is_written(self):
        st2 = make_studio(self.tmp / "c")
        cases = [{"project/../../evil.txt": b"x"}, {"/abs.txt": b"x"}] + ([{"project\\x.txt": b"x"}] if os.sep == "/" else []) + [
                 {"sources/0123456789abcdef.py": b"print('not matching')"}, {"conversations/zz/meta.json": b"{}"},
                 {"conversations/0123456789ab/../x": b""}]
        for extra in cases:
            with self.assertRaises(bundle.BundleError, msg=str(extra)):
                bundle.import_bytes(st2, self.zip_with(extra))
        with self.assertRaises(bundle.BundleError):
            bundle.import_bytes(st2, self.zip_with({}, manifest={"format": "something-else"}))
        with self.assertRaises(bundle.BundleError):
            bundle.import_bytes(st2, b"not a zip")
        with self.assertRaises(bundle.BundleError):                        # code is missing for a revision
            bundle.import_bytes(st2, self.zip_with({}, drop=[n for n in zipfile.ZipFile(io.BytesIO(self.zip_with({}))).namelist() if n.startswith("sources/")]))
        self.assertEqual(st2.list(), [])
        self.assertFalse((st2.root / ".conversations").exists() and any((st2.root / ".conversations").iterdir()))

    def test_a_link_in_the_archive_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": bundle.FORMAT}))
            info = zipfile.ZipInfo("project/link")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
        with self.assertRaises(bundle.BundleError):
            bundle.import_bytes(self.st, buf.getvalue())

    def test_an_older_formproj_still_imports(self):
        p = self.st.create("Old hook", "hook", "")
        f = self.st.export_archive(p)
        res = bundle.import_bytes(make_studio(self.tmp / "d"), f.read_bytes())
        self.assertEqual((res["format"], res["name"]), ("formproj", "Old hook"))

    def test_conversation_markdown_and_json_round_trip(self):
        p, c, _ = self.project_with_conversation()
        md = bundle.conversation_markdown(self.st.root, c["id"])
        self.assertIn("## You", md)
        self.assertIn("Make it 30 mm wide", md)
        self.assertIn("Previewed **30 mm**.", md)
        self.assertIn("_1 tool call_", md)
        doc = bundle.conversation_json(self.st.root, c["id"])
        self.assertEqual(doc["format"], bundle.CONV_FORMAT)
        m = bundle.import_conversation(self.st, json.loads(json.dumps(doc)))
        self.assertNotEqual(m["id"], c["id"])
        self.assertEqual((m["project"], m["messages"]), (p["id"], 1))
        elsewhere = make_studio(self.tmp / "e")
        m2 = bundle.import_conversation(elsewhere, doc)
        self.assertIsNone(m2["project"])
        self.assertEqual(m2["project_was"]["id"], p["id"])
        with self.assertRaises(bundle.BundleError):
            bundle.import_conversation(self.st, {"format": "x"})

    def test_conversation_export_carries_thread_ancestry(self):
        p, c, _ = self.project_with_conversation()
        store = Conversations(self.st.root)
        store.rename(c["id"], "Shelf block")
        b1 = store.fork(c["id"], at_event=2, reason="try a wider one")
        store.rename(b1["id"], "Wider block")
        b2 = store.fork(b1["id"], reason="rounded")
        root = bundle.conversation_json(self.st.root, c["id"])["ancestry"]
        self.assertEqual((root["thread"], root["parent"], root["ancestors"], root["conversations"]), (c["id"], None, [], 3))
        self.assertEqual([(r["id"], r["fork_event"], r["fork_reason"]) for r in root["branches"]], [(b1["id"], 2, "try a wider one")])
        leaf = bundle.conversation_json(self.st.root, b2["id"])["ancestry"]
        self.assertEqual([r["id"] for r in leaf["ancestors"]], [c["id"], b1["id"]])          # the root first
        self.assertEqual((leaf["parent"], leaf["fork_event"], leaf["fork_reason"], leaf["branches"]), (b1["id"], 2, "rounded", []))
        self.assertEqual(leaf["ancestors"][1]["fork_event"], 2)
        md = bundle.conversation_markdown(self.st.root, b2["id"])
        self.assertIn(f"- Started as “Shelf block” (`{c['id']}`)", md)
        self.assertIn(f"- Branched into “Wider block” (`{b1['id']}`) after event 3 (try a wider one)", md)
        self.assertIn("- This conversation branched from “Wider block” after event 3 (rounded)", md)
        self.assertIn(f"- Branch from here: “Wider block” (`{b1['id']}`) after event 3 (try a wider one)",
                      bundle.conversation_markdown(self.st.root, c["id"]))
        self.assertNotIn("**Thread**", bundle.conversation_markdown(self.st.root, self.project_with_conversation()[1]["id"]))
        store.delete(b1["id"])                               # a deleted parent is still named, and ends the chain
        gone = bundle.conversation_json(self.st.root, b2["id"])["ancestry"]["ancestors"]
        self.assertEqual([(r["id"], r.get("missing")) for r in gone], [(b1["id"], True)])
        m = bundle.import_conversation(self.st, bundle.conversation_json(self.st.root, b2["id"]))   # still imports
        self.assertEqual(m["messages"], 1)


# ---- What's New and the update channel ----------------------------------------------------------------------------

CHANGELOG = """# Changelog

## 12.0.0

### Home
- **Learned starters.** Home suggests what you make.
- **What's New** after every update.
- A plain line.

## 11.1.1

- **Older.** Fix.
"""


class WhatsNew(Tmp):
    def setUp(self):
        super().setUp()
        self.cl = self.tmp / "CHANGELOG.md"
        self.cl.write_text(CHANGELOG, encoding="utf-8")

    def test_sections_and_highlights(self):
        sec = whatsnew.sections(CHANGELOG)
        self.assertEqual(list(sec), ["12.0.0", "11.1.1"])
        hl = whatsnew.highlights(sec["12.0.0"])
        self.assertEqual(hl[0], {"title": "Learned starters", "text": "Home suggests what you make.", "group": "Home"})
        self.assertEqual(len(hl), 2)

    def test_a_dev_build_shows_what_is_unreleased(self):
        cl = self.tmp / "CHANGELOG-dev.md"
        cl.write_text("# Changelog\n\n## Unreleased\n\n- **Lighter.** Thinner walls.\n\n" + CHANGELOG.split("\n", 1)[1], encoding="utf-8")
        self.assertEqual(list(whatsnew.sections(cl.read_text(encoding="utf-8")))[0], "Unreleased")
        n = whatsnew.notes("1.1.0-dev", cl)
        self.assertTrue(n["found"])
        self.assertEqual(n["highlights"][0]["title"], "Lighter")
        self.assertFalse(whatsnew.notes("1.1.0", cl)["found"])       # a release never shows the Unreleased notes

    def test_only_the_summary_above_details(self):
        cl = self.tmp / "CHANGELOG-sum.md"
        cl.write_text("# Changelog\n\n## Unreleased\n\n### New\n\n- **Lighter.** Thinner walls.\n\n### Details\n\n"
                      "- **Wall code.** Every detail.\n\n" + CHANGELOG.split("\n", 1)[1], encoding="utf-8")
        for v in ("1.1.0-dev", "1.1.0-preview.1"):
            n = whatsnew.notes(v, cl)
            self.assertIn("Lighter", n["markdown"])
            self.assertNotIn("Wall code", n["markdown"])
            self.assertNotIn("Details", n["markdown"])
            self.assertEqual([h["title"] for h in n["highlights"]], ["Lighter"])
        real = whatsnew.notes("1.1.0-preview.1")                         # the bundled changelog's 1.1 summary
        self.assertIn("Known limits", real["markdown"])
        self.assertLess(len(real["markdown"]), 20_000)

    def test_shown_once_per_version(self):
        root = self.tmp / "data"
        self.assertFalse(whatsnew.due(root, "12.0.0", first_run=True, path=self.cl)["show"])       # a new folder: silent
        self.assertFalse(whatsnew.due(root, "12.0.0", path=self.cl)["show"])
        d = whatsnew.due(root, "13.0.0", path=self.cl)
        self.assertFalse(d["show"])                                         # no notes for that version: nothing to show
        whatsnew.seen(root, "11.1.1")
        d = whatsnew.due(root, "12.0.0", path=self.cl)
        self.assertTrue(d["show"])
        self.assertEqual(d["last"], "11.1.1")
        whatsnew.seen(root, "12.0.0")
        self.assertFalse(whatsnew.due(root, "12.0.0", path=self.cl)["show"])

    def test_upgraded_from_before_the_feature(self):
        root = self.tmp / "old"
        self.assertTrue(whatsnew.due(root, "12.0.0", setup_version="11.1.1", path=self.cl)["show"])
        self.assertFalse(whatsnew.due(self.tmp / "t", "12.0.0", setup_version="test", path=self.cl)["show"])

    def test_the_bundled_changelog_has_the_running_version(self):
        from form import __version__
        self.assertIsNotNone(whatsnew.changelog_path())
        self.assertTrue(whatsnew.notes(__version__)["found"])
        spec = (Path(__file__).resolve().parents[1] / "packaging" / "form.spec").read_text(encoding="utf-8")
        self.assertIn('"CHANGELOG.md"', spec)


class Channel(unittest.TestCase):
    REL = [{"tag_name": "v11.2.0-rc.1", "prerelease": True}, {"tag_name": "v11.1.1", "prerelease": False},
           {"tag_name": "v12.0.0", "draft": True}, {"tag_name": "v11.1.0"}]

    def test_stable_never_offers_a_prerelease(self):
        self.assertEqual(updates.pick(self.REL, "stable")["tag_name"], "v11.1.1")
        self.assertEqual(updates.pick(self.REL, "preview")["tag_name"], "v11.2.0-rc.1")
        self.assertIsNone(updates.pick([], "preview"))

    def test_channel_setting(self):
        self.assertEqual(updates.channel({}), "stable")
        self.assertEqual(updates.channel({"updates": {"channel": "Preview"}}), "preview")
        self.assertEqual(updates.channel({"updates": {"channel": "nightly"}}), "stable")
        from form import config_edit
        self.assertEqual(config_edit.SCHEMA["updates.channel"]["choices"], ["stable", "preview"])

    def test_the_cache_follows_the_channel(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / updates.CACHE).write_text(json.dumps({"checked": time.time(), "channel": "stable",
                                                          "latest": {"version": "11.1.1"}}), encoding="utf-8")
            seen = []
            orig = updates._fetch
            updates._fetch = lambda chan="stable": seen.append(chan) or {"version": "99.0.0rc1", "prerelease": True}
            env = os.environ.pop("FORM_NO_UPDATE_CHECK", None), os.environ.pop("FORM_FAKE_LATEST", None)
            try:
                a = updates.check({"updates": {"check": True, "channel": "stable"}}, data_dir=str(tmp))
                b = updates.check({"updates": {"check": True, "channel": "preview"}}, data_dir=str(tmp))
            finally:
                updates._fetch = orig
                if env[0] is not None:
                    os.environ["FORM_NO_UPDATE_CHECK"] = env[0]
                if env[1] is not None:
                    os.environ["FORM_FAKE_LATEST"] = env[1]
            self.assertEqual(seen, ["preview"])                  # stable was cached; preview asked GitHub
            self.assertEqual((a["channel"], b["channel"]), ("stable", "preview"))
            self.assertTrue(b["available"] and b["prerelease"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---- the HTTP routes the app uses ----------------------------------------------------------------------------------

class Routes(Tmp):
    def test_starters_library_archive_and_whatsnew_over_http(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from form.server import make_handler
        st = make_studio(self.tmp)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}/api"

        def call(path, body=None, raw=None):
            data, h = (raw, {"Content-Type": "application/octet-stream"}) if raw is not None else \
                ((json.dumps(body).encode(), {"Content-Type": "application/json"}) if body is not None else (None, {}))
            try:
                with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers={**h, "Connection": "close"}), timeout=60) as r:
                    payload = r.read()
                    return json.loads(payload) if r.headers.get("Content-Type", "").startswith("application/json") else payload
            except urllib.error.HTTPError as e:
                return json.loads(e.read())
        try:
            s = call("/starters")
            self.assertEqual(s["prompts"][0]["id"], "d-gearbox")
            self.assertEqual(call("/starters/pin", {"id": "d-hook", "on": True})["pinned"], True)
            self.assertEqual(call("/starters")["prompts"][0]["id"], "d-hook")
            self.assertIn("error", call("/starters/pin", {"id": "zzz"}))
            info = call("/recipes/inspect?name=block.py", raw=BLOCK.encode())
            self.assertEqual(info["title"], "Test block")
            m = call("/recipes/install", {"source": info["source"], "kind": "python", "sha256": info["sha256"]})
            self.assertEqual(m["id"], "test-block")
            lib = call("/recipes/library?section=mine")
            self.assertEqual([i["id"] for i in lib["items"]], ["test-block"])
            p = st.create("Wall hook", "hook", "")
            data = call(f"/archive/{p['id']}.formstudio")
            self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
            self.assertFalse((st.root / f"{p['id']}.formstudio").exists())
            res = call("/archive/import?name=x.formstudio", raw=data)
            self.assertEqual(res["renamed_from"], p["id"])
            self.assertIn("show", call("/whatsnew"))
            self.assertEqual(call("/whatsnew/seen", {"version": "1.0.0"})["seen"], "1.0.0")
        finally:
            httpd.shutdown()
            st.kernel.stop()


if __name__ == "__main__":
    unittest.main()


class RecipePreviews(Tmp):
    def test_a_built_in_preview_is_built_once_and_then_read_from_disk(self):
        from unittest import mock
        from form import home_api
        self.st = make_studio(self.tmp)
        built = []

        def fake_k(op, **kw):
            built.append(kw["recipe_id"])
            return {"positions": "AAAA", "recipe": kw["recipe_id"]}
        with mock.patch.object(self.st, "_k", side_effect=fake_k):
            v = home_api.recipe_view(self.st, "shelf_bracket")
        self.assertEqual((built, v["companions"]), (["shelf_bracket"], []))
        self.assertEqual(len(list((self.st.root / ".cache" / "recipe-views").glob("*.json"))), 1)
        st2 = make_studio(self.tmp)                          # a new start of the app: nothing in memory
        with mock.patch.object(st2, "_k", side_effect=AssertionError("built again")):
            self.assertEqual(home_api.recipe_view(st2, "shelf_bracket")["recipe"], "shelf_bracket")
        with self.assertRaises(StudioError):
            home_api.recipe_view(st2, "not-a-recipe")
        with self.assertRaises(StudioError):                 # a legacy recipe builds for its designs, but has no library preview
            home_api.recipe_view(st2, "hook")
