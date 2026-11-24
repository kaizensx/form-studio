"""Engine presets: units, up axis, file formats and collision names for each game engine, and the default budgets.

A design is modelled in millimetres, Z up (CAD). Each preset says how the asset is handed to an engine:

    gltf     glTF 2.0 binary (GLB): metres, +Y up (the glTF definition). Collision nodes carry extras.
    godot    GLB, metres, +Y up. Collision nodes end in "-convcolonly" (Godot's import hint: a convex shape only).
    unity    FBX in metres (Unity's import scale 1), plus the GLB. Collision objects end in "_collider".
    unreal   FBX in centimetres, Z up, plus the GLB. Collision hulls are named UCX_<asset>_LOD0_NN (Unreal's
             convention: UCX_ plus the render mesh's name).

GLB is always written (form/meshio.py, pure numpy, so a GLB never depends on Blender's exporter). FBX and USD come
from Blender's own exporters. LODs are separate nodes named <asset>_LOD0 .. <asset>_LOD3 (Unity and Unreal read the
suffix as LOD levels).

Budgets are triangle ceilings per LOD (a LOD passes when it has at most 2% more triangles than its budget; the report
gives how full each one is). The defaults are a mid-size prop's and are proposed values, not engine rules.
"""
from __future__ import annotations

import numpy as np

PRESETS = {
    "gltf": {"label": "glTF 2.0 (GLB)", "unit": "m", "scale": 0.001, "up": "Y", "formats": ("glb",),
             "collision": "{asset}_collision_{i:02d}", "collision_extras": True},
    "godot": {"label": "Godot 4 (GLB)", "unit": "m", "scale": 0.001, "up": "Y", "formats": ("glb",),
              "collision": "{asset}_{i:02d}-convcolonly", "collision_extras": True},
    "unity": {"label": "Unity (FBX, metres)", "unit": "m", "scale": 0.001, "up": "Y", "formats": ("glb", "fbx"),
              "collision": "{asset}_{i:02d}_collider", "collision_extras": False},
    "unreal": {"label": "Unreal Engine (FBX, centimetres, Z up)", "unit": "cm", "scale": 0.1, "up": "Z",
               "formats": ("glb", "fbx"), "collision": "UCX_{asset}_LOD0_{i:02d}", "collision_extras": False},
}
EXTRA_FORMATS = ("fbx", "usd")             # any preset may ask for these as well (Blender's exporters)
LOD_NAME = "{asset}_LOD{i}"
DEFAULT_BUDGETS = (12000, 6000, 2500, 800)  # triangles, LOD0..LOD3 (a mid-size prop; proposed, not a rule)
MIN_BUDGET, MAX_BUDGET = 12, 2_000_000
BUDGET_TOLERANCE = 0.02                     # a LOD passes with up to 2% more triangles than its budget
TEXTURE_PX = (1024, 2048, 4096)
BAKE = {
    # fast: CPU friendly (a 1k bake of a prop in well under a minute on a laptop CPU); quality: more AO samples
    "fast": {"samples": 8, "ao_samples": 16, "margin_px": 8, "device": "CPU"},
    "quality": {"samples": 32, "ao_samples": 128, "margin_px": 16, "device": "AUTO"},
}
MAPS = ("base_color", "normal", "orm", "ao")    # ORM: R ambient occlusion, G roughness, B metallic (glTF reads G/B)
PIVOTS = ("bottom_center", "center", "origin")


def preset(name: str) -> dict:
    p = PRESETS.get(str(name or "gltf").lower())
    if p is None:
        raise ValueError(f"Unknown engine preset “{name}”. Presets: {', '.join(PRESETS)}.")
    return {"id": str(name or "gltf").lower(), **p}


def budgets(b=None) -> list[int]:
    """Four triangle budgets, LOD0 first, each at most its predecessor. Raises ValueError naming what is wrong."""
    if b is None:
        return list(DEFAULT_BUDGETS)
    if isinstance(b, dict):
        b = [x for x in (b.get(f"LOD{i}", b.get(f"lod{i}")) for i in range(4)) if x is not None]
    if not isinstance(b, (list, tuple)) or not 1 <= len(b) <= 4:
        raise ValueError("budgets must list 1 to 4 triangle counts, LOD0 first.")
    out = []
    for i, x in enumerate(b):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not float(x).is_integer():
            raise ValueError(f"budget LOD{i} must be a whole number of triangles.")
        x = int(x)
        if not MIN_BUDGET <= x <= MAX_BUDGET:
            raise ValueError(f"budget LOD{i} = {x} is outside {MIN_BUDGET}..{MAX_BUDGET} triangles.")
        if out and x > out[-1]:
            raise ValueError(f"budget LOD{i} ({x}) is above LOD{i - 1} ({out[-1]}); each LOD has at most the "
                             "triangles of the one before.")
        out.append(x)
    return out


def texture_px(px) -> int:
    px = int(px or 1024)
    if px not in TEXTURE_PX:
        raise ValueError(f"texture_px must be one of {', '.join(map(str, TEXTURE_PX))}.")
    return px


def to_engine(P_mm: np.ndarray, pre: dict) -> np.ndarray:
    """Positions in the preset's units and axes from millimetres, Z up. Y up: (x, y, z) -> (x, z, -y)."""
    P = np.asarray(P_mm, dtype=np.float64) * float(pre["scale"])
    if pre["up"] == "Y":
        P = np.stack([P[:, 0], P[:, 2], -P[:, 1]], axis=1)
    return P


def from_engine(P: np.ndarray, pre: dict) -> np.ndarray:
    """The inverse of to_engine: back to millimetres, Z up."""
    P = np.asarray(P, dtype=np.float64)
    if pre["up"] == "Y":
        P = np.stack([P[:, 0], -P[:, 2], P[:, 1]], axis=1)
    return P / float(pre["scale"])


def pivot_offset(P_mm: np.ndarray, pivot: str) -> np.ndarray:
    """The translation (mm) that puts the asset's pivot at the origin: bottom_center (the middle of the footprint, on
    the floor: props stand on the ground), center (the bounding box centre) or origin (the design's own origin)."""
    if pivot not in PIVOTS:
        raise ValueError(f"pivot must be one of {', '.join(PIVOTS)}.")
    P = np.asarray(P_mm, dtype=np.float64)
    lo, hi = P.min(0), P.max(0)
    if pivot == "origin":
        return np.zeros(3)
    c = (lo + hi) / 2
    if pivot == "bottom_center":
        c[2] = lo[2]
    return -c


def collision_name(pre: dict, asset: str, i: int) -> str:
    return pre["collision"].format(asset=asset, i=i)


def lod_name(asset: str, i: int) -> str:
    return LOD_NAME.format(asset=asset, i=i)


def safe_name(name: str) -> str:
    s = "".join(c if c.isalnum() else "_" for c in str(name or "asset")).strip("_")
    return (s or "asset")[:48]
