# Form Studio: instructions for coding agents

This file is for any agent (Codex, Claude Code, Gemini CLI, Cursor, ...). `CLAUDE.md` and `GEMINI.md` point here.

## Using Form Studio to design a part

Prefer the MCP server (`form-mcp`). Without MCP, the `form` CLI does the same and prints JSON.

| Step | MCP tool | CLI |
|---|---|---|
| See what exists | `form_overview` | `form doctor`, `form list` |
| Learn a recipe's parameters | `describe_recipe` | `form recipe device_stand` |
| Start a design | `create_project` | `form new "Desk stand" device_stand device_width=75.6` |
| Start from words, photos, a sketch, files or links | — (Home in the app) | `form start --text "a hook for my desk" --photo desk.jpg` |
| A blank design to shape | — | `form start --blank --name "Bracket"` |
| Offer different concepts for a new idea, then let the person pick | `propose_concepts` → `pick_concept`, `list_concepts` | `form concepts`, `form concepts pick <group> <project>` |
| Read the design | `get_project` | `form state <project>` |
| Try a change, save nothing | `preview_change` | `form preview <project> lean=18` |
| Look at it | `render` (`view="sheet"` for four views) | `form render <project> --view sheet` |
| Keep a change | `commit_change` with `expect_head` | `form commit <project> lean=18 --expect-head 3` |
| Regenerate outputs | `run_pipeline` / `get_job` | `form run <project>` |
| Ask for release | `request_release` (the user approves in the app) | — |
| Design something no recipe covers | `design_guide` → `create_design` → `update_design` | — |
| Read a datasheet or drawing | `read_document` (PDF pages as images) | — |
| Find the best design under constraints | `optimize` | `form optimize <p> --vary arm_t:4:20 --minimize solid_mass_g --require "statics.safety_factor>=3"` |
| Show motion | `animate` (turntable or morph) | `form animate <p> --morph 1:4` |
| Check this machine | `setup_status` (never run fixes without asking) | `form setup --check` |
| Ask the person a blocking question | `ask_user` (a card in Form Studio's chat; elsewhere it tells you to ask yourself) | `form chat` prompts in the terminal |
| Ask the person to measure a dimension | `ask_measurement` (where, tolerance, diagram; the answer is committed with how it was measured) | `form chat` prompts in the terminal |
| Offer next steps | `suggest_replies` (up to three buttons under the reply) | — |
| Put text on a flat face (a feature in the source) | `add_text`, `remove_text` | `form engrave <p> TEXT --at x,y,z --normal x,y,z` |
| See what changed in the solid between revisions | `geometry_diff` | `form diff <p> 1 3 --png diff.png` |
| Assembly instructions as a PDF | `assembly_instructions` | `form instructions <p> --out steps.pdf` |

Every design has a **purpose**: `print` (for 3D printing) or `model` (just a 3D model: rendering, CAD exchange, CNC,
laser, moulding). `get_project` reports it and `form_overview` says whether the person prints at all (`has_printer`).
For a model, never ask about a printer, slicer, filament or orientation: print checks and slicing do not apply. Pass
`purpose` (and for a model `process`) to `create_project` / `create_design` when the person says what it is for.

Rules that keep the record honest:

1. **Units:** mm, degrees, grams. Only use parameter keys that `describe_recipe` lists.
2. **Preview, then commit.** Pass `expect_head` so you never overwrite someone else's newer revision.
3. **Provenance is evidence.** Mark a value `measured` only when the user measured it and gave you the number. Ask how they measured it, for example with calipers. Otherwise it stays `assumed`.
4. **Never invent physical results.** `record_physical_result` is only for what the user reports after a real print.
5. **Name evidence classes correctly.** A slice is a simulation. Fit yield is a statistical model. Checks are labelled computed, heuristic or model. Say which one you are reporting.
6. **You cannot approve a release.** The user approves in the app's Release stage, after reviewing the checks and acknowledging the warnings.
7. **No printing, no uploads.** Form Studio never sends files to a printer or a service, and you must not either unless the user explicitly asks.

## Recipes

Built-in: `gridfinity_bin`, `gridfinity_baseplate`, `storage_box`, `pegboard`, `device_stand`, `cable_organizer`, `desk_hanger`, `shelf_bracket`, `hose_adapter`, `plant_pot`, `vase`, `battery_holder`, `enclosure`, `coupon`.
Retired (`legacy`, never listed, but designs that use them still build): `dock`, `gridfinity`, `hook`, `planter`, `gear_pair`, `knob`, `hinged_box`.
Community recipes are in `community/recipes/`. To write a new one, see `docs/RECIPES.md` and `community/recipes/README.md`.

## Skills

Form Studio's design and print-engineering practice is written as skills in `plugins/form/skills/<name>/SKILL.md`
(intake, parametric-design, industrial-design, design-review, explore-variants, fdm-engineering, fit-calibration,
hardware-integration, assemblies-and-mechanisms, modular-storage, verify-print, print-feedback, release). Each says when
to use it and which MCP tools to call. Claude Code installs them as a plugin (`claude plugin marketplace add
kaizensx/form-studio`, then `claude plugin install form@form-studio`); other agents: read the matching `SKILL.md`
before that kind of task.

## Working on Form Studio's code

- **One geometry authority:** a recipe in `form/recipes/`, built by build123d (OCCT). STEP, STL, checks and slices are derived from it and are never edited by hand.
- **Never mark anything current by hand.** An artifact is current only when it exists under the key `Studio.keys` computes from the head revision's inputs. If an input matters, put it in the key.
- **OCCT runs only in the worker process** (`form/worker.py`). The MCP server, the app's engine and the CLI must stay importable without it.
- **Software Form Studio drives sits behind adapters** (`form/adapters/`). To add a slicer, write a module with the interface described in `form/adapters/__init__.py`, register it in `SLICERS`, and select it with `[slicer].kind`.
- **New recipe:** subclass `Recipe` with typed `Param`s, ordered `Stage`s named after `Feature`s, and `constraints()` that return `RecipeError`s naming a feature, the parameters involved and a hint.
- **Project mutations take `Studio.lock(pid)`.** It locks across processes, because the app, MCP servers and the CLI can run at the same time.

Commands:

```
./run.sh                                            # set up .venv and start the engine on 127.0.0.1
.venv/bin/python -m form.app                        # the desktop app from source
.venv/bin/python -m unittest discover -s tests      # includes an MCP stdio end-to-end test
.venv/bin/python scripts/acceptance.py              # writes docs/ACCEPTANCE_RUN.md
.venv/bin/python scripts/make_media.py              # regenerates docs/assets from real builds
.venv/bin/python scripts/make_app_media.py          # README animations, recorded from the real app window (the website draws the app in code)
.venv/bin/python scripts/media/site_shot.py URL OUT  # a picture of the website's live replica (README hero docs/images/try-it*.webp)
.venv/bin/python scripts/gen_mcp_docs.py            # regenerates docs/MCP.md
```

Branches: `main` holds releases; `dev` is where work lands first. Open pull requests against `dev`.
