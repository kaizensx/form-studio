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
form examples add                                  # copy the example designs into your projects
form run hallway-phone-dock                        # solid, exports, checks and slice
form simulate hallway-phone-dock --png sim.png     # the print, drawn from the G-code
form share hallway-phone-dock --out card.png       # a share card
form chat "Make the base 92 mm deep" --project hallway-phone-dock --agent codex
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
| `form setup` | Find what is missing and fix what you choose. `--check` prints the findings as JSON, `--yes` accepts every fix, `--dry-run` shows the commands only |
| `form doctor` | The kernel, slicer, printer and agents Form Studio found |
| `form install --list` | Everything Form Studio can install: parts libraries, slicers, agents, OpenSCAD, Blender, FreeCAD |
| `form install <id>` | Install one item, after showing its commands (`--yes`, `--dry-run`) |
| `form config get [key]` / `form config set <key> <value>` | Read or change `studio.toml` |
| `form secrets status \| set NAME \| clear NAME` | Agent keys such as `gemini_api_key`, read from a hidden prompt |
| `form update` | Is there a newer version (`--check` prints JSON; `--install` installs it) |
| `form examples [add]` | List the shipped examples, or copy them into your projects |

## Designs

| Command | Does |
|---|---|
| `form list` | Every project |
| `form recipe <recipe>` | A recipe's parameters, features and checks |
| `form new <name> <recipe> [key=value ...] [--brief TEXT]` | A new design from a recipe |
| `form state <project>` | The head revision: parameters with provenance, outputs, checks, fit, slice, release gate |
| `form preview <project> key=value ...` | Build a change without saving it, and report its impact |
| `form commit <project> key=value ... [--note] [--expect-head N] [--measured keys]` | Save a change as a new revision |
| `form run <project> [--force]` | Regenerate whatever is stale: solid, STEP and STL, checks, slice |
| `form history <project> [--gif FILE]` | The revision list; `--gif` writes a morph through every revision (`.gif` or `.webp`) |
| `form variants list\|save\|promote\|delete <project> [name] [key=value ...]` | Named variants |
| `form mark <project> --text TEXT` | The label text for designs with lettering |
| `form rename <project> <name>` | Change the display name (the id stays) |
| `form duplicate <project> [--name NAME]` | Copy a project under a new id |
| `form delete <project> --yes` | Move a project to the trash inside the projects folder |

## Look and analyse

| Command | Does |
|---|---|
| `form render <project> [--view iso\|front\|side\|top\|under\|sheet] [--highlight FEATURE] [--out PNG]` | An engine render coloured by feature |
| `form analyze <project> --map thickness\|overhang\|section\|features [--png FILE]` | An analysis map and its statistics |
| `form measure <project> --from x,y,z --to x,y,z` | A distance; `--at x,y,z` reports the face, edge or hole at a point |
| `form orient <project> [--apply [ID]] [--png FILE]` | Rank print orientations; `--apply` sets the best one |
| `form animate <project> [--morph 1:4] [--frames N] [--out FILE]` | A turntable, or a morph between two revisions |
| `form share <project> [--out PNG] [--photo]` | The share card; `--photo` uses the newest Blender render |

## Print

| Command | Does |
|---|---|
| `form simulate <project> [--png PNG --layer N] [--gif GIF] [--frames DIR] [--layers a:b]` | Pictures of the toolpaths building up, from the slicer's G-code |
| `form cost <project> [--price-per-kg] [--kwh-price] [--watts] [--machine-rate] [--copies] [--save]` | Filament, electricity and machine time |
| `form pack <project> [--copies N] [--spacing MM] [--no-rotate]` | Do N copies fit on one plate |
| `form optimize <project> --vary key:min:max ... --minimize\|--maximize METRIC [--require EXPR] [--budget N]` | Goal seek over parameters |
| `form verify <project> <release>` | Re-hash a release against its manifest |

## Agents

| Command | Does |
|---|---|
| `form chat "message" [--project ID] [--conversation ID] [--agent ID] [--model X] [--effort L] [--json]` | Send one message to an agent, with Form Studio's tools |
| `form conversations list \| show ID \| rename ID TITLE \| pin ID \| delete ID` | Saved conversations |

Release approval has no command. It is a deliberate action in the app's Release stage.
