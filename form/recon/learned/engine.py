"""CAD-Recode inference, offline: a point cloud of the mesh in, CadQuery code out. Imported only when the engine is
installed (torch and transformers are not Form Studio dependencies).

The model (huggingface.co/filapro/cad-recode) is Qwen2-1.5B with a point projector in front of it: 256 points of
the part's surface, centred and scaled into the unit cube, become the first 256 input embeddings, followed by the
start token; the model then writes the CadQuery program. Which projector the weights carry (a plain linear layer on
x, y, z, or a linear layer on Fourier features of them) is read from the weights themselves. Nothing is fetched from
the network here: the files are read from the folder the installer downloaded them to (HF_HUB_OFFLINE is set).

Speed on Apple silicon (MPS) or a CPU is not measured by Form Studio; the time each run takes is reported.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

POINTS = 256
SAMPLES = 8192
MAX_NEW_TOKENS = 768

_cache: dict = {}


def surface_points(V, F, n: int = SAMPLES, seed: int = 0) -> np.ndarray:
    """n points spread over the mesh surface by area."""
    rng = np.random.default_rng(seed)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    A = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    t = rng.choice(len(F), n, p=A / A.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return (1 - s)[:, None] * a[t] + (s * (1 - r2))[:, None] * b[t] + (s * r2)[:, None] * c[t]


def farthest(P: np.ndarray, k: int = POINTS, seed: int = 0) -> np.ndarray:
    """k points of P chosen by farthest-point sampling."""
    rng = np.random.default_rng(seed)
    idx = [int(rng.integers(len(P)))]
    d = np.linalg.norm(P - P[idx[0]], axis=1)
    for _ in range(1, min(k, len(P))):
        j = int(np.argmax(d))
        idx.append(j)
        d = np.minimum(d, np.linalg.norm(P - P[j], axis=1))
    return P[idx]


def normalised_cloud(V, F) -> np.ndarray:
    """The model's input: POINTS surface points, centred on the bounding box and scaled so its largest side is 2."""
    lo, hi = V.min(axis=0), V.max(axis=0)
    c, s = (lo + hi) / 2, 2.0 / max(float((hi - lo).max()), 1e-9)
    return farthest((surface_points(V, F) - c) * s).astype(np.float32)


def _load(folder: Path):
    key = str(folder)
    if key in _cache:
        return _cache[key]
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import torch
    from safetensors.torch import load_file
    from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

    state = load_file(str(folder / "model.safetensors"))
    proj = {k: v for k, v in state.items() if k.startswith("point_encoder")}
    w = next((v for k, v in proj.items() if k.endswith("weight") and v.ndim == 2), None)
    if w is None:
        raise RuntimeError("the weights carry no point projector (point_encoder.*)")
    fourier = int(w.shape[1]) != 3

    class PointEncoder(torch.nn.Module):
        def __init__(self, hidden, n_in):
            super().__init__()
            self.register_buffer("frequencies", 2.0 ** torch.arange(8, dtype=torch.float32), persistent=False)
            self.projection = torch.nn.Linear(n_in, hidden)

        def forward(self, pts):
            if not fourier:
                return self.projection(pts)
            x = (pts.unsqueeze(-1) * self.frequencies).view(*pts.shape[:-1], -1)
            return self.projection(torch.cat((pts, x.sin(), x.cos()), dim=-1))

    class CADRecode(Qwen2ForCausalLM):
        def __init__(self, config):
            super().__init__(config)
            self.point_encoder = PointEncoder(config.hidden_size, int(w.shape[1]))

    cfg = Qwen2Config.from_pretrained(str(folder))
    model = CADRecode(cfg)
    remap = {}
    for k, v in proj.items():                           # either point_encoder.weight or point_encoder.projection.weight
        remap["point_encoder.projection." + k.split(".")[-1]] = v
    state = {k: v for k, v in state.items() if not k.startswith("point_encoder")} | remap
    missing, unexpected = model.load_state_dict(state, strict=False)
    if [m for m in missing if not m.endswith("lm_head.weight")] or unexpected:
        raise RuntimeError(f"the weights do not fit the model ({len(missing)} missing, {len(unexpected)} unexpected)")
    if any(m.endswith("lm_head.weight") for m in missing):
        model.tie_weights()
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    model = model.to(dev).eval()
    tok = AutoTokenizer.from_pretrained(str(folder / "tokenizer"), padding_side="left")
    _cache[key] = (model, tok, dev)
    return _cache[key]


def generate(V, F, folder: Path, deadline: float | None = None) -> dict:
    """{"code", "seconds", "device"}: the CadQuery program the model writes for this mesh."""
    import torch
    t0 = time.perf_counter()
    model, tok, dev = _load(Path(folder))
    pts = torch.from_numpy(normalised_cloud(V, F))[None].to(dev)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    start = tok("<|im_start|>")["input_ids"][0]
    ids = torch.tensor([[pad] * POINTS + [start]], device=dev)
    mask = torch.tensor([[-1] * POINTS + [1]], device=dev)
    with torch.no_grad():
        emb = model.get_input_embeddings()(ids)
        emb[mask == -1] = model.point_encoder(pts).reshape(-1, emb.shape[-1]).to(emb.dtype)
        mask = mask.clone()
        mask[mask == -1] = 1
        budget = MAX_NEW_TOKENS
        out = model.generate(inputs_embeds=emb, attention_mask=mask, max_new_tokens=budget, do_sample=False,
                             pad_token_id=pad, eos_token_id=tok.eos_token_id)
    code = tok.decode(out[0], skip_special_tokens=True)
    if "<|im_start|>" in code:
        code = code.split("<|im_start|>")[-1]
    return {"code": code.strip(), "seconds": round(time.perf_counter() - t0, 2), "device": dev}


# ---- out of process: the engine's own environment (form/engines.py) ----------------------------------------------

CHILD = "from form.recon.learned.engine import _main; _main()"


def generate_in(python, V, F, folder: Path, deadline: float | None = None) -> dict:
    """generate() run by another interpreter (the engine's own environment, which has PyTorch): the mesh goes in a
    file, the program comes back as JSON. Killed at the deadline; the child also ends when this process ends."""
    import json
    import subprocess
    import tempfile
    from ... import engines
    with tempfile.TemporaryDirectory(prefix="form-learned-") as tmp:
        src, out = Path(tmp) / "mesh.npz", Path(tmp) / "out.json"
        np.savez(src, V=np.asarray(V, dtype=float), F=np.asarray(F, dtype=np.int64))
        wait = None if deadline is None else max(1.0, deadline - time.perf_counter())
        try:
            r = subprocess.run([str(python), "-c", CHILD, str(src), str(folder), str(out), str(os.getpid())],
                               env=engines.child_env(), capture_output=True, text=True, timeout=wait,
                               stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"the model did not finish within {wait:.0f} s") from None
        if r.returncode != 0 or not out.is_file():
            lines = (r.stderr or r.stdout or "").strip().splitlines()
            raise RuntimeError((lines[-1] if lines else f"exit code {r.returncode}")[:300])
        return json.loads(out.read_text(encoding="utf-8"))


def _main() -> None:                                    # pragma: no cover - runs in the engine's own interpreter
    import json
    import sys
    import threading
    src, folder, out, parent = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])

    def watch():                                        # the process that asked is gone: so is this one
        while True:
            time.sleep(1.0)
            if os.getppid() != parent:
                os._exit(1)
    threading.Thread(target=watch, daemon=True).start()
    d = np.load(src)
    got = generate(d["V"], d["F"], Path(folder))
    Path(out).write_text(json.dumps(got), encoding="utf-8")
