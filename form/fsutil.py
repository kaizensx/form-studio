"""File moves that survive Windows.

On Windows a file cannot be replaced while any other handle has it open: another thread of FORM reading
project.json for the window, an antivirus scan, the search indexer. `os.replace` then fails with PermissionError
(WinError 5 or 32) for a few milliseconds. POSIX never does this, so the failure only shows up on Windows and only
under load: a Windows CI runner hit it as a pipeline that "failed" right after the solid was built.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


def replace(src, dst, seconds: float = 3.0) -> None:
    """os.replace(src, dst), retried while Windows reports the target as busy."""
    end = time.monotonic() + seconds
    wait = 0.01
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.monotonic() >= end:
                raise
            time.sleep(wait)
            wait = min(wait * 2, 0.2)


def replace_dir(src, dst, seconds: float = 3.0) -> None:
    """Put the folder `src` where `dst` is, removing an old `dst` first. Retries while a file inside is busy."""
    src, dst = Path(src), Path(dst)
    end = time.monotonic() + seconds
    wait = 0.01
    while True:
        try:
            if dst.exists():
                shutil.rmtree(dst)
            os.replace(src, dst)
            return
        except (PermissionError, OSError) as e:
            if isinstance(e, FileNotFoundError) or time.monotonic() >= end:
                raise
            time.sleep(wait)
            wait = min(wait * 2, 0.2)
