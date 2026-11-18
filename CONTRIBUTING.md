# Contributing to Form Studio

Thank you for helping. Form Studio gets better fastest when people who print things bring what they know: a recipe,
a slicer that behaves differently, a measured result, a sharper check.

## Ways to contribute

| Contribution | Where it goes | Start here |
|---|---|---|
| **Recipes** | `community/recipes/<id>/` (gallery) or `form/recipes/` (built-in) | [community/recipes](community/recipes/README.md), [Writing a recipe](docs/RECIPES.md); in the app, **Share… › To the community** prepares the folder and a pre-filled issue |
| **Measured print results** | An issue or a Show and tell post | Printer, nozzle, filament, slicer preset and the measured numbers |
| **Slicer and printer support** | `form/adapters/` | [`form/adapters/__init__.py`](form/adapters/__init__.py) defines the adapter interface |
| **Agent support** | `form/agents/` | [`form/agents/base.py`](form/agents/base.py) defines the agent interface |
| **The desktop app** | `form/app/qml/` | [UI contributor notes](form/app/qml/CONTRIBUTING-UI.md) |
| **Docs and website** | `docs/`, `site/` | [Website build](#the-website) |

Issues labelled [`good first issue`](https://github.com/kaizensx/form-studio/labels/good%20first%20issue) are small and
self-contained. [`help wanted`](https://github.com/kaizensx/form-studio/labels/help%20wanted) marks larger pieces the
maintainers would like a hand with.

## Branches

| Branch | Purpose |
|---|---|
| `main` | Stable releases. Every commit on `main` is a released or releasable version; the website deploys from it. |
| `dev` | Integration and testing. Features and fixes land here first and are exercised on all three platforms before a release. |
| `feat/*`, `fix/*` | Your work. Branch from `dev`. |

**Pull requests target `dev`.** A release is a merge from `dev` into `main` followed by a version tag.

## Development setup

```bash
git clone https://github.com/kaizensx/form-studio && cd form-studio
git switch dev
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[all]"
.venv/bin/python -m form.app                          # the desktop app, from source
.venv/bin/python -m unittest discover -s tests        # the test suite
```

The tests run on the real CAD kernel. Slicing tests run when a supported slicer is installed and are skipped otherwise.
The interface journeys (`tests/test_ui_journeys.py`) drive the real window with mouse and key events.

### Useful commands

```bash
.venv/bin/python -m form.app --shot out.png --project hallway-phone-dock --stage prove   # screenshot the app
.venv/bin/python scripts/gen_mcp_docs.py           # regenerate docs/MCP.md after changing MCP tools
.venv/bin/python scripts/make_media.py             # regenerate README media after changing recipes or the renderer
.venv/bin/python scripts/acceptance.py             # the end-to-end acceptance run
```

### The website

```bash
python site/build.py                    # docs pages, from docs/*.md
python site/tools/build_recipe_index.py # site/recipes/index.json, from form/recipes and community/recipes
python site/tools/check_site.py         # links, images, page weight
python -m http.server -d site 8000
```

## Engineering principles

- **One geometry authority.** Everything derives from the recipe's build123d code. Outputs are never edited by hand.
- **Staleness is derived.** An artifact is current when a file exists under the hash of its inputs. If an input
  matters, it belongs in the key (`Studio.keys`).
- **Evidence classes are not interchangeable.** A rule of thumb is `heuristic`; a formula with assumptions is `model`
  and states the assumptions; a slicer result is `simulated`; only a measured print is `physical`.
- **Headless parity.** Every capability in the app is also a `form` command and an MCP tool.
- **No network calls** beyond the ones the user starts.
- **A person releases.** No code path lets an agent approve a release, start a print or upload a design.
- **Cross-platform.** macOS, Windows and Linux; UTF-8 everywhere; no POSIX-only code without a Windows path.

## Pull requests

1. Open or find an issue for anything larger than a small fix, so the approach can be agreed first.
2. Keep each pull request to one change. Include tests, and screenshots for interface changes.
3. Add a line to `CHANGELOG.md` under the next version.
4. CI runs the test suite on Linux and macOS, checks that `docs/MCP.md` is current, and builds the website.

By contributing you agree that your work is released under the [MIT licence](LICENSE), and to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
