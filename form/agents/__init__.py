"""Agents Form Studio can chat through. Each one is an adapter (see base.py); add one by adding it to ADAPTERS.

CLI agents run a CLI headless on the user's own account; API agents (api.py) talk to a model provider's API with
Form Studio's tools and need no CLI (providers.py lists them)."""
from __future__ import annotations

from .api import all_api_adapters, sync
from .base import Adapter, Parser, Run
from .claude import Claude
from .codex import Codex
from .copilot import Copilot
from .cursor import Cursor
from .gemini import Gemini
from .opencode import OpenCode
from .qwen import Qwen

ADAPTERS: dict[str, Adapter] = {a.id: a for a in (Claude(), Codex(), Gemini(), Cursor(), OpenCode(), Qwen(), Copilot(),
                                                  *all_api_adapters())}
CLI_IDS = ("claude", "codex", "gemini", "cursor", "opencode", "qwen", "copilot")


def refresh(adapters: dict | None = None) -> dict:
    """Add, update or drop the providers the person added (form/agents/custom.py) in an adapter table, in place."""
    return sync(ADAPTERS if adapters is None else adapters)

__all__ = ["ADAPTERS", "CLI_IDS", "Adapter", "Parser", "Run", "refresh"]
