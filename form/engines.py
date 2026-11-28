"""Managed engine environments: an optional engine that needs Python libraries Form Studio does not carry gets a Python
of its own, made with one click from Settings > Engines & software, and runs out of process with that interpreter.

    <data folder>/.engines/
        .uv/<version>/uv            a pinned uv release, its SHA-256 checked against the value below before it is used
        .python/                    the Python 3.12 that uv installs for the engines (uv's managed CPython builds)
        recon.learned/              CAD-Recode: torch, transformers, safetensors (pinned)
        recon.cadfit/               CADFit: build123d, trimesh, scikit-learn, SciPy, manifold3d (pinned)
        game.coacd/                 CoACD: approximate convex decomposition for game collision (pinned)
        fea/                        strength studies: Netgen, scikit-fem, SciPy, PyAMG (pinned)
        robot.mujoco/               MuJoCo and yourdfpy: robot files loaded and stepped (pinned)

An environment is built in a temporary folder next to its final place and moved there only when every step worked
(uv venv, uv pip install, an import check, the engine's own extra step such as its weights). A failed or cancelled
install deletes the temporary folder, so whatever was there before is left as it was. `form-engine.json` is written
last: an environment without it is never used.

The engine's own code runs from Form Studio's source: the packaged app ships it as files under `engine_src/`
(packaging/form.spec), a source checkout uses the checkout. Nothing here runs at import; nothing downloads unless an
install the person started asks for it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

UV_VERSION = "0.13.7"
UV_BASE = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
# (os, machine) -> (release asset, its SHA-256 as published with the release)
UV_ASSETS = {
    ("darwin", "arm64"): ("uv-aarch64-apple-darwin.tar.gz", "81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731"),
    ("darwin", "x86_64"): ("uv-x86_64-apple-darwin.tar.gz", "20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7"),
    ("linux", "x86_64"): ("uv-x86_64-unknown-linux-gnu.tar.gz", "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83"),
    ("linux", "arm64"): ("uv-aarch64-unknown-linux-gnu.tar.gz", "71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc"),
    ("windows", "x86_64"): ("uv-x86_64-pc-windows-msvc.zip", "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021"),
}
PYTHON = "3.12"
MARKER = "form-engine.json"
STEP_TIMEOUT_S = 7200            # one step (a 1 GB PyTorch install, 3 GB of weights) may take this long

# What each engine's environment holds. Pins resolved with uv for Python 3.12 (macOS arm64 and Linux x86_64).
SPECS: dict[str, dict] = {
    "recon.learned": {
        "label": "CAD-Recode",
        "pins": ("torch==2.11.0", "transformers==4.57.6", "safetensors==0.8.0", "tokenizers==0.22.2",
                 "huggingface-hub==0.36.2", "numpy==2.5.5"),
        "check": "import torch, transformers, safetensors, numpy; import form.recon.learned.engine",
    },
    "recon.cadfit": {
        "label": "CADFit",
        # the same versions Form Studio's own environment is tested with; build123d builds CADFit's programs (cqrun)
        "pins": ("build123d==0.13.0", "numpy==2.5.4", "scipy==1.18.1", "scikit-learn==1.9.1", "trimesh==5.2.1",
                 "manifold3d==3.5.5"),
        "check": ("import trimesh, manifold3d, sklearn, scipy, build123d; "
                  "import form.recon.cadfit.driver, form.recon.cadfit.cqrun, form.recon.cadfit.vendor.greedy_search"),
    },
    "game.coacd": {
        "label": "CoACD",
        # CoACD 1.0.14 (MIT) ships abi3 wheels for macOS arm64, Linux x86_64/arm64 and Windows x86_64
        "pins": ("coacd==1.0.14", "numpy==2.5.4"),
        "check": "import coacd, numpy; import form.game.lod",
    },
    "fea": {
        "label": "Strength studies (FEA)",
        # Netgen meshes the B-rep (LGPL-2.1, unmodified wheels, with its own OCCT build netgen-occt, LGPL-2.1 with
        # the Open CASCADE exception); scikit-fem (BSD-3-Clause) gives the quadratic shape functions; SciPy
        # (BSD-3-Clause) and PyAMG (MIT) solve. Wheels for macOS arm64/x86_64, Linux x86_64 and Windows x86_64.
        "pins": ("netgen-mesher==6.2.2608", "netgen-occt==7.8.1", "scikit-fem==12.0.2", "scipy==1.18.1",
                 "pyamg==5.4.1", "numpy==2.5.5"),
        "check": ("import netgen.occ, netgen.meshing, skfem, scipy.sparse.linalg, pyamg, numpy; "
                  "import form.fea.core, form.fea.run, form.fea.verify, form.topo.run, form.topo.verify"),
    },
    "robot.mujoco": {
        "label": "MuJoCo",
        # MuJoCo 4.0.1 (Apache-2.0) and yourdfpy 0.0.60 (MIT): the robot files are loaded, and the MJCF stepped, here
        "pins": ("mujoco==4.0.1", "yourdfpy==0.0.60", "numpy==2.5.5"),
        "check": "import mujoco, yourdfpy, numpy; import form.robot",
    },
}


class EngineError(RuntimeError):
    pass


# ---- where things are ---------------------------------------------------------------------------------------------

def os_key() -> str:
    return "darwin" if sys.platform == "darwin" else "windows" if sys.platform.startswith("win") else "linux"


def machine_key() -> str:
    m = _platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64" if m in ("x86_64", "amd64") else m


def root(cfg: dict | None = None) -> Path:
    """$FORM_ENGINES_DIR, else <data folder>/.engines."""
    if os.environ.get("FORM_ENGINES_DIR"):
        return Path(os.environ["FORM_ENGINES_DIR"]).expanduser()
    if cfg is None:
        try:
            from . import config
            cfg = config.load()
        except Exception:                               # noqa: BLE001
            cfg = {"data": {"dir": os.environ.get("FORM_DATA") or "~/FORM"}}
    return Path(cfg["data"]["dir"]).expanduser() / ".engines"


def env_dir(eid: str, cfg: dict | None = None) -> Path:
    return root(cfg) / eid


def env_python(folder: Path) -> Path:
    return folder / ("Scripts/python.exe" if os_key() == "windows" else "bin/python")


def python(eid: str, cfg: dict | None = None) -> Path | None:
    """The engine environment's interpreter, when the environment is complete (its marker is there); else None."""
    d = env_dir(eid, cfg)
    py = env_python(d)
    return py if (d / MARKER).is_file() and py.exists() else None


def info(eid: str, cfg: dict | None = None) -> dict | None:
    try:
        return json.loads((env_dir(eid, cfg) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def src_root() -> Path:
    """The folder that holds the `form` package the engine environments import: engine_src/ in the packaged app, the
    checkout otherwise."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "engine_src"
    return Path(__file__).resolve().parent.parent


def child_env(extra: dict | None = None) -> dict:
    """The environment an engine's interpreter runs in: Form Studio's engine code on its path and nothing of the app's
    own Python (a packaged app's library path, a developer's virtualenv)."""
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONSTARTUP", "__PYVENV_LAUNCHER__"):
        env.pop(k, None)
    if getattr(sys, "frozen", False):                   # PyInstaller points the loader at the bundle: undo it
        for k in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            orig = env.pop(k + "_ORIG", None)
            if orig is not None:
                env[k] = orig
            else:
                env.pop(k, None)
    env.update(PYTHONPATH=str(src_root()), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    env.update(extra or {})
    return env


def uv_env(r: Path) -> dict:
    """uv kept to the engines folder: its own Python downloads, no user configuration, no shared cache."""
    env = child_env()
    env.pop("PYTHONPATH", None)
    env.update(UV_PYTHON_INSTALL_DIR=str(r / ".python"), UV_PYTHON_PREFERENCE="only-managed", UV_NO_CONFIG="1",
               UV_NO_CACHE="1", UV_PYTHON_DOWNLOADS="automatic", UV_NO_PROGRESS="1")
    return env


def uv_asset() -> tuple[str, str]:
    key = (os_key(), machine_key())
    if key not in UV_ASSETS:
        raise EngineError(f"Form Studio has no pinned uv for {key[0]} on {key[1]}.")
    return UV_ASSETS[key]


def _tilde(p) -> str:
    s, home = str(p), str(Path.home())
    return "~" + s[len(home):] if len(home) > 1 and s.startswith(home) else s


def commands(eid: str, cfg: dict | None = None, extra: list[str] | None = None) -> list[str]:
    """What an install does, step by step, as it is shown before it runs."""
    spec = SPECS[eid]
    r, d = root(cfg), env_dir(eid, cfg)
    try:
        asset, sha = uv_asset()
        get_uv = f"download {UV_BASE}{asset} (uv {UV_VERSION}, SHA-256 {sha[:16]}…, checked before use)"
    except EngineError as e:
        get_uv = str(e)
    return [get_uv,
            f"uv venv --python {PYTHON} --relocatable {_tilde(d)}   (Python {PYTHON} kept in {_tilde(r / '.python')})",
            f"uv pip install {' '.join(spec['pins'])}",
            f"python -c \"{spec['check']}\"", *(extra or [])]


# ---- install ------------------------------------------------------------------------------------------------------

def _download(url: str, dest: Path, io) -> str:
    """Fetch url to dest (a .part name first), reporting progress; returns its SHA-256. Stops when io is cancelled."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "form-studio"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:   # noqa: S310 (pinned https URL)
            total, got, shown = int(r.headers.get("Content-Length") or 0), 0, -1
            while True:
                if io.cancelled():
                    raise EngineError("cancelled")
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                h.update(b)
                got += len(b)
                pct = int(100 * got / total) if total else -1
                if pct != shown and pct % 10 == 0:
                    io.say(f"{dest.name}: {got / 1e6:.1f} MB" + (f" ({pct}%)" if total else ""))
                    shown = pct
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return h.hexdigest()


def ensure_uv(r: Path, io) -> Path:
    """The pinned uv under r/.uv/<version>, downloaded and checked when it is not there yet."""
    asset, sha = uv_asset()
    d = r / ".uv" / UV_VERSION
    exe = d / ("uv.exe" if os_key() == "windows" else "uv")
    ok_file = d / "sha256"
    if exe.is_file() and ok_file.is_file() and ok_file.read_text(encoding="utf-8").strip() == sha:
        return exe
    io.say(f"Getting uv {UV_VERSION} ({asset})")
    work = Path(tempfile.mkdtemp(prefix="form-uv-"))
    try:
        got = _download(UV_BASE + asset, work / asset, io)
        if got != sha:
            raise EngineError(f"The downloaded {asset} has SHA-256 {got}, not the pinned {sha}; it was not used.")
        io.say(f"{asset}: SHA-256 matches the pinned value")
        want = exe.name
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (want + ".part")
        if asset.endswith(".zip"):
            with zipfile.ZipFile(work / asset) as z:
                name = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == want), None)
                if name is None:
                    raise EngineError(f"{asset} has no {want}")
                tmp.write_bytes(z.read(name))
        else:
            with tarfile.open(work / asset, "r:gz") as t:
                m = next((m for m in t.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == want), None)
                if m is None:
                    raise EngineError(f"{asset} has no {want}")
                tmp.write_bytes(t.extractfile(m).read())
        tmp.chmod(0o755)
        tmp.replace(exe)
        ok_file.write_text(sha, encoding="utf-8")
        return exe
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build(eid: str, cfg: dict | None, io, extra=None) -> str:
    """Make the engine environment for `eid` and return what was done. `io` is the install job's runner: say(text),
    run(argv, env, timeout) (raises when a command fails), cancelled(). `extra(tmp_env, python, io)` runs after the
    import check (an engine's weights) and returns a function that commits its own result, or None. Raises on any
    failure, and then leaves nothing new behind."""
    spec = SPECS[eid]
    r = root(cfg)
    r.mkdir(parents=True, exist_ok=True)
    final = r / eid
    tmp = r / f".{eid}.partial-{os.getpid()}-{int(time.time())}"
    shutil.rmtree(tmp, ignore_errors=True)
    commit = None
    try:
        uv = ensure_uv(r, io)
        env = uv_env(r)
        io.run([str(uv), "venv", "--python", PYTHON, "--no-project", "--relocatable", str(tmp)], env=env)
        py = env_python(tmp)
        io.run([str(uv), "pip", "install", "--python", str(py), *spec["pins"]], env=env)
        io.run([str(py), "-c", spec["check"]], env=child_env())
        if extra is not None:
            commit = extra(tmp, py, io)
        if io.cancelled():
            raise EngineError("cancelled")
        (tmp / MARKER).write_text(json.dumps({"engine": eid, "python": PYTHON, "uv": UV_VERSION, "pins": list(spec["pins"]),
                                              "built": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1), encoding="utf-8")
        old = None
        if final.exists():
            old = r / f".{eid}.old-{os.getpid()}-{int(time.time())}"
            final.rename(old)
        try:
            tmp.rename(final)
        except OSError:
            if old is not None:
                old.rename(final)
            raise
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if commit is not None:
        commit()
    return f"{spec['label']} has its own Python {PYTHON} in {_tilde(final)}"
