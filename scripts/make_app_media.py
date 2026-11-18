"""Smooth animations of the real app for the README (animated WebP).

    .venv/bin/python scripts/make_app_media.py                 # capture every clip, then encode
    .venv/bin/python scripts/make_app_media.py --encode-only   # encode frames captured before
    .venv/bin/python scripts/make_app_media.py --clips hinge   # only some clips

The frames come from scripts/media/app_clips.py, run in the real window by the app's own test driver
(python -m form.app --uitest) with a fresh data folder and no model: the design is built by the kernel and sliced
by the slicer installed on this computer. Frames are 30 per second, eased, grabbed at the screen's pixel ratio and
scaled down, so the result is smooth and sharp.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / ".dev" / "media-frames"
README = ROOT / "docs" / "images"
FPS = 30

# clip → README animated WebP (width, quality, keep every nth frame). The website draws the app in code instead:
# it has no video and no animated images.
OUT = {
    "orbit": {"readme": ("app-orbit.webp", 960, 70, 1)},
    "hinge": {"readme": ("assembly-joint.webp", 760, 76, 1)},
    "print": {"readme": ("print-sim-play.webp", 960, 70, 1)},
}


def capture(clips: list[str], size: str) -> None:
    with tempfile.TemporaryDirectory(prefix="form-media-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        (data / ".form-setup.json").write_text(json.dumps({"ts": 1, "version": "media", "how": "done"}), encoding="utf-8")
        env = dict(os.environ, FORM_DATA=str(data), FORM_CONFIG=str(Path(tmp) / "studio.toml"), FORM_NO_UPDATE_CHECK="1",
                   FORM_UITEST_TMP=tmp, FORM_SECRETS=str(Path(tmp) / "secrets.json"), FORM_NO_AUTO_SETUP="1",
                   FORM_PROVIDERS_OFFLINE="1", FORM_UITEST_OUT=str(FRAMES), FORM_REDUCED_MOTION="0",
                   FORM_UITEST_LAX="1", FORM_MEDIA_CLIPS=",".join(clips), FORM_UITEST_WATCHDOG="2400")
        t0 = time.time()
        r = subprocess.run([sys.executable, "-m", "form.app", "--uitest", str(ROOT / "scripts" / "media" / "app_clips.py"),
                            "--size", size], cwd=ROOT, env=env)
        print(f"capture: {time.time() - t0:.0f}s, exit {r.returncode}")
        if r.returncode:
            sys.exit(r.returncode)


def encode(clip: str) -> None:
    from PIL import Image
    files = sorted((FRAMES / clip).glob("*.png"))
    if not files:
        print(f"{clip}: no frames")
        return
    name, width, quality, nth = OUT[clip]["readme"]
    imgs = []
    for f in files[::nth]:
        im = Image.open(f).convert("RGB")
        imgs.append(im.resize((width, round(im.height * width / im.width)), Image.LANCZOS))
    dest = README / name
    ms = round(1000 * nth / FPS)
    imgs[0].save(dest, save_all=True, append_images=imgs[1:], duration=ms, loop=0, quality=quality, method=4)
    print(json.dumps({"file": str(dest.relative_to(ROOT)), "frames": len(imgs), "fps": round(FPS / nth, 1),
                      "seconds": round(len(imgs) * ms / 1000, 1), "size": f"{imgs[0].width}x{imgs[0].height}",
                      "kb": dest.stat().st_size // 1024}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=",".join(OUT))
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--encode-only", action="store_true")
    a = ap.parse_args()
    clips = [c for c in a.clips.split(",") if c]
    if not a.encode_only:
        capture(clips, a.size)
    for c in clips:
        encode(c)


if __name__ == "__main__":
    main()
