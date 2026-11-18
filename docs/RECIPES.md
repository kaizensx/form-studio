# Writing a recipe

A recipe is a family of objects: typed parameters in, one valid solid out, built in named stages so that every face knows which feature it belongs to. Everything else in Form Studio depends on recipes: checks, fit, the optimizer, renders, animations and releases. It all works on a new recipe automatically.

Start from [`form/recipes/shelf_bracket.py`](../form/recipes/shelf_bracket.py). It is short and uses most hooks: a measured interface with a fit window, a load model, hardware with tool access, and a ghost of the shelf it carries.

## The built-in library

Recipes are building blocks: agents start from them and change anything, and people browse them in the
[website gallery](https://kaizensx.github.io/form-studio/recipes/). The library is the recipes people print most, each
designed to be bought, not only to work:

| id | title | category |
|---|---|---|
| `gridfinity_bin` | Gridfinity bin | Storage |
| `gridfinity_baseplate` | Gridfinity baseplate | Storage |
| `storage_box` | Box with lid (sliding, press-on or hinged) | Storage |
| `pegboard` | SKÅDIS pegboard accessory (hook, cup, shelf, bin) | Wall & desk |
| `device_stand` | Phone and tablet stand | Desk |
| `cable_organizer` | Cable organizer | Wall & desk |
| `desk_hanger` | Under-desk hanger | Wall & desk |
| `shelf_bracket` | Shelf bracket | Wall & desk |
| `hose_adapter` | Hose and pipe adapter | Workshop |
| `plant_pot` | Self-watering planter | Home |
| `vase` | Faceted vase and lamp shade | Home |
| `battery_holder` | Battery and card holder | Storage |
| `enclosure` | Electronics enclosure | Enclosures |
| `coupon` | Fit coupon | Calibration |

The order is `LIBRARY` in [`form/recipes/__init__.py`](../form/recipes/__init__.py). Each recipe lives in `form/recipes/<id>.py`: the file name is the id, because the build cache hashes that file.

**Design language.** [`form/recipes/style.py`](../form/recipes/style.py) holds the shared proportions and print rules: soft plan corners, a chamfer where the part meets the plate (it hides the first-layer flare), rounded top edges, and teardrop holes that print in a vertical wall. Model each part in its print orientation and keep every downward face within 45° of vertical, or a short bridge.

> **Tip:** an exact 45° chamfer or cone around a curved edge tessellates a little past 45° and trips the overhang check. Use a chamfer that rises more than it runs (0.3 mm in, 0.5 mm up), or 40° cones.

**Legacy recipes.** `dock`, `gridfinity`, `hook`, `planter`, `gear_pair`, `knob` and `hinged_box` are retired (`legacy = True`). They are left out of every listing: `form recipes`, `form_overview`, `recipe_library` and the website gallery. Designs that name them still open, build and release exactly as before. To retire a recipe, set `legacy = True` and move its id from `LIBRARY` to `LEGACY`; never delete its file.

## 1. Parameters

```python
Param("screw_d", "Screw shank diameter", 4.0, 2, 8, 0.05, "mm", "brief", "screws",
      "Measure the shank, not the thread tips.")
```

The positional arguments are, in order: key, label, default, min, max, step, unit, group, feature, doc.

Groups tell agents and people what kind of number each one is:

| group | meaning | example |
|---|---|---|
| `brief` | a fact about the world; **measure it** | phone width, magnet diameter, load |
| `interface` | how parts meet | clearance per side |
| `form` | a free design choice | wall, fillet, twist |
| `process` | an assumption about printing | material strength |

Integer parameters use `step=1` with unit `""` or `"u"`. The optimizer and animations snap them to whole values.

## 2. Features and stages

```python
features = [Feature("plate", "Wall plate", "structure"), Feature("arm", "Arm", "structure"), ...]

def build(self, v):
    plate = Box(...)
    stages = [Stage("plate", plate)]
    s = plate + arm
    stages.append(Stage("arm", s))
    ...
    return stages
```

Each `Stage` is the whole solid after that feature has been applied. After the build, Form Studio attributes every face of the final solid to the last stage that created its surface. That attribution drives several things:

- click-to-select in the viewport,
- the colours in renders,
- "features touched" in change impact.

> **Tip:** when two stages leave coplanar faces, OpenCascade fuses them into one face, which then belongs to one feature. Give them slightly different heights; the Gridfinity dividers stop 1.5 mm below the label shelf for this reason.

## 3. Constraints that explain themselves

```python
def constraints(self, v):
    if g["z2"] + v["screw_head_d"] / 2 + 2 > v["plate_h"]:
        return [RecipeError("Upper screw sits 75 mm up; the plate is 80 mm tall", "screws",
                            "Raise the plate height or reduce the screw spacing.", ["plate_h", "screw_spacing"])]
```

Every error names the feature, the parameters involved and a way forward. Agents read these. The optimizer reports the most common ones as the reasons candidates were rejected.

## 4. Interfaces and fit

```python
fit = {"cavity": "screw_hole", "mating": "screw_d", "clearance": "screw_clearance",
       "label": "Screw hole ↔ screw shank", "per_side": True, "window": [0.2, 1.0]}
```

- **`derived()`** returns the intended interface dimensions, for example `screw_hole = d + 2 × clearance`.
- **`measure()`** reads the same dimensions back off the built solid. The "Interfaces as modelled" check compares the two.
- **`window`** is the acceptable total gap in mm. Use small or negative values for press fits and larger ones for clearance holes.

## 5. Optional extras

| method | what it adds |
|---|---|
| `statics(v, volume, com)` | Numbers such as `safety_factor` (optimizer metrics `statics.<key>`), plus `"checks": [...]` that appear on the checks list labelled `model`. |
| `companions(v)` | Objects drawn with the part but not printed, such as the phone on the stand. |
| `test_piece(v, shape)` | A small piece cut from the real geometry around the interface. Printing it is the cheapest physical test. |

## 6. Library metadata

```python
category = "Wall & desk"
tags = ("skadis", "ikea", "pegboard", "hook")
```

`category` files the recipe in the library and the gallery; `tags` are the words people search for. Keep `summary` to one sentence.

## 7. Register and test

Built-in recipes live in `form/recipes/`. Community recipes live in [`community/recipes/`](../community/recipes/README.md) and need no registration.

1. Add the id to `LIBRARY` in [`form/recipes/__init__.py`](../form/recipes/__init__.py).
2. Run these checks:

```bash
form new "Try it" myrecipe
form render try-it --view sheet --out try.png
form optimize try-it --vary wall:1:4 --minimize solid_mass_g
python -m unittest discover -s tests
```

Add a test that builds the recipe at its defaults and at the ends of its ranges with [`tests/recipe_harness.py`](../tests/recipe_harness.py): it checks the solid count, the plate, a 180 mm bed, feature attribution and every interface dimension as modelled. See `tests/test_library_*.py`.

Look at the render. Most recipe mistakes are visible there before any check catches them, such as a screw a screwdriver cannot reach, or a knife-edge shelf.

## Evidence in recipes

Models in `statics()` must state their assumptions in the check detail, and use `evidence: "model"`. A beam formula is not a load rating, and the text has to say so.
