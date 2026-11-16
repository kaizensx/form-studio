# FORM plugin for Claude Code

Skills that carry FORM's design and print-engineering practice, and the `form-mcp` server they use.

## Install

FORM itself must be installed first, so that `form-mcp` is on your PATH (see the repository README).

```
claude plugin marketplace add kaizensx/form-studio
claude plugin install form@form-studio
```

From a local checkout: `claude plugin marketplace add ./form-studio`, then the same install command.

If you already registered FORM with `form setup` (`claude mcp add form ...`), you have the server twice.
Keep one: remove the old registration with `claude mcp remove --scope user form`, or keep it and ignore the plugin's.

## Skills

| Skill | Use when |
|---|---|
| `intake` | a new part request: what to ask, what to look up, templates |
| `parametric-design` | building or changing the part's geometry |
| `industrial-design` | developing the form and appearance |
| `design-review` | reviewing a revision as designer, engineer and print technician |
| `explore-variants` | comparing candidates or searching parameter ranges |
| `fdm-engineering` | orientation, material, walls, overhangs, loads |
| `fit-calibration` | clearances, coupons, test pieces, the fit model |
| `hardware-integration` | screws, inserts, magnets, bearings |
| `assemblies-and-mechanisms` | multi-part parts, hinges, sliders, BOM and assembly order |
| `modular-storage` | Gridfinity bins and drawer inserts |
| `verify-print` | before saying a part is ready to print |
| `print-feedback` | a real print came back: failed, tight, loose |
| `release` | handing a revision to the user for approval |

Other agents (Codex, Gemini CLI, Cursor) can read the same files: `AGENTS.md` at the repository root points here.
