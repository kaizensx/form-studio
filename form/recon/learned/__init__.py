"""The optional learned engine for mesh to CAD: CAD-Recode, opt-in, installed by the person, run offline.

CAD-Recode (huggingface.co/filapro/cad-recode) reads a point cloud of a part and writes a CadQuery program for it.
Its weights are licensed CC BY-NC 4.0: **non-commercial use only**. So Form Studio never bundles them, never fetches
them by itself, and its tests never download them. A person installs it through the installer
(`form install recon.learned`), which shows the download size (3.09 GB of weights plus the PyTorch and Transformers
libraries) and the licence before anything is downloaded, and the download itself refuses to start unless the
licence is accepted on its command line.

When it is installed, the pipeline (pipeline.py) asks it for one more candidate beside the program route:

    1. engine.py     the model writes a CadQuery program for the mesh (offline, on MPS or the CPU)
    2. cq.py         the program is read, never executed, as sketch extrusions; anything outside that subset is refused
    3. translate.py  placed on the mesh, every level, side and circle snapped to the mesh, values pooled into Params
    4. candidate()   built as the Studio builds it and verified against the mesh (valid, one solid, within the limit)

A candidate that does not verify is reported and never returned as the result. Not installed, nothing changes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

NAME = "CAD-Recode"
REPO = "filapro/cad-recode"
REVISION = "main"
TOKENIZER_REPO = "Qwen/Qwen2-1.5B"
LICENCE = "CC BY-NC 4.0 (non-commercial use only)"
LICENCE_ID = "cc-by-nc-4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
WEIGHTS_BYTES = 3_090_000_000          # model.safetensors, as listed on the model page
SIZE = "3.09 GB of weights, plus about 1 GB of PyTorch and Transformers"
WEIGHT_FILES = ("config.json", "model.safetensors")
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt")
LIBRARIES = ("torch", "transformers", "safetensors")
PIP = ("torch>=2.2,<3", "transformers>=4.45,<5", "safetensors>=0.4")
MARKER = "form-download.json"          # written last by the download: the folder is complete


def model_dir() -> Path:
    """Where the weights live: $FORM_CADRECODE_DIR, else <data folder>/models/cad-recode."""
    env = os.environ.get("FORM_CADRECODE_DIR")
    if env:
        return Path(env).expanduser()
    try:
        from ... import config
        data = Path(config.load()["data"]["dir"]).expanduser()
    except Exception:                                   # noqa: BLE001
        data = Path(os.environ.get("FORM_DATA") or "~/FORM").expanduser()
    return data / "models" / "cad-recode"


def status(folder: Path | None = None) -> dict:
    """Is the engine installed? Never downloads, never imports torch."""
    folder = Path(folder) if folder else model_dir()
    libs = [m for m in LIBRARIES if importlib.util.find_spec(m) is None]
    w = folder / "model.safetensors"
    weights = (folder / MARKER).is_file() and w.is_file() and all((folder / f).is_file() for f in WEIGHT_FILES) \
        and all((folder / "tokenizer" / f).is_file() for f in TOKENIZER_FILES)
    out = {"name": NAME, "installed": not libs and weights, "folder": str(folder), "licence": LICENCE,
           "licence_url": LICENCE_URL, "size": SIZE}
    if libs:
        out["missing_libraries"] = libs
    if not weights:
        out["missing_weights"] = True
    out["status"] = "installed" if out["installed"] else "not installed"
    return out


def candidate(V, F, tol, name="part", limit=None, deadline=None, generate=None, folder=None) -> dict:
    """One more reconstruction candidate from the learned engine, built and verified like the program route's.

    `generate(V, F)` returns {"code": CadQuery text, ...}; by default the installed model (engine.generate). Returns
    the shape of program.recipe: {"report", "source", "verified", "shape", "P", "T", "cmp", "refs", "params"}; the
    report always says why a candidate was not verified. Never raises."""
    t0 = time.perf_counter()
    limit = tol if limit is None else limit
    rep = {"method": f"learned engine ({NAME})", "engine": NAME, "licence": LICENCE}
    try:
        if generate is None:
            from . import engine
            folder = Path(folder) if folder else model_dir()
            gen = engine.generate(V, F, folder, deadline=deadline)
        else:
            gen = generate(V, F)
        code = str(gen.get("code") or "")
        rep["model_seconds"] = gen.get("seconds")
        rep["device"] = gen.get("device")
    except Exception as e:                              # noqa: BLE001
        rep["error"] = f"The model did not run: {type(e).__name__}: {e}"[:300]
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep, "verified": False}
    from . import cq, translate
    try:
        plan = cq.parse(code)
        src, info = translate.source(plan, V, tol, name=name)
    except cq.Unsupported as e:
        rep["error"] = f"The model's program is not a plain sketch-and-extrude program Form Studio can read: {e}"[:300]
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep, "verified": False}
    except Exception as e:                              # noqa: BLE001
        rep["error"] = f"The model's program could not be placed on the mesh: {type(e).__name__}: {e}"[:300]
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep, "verified": False}
    pool = info.pop("_pool")
    rep.update({k: (round(v, 6) if isinstance(v, float) else v) for k, v in info.items()})
    import numpy as np
    from .. import program, solid, verify
    try:
        stages, _ = program.build_stages(src)
        shape = stages[-1].shape
        ck = solid.check(shape.wrapped)
        fl = []
        P, T = solid.tessellate(shape, max(tol / 10, 1e-4), faces_out=fl)
        diag = float(np.linalg.norm(np.ptp(V, axis=0)))
        cmp = verify.compare(V, F, P, T, spacing=max(diag / 200, 1e-3), shape=shape.wrapped, check_above=limit, faces=fl)
    except Exception as e:                              # noqa: BLE001
        rep["error"] = f"The translated recipe did not build: {type(e).__name__}: {e}"[:300]
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep, "verified": False, "source": src}
    ok = bool(ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit)
    rep.update({"kind": "learned", "base": "sketches and extrusions", "valid": ck["valid"], "solids": ck["solids"],
                "volume_mm3": round(ck["volume_mm3"], 4), "verified": ok,
                # every face of the result is made by a feature: no part of it is kept as the mesh
                "editable_pct": 100.0 if ok else 0.0, "driven_by_params_pct": 100.0 if ok else 0.0,
                "params": len(pool.params), "param_table": [dict(q) for q in pool.params],
                **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")}})
    if not ok:
        rep["error"] = (f"The learned candidate is {cmp['hausdorff_mm']:.4f} mm from the mesh (limit {limit:.4f} mm)"
                        if ck["valid"] and ck["solids"] == 1 else
                        f"The learned candidate is not one valid solid ({ck['solids']} solids, valid {ck['valid']}).")
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    return {"report": rep, "source": src, "verified": ok, "shape": shape.wrapped, "P": P, "T": T, "cmp": cmp,
            "refs": {}, "params": pool.params}


CANDIDATE = candidate          # the real one: a test that replaces `candidate` is run in its own process


def describe() -> dict:
    """What the installer shows before anything is downloaded."""
    return {"name": NAME, "model": f"https://huggingface.co/{REPO}", "licence": LICENCE, "licence_url": LICENCE_URL,
            "size": SIZE, "weights_bytes": WEIGHTS_BYTES, "folder": str(model_dir()),
            "note": json.dumps({"files": list(WEIGHT_FILES), "tokenizer": TOKENIZER_REPO})}
