"""Cleaner edges for the part cut-outs, used by direction H (the shared assets stay as they are for A, B and C).

Reads assets/part-*.png (made by cutout.py), smooths the stair-stepped outline, pulls it in past the floor-coloured
fringe, and repaints fringe pixels with the nearest colour from inside the part. Nothing is redrawn.

    .venv/bin/python docs/design/directions/tools/refine_cutout.py
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "h" / "assets"
JOBS = [("part-sensor-case-dark", 1), ("part-sensor-case-light", 2), ("part-build-6of12-dark", 1)]


def refine(name, inset):
    im = Image.open(ROOT / "assets" / f"{name}.png").convert("RGBA")
    px = np.asarray(im).astype(float)
    rgb, a = px[..., :3], px[..., 3] / 255
    solid = ndi.gaussian_filter((a > .5).astype(float), 1.6) > .5          # round off the stair steps
    solid = ndi.binary_erosion(solid, iterations=inset)                     # step inside the fringe
    inner = ndi.binary_erosion(solid, iterations=3)
    _, (iy, ix) = ndi.distance_transform_edt(~inner, return_indices=True)   # nearest pixel well inside the part
    near = rgb[iy, ix]
    lum, lum_in = rgb.mean(-1), near.mean(-1)
    light = name.endswith("light")
    fringe = ~inner & ((lum > lum_in + 6) if light else (lum < lum_in - 60) & ~solid)
    rgb = np.where(fringe[..., None], near, rgb)
    alpha = ndi.gaussian_filter(solid.astype(float), .75)
    out = np.dstack([rgb, alpha * 255]).round().astype("uint8")
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, "RGBA").save(OUT / f"{name}.png", optimize=True)
    print(name, im.size, (OUT / f"{name}.png").stat().st_size // 1024, "kB")


for job in JOBS:
    refine(*job)
