"""Agent CLIs FORM can chat through. Each one is an adapter (see base.py); add one by adding it to ADAPTERS."""
from __future__ import annotations

from .base import Adapter, Parser, Run
from .claude import Claude
from .codex import Codex
from .gemini import Gemini

ADAPTERS: dict[str, Adapter] = {a.id: a for a in (Claude(), Codex(), Gemini())}

__all__ = ["ADAPTERS", "Adapter", "Parser", "Run"]
