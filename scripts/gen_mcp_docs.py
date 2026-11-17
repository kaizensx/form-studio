"""Regenerate docs/MCP.md from the live tool definitions, so the reference cannot drift.

    python scripts/gen_mcp_docs.py

CI runs this and fails if docs/MCP.md changes.
"""
import asyncio
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from form import mcp_server  # noqa: E402

INTRO = """\
# MCP reference

Form Studio's engine is an [MCP](https://modelcontextprotocol.io) server. Any MCP client (Claude Code, Codex,
Gemini CLI, Cursor, Claude Desktop and others) can design, check, slice, simulate and prepare a release through it,
with the same engine, project folder and rules as the desktop app. The app follows those changes live.

This page is generated from the server's own tool definitions by `scripts/gen_mcp_docs.py`.

## Connect

The server speaks MCP over stdio. Its command is `form-mcp` (or `form mcp`).

```bash
claude mcp add --scope user form -- form-mcp      # Claude Code
codex mcp add form -- form-mcp                    # Codex
```

Clients configured with a JSON file (Gemini CLI, Cursor, Claude Desktop and most others) use:

```json
{ "mcpServers": { "form": { "command": "form-mcp" } } }
```

`form setup` finds the agents installed on this computer and adds the entry for the ones you select.

## Workflow and rules

Every client receives these instructions when it connects:
"""


def first_sentence(text: str) -> str:
    """The opening of a tool's description: its first sentence, or two when the first is a short lead-in."""
    text = " ".join(inspect.cleandoc(text or "").split())
    ends = [m.end(1) for m in re.finditer(r"([.!?])(\s|$)", text)
            if not re.search(r"\b(e\.g|i\.e|etc|vs)\.$", text[:m.end(1)])]
    out = text
    for e in ends:
        out = text[:e]
        if len(out) >= 30:
            break
    return out.replace("|", "\\|")


def main():
    m = mcp_server.build()
    tools = asyncio.run(m.list_tools())
    ro = lambda t: bool(t.annotations and t.annotations.read_only_hint)  # noqa: E731
    lines = [INTRO, "```", mcp_server.INSTRUCTIONS.strip(), "```", "",
             "## Tools at a glance", "",
             f"{len(tools)} tools. Read-only tools never change a project.", "",
             "| Tool | Access | What it does |", "|---|---|---|"]
    for t in tools:
        lines.append(f"| [`{t.name}`](#{t.name}) | {'read-only' if ro(t) else 'changes'} | {first_sentence(t.description)} |")
    lines += ["", "## Tools", ""]
    for t in tools:
        lines += [f"### `{t.name}`", ""]
        if ro(t):
            lines += ["*Read-only.*", ""]
        lines += [inspect.cleandoc(t.description or ""), ""]
        props = (t.input_schema or {}).get("properties", {})
        req = set((t.input_schema or {}).get("required", []))
        if props:
            lines += ["| Argument | Type | Required |", "|---|---|---|"]
            for k, v in props.items():
                typ = v.get("type") or " \\| ".join(x.get("type", "?") for x in v.get("anyOf", []))
                lines.append(f"| `{k}` | {typ} | {'yes' if k in req else ''} |")
            lines.append("")
    lines += ["## Prompts", "", "### `design_part(goal)`", "",
              "A guided session: measure first, look at renders, preview before commit, hand the release to the user.", ""]
    out = Path(__file__).resolve().parents[1] / "docs" / "MCP.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out, len(tools), "tools")


if __name__ == "__main__":
    main()
