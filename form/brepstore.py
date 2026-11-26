"""The built B-rep of a (design source, values) pair, kept on disk so it is built once. Runs in the worker only.

A build is the expensive part of every kernel operation (seconds to minutes); a tessellation at any tolerance, an
export, a check or a probe is derived from the B-rep. The store is content-addressed: the key covers the design's
code, the values, the code that builds and attributes solids, the kernel and what a build reads besides its code
(form/featureprog.py _context_fingerprint: label text, imported parts). Any process with the same data folder (the
app's workers, every MCP server's, the CLI's) finds a solid another one built.

    <data>/.cache/brep/<key>.bin          the B-rep (OCCT binary, written by featureprog.checkpoint_put)
    <data>/.cache/brep/<key>.json         its type and part names (checkpoint metadata)
    <data>/.cache/brep/<key>.model.json   the face-to-feature map by face index, volume, area, box, build log
    <data>/.cache/brep/<key>.building     a process is building this key now: wait for it instead of building

A miss only costs a build; a file that cannot be read is a miss. Pruned like the checkpoints: the oldest go first.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path

STORE_VERSION = 1            # bump on any change to what a stored entry holds or how faces are attributed
DISK_MAX = 240               # entries kept on disk (the oldest go first)
PRUNE_EVERY_S = 30.0
BUILDING_TTL = 3600.0        # a marker older than this is stale whoever wrote it
WAIT_POLL_S = 0.1

_code: dict = {}
_pruned = -1e9


def directory() -> Path | None:
    d = os.environ.get("FORM_BREP_STORE")
    if d:
        return Path(d)
    s = os.environ.get("FORM_SOURCES")
    return Path(s).parent / ".cache" / "brep" if s else None


def _h(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _files_hash(files) -> str:
    h = hashlib.sha256()
    for f in sorted({str(x) for x in files if x}):
        h.update(f.encode())
        try:
            h.update(Path(f).read_bytes())
        except OSError:
            h.update(b"?")
    return h.hexdigest()[:16]


def code_fingerprint(recipe, recipe_id: str) -> str:
    """The code a build of this recipe runs: the kernel, the recipes package and the design's own classes (a design
    written as code is its file). form/craft and form/featureprog are in featureprog.build_id()."""
    hit = _code.get(recipe_id)
    if hit is not None:
        return hit
    import inspect
    here = Path(__file__).parent
    files = [here / "kernel.py", here / "brepstore.py", *sorted((here / "recipes").rglob("*.py"))]
    for c in type(recipe).__mro__:
        if c.__module__ in ("builtins",):
            continue
        try:
            files.append(inspect.getsourcefile(c))
        except (TypeError, OSError):
            pass
    try:
        from . import __version__ as ver
    except Exception:
        ver = "?"
    _code[recipe_id] = out = f"{ver}/{_files_hash(files)}"
    return out


def key(recipe, recipe_id: str, values: dict) -> str:
    """Content key of the B-rep built from this recipe with these (validated) values in this context."""
    from . import featureprog
    vals = {k: (round(float(v), 9) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for k, v in (values or {}).items()}
    return "b" + _h(STORE_VERSION, recipe_id, code_fingerprint(recipe, recipe_id), vals,
                    featureprog._context_fingerprint())


# ---- entries -------------------------------------------------------------------------------------------------------

def load(k: str):
    """(shape, meta) stored under k, or None."""
    d = directory()
    if d is None:
        return None
    f = d / f"{k}.model.json"
    if not f.is_file() or not (d / f"{k}.bin").is_file():
        return None
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if meta.get("v") != STORE_VERSION:
        return None
    from . import featureprog
    shape = featureprog.checkpoint_get(k, d=d)
    if shape is None:
        return None
    try:
        if len(shape.faces()) != int(meta.get("n_faces", -1)):
            return None                                  # not the solid the map was made for
        os.utime(f)
    except Exception:
        return None
    return shape, meta


def save(k: str, shape, meta: dict) -> None:
    d = directory()
    if d is None:
        return
    from . import featureprog
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{k}.model.tmp"
        tmp.write_text(json.dumps({**meta, "v": STORE_VERSION, "ts": time.time()}, default=str), encoding="utf-8")
        os.replace(tmp, d / f"{k}.model.json")
        featureprog.checkpoint_put(k, shape, d=d)
    except Exception:                                    # noqa: BLE001 - a store that cannot be written is a miss later
        return
    global _pruned
    if time.monotonic() - _pruned >= PRUNE_EVERY_S:
        _pruned = time.monotonic()
        threading.Thread(target=_prune_quietly, args=(d,), daemon=True, name="form-brep-prune").start()


# ---- one builder per key across processes --------------------------------------------------------------------------

def _marker(k: str) -> Path | None:
    d = directory()
    return d / f"{k}.building" if d is not None else None


def _live(info: dict) -> bool:
    if time.time() - float(info.get("ts", 0)) > BUILDING_TTL:
        return False
    if info.get("host") != socket.gethostname():
        return True                                       # another machine on a shared folder: trust its marker
    from .procs import pid_alive
    return pid_alive(info.get("pid", -1))


def _read_marker(m: Path) -> dict | None:
    try:
        return json.loads(m.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def claim(k: str) -> bool:
    """True: this process builds k (a marker now says so). False: another live process is building it."""
    m = _marker(k)
    if m is None:
        return True
    for _ in range(2):
        try:
            m.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(m), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            info = _read_marker(m)
            if info is not None and _live(info) and int(info.get("pid", -1)) != os.getpid():
                return False
            try:
                m.unlink()                                # stale (its process died), or our own
            except OSError:
                pass
            continue
        except OSError:
            return True                                   # no marker possible: build without one
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(), "ts": time.time()}, fh)
        return True
    return True


def release(k: str) -> None:
    m = _marker(k)
    if m is None:
        return
    info = _read_marker(m)
    if info is None or int(info.get("pid", -1)) == os.getpid():
        try:
            m.unlink()
        except OSError:
            pass


def wait(k: str, limit: float | None = None) -> bool:
    """Wait while another process builds k: True when its marker went (the entry may now be there)."""
    m = _marker(k)
    if m is None:
        return True
    end = time.monotonic() + (limit if limit is not None else BUILDING_TTL)
    while time.monotonic() < end:
        info = _read_marker(m)
        if info is None or not _live(info):
            return True
        time.sleep(WAIT_POLL_S)
    return False


# ---- housekeeping --------------------------------------------------------------------------------------------------

def _prune_quietly(d) -> None:
    try:
        prune(d)
    except Exception:                                    # noqa: BLE001 - pruning is housekeeping
        pass


def prune(d: Path | None = None, keep: int | None = None) -> None:
    """At most DISK_MAX entries (the least recently used go first, with their sidecars); stale markers go."""
    d = d or directory()
    if d is None or not d.is_dir():
        return
    keep = DISK_MAX if keep is None else keep

    def mtime(x):
        try:
            return x.stat().st_mtime
        except OSError:
            return 0.0
    entries = sorted(d.glob("*.model.json"), key=mtime)
    for old in entries[:max(0, len(entries) - keep)]:
        k = old.name[:-len(".model.json")]
        for suffix in (".bin", ".json", ".model.json"):
            (d / f"{k}{suffix}").unlink(missing_ok=True)
    for b in d.glob("*.bin"):                             # a B-rep whose map never got written
        if not (d / f"{b.stem}.model.json").exists() and time.time() - mtime(b) > 60:
            b.unlink(missing_ok=True)
            b.with_suffix(".json").unlink(missing_ok=True)
    for m in d.glob("*.building"):
        info = _read_marker(m)
        if info is None or not _live(info):
            m.unlink(missing_ok=True)
