"""Form Studio's design guidance, written once as Agent Skills: form/guidance/<skill>/SKILL.md plus references/*.md.

Three readers share these files byte for byte:
  * form/design_guide.py: the design_guide MCP tool returns each topic's text from the reference file named in TOPICS;
  * form/mcp_skills.py: the MCP skills extension (io.modelcontextprotocol/skills) serves every file at
    skill://<skill>/<path>, with digests computed from these bytes;
  * scripts/gen_skills.py: writes plugins/form/skills/** (the Claude Code plugin) as an exact copy.

Standard library only: the MCP server, the CLI and the kernel worker import this without the SDK or OCCT.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# design_guide topic -> (skill, file inside the skill). The topic's text is that file's content, unchanged.
TOPICS = {
    "core": ("cad-core", "references/contract.md"),
    "surfacing": ("surfacing-organic", "references/surfacing.md"),
    "mechanisms": ("assemblies-and-mechanisms", "references/mechanisms.md"),
    "organic": ("surfacing-organic", "references/organic.md"),
    "texture": ("texture", "references/texture.md"),
    "aesthetics": ("industrial-design", "references/aesthetics.md"),
    "dfm": ("fdm-engineering", "references/dfm.md"),
    "reference_parts": ("remodel-from-mesh", "references/reference-parts.md"),
    "hybrid": ("remodel-from-mesh", "references/hybrid.md"),
    "game": ("game-asset", "references/game.md"),
}

# cad-core's worked examples: Python sources in a fenced block, so they read as Markdown
EXAMPLES = {"recipe": ("cad-core", "references/example-recipe.md"),
            "features": ("cad-core", "references/example-features.md")}

# skills listed only when the part of Form Studio they describe is in this build
REQUIRES = {"game-asset": "game"}

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FENCE = re.compile(r"\A```python\n(.*)```\n\Z", re.S)


def game_available() -> bool:
    """Is the game-asset pipeline (form/game) in this build?"""
    return (ROOT.parent / "game" / "__init__.py").is_file()


def available(skill: str) -> bool:
    need = REQUIRES.get(skill)
    return need != "game" or game_available()


def skills(all_: bool = False) -> list[str]:
    """Skill names, sorted: every folder here with a SKILL.md (all_=False leaves out skills this build lacks)."""
    out = sorted(p.parent.name for p in ROOT.glob("*/SKILL.md") if _NAME.match(p.parent.name))
    return out if all_ else [s for s in out if available(s)]


def files(skill: str) -> list[str]:
    """Every file of a skill, as paths relative to its folder ("SKILL.md" first, then sorted)."""
    base = ROOT / skill
    out = sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                 if p.is_file() and not any(part.startswith((".", "__")) for part in p.relative_to(base).parts))
    out.remove("SKILL.md")
    return ["SKILL.md", *out]


def read_bytes(skill: str, rel: str = "SKILL.md") -> bytes:
    """The exact bytes of one file. Refuses names outside the skill folders."""
    if not _NAME.match(skill) or rel not in files(skill):
        raise KeyError(f"{skill}/{rel}")
    return (ROOT / skill / rel).read_bytes()


def read(skill: str, rel: str = "SKILL.md") -> str:
    return read_bytes(skill, rel).decode("utf-8")


def frontmatter(text: str) -> dict[str, str]:
    """The YAML frontmatter of a SKILL.md: one `key: value` per line (plain or quoted scalars only)."""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if not sep or not k.strip():
            raise ValueError(f"frontmatter line is not `key: value`: {line!r}")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def topic_text(name: str) -> str:
    skill, rel = TOPICS[name]
    return read(skill, rel)


def topic_skill(name: str) -> tuple[str, str]:
    """(skill, file) that holds a design_guide topic."""
    return TOPICS[name]


def example(kind: str) -> str:
    """A worked example's Python source (the fenced block of its reference file)."""
    skill, rel = EXAMPLES[kind]
    m = _FENCE.match(read(skill, rel))
    if not m:
        raise ValueError(f"{skill}/{rel} must hold exactly one ```python block")
    return m.group(1)
