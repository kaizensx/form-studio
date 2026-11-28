"""A design built lying down, for the views that must rest it on the ground (tests/test_assembly_views.py,
tests/journeys/plates.py)."""

# Built lying down: a post modelled along X beside a base plate, stood upright by its placement about a point under
# the plate, and pulled down and out for the exploded view. Shown naively, the post would hang below the plate.
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
            Part("base", "Base", 0, explode=(0, 0, 0)),
            Part("post", "Post", 1, rotate=(0, 90, 0), move=(-50, 19, -40), explode=(0, 0, -30)),
        ])
'''
