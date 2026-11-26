"""Re-encode a direction's PNGs smaller: drop the unused alpha channel, round each channel to 7 bits (a step of
2 in 255, not visible), strongest deflate. About 30 % smaller.

    .venv/bin/python docs/design/directions/tools/optimise.py h
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
total = 0
for d in sys.argv[1:]:
    for p in sorted((ROOT / d).glob("*.png")):
        before = p.stat().st_size
        a = np.asarray(Image.open(p).convert("RGB")).astype(int)
        a = (((a + 1) >> 1) << 1).clip(0, 255).astype("uint8")
        Image.fromarray(a).save(p, optimize=True, compress_level=9)
        total += p.stat().st_size
        print(f"{p.relative_to(ROOT)}  {before // 1024} -> {p.stat().st_size // 1024} kB")
print(f"total {total / 1e6:.2f} MB")
