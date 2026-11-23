"""The opt-in reference corpus: CADEvolve's parametric CadQuery generators, a second, lower tier for exemplar search.

CADEvolve (kulibinai/CADEvolve, Apache-2.0; dataset huggingface.co/datasets/kulibinai/cadevolve) evolved about 8,000
parametric CadQuery generator programs from a small set of hand-written seeds. Form Studio ships twelve of those seeds
hand-ported to Form designs (form/exemplars/*.py, META "origin"). The rest is available here, opt in:

    python -m form.exemplars.corpus status
    python -m form.exemplars.corpus download --accept-licence apache-2.0 [--dir FOLDER]
    form install exemplars.cadevolve            (the installer shows the size and the licence first)

The dataset is one 4.73 GB tar. The download streams it from huggingface.co over HTTPS at a fixed revision, checks
its SHA-256, and writes only CADEvolve-G/parametric_generators.json: nothing from the ABC-* or ShapeNet-* folders (or
any other folder) is ever written to disk, because those programs derive from third-party datasets whose licences
Form Studio has not checked. The tar itself is not kept.

What it is for: exemplars.search() adds up to a few hits from this corpus after every Form exemplar hit, each marked
{"tier": "reference", "label": "reference CadQuery, not the Form API"}. They are other people's CadQuery programs, read
as text and never run: an agent may learn a construction from one, but writes its design with the Form API. Without
the corpus, search is exactly what it was.

Reading the corpus imports nothing heavy (json only); nothing here imports build123d or runs the programs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

NAME = "CADEvolve-G parametric generators"
REPO = "kulibinai/cadevolve"                                  # Hugging Face dataset
REVISION = "7543a3c1103b72c71f40ec71d6cacd1a50a77a16"
TAR = "cadevolve.tar"
TAR_SHA256 = "1bd4c987ff538ebdd8e85da81ab41d7a276f90b3015cddd371ac4c4e51ad07e8"
TAR_BYTES = 4_732_815_360
SIZE = "4.73 GB download; only CADEvolve-G/parametric_generators.json is kept"
LICENCE = "Apache-2.0"
LICENCE_ID = "apache-2.0"
LICENCE_URL = "https://www.apache.org/licenses/LICENSE-2.0"
CODE_REPO = "kulibinai/CADEvolve"
CODE_SHA = "e30e6358648df661247815c67414cd42079f8b41"
URL = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{TAR}"
KEEP = "parametric_generators.json"
KEEP_FOLDER = "CADEvolve-G"
NEVER = ("ABC-", "ShapeNet-")                                 # folder prefixes never written, whatever else matches
MARKER = "form-download.json"                                 # written last: the folder is complete
PREFIX = "cadevolve:"                                         # names of corpus entries in search hits and get()
LABEL = "reference CadQuery, not the Form API"
_CACHE: dict = {}


def corpus_dir() -> Path:
    """$FORM_EXEMPLAR_CORPUS_DIR, else <data folder>/corpus/cadevolve."""
    env = os.environ.get("FORM_EXEMPLAR_CORPUS_DIR")
    if env:
        return Path(env).expanduser()
    try:
        from .. import config
        data = Path(config.load()["data"]["dir"]).expanduser()
    except Exception:                                   # noqa: BLE001
        data = Path(os.environ.get("FORM_DATA") or "~/FORM").expanduser()
    return data / "corpus" / "cadevolve"


def wanted(member: str) -> bool:
    """True only for CADEvolve-G/parametric_generators.json (at any depth under one top folder). A path with an
    ABC-* or ShapeNet-* folder, an absolute path or a '..' is never wanted."""
    p = PurePosixPath(member)
    parts = p.parts
    if not parts or p.is_absolute() or ".." in parts:
        return False
    if any(x.startswith(NEVER) for x in parts):
        return False
    return p.name == KEEP and len(parts) >= 2 and parts[-2] == KEEP_FOLDER and len(parts) <= 3


def status(folder: Path | None = None) -> dict:
    """Is the corpus installed? Never downloads."""
    folder = Path(folder) if folder else corpus_dir()
    ok = (folder / MARKER).is_file() and (folder / KEEP).is_file()
    out = {"name": NAME, "installed": ok, "folder": str(folder), "licence": LICENCE, "licence_url": LICENCE_URL,
           "size": SIZE, "dataset": f"huggingface.co/datasets/{REPO}@{REVISION[:7]}"}
    if ok:
        out["entries"] = len(entries(folder))
    return out


def installed() -> bool:
    try:
        return status()["installed"]
    except Exception:                                   # noqa: BLE001  (search must never fail because of the corpus)
        return False


# ---- reading --------------------------------------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (s or "").lower()).strip("_")[:60] or "generator"


def _records(data) -> list[dict]:
    """The generator records, whatever the file's top level is (a list, or a dict of name -> record or -> code)."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in ("generators", "items", "data"):
            if isinstance(data.get(k), list):
                return _records(data[k])
        out = []
        for k, r in data.items():
            if isinstance(r, dict):
                out.append({"name": k, **r})
            elif isinstance(r, str):
                out.append({"name": k, "code": r})
        return out
    return []


def entries(folder: Path | None = None) -> list[dict]:
    """[{"name", "title", "summary", "code"}] from parametric_generators.json, read as text (never run)."""
    folder = Path(folder) if folder else corpus_dir()
    f = folder / KEEP
    if not f.is_file():
        return []
    key = (str(f), f.stat().st_mtime_ns)
    if key in _CACHE:
        return _CACHE[key]
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    for i, r in enumerate(_records(data)):
        code = next((r[k] for k in ("code", "program", "source", "generator", "script") if isinstance(r.get(k), str)), "")
        if not code:
            continue
        raw = str(r.get("name") or r.get("id") or r.get("func_name") or f"generator_{i}")
        name = _slug(raw)
        if name in seen:
            name = f"{name}_{i}"
        seen.add(name)
        title = str(r.get("abstract") or r.get("title") or raw)
        summary = str(r.get("detailed") or r.get("description") or r.get("abstract") or "")
        out.append({"name": PREFIX + name, "title": title[:200], "summary": summary[:600], "code": code})
    _CACHE.clear()
    _CACHE[key] = out
    return out


def hit(e: dict) -> dict:
    """A search hit for one corpus entry: labelled, never mistaken for a Form exemplar."""
    return {"name": e["name"], "title": e["title"], "summary": e["summary"], "tier": "reference", "label": LABEL,
            "source": f"{CODE_REPO} (CADEvolve-G, {LICENCE})",
            "how_to_use": "Reference CadQuery from another project, not the Form API and not a Form design: read it "
                          "for the construction idea, then write the design with build123d and form.craft. Never run it."}


def get(name: str, folder: Path | None = None) -> dict:
    """One corpus entry with its code, labelled. KeyError when the corpus is not installed or has no such entry."""
    for e in entries(folder):
        if e["name"] == name:
            return {**hit(e), "code": e["code"]}
    raise KeyError(name)


# ---- download -------------------------------------------------------------------------------------------------------

class _Hashing:
    """A read-only stream that hashes what passes through it and reports progress."""

    def __init__(self, raw, echo, total: int, cancelled=None):
        self.raw, self.echo, self.total, self.cancelled = raw, echo, total, cancelled
        self.h, self.got, self.shown = hashlib.sha256(), 0, -1

    def read(self, n: int = -1) -> bytes:
        if self.cancelled is not None and self.cancelled():
            raise RuntimeError("cancelled")
        b = self.raw.read(n if n and n > 0 else 1 << 20)
        self.h.update(b)
        self.got += len(b)
        pct = int(100 * self.got / self.total) if self.total else -1
        if pct != self.shown and pct % 5 == 0:
            self.echo(f"{TAR}: {self.got / 1e9:.2f} GB ({pct}%)")
            self.shown = pct
        return b

    def drain(self) -> None:
        while self.read(1 << 20):
            pass


def extract(stream, folder: Path) -> list[str]:
    """Read a tar stream and write only the wanted member to folder/parametric_generators.json (a temporary name
    first). Returns the member names written. Every other member is skipped without touching the disk."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    with tarfile.open(fileobj=stream, mode="r|*") as tf:
        for m in tf:
            if not (m.isfile() and wanted(m.name)):
                continue
            src = tf.extractfile(m)
            part = folder / (KEEP + ".part")
            with open(part, "wb") as out:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
            part.replace(folder / KEEP)
            written.append(m.name)
    return written


def download(folder: Path, echo=print, opener=None, sha256: str | None = None, cancelled=None) -> dict:
    """Stream the dataset tar, keep only CADEvolve-G's generators, check the tar's SHA-256 (`sha256`: the pinned one,
    unless a test serves its own tar). Nothing else is written. `cancelled()` true stops it."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MARKER).unlink(missing_ok=True)
    opener = opener or (lambda: urllib.request.urlopen(            # noqa: S310 (https only, fixed host and revision)
        urllib.request.Request(URL, headers={"User-Agent": "form-studio"}), timeout=60))
    with opener() as r:
        stream = _Hashing(r, echo, TAR_BYTES, cancelled)
        written = extract(stream, folder)
        stream.drain()                                  # hash the rest of the tar too
    digest = stream.h.hexdigest()
    sha256 = sha256 or TAR_SHA256
    if digest != sha256 or not written:
        (folder / KEEP).unlink(missing_ok=True)
        why = "its SHA-256 does not match" if digest != sha256 else f"it has no {KEEP_FOLDER}/{KEEP}"
        raise RuntimeError(f"The downloaded {TAR} was not kept: {why}.")
    info = {"dataset": REPO, "revision": REVISION, "licence": LICENCE, "tar_sha256": digest, "kept": written,
            "sha256": hashlib.sha256((folder / KEEP).read_bytes()).hexdigest(),
            "code": f"https://github.com/{CODE_REPO}/tree/{CODE_SHA}"}
    (folder / MARKER).write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m form.exemplars.corpus", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    d = sub.add_parser("download")
    d.add_argument("--accept-licence", default="", help=f"must be {LICENCE_ID}: {LICENCE} ({LICENCE_URL})")
    d.add_argument("--dir", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if a.accept_licence.strip().lower() != LICENCE_ID:
        print(f"{NAME} (huggingface.co/datasets/{REPO}) is licensed {LICENCE} ({LICENCE_URL}); {SIZE}.\n"
              f"Nothing was downloaded. To accept the licence and download, pass --accept-licence {LICENCE_ID}.",
              file=sys.stderr)
        return 2
    folder = Path(a.dir).expanduser() if a.dir else corpus_dir()
    print(f"Downloading {REPO}@{REVISION[:7]} ({SIZE}; licence {LICENCE}) to {folder}", file=sys.stderr)
    info = download(folder, echo=lambda s: print(s, file=sys.stderr, flush=True))
    print(json.dumps({"downloaded": str(folder), **info}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
