"""Game exemplars: six original game assets made with the cage vocabulary, the kit and the material library, plus one
deliberately bad control asset the game critic must fail.

Each module holds TITLE, ORIGINALITY (what it is and why it copies nothing: no franchise, brand or character),
MATERIALS ({region or "default": material}, form/game/materials.py) and either ops() (a model_mesh op list: blocks
from base.py, then bevel, inset, panel_line, trim_strip, kit_place; bake-only detail tagged high_only) or SOURCE (a
kernel design, for an asset that is also real CAD). scripts/game_bench.py builds, measures and renders them.

    from form.exemplars import game
    game.names()                         # the six, then the control
    game.make("treasure_chest")          # {"title", "source", "cage" or None, "materials", "originality", "seconds"}

make() runs Blender (the op list in the fixed runner) for a cage exemplar; a kernel exemplar needs no Blender.
These are not design exemplars for design_examples (form/exemplars/*.py are): the folder is a package and the
catalogue reads only the files beside it.
"""
from __future__ import annotations

import importlib
import time

EXEMPLARS = ("scifi_helmet", "treasure_chest", "fantasy_sword", "wall_kit", "vehicle_wheel", "tv_remote")
CONTROL = "control_blob"


def names() -> list[str]:
    return [*EXEMPLARS, CONTROL]


def module(name: str):
    if name not in names():
        raise KeyError(f"no game exemplar {name!r}; there are {', '.join(names())}")
    return importlib.import_module(f"{__name__}.{name}")


def make(name: str, cfg: dict | None = None) -> dict:
    from . import base
    m = module(name)
    t = time.time()
    out = {"name": name, "title": m.TITLE, "materials": m.MATERIALS, "originality": m.ORIGINALITY, "cage": None,
           "ops": None}
    if hasattr(m, "SOURCE"):
        out["source"] = m.SOURCE
    else:
        if hasattr(m, "cage"):
            cage = m.cage()
        else:
            out["ops"] = m.ops()
            cage = base.build(out["ops"], cfg)
        out["cage"] = cage
        out["source"] = base.design_source(cage, m.TITLE, m.MATERIALS, (m.__doc__ or "").split("\n")[0])
    out["seconds"] = round(time.time() - t, 2)
    return out
