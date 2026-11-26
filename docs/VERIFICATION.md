# Compatibility and testing

Which platforms, slicers, agents and programs Form Studio works with, and what the continuous integration exercises on
every change.

**Status labels**

| Label | Meaning |
|---|---|
| **CI** | Exercised automatically by a GitHub Actions workflow, with the real program where named |
| **Supported** | Implemented and covered by unit tests against fixtures; not run by CI with the real program |

## Platforms

| Platform | Engine tests | Packaged app starts | Interface journeys | Real slices |
|---|---|---|---|---|
| macOS, Apple Silicon | CI | CI | Supported | Supported |
| macOS, Intel | CI | CI | Supported | Supported |
| Windows 10 and 11, x64 | CI | CI | CI | CI |
| Linux x64 (glibc 2.35+) | CI | CI | CI | CI |

- **Engine tests:** the full test suite on the real CAD kernel.
- **Packaged app starts:** the built bundle is launched; its window must load, the engine must answer and the CAD kernel
  must start.
- **Interface journeys:** the real window driven with mouse and key events through design, slice, simulation and
  release (`tests/journeys/`).
- **Real slices:** the official build of each slicer is installed on the runner and a design is sliced through Form
  Studio; time, filament and layers are read back from the G-code.

## Slicers

| Slicer | Version in CI | Linux | Windows | macOS | Notes |
|---|---|---|---|---|---|
| Bambu Studio | 2.9.1 | CI | CI | Supported | Presets from the slicer's selection or pinned in Settings |
| OrcaSlicer | 2.5.1 | CI | CI | Supported | Packed vendor profiles (`.opc`) read directly |
| PrusaSlicer | Ubuntu package (Linux), Chocolatey (Windows) | CI | CI | Supported | Bundled vendor profiles used without opening the slicer |
| SuperSlicer | 2.5.59 | CI | CI | Supported | |
| QIDISlicer | 1.2.5 | CI | CI | Supported | |
| ElegooSlicer | 1.5.3.5 | CI | CI | Supported | OrcaSlicer family |
| Snapmaker Orca | 2.4.1 | CI | CI | Supported | OrcaSlicer family |

Every printer set up in one of these slicers can be chosen, per design or as the default. Time and filament are the
slicer's own estimate and are labelled *simulated*.

**Every night**, every built-in recipe is sliced by every slicer above on Linux, and the result of each
recipe and slicer pair (built, sliced, checks passed, print time, filament, layers) is published as the
[compatibility matrix](https://kaizensx.github.io/form-studio/compat/). The pipeline's timings per recipe and the app's
start time are tracked on every change to `dev` and drawn as [benchmarks](https://kaizensx.github.io/form-studio/bench/).

## Agents

| Agent | Chat inside the app | MCP from the agent's own window | Notes |
|---|---|---|---|
| Claude Code | Supported | Supported | Sign-in from the app |
| Codex | Supported | Supported | |
| Gemini CLI | Supported | Supported | Sign in, or paste an API key in Settings › Agents & models |
| Cursor CLI | Supported | Supported | |
| OpenCode | Supported | Supported | |
| Qwen Code | Supported | Supported | |
| GitHub Copilot CLI | Supported | Supported | |
| Model APIs: Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, DeepSeek, Groq | Supported | | Found from your key; Form Studio runs the conversation and its tools |
| Local models: Ollama, LM Studio, llama.cpp | Supported | | Found from their running servers |
| Any provider added by its address | Supported | | OpenAI-, Anthropic- or Gemini-compatible, or Ollama; format and models detected |
| Claude Desktop | | Supported | |
| Any MCP client over stdio | | Supported | `{ "mcpServers": { "form": { "command": "form-mcp" } } }` |

The MCP server itself is tested in CI over real stdio (`tests/test_mcp.py`): tools are listed and called, renders come
back as images, a stale `expect_head` is refused, and no tool can approve a release.

## Other programs

| Program | Used for | Status |
|---|---|---|
| build123d on OpenCascade | Every solid, STEP export and B-rep check | CI |
| FreeCAD 1.x | Open the STEP, re-import check, parameter macro | Supported |
| OpenSCAD | `.scad` designs with Customizer parameters | Supported |
| Blender | Photoreal renders; 3D-Print Toolbox checks when installed | Supported |
| STEP and STL files | Reference parts to design around | CI |

## Continuous integration

| Workflow | Runs | On |
|---|---|---|
| [CI](../.github/workflows/ci.yml) | The test suite in parallel shards balanced by `tests/ci_timings.json` (`scripts/ci/test_shards.py`): on Linux the whole suite in ten shards with line coverage; on macOS everything but the long geometry runs (mesh to CAD, remodelling, the design bench, mesh bodies) in five shards for a pull request, and the whole suite in five for every push and every night. A pull request that changes only docs, the site, artwork or other workflows leaves the long geometry runs out on Linux too. Checks that the MCP reference matches the server | Linux, macOS; every push to `main` and `dev`, every pull request, nightly on `dev` |
| [Slow tests](../.github/workflows/slow-tests.yml) | The design bench's helmet and mouse exemplars, the 250 MB STL preflight and the 200k-triangle helmet run (`FORM_SLOW_TESTS=1`, `FORM_SLOW=1`) | Linux, macOS; nightly on `dev` |
| [Desktop app](../.github/workflows/app.yml) | Engine tests, the app bundle build, the packaged app launch | macOS arm64 and x64, Windows, Linux |
| [Interface tests](../.github/workflows/ui.yml) | The interface journeys with a real PrusaSlicer | Windows, Linux |
| [Real slicers](../.github/workflows/slicers.yml) | A real slice with each slicer's pinned official build, verified by SHA-256 | Windows, Linux |
| [Compatibility matrix](../.github/workflows/compat.yml) | Every recipe through every slicer CI installs | Linux, nightly |
| [Benchmarks](../.github/workflows/bench.yml) | Pipeline time per recipe and app start time | Linux, every change to `dev` |
| [Release smoke test](../.github/workflows/release-smoke.yml) | The latest published release, downloaded and checked against `SHA256SUMS`, then opened and used | All four platforms, nightly |
| [PR preview](../.github/workflows/pr-preview.yml) | Before and after pictures of the recipes and interface a pull request changes | Linux, on the pull request |
| [CodeQL](../.github/workflows/codeql.yml) | Static analysis of the engine, the app, the website's JavaScript and the workflows | Every push and pull request |
| [Links](../.github/workflows/links.yml) | Links in the docs and the website | Pull requests; every link weekly |
| [Website](../.github/workflows/pages.yml) | Docs build, recipe index, link and page-weight check | Linux |

## Running the tests yourself

```bash
python -m unittest discover -s tests          # the suite; slicing tests run when a slicer is installed
FORM_UI_TESTS=1 python -m unittest tests.test_ui_journeys   # the interface journeys in the real window
python scripts/acceptance.py                  # end to end: from the first revision to the release, recovery, rebuild latency
```

## What results mean

Form Studio labels every number with how it is known. A geometric check is *computed* on the kernel's solid. A slice
is *simulated*. Fit yield and tip-over are *models* with stated assumptions. Only a measurement from a real print, entered
by you, is *physical*; coupon measurements calibrate the fit model for your printer and filament.
