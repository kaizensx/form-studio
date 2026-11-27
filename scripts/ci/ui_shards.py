"""Which interface journeys one shard runs: every n-th test of tests/test_ui_journeys.py, by name.

    python scripts/ci/ui_shards.py --shards 3 --index 1        # the unittest names of shard 1 (1-based), one line

Read from the source, so nothing is imported and none is left out; a journey and its variants (x, x_light, x_small)
are next to each other by name and so land in different shards.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

FILE = Path(__file__).resolve().parents[2] / "tests" / "test_ui_journeys.py"


def names() -> list[str]:
    out = []
    for node in ast.parse(FILE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef):
            out += [f"tests.test_ui_journeys.{node.name}.{f.name}" for f in node.body
                    if isinstance(f, ast.FunctionDef) and f.name.startswith("test_")]
    return sorted(out)


def shard(index: int, shards: int) -> list[str]:
    return names()[index - 1::shards]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--index", type=int, required=True, help="1-based")
    a = ap.parse_args(argv)
    if not 1 <= a.index <= a.shards:
        ap.error("--index is 1 to --shards")
    print(" ".join(shard(a.index, a.shards)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
