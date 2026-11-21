"""`python -m form.recon.learned`: status, or download the CAD-Recode weights after the licence is accepted.

    python -m form.recon.learned status
    python -m form.recon.learned download --accept-licence cc-by-nc-4.0 [--dir FOLDER]

The download is what the installer runs (`form install recon.learned`) after showing the size and the licence. It
refuses to start unless `--accept-licence` names the model's licence. Files come only from huggingface.co over
HTTPS, are written to a temporary name and moved into place when complete, and their SHA-256 is recorded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from . import (LICENCE, LICENCE_ID, LICENCE_URL, MARKER, REPO, REVISION, SIZE, TOKENIZER_FILES, TOKENIZER_REPO,
               WEIGHT_FILES, model_dir, status)

BASE = "https://huggingface.co"


def _fetch(url: str, dest: Path, echo) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "form-studio"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:   # noqa: S310 (https only, fixed host)
        total = int(r.headers.get("Content-Length") or 0)
        got, shown = 0, -1
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            h.update(b)
            got += len(b)
            pct = int(100 * got / total) if total else -1
            if pct != shown and (pct % 5 == 0):
                echo(f"{dest.name}: {got / 1e9:.2f} GB" + (f" ({pct}%)" if total else ""))
                shown = pct
    part.replace(dest)
    return h.hexdigest()


def download(folder: Path, echo=print) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MARKER).unlink(missing_ok=True)
    sums = {}
    for f in WEIGHT_FILES:
        sums[f] = _fetch(f"{BASE}/{REPO}/resolve/{REVISION}/{f}", folder / f, echo)
    for f in TOKENIZER_FILES:
        sums[f"tokenizer/{f}"] = _fetch(f"{BASE}/{TOKENIZER_REPO}/resolve/main/{f}", folder / "tokenizer" / f, echo)
    info = {"model": REPO, "revision": REVISION, "tokenizer": TOKENIZER_REPO, "licence": LICENCE, "sha256": sums}
    (folder / MARKER).write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m form.recon.learned", description=__doc__,
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
        print(f"{REPO} is licensed {LICENCE} ({LICENCE_URL}) and is {SIZE}.\n"
              f"Nothing was downloaded. To accept the licence and download, pass --accept-licence {LICENCE_ID}.",
              file=sys.stderr)
        return 2
    folder = Path(a.dir).expanduser() if a.dir else model_dir()
    print(f"Downloading {REPO} ({SIZE}; licence {LICENCE}) to {folder}", file=sys.stderr)
    info = download(folder, echo=lambda s: print(s, file=sys.stderr, flush=True))
    print(json.dumps({"downloaded": str(folder), **info}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
