"""Turn the Blender renders into the mockups' assets: feather each picture's border (so the shadow catcher never
shows the picture's rectangle), save WebP, cut the stress map's lit part for the bloom, and write assets/geo.js.

    .venv/bin/python docs/design/directions/i/tools/assets.py GEO RENDERS
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

geo, rend = Path(sys.argv[1]), Path(sys.argv[2])
A = Path(__file__).resolve().parents[1] / "assets"
s = lambda t: t * t * (3 - 2 * t)
for n in ["mount-s1", "mount-s2", "mount-s3", "mount-s5", "mount-s8", "mount-heat", "cam-stock", "plate-1", "plate-2"]:
    im = np.asarray(Image.open(rend / f"{n}.png").convert("RGBA")).astype(np.float32)
    h, w = im.shape[:2]; m = 160
    fx = np.clip(np.minimum(np.arange(w), w - 1 - np.arange(w)) / m, 0, 1); fy = np.clip(np.minimum(np.arange(h), h - 1 - np.arange(h)) / m, 0, 1)
    im[..., 3] *= s(fx)[None, :] * s(fy)[:, None]
    Image.fromarray(im.astype(np.uint8)).save(A / f"{n}.webp", quality=95, method=6)
    if n == "mount-heat":                                   # only what is lit blooms
        k = np.clip((im[..., 2] - im[..., 0] - 18) / 60, 0, 1); g = im.copy(); g[..., 3] *= k
        Image.fromarray(g.astype(np.uint8)).save(A / "mount-glow.webp", quality=92, method=6)
    if n == "mount-s8":
        Image.fromarray(im.astype(np.uint8)).resize((640, 640), Image.LANCZOS).save(A / "thumb-motor-mount.webp", quality=95)
proj = json.load(open(rend / "proj.json"))
(A / "geo.js").write_text("// Written by tools/assets.py from the kernel build and the renders: projections, hidden-line views, computed numbers.\n"
    f"const PROJ = {json.dumps(proj)};\nconst CAM = {json.dumps(json.load(open(geo / 'cam.json')))};\nconst META = {json.dumps(json.load(open(geo / 'meta.json')))};\n" + (geo / "hlr.js").read_text())
