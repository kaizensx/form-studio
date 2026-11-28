"""A design built lying down, for the views that must rest it on the ground (tests/test_assembly_views.py,
tests/journeys/plates.py)."""

# A front flap (the "lid") hinged on the box's bottom front edge, printed flat and stood up on the box's front by its
# placement. It swings forward through 180°: flat in front of the box at 90°, and at 180° hanging straight down past
# the plate's side, 20 mm lower than the plate.
FLAP = '''
from build123d import Align, Box, Pos
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage, hinge

A = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Box with a flap"
    summary = "A box whose front flap swings forward and down through 180 degrees."
    solids = 2
    params = [Param("depth", "Depth", 40, 20, 80, 1, "mm", "brief", "box")]
    features = [Feature("box", "Box", "structure"), Feature("lid", "Flap", "structure")]

    def build(self, v):
        box = Box(60, v["depth"], 20, align=A)
        flap = Pos(70, 0, 0) * Box(60, 20, 4, align=A)
        return [Stage("box", box), Stage("lid", box + flap)]

    def assembly(self, v):
        return Assembly(parts=[Part("box", "Box", 0),
                               Part("lid", "Flap", 1, rotate=(90, 0, 0), move=(-70, 0, 0), explode=(0, -20, 0))],
                        joints=[hinge("lid", (1, 0, 0), (0, -4, 0), (0, 180), parent="box", id="flap", label="Flap")])
'''

# Built lying down: a post modelled along X beside a base plate, stood upright on the base by its placement (a turn
# about Y, then a move down and over). Both exploded offsets point down (the base's 10 mm, the post's 40 mm and out):
# shown naively, the exploded set goes through the ground. The base is the anchor (fixed to the world, the largest
# footprint): it stays where it rests, and the post's offset relative to it (25, 0, -30) is turned upward.
LYING = '''
from build123d import Align, Box, Pos
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, Stage

A = (Align.MIN, Align.MIN, Align.MIN)


class Design(Recipe):
    title = "Post on a base"
    summary = "A post printed lying down beside its base."
    solids = 2
    params = [Param("post_l", "Post length", 60, 20, 120, 1, "mm", "brief", "post")]
    features = [Feature("base", "Base", "structure"), Feature("post", "Post", "structure")]

    def build(self, v):
        base = Box(50, 50, 6, align=A)
        post = Pos(70, 0, 0) * Box(v["post_l"], 12, 12, align=A)
        return [Stage("base", base), Stage("post", base + post)]

    def assembly(self, v):
        return Assembly(parts=[
            Part("base", "Base", 0, explode=(0, 0, -10)),
            Part("post", "Post", 1, rotate=(0, -90, 0), move=(31, 19, -64), explode=(25, 0, -40)),
        ])
'''
