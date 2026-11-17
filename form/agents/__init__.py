"""Agent CLIs FORM can chat through. Each one is an adapter (see base.py); add one by adding it to ADAPTERS."""
from __future__ import annotations

from .base import Adapter, Parser, Run
from .claude import Claude
from .codex import Codex
from .copilot import Copilot
from .cursor import Cursor
from .gemini import Gemini
from .opencode import OpenCode
from .qwen import Qwen

ADAPTERS: dict[str, Adapter] = {a.id: a for a in (Claude(), Codex(), Gemini(), Cursor(), OpenCode(), Qwen(), Copilot())}

__all__ = ["ADAPTERS", "Adapter", "Parser", "Run"]
