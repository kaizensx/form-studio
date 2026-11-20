# Command line

Everything the desktop app does is also a `form` command. Commands print JSON, so scripts and agents can read them,
and they work on the same project folder as the app and the MCP server, at the same time.

```bash
form --help              # every command
form <command> --help    # its arguments
```

Projects live in `~/FORM` by default. Set `FORM_DATA` to use another folder, and `FORM_CONFIG` to use another
`studio.toml`.

## Quick start

```bash
form start --text "A stand for my phone, 9.5 mm thick" --photo phone.jpg   # start the way Home does
form new "Desk stand" device_stand device_width=75.6                    # or from a recipe: solid, exports, checks, slice
form commit desk-stand lean=18 --expect-head 1                          # a new revision, rebuilt and checked
form simulate desk-stand --png sim.png --layer 40                       # the print, drawn from the G-code
form share desk-stand --out card.png                                    # a share card
form chat "Make the base 92 mm deep" --project desk-stand --agent codex
```

## Apps and servers

| Command | Does |
|---|---|
| `form app` | Open the desktop app |
| `form mcp` | The MCP server over stdio (the same as `form-mcp`) |
| `form serve` | The engine's local HTTP interface on `127.0.0.1` |

## Setup

| Command | Does |
|---|---|
| `form setup` | Find what is missing and fix what you choose. `--check` prints the findings as JSON, `--yes` accepts every fix, `--dry-run` shows the commands only, `--auto` installs everything needed hands-free and waits where you must act (`--no-wait` skips those steps) |
| `form doctor` | The kernel, slicer, printer, purpose and agents Form Studio found |
| `form install --list` | Everything Form Studio can install: parts libraries, slicers, agents, OpenSCAD, Blender, FreeCAD |
| `form install <id>` | Install one item, after showing its commands (`--yes`, `--dry-run`) |
| `form config get [key]` / `form config set <key> <value>` | Read or change `studio.toml` |
| `form secrets status \| set NAME \| clear NAME` | Agent keys such as `gemini_api_key`, read from a hidden prompt |
| `form providers list \| add URL [--name N] [--no-key] \| edit ID \| test ID [--model M --tools\|--images] \| remove ID` | Model providers added by address: format and models detected; the key is read from stdin or a hidden prompt, never an argument |
| `form update` | Is there a newer version (`--check` prints JSON; `--install` installs it) |
| `form capabilities [on\|off <id>]` | What Form Studio is set up for (core, parts, mesh, render, exchange, print); off never uninstalls |

## Start a design

`form start` starts a design the way Home does: words, photos, files, a sketch and links go to an agent in one
message, with what the design is for.

| Command | Does |
|---|---|
| `form start --text "…" [--photo F]... [--file F]... [--sketch F.json] [--link URL]... [--purpose print\|model] [--agent ID] [--model X] [--json]` | A new conversation with everything attached, sent to the agent; prints like `form chat` |
| `form start --blank [--name N] [--purpose print\|model]` | A blank design (a rounded 60 × 40 × 20 mm block) built in the kernel; prints `{id, name, purpose}` |
| `form concepts` | Open concept groups, newest first |
| `form concepts <group-or-project>` | One group's board: each concept's project, title, rationale and computed size and volume |
| `form concepts pick <group> <project> [--keep-others]` | Keep one concept: it takes the group's name; the others move to the trash unless `--keep-others` |

- `--purpose print` is for 3D printing on your printer; `model` is just a 3D model: Design only is set and nothing is
  sliced. Without it, the choice you made last on Home is used, else `print` when a slicer is installed.
- `--link`: a link to a file (STL, STEP, 3MF, PDF, PNG, JPEG, WebP) is downloaded once (up to 50 MB) and attached;
  any other link is passed to the agent as a page and nothing is downloaded.
- `--sketch` takes Form Studio's sketch JSON (millimetres, y up; see `form/sketch.py`). The agent reads its geometry
  as exact numbers; a dimension with a stated value overrides the drawn length.
- Concepts are made by the agent (`propose_concepts`): three or four genuinely different designs, each a real project.

## Designs

| Command | Does |
|---|---|
| `form replace --photo FILE [--name NAME] [--what TEXT] [--broke TEXT] [--reference card\|coin\|ruler\|none]` | Start the replacement of a broken part from a photo with a scale reference |
| `form list` | Every project |
| `form recipe <recipe>` | A recipe's parameters, features and checks |
| `form new <name> <recipe> [key=value ...] [--purpose print\|model] [--process P] [--brief TEXT]` | A new design from a recipe; `--process` (for a model) is `cnc`, `laser`, `injection`, `casting`, `sheet_metal`, `render`, `cad` or `other` |
| `form purpose <project> [print\|model] [--process P]` | Read or change what a design is for |
| `form state <project>` | The head revision: parameters with provenance, outputs, checks, fit, slice, release gate |
| `form preview <project> key=value ...` | Build a change without saving it, and report its impact |
| `form commit <project> key=value ... [--note] [--expect-head N] [--measured keys]` | Save a change as a new revision |
| `form run <project> [--force]` | Regenerate whatever is stale: solid, STEP, STL, OBJ and GLB, checks, slice |
| `form history <project> [--gif FILE]` | The revision list; `--gif` writes a morph through every revision (`.gif` or `.webp`) |
| `form variants list\|save\|promote\|delete <project> [name] [key=value ...]` | Named variants |
| `form mark <project> --text TEXT` | The label text for designs with lettering |
| `form rename <project> <name>` | Change the display name (the id stays) |
| `form duplicate <project> [--name NAME]` | Copy a project under a new id |
| `form delete <project> --yes` | Move a project to the trash inside the projects folder |
| `form export <project> [--out FILE.formstudio] [--no-conversations]` | The design, its history, its conversations and the code it was built from, as one file |
| `form import FILE.formstudio \| FILE.formproj \| CONVERSATION.json` | Import; a clashing id gets a new one and nothing is overwritten |

## Look and analyse

| Command | Does |
|---|---|
| `form render <project> [--view iso\|front\|side\|top\|under\|sheet] [--highlight FEATURE] [--out PNG]` | An engine render coloured by feature |
| `form analyze <project> --map thickness\|overhang\|section\|features [--png FILE]` | An analysis map and its statistics |
| `form measure <project> --from x,y,z --to x,y,z` | A distance; `--at x,y,z` reports the face, edge or hole at a point |
| `form orient <project> [--apply [ID]] [--png FILE]` | Rank print orientations; `--apply` sets the best one |
| `form animate <project> [--morph 1:4] [--frames N] [--out FILE]` | A turntable, or a morph between two revisions |
| `form turntable <project> [--fmt mp4\|png\|webp\|gif] [--frames N] [--elevation DEG] [--out FILE]` | The part turning once, rendered from the kernel's mesh; MP4 needs ffmpeg |
| `form share <project> [--out PNG] [--photo]` | The share card; `--photo` uses the newest Blender render |
| `form select <project> [--point\|--edge\|--face x,y,z]... [--region "x,y,z;..." --radius R] [--keep NAME --note TEXT] [--text]` | Analyse points, edges, faces or a painted region on the solid: area, tilt, overhang, wall thickness, curvature, height; `--keep` saves it as an annotation |
| `form annotations <project> [list\|show\|delete] [ID]` | Kept selections |
| `form appearance <project> [--part PART] [--color #hex] [--material M] [--clear] [--3mf FILE]` | Colour and material of the design or one part; `--3mf` writes a 3MF with colours |
| `form engrave <project> TEXT --at x,y,z --normal x,y,z [--up x,y,z] [--height MM] [--depth MM] [--sunk]` | Raised or sunk text on a flat face, written into the design's code as a feature and built as a new revision; `--list` and `--remove text_N` |
| `form feature <project> boss\|snap_hook --at x,y,z --normal x,y,z [--size M3] [--hole tapped\|clearance\|insert] ...` | A screw boss or a snap-fit hook on a flat face, written into the design's code and built as a new revision |
| `form diff <project> A [B] [--png FILE]` | What changed between two revisions on the solids: material added and removed, with volumes and regions |
| `form reconstruct FILE [--name N] [--tolerance MM] [--layer 0\|1\|2]` | A mesh (STL, OBJ, 3MF) as a new design: the exact solid, analytic faces (beta) and a feature recipe (beta), each compared with the mesh |

## Print

| Command | Does |
|---|---|
| `form printers` | Every printer set up in every installed slicer |
| `form printers options KIND NAME` | A printer's filaments and processes |
| `form printers use KIND NAME [--filament F] [--process P] (--project ID \| --default)` | Use a printer for one design or as the default |
| `form printers clear (--project ID \| --default)` | Forget a design's printer, or the default |
| `form plates <project> [--orient PART=O] [--material PART=M] [--color PART=#hex]` | How the design's parts go onto plates, and per-part print settings |
| `form material <project> <PLA\|PETG\|ABS\|ASA\|TPU\|... \| "">` | The filament the slice uses |
| `form design-only <project> on\|off` | Slice this design or not |
| `form simulate <project> [--png PNG --layer N] [--gif GIF] [--frames DIR] [--layers a:b]` | Pictures of the toolpaths building up, from the slicer's G-code |
| `form cost <project> [--price-per-kg] [--kwh-price] [--watts] [--machine-rate] [--copies] [--save]` | Filament, electricity and machine time |
| `form pack <project> [--copies N] [--spacing MM] [--no-rotate]` | Do N copies fit on one plate |
| `form optimize <project> --vary key:min:max ... --minimize\|--maximize METRIC [--require EXPR] [--budget N]` | Goal seek over parameters |
| `form compare-printers <project> [--printer ID] [--limit N]` | Slice the design for real on every printer in your slicers: time, filament and cost side by side |
| `form lighter <project> [--builds N] [--apply ID]` | Lighter versions that keep every passing check passing: thinner walls, bigger pockets, less infill, each with its mass and the slicer's grams; `--apply` commits one |
| `form verify <project> <release>` | Re-hash a release against its manifest |
| `form release-files <project> [release] [--out FILE.zip]` | Every file of a release in one .zip: models, G-code, sliced 3MF, report, documents and manifest (the newest release by default) |
| `form instructions <project> [--rev N] [--out FILE.pdf]` | Assembly instructions as a PDF: a parts page, then one page per part in the order the assembly attaches them |

## Any MCP tool

| Command | Does |
|---|---|
| `form tool` | Every MCP tool with a one-line summary |
| `form tool NAME '{"key": value}'` | Call any MCP tool headless, with the same arguments, checks and refusals as over MCP ([MCP reference](MCP.md)); `-` reads the JSON from stdin |

## Agents

| Command | Does |
|---|---|
| `form chat "message" [--project ID] [--conversation ID] [--agent ID] [--model X] [--effort L] [--json]` | Send one message to an agent, with Form Studio's tools |
| `form conversations list \| show ID \| rename ID TITLE \| pin ID \| delete ID` | Saved conversations |
| `form export-conversation <id> [--format md\|json] [--out FILE]` | One conversation as Markdown (to read) or JSON (to import again) |

`form chat` asks the agent's questions in the terminal, and takes `--attach FILE` for files.

## Recipes

Recipes are building blocks for agents and the community gallery. Installing one never runs it: the code runs only
when a design is created from it.

| Command | Does |
|---|---|
| `form recipes [list] [--q WORDS] [--section builtin\|mine\|community] [--tag T] [--sort name\|recent]` | Built-in recipes, the ones you installed, and the community gallery |
| `form recipes community [--refresh]` | The community index from the website |
| `form recipes inspect FILE` | What installing a file would install: its SHA-256, title and any problems |
| `form recipes install FILE --sha256 HEX` | Install exactly that file, by its hash |
| `form recipes uninstall ID` | Remove an installed recipe |
| `form recipes export ID [--out FILE] [--author NAME] [--tags a,b]` | One `.formrecipe` file: the code, `meta.json` with its SHA-256, and a preview from a real build |
| `form recipes import FILE.formrecipe [--sha256 HEX]` | Shows the code's checksum; with `--sha256`, installs it |
| `form recipes submit ID [--out DIR] [--author NAME] [--tags a,b]` | The community submission folder, and a link to a pre-filled GitHub issue; nothing is posted |
| `form recipes derive PROJECT [--title T] [--summary S] [--range key=min:max ...] [--install --sha256 HEX]` | Turn a design into a recipe whose defaults are the design's values |

Release approval has no command. It is a deliberate action in the app's Release stage.
