"""Form Studio's design guidance as MCP skills: the io.modelcontextprotocol/skills extension (SEP-2640).

The SDK (mcp 2.3) has the Extension base but no skills implementation, so this module is one: it serves every skill
in form/guidance (see form/guidance/__init__.py) to clients that read skills over MCP.

  * skills/list: every skill, each entry {uri, frontmatter, resources: [{uri, digest: "sha256:<hex>", size}]}, the
    manifest computed from the exact bytes resources/read serves. No pagination (one page; a cursor is refused).
  * skills/get {uri}: one entry by its SKILL.md URI. An unknown URI is -32602 (invalid params).
  * resources/read skill://<skill>/<path>: each file, text/markdown. An unknown skill URI is -32602 (the SDK's
    ResourceNotFoundError mapping).
  * Every result carries resultType "complete", ttlMs and cacheScope.

Skills whose part of Form Studio is not in this build (game-asset without form/game) are not served at all.

Registering it is the server's job (form/mcp_server.py):

    from .mcp_skills import skills_extension
    mcp = MCPServer("form", ..., extensions=[skills_extension()])

The design_guide tool stays for clients without skills (claude -p, the Agent SDK, Codex, API agents); its results
name the skill that holds the same text.
"""
from __future__ import annotations

import hashlib
from typing import Any, Literal

from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp_types import RequestParams
from mcp_types.jsonrpc import INVALID_PARAMS

from . import guidance

EXTENSION_ID = "io.modelcontextprotocol/skills"
SCHEME = "skill://"
TTL_MS = 300_000                     # five minutes: the files change only with a Form Studio update
MIME = {".md": "text/markdown"}


def skill_uri(skill: str, rel: str = "SKILL.md") -> str:
    return f"{SCHEME}{skill}/{rel}"


class SkillsListParams(RequestParams):
    cursor: str | None = None


class SkillsGetParams(RequestParams):
    uri: str


class Skills(Extension):
    """Serves form/guidance as MCP skills. Pass to MCPServer(extensions=[...])."""

    identifier = EXTENSION_ID

    def __init__(self, ttl_ms: int = TTL_MS, cache_scope: Literal["public", "private"] = "public") -> None:
        self.ttl_ms = int(ttl_ms)
        self.cache_scope = cache_scope
        self._files: dict[str, tuple[str, str, bytes]] = {}      # uri -> (skill, rel, bytes)
        self._entries: dict[str, dict[str, Any]] = {}           # SKILL.md uri -> skills/list entry
        for skill in guidance.skills():
            manifest = []
            for rel in guidance.files(skill):
                data = guidance.read_bytes(skill, rel)
                data.decode("utf-8")                             # served as text: must be UTF-8
                uri = skill_uri(skill, rel)
                self._files[uri] = (skill, rel, data)
                manifest.append({"uri": uri, "digest": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data)})
            fm = guidance.frontmatter(self._files[skill_uri(skill)][2].decode("utf-8"))
            if fm.get("name") != skill or not fm.get("description"):
                raise ValueError(f"{skill}/SKILL.md: frontmatter needs name: {skill} and a description")
            self._entries[skill_uri(skill)] = {"uri": skill_uri(skill), "frontmatter": fm, "resources": manifest}

    # what the server advertises at capabilities.extensions[EXTENSION_ID]: no resources/directory/read
    def settings(self) -> dict[str, Any]:
        return {}

    def names(self) -> list[str]:
        return [e["frontmatter"]["name"] for e in self._entries.values()]

    def entries(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._entries.values()]

    def resources(self) -> list[ResourceBinding]:
        out = []
        for uri, (skill, rel, data) in self._files.items():
            ext = rel[rel.rfind("."):] if "." in rel else ""
            out.append(ResourceBinding(TextResource(
                uri=uri, name=f"{skill}/{rel}", title=f"{skill}: {rel}",
                description=(self._entries[skill_uri(skill)]["frontmatter"]["description"] if rel == "SKILL.md"
                             else f"Supporting file of the {skill} skill"),
                mime_type=MIME.get(ext, "text/plain"), text=data.decode("utf-8"))))
        return out

    def methods(self) -> list[MethodBinding]:
        return [MethodBinding("skills/list", SkillsListParams, self._list),
                MethodBinding("skills/get", SkillsGetParams, self._get)]

    def _envelope(self, **body: Any) -> dict[str, Any]:
        return {"resultType": "complete", **body, "ttlMs": self.ttl_ms, "cacheScope": self.cache_scope}

    async def _list(self, ctx: Any, params: SkillsListParams | None) -> dict[str, Any]:
        if params is not None and params.cursor:
            raise MCPError(code=INVALID_PARAMS, message="Unknown cursor: skills/list returns one page.",
                           data={"cursor": params.cursor})
        return self._envelope(skills=self.entries())

    async def _get(self, ctx: Any, params: SkillsGetParams) -> dict[str, Any]:
        entry = self._entries.get(params.uri)
        if entry is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Unknown skill {params.uri!r}.", data={"uri": params.uri})
        return self._envelope(skill=dict(entry))


def skills_extension(**kwargs: Any) -> Skills:
    """The skills extension for form/mcp_server.py: MCPServer(..., extensions=[skills_extension()]).
    kwargs: ttl_ms (default 300000), cache_scope ("public" by default; the files are the same for every user)."""
    return Skills(**kwargs)
