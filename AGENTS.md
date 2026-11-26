# Form Studio: instructions for coding agents

This file is for any agent (Codex, Claude Code, Gemini CLI, Cursor, ...). `CLAUDE.md` and `GEMINI.md` point here.

## Using Form Studio to design a part

Prefer the MCP server (`form-mcp`). Without MCP, the `form` CLI does the same and prints JSON.

| Step | MCP tool | CLI |
|---|---|---|
| See what exists | `form_overview` | `form doctor`, `form list` |
| Learn a building block's parameters | `describe_recipe` | `form recipe device_stand` |
| Start a design from a building block | `create_project` | `form new "Desk stand" device_stand device_width=75.6` |
| Start from words, photos, a sketch, files or links | — (Home in the app) | `form start --text "a hook for my desk" --photo desk.jpg` |
| A blank design to shape | — | `form start --blank --name "Bracket"` |
| Offer different concepts for a new idea, then let the person pick | `propose_concepts` → `pick_concept`, `list_concepts` | `form concepts`, `form concepts pick <group> <project>` |
| Read the design | `get_project` | `form state <project>` |
| Try a change, save nothing | `preview_change` | `form preview <project> lean=18` |
| Look at it | `render` (`view="sheet"` for four views) | `form render <project> --view sheet` |
| Keep a change | `commit_change` with `expect_head` | `form commit <project> lean=18 --expect-head 3` |
| Regenerate outputs | `run_pipeline` / `get_job` | `form run <project>` |
| Ask for release | `request_release` (the user approves in the app) | — |
| Design from your own code (the usual case) | `design_guide` → `create_design` → `edit_design` (ops, not the file) | — |
| Say what must be true, and read what was measured | `design_brief` (contract and audit) → `get_project` (`proof`) | — |
| Read a datasheet or drawing | `read_document` (PDF pages as images) | — |
| Find the best design under constraints | `optimize` | `form optimize <p> --vary arm_t:4:20 --minimize solid_mass_g --require "statics.safety_factor>=3"` |
| Show motion | `animate` (turntable or morph) | `form animate <p> --morph 1:4` |
| Check this machine | `setup_status` (never run fixes without asking) | `form setup --check` |
| Ask the person a blocking question | `ask_user` (a card in Form Studio's chat; elsewhere it tells you to ask yourself) | `form chat` prompts in the terminal |
| Ask the person to measure a dimension | `ask_measurement` (where, tolerance, diagram; the answer is committed with how it was measured) | `form chat` prompts in the terminal |
| Offer next steps | `suggest_replies` (up to three buttons under the reply) | — |
| Put text on a flat face (a feature in the source) | `add_text`, `remove_text` | `form engrave <p> TEXT --at x,y,z --normal x,y,z` |
| See what changed in the solid between revisions | `geometry_diff` | `form diff <p> 1 3 --png diff.png` |
| Turn an STL, OBJ or 3MF into editable CAD (verified against the mesh) | `reconstruct` | `form reconstruct part.stl --tolerance 0.02` |
| Rebuild a mesh by hand: what is left to add or cut, then tune the sizes | `reference_residual`, `fit_params`, `compare_to_reference` | — |
| Assembly instructions as a PDF | `assembly_instructions` | `form instructions <p> --out steps.pdf` |

Every design has a **purpose**: `print` (for 3D printing) or `model` (just a 3D model: rendering, CAD exchange, CNC,
laser, moulding). `get_project` reports it and `form_overview` says whether the person prints at all (`has_printer`).
For a model, never ask about a printer, slicer, filament or orientation: print checks and slicing do not apply. Pass
`purpose` (and for a model `process`) to `create_project` / `create_design` when the person says what it is for.

Rules that keep the record honest:

1. **Units:** mm, degrees, grams. For a design started from a building block, only use parameter keys that `describe_recipe` lists.
2. **Preview, then commit.** Pass `expect_head` so you never overwrite someone else's newer revision.
3. **Provenance is evidence.** Mark a value `measured` only when the user measured it and gave you the number. Ask how they measured it, for example with calipers. Otherwise it stays `assumed`.
4. **Never invent physical results.** `record_physical_result` is only for what the user reports after a real print.
5. **Name evidence classes correctly.** A slice is a simulation. Fit yield is a statistical model. Checks are labelled computed, heuristic or model. Say which one you are reporting.
6. **You cannot approve a release.** The user approves in the app's Release stage, after reviewing the checks and acknowledging the warnings.
7. **No printing, no uploads.** Form Studio never sends files to a printer or a service, and you must not either unless the user explicitly asks.

## Recipes (internal building blocks)

Recipes are parametric building blocks inside the engine. Use one on your own when it fits the request, then change
anything; do not offer recipes, a recipe list or a gallery to the person. Every design starts from what the person
describes. There is no public recipe library, community gallery or submission form.

Built-in: `gridfinity_bin`, `gridfinity_baseplate`, `storage_box`, `pegboard`, `device_stand`, `cable_organizer`, `desk_hanger`, `shelf_bracket`, `hose_adapter`, `plant_pot`, `vase`, `battery_holder`, `enclosure`, `coupon`.
Retired (`legacy`, never listed, but designs that use them still build): `dock`, `gridfinity`, `hook`, `planter`, `gear_pair`, `knob`, `hinged_box`.
To write a new built-in one, see `docs/RECIPES.md`.

## Skills

Form Studio's design and print-engineering practice is written as skills in `plugins/form/skills/<name>/SKILL.md`
(intake, parametric-design, industrial-design, design-review, explore-variants, fdm-engineering, fit-calibration,
hardware-integration, assemblies-and-mechanisms, modular-storage, verify-print, print-feedback, release, cad-core,
staged-design, surfacing-organic, texture, remodel-from-mesh, game-asset). Each says when to use it and which MCP tools
to call; longer texts sit in its `references/`. Claude Code installs them as a plugin (`claude plugin marketplace add
kaizensx/form-studio`, then `claude plugin install form@form-studio`); other agents: read the matching `SKILL.md`
before that kind of task.

The source is `form/guidance/<name>/` (one text, three readers): `design_guide(topic)` returns its reference files
unchanged, `form/mcp_skills.py` serves it over MCP (`skills/list`, `skills/get`, `resources/read` at
`skill://<name>/SKILL.md`; `skills_extension()` is what the server registers), and `scripts/gen_skills.py` writes
`plugins/form/skills`. Edit `form/guidance`, then run `.venv/bin/python scripts/gen_skills.py`; a test fails on drift.
Skill text is instructions an agent follows: no steps that fetch, download or run anything the person did not give.

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
.venv/bin/python scripts/readme_art.py              # the README's pictures (docs/readme/*.svg), drawn from a real engine and slicer run
.venv/bin/python scripts/make_app_media.py          # app animations, recorded from the real app window (the website draws the app in code)
.venv/bin/python site/tools/export_proof.py         # the home page's proof sheet, stamped from a real run of scripts/proof_demo.py
.venv/bin/python scripts/media/site_shot.py URL OUT  # a picture of the website's live replica (docs/images/try-it*.webp)
.venv/bin/python scripts/media/showcase/product_shots.py  # product pictures for the site and README (scripts/media/showcase/README.md)
.venv/bin/python scripts/gen_mcp_docs.py            # regenerates docs/MCP.md
.venv/bin/python scripts/gen_preflight_api.py       # regenerates form/preflight_api.json (the API preflight checks names against)
.venv/bin/python scripts/proof_demo.py              # brief with a trap, a red proof row, one edit op, a green sheet (real MCP, no model)
```

Branches: `main` holds releases; `dev` is where work lands first. Open pull requests against `dev`.
