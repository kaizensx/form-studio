"""Kinematic chains in the assembly contract (form/recipes/assembly.py): the tree, the transforms, validation.

Plain data and numpy; no kernel.
"""
import math
import unittest

import numpy as np

from form.recipes.assembly import Assembly, Joint, Mate, Part, fixed, hinge, joint_matrix, placement_matrix, slide, slider


def P(M, p):
    return (M[:3, :3] @ np.asarray(p, float) + M[:3, 3]).tolist()


def holder():
    """base (world) <- arm tilt <- arm <- cup tilt <- cup <- cup bolt; wall bolt fixed to the base."""
    return Assembly(
        parts=[Part("base", "Base", 0), Part("arm", "Arm", 1, explode=(0, 0, 30)),
               Part("bolt", "Wall bolt", 2, attach="base", explode=(-20, 0, 0)),
               Part("cup", "Cup", 3, explode=(0, 0, 40)), Part("cup_bolt", "Cup bolt", 4, attach="cup", explode=(-20, 0, 0))],
        joints=[hinge("arm", (1, 0, 0), (0, 0, 20), (-60, 60), parent="base", id="arm_tilt"),
                hinge("cup", (1, 0, 0), (0, 0, 75), (-90, 90), parent="arm", id="cup_tilt")],
        mates=[Mate("bolt", "base", "thread"), Mate("bolt", "arm", "pin"), Mate("cup_bolt", "cup", "pin")])


class Tree(unittest.TestCase):
    def test_chains_and_what_each_joint_moves(self):
        a = holder()
        self.assertEqual(a.validate(5), [])
        self.assertEqual([j.id for j in a.chain("cup_bolt")], ["arm_tilt", "cup_tilt"])
        self.assertEqual([j.id for j in a.chain("bolt")], [])
        self.assertEqual(a.moved_by("arm_tilt"), ["arm", "cup", "cup_bolt"])
        self.assertEqual(a.moved_by("cup_tilt"), ["cup", "cup_bolt"])
        self.assertEqual(a.ancestors("cup_bolt"), ["base", "arm", "cup"])
        self.assertEqual(a.rigid_group("cup_bolt"), "cup")
        self.assertEqual(a.rigid_group("bolt"), "base")
        self.assertIsNotNone(a.mate("arm", "bolt"))
        pub = a.public()
        self.assertEqual(pub["joints"][0]["moves"], ["arm", "cup", "cup_bolt"])
        self.assertEqual(len(pub["mates"]), 3)

    def test_a_child_moves_with_its_parent_and_its_axis_rides_along(self):
        a = holder()
        # a point on the cup axis at rest, and a point on the cup bolt
        on_axis, bolt_pt = [0, 0, 75], [-5, 0, 75]
        M = a.motion("cup_bolt", {"arm_tilt": 30})
        # arm tilt alone: the cup bolt turns 30° about the arm axis (x through (0, 0, 20)), exactly like the arm
        np.testing.assert_allclose(M, a.motion("arm", {"arm_tilt": 30}), atol=1e-12)
        r = math.radians(30)
        np.testing.assert_allclose(P(M, on_axis), [0, -55 * math.sin(r), 20 + 55 * math.cos(r)], atol=1e-9)
        # nested: with the arm at 30°, turning the cup keeps the cup axis where the arm put it
        M2 = a.motion("cup", {"arm_tilt": 30, "cup_tilt": 45})
        np.testing.assert_allclose(P(M2, on_axis), P(M, on_axis), atol=1e-9)
        np.testing.assert_allclose(P(M2, bolt_pt), P(M, bolt_pt), atol=1e-9)      # the bolt lies on that axis
        # and a cup point off the axis turns 45° about it, in the arm's frame
        off = [0, 10, 75]
        rel = np.linalg.inv(M) @ M2
        np.testing.assert_allclose(P(rel, off), [0, 10 * math.cos(math.radians(45)), 75 + 10 * math.sin(math.radians(45))], atol=1e-9)
        # parts outside the chain never move
        np.testing.assert_allclose(a.motion("bolt", {"arm_tilt": 30, "cup_tilt": 45}), np.eye(4))

    def test_world_is_motion_after_placement(self):
        a = Assembly(parts=[Part("b", "B", 0), Part("l", "L", 1, move=(1, 2, 3), rotate=(90, 0, 0))],
                     joints=[slide("l", (0, 0, 2), (0, 10))])
        W = a.world("l", {"l_slide": 4})
        np.testing.assert_allclose(W, joint_matrix(a.joints[0], 4) @ placement_matrix(a.parts[1]))
        np.testing.assert_allclose(W[:3, 3], [1, 2, 7])

    def test_explode_offsets_add_up_the_chain(self):
        a = holder()
        self.assertEqual(a.explode_total("cup_bolt"), (-20.0, 0.0, 70.0))
        self.assertEqual(a.explode_total("bolt"), (-20.0, 0.0, 0.0))

    def test_detents(self):
        j = hinge("p", (1, 0, 0), (0, 0, 0), (-60, 60), step=15)
        self.assertEqual(Assembly(parts=[Part("p", "P", 0)], joints=[j]).detents(j), [-60, -45, -30, -15, 0, 15, 30, 45, 60])


class Compatible(unittest.TestCase):
    def test_a_joint_without_parent_moves_only_its_part(self):
        a = Assembly(parts=[Part("box", "Box", 0), Part("lid", "Lid", 1)],
                     joints=[hinge("lid", (-1, 0, 0), (0, 20, 12), (0, 100))])
        self.assertEqual(a.validate(2), [])
        self.assertEqual(a.moved_by("lid_hinge"), ["lid"])
        self.assertEqual(a.link("lid")[0], "")
        np.testing.assert_allclose(a.motion("box", {"lid_hinge": 50}), np.eye(4))

    def test_synonyms_and_fixed(self):
        a = Assembly(parts=[Part("a", "A", 0), Part("b", "B", 1), Part("c", "C", 2)],
                     joints=[Joint("s", "S", "b", "slider", (1, 0, 0)), fixed("c", "b")])
        self.assertEqual(a.joints[0].kind, "slide")
        self.assertIs(slider, slide)
        self.assertEqual(a.validate(3), [])
        self.assertEqual(a.moved_by("s"), ["b", "c"])
        np.testing.assert_allclose(a.motion("c", {"s": 5})[:3, 3], [5, 0, 0])


class Validation(unittest.TestCase):
    def problems(self, **kw):
        base = dict(parts=[Part("a", "A", 0), Part("b", "B", 1), Part("c", "C", 2)])
        base.update(kw)
        return " | ".join(Assembly(**base).validate(3))

    def test_clear_errors(self):
        self.assertIn("attached to unknown part “zz”", self.problems(parts=[Part("a", "A", 0, attach="zz")]))
        self.assertIn("attached to itself", self.problems(parts=[Part("a", "A", 0, attach="a")]))
        self.assertIn("parent “q” is not a part", self.problems(joints=[hinge("b", (1, 0, 0), (0, 0, 0), (0, 9), parent="q")]))
        self.assertIn("relative to itself", self.problems(joints=[hinge("b", (1, 0, 0), (0, 0, 0), (0, 9), parent="b")]))
        self.assertIn("moved by two joints", self.problems(joints=[hinge("b", (1, 0, 0), (0, 0, 0), (0, 9), id="j1"),
                                                                   slide("b", (1, 0, 0), (0, 9), id="j2")]))
        self.assertIn("both attached to a and moved by joint", self.problems(
            parts=[Part("a", "A", 0), Part("b", "B", 1, attach="a")], joints=[hinge("b", (1, 0, 0), (0, 0, 0), (0, 9))]))
        loop = self.problems(parts=[Part("a", "A", 0, attach="c"), Part("b", "B", 1, attach="a"), Part("c", "C", 2, attach="b")])
        self.assertIn("form a loop", loop)
        self.assertIn("lo < hi", self.problems(joints=[hinge("b", (1, 0, 0), (0, 0, 0), (9, 0))]))
        self.assertIn("kind must be hinge, slide or fixed", self.problems(joints=[Joint("x", "X", "b", "spin", (1, 0, 0))]))
        self.assertIn("Mate a/zz names unknown part", self.problems(mates=[Mate("a", "zz")]))
        self.assertIn("kind must be one of", self.problems(mates=[Mate("a", "b", "glue")]))
        self.assertIn("step must be", self.problems(joints=[hinge("b", (1, 0, 0), (0, 0, 0), (0, 9), step=30)]))


if __name__ == "__main__":
    unittest.main()
