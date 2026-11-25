"""Failures seen in real conversations, fixed at their cause: a build error that hid its message, an STL rejected for
its label, a valid solid exported with holes, an assembly the render tool could not show, a model the account cannot
use that kept coming back, and a no-op draft shown as a build failure.

Real kernel, temp data folder."""
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="form-chatfail-")

from form import config, kernel  # noqa: E402
from form import render as rendering  # noqa: E402
from form.agents.models import Learned, Recent  # noqa: E402
from form.chat import _model_unavailable  # noqa: E402
from form.design_guide import EXAMPLE  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

BUILD = "    def build(self, v):\n"
BROKEN = EXAMPLE.replace(BUILD, BUILD + "        width = len(v['inner_w'])\n", 1)        # TypeError on a float


def _stl(path: Path, tris) -> None:
    with open(path, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v) for v in t) + b"\0\0")


TETRA = [((0, 0, 0), (0, 10, 0), (10, 0, 0)), ((0, 0, 0), (10, 0, 0), (0, 0, 10)),
         ((0, 0, 0), (0, 0, 10), (0, 10, 0)), ((10, 0, 0), (0, 10, 0), (0, 0, 10))]


class Kernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["FORM_DATA"] = TMP
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def test_build_error_says_what_and_where(self):
        with self.assertRaises(StudioError) as cm:
            self.st.create_design("Broken box", BROKEN)
        msg = str(cm.exception)
        self.assertIn("TypeError", msg)
        self.assertIn("float", msg)                                  # the exception's own text
        self.assertIn("len(v['inner_w'])", msg)                       # and the line of the design it came from

    def test_stl_with_a_label_for_a_name_imports(self):
        p = self.st.create_design("Label import", EXAMPLE)
        src = Path(TMP) / "64e6bd-Sliding-wallet-V1_Slider.stl"
        _stl(src, TETRA)
        rec = self.st.import_reference(p, src, "Original slider")
        self.assertEqual(rec["file"], "Original_slider.stl")
        with self.assertRaises(StudioError):                           # a file that is not a part is still refused
            self.st.import_reference(p, Path(TMP) / "notes.txt", "Notes")

    def test_assembled_and_exploded_render(self):
        p = self.st.create_design("Posed box", EXAMPLE)
        v = self.st.view(p)
        feats = [{"id": f.id, "label": f.label} for f in self.st.recipe(p).features]
        for pose in rendering.POSES:
            posed = rendering.posed(v, pose)
            self.assertIsNone(posed["edges"])
            self.assertTrue(rendering.render_png(posed, feats, "iso").startswith(b"\x89PNG"))
        lid = next(m for m in v["mesh"] if m.get("part") and m["feature"] == "lid")
        moved = next(m for m in rendering.posed(v, "assembled")["mesh"] if m["part"] == lid["part"] and m["feature"] == "lid")
        self.assertNotEqual(lid["positions"], moved["positions"])     # the lid goes from the plate onto the box

    def test_single_part_has_no_assembled_view(self):
        with self.assertRaises(ValueError):
            rendering.posed({"mesh": [], "assembly": None}, "assembled")


class Stl(unittest.TestCase):
    def test_open_edges_counts_holes(self):
        closed, holed = Path(TMP) / "closed.stl", Path(TMP) / "holed.stl"
        _stl(closed, TETRA)
        _stl(holed, TETRA[:3])
        self.assertEqual(kernel._open_edges(closed), 0)
        self.assertEqual(kernel._open_edges(holed), 3)

    def test_write_stl_remeshes_until_closed(self):
        """The mesher's failure on the first setting only: one face gets no triangles. The export ladder meshes again
        finer and the STL is closed; the result says which rung closed it and how far it may be from the CAD."""
        from build123d import Box, Cylinder, Pos
        from form import meshclose
        shape = Box(30, 20, 10) - Pos(0, 0, 2) * Cylinder(6, 10)
        out = Path(TMP) / "part.stl"
        calls = []
        real = meshclose._triangles

        def flaky(s):                         # the first meshing loses one face's triangles
            V, missing = real(s)
            calls.append(1)
            return (V[:-40], missing) if len(calls) == 1 else (V, missing)
        meshclose._triangles = flaky
        try:
            res = kernel.write_stl(shape, out, 0.01, 0.1)
        finally:
            meshclose._triangles = real
        self.assertTrue(res["remeshed"])
        self.assertEqual(res["open_edges"], 0)
        self.assertGreater(res["open_edges_first"], 0)
        self.assertTrue(res["closure"]["closed"])
        self.assertEqual(res["closure"]["rung"], "finer")
        self.assertLessEqual(res["closure"]["deviation_mm"], 0.01)
        self.assertEqual(kernel._open_edges(out), 0)

    def test_an_assembly_export_is_closed_part_by_part(self):
        """Parts that touch in their assembled pose share faces: not a defect. Each solid is meshed and audited on its
        own (the STL's .parts.json sidecar), so two touching boxes are a closed export."""
        from build123d import Box, Compound, Pos
        from form import mesh_audit
        shape = Compound([Box(10, 10, 10), Pos(10, 0, 0) * Box(10, 10, 10)])
        out = Path(TMP) / "pair.stl"
        res = kernel.write_stl(shape, out, 0.01, 0.1)
        self.assertTrue(res["closure"]["closed"], res["closure"])
        self.assertEqual(res["closure"]["solids"], 2)
        tris, _f, _sha = mesh_audit.read_stl(out)
        self.assertEqual(len(tris.parts), 2)
        a = mesh_audit.audit(tris, expected_components=2)
        self.assertEqual(a["status"], "PASS_LIMITED_SCREEN", a["failures"])
        whole = mesh_audit.audit(list(tris), expected_components=2)   # welded as one mesh: the shared face shows
        self.assertIn("nonmanifold_edges", whole["failures"])


class MeshReferences(unittest.TestCase):
    """A design made of imported meshes (thousands of one-triangle faces) builds in seconds, each face credited to
    the stage that added it. It took longer than the kernel's 180 s limit with three ~10k-triangle STLs."""

    def test_many_face_meshes_build_quickly_and_attribute_right(self):
        import time
        from build123d import Pos, Sphere, Compound
        from form.recipes import meshsolid
        from form.recipes.base import Feature, Param, Recipe, Stage

        def mesh_ball(r):
            P, T = kernel._tessellate(Sphere(r), 0.02)
            return meshsolid.solid_from_triangles([tuple(map(tuple, P[i])) for i in T])

        a, b = mesh_ball(10), Pos(40, 0, 0) * mesh_ball(10)
        self.assertGreater(len(a.faces()), 1500)

        class Balls(Recipe):
            title, summary, solids, mesh = "Balls", "Two mesh balls.", 2, True
            params = [Param("x", "x", 1, 0, 2, 1, "mm", "form", "a")]
            features = [Feature("a", "A", "structure"), Feature("b", "B", "structure")]

            def build(self, v):
                return [Stage("a", a), Stage("b", Compound(children=[a, b]))]

        real = kernel.resolve
        kernel.resolve = lambda rid: Balls()
        try:
            t0 = time.perf_counter()
            m = kernel._build("balls", {"x": 1}, 0.05)
            took = time.perf_counter() - t0
        finally:
            kernel.resolve = real
        self.assertLess(took, 30)
        ids = {"a": {hash(f) for f in a.faces()}, "b": {hash(f) for f in b.faces()}}
        self.assertTrue(all(hash(x["face"]) in ids[x["feature"]] for x in m["faces"]))    # every face to its own ball
        self.assertGreater(sum(x["feature"] == "b" for x in m["faces"]), 1500)


class Models(unittest.TestCase):
    def test_unavailable_model_errors_are_recognised(self):
        self.assertTrue(_model_unavailable("The 'gpt-6.2-sol' model is not supported when using Codex with a ChatGPT account."))
        self.assertTrue(_model_unavailable('{"code":"model_not_found"}'))
        self.assertFalse(_model_unavailable("Rate limit reached. Try again in 20 s."))
        self.assertFalse(_model_unavailable("Network is unreachable"))

    def test_forget_and_drop(self):
        d = Path(tempfile.mkdtemp(prefix="form-models-"))
        learned, recent = Learned(d), Recent(d)
        learned.learn("codex", "gpt-6.2-sol", "gpt-6.2-sol")
        learned.learn("codex", "default", "gpt-6.1-sol")
        recent.use("codex", "gpt-6.1-sol", 1)
        recent.use("codex", "gpt-6.2-sol", 2)
        learned.forget("codex", "gpt-6.2-sol")
        recent.drop("codex", "gpt-6.2-sol")
        self.assertIsNone(learned.get("codex", "gpt-6.2-sol"))
        self.assertEqual(learned.get("codex", "default")["id"], "gpt-6.1-sol")
        self.assertEqual(recent.last("codex"), "gpt-6.1-sol")


class DraftCard(unittest.TestCase):
    def test_no_op_commit_is_not_a_build_failure(self):
        qml = (Path(__file__).resolve().parent.parent / "form" / "app" / "qml" / "Form" / "Store.qml").read_text(encoding="utf-8")
        i = qml.index("function commit()")
        self.assertIn('e.message === "Nothing changed."', qml[i:i + 900])


if __name__ == "__main__":
    unittest.main()
