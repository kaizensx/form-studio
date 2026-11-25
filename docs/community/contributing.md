# Contributing

Form Studio is open source under the MIT licence: the app, the engine, the recipes, the docs and the website. This guide shows where each kind of contribution goes, how to set up a development copy, and what a pull request needs.

## Ways to contribute

- **Recipes.** Parametric building blocks written as code, with their own checks. Open a [New recipe issue](https://github.com/kaizensx/form-studio/issues/new?template=3-recipe.yml): it is built, checked and sliced for you and answered with pictures. Or run `form recipes submit <id>` for the folder and a pre-filled issue. See [Writing a recipe](https://github.com/kaizensx/form-studio/blob/main/docs/RECIPES.md).
- **Measured results.** Printer, nozzle, filament, slicer preset and the measured numbers, in an issue or in #show-and-tell. Attach a `.formstudio` file (renamed to `.zip`).
- **Slicer and printer support.** `form/adapters/`. `form/adapters/__init__.py` defines the adapter interface. OrcaSlicer forks that kept its command line need only an entry in `form/adapters/orca_forks.py`.
- **Agent and provider support.** `form/agents/`. `form/agents/base.py` defines the agent interface; model APIs are entries in `form/agents/providers.py`.
- **The desktop app.** `form/app/qml/`, written in Qt Quick. Read `form/app/qml/CONTRIBUTING-UI.md` first.
- **Docs and the website.** `docs/` and `site/`.

Issues labelled [good first issue](https://github.com/kaizensx/form-studio/labels/good%20first%20issue) are small and self-contained. [help wanted](https://github.com/kaizensx/form-studio/labels/help%20wanted) marks larger pieces the maintainers would like a hand with.

## Branches

- `main`: stable releases. Every commit on `main` is a released or releasable version; the website deploys from it.
- `dev`: integration and testing. Features and fixes land here first.
- `feat/*`, `fix/*`: your work. Branch from `dev`.

**Pull requests target `dev`.**

## Development setup

```bash
git clone https://github.com/kaizensx/form-studio && cd form-studio
git switch dev
uv venv --python 3.12 .venv
uv pip install --python .venv -e ".[all]"
.venv/bin/python -m form.app                          # the desktop app, from source
.venv/bin/python -m unittest discover -s tests        # the test suite
```

The tests run on the real CAD kernel. Slicing tests run when a supported slicer is installed and are skipped otherwise. The interface journeys (`tests/test_ui_journeys.py`) drive the real window with mouse and key events.

## Useful commands

```bash
.venv/bin/python -m form.app --shot out.png --project hallway-phone-dock --stage prove   # screenshot the app
.venv/bin/python -m form.app --uitest tests/journeys/start.py    # drive the real window with one journey
.venv/bin/python scripts/gen_mcp_docs.py     # regenerate docs/MCP.md after changing MCP tools
.venv/bin/python scripts/acceptance.py       # the end-to-end acceptance run
python site/build.py                         # the website's docs pages, from docs/*.md
```

## Engineering principles

- **One geometry authority.** Everything derives from the design's build123d code. Outputs are never edited by hand.
- **Staleness is derived.** An artifact is current when a file exists under the hash of its inputs. If an input matters, it belongs in the key.
- **Evidence classes are not interchangeable.** A rule of thumb is `heuristic`. A formula with assumptions is `model` and states them. A slicer result is `simulated`. Only a measured print is `physical`.
- **Headless parity.** Every capability in the app is also a `form` command and an MCP tool.
- **No network calls** beyond the ones the user starts.
- **A person releases.** No code path lets an agent approve a release, start a print or upload a design.
- **Cross-platform.** macOS, Windows and Linux; UTF-8 everywhere; no POSIX-only code without a Windows path.

## Pull requests

1. Open or find an issue for anything larger than a small fix, so the approach can be agreed first.
2. Keep each pull request to one change. Include tests, and screenshots for interface changes.
3. Add a line to `CHANGELOG.md` under the next version.
4. CI runs the test suite on Linux and macOS, checks that `docs/MCP.md` is current and builds the website. A pull request that touches recipes or the interface gets before and after pictures in a comment.

By contributing you agree that your work is released under the MIT licence, and to follow the [Code of Conduct](https://github.com/kaizensx/form-studio/blob/main/CODE_OF_CONDUCT.md).

## Working with a coding agent

[AGENTS.md](https://github.com/kaizensx/form-studio/blob/main/AGENTS.md) is the guide for any coding agent (Claude Code, Codex, Gemini CLI, Cursor) working on Form Studio's code or using it to design.

## How releases happen

- **Preview** (`v1.1.0-preview.1`): at most once a week, from `dev`, when a set of features is ready to try.
- **Stable** (`v1.1.0`): every 2 to 4 weeks, after a preview has run for at least 3 days with no serious bug and every workflow is green.
- **Patch** (`v1.1.1`): fixes only, for a bug in a stable release that hurts people.

Every build is posted in #releases. Stable releases are also announced in #announcements. The details are in [RELEASING.md](https://github.com/kaizensx/form-studio/blob/main/docs/RELEASING.md).

## On this server

- Talk about the code, the docs, recipes or the website in #contributing.
- Issues, pull requests, discussions and failed runs on `main` and `dev` are posted in #github.
- **The Contributor role.** Add your GitHub login and your Discord user id to `CONTRIBUTORS` in `scripts/discord/server.py` in your pull request. The role is given when it merges.
- **Security issues** are reported privately, never in a channel: [open a security advisory](https://github.com/kaizensx/form-studio/security/advisories/new).
