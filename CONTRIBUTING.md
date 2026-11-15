# Contributing

Thanks for helping. The most valuable contributions, roughly in order:

1. **Physical results.** Print a coupon or a test piece and report the measured numbers in an issue. Include your printer, nozzle, filament and slicer profile. This is the only way FORM's models get checked against reality.
2. **Recipes.** See [docs/RECIPES.md](docs/RECIPES.md). Open a *Recipe request* issue first if you'd like feedback on the parameters.
3. **Slicer adapters** for Orca Slicer and PrusaSlicer. The interface is in [`form/adapters/__init__.py`](form/adapters/__init__.py).
4. **Agent reports.** A transcript of a session that went wrong or right in Gemini CLI, Cursor or another MCP client.

## Setup

```bash
git clone https://github.com/kaizensx/form-studio && cd form-studio
./run.sh                      # creates .venv, starts the bench
.venv/bin/python -m unittest discover -s tests
```

The tests use the real CAD kernel. Slicing tests run only when Bambu Studio is installed, and skip otherwise.

## Rules of the house

- **One geometry authority.** Everything derives from the recipe. Never edit an output by hand.
- **Never mark something current by hand.** If an input matters, put it in the key (`Studio.keys`).
- **Evidence classes are not interchangeable.** If a check is a rule of thumb, label it `heuristic`. If it's a formula with assumptions, label it `model` and state the assumptions.
- **No network calls** beyond what the user starts.
- **Update the MCP reference** after changing tools: `python scripts/gen_mcp_docs.py`. CI fails if it's stale.
- **Update the media** after changing recipes or the renderer: `python scripts/make_media.py`. Every image comes from a real build.
