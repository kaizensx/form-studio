# Contributing to Form Studio

Thank you for helping. Form Studio gets better fastest when people who print things bring what they know: a recipe,
a slicer that behaves differently, a measured result, a sharper check.

## Ways to contribute

| Contribution | Where it goes | Start here |
|---|---|---|
| **Recipes** | `community/recipes/<id>/` (gallery) or `form/recipes/` (built-in) | Open a [New recipe](https://github.com/kaizensx/form-studio/issues/new?template=3-recipe.yml) issue: it is built, checked and sliced for you and answered with pictures. Or `form recipes submit <id>` for the folder and a pre-filled issue. See [community/recipes](community/recipes/README.md) and [Writing a recipe](docs/RECIPES.md) |
| **Measured print results** | An issue or a [Show and tell](https://github.com/kaizensx/form-studio/discussions/categories/show-and-tell) post | Printer, nozzle, filament, slicer preset and the measured numbers. Attach a `.formstudio` file (renamed to `.zip`) and the automation replies with a turntable, four views, its checks and a slice |
| **Slicer and printer support** | `form/adapters/` | [`form/adapters/__init__.py`](form/adapters/__init__.py) defines the adapter interface; OrcaSlicer forks that kept its command line need only an entry in [`form/adapters/orca_forks.py`](form/adapters/orca_forks.py) |
| **Agent and provider support** | `form/agents/` | [`form/agents/base.py`](form/agents/base.py) defines the agent interface; model APIs are entries in [`form/agents/providers.py`](form/agents/providers.py) |
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

**Pull requests target `dev`.** A release is a merge from `dev` into `main` followed by a version tag; when and how is in [RELEASING.md](docs/RELEASING.md).

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
.venv/bin/python -m form.app --uitest tests/journeys/start.py   # drive the real window with one journey
.venv/bin/python scripts/gen_mcp_docs.py           # regenerate docs/MCP.md after changing MCP tools
.venv/bin/python scripts/make_media.py             # regenerate README media after changing recipes or the renderer
.venv/bin/python scripts/readme_art.py             # redraw the README's pictures (docs/readme) from a fresh engine and slicer run
.venv/bin/python scripts/make_app_media.py         # re-record the app animations and website videos from the app (30 fps)
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
4. Run the checks before you push (below). CI runs the test suite on Linux and macOS, checks that `docs/MCP.md` is
   current, and builds the website. A pull request that touches recipes or the interface gets before and after
   pictures in a comment.

## Checks on every pull request

| Check | What it does | Run it yourself |
|---|---|---|
| **CI** | The test suite on Linux in ten shards (with a coverage summary) and on macOS in four (the long geometry runs on macOS run on every push to `dev` and `main` and nightly), the MCP reference, actionlint and the automation's own tests; the slowest tests run nightly | `.venv/bin/python -m unittest discover -s tests` (one shard: `.venv/bin/python scripts/ci/test_shards.py run --shards 10 --index 1`; the slow ones: `FORM_SLOW_TESTS=1 FORM_SLOW=1`) |
| **Code quality** | ruff lint on the whole tree; the pre-commit hooks on the files you changed; ruff format on changed Python files, as advice | `pre-commit run --from-ref origin/dev --to-ref HEAD` |
| **Dependency review** | Fails on a new dependency with a high or critical vulnerability, or a licence that cannot ship in an MIT app | — |
| **CodeQL** | Security analysis of the Python, the website's JavaScript and the workflows | — |
| **Workflow security** | zizmor, when `.github/` changes | `pre-commit run zizmor --all-files` |
| **Dependency audit** | pip-audit on `requirements.lock`, when it changes | `uvx pip-audit -r requirements.lock --no-deps` |

The hooks live in [`.pre-commit-config.yaml`](.pre-commit-config.yaml). To run them on every commit:

```bash
uv tool install pre-commit      # or: pipx install pre-commit
pre-commit install
```

`@kaizensx` reviews every pull request ([CODEOWNERS](.github/CODEOWNERS)); an automated review may also comment.

By contributing you agree that your work is released under the [MIT licence](LICENSE), and to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
