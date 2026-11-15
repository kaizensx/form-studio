# Writing a recipe

A recipe is a family of objects: typed parameters in, one valid solid out, built in named stages so that every face knows which feature it belongs to. Everything else in FORM depends on recipes: checks, fit, the optimizer, renders, animations and releases. It all works on a new recipe automatically.

Start from [`form/recipes/hook.py`](../form/recipes/hook.py). It is short and uses every hook.

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

Each `Stage` is the whole solid after that feature has been applied. After the build, FORM attributes every face of the final solid to the last stage that created its surface. That attribution drives several things:

- click-to-select on the bench,
- the colours in renders,
- "features touched" in change impact.

> **Tip:** if two stages leave coplanar faces that OpenCascade fuses into one face, give them slightly different heights. Otherwise they share a colour. The Gridfinity dividers stop 1.5 mm below the label shelf for this reason.

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
| `companions(v)` | Ghost objects on the bench, such as the phone in the dock. |
| `test_piece(v, shape)` | A small piece cut from the real geometry around the interface. Printing it is the cheapest physical test. |

## 6. Register and test

1. Add the recipe to `registry()` in [`form/recipes/__init__.py`](../form/recipes/__init__.py).
2. Run these checks:

```bash
.venv/bin/form new "Try it" myrecipe
.venv/bin/form render try-it --view sheet --out /tmp/try.png
.venv/bin/form optimize try-it --vary wall:1:4 --minimize solid_mass_g
.venv/bin/python -m unittest discover -s tests
```

Look at the render. Most recipe bugs are visible there before any check catches them: in this repository, a screwdriver that couldn't reach a screw, and a knife-edge label shelf.

## Be honest in the recipe too

Models in `statics()` must state their assumptions in the check detail, and use `evidence: "model"`. A beam formula is not a load rating, and the text has to say so.
