# Development history

Form Studio was built in the open before its first public release. These are the notes of those development builds,
numbered 5.0.0 to 12.2.0. Build 12.3.0 was renamed 1.0.0, the first public release ([changelog](../CHANGELOG.md)); how releases are numbered is in [RELEASING.md](RELEASING.md).

### 12.2.0

- **One place to type.** With a conversation open on Home, the middle of Home steps aside instead of showing a second box; **New design** (Ctrl+N, the menus, the palette) starts a fresh conversation, as a new chat does in Claude, and the one you were in stays in the list. Files attached to an unsent message are kept.
- **Every MCP tool from the terminal.** `form tool` lists them; `form tool NAME '{json}'` calls any of them headless with the same arguments, checks and refusals as over MCP, so everything an agent can do is also a command.
- **Every file of a release from the terminal.** `form release-files <project> [release] [--out FILE.zip]` writes the same .zip as **Save files…**: models, G-code, the sliced 3MF, report, documents and manifest.
- **A Discord community server** with the Form Studio bot: releases, discussions, issues, pull requests and a weekly digest are posted there from GitHub Actions.
- **Motion that follows where you go.** Screens hand over by depth (going into a design the workspace grows in and its inspector slides after it; going back, Home settles), Prove counts its results up and the checks rise in one after another, chat messages rise into place with a caret while a reply is written, step groups unfold in a cascade, and focus rings close in on the control. Reduced motion keeps only the fades.
- **The mark is the loader.** The opening screen builds the Form Studio mark while the CAD kernel starts, and every loading state in the app is the same mark building itself.
- **Save a whole release.** Release › Releases › **Save files…** saves every file of a release in one .zip (STEP, STL, sliced 3MF, G-code, report, documents); **Show in Finder** opens its folder.
- **Opening a design from Home:** an outline grows from where you typed into the 3D view.

### 12.1.0

- **Text on any flat face.** In Annotate, pick a point on a flat face and choose **Text here…**: type the words, raised or sunk, cap height and depth, with the stroke width and cap height checked against your nozzle as you type (computed on the glyphs). **Add to design** writes the lettering into the design's own code as a feature (one stage per text, in Form Studio's bundled font) and builds a new revision in the kernel; text off the part or on a curved face is refused with the reason. `form engrave <project> TEXT --at x,y,z --normal x,y,z [--sunk]`, `--list`, `--remove text_N`; MCP `add_text`, `remove_text`.
- **What changed, on the solids.** Compare with head (Release › Revisions) now also compares the two solids in the kernel: material added in green and removed in red over the new revision, the whole part and a view framed on the change, with the volume and number of regions of each, computed with booleans on the B-rep. `form diff <project> A [B] --png out.png`; MCP `geometry_diff`.
- **Assembly instructions as a PDF.** Maker documents › **Make assembly instructions** draws a parts page (each part with its computed volume) and one page per part going on, in the order the assembly declaration attaches them, at its exploded offset with an arrow to where it seats. Step text is the part's own note, or exactly what the declaration says; a design without an assembly declaration has none. Page previews in the app, **Save PDF…**; `form instructions <project> [--out file.pdf]`; MCP `assembly_instructions`.

### 12.0.1

- **Edits never wait for a slice.** Changing a colour or material, a setting, the printer or a note goes through at once while the pipeline builds, checks or slices; the run records its results without undoing what changed meanwhile. One pipeline runs per project at a time, and deleting a project waits for it.
- **A slice whose G-code was written is kept.** Snapmaker Orca on Windows writes the whole G-code and then crashes drawing the project thumbnail with software OpenGL; Form Studio now keeps that G-code, says what happened, and keeps no half-written project 3MF. Every slicer in the real-slicer matrix (Bambu Studio, OrcaSlicer, ElegooSlicer, Snapmaker Orca, QIDISlicer and SuperSlicer on Windows and Linux) slices for real again.

### 12.0.0

- **Start from anything.** Home is one composer for words, a photo, a sketch, a STEP, STL or 3MF part, a PDF drawing or a link; drop or paste them anywhere on Home. A model page link is passed to the agent; only a direct file link is downloaded, and the composer shows what was fetched. `form start --text … --photo … --sketch … --file … --link …`.
- **Photos with a scale.** With a bank card, a coin or a ruler in the photo, the agent estimates sizes from it, labels them "estimated from the photo" and keeps them assumed until you measure.
- **A sketch pad.** Lines, rectangles, circles, arcs, freehand and dimensions in millimetres, snapped to a grid and to your points, with undo. The agent receives the shapes as structured geometry and the picture, and extrudes or revolves them faithfully.
- **For my printer, or just a 3D model.** Chosen on Home for what starts next; a 3D model is not sliced and has no print checks. The printer and the agent and model are chosen right under the composer, which sits in the middle of Home, with a Continue link to the last design.
- **Start blank is blank.** It opens the workspace with an empty build plate and the conversation: describe, sketch or import what goes on it. **Start from a block** gives a rounded block shaped with sliders, no agent needed.
- **Designs open faster.** Geometry views are kept on disk, keyed by the design's code, values and versions, so opening a design again does not rebuild it (21 s to 1.5 s on a large one).
- **The top bar is the title bar.** Drag it to move the window, double-click it to zoom; the window buttons sit centred on it on macOS, and the wordmark is in proportion with the design's name.
- **The workspace opens at once.** Sending from Home shows the design being made, with what the agent is doing, and attaches the design the moment it exists.
- **Watch it being built.** Each new build from the agent grows into the viewport feature by feature, in build order, each one named as it arrives.
- **Concepts first.** For a new idea the agent proposes three or four genuinely different concepts as real CAD, side by side and turning, with a line on each and their computed size and volume. Continue with one, or ask for a mix in words. MCP `propose_concepts`, `pick_concept`, `list_concepts`; `form concepts`.
- **Measure this.** When the agent needs a real number it shows where to measure on a picture or a diagram, the unit, the tolerance that matters and what the design assumes now. The number you enter is committed with how you measured it (calipers, ruler, tape, or an estimate kept as assumed) and the part updates. MCP `ask_measurement`.
- **Recipes and briefs leave the interface.** No recipe library, brief templates or starter chips on Home, in the new-design flow or the command palette; agents may still build on recipes, community recipes still install from the CLI, and existing designs open and build as before. The New design sheet is now Import.
- **Assemblies that move like the real thing.** Joints form chains: a part can be fixed to another (`Part(attach="arm")`) or move on a joint mounted on another part (`hinge(..., parent="arm")`), so turning an arm swings the cup on it and the bolt in the cup, in the viewport sliders, the Assembled and Exploded views and the checks. Exploded offsets are relative to the parent. Ratchet joints (`step=15`) are checked at the positions they click to. Existing declarations work unchanged.
- **Joined parts are fits, not collisions.** `Mate(a, b, "pin" | "thread" | ...)` declares a pin in its hole or a thread in its thread; the pair is measured against its clearance instead of booleaned, and a thread's arbitrary phase is searched.
- **Assembly checks in seconds, within a budget.** Parts are compared on their meshes and booleaned only where they meet; joint sweeps refine near contact, give the first contact angle and prove motion free between positions where the clearance allows. They run in their own time budget (`[assembly].budget_s`, 45 s) with progress, and a partial result says which range was checked instead of timing out. A five-part shower holder with fine threads went from not finishing in 15 minutes to 20 s.
- **Wrong assembly declarations are refused with the reason** (unknown part, a loop, a part with two parents) when a design is created or updated.
- **Design without a 3D printer.** The first run and Settings › General ask once: "I have a 3D printer" or "I just design". Someone who only designs gets no printer chip, no slicer install, no slicer in setup or the hands-free first start, and no Printing tab; the top bar reads "No printer · Just designing".
- **Every design has a purpose:** For 3D printing, or Just a 3D model (rendering, CAD exchange, CNC, laser cutting, moulding, visualisation). New designs start from your answer; change it any time in the Brief or from the top bar. `form new … --purpose model --process cnc`, `form purpose <project> model`, MCP `create_project` / `create_design` / `set_print_setup` take `purpose` and `process`, and `get_project` reports it.
- **A 3D model is checked as a model.** Overhangs, bridges, plate contact, the build volume, nozzle walls, the printer-accuracy fit model and the slice are not run and Prove says so; size, a valid solid, a closed mesh, the STEP round trip, loads and assembly checks still run, and the thinnest feature is compared with the process you name. The pipeline has no Slice step and the Fit stage is hidden.
- **Releases of a 3D model** hold STEP, STL, 3MF, OBJ and GLB, a four-view sheet and an iso render, with no G-code and no print report; the gate never mentions slicing.
- **OBJ and GLB exports** for every design, written next to STEP and STL, headless too.
- **Settings that apply at once.** Choosing the default printer (from Settings › Printing or the printer picker) updates Settings, the top bar, the plate and the open design's checks without a restart; "I just design" hides printing everywhere immediately. Checks use the printer your slicer slices on, not a separate bed size.
- **Settings rebuilt:** General, Printing, Agents, Other apps, Updates, Advanced and Software, with search. Agent, model and effort are picked from what is set up; slicers and programs (Blender, OpenSCAD, FreeCAD, Claude Code) show whether and where they were found, with Browse as a fallback and what each one unlocks; numbers are checked as you type; every value can be reset to its default. Preset names are no longer typed by hand.
- **Agents never ask a designer about a printer.** The in-app agent and MCP clients are told whether you print and what each design is for.
- **New building blocks for agents, made of the things people print most:** Gridfinity bin and baseplate, a box with a sliding, press-on or hinged lid, SKÅDIS pegboard accessories, a phone and tablet stand, a cable organizer, an under-desk hanger, a shelf bracket, a hose and pipe adapter, a self-watering planter, a faceted vase and lamp shade, and a battery and card holder. Each passes its checks at its defaults and prints without supports; multi-part recipes show Assembled and Exploded views. Agents use them as starting points and change anything; they are in the website gallery with categories and tags. The older dock, wall hook, twisted planter, gear pair, knob, hinged box and Gridfinity bin leave the library; designs that use them still open and build.
- **Community recipes.** Install a `.py` or `.scad` recipe from a file or from the gallery on the website, after reading its source and SHA-256, with `form recipes install`. Downloads are verified against the index, nothing runs until a design is created, and `form recipes uninstall` removes one.
- **Move designs anywhere.** Export a design with its conversations and code as one `.formstudio` file and import it again; clashing ids get new ones and nothing is overwritten. Conversations export as Markdown or JSON. `form export`, `form import`, `form export-conversation`.
- **The agent asks when it needs to.** Questions arrive in the conversation as cards with choices, several choices, your own words or an approval, and the agent waits for your answer. `form chat` asks in the terminal.
- **Suggested replies, change cards and revision links.** Replies can end with suggested next messages. A reply that changed the design shows r01 → r02 with Compare and Go back. A revision name like r04 opens it.
- **Fix with your agent.** Failed checks, pipeline steps, slices, drafts that don't build and Blender renders have a Fix button that sends the failure to the design's conversation.
- **Opening a conversation opens its design.**
- **Model names with their version** ("Opus 5.5"), taken from what the agent reports, in the picker and on every reply.
- **More agents:** Cursor CLI, OpenCode, Qwen Code and GitHub Copilot CLI, with install entries, sign-in checks and an Agents list in Settings › Agents.
- **Every printer you have.** Form Studio finds every printer set up in every installed slicer and lets you choose printer, filament and process per design or as the default. Slicing and the bed-size and nozzle checks follow the choice. `form printers`, MCP `list_printers` and `choose_printer`.
- **Your own Bambu Studio printers slice.** The slicer used to refuse them as incompatible with the process.
- **More slicers:** ElegooSlicer and Snapmaker Orca.
- **Setup by itself.** First start installs what Form Studio needs and pauses only when you have to sign in or download something, then carries on once it is done. `form setup --auto` does the same headless.
- **Exploded views for every multi-part design.** The enclosure and the gear pair declare how their parts go together, with interference and clearance checks; any design with several bodies gets As modelled and Exploded views.
- **Thinnest wall measures walls, not contacts or edges.** In a design of several parts, a wall is now measured inside its own part: a bolt resting in its nut no longer reads as a 0 mm wall. A wedge where a slanted face meets another (a tapered edge at the plate) is no longer a wall either; only faces within 30° of parallel count. A real thin fin still fails.
- **Release over failed checks, on the record.** A failed check no longer makes a release impossible: tick each failed check and write why, and the release, its manifest and its report say it was released with failed checks. Missing or stale files still block, and agents still cannot approve.
- **Measuring works everywhere.** On every multi-part design and in every view (print layout, assembled, exploded), clicks answer at once instead of rebuilding the solid, measurements follow the parts, and a click that misses the part says so.
- **Annotate (N).** Pick faces, edges and points, or brush and lasso regions on the part; see area, tilt, overhang, wall thickness, curvature and height above the bed computed on the solid; keep a selection with a name and a note as a pin on its revision; ask the agent about it with the exact numbers, or cut a section through it. `form select`, `form annotations`, MCP `analyze_selection`, `annotate`, `list_annotations`.
- **Assembled view, honestly.** Designs that say how their parts go together get Assembled, Exploded and Print layout. Designs with separate bodies that don't say show Assembled as unavailable, explain why and offer to ask the agent to add it; their bodies are named after their main feature.
- **Colours and materials** per design or per part, drawn in the viewport, exported as a 3MF with colours, and used in the checks (heat, sunlight, warping, flexible and fibre-filled filament). A material picks the printer's matching filament preset, one material per plate. `form appearance`, `form material`, MCP `set_appearance`.
- **Several plates.** A design whose parts do not fit one plate is laid out part by part on as many plates as needed, each sliced, with time, filament and cost added up; Prove and the print simulation switch between plates. `form plates`, MCP `plate_plan`, `set_part_print`.
- **Design only.** Slicing is optional per design, for every design, or when no slicer is installed; checks, exports, renders and releases work without it, and the release says what it does not cover.
- **Any model, any provider.** Chat with model APIs (Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, DeepSeek, Groq) and local models (Ollama, LM Studio, llama.cpp), found from your keys and running servers; no agent app needed. Settings › Agents lists agent apps, provider keys and local models in one place, and first start lets you choose any of them.
- **Add any provider by its address.** Settings › Agents › Add a provider… (or `form providers add URL`) takes a base URL and an optional key, finds the format (OpenAI-, Anthropic- or Gemini-compatible, with or without `/v1`, Ollama), reads the models and which call tools, and shows "Connected: OpenAI-compatible, 37 models, tools supported" before you save. The key is kept in Form Studio's private secrets file and never shown again. Saved providers are agents in the model menu, in `form chat --agent`, and can be edited, tested on one model or removed.
- **A model menu for hundreds of models.** Search, vendor sections, ↑ ↓ and Return, free models marked, models you used pinned under Recent. Batch-only variants and models without tool calls are left out.
- **No surprise default.** A provider's Default is the model you last used with it; until then the menu asks you to pick one instead of choosing the newest. Switching agents brings back the model you last used with that agent.
- **Default says which model it is** when the agent itself says so: Codex's config (Default · GPT-6.1-Sol), Gemini CLI's and OpenCode's settings, or the version the agent reported on its last run with Default. Never another agent's model, and never a guess. Gemini CLI and Copilot CLI list their own models; OpenCode lists all of its connected ones.
- **Chat:** retry with another model, token counts on replies, a model picker grouped by kind with filtering. A model learned for one agent no longer appears under another (Codex showed "Opus 5.5"); existing data is repaired automatically.
- **Clear version errors.** When an agent CLI, slicer, Blender, FreeCAD or OpenSCAD version outside the supported range is why something failed, the error names the supported versions and what to do.
- **Share recipes from the command line.** Save a recipe as one `.formrecipe` file (code, meta.json with its SHA-256, and a preview from a real build), open one with the code and checksum shown before anything is installed, share to the community through a pre-filled GitHub form (nothing is posted from Form Studio), or turn a design into a recipe. `form recipes export|import|submit|derive`.
- **Feedback on every click.** Buttons show a spinner and a working label while the engine works and ignore repeat clicks; a bar under the top bar names any work over 300 ms with progress for the pipeline, and a toast says when it finished or failed.
- **Bambu Studio:** a filament the default build plate cannot take is sliced on a plate it supports.
- **GitHub automation:** recipes submitted in an issue are built, checked, sliced and answered with pictures; pull requests get before/after previews; a nightly slicer compatibility matrix and benchmarks are published on the website; releases ship with SHA256SUMS, build provenance and an SBOM.
- **What's New** after every update, once, and any time from About and Help.
- **Update channel:** Stable (releases) or Preview (pre-releases from the `dev` branch), in Settings.
- **A new website and README,** with every feature, a recipe gallery, documentation pages and a guide to contributing. Issue forms, discussions and labels on GitHub.

### 11.1.1

- **Agents can read datasheets and drawings from the web in the installed app.** Every https read failed with a certificate error, because the app did not use the certificates it ships. Links that start with http:// are tried over https first. A site that only serves browsers is named as such, with the way around it: attach the file to the conversation.
- **Chat in the installed app now gives the agent this app's own tools.** It used to start whatever `form-mcp` was on the computer's PATH, often an older command-line install, so the agent worked with an old copy of Form Studio.
- **Blender renders work in the installed app:** the script Blender runs was missing from the app.
- **macOS:** the window title is no longer drawn over the top bar.
- **Release check on the built app** (`scripts/smoke_packaged.py`): opens the window, builds and slices a design, draws the print, starts the app's own MCP server, reads a datasheet over https and renders in Blender, all with the packaged program instead of the source.
- GitHub workflows run only when started by hand, so a private repository does not spend Actions minutes on every push.
- **Brief presets** are found however the agent writes the name ("bathroom mount", "Bathroom Mount", "bathroom-mount").
- **Timeline:** dragging through revisions and pressing "Back to head" always returns to the head; a late answer for an older revision could put it back on screen.
- **Chat:** when an agent run fails or is stopped, its error or end is saved before the conversation shows it as finished.
- The MCP reference uses the Form Studio name.

### 11.1.0

### Form Studio
- **A name and a mark.** FORM is now **Form Studio**, with the Frame mark: an F drawn as a coordinate frame, its origin in datum mint. A new app icon on macOS, Windows and Linux, and the mark in the title bar, first start and About. The `form` command, file names and release assets are unchanged, so updates and existing installs keep working.
- **A new website**, with Form Studio itself drawn live in the page from the engine's own data: the phone dock's real geometry, its twelve checks, the fit model and the toolpaths from Bambu Studio's G-code. It plays on its own and you can take over: orbit the part, switch stages, scrub the print.
- **A new README** with retina screenshots of the app.

### Every slicer Form Studio supports, run for real on Windows and Linux
- A new CI workflow, **Real slicers**, installs the official builds and slices a design through Form Studio on Windows and Linux, weekly and whenever the slicer code changes. All eight jobs pass:

  | Slicer | Linux | Windows |
  |---|---|---|
  | OrcaSlicer 2.5.1 | 86 min, 59.99 g | 86 min, 59.99 g |
  | Bambu Studio 2.9.1 | 75 min, 66.94 g | 77 min, 66.95 g |
  | SuperSlicer 2.5.59 | 298 min, 65.5 g | 299 min, 65.5 g |
  | QIDISlicer 1.2.5 | 100 min, 61.23 g | 100 min, 61.23 g |

  (The phone dock, 177 layers in every run, each slicer's own default printer. Print simulation and cost ran on every result.)
- **QIDISlicer 1.2.5 on macOS** sliced for real too: QIDI Q1 Pro, 1 h 40 min, 61.24 g.
- Fixed on the way: Bambu Studio presets on a copy that was never opened; Bambu Studio as an unpacked AppImage; QIDISlicer not found on Windows (it has no console program); SuperSlicer and QIDISlicer profiles in their Linux and AppImage layouts; SuperSlicer's version read as unknown; slicer versions on Windows, where window programs print nothing; and a SuperSlicer Flathub id that does not exist.

### Gemini CLI inside Form Studio
- **Paste a Gemini API key once in Settings, Chat.** FORM keeps it in a private file on this computer (never in `studio.toml`), never shows it again, and gives it only to Gemini CLI. `form secrets set gemini_api_key` does the same without a window; the value is read from a hidden prompt, never from the command line. MCP cannot read or change it.
- A real run of Gemini CLI 0.68.0 through FORM showed it stops when it is not signed in. FORM now says that plainly and points to Settings instead of to a file in your home folder.
- The installer offers **Gemini CLI** and **Codex** (the publishers' npm packages), shows whether Gemini is signed in, and lists **SuperSlicer** and **QIDISlicer** with their official downloads. Homebrew withdrew SuperSlicer because it fails Apple's Gatekeeper check, so FORM does not offer it there.

### Design
- **Variants**: an empty state that says what a variant is and holds the one action.
- **The part's companion** (the phone a dock holds) fades out above the part with a note, "Device · 147 mm tall · not printed", instead of running off the view.
- **Replies**: lists, numbers and nested points sit on the app's grid with hanging indents, instead of Qt's 40 px indent. Copy still copies the original Markdown.
- **Folds** open with a short fade and settle; reduced motion keeps only the fade.
- **Labels in the viewport** no longer sit on each other: a dimension moves along its line or steps aside for a marker.

- **Windows:** deleting a design now always detaches its conversations; a read that met a file being replaced used to fail silently.

### 11.0.3

### Used on Windows and Linux, by the test suite
- **The interface journeys now run on Windows and Linux in CI** (`.github/workflows/ui.yml`): the real window, real mouse and key events, and a real PrusaSlicer installed on the runner, so designs are built, sliced, simulated and released there. Until now only a Mac had done that. No person has used those builds by hand yet.
- **Windows: `form run` failed on any design whose checks contain "Δ"**, because the console is not UTF-8. The CLI now writes UTF-8 everywhere. Found by the first real slice on a Windows runner.
- **Windows: a pipeline could fail right after the solid was built.** Windows refuses to replace a file that anything else has open (the window reading `project.json`, an antivirus scan). Every file FORM replaces is now retried for a moment. Found by the Windows interface run.
- **Windows: a PrusaSlicer installed with Chocolatey is found.**
- **Linux: PrusaSlicer 2.4.0** (Ubuntu's package) slices through FORM; presets come from the bundles it ships.

### OrcaSlicer, every vendor
- **Sliced a 20 mm cube for 496 printers from all 71 vendors OrcaSlicer 2.5.1 ships: 471 slice.** The other 25 fail the same way with OrcaSlicer's own preset files (for example a start G-code outside the printable area), so they are OrcaSlicer's to fix.
- **The build plate is the one OrcaSlicer's window would use.** Its command line defaulted to the Cool Plate: a Prusa CORE One came out with a 35 °C bed instead of 60 °C.
- **A refused slice says why**, in OrcaSlicer's own words, instead of "exit code 154".
- **macOS: no hang after a slicer crash** (the "reopen windows?" dialog used to block every later run).
- **A preset you made in OrcaSlicer works**: layer height, infill and wall overrides were confirmed in the G-code on three printers.

### Design and motion pass
- All 62 screens were re-shot and reviewed at two window sizes. The pipeline strip and stage tabs no longer cut their text; sheets with a subtitle have a proper header; recipe descriptions, model notes and scene notes wrap instead of ending in "…"; reply cost and time are readable.
- Motion: new messages fade in; tabs, rail buttons, pipeline nodes, rows and folds answer hover and press; every duration is a theme token; reduced motion is honoured in three places that ignored it.
- **Renaming a design on Home is instant**, keeps what you typed if the list refreshes, and is not cancelled when you switch to another app.

Left as they are, and known: the Variants sheet's empty state, phone companion lines that can leave the viewport, and Markdown list indent in replies.

### 11.0.2

- **OrcaSlicer 2.5 slices through FORM.** OrcaSlicer 2.5 stopped shipping its printer, process and filament presets as JSON files; each vendor is now one packed file (`.opc`). FORM reads that format (written from OrcaSlicer's own source, format version 2; any other version is refused by name, not guessed) and hands the slicer the presets it needs. Run for real with OrcaSlicer 2.5.1: the phone dock on a Bambu Lab A1 mini 0.4 nozzle, 0.20mm Standard, Generic PLA: 1 h 45 min, 59.04 g, 177 layers; layers, print simulation and cost all read its G-code.
- **Presets pinned in `studio.toml` work on an OrcaSlicer that was never opened**: FORM falls back to the profiles inside the program.
- **"Current selection"** follows OrcaSlicer's per-printer process and filament, and the Slicer sheet says exactly what is missing when the selection is incomplete.
- Not verified: OrcaSlicer on Windows and Linux (profile paths are fixture-tested only; AppImage and Flatpak locations are not covered), vendors other than Bambu Lab (their packed files decode, none was sliced), and a real user-made preset.

### 11.0.1

Run against the real programs for the first time, and fixed what that showed.

- **Codex works in the app.** FORM passed Claude's default model name to Codex, which refused it. The default model and effort now belong to the default agent only. In a live run Codex called FORM's `get_project` tool and answered correctly. Codex notices are shown quietly instead of as errors.
- **PrusaSlicer 2.9.7:** a real slice of the phone dock ran through FORM, and the layers, print simulation and cost all read its G-code. Presets pinned in `studio.toml` now resolve from the bundles PrusaSlicer ships, so it does not have to be opened first.
- **FreeCAD 1.1.4:** the re-import check and the generated macro both ran. The check now uses FreeCAD's exact bounding box; the default one is padded on curved faces and made the check warn.
- **OrcaSlicer 2.5.1** is found and reported. It keeps its printer profiles packed until its own first-run setup is done, so FORM says so and waits.
- **Installer:** the parts libraries, OrcaSlicer, PrusaSlicer and FreeCAD were installed for real through `form install`.
- **Every build launches the packaged app** on macOS, Windows and Linux and requires the interface to load and the CAD kernel to start (`--check` now reports the kernel).
- **Windows:** conversation times always move forward, so "most recent" is right on a coarse clock.

### 11.0.0

### One app, zero terminal
- **First start is three steps** (FORM itself, your printer and slicer, your AI) and installs what FORM needs from inside the app. Every command is shown first and nothing runs until you press the button. Installs were tested with stand-in commands, not real installers.
- **No example projects.** A new projects folder starts empty. Examples are one click away ("Open an example", or `form examples add`).
- **Settings** (gear, Ctrl/⌘ ,) edits everything that used to need `studio.toml`, with a backup of the file.
- **Claude sign-in** status and a sign-in link in the app.

### Conversations
- **Saved conversations** per design and free-standing: switch, search, pin, rename, delete. They live in `<data>/.conversations`.
- **Agent, model and effort per conversation:** Claude Code and Codex (Gemini CLI when installed). Models come from the agent's own list; FORM does not invent ids. Codex and Gemini have not been run live yet.
- **Attachments:** images, PDFs, STEP/STL by drop or paperclip. Replies stream as they are written, with the agent's steps folded into a group and the views it looked at shown inline.

### See it
- **Watch it print:** the slicer's G-code played back in 3D with a nozzle marker, line-type filters, a per-layer chart and the slicer's own time. Simulated, not a print.
- **Analysis on the model:** wall thickness, overhang, layer cross-section and small-feature maps, computed from the real geometry. Each legend says what the map does not tell you.
- **Measure tool** (M): distance, face area and tilt, hole diameter (exact from the solid).
- **Find the best orientation,** with the numbers behind the ranking.

### Design tools
- **Revision timeline** you can scrub and play as a morph; export as GIF/WebP.
- **Variants** and a variants board.
- **Text, revision stamps and vent/grip patterns** for any design (`form.marks`, `form.patterns`).
- **Cost:** filament, electricity and machine time from the slice and your prices. FORM never guesses a price.
- **Copies on a plate:** does N fit?
- **Share card,** right-click quick actions, viewport keys (`?`).

### Redesign
- **Workspace:** one tool rail and options bar for the viewport, docked legends that never cover the part, one strip for the pipeline and the history, cross-faded rebuilds, a camera that keeps the part clear of panels, focal stage panels (Prove opens with a pass / review / fail scoreboard).
- **Shell:** a design system with motion tokens, one sheet system for all 13 sheets, a one-line top bar, a resizable conversation column, a new Home with filters, sort and right-click actions, a grouped fuzzy command palette, a native menu bar, About with licences, remembered window size. Reduced motion is respected (`FORM_REDUCED_MOTION`).
- **Housekeeping:** rename, duplicate, export and trash designs from Home (`form rename|duplicate|delete`).

### Tested by clicking
- **Nine UI journeys** drive the real window with synthetic mouse and keyboard events (`python -m form.app --uitest`, `tests/journeys`). They found and fixed, among others: Enter creating a project twice, Tab leaving a sheet, viewport keys typing into the chat box, toasts restarting each other, Esc not closing the context menu.
- **Update now:** the update sheet installs the upgrade from the app (`form update --install`); the terminal instruction is gone.

### Headless
- New commands: `form chat`, `conversations`, `install`, `config`, `examples`, `simulate`, `cost`, `pack`, `analyze`, `measure`, `orient`, `variants`, `share`, `history`, `mark`, `rename`, `duplicate`, `delete`, `update --install`.
- 44 MCP tools.

### Website
- https://kaizensx.github.io/form-studio/ (source in `site/`; the docs pages are generated from `docs/*.md`).

### 10.0.0

### Works with the tools you already have
- **Slicers:** OrcaSlicer and PrusaSlicer (and SuperSlicer, QIDISlicer) join Bambu Studio. `[slicer].kind = "auto"` uses the first one installed; the Slicer sheet switches between them. Only Bambu Studio was run for real on the release machine; the others are tested against fixtures written from their source.
- **Import a real part:** bring in a STEP or STL (a board, a device, a motor). It is drawn in blueprint around your design, and a design can cut clearance from it with `self.reference("pi5.step")`.
- **OpenSCAD designs:** `create_design(..., language="openscad")`. Customizer range comments become FORM parameters. Mesh designs say clearly which checks and exports do not apply.
- **FreeCAD:** open the STEP in FreeCAD, an optional re-import check when FreeCAD is installed, and a `.FCMacro` with every parameter in a spreadsheet. Not run against a real FreeCAD yet.
- **Blender:** illustrative renders of the current revision (studio, desk, dark; matte PLA, PETG, silk), cached like every other artifact. Blender's 3D-Print Toolbox checks run when the add-on is installed.

### Designs with real hardware
- **`form.parts`:** screw clearances (ISO 273), heat-set insert pockets, nut traps, magnet pockets, bearing seats, printable threads and spur gears, each with its dimensions and their source.
- **New recipes:** electronics enclosure, gear pair, control knob, hinged box.

### Assemblies
- **Assembled / Exploded / Print layout** in the viewport, with hinge and slide joints you can move.
- **Checks from the solids:** overlap when assembled, the smallest gap, each joint swept at sampled positions, and screwdriver access. The check text says that sampled motion does not prove the motion is free between samples.
- **Maker documents on release:** `BOM.csv`, `ASSEMBLY.md` (an exploded image per step), `PRINT_REPORT.md`, `MEASUREMENT_PLAN.md`, `MOTION_CHECKS.csv`.

### The app sets itself up
- **First-run welcome:** what FORM found on this computer, and what it can set up. Nothing is installed until you tick it and press Apply, and every command is shown first.
- **Update notices:** FORM checks GitHub's latest release at most once a day and tells you when one exists. It never downloads or installs anything itself. Turn it off with `[updates] check = false`.

### Expertise
- **Claude Code plugin:** 13 skills (intake, parametric design, FDM engineering, fit calibration, hardware, assemblies, industrial design, design review, release and more) plus the MCP server, in `plugins/form`.
- **Start from a brief:** six brief templates (remote holder, desk accessory, organizer, bathroom mount, enclosure, car accessory) with the questions worth answering; your answers go to Claude.
- **Design review on demand** from the Release stage.

### 9.0.0

### A desktop app
- **FORM is now a native app** for macOS, Windows and Linux (`form app`, or the downloadable bundle). It is built with Qt Quick and runs in one process with the CAD engine. No browser, no web view.
- **Native 3D viewport:** the kernel's meshes and edges, feature picking, section cuts with solid cut faces, and overall dimensions drawn as dimension lines.
- **Home** shows every design as a live 3D card. **Claude** has its own column. A **command palette** (Ctrl/⌘ K) reaches every action and design.
- **All five stages** are in the app: Brief (with photo measuring), Shape, Fit, Prove (with the slice layer viewer) and Release.
- **Installers for every platform** are built by the *Desktop app* workflow. They are not signed or notarized yet.

### Engine
- Project locks now also work across processes on Windows.
- `form serve` no longer prints a traceback when FORM is already running.

### 8.0.0

### Design anything
- **Designs as code:** agents write designs (`design_guide`, `create_design`, `update_design`, `get_design_source`) that get the full pipeline. Every revision keeps its exact code.
- **Multi-part designs:** `solids = N`, so a base and lid print on one plate.
- **`read_document`:** renders datasheet and mechanical-drawing PDFs as images, so agents read real dimensions.
- **Declared provenance:** a design can mark a value `Param(..., provenance="specified")`.

### The page
- **Chat with Claude in the page.** It runs on your Claude Code account, with FORM tools and web lookup, and streams what Claude is writing.
- **The page follows any agent live:** it opens projects, shows drafts and views, and refreshes on commits.
- **It opens by itself** the first time an agent starts working.

### Fixes
- The `form-mcp` path broke when it contained spaces.
- Setup fixes no longer inherit the terminal.
- Registration is detected from config files.
- The installer always fetches the latest version.

### 7.0.0

### Installation
- **One-line installer** (`install.sh`). It installs uv if missing (after asking), installs FORM with its own Python 3.12, then runs `form setup`.
- **`form setup`** reports the kernel, project folder, slicer, printer size, and Claude Code, Codex, Gemini CLI, Cursor and Claude Desktop. You choose what to fix. Each fix shows its command, config files are backed up, and the result is verified afterwards. `--check`, `--yes` and `--dry-run` are available. The same report is available to agents as the `setup_status` tool.

### New recipes
- **`gridfinity`:** Gridfinity-style bin with magnet pockets, dividers, scoop, label shelf and a stacking lip truncated to two perimeters.
- **`hook`:** wall hook with a bending-stress model, screw pull-out estimate and screwdriver clearance.
- **`planter`:** twisted polygon planter with a drain-plug fit.

### New tools
- **Goal seek** (`optimize`): minimise or maximise any metric under constraints, with every candidate built by the kernel.
- **Motion** (`animate`): turntables and parameter morphs as GIF or WebP, from real builds.

### Fixes
- Recipe-specific model checks via `statics()["checks"]`, and a fit window per recipe.
- Change impact and alternatives no longer assume the dock's tip-over model.
- The renderer wraps long legends and supports fixed framing and free cameras.
- The repository's media, gallery, social card and animated session replay are all generated from real builds (`scripts/make_media.py`).
- Added CI workflow, issue and PR templates, `CONTRIBUTING.md`, `SECURITY.md` and [docs/RECIPES.md](RECIPES.md).

### 6.0.0

- **MCP server:** stdio MCP server, JSON CLI, headless renders, cross-process project locks, `expect_head`, and agent-attributed revisions.
- **Bench:** deep links, and the bench follows agent edits live.
- **Slicer:** slicer adapter interface; slicer logs strip the home path.
- **Packaging:** installable package with first-run examples. The built-in model call is now off by default.

### 5.0.0

- **Single-user studio:** one CAD authority, a hashed artifact graph, fit under uncertainty, real slicing and a release gate.
