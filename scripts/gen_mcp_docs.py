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


SKILLS = """\
## Skills

Form Studio's design and engineering practice is also served as MCP skills (the `io.modelcontextprotocol/skills`
extension, MCP 2026-07-28): `skills/list` names each skill with a digest of every file it holds, and the files are
read with `resources/read` at `skill://<name>/SKILL.md`. Claude Code lists them as `form:<skill>`. Skills are not
available in headless runs (`claude -p`, the Agent SDK) or to clients without the extension, so the same guidance
stays reachable through the `design_guide` tool."""

QUESTIONS = """\
## Questions to the person

A tool that needs the person asks, in this order: Form Studio's own chat (when the agent runs inside it); the
client's own form, when the client declared MCP elicitation (form mode); otherwise the result says so, as before.
Through the client's form:

| Tool | The form asks | Declined or dismissed |
|---|---|---|
| `ask_user` | the question, its choices (one, or several with `multi_select`) and a free answer | `{answered: false, reason}` |
| `ask_measurement` | the value (within the parameter's range), how it was got (calipers, ruler, datasheet), or skip | `{answered: false, reason}`, nothing committed |
| `delete_project` | to confirm, with the trash path | `{ok: false, refused}`, nothing moved |
| `install_software` | to install, with the commands and the licence (always for a non-commercial licence) | `{installed: false, refused}` |
| `fetch_link` | to download, for more than 100 MB | `{fetched: false, refused}` |

On MCP 2026-07-28 the tool answers with an `InputRequiredResult` holding one `elicitation/create` and a sealed
`requestState`, and the client calls it again with `inputResponses`; an answer without that state is not taken.
Earlier protocol versions get `elicitation/create` on the session. A client without elicitation, and
`install_software(confirm=True)` for a licence that needs no acceptance, work exactly as before."""

SEARCH = """\
## Tool search

Claude Code can defer MCP tools and find them with its ToolSearch tool. These tools carry
`_meta["anthropic/alwaysLoad"]: true` and are always loaded: {always}. Every tool's description opens with what it
does (a verb and its object), so a search finds it; descriptions and the instructions above stay within the 4,096
characters Claude Code reads. Form Studio's own chat runs Claude Code with `ENABLE_TOOL_SEARCH=auto` and ToolSearch
in its tools; `[chat] tool_search = "false"` in studio.toml (or `FORM_TOOL_SEARCH=false`) loads every tool up front
instead."""


def extension_lines() -> list:
    ids = [getattr(e, "identifier", "") for e in mcp_server.extensions()]
    if not ids:
        return []
    return ["This build of the server offers the extensions " + ", ".join(f"`{i}`" for i in ids) + ".", ""]


def main():
    m = mcp_server.build()
    tools = asyncio.run(m.list_tools())
    ro = lambda t: bool(t.annotations and t.annotations.read_only_hint)  # noqa: E731
    always = ", ".join(f"`{n}`" for n in mcp_server.ALWAYS_LOAD)
    lines = [INTRO, "```", mcp_server.INSTRUCTIONS.strip(), "```", "",
             SKILLS, "", *extension_lines(), QUESTIONS, "", SEARCH.format(always=always), "",
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
