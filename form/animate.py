"""Motion from real geometry: turntables and parameter morphs as GIF / animated WebP.

Every morph frame is a separate kernel build of interpolated parameters, so the
animation shows what the recipe actually does between two designs, constraints
included. Frames that do not build are skipped and reported.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from . import render
from .studio import H


def _feats(recipe):
    return [{"id": f.id, "label": f.label} for f in recipe.features]


def _bbox(view_data):
    lo, hi = None, None
    for m in view_data["mesh"]:
        P = render._arr(m["positions"], np.float32, 3)
        a, b = P.min(0), P.max(0)
        lo = a if lo is None else np.minimum(lo, a)
        hi = b if hi is None else np.maximum(hi, b)
    return lo, hi


def _save(frames: list, out: str | Path, ms: int) -> dict:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".webp":
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=ms, loop=0, quality=82, method=6)
    else:
        pal = frames[0].convert("P", palette=Image.ADAPTIVE, colors=128)
        q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], duration=ms, loop=0, optimize=True, disposal=1)
    return {"file": str(out), "frames": len(frames), "bytes": out.stat().st_size, "fps": round(1000 / ms, 1)}


def turntable(studio, p: dict, out, frames: int = 36, elevation: float = 24, size=(640, 480), ms: int = 70) -> dict:
    recipe = studio.recipe(p)
    v = studio.view(p)
    lo, hi = _bbox(v)
    imgs = []
    for i in range(frames):
        az = -90 + 360 * i / frames
        imgs.append(render.render_png(v, _feats(recipe), camera=(az, elevation), frame_box=(lo, hi), size=size,
                                      overlay=False, title=f"{p['name']}  r{p['head']:02d}",
                                      caption=f"{recipe.title} - built by build123d/OCCT, rendered headless by Form Studio",
                                      as_image=True))
    return _save(imgs, out, ms) | {"kind": "turntable"}


def _num(x, step):
    dec = 0 if step >= 1 else min(3, max(0, -int(math.floor(math.log10(step)))))
    return f"{x:.{dec}f}"


def _ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


def morph(studio, p: dict, a: dict, b: dict, out, frames: int = 24, size=(640, 480), ms: int = 90, title: str = "",
          azimuth: float = -55, elevation: float = 26, hold: int = 6, spin: float = 40) -> dict:
    """Interpolate every numeric parameter from a to b, build each frame, render with fixed framing."""
    recipe = studio.recipe(p)
    changed = [k for k in a if abs(a[k] - b[k]) > 1e-9]
    views, skipped = [], []
    for i in range(frames):
        t = _ease(i / (frames - 1))
        vals = {}
        for k in a:
            sp = recipe.spec(k)
            x = a[k] + (b[k] - a[k]) * t
            vals[k] = float(round(x)) if sp.step >= 1 and sp.unit in ("", "u") else round(x, 4)
        try:
            v = studio._k("view", key="mv-" + H(studio.rid(p), vals), recipe_id=studio.rid(p), values=vals, tol=0.08, p=p)
            views.append((t, vals, v))
        except Exception as e:                                   # recipe constraint or kernel failure: show it, don't fake it
            skipped.append({"t": round(t, 3), "reason": str(e)[:160]})
    if len(views) < 2:
        raise ValueError("Fewer than two frames built; nothing to animate. " + (skipped[0]["reason"] if skipped else ""))
    lo = np.min([_bbox(v)[0] for _, _, v in views], axis=0)
    hi = np.max([_bbox(v)[1] for _, _, v in views], axis=0)
    imgs = []
    for i, (t, vals, v) in enumerate(views):
        cap = "   ".join(f"{recipe.spec(k).label.lower()} {_num(vals[k], recipe.spec(k).step)} {recipe.spec(k).unit}".strip()
                         for k in changed[:3])
        imgs.append(render.render_png(v, _feats(recipe), camera=(azimuth + spin * t, elevation), frame_box=(lo, hi), size=size,
                                      overlay=False, title=title or p["name"], caption=cap, as_image=True))
    imgs = [imgs[0]] * hold + imgs + [imgs[-1]] * hold + imgs[::-1]       # pause, go, pause, come back
    info = _save(imgs, out, ms)
    return info | {"kind": "morph", "built_frames": len(views), "skipped": skipped, "changed": changed}


# ---- turntable export: GIF, animated WebP, a PNG sequence, or MP4 (with ffmpeg) -------------------------------------
FORMATS = ("gif", "webp", "png", "mp4")


def ffmpeg() -> str | None:
    """The ffmpeg program, if one is installed (PATH, or the imageio-ffmpeg wheel). MP4 needs it; nothing else does."""
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def export(studio, p: dict, fmt: str = "webp", frames: int = 36, elevation: float = 24, size=(960, 720), fps: int = 24) -> dict:
    """A turntable of the head revision rendered from the real mesh. gif / webp: one animated file; png: a folder of
    numbered frames and a .zip of them; mp4: H.264 through ffmpeg (refused with the reason when it is not installed).
    Cached per geometry key, format, frame count and elevation."""
    import json
    import shutil
    import subprocess
    import zipfile
    from .studio import StudioError
    fmt = (fmt or "webp").lower().lstrip(".")
    if fmt not in FORMATS:
        raise StudioError(f"Unknown format “{fmt}”.", "Use " + ", ".join(FORMATS) + ".")
    exe = ffmpeg() if fmt == "mp4" else None
    if fmt == "mp4" and not exe:
        raise StudioError("MP4 needs ffmpeg, which is not installed.", "Install ffmpeg (brew install ffmpeg), or export a PNG sequence or WebP.")
    frames = max(12, min(int(frames), 180))
    elevation = max(-60.0, min(float(elevation), 80.0))
    key = H("turntable", studio.keys(p)["geometry"], fmt, frames, elevation, list(size), fps)[:12]
    d = studio.dir(p["id"]) / "artifacts" / "motion"
    stem = f"r{p['head']:02d}-turntable-{key}"
    meta_f = d / (stem + ".json")
    if meta_f.is_file():
        info = json.loads(meta_f.read_text(encoding="utf-8"))
        if Path(info["file"]).exists():
            return info | {"cached": True}
    recipe = studio.recipe(p)
    v = studio.view(p)
    lo, hi = _bbox(v)
    imgs = [render.render_png(v, _feats(recipe), camera=(-90 + 360 * i / frames, elevation), frame_box=(lo, hi), size=size,
                              overlay=False, title=f"{p['name']}  r{p['head']:02d}", caption=recipe.title, as_image=True)
            for i in range(frames)]
    d.mkdir(parents=True, exist_ok=True)
    still = d / (stem + "-still.png")
    imgs[frames // 8].convert("RGB").save(still)
    ms = round(1000 / fps)
    if fmt in ("gif", "webp"):
        info = _save(imgs, d / f"{stem}.{fmt}", ms) | {"fps": fps}
    else:
        folder = d / (stem + "-frames")
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        for i, im in enumerate(imgs):
            im.convert("RGB").save(folder / f"frame_{i:04d}.png")
        if fmt == "png":
            out = d / f"{stem}-png.zip"
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for f in sorted(folder.iterdir()):
                    z.write(f, f"{stem}/{f.name}")
        else:
            out = d / f"{stem}.mp4"
            r = subprocess.run([exe, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(folder / "frame_%04d.png"),
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not out.is_file():
                raise StudioError("ffmpeg could not write the MP4.", (r.stderr or "").strip()[-300:])
            shutil.rmtree(folder, ignore_errors=True)
        info = {"file": str(out), "frames": frames, "bytes": out.stat().st_size, "fps": fps}
        if fmt == "png":
            info["folder"] = str(folder)
    info |= {"kind": "turntable", "fmt": fmt, "rev": p["head"], "elevation": elevation, "size": list(size),
             "still": str(still), "seconds": round(frames / fps, 2), "renderer": "Form Studio's headless renderer, from the kernel's mesh"}
    meta_f.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info | {"cached": False}
