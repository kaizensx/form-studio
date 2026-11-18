# Community recipes

Recipes contributed by the community. Each one appears in the
[recipe gallery](https://kaizensx.github.io/form-studio/recipes/), with its category and tags, and agents can find it
and build on it (`recipe_library` over MCP). Anyone can install one with `form recipes install`, after reading its
source and its SHA-256; nothing runs until a design is created from it.

A recipe is a family of objects: typed parameters in, one valid solid out, built in named stages so that every face
knows which feature it belongs to. Form Studio builds it in the CAD kernel and runs the full pipeline on it: checks,
fit model, slicing, print simulation, revisions, variants, optimisation and release.

## Submit it in an issue

The quickest way. Open a [New recipe](https://github.com/kaizensx/form-studio/issues/new?template=3-recipe.yml)
issue, choose **build and check it here**, and paste `recipe.py` (or link to it, or attach it as `recipe.py.txt` or in
a `.zip`). The automation builds it in the CAD kernel at its defaults and at a smaller and a larger set of measured
dimensions, runs the checks, slices it with PrusaSlicer and replies with pictures and results. Edit the issue to check
again. Once it passes, a maintainer can accept it, and the automation opens the pull request with `recipe.py`,
`meta.json` and `preview.png`, credited to you.

## Prepare it with Form Studio

Install your recipe, or turn a design into one, then package or submit it. Each command prints JSON:

```bash
form recipes inspect my_recipe.py                              # its SHA-256, title and any problems
form recipes install my_recipe.py --sha256 <hex>               # install exactly that file
form recipes derive <project> --range wall=1.6:3               # a design as a recipe; --install --sha256 <hex>
form recipes export <id> --out my-recipe.formrecipe --author your-github-username --tags "desk, cables"
form recipes import my-recipe.formrecipe                       # shows the code's SHA-256; add --sha256 <hex> to install
form recipes submit <id> --out path/to/fork/community/recipes  # the folder, and the pre-filled issue link
```

- **`export`** writes one `.formrecipe` file: the code, `meta.json` (title, summary, author, tags, every parameter
  with its range, the code's SHA-256) and `preview.png`, drawn from a real build at the recipe's defaults. Anyone can
  `import` it and sees the code and the checksum before anything is installed.
- **`submit`** checks what the gallery would refuse (author, summary, tags, id), writes `<id>/` with exactly the three
  files below for a pull request, and prints a link that opens the recipe issue form with the title, id, `meta.json`
  and code filled in. Open it, drag `preview.png` into it and submit it yourself. Form Studio sends nothing on its own.

Agents can do the same over MCP (`export_recipe`, `prepare_recipe_submission`, `design_as_recipe`). How it printed
belongs in its thread in [Discussions](https://github.com/kaizensx/form-studio/discussions).

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
| `discussion` | string, optional | Its thread in GitHub Discussions (`https://github.com/kaizensx/form-studio/discussions/<n>`) |
| `added` | string, optional | The date it joined the gallery, `YYYY-MM-DD`, for "newest" sorting |

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

About 960 × 560 px, the part at its default values. The simplest way to make one:

```bash
form render <project> --view iso --out preview.png
```

## Before you open a pull request

1. Create a design from your file and run the pipeline: ask an agent to create a design from the file
   (`create_design`), or from a script `Studio.create_design(name, source)` then `form run <project>`.
2. It builds with its default values, and `form state <project>` shows no failed check.
3. Every parameter has a unit, a range and a group (`brief`, `interface`, `form`, `process`). Dimensions people should
   measure are `brief`.
4. Constraints name the feature, the parameters and a way forward.
5. Open the pull request against `dev`. The website's index is rebuilt from this folder on every release.

Contributions are released under the repository's [MIT licence](../../LICENSE).
