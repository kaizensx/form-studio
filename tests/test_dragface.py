"""Drag a face, change the parameter that drives it (form/dragface.py, WP-F). Ten fixture designs: the face under a
known ray and the parameter a designer means when they pull it. Acceptance: right on at least 8 of 10."""
import unittest

from build123d import extrude

from form import dragface
from form.recipes import registry
from form.recipes.base import Param, Recipe, Stage
from form.sketch2d import fixtures as sk


class SketchBracket(Recipe):
    """An L bracket from a constrained sketch (form.sketch2d): its legs are dimensions of the sketch."""
    id = "sketch_bracket"
    S = sk.l_bracket()
    params = S.params(feature="bracket") + [Param("depth", "Depth", 24, 8, 80, 1, "mm", "form", "bracket")]

    def build(self, v):
        return [Stage("bracket", extrude(self.S.face(v), v["depth"]))]


def c(bb):
    return ((bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2)


def cases():
    R = registry()
    from form import exemplars
    return [
        ("storage box top", R["storage_box"], lambda bb: (-41.2, 7, 60), (0, 0, -1), {"inner_h"}),
        ("coupon top", R["coupon"], lambda bb: (bb.min.X + 2, c(bb)[1], bb.max.Z + 10), (0, 0, -1), {"height"}),
        ("enclosure side", R["enclosure"], lambda bb: (bb.min.X - 10, 0, 12), (1, 0, 0), {"inner_w"}),
        ("desk hanger jaw", R["desk_hanger"], lambda bb: (c(bb)[0], bb.max.Y + 10, c(bb)[2]), (0, -1, 0), {"desk_t"}),
        ("battery holder top", R["battery_holder"], lambda bb: (bb.min.X + 1.5, c(bb)[1], bb.max.Z + 10), (0, 0, -1),
         {"depth_pct"}),
        ("cable organizer base", R["cable_organizer"], lambda bb: (c(bb)[0], c(bb)[1], bb.max.Z + 10), (0, 0, -1),
         {"base_t"}),
        ("hose adapter end", R["hose_adapter"], lambda bb: (c(bb)[0], bb.max.Y + 10, bb.min.Z + 8), (0, -1, 0),
         {"d_a"}),
        ("sketch bracket leg", SketchBracket(), lambda bb: (3, bb.max.Y + 10, 12), (0, -1, 0), {"leg_b"}),
        ("sketch bracket end", SketchBracket(), lambda bb: (bb.max.X + 10, 3, 12), (-1, 0, 0), {"leg_a"}),
        ("character mask brow", exemplars.load("character_mask"), lambda bb: (300, 0, 157), (-1, 0, 0), {"brow"}),
    ]


class DragFace(unittest.TestCase):
    def test_right_parameter_on_8_of_10(self):
        right, report = 0, []
        for name, recipe, origin, ray, want in cases():
            v = recipe.validate(recipe.defaults())
            base = recipe.build(v)[-1].shape
            hit = dragface.probe(base, origin(base.bounding_box()), ray)
            self.assertIsNotNone(hit, name)
            p, n, f = hit
            out = dragface.sensitivity(recipe, v, p, n, base_shape=base, face_area=f.area)
            got = out["best"]["key"] if out["best"] else None
            ok = got in want
            right += ok
            report.append(f"{name}: {got} ({'right' if ok else 'want ' + '/'.join(want)})")
        self.assertGreaterEqual(right, 8, "\n".join(report))

    def test_value_for_follows_the_rate_and_the_range(self):
        b = {"value": 36.0, "rate": 1.0, "step": 0.5, "min": 8, "max": 140}
        self.assertEqual(dragface.value_for(b, 10.2), 46.0)
        self.assertEqual(dragface.value_for({**b, "rate": 0.5}, 5), 46.0)        # a symmetric width moves half
        self.assertEqual(dragface.value_for(b, -100), 8)

    def test_switches_are_never_dragged(self):
        keys = [p.key for p in dragface.candidates(registry()["storage_box"], "shell")]
        self.assertNotIn("lid", keys)


if __name__ == "__main__":
    unittest.main()
