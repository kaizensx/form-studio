from build123d import Box
from form.recipes.base import Feature, Param, Recipe, Stage


class CableClip(Recipe):
    title = "Cable clip"
    summary = "A test stand-in for a community recipe: a plain block."
    params = [Param("w", "Width", 16, 5, 60, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 8, 8))]
