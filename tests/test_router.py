"""The hybrid router (form/router.py): a route per planned feature (kernel, subd_cage, sculpt_recon, procedural)
with the words that chose it and evidence "heuristic"; agreement on a labelled set of feature phrases (English and
Portuguese) with the confusion matrix printed; plan_design storing stated routes, warning about a mechanical
interface on a mesh-only route and writing unread routes into the brief's unknowns; every helper a route names
checked against the real registry; the hybrid and game guide topics.

The labels are the implementer's reading of each phrase under the rules in form/router.py (an interface is built in
the kernel; a pattern on a smooth surface is procedural; sculpted detail is sculpt_recon). Agreement measures how
well the keyword heuristic follows those rules, not how often a designer would agree."""
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="form-router-")
os.environ["FORM_DATA"] = TMP
os.environ.setdefault("FORM_SKIP_UI", "1")

from form import config, design_guide, router, staged  # noqa: E402
from form.studio import Studio, StudioError  # noqa: E402

K, S, R, P = "kernel", "subd_cage", "sculpt_recon", "procedural"

#: (phrase, class of phrase, language, expected route)
LABELLED = [
    # mechanical, English
    ("M3 heat-set insert bosses on the base", "mechanical", "en", K),
    ("608 bearing seat, 22.05 mm bore", "mechanical", "en", K),
    ("snap-fit tabs that lock the lid", "mechanical", "en", K),
    ("mounting flange with four countersunk screw holes", "mechanical", "en", K),
    ("M8 threaded hole through the clamp", "mechanical", "en", K),
    ("rectangular cable cutout in the back wall", "mechanical", "en", K),
    ("flat mating face for the lid, 0.2 mm clearance", "mechanical", "en", K),
    ("hinge pin and knuckles", "mechanical", "en", K),
    ("chamfered base plate, 4 mm thick", "mechanical", "en", K),
    ("dovetail rail for the slide", "mechanical", "en", K),
    ("31 mm bolt pattern on the motor face", "mechanical", "en", K),
    # organic (sculpted detail), English
    ("sculpted dragon head with scales and wrinkles", "organic", "en", R),
    ("creature skin with pores and muscle definition", "organic", "en", R),
    ("weathered rock base for the figurine", "organic", "en", R),
    ("detailed facial features on the bust", "organic", "en", R),
    ("anatomical hand with knuckles and veins", "organic", "en", R),
    ("cloth folds on the character's cape", "organic", "en", R),
    ("monster claws and horns, sculpted", "organic", "en", R),
    # styled (smooth designed surfaces), English
    ("smooth ergonomic mouse shell", "styled", "en", S),
    ("sleek aerodynamic car body", "styled", "en", S),
    ("flowing helmet shell with a visor line", "styled", "en", S),
    ("streamlined drone fuselage", "styled", "en", S),
    ("soft rounded controller grip", "styled", "en", S),
    ("curved fairing for the motorcycle", "styled", "en", S),
    ("organic lamp shade with smooth transitions", "styled", "en", S),
    # procedural, English
    ("hexagonal vent pattern on the side", "procedural", "en", P),
    ("voronoi lattice for the lamp", "procedural", "en", P),
    ("scatter rivets across the hull panels", "procedural", "en", P),
    ("diamond knurl around the knob", "procedural", "en", P),
    ("repeating brick tiles for the modular wall", "procedural", "en", P),
    ("gyroid infill texture", "procedural", "en", P),
    ("array of cooling fins along the housing", "procedural", "en", P),
    ("grass and pebble scatter on the base", "procedural", "en", P),
    # mixed, English
    ("magnet pocket in the sculpted creature head", "mixed", "en", K),
    ("screw bosses inside the smooth mouse shell", "mixed", "en", K),
    ("hex texture on the helmet's smooth crown", "mixed", "en", P),
    ("bearing seat in the organic handle", "mixed", "en", K),
    ("sculpted battle damage on the smooth armour plates", "mixed", "en", R),
    # mechanical, Portuguese
    ("furos para parafusos M4 na base", "mechanical", "pt", K),
    ("alojamento para rolamento 608", "mechanical", "pt", K),
    ("encaixe de pressão na tampa", "mechanical", "pt", K),
    ("rosca M6 no suporte", "mechanical", "pt", K),
    ("dobradiça com pino de 3 mm", "mechanical", "pt", K),
    ("placa de fixação com chanfro", "mechanical", "pt", K),
    # organic, Portuguese
    ("cabeça de dragão esculpida com escamas", "organic", "pt", R),
    ("rugas e poros na pele da criatura", "organic", "pt", R),
    ("busto com traços faciais detalhados", "organic", "pt", R),
    ("rocha erodida para a base da estatueta", "organic", "pt", R),
    # styled, Portuguese
    ("carcaça lisa e ergonómica do rato", "styled", "pt", S),
    ("carroçaria aerodinâmica e fluida", "styled", "pt", S),
    ("casco do capacete com curvas suaves", "styled", "pt", S),
    ("pega arredondada e confortável", "styled", "pt", S),
    # procedural, Portuguese
    ("padrão hexagonal de ventilação", "procedural", "pt", P),
    ("textura voronoi na superfície", "procedural", "pt", P),
    ("rebites espalhados pelo painel", "procedural", "pt", P),
    ("recartilhado em diamante no botão", "procedural", "pt", P),
    ("tijolos repetidos na parede modular", "procedural", "pt", P),
    # mixed, Portuguese
    ("íman embutido na cabeça esculpida", "mixed", "pt", K),
    ("furos de montagem na carenagem lisa", "mixed", "pt", K),
    ("textura de colmeia no casco suave do capacete", "mixed", "pt", P),
    ("dobradiça viva entre a tampa e a caixa", "mixed", "pt", K),
    # first held-out set: measured at 69.4 % (25/36) before the vocabulary saw it, then used to fix it (in-sample now)
    ("USB-C port opening on the side", "mechanical", "en", K),
    ("battery compartment with a sliding cover", "mechanical", "en", K),
    ("keyed D-shaft bore for the knob", "mechanical", "en", K),
    ("cable gland boss at the rear", "mechanical", "en", K),
    ("press-fit lens retainer", "mechanical", "en", K),
    ("tripod 1/4-20 mount", "mechanical", "en", K),
    ("goblin ear with cartilage folds", "organic", "en", R),
    ("tree bark around the trunk", "organic", "en", R),
    ("old man's face, deep wrinkles", "organic", "en", R),
    ("horse mane flowing in the wind", "organic", "en", R),
    ("broken stone pillar, chipped edges", "organic", "en", R),
    ("toad warts on the back", "organic", "en", R),
    ("pebble-shaped soap dish body", "styled", "en", S),
    ("teardrop speaker enclosure surface", "styled", "en", S),
    ("smooth transition from neck to body of the bottle", "styled", "en", S),
    ("yacht hull, fair lines", "styled", "en", S),
    ("sculptural chair seat surface", "styled", "en", S),
    ("ergonomic palm rest", "styled", "en", S),
    ("woven basket texture", "procedural", "en", P),
    ("staggered louvre slats repeated 12 times", "procedural", "en", P),
    ("fish-scale tiling on the roof", "procedural", "en", P),
    ("random studs scattered on the shield", "procedural", "en", P),
    ("leather grain on the grip", "procedural", "en", P),
    ("parametric wave panels", "procedural", "en", P),          # still missed: no word says it is generated
    ("furo para cabo USB na lateral", "mechanical", "pt", K),
    ("tampa deslizante do compartimento da pilha", "mechanical", "pt", K),
    ("rosto de velho com rugas profundas", "organic", "pt", R),
    ("casca de árvore em volta do tronco", "organic", "pt", R),
    ("superfície lisa da garrafa", "styled", "pt", S),
    ("assento ergonómico da cadeira", "styled", "pt", S),
    ("escamas de peixe repetidas no telhado", "procedural", "pt", P),
    ("textura de couro na pega", "procedural", "pt", P),
    ("magnetic catch in the smooth lid", "mixed", "en", K),
    ("screw holes in the sculpted base rock", "mixed", "en", K),
    ("knurled band on the smooth bottle cap", "mixed", "en", P),
    ("rosca no gargalo da garrafa lisa", "mixed", "pt", K),
]
#: second held-out set: written after the vocabulary was fixed and never used to change it. First run: 88.9 % (32/36);
#: its four misses are sculpt phrases with no known word, routed to the kernel with confident False (brief unknowns)
HELDOUT = [
    ("two alignment dowels between the halves", K), ("zip-tie anchor loop under the shelf", K),
    ("PCB standoffs, 3 mm tall", K), ("wall-mount keyhole slots", K), ("the lid's sealing groove for an O-ring", K),
    ("drain opening at the bottom", K), ("1/4 turn bayonet lugs on the cap", K),
    ("elf face with high cheekbones", R), ("gnarled roots spreading over the base", R),
    ("orc skin, scars and pockmarks", R), ("chiselled marble statue drapery", R), ("lion paw with sharp claws", R),
    ("smooth swept body of the kettle", S), ("rounded edges of the phone case shell", S),
    ("curved armrest of the chair", S), ("aerodynamic nose cone", S), ("soft pillow-like cushion surface", S),
    ("stippled grip texture", P), ("radial array of spokes", P), ("bubbles scattered across the vase", P),
    ("herringbone pattern on the floor tile", P), ("geometric facets repeated around the lamp", P),
    ("encaixes para parafusos na traseira", K), ("pino de alinhamento entre as metades", K),
    ("ranhura para o vedante da tampa", K),
    ("rosto de elfo com maçãs do rosto altas", R), ("raízes retorcidas sobre a base", R),
    ("pele de orc com cicatrizes", R),
    ("corpo suave e arredondado da chaleira", S), ("bico aerodinâmico", S),
    ("padrão de espinha de peixe no piso", P), ("bolhas espalhadas pelo vaso", P),
    ("magnet recess under the sculpted owl", K), ("threaded insert in the smooth drone arm", K),
    ("voronoi cutouts on the organic shade", P), ("sculpted wrinkles on the smooth leather boot", R),
]
TARGET = 0.85


def evaluate(rows=None):
    """(agreement, confusion {expected: {got: n}}, misses) over (text, expected) rows (default: LABELLED)."""
    rows = [(t, w) for t, *_, w in LABELLED] if rows is None else rows
    conf = {a: {b: 0 for b in router.ROUTES} for a in router.ROUTES}
    misses = []
    for text, want in rows:
        got = router.route_feature(text)["route"]
        conf[want][got] += 1
        if got != want:
            misses.append((text, want, got))
    return 1 - len(misses) / len(rows), conf, misses


def matrix_text(conf) -> str:
    w = max(len(r) for r in router.ROUTES) + 2
    lines = ["expected \\ got".ljust(w + 4) + "".join(r.rjust(w) for r in router.ROUTES)]
    for a in router.ROUTES:
        lines.append(a.ljust(w + 4) + "".join(str(conf[a][b]).rjust(w) for b in router.ROUTES))
    return "\n".join(lines)


class Labelled(unittest.TestCase):
    def test_set_is_large_and_mixed(self):
        self.assertGreaterEqual(len(LABELLED), 40)
        self.assertEqual({c for _, c, _, _ in LABELLED}, {"mechanical", "organic", "styled", "procedural", "mixed"})
        self.assertEqual({lang for _, _, lang, _ in LABELLED}, {"en", "pt"})
        self.assertEqual({r for *_, r in LABELLED}, set(router.ROUTES))

    def test_agreement_and_confusion_matrix(self):
        agree, conf, misses = evaluate()
        lucky = sum(1 for t, *_, w in LABELLED if w == "kernel" and not router.route_feature(t)["confident"])
        print(f"\nrouter agreement: {agree:.1%} on {len(LABELLED)} labelled phrases (target {TARGET:.0%}); "
              f"{lucky} of them right only by the kernel default")
        print(matrix_text(conf))
        for text, want, got in misses:
            print(f"  miss: {text!r}: expected {want}, got {got}")
        self.assertGreaterEqual(agree, TARGET)

    def test_heldout_agreement(self):
        agree, conf, misses = evaluate(HELDOUT)
        lucky = sum(1 for t, w in HELDOUT if w == "kernel" and not router.route_feature(t)["confident"])
        print(f"\nrouter agreement, held out: {agree:.1%} on {len(HELDOUT)} phrases (target {TARGET:.0%}); "
              f"{lucky} of them right only by the kernel default")
        print(matrix_text(conf))
        for text, want, got in misses:
            print(f"  miss: {text!r}: expected {want}, got {got}"
                  + ("" if router.route_feature(text)["confident"] else " (not confident: a brief unknown)"))
        self.assertGreaterEqual(agree, TARGET)

    def test_every_answer_is_labelled_heuristic_with_its_words(self):
        by_default = []
        for text, *_ in LABELLED + [(t, None, None, w) for t, w in HELDOUT]:
            r = router.route_feature(text)
            self.assertEqual(r["evidence"], "heuristic")
            self.assertIn(r["route"], router.ROUTES)
            self.assertEqual(bool(r["because"]), r["confident"], text)    # confident only with the words that chose it
            if not r["confident"]:
                self.assertEqual(r["route"], "kernel")
                by_default.append(text)
        print(f"\nnot confident (kernel by default, reported as brief unknowns): {len(by_default)}: {by_default}")

    def test_unknown_words_are_not_claimed(self):
        r = router.route_feature("the main part")
        self.assertEqual(r["route"], "kernel")
        self.assertFalse(r["confident"])
        self.assertEqual(r["because"], [])

    def test_helpers_named_in_how_decide(self):
        self.assertEqual(router.route_feature("craft.subd.Cage of the shell")["route"], S)
        self.assertEqual(router.route_feature("craft.subd.fit_cage to the sculpt")["route"], R)
        self.assertEqual(router.route_feature("recon.freeform.fit_patch")["route"], R)
        self.assertEqual(router.route_feature("patterns.hex_vents 5 mm")["route"], P)
        self.assertEqual(router.route_feature("craft.MeshTexture voronoi")["route"], P)
        self.assertEqual(router.route_feature("craft.safe_shell 2 mm on the smooth body")["route"], K)


class Helpers(unittest.TestCase):
    def test_every_route_helper_exists_in_the_registry(self):
        reg = staged.registry()
        self.assertIn("Cage", reg["craft.subd"])
        for route, h in router.ROUTE_HELPERS.items():
            for name in h["helpers"]:
                self.assertTrue(router.check_helper(name), f"{route}: {name}")
        self.assertFalse(router.check_helper("craft.subd.NoSuchCage"))
        self.assertFalse(router.check_helper("recon.freeform.no_such_fit"))

    def test_model_mesh_is_named_not_required(self):
        p = router.plan_for("subd_cage")
        self.assertEqual([t["tool"] for t in p["tools"]], ["model_mesh"])
        self.assertEqual(p["tools"][0]["available"], router.model_mesh_available())
        self.assertIn("when available", router.ROUTE_HELPERS["sculpt_recon"]["how"])
        self.assertEqual(router.plan_for("kernel")["tools"], [])

    def test_brief_routes_unchanged(self):
        self.assertEqual(staged.ROUTES, ("prismatic", "revolve", "skin+features", "mechanism"))


class Plan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()

    def _brief(self):
        return staged.save_brief(self.st, "Creature lamp", "A lamp shaped like a sculpted creature head with a smooth "
                                 "shade and a hex vent pattern")

    def test_steps_carry_routes_and_real_helpers(self):
        b = self._brief()
        feats = [{"id": "head", "label": "Sculpted creature head", "how": "sculpt, then craft.subd.fit_cage"},
                 {"id": "shade", "label": "Smooth shade", "how": "craft.subd.Cage, 24 faces"},
                 {"id": "vents", "label": "Vents", "how": "patterns.hex_vents 5 mm cells"},
                 {"id": "cable_hole", "label": "Cable hole", "how": "a 6 mm hole through the base"}]
        r = staged.save_plan(self.st, b["id"], feats, risks=["fit deviation at the horns"])
        plan = r["plan"]
        self.assertEqual({k: v["route"] for k, v in plan["feature_routes"].items()},
                         {"head": R, "shade": S, "vents": P, "cable_hole": K})
        for s in plan["steps"]:
            self.assertEqual(s["route"]["evidence"], "heuristic")
            for h in s["route_plan"]["helpers"]:
                self.assertTrue(router.check_helper(h), h)
        self.assertEqual(plan["route_warnings"], [])
        self.assertEqual(plan["route"], staged.route(b["goal"] + " " + b["name"])["route"])

    def test_stated_route_is_kept_and_checked(self):
        b = self._brief()
        feats = [{"id": "body", "label": "Body", "how": "Box 40 x 30 x 20"},
                 {"id": "detail", "label": "Detail", "how": "anything", "route": "sculpt_recon"},
                 {"id": "edge", "label": "Edges", "how": "craft.safe_fillet 1 mm"}]
        r = staged.save_plan(self.st, b["id"], feats, risks=["x"])
        self.assertEqual(r["plan"]["feature_routes"]["detail"]["evidence"], "stated")
        feats[1]["route"] = "blender_magic"
        with self.assertRaises(StudioError) as cm:
            staged.save_plan(self.st, b["id"], feats, risks=["x"])
        self.assertIn("blender_magic", str(cm.exception))

    def test_interface_on_a_mesh_only_route_warns(self):
        b = self._brief()
        feats = [{"id": "head", "label": "Sculpted creature head", "how": "sculpted mesh"},
                 {"id": "bearing", "label": "Bearing seat", "how": "a 608 bearing seat, craft.bearing_fit"},
                 {"id": "thread", "label": "Lamp thread", "how": "E27 thread", "route": "procedural"},
                 {"id": "base", "label": "Base", "how": "Box"}]
        r = staged.save_plan(self.st, b["id"], feats, risks=["x"])
        w = " ".join(r["plan"]["route_warnings"])
        self.assertIn("bearing: a mechanical interface", w)
        self.assertIn("cut into head", w)
        self.assertIn("thread", w)
        self.assertEqual(len(r["plan"]["route_warnings"]), 2)
        # the same seat in a head brought back as a surface does not warn
        feats[0]["how"] = "sculpt, then craft.subd.fit_cage"
        feats[2].pop("route")
        r = staged.save_plan(self.st, b["id"], feats, risks=["x"])
        self.assertEqual(r["plan"]["route_warnings"], [])

    def test_unread_routes_go_into_the_brief(self):
        b = self._brief()
        feats = [{"id": "thing", "label": "Thing", "how": "make it"},
                 {"id": "vents", "label": "Vents", "how": "patterns.hex_vents"},
                 {"id": "plate", "label": "Plate", "how": "Box"}]
        staged.save_plan(self.st, b["id"], feats, risks=["x"])
        staged.save_plan(self.st, b["id"], feats, risks=["x"])          # twice: listed once
        unknowns = staged.load_brief(self.st, b["id"])["unknowns"]
        hits = [u for u in unknowns if "feature thing" in u]
        self.assertEqual(len(hits), 1)
        self.assertIn("heuristic", hits[0])
        self.assertFalse([u for u in unknowns if "feature vents" in u])


class Guide(unittest.TestCase):
    def test_hybrid_and_game_topics(self):
        h = design_guide.topic("hybrid")["guide"]
        for words in ("kernel", "subd_cage", "sculpt_recon", "procedural", "craft.subd.Cage", "fit_cage",
                      "when available", "approximate", "editable"):
            self.assertIn(words, h)
        g = design_guide.topic("game")["guide"]
        for words in ("LOD", "UV", "bake", "collision", "glTF", "Unreal", "Unity", "Godot"):
            self.assertIn(words, g)
        self.assertIn("hybrid", design_guide.topic("core")["topics"])
        for name in router.helpers_in(h):
            self.assertTrue(router.check_helper(name), name)


if __name__ == "__main__":
    unittest.main()
