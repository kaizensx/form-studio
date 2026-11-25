"""Write the Claude Code plugin's skills (plugins/form/skills/**) from form/guidance, the one source.

    .venv/bin/python scripts/gen_skills.py           # write
    .venv/bin/python scripts/gen_skills.py --check   # exit 1 and list the drift, write nothing

Every skill in form/guidance is copied byte for byte, including skills the MCP server lists only when their part of
Form Studio is in the build (game-asset). Skill folders in plugins/form/skills that have no source are removed.
Edit form/guidance, never plugins/form/skills.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import guidance  # noqa: E402

OUT = ROOT / "plugins" / "form" / "skills"


def expected() -> dict[str, bytes]:
    """{path relative to plugins/form/skills: bytes} for every file the plugin should hold."""
    return {f"{s}/{rel}": guidance.read_bytes(s, rel) for s in guidance.skills(all_=True) for rel in guidance.files(s)}


def actual() -> dict[str, bytes]:
    if not OUT.is_dir():
        return {}
    return {p.relative_to(OUT).as_posix(): p.read_bytes() for p in sorted(OUT.rglob("*")) if p.is_file()
            and not any(part.startswith(".") for part in p.relative_to(OUT).parts)}


def drift() -> list[str]:
    want, have = expected(), actual()
    out = [f"missing {k}" for k in sorted(want.keys() - have.keys())]
    out += [f"stale {k}" for k in sorted(have.keys() - want.keys())]
    out += [f"changed {k}" for k in sorted(want.keys() & have.keys()) if want[k] != have[k]]
    return out


def write() -> list[str]:
    changes = drift()
    want = expected()
    keep = {k.split("/", 1)[0] for k in want}
    if OUT.is_dir():
        for d in OUT.iterdir():
            if d.is_dir() and d.name not in keep:
                shutil.rmtree(d)
    for k, data in want.items():
        p = OUT / k
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.is_file() or p.read_bytes() != data:
            p.write_bytes(data)
    for k in actual().keys() - want.keys():         # a stray file inside a kept skill
        (OUT / k).unlink()
    return changes


def main(argv: list[str]) -> int:
    if "--check" in argv:
        d = drift()
        for line in d:
            print(line)
        if d:
            print("plugins/form/skills is out of date: run scripts/gen_skills.py", file=sys.stderr)
        return 1 if d else 0
    changes = write()
    print(f"{len(guidance.skills(all_=True))} skills in {OUT.relative_to(ROOT)}; {len(changes)} file(s) changed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
