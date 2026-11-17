# Community recipes

Recipes contributed by the community. Each one appears in the
[recipe gallery](https://kaizensx.github.io/form-studio/recipes/) and in the app's **New design › Community recipes**,
where it can be opened as a new design in one click.

A recipe is a family of objects: typed parameters in, one valid solid out, built in named stages so that every face
knows which feature it belongs to. Form Studio builds it in the CAD kernel and runs the full pipeline on it: checks,
fit model, slicing, print simulation, revisions, variants, optimisation and release.

## Layout

```
community/recipes/
  <id>/
    recipe.py      the design: one Python file with one Recipe subclass (or recipe.scad for OpenSCAD)
    meta.json      what the gallery shows
    preview.png    a picture of the part with its default values
```

`<id>` is lowercase letters, digits and hyphens, and matches `meta.json`'s `id`.

### `meta.json`

```json
{
  "id": "cable-clip",
  "title": "Cable clip",
  "summary": "A screw-down clip that snaps over a cable of measured diameter, with a fit model for the bore.",
  "author": "your-github-username",
  "tags": ["cable management", "desk", "snap fit"],
  "kind": "python",
  "params_count": 8
}
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Same as the folder name |
| `title` | string | Short name, sentence case |
| `summary` | string | One sentence: what it is and what makes it fit |
| `author` | string | Your GitHub username |
| `tags` | string[] | A few lowercase words people would search for |
| `kind` | `"python"` or `"scad"` | `recipe.py` (build123d) or `recipe.scad` (OpenSCAD with Customizer ranges) |
| `params_count` | integer | Number of parameters the recipe exposes |

### `recipe.py`

The same contract an agent uses for a design written as code: the MCP tool `design_guide` returns it in full, and
[Writing a recipe](../../docs/RECIPES.md) walks through it. In short:

```python
from build123d import Align, Box, Cylinder, Pos, Rot
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

class Design(Recipe):
    title = "Cable clip"
    summary = "..."
    params = [Param("cable_d", "Cable diameter", 6.0, 2, 20, 0.1, "mm", "brief", "ring", "Measure it."), ...]
    features = [Feature("plate", "Base plate", "structure"), ...]
    def constraints(self, v): ...      # RecipeError(message, feature, hint, [params]) for every invalid combination
    def build(self, v): ...            # [Stage(feature_id, whole_solid_after_this_feature), ...]
```

[`cable-clip/recipe.py`](cable-clip/recipe.py) is a complete, small example.

### `preview.png`

About 960 × 620 px, the part at its default values. The simplest way to make one:

```bash
form render <project> --view iso --out preview.png
```

## Before you open a pull request

1. Create a design from your file and run the pipeline. In the app: **New design › Import project**, or ask the agent
   to create a design from the file. From a script, `Studio.create_design(name, source)` then `form run <project>`.
2. It builds with its default values, and `form state <project>` shows no failed check.
3. Every parameter has a unit, a range and a group (`brief`, `interface`, `form`, `process`). Dimensions people should
   measure are `brief`.
4. Constraints name the feature, the parameters and a way forward.
5. Open the pull request against `dev`. The website's index is rebuilt from this folder on every release.

Contributions are released under the repository's [MIT licence](../../LICENSE).
