# Niche sweep: every AI CAD app, and what it takes to be the best

Date: 2026-11-28. Branch `dev`, version 1.2.0-dev. Status: research only; no product code changed.

This page extends [the parity plan of 2026-11-27](../plans/2026-11-27-beyond-studio.md) from one competitor to the
whole field. It records what each app does today, deduplicates the features into one inventory graded against Form
Studio, names what nobody does well, collects the visual and interaction patterns from the most polished apps, and
proposes additions to the wave plan.

- [Method and evidence](#method-and-evidence)
- [text-to-cad Studio in depth](#text-to-cad-studio-in-depth)
- [The rest of the niche](#the-rest-of-the-niche)
- [Master feature inventory](#master-feature-inventory)
- [What nobody does well](#what-nobody-does-well)
- [Visual and interaction patterns to adopt](#visual-and-interaction-patterns-to-adopt)
- [Additions to the wave plan](#additions-to-the-wave-plan)
- [Summary lists](#summary-lists)
- [Sources](#sources)

## Method and evidence

- Public pages only, read on 2026-11-27 and 2026-11-28 with a scraper, a browser and the GitHub API. No account was
  created, nothing was installed and no private data was sent anywhere.
- The text-to-cad Studio site was saved and read as HTML; its 12 clips were described from their captions,
  accessibility text and poster frames, not played frame by frame. Their repo was read with `gh api` at commit
  `8c0c60e` (2026-11-27).
- Form Studio grades come from `docs/FEATURES.md`, `docs/APP.md`, the parity plan and a search of `form/`.
- Evidence labels: **[V]** read on the cited page; **[S]** seen only in a search excerpt or a third-party summary;
  **[I]** inference. Vendor comparison pages (Leo AI, MecAgent, BuildCAD, QuantCAD) are biased about their rivals.
- Grades for Form Studio: **better**, **equal**, **partial**, **missing**.

## text-to-cad Studio in depth

### Facts that update the 2026-11-27 plan

| Fact | Value | Evidence |
|---|---|---|
| Latest build | v0.1.18, 2026-11-23, carrying text-to-cad 0.11.16; a release about every three days | `amywork777/studio-download` releases [V] |
| Download | DMG 611 MB, Windows installer 515 MB; "about 5 GB free" is disk after unpacking | releases, site download section [V] |
| Platforms | Mac on Apple silicon only; Windows 10 and 11 unsigned, needs Git for Windows, about 20,000 files under `%LOCALAPPDATA%` | site, `STUDIO.md` [V] |
| Agents | Claude Code or Codex subscription, or an **invite code** that routes a friend's Codex through a proxy on the maintainer's own OpenAI key (the proxy is not in the repo) | `CodexInviteCode.tsx`, `codexInvite.ts`, FAQ [V] |
| Toolbox | The headline says 32; the site's lists add up to 30 (Design 2, Check 11, Make 7, Document 12) | site text [V] |
| Repo | MIT, TypeScript, 49 stars; built on T3 Code (Electron), merged weekly from upstream; text-to-cad as a submodule merged every 6 hours | GitHub [V] |
| text-to-cad | MIT, 27,621 stars, `cad` 0.11.18 on PyPI, build123d on OCP, eight skills | GitHub [V] |
| Telemetry | On by default after a notice; `DO_NOT_TRACK=1` honoured | `StudioAnalytics.ts` [V] |
| Website | One page; `/docs`, `/pricing`, `/changelog`, `/blog` and `/privacy` return 404 | site [V] |

### The twelve clips

| | Clip | What it shows |
|---|---|---|
| A | From a brief to a model | A PRD and a datasheet attached; one question; the part built feature by feature; the chat shows "Updated 1 file, took 17 steps" and fetched pages; a "Sped up 2x" badge |
| B | Draw it in the chat | A modal sketch: select, line, rectangle, circle, arrow, dimension, text on a grid; "only the numbers you type are sizes"; a note in words |
| C | Point and ask | A markup bar (pen, highlighter, eraser, colour, stroke) over the model; a circle on a bend plus "add a gusset here"; the agent states what it assumed |
| D | Edit a feature | Double-click Cut-Extrude1, drag the depth with a live preview, type 4.5 mm, rebuild |
| E | Change a sketch | Edit Sketch with relations and dimensions; change one size; dependants follow |
| F | Step back in time | A rollback bar dragged up and down the feature tree |
| G | Every version saved | Versions list; What changed: one model, side by side, script, open in 3D; added material in green; "dimensions that changed"; volume and size deltas; Restore |
| H | Mold check | Area without draft and undercut share; adds draft; reruns the 10 N stress study |
| I | Strength | "Too weak", a hand edit to an equation, "Strong enough"; MPa against a limit |
| J | Drawings | Views, dimensions, title block, then PMI on the model; a job card "Worked for 1m 17s" with a caveat paragraph and a references list |
| K | Fit and motion | Open pose, fit report at the stop, range of motion to an unrounded 80.757546° |
| L | Projects | Home with Start box, project tiles with 3D thumbnails, stars and "Opened 4m ago"; Find anything across projects; project Overview with decisions, README and files by kind |

### Small UX details worth knowing

- **Tool runs in the chat.** While working, one line in engineering words joined by arrows ("Reading the script →
  Rebuilding the head"); after 20 minutes with nothing new it says so. Done turns fold to "Worked for 4m 51s ›" with
  step rows. Under the reply: a what-changed card (parts and documents with size changes, opens Versions at that
  turn), changed-file chips and a **References** block that numbers claims [1] and records whether each source was
  opened this turn, earlier, not opened, or is the model's own knowledge.
- **A context strip** above the composer names what the viewer shows: part, kind, units, material, last build.
- **Interface modes.** Engineering (default) hides git, terminal and diffs and names files as parts; "Engineering
  with code" and "Code" bring them back.
- **Hand edits reach the agent.** Each hand edit queues a hidden "Hand edit" note sent with the next message.
- **Who made what.** Dots in the feature tree: purple for the agent, grey for the person (`authors.jsonl`).
- **Edit on the model.** Double-click a dimension on the part to change it; a value built from several sizes asks
  which to change; a file changed since it was read is refused.
- **Feature tree and ribbon** copy SolidWorks wording (FeatureManager, Hole Wizard, Boss-Extrude) and a four-tab
  ribbon (Features, Sketch, Evaluate, Drawing). A heads-up strip on the viewer: select, markup, measure, explode,
  section, view cube, play.
- **Tabs** like a browser: Overview pinned, then mixed documents (a joint report, an FEA, a CAM job, a drawing);
  Ctrl+Tab and ⌘1–9.
- **Toolbox popup.** Searchable by name, output, menu and tab; starred jobs lead their tab; the last tab is
  remembered; each row expands to an example result, inputs, outputs, needs and **the exact prompt Run sends**; jobs
  that do not fit the open file are dimmed, not hidden; a tile names its setup need ("Needs OrcaSlicer installed").
  Run sends a chat prompt.
- **Brainstorm cards.** Four concepts with render, mass, material and a rationale; "Use this" and "More like this";
  the lightest tagged; "not in the project until you use one".
- **CAM panel.** "Ready to cut · 5 min · 4 tools · 3 warnings", colour-coded operations, a tool table, toggles for
  toolpaths, rapids, tool, stock and part; "not proven on a machine. Air-cut first".
- **Projects.** A sidebar of projects with their chats nested; "Needs you" first; ⌘K finds projects, parts,
  documents, chats and jobs; Trash never deletes on disk; document templates (PRD, requirements, FMEA, design review).
- **Onboarding.** First screen installs Claude Code and signs in, with an invite-code row; empty Home offers three
  parts to try; a five-step tour that waits until the chat is quiet; the first turn names the project, writes a
  README, makes a first draft with its assumptions and asks at most one question, recommended answer first.
- **Sync.** A private GitHub repo the server creates, or a copy-only folder (Drive, Dropbox, iCloud); restore on
  another computer. **Conversations are not backed up.**
- **Model picker.** None in the engineering composer; a model is applied from Settings to the chat in front.

### Weaknesses observed

Apple silicon only; unsigned Windows build needing Git; 5 GB on disk; a subscription or a shared proxy key; linear
static strength only; drawings need review; CAM needs the person's FreeCAD and is unverified; imported parts lose
their history; unrounded numbers in reports; tab names drift between clips and site; one maintainer against an
upstream that moves more than a thousand commits a week; SolidWorks trade wording as the interface's identity [I].

## The rest of the niche

### AI text-to-CAD and agent apps

| App | What it does | Standout | Pattern to beat | Price, openness | Weakness |
|---|---|---|---|---|---|
| **Zoo Design Studio** with Zookeeper | KCL code, point-and-click, tree and prompt kept one to one | Code pane mirrors the tree; agent can snapshot and debug geometry; reasoning modes | The one-to-one code ⇄ tree ⇄ viewport loop | App MIT (Electron); **engine closed and cloud-only** (the viewport is a video stream); Free 20 min/mo, Plus $20, Pro $99 [V] | No offline, single parts, no assemblies; sketches in functions not editable by hand [V] |
| **Adam** | Agent that drives the person's CAD (Onshape, Fusion, SolidWorks, NX, CATIA) and PLM/CAE | Onshape extension using the current selection; "review each change in the feature list"; drawings, DFM, FEA loop | Selection-aware edits with per-change review | Closed; Free, Pro, Max, Team; MCP [V] | Needs a professional CAD licence [I] |
| **CADAM** | Open-source text and image to OpenSCAD in the browser | Parameters extracted into sliders | Slider extraction | GPL-3.0, 5.5k stars [V] | Mesh only, no STEP, no fillets [V] |
| **Backflip AI** | Scan, mesh, drawing or photo to a parametric feature tree | **Fast mode: four alternative constructions**; Thinking mode one refined result; Fusion add-in | Alternatives to choose from | Closed, credits, about $1.52–$10 per job [V] | No published accuracy; misses notches and thin walls [V] |
| **Leo AI** | Engineering copilot over CAD and PLM | Cited answers; part reuse search | Answers with sources | Enterprise sales only [V] | Not self-serve; SolidWorks-centred [I] |
| **Navier Prism** (new, 2026-11-03) | Native desktop (Mac, Windows, Linux) where agents build on OCCT and run OpenFOAM, CalculiX, code_aster, SU2, Elmer, Chrono | A Solver Desk tracking runs; plan before acting; diff of files touched | **Closest architectural rival**: native, OCCT, agents; simulation-first | "Free to try" [V] | Not creation-first [I] |
| **QuantCAD** (new) | Web text to OCCT B-rep parts and assemblies | STEP AP242; revision history; Ask mode | Assemblies from text | Closed, Pro $29/mo [S] | Web only [I] |
| **BuildCAD AI** (new) | Web text, photo or sketch to STEP, STL, 3MF with sliders | Shows build steps; free MCP connector | Unlimited slider edits | Closed, Maker $12/mo [V] | Web only [I] |
| **MecAgent** | Copilot inside SolidWorks | Free plan | Selection-aware commands | Closed [V] | Windows and SolidWorks only [I] |
| **text-to-cad** skills | build123d skills for 24 agent apps, local web viewer | Biggest open mindshare on our stack (27.6k stars) | Skills that work in any agent | MIT [V] | A toolkit, not an app [I] |
| **build123d-mcp** | MCP server: execute, render_view, measure, export, diff_step | Live viewer socket | Minimal tool surface | Apache-2.0, 167 stars [V] | No app, no checks [I] |
| **Research** | Parametric CAD Bench v3 (arXiv 2611.02659): 100 tasks, checked by a separate verifier; best system Claude Code with Opus 5.5 at 61.03 % | "An executable script is not sufficient" | **A public benchmark to win** | Open [V] | |

### Incumbent CAD with AI

| App | AI today | Pattern to adopt | Price | Weakness |
|---|---|---|---|---|
| **Onshape** | AI Advisor answers from docs with links; FeatureScript MCP (Labs, 2026-08) writes reusable custom features; AI search by generated thumbnail descriptions ("red bracket"); Replicate Annotations; agents as revocable teammates (proof of concept) [V] | Agent as a permissioned teammate whose every action is logged and reversible; AI writes code that becomes a feature | $1,500–2,500/user/yr [V] | Browser; AI mostly docs and code [V] |
| **Autodesk Fusion** | Autodesk Assistant: text commands on the selection ("0.5 mm chamfer on all edges"), saved multi-step prompts, confirm before apply, CAM help; AutoConstrain; Automated Drawings; Fusion MCP on `127.0.0.1:27182` ("not reliable yet" on assemblies); Neural CAD announced (text or sketch to B-rep with its command history), no date [V] | Selection-scoped commands; saved prompts; confirm card | ~$680/yr; restricted personal tier [V] | Most AI in preview; cloud [V] |
| **SOLIDWORKS / 3DEXPERIENCE** | AURA (docs chat), MARIE (materials), LEO (feature trees, exploded views, drawings to company standard, B-rep to parametric, release checks); Command Predictor; "What's Wrong" with fixes [V] | Diagnosis with a fix; next-command prediction | Heavy licensing [I] | Windows only; AI split across personas [V] |
| **Shapr3D** | AI renders in Visualization (metered); 26.220 adds mesh to editable solid, curvature analysis, "Recently Deleted" for 30 days [V] | Native feel, context menu at the selection, X-ray, 30-day recovery | Solo $199.99/yr [V] | Price; young history model [V/I] |
| **Plasticity** | No AI; 26.2 adds constraints drawn in the viewport, curvature shader, tintable matcaps, mesh snaps, gizmo feedback [V] | **The interaction bar**: gizmo plus numeric field, in-command modifier keys, Ctrl to compare before and after, palette for the long tail | Perpetual, $175 / $299 [V] | No drawings or engineering [I] |
| **FreeCAD 1.1** | AI only as add-ons: FreeCAD AI (39 tools, code review before run, skills, MCP), several MCP bridges [V] | Transparent previews, fillet draggers, 3-point lighting, Clarify Selection, status-bar hints [V] | LGPL, free | Dated, inconsistent UI [I] |
| **CQ-editor, OCP CAD Viewer, YACV** | Code beside a live viewport; measure, tree, clipping, explode, animation [V] | Click a face to its code; hot reload | Apache / MIT | Utilitarian [I] |
| **Tinkercad** | Codeblocks Shapes (parametric blocks); no first-party AI [V] | No modes; solid/hole as a property; starter activities | Free | Toy scale [I] |

### Generators, design tools and the print ecosystem

| App | What it does | Pattern to beat | Price, openness | Weakness |
|---|---|---|---|---|
| **Meshy 7.1** | Image or text to PBR mesh; remesh, rig, split; 3MF with AMS colours mapped; one click to Bambu Studio, Orca, Creality, Elegoo [V] | **Cost and time shown before generating**; slicer hand-off with colours | Credits, Pro $20 [V] | Mesh only; "97 % slice cleanly" is figurines [V/I] |
| **Tripo 3.1 / Studio** | Segment parts, complete hidden geometry per part, retopology, magic-brush texture, auto-rig [V] | **Segment → complete → retopologise per part** | Credits, Pro $20 [V] | Parts are mesh islands, no fits [I] |
| **Hunyuan3D 3.x** | Open weights (2.1 public) and a hosted engine [V] | | Community licence with regional limits (unverified) [I] | Licence not OSI [I] |
| **TRELLIS.2** | Open 4B image-to-3D, PBR, 1536³ [V] | Bundleable | **MIT code and weights** [V] | Needs CUDA [I] |
| **Rodin Gen-2.5** | Props and hard-surface meshes; bbox, voxel or point-cloud guidance [V] | Guided generation | $30–120 [V] | Weak on thin parts [V] |
| **Sloyd** | Parametric generators plus AI, sliders | Flat unlimited price | $15/mo [V] | Mesh [I] |
| **Womp** | Browser SDF "liquid 3D" modelling, AI meshes, print ordering in the app [V] | Beginner-friendly blending | Pro $9.99 [V] | No B-rep, no STEP [I] |
| **Vizcom** | Sketch to render and 3D for industrial designers [V] | **Sketch-to-render speed** | $49/user/mo [V] | Ideation only [I] |
| **Spline** | Web 3D scenes with AI credits [V] | | $12–25 [V] | Not CAD [I] |
| **MakerWorld MakerLab** | Image to 3D (Meshy or Tripo), keychains, reliefs, lithophanes, Bento trays, PrintMon; **Parametric Model Maker** (OpenSCAD variables as sliders, server-side, STL out); 2M+ users [V] | **Single-purpose, print-ready generators** | Free | STL only, no source for the user [I] |
| **Bambu / Orca / Creality** | Camera and probe failure detection during printing; auto-orient; CubeMe photo figurines [V] | | | Checks happen during the print, not the design [I] |
| **Printables, Thingiverse** | OpenSCAD Customizer models [V] | | | |

## Master feature inventory

Deduplicated across every app above. "Who leads" names the strongest current implementation outside Form Studio.
Rows already graded in the parity plan are not repeated in detail; their row numbers there are given as `P#`.

### Starting a design

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Words to editable B-rep | Zoo, QuantCAD, text-to-cad Studio | better | Brief as a contract with a proof sheet (P1) |
| Attach a spec, PRD or datasheet and get questions | Studio clip A | better | Triage of any input; at most three questions |
| Sketch in the chat with typed sizes | Studio clip B | better | Structured geometry in mm (P2) |
| Photo to sized model | BuildCAD, Backflip | equal | Scale from a reference object; sizes labelled estimated |
| Image or text to a generated mesh | Meshy, Tripo, TRELLIS.2 | **missing** | No generative mesh engine |
| Scan or mesh to parametric CAD | Backflip | better | Measured deviation 0.001–0.012 mm on the bench; Backflip publishes none |
| Several alternative constructions to choose from | Backflip Fast mode | partial | Recon races routes internally; concepts and `build_candidates` exist; recon alternatives are not shown to the person |
| Concepts with mass and material | Studio Brainstorm | partial | Size and volume only (P12) |
| Single-purpose generators (keychain, relief, tray, sign) | MakerLab | partial | Recipes and lithophane-like helpers exist; no gallery of one-click generators |
| Starter parts and a first-run tour | Studio, Tinkercad | partial | A turning example on Home; no tour, no "try these three" |

### Working with the agent

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Bring your own agent or model | Studio (2 agents) | better | Seven agent apps, eight APIs, local models, any provider |
| Model picker in the composer | Form Studio | better | Studio has none in its engineering composer |
| Tool runs folded into steps, time and cost per reply | Studio | equal | Studio adds a live one-line "working" status in engineering words |
| What-changed card per turn, opening the version | Studio | equal | Revision card with values from → to, Compare, Go back |
| **References block: which sources were opened vs own knowledge** | Studio, Leo, Onshape Advisor | **missing** | Biggest single trust gap in the chat |
| Hand edits reported to the agent | Studio | partial | Revisions record origin; no explicit "you changed X since my last turn" note |
| Who made each feature (agent or person) | Studio | partial | Origin per revision, not per feature in the Program |
| Confirm before apply, with impact | Fusion Assistant | better | Drafts with computed impact; commit or discard |
| Text commands on the selection ("chamfer these 0.5 mm") | Fusion, Adam | partial | Annotate sends a selection with numbers; no direct command line bound to it |
| Saved multi-step prompts as commands | Fusion | missing | |
| Plan before acting, shown | Navier Prism | partial | `plan_design` exists; the plan is not a card the person approves |
| "What's wrong" with a one-click fix | SOLIDWORKS | better | Fix with your agent on every failure; refine lands as named, undoable features |
| Next-command prediction | SOLIDWORKS | partial | Suggested replies and next best actions |
| Agent as a permissioned teammate, every action reversible | Onshape (proof of concept) | better | Revisions never overwritten; release only by a person |
| Interface without code by default | Studio Engineering mode | equal | No code surface shown unless asked |
| Code ⇄ tree ⇄ viewport one to one | Zoo | partial | Source exists (`get_design_source`, features as methods); no source pane in the app |
| MCP for outside agents | Zoo, Fusion, Adam, BuildCAD | better | 97 tools, headless parity, live follow |

### Modelling by hand

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Feature tree with rollback, suppress, reorder | Onshape, SOLIDWORKS, Studio | partial | Wave B1 (P4, P7) |
| Fillet, chamfer, hole wizard, pattern, shell by picking | Fusion, Shapr3D, Studio ribbon | partial | Wave B2 (P5) |
| Sketch on a face with constraints | everyone | partial | Solver exists; wave B3 (P6) |
| Inferred constraints drawn as glyphs | Fusion AutoConstrain, Plasticity 26.2 | missing | Add to B3 |
| Drag a face to change its parameter | Form Studio | better | ⌘-drag finds the parameter that moves the face |
| Double-click a dimension on the model to edit it | Studio | partial | Dimension lines are drawn; editing is by slider or face drag |
| Gizmo plus numeric field, modifier keys in the command | Plasticity | missing | |
| Draggers on fillet and chamfer edges | FreeCAD 1.1 | missing | Add to B2 |
| Before/after toggle while a command runs | Plasticity (hold Ctrl) | partial | Drafts preview; no hold-to-compare |
| Primitives and a no-mode beginner path | Tinkercad, Shapr3D | partial | Start blank exists; no primitive drop |
| Drag reusable parts from an assets drawer | Plasticity Assets | partial | `form.parts` by tool; no drawer (wave G) |
| Sculpted and organic forms as exact NURBS | Plasticity, Womp (SDF) | better | Sculpted bodies as NURBS, SubD cages |

### Viewport and looking

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Studio look by default | Plasticity, Shapr3D | better | Pool of light, dithered glass, studio floor |
| Matcaps and shading presets | Plasticity | missing | |
| Curvature and zebra maps | Plasticity, Shapr3D | partial | Curvature is computed in Annotate and critique; no map or zebra stripes |
| Draft map | Studio (mold check) | missing | Wave E |
| Crisp silhouette and feature edges, tintable | Plasticity | partial | Edges drawn; not tunable |
| X-ray | Shapr3D | missing | |
| View cube | Studio, FreeCAD, Fusion | partial | Views by keys and buttons, no cube |
| Clarify selection among overlapping picks | FreeCAD 1.1 | missing | |
| Snap highlight of the target | Plasticity | partial | Measure snaps; no highlighted target |
| Section with filled faces | everyone | equal | |
| Exploded view | Studio, OCP viewer | equal | |
| Measure with exact diameters | OCP viewer, Studio | better | |

### Checks and analysis

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Requirements proved on the solid | Parametric CAD Bench (as a method) | better | Proof sheet: PASS, FAIL, UNPROVEN per requirement |
| Strength (FEA) | Studio (CalculiX), Prism (many solvers), Adam (Ansys) | partial | Wave D (P14) |
| CFD, thermal, multiphysics | Navier Prism | missing | Out of scope until D lands; see wave D2 below |
| Moulding, CNC, sheet, powder | Studio | partial / missing | Waves E, H (P19–P22) |
| Fit, clearance, range of motion | Studio | better | (P16, P17) |
| Mass, centre of mass, inertia | Studio | partial | Wave C (P18) |
| Printability with reasons before slicing | nobody | better | Thickness, overhang, orientation, nozzle checks, fit model |
| Check against a drawing | Studio | partial | Wave F (P15) |
| Release standard check | SOLIDWORKS LEO | better | Release gate with hashes and a person's approval |

### Making and documenting

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Slicing on every printer | Form Studio | better | Seven slicers (P25) |
| One-click to slicer with colours mapped | Meshy | equal | 3MF with colours; Open in slicer |
| Drawings, PMI, CAM, flat patterns, board files, robot files | Studio | missing | Waves F, J, H, K, I (P24–P31, P40, P41) |
| Renders and turntables | Vizcom (speed), Studio (Blender) | equal | Blender scenes; no instant sketch-to-render |
| AI render from a prompt | Onshape Quick Render, Shapr3D | missing | |
| Assembly instructions, BOM | Studio | equal | (P32, P33) |
| Print ordering in the app | Womp | missing | Deliberately not done: no uploads |

### Projects and data

| Feature | Who leads | Form Studio | Note |
|---|---|---|---|
| Versions with a solid diff | Studio, Onshape | better | Boolean diff on the B-rep (P8) |
| Branches and variants | Onshape | better | |
| Project Overview: decisions, README, open questions, files by kind | Studio | missing | Home and the design header only |
| Document templates (PRD, requirements, FMEA, design review) | Studio | missing | |
| Search across designs, parts, documents, chats and jobs | Studio ⌘K | partial | Palette finds actions and designs; conversations search separately |
| Search your library by what a part is ("red bracket") | Onshape Labs | missing | |
| "Needs you" ordering | Studio | partial | Concepts waiting for a pick show first |
| Trash with recovery | Shapr3D (30 days), Studio | equal | Trash never deletes; no stated retention |
| Backup to a folder or a private Git repo | Studio | partial | One-file export; wave L adds scheduled backups. Studio leaves chats out; Form Studio's file includes them |
| No telemetry | Form Studio | better | Studio, text-to-cad and Zoo collect usage |
| Offline and local kernel | Form Studio, Prism | better | Zoo needs the cloud |
| Install size | Form Studio | better | About 0.8 GB against 5 GB |
| Platforms | Form Studio, Prism | better | Mac Intel and Apple silicon, Windows, Linux |

**Count over the 79 inventory rows:** better 25, equal 10, partial 27, missing 17 (the row marked
"partial / missing" counted as partial). Most new gaps are in agent trust (references), viewport craft (matcaps,
zebra, X-ray, gizmos) and project knowledge (overview, templates, semantic search); none of them is large.

## What nobody does well

1. **Generation that ends in editable, measured CAD.** Every mesh generator ends in a mesh; every text-to-CAD tool
   ends in an unmeasured script. Nobody generates a shape, rebuilds it as features and states its deviation.
2. **A chat that proves its claims.** Studio lists references; nobody ties each number in a reply to how it is known
   (measured, specified, computed, simulated, assumed) and each requirement to a check.
3. **Alternatives that are real.** Backflip offers four constructions, Studio four concepts, but nobody compares
   alternatives on the same computed scorecard (mass, deviation, checks passed, editability, cost to make).
4. **Hand edits and agent edits in one source.** Studio keeps a tree and a script in step and tells the agent about
   hand edits; Zoo mirrors code and tree but only in the cloud. Nobody local does it with one source.
5. **Printability before slicing, with reasons.** Generators report "manifold"; printers detect failures during
   the print. Function checks before the slice are Form Studio's alone.
6. **A published, reproducible score.** Parametric CAD Bench v3 exists; no app publishes its own result on it.
7. **Native beauty with engineering depth.** Plasticity and Shapr3D are beautiful without engineering; SOLIDWORKS
   and Fusion are deep and dense; the open-source AI apps are MCP bridges on old interfaces or Electron shells.
8. **Privacy as a property.** Every commercial tool meters a cloud; Studio and Zoo collect usage. Local, offline,
   no telemetry and opt-in engines is unclaimed as a stated promise.

## Visual and interaction patterns to adopt

Each fits the Lightdesk direction (`docs/design/DIRECTION.md`): glass over the room, no ribbon, results on the part.

| # | Pattern | Source | Where in Form Studio |
|---|---|---|---|
| 1 | Matcap and studio shading presets, tintable; curvature and zebra as analysis maps | Plasticity 26.2 | Analyze tool, a shading chip by the views |
| 2 | Silhouette and feature edges in their own tunable colours | Plasticity | Viewport edge pass |
| 3 | Translucent ghost of every operation; hold a key to flip before and after | FreeCAD 1.1, Plasticity | Drafts |
| 4 | X-ray to see inside enclosures | Shapr3D | A key in the tool dock |
| 5 | Gizmo and numeric field together; Return or right-click commits | Plasticity | B2 and B3 tools |
| 6 | In-command modifier keys (X/Y/Z lock, Shift plane, V pivot) | Plasticity | Drag, move and pattern tools |
| 7 | Gizmo feedback: a rotation arc, summed repeated drags | Plasticity 26.2 | Gizmos |
| 8 | Draggers on fillet and chamfer edges | FreeCAD 1.1 | B2 |
| 9 | Clarify selection among overlapping picks; highlighted snap target | FreeCAD 1.1, Plasticity | Select, Measure, Annotate |
| 10 | Inferred constraints as glyphs, click for options | Fusion, Plasticity | B3 sketch |
| 11 | Context menu at the selection, not at the window edge | Shapr3D | Right-click quick actions, extended |
| 12 | Status line hints for the active tool ("Click a face; Shift adds") | FreeCAD 1.1 | Under the tool options |
| 13 | Scrubbable numbers: drag a label to change its value | Figma | Parameters, typed loads, every numeric field |
| 14 | Command palette as the canonical surface, single-key tools, `?` cheat sheet | Linear, Plasticity | Exists; add saved prompts and studies |
| 15 | Theme from three variables (base, accent, contrast) in a perceptual space; a high-contrast option for free | Linear | `Theme.qml` |
| 16 | Low-saturation chrome, high-contrast text and icons aligned on both axes | Linear | Every pane |
| 17 | One-line live status in the work's own words while the agent works | Studio | Conversation and the build pane |
| 18 | A references block under answers, with opened vs own knowledge | Studio | Conversation |
| 19 | Who-made-what marks in the Program (agent, person, refine) | Studio | Program listing |
| 20 | Dimmed, not hidden, actions that do not fit the open design, each with what it needs | Studio Toolbox | The Bench (wave A) |
| 21 | Show the exact prompt a one-click job sends | Studio Toolbox | Bench entries that use the agent |
| 22 | Cost and time shown before an expensive run | Meshy | Concepts, recon, studies, generation |
| 23 | A 30-day recently-deleted shelf | Shapr3D | Home › Trash |
| 24 | First-run: three parts to try, a short tour that waits for quiet, one question at most | Studio, Tinkercad | Home on the first day |
| 25 | Polishing seasons: fixed periods of nothing but polish, behind flags | Linear | Release rhythm (`docs/RELEASING.md`) |

## Additions to the wave plan

Sizes are agent-days for one agent, including tests, documentation, screenshots and the site, as in the plan.
New waves are lettered after L. Total added: 44 days.

| Wave | Outcome | Size | Closes |
|---|---|---|---|
| M | Viewport craft | 5 | Matcaps, zebra, curvature map, edges, X-ray, view cube, clarify selection, ghost compare |
| N | Direct manipulation | 4 | Gizmos with numeric fields, modifier keys, edge draggers, edit a dimension on the model, scrubbable numbers |
| O | A conversation that proves itself | 4 | References, live status, hand-edit notes, author marks, plan card, saved prompts, selection commands |
| P | Project knowledge | 4 | Overview, templates, search everything, search by description, recently deleted |
| Q | Generate, then make it CAD | 7 | Image or text to mesh (opt-in), segment, rebuild as features with deviation |
| R | Alternatives on one scorecard | 3 | Recon alternatives shown; concepts with mass, material, checks, editability |
| S | Makers' generators | 3 | One-click print-ready generators as recipes with sliders |
| T | First run | 2 | Three parts to try, a tour, first-turn README and assumptions |
| U | Source pane | 4 | Code ⇄ Program ⇄ viewport, one to one, local |
| V | Benchmarks in public | 3 | Parametric CAD Bench v3 and our own suites, scores on the site |
| W | Theme and polish season | 2 | Three-variable theme, high contrast, a fixed polish pass |
| D2 | Beyond linear strength | 3 (after D) | Thermal and modal on the same mesh; CFD stays out |

### Wave M. Viewport craft (5 days)

- Shading presets as a chip beside the views: Studio (today), Clay, Matcap (a few bundled, tintable), Technical
  (flat with crisp edges). Edge pass with silhouette and feature edges in theme colours, width by DPI.
- Analysis maps join Analyze: **zebra** (reflection lines), **curvature** (Gaussian, mean, max) from the B-rep face
  curvature already computed for critique, and the **draft** map that wave E needs, sharing one legend component.
- **X-ray** (`Z`): parts at low opacity with back edges, the selected part opaque.
- A small **view cube** in glass at the top right; click faces, edges and corners; drag orbits.
- **Clarify selection**: a click on overlapping candidates opens a tiny list at the pointer; the snap target of
  Measure is outlined.
- **Before/after**: hold Space during a draft to show the committed state.
- Accepted when every map has a legend that says what it does not tell, crops at 200 % are clean on dark and
  light, and the frame time stays under 8 ms on the audit's bracket on an M1.

### Wave N. Direct manipulation (4 days, after B2)

- One gizmo component for move, rotate and scale of sketch entities, pattern spacing and datum planes: handles plus a
  numeric field beside the pointer; Return commits, Esc cancels; X/Y/Z lock, Shift locks a plane; a rotation arc
  with the angle in mono.
- Draggers on picked fillet and chamfer edges (radius and distance), writing the same feature method as B2.
- **Edit a dimension on the model**: double-click a dimension line, type, Return; the parameter changes as a draft.
  A dimension derived from several parameters asks which one.
- **Scrubbable numbers** everywhere a number is typed: drag the label, Shift for fine, Alt for coarse.

### Wave O. A conversation that proves itself (4 days)

- **References under a reply.** Every claim that rests on a source is numbered; the block lists each source with
  how it was used: opened this turn (link, page, file), opened earlier, not opened, or model knowledge. Numbers in the
  reply that come from the design link to their evidence class (computed, measured, assumed). Built from the
  tool-call log, never from the model's say-so.
- **Live status line** while working, in the design's words, with the feature being built; a quiet note after a long
  silence.
- **Hand-edit notes**: edits made by hand since the agent's last turn are summarised into the next message ("You
  changed wall from 2.0 to 2.4 mm and added Fillet 2").
- **Author marks** in the Program: agent (by name), person, refine; hover for the revision.
- **Plan card**: `plan_design` posts its plan as a card with Approve, Edit and Skip for complex briefs.
- **Saved prompts**: any message can be saved as a command with a name; it appears in the palette and on the Bench.
- **Selection commands**: with a selection in Annotate, the composer prefix shows "On 4 edges:"; the request goes
  with the selection's references.

### Wave P. Project knowledge (4 days)

- **Overview** of a design: its brief and contract, decisions taken in its conversations (extracted with a source
  line each), open questions, files by kind (exports, studies, documents, references) and its family.
- **Templates**: requirements, PRD, FMEA, design review as Markdown documents tied to the design; the FMEA rows can
  point to checks and studies so a row says whether it is covered.
- **Search everything** in the palette: designs, features, parameters, conversations, studies, documents and files.
- **Search by description**: each design gets a short description written from its brief and renders; matching runs
  locally (text search first, local embeddings when a local model is set up). Nothing leaves the machine.
- **Recently deleted** with a 30-day retention shown in Home's trash.

### Wave Q. Generate, then make it CAD (7 days; owner decision 1)

- Engines, opt-in: TRELLIS.2 (MIT) locally where a CUDA GPU exists; hosted APIs (Meshy, Tripo, Hunyuan) only with
  the person's own key, each request saying what is sent and to whom, and the cost before it runs.
- Flow: image or words → mesh → **segment into parts** (`form/recon/segment.py`) → rebuild each part as features
  through the existing recon routes → a **deviation map** on the part and the proof sheet. The mesh stays a
  reference, never the design.
- For organic shapes: the sculpt route (exact NURBS) with its deviation stated.
- Accepted when a generated object comes back as an editable multi-part design whose deviation and editability are
  shown, on three fixtures.

### Wave R. Alternatives on one scorecard (3 days, after C)

- Recon shows its competing routes to the person as alternatives (like Backflip's four), each with deviation,
  editable share, feature count and build time; pick one or keep racing.
- Concept and candidate cards gain mass and material (wave C), checks passed and a "cost to make" line where a
  study exists; "Use this" and "More like this" keep their current meaning.

### Wave S. Makers' generators (3 days)

- A gallery of single-purpose recipes, print-ready and editable: name tag and keychain, lithophane and relief from a
  picture, drawer and Gridfinity-style trays, knobs, cable clips, signs. Each is a recipe with sliders and the full
  source, unlike MakerLab's STL-only output.
- Export any design's parameters as an OpenSCAD Customizer file where the design is expressible that way, labelled
  with what is lost; never uploaded.

### Wave T. First run (2 days)

- Home on the first day offers three parts to try (a bracket, an enclosure, a hinge) as real briefs.
- A five-step tour that waits until the agent is idle: the composer, the stages, the Program, the tool dock, the
  palette. Shown once; reopened from Help.
- The first turn of a new design writes a short README of the design, lists its assumptions and asks at most one
  question with the recommended answer first (already the agent rule; made visible as a card).

### Wave U. Source pane (4 days)

- A read-only pane by default (editable on request) showing the design's code, one method per feature; selecting a
  feature or a face scrolls to its method and highlights the lines; editing a value in code is a draft like a slider.
- Hidden in the default interface; on in Settings or from the palette. No code is shown to a person who did not ask.

### Wave V. Benchmarks in public (3 days)

- Run Parametric CAD Bench v3 through Form Studio's own tools with each supported agent; publish the score, the
  harness and the failures. Add the mesh bench and the strength suite (wave D) to the same page.
- Accepted when the run is reproducible from one command and the site shows the date, version and agent of every
  number.

### Wave W. Theme and polish season (2 days, then each release cycle)

- `Theme.qml` generated from base, accent and contrast in a perceptual colour space, with high contrast as a mode.
- One polish pass per release cycle with a checklist from this page's patterns; 200 % crops in the release notes.

### Changes to existing waves

| Wave | Add | Size |
|---|---|---|
| A (Bench) | Dimmed entries with what they need; the exact agent prompt shown for agent-run entries; stars to pin | +0.5 |
| B2 | Edge draggers come from N; selection-scoped text commands from O | 0 |
| B3 | Inferred constraints as glyphs on the sketch | +1 |
| D | Name Navier Prism as the strength benchmark to pass; publish the verification suite on the site (wave V) | 0 |
| E | "What's wrong" wording: each finding a sentence, a fix and a proof | 0 |
| F | Replicate annotations between views; drawings to a house standard (a stored style) | +1 |
| G | An assets drawer: drag a screw, insert or bearing onto a hole | +1 |
| I | A motion film export from the timeline | 0 (in I) |
| L | Optional backup to a private Git repo the person owns; conversations included | +1 |

### Order with the additions

1. A, then **O** and **M** beside B1 (trust and look are what a first-time visitor sees).
2. B2 with **N**; C; then **R** and **T**.
3. D; F; **P**; **V** as soon as D's suite exists.
4. E, G, H, then **Q** after the owner decides on hosted generators.
5. I, J, K, L, **S**, **U**; **W** each release cycle.

### Owner decisions needed

1. **Hosted mesh generators (wave Q).** Allow Meshy, Tripo or Hunyuan with the person's own key as opt-in, or local
   TRELLIS.2 only. Hunyuan's licence terms are to be read before any use.
2. **Source pane (wave U).** Read-only by default, or editable.
3. **Public benchmark (wave V).** Publish scores including failures, on the site and in the README.

## Summary lists

### Top 15 must-have additions

1. References under replies, with opened vs own knowledge and evidence classes (O).
2. Feature tree with rollback, suppress, reorder and rename (B1).
3. Fillet, chamfer, hole, pattern and shell by picking, with edge draggers (B2, N).
4. Sketch on a face with inferred constraints (B3).
5. Linear strength with stated error, then modal and buckling (D).
6. Drawings and PMI from the B-rep (F).
7. Mass, centre of mass and sourced materials on concept cards (C, R).
8. Moulding and CNC checks with draft map and fixes (E, M).
9. Matcap, zebra, curvature maps, X-ray and view cube (M).
10. Edit a dimension on the model, scrubbable numbers, gizmos with numeric fields (N).
11. Hand-edit notes to the agent and author marks in the Program (O).
12. Project overview, templates and search across everything (P).
13. The Bench with dimmed entries and visible prompts (A).
14. First run: three parts to try and a tour (T).
15. Scheduled backup, optionally to a private Git repo, conversations included (L).

### Top 10 unique differentiators

1. Generated shapes rebuilt as editable multi-part CAD with a measured deviation (Q on top of recon).
2. A chat whose every number carries its evidence class and every claim its source (O with provenance).
3. Requirements proved on the solid at every revision (the proof sheet), across strength, fit and drawings.
4. Alternatives compared on one computed scorecard: mass, deviation, checks passed, editability (R).
5. One source for hand and agent edits, local and offline, with a source pane one to one (B, U).
6. Strength with automatic convergence and named singularities, verified against published cases (D).
7. Printability before slicing with reasons, on seven real slicers (shipped).
8. A published, reproducible benchmark score (V).
9. Native on three platforms at 0.8 GB, no telemetry, engines opt-in (shipped; to be said on the site).
10. Plasticity-grade viewport and manipulation in an engineering app (M, N, W).

## Sources

text-to-cad Studio and text-to-cad
- https://texttocad.studio/ (site, clips, Toolbox, FAQ)
- https://github.com/amywork777/studio (README, `STUDIO.md`, `apps/web/src/components/workbench/`, `studio-job-skills/`)
- https://github.com/amywork777/studio-download/releases
- https://github.com/earthtojake/text-to-cad

AI CAD apps
- https://zoo.dev/design-studio, https://zoo.dev/zoo-pricing, https://zoo.dev/docs/developer-tools/mcp, https://github.com/KittyCAD/modeling-app
- https://adam.new/, https://adam.new/onshape, https://adam.new/pricing, https://github.com/Adam-CAD/CADAM
- https://www.backflip.ai/, https://www.engineering.com/backflips-back-is-the-mesh-to-cad-ai-real-this-time/
- https://www.getleo.ai/, https://www.getleo.ai/blog/zoo-text-to-cad-review
- https://www.navier.ai/blog/2026-11-03-introducing-prism
- https://quantcad.ai/, https://buildcad.ai/, https://buildcad.ai/guides/cad-mcp-servers, https://mecagent.com/blog/ai-cad-tools-2026
- https://github.com/pzfreo/build123d-mcp
- https://arxiv.org/abs/2611.02659 (Parametric CAD Bench v3), https://arxiv.org/abs/2605.18430, https://arxiv.org/abs/2505.06507, https://arxiv.org/abs/2507.09792

Incumbents and polish
- https://www.onshape.com/en/features/ai-advisor, https://www.ptc.com/en/news/2026/onshape-launches-featurescript-mcp-server, https://www.onshape.com/en/blog/ai-artificial-intelligence-cloud-native-cad-pdm-platform, https://www.onshape.com/en/pricing
- https://www.autodesk.com/products/fusion-360/blog/autodesk-assistant-ai/, https://www.autodesk.com/products/fusion-360/blog/introducing-the-fusion-mcp-opening-fusion-to-ai-powered-workflows/, https://www.engineering.com/autodesk-introduces-neural-cad-at-au-2025/, https://develop3d.com/ai/autodesk-charts-its-ai-future/
- https://blog.championxperience.com/solidworks-ai-announcements-3dexperience-world-2026/, https://trimech.com/whats-new-in-solidworks-ai-solidworks-2026-fd04/
- https://www.shapr3d.com/pricing, https://discourse.shapr3d.com/t/26-220-new-modeling-tools-expanded-import-support-and-workflow-improvements/42821
- https://www.plasticity.xyz/, https://doc.plasticity.xyz/whats-new, https://doc.plasticity.xyz/common/move
- https://blog.freecad.org/2026/03/25/freecad-version-1-1-released/, https://wiki.freecad.org/Release_notes_1.1, https://github.com/ghbalf/freecad-ai
- https://github.com/CadQuery/CQ-editor, https://pypi.org/project/ocp-vscode/, https://github.com/yeicor-3d/yet-another-cad-viewer
- https://www.tinkercad.com/codeblocks, https://www.tinkercad.com/blog/istelive26-whats-new
- https://linear.app/now/how-we-redesigned-the-linear-ui

Generators and print ecosystem
- https://www.meshy.ai/3d-printing, https://www.meshy.ai/tutorials/multicolor-3d-printing-with-meshy, https://docs.meshy.ai/en/webapp/pricing
- https://www.tripo3d.ai/blog/tripo-studio-tutorial-english, https://www.tripo3d.ai/pricing
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1, https://microsoft.github.io/TRELLIS.2/, https://github.com/microsoft/trellis.2
- https://voyager.so/blog/hyper3d-rodin-review, https://www.sloyd.ai/pricing, https://womp.com/pricing/, https://vizcom.com/blog/introducing-generative-3d-in-vizcom
- https://makerworld.com/en/makerlab, https://www.makerhacks.com/openscad-makerworld-customizer/, https://wiki.bambulab.com/en/h2/manual/intelligent-detection
- https://www.printables.com/tag/openscadcustomizer, https://wiki.creality.com/en/printers-general-documents/2d-image-into-3d-model
