<!-- Pull requests target the `dev` branch. `main` only receives releases. -->

## Summary

<!-- What changes and why. Link the issue: "Closes #123". -->

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Built-in recipe (an engine building block in `form/recipes/`)
- [ ] Slicer or agent support
- [ ] Docs or website

## Checklist

- [ ] `python -m unittest discover -s tests` passes
- [ ] `pre-commit run --from-ref origin/dev --to-ref HEAD` passes (lint, YAML/TOML, whitespace)
- [ ] MCP tools changed: `python scripts/gen_mcp_docs.py` was run and `docs/MCP.md` is committed
- [ ] Interface changed: screenshots of the app before and after are attached
- [ ] New recipe: it builds with its defaults, its constraints name a feature and a fix, and `measure()` reads its interfaces off the solid
- [ ] Every number this change shows carries its evidence class (computed, heuristic, model, simulated, measured)
- [ ] `CHANGELOG.md` has a line under the next version
