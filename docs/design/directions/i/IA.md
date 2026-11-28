# Direction I: Lightdesk, one bench

Date: 2026-11-28. Status: **approved; being built on the branch `direction-i`.** What is built is listed in [Built so far](#built-so-far-branch-direction-i); the rest of this page is the proposal as it was drawn.

Direction I keeps Lightdesk (`docs/design/DIRECTION.md`): the room, the warm pool, glass panes, one cyan, Geist and
Geist Mono, the film-title cue, the conversation on the left, the pane on the right, the floating dock. It changes
where things live, so that the waves in `docs/plans/2026-11-27-beyond-studio.md` (A to L) and
`docs/research/2026-11-28-niche-sweep.md` (M to W) fit without a ribbon, a tab grid or a second window.

- [The idea in one paragraph](#the-idea-in-one-paragraph)
- [The map](#the-map)
- [Decisions, and why](#decisions-and-why)
- [Where each thing lives](#where-each-thing-lives)
- [How the eye travels](#how-the-eye-travels)
- [Screens](#screens)
- [Signature moments](#signature-moments)
- [Motion spec](#motion-spec)
- [What changed from Lightdesk](#what-changed-from-lightdesk)
- [What is real in the pictures](#what-is-real-in-the-pictures)
- [What was checked, and what was not](#what-was-checked-and-what-was-not)
- [Choices for the owner](#choices-for-the-owner)
- [How the pictures are made](#how-the-pictures-are-made)

## The idea in one paragraph

Everything the app can do to a design is one of four verbs: **Design** it, **Check** it, **Make** it, **Document**
it. Those are the four modes at the top of the window, and the four chapters of **the Bench**. The pane on the right
is always the Bench's chapter for the mode you are in, written in one row grammar: a state, a name, a number, and
the word that says how the number is known. Open the Bench (Ctrl/⌘ B) and the pane widens into all four chapters at
once. A result is never a new page: it appears on the part, and a legend under the part says how it is known and
what it does not tell.

## The map

```
┌─ design capsule ──────────┐      ┌─ modes ──────────────────────────┐      ┌─ app ───────────────┐
│ mark · name · rev · state │      │ Design   Check   Make   Document │      │ activity  ⌘K  ⌘B  ⚙ │
│ opens: Overview           │      │ one line of state under each     │      │ printer (Make only) │
└───────────────────────────┘      └──────────────────────────────────┘      └─────────────────────┘
┌─ conversation ─┐ ┌dock┐ ┌─ tool options ─────────┐        ┌cube┐ ┌─ pane: the Bench, docked ───┐
│ picker, New,   │ │ 4  │ └────────────────────────┘        │    │ │ Design   → the tree, with   │
│ Fold           │ │uni-│                                   └────┘ │            the rollback bar │
│                │ │ver-│            THE STAGE              shading│ Check    → studies          │
│ what was said: │ │sal │                                          │ Make     → routes           │
│ steps, plan,   │ │ ── │        the part, in the room             │ Document → documents        │
│ replies with   │ │mode│   dimensions, sketches, handles,         │ ─────────────────────────── │
│ sources,       │ │tools│  maps and markers are drawn on it       │ the selected row, opened:   │
│ revision cards,│ │    │                                          │ values or Source            │
│ hand-edit notes│ └────┘                                          │                             │
│                │                                                 │                             │
│ ─────────────  │  size line          ┌─ result strip ─────────┐   │ ─────────────────────────── │
│ prompt, agent  │  mass, how known    │ legend · error · limits │   │ pipeline, one line          │
└────────────────┘  or a key hint      └─────────────────────────┘  └─────────────────────────────┘

Sheets over the stage (the conversation stays):   Bench open (⌘B) · Overview (design capsule)
Sheets over the window:                           Palette (⌘K) · Settings · Home
```

Fixed positions at 1440 × 900: edge 20, gap 12. Conversation 340 wide, pane 332 wide, dock 48 wide at the stage's
left edge, stage 644 wide between them. Top row on one centre line.

## Decisions, and why

| # | Decision | Why |
|---|---|---|
| 1 | **Four modes: Design, Check, Make, Document.** Today's five stages become four | They are the plan's own grouping (its parity matrix and the Bench's groups). One set of words for the modes, the Bench, the palette and the CLI means a person learns the app once. Five stages plus a Bench with different groups would be two maps of the same place |
| 2 | **Describe becomes the Overview**, opened from the design capsule | The brief, the measured values and the purpose describe the design, not a step of work. As a mode it sat empty most of the day. As the Overview it also holds what wave P adds: decisions with their source, open questions, files by kind, the family, revisions |
| 3 | **Fit becomes a study in Check** | Fit yield is a model with an evidence class, exactly what a study is. As a row it gets a state, staleness and a place in the report for free |
| 4 | **The right pane is the Bench, docked.** One pane, one row grammar, in every mode | Today the pane changes its whole character per stage. With studies, routes and documents arriving it would have to become tabs. One grammar (state dot, name, number, evidence word) reads the same for a feature, a study, a route and a sheet |
| 5 | **The Bench opens into a sheet** of four columns, no tabs (Ctrl/⌘ B, or the button in the top right) | The reference has a Toolbox of 32 tools in four tabs: three quarters are always hidden. Thirty rows fit on one sheet at 50 px each. Everything is visible, each with its state, and a row that cannot run is dimmed and says what it needs |
| 6 | **A selected row opens in place**, under the list | No modal, no second pane. The list stays as the way out. The opened row takes what it needs; the list keeps its size |
| 7 | **Results live on the part; a strip under the part is their legend** | The legend is where the eye already is. It always carries three things: the scale, how the result is known (with the error), and what it does not tell. That is the honesty rule made into a component, shared by stress, thickness, draft, deviation, layers and stock |
| 8 | **The tool dock is mode-aware:** four universal tools (Select, Measure, Section, Annotate), then the mode's own | Hand modelling adds nine tools to today's eleven. One list of twenty is a ribbon standing up. Per mode the dock never passes fourteen, and it is the same capsule in the same place |
| 9 | **Tool options sit at the head of the stage**, one capsule, always in the same spot | Beside the active tool they crossed the part (tried in the first render, rejected). A fixed place also means the hand learns it |
| 10 | **The tree's gutter is the rollback bar** | Lightdesk's one drawn line was the listing's gutter, lit as the build's progress. Dragging it is the same picture run by hand: no new control is drawn |
| 11 | **The lower half of the Design pane is Values or Source** (wave U) | Code, slider and handle change one value. Showing the method under the tree, with the selected feature's lines lit, says that without a paragraph. Off by default; a person who never asks never sees code |
| 12 | **A view cube and a shading chip** at the stage's top right (wave M) replace the row of view buttons | Five buttons for views were the widest thing at the foot of the stage. The cube does the same in 64 px and leaves the foot for the size line and the result strip |
| 13 | **Every reply that rests on something ends in Sources** (wave O), built from the tool log | A number in a reply carries a superscript; the block says simulated, specified, opened. The app's brand is honesty: this is where a first-time visitor sees it |
| 14 | **In Document the conversation folds to the bar** and the sheet takes the stage | A drawing at fit-to-stage with the column open had 5 px dimension text. Folded, an A4 sheet at 1:1 shows at 3 px per mm and its text is 11 px. Calm mode already exists; Document uses it by default |
| 15 | **The printer chip shows only in Make**, and only with a print route | It is a property of one route, not of the app. Elsewhere its place holds the activity line |
| 16 | **Sheets over the stage are denser glass** (80 % plate) | Thirty rows of text over a blurred clay part were not readable at the first render. A sheet is for reading; the room still shows around it |

## Where each thing lives

| Thing | Lives in | Shown when |
|---|---|---|
| Feature tree, rollback bar, suppress, reorder, rename, author marks | Design pane | Always in Design |
| Sketch, extrude, cut, revolve; fillet, chamfer, hole, pattern, shell | Dock, Design group | In Design |
| Sketch on a face, constraints as glyphs, degrees of freedom | On the part; counts and values in the opened row | While a sketch is open |
| Edge handles, gizmos with a number field, edit a dimension on the model | On the part | While the tool is active or a dimension is double-clicked |
| Source of the design | Design pane, lower half, Source | On request |
| Contract (proof sheet), make it lighter, optimise, variants, refine | Bench, Design chapter; palette; completions in the conversation | Bench open; proof rows also while a build runs |
| Checks, mass and inertia, strength, modes, thickness, machinability and other DFM, fit, interference, motion | Check pane (Bench, Check chapter) | In Check; result on the part with its strip |
| Fixtures and loads | Dock, Check group (anchor); drawn on the part | While a study is being set up or shown |
| Analysis maps (thickness, draft, access, zebra, curvature), X-ray, explode | Dock, Check group; strip as legend | In Check |
| 3D print (plates, slice, print simulation), CNC with stock simulation, STEP with PMI, flat pattern, robot files, board and enclosure, renders | Make pane (Bench, Make chapter) | In Make; plates or stock on the stage, a timeline in the strip |
| Printer and slicer | Top right chip; Settings › Printing | In Make with a print route |
| Drawings with GD&T, parts list, standard parts, assembly steps, test plan, report, release | Document pane (Bench, Document chapter) | In Document; the sheet on the stage |
| Brief, purpose, measured values, decisions, open questions, files, family, revisions and branches | Overview (design capsule) | On request |
| Conversations, model picker, attachments, plan card, sources, live status, hand-edit notes | Conversation column | Always; folds to the bar |
| Every action, design, feature, study, document and setting | Palette, Ctrl/⌘ K | On request |
| Designs, families, import, trash, first-day starts | Home | Before a design is open |
| Set up for, engines with licence and size, agents, printing, machining, materials, appearance, keys, privacy | Settings | On request |
| Triage of any input, scans to CAD | Home's composer and the conversation (unchanged) | When something is dropped |

## How the eye travels

1. **Top centre: where am I.** Four words; the lit one is the mode, the line under each is its state.
2. **Centre: the part.** Still the only bright thing. Whatever the mode adds is drawn on it.
3. **Right: what there is to ask.** The list for this mode, then the one thing you opened.
4. **Under the part: can I trust it.** The strip: scale, evidence, limits. Or the size line when nothing is shown.
5. **Left: what was said.** The record, read when you want the reason.

The hand follows the same path the other way: say it on the left, or pick a tool from the dock and work on the part.

## Screens

All at 1440 × 900, rendered at 2x, dark and light. HTML is the screen's name with `.html`.

| Screen | Dark | Light |
|---|---|---|
| Home | `home-dark.webp` | `home-light.webp` |
| Designing (the agent builds) | `designing-dark.webp` | `designing-light.webp` |
| Design: tree, rollback bar, hand tools, sketch on a face | `design-dark.webp` | `design-light.webp` |
| Design: a picked edge with its handle, and the Source pane | `design-edge-dark.webp` | `design-edge-light.webp` |
| Bench, open | `bench-dark.webp` | `bench-light.webp` |
| Overview of a design | `overview-dark.webp` | `overview-light.webp` |
| Check: a strength study | `study-dark.webp` | `study-light.webp` |
| Document: a drawing sheet | `drawing-dark.webp` | `drawing-light.webp` |
| Make: multi-plate print | `make-print-dark.webp` | `make-print-light.webp` |
| Make: CNC with the stock simulation | `make-cam-dark.webp` | `make-cam-light.webp` |
| Settings | `settings-dark.webp` | `settings-light.webp` |
| Command palette | `palette-dark.webp` | `palette-light.webp` |
| Variant: the sheet as white paper in the dark room | `drawing-paper-dark.webp` | |
| Storyboards of the three moments | `moment-develop-dark.webp`, `moment-rollback-dark.webp`, `moment-unfold-dark.webp` | |

## Signature moments

Each is a real capability shown, not decoration, and each can be skipped by a key or a click.

1. **A result develops.** When a study's result is first shown, the map comes up on the part from the peak outward,
   like a print in the tray; the legend settles; the error statement lights last. 520 ms. A result that did not
   converge never plays it: it shows its reason.
2. **A feature lights as the bar passes.** Drag the rollback bar through the tree: the part steps back under it from
   the kernel's checkpoints, the feature the bar passes flashes its edges once in cyan, later cuts stay as faint
   outlines. The bar itself has no easing; it is under the pointer.
3. **The sheet unfolds from the part.** Going to Document, the part's visible edges light, the camera turns to the
   front, the top and side views swing out on the hinges a third-angle sheet implies, and land on the paper.
   Dimensions fade in last. 480 ms, once per visit.

## Motion spec

Lightdesk's tokens stay (`Theme.qml`: press, ui, cross, camera, part; `easeOut`, `easeMove`). New entries only:

| What | Duration | Easing | Notes |
|---|---|---|---|
| Mode change: the lit segment glides, the pane's rows cross-fade | 180 ms | ease-out (0.16, 1, 0.3, 1) | The pane keeps its frame; only its rows change. The dock's mode group fades, the universal four do not move |
| Bench opens: the pane's left edge travels to the stage's left edge | 220 ms | ease-out | Columns fade in over the last 120 ms, staggered 20 ms. Closing is 160 ms |
| A row opens in place | 140 ms | ease-out | Height and opacity; the list above does not move |
| Tool options change | 0 ms | none | Used all day: a cut |
| Rollback bar | follows the pointer | none | Feature flash 140 ms linear in, ease-out; row glass 80 ms. Budget: under 100 ms from position to solid |
| Result develops | 520 ms in all | ease-out | Mask radius 0 to 320 ms; legend and error line 320 to 520 ms |
| Sheet unfolds | 480 ms in all | ease-in-out (0.65, 0, 0.35, 1) for the fold | Edges 0 to 140, fold 140 to 340, landing 340 to 480, dimensions +120 |
| Strip appears under the part | 180 ms | ease-out | 8 px rise, as panes do today |
| Handle drag, scrubbed number | follows the pointer | none | The draft's impact number updates when the kernel answers; it never animates toward a value it does not have |
| Sources block under a reply | 120 ms | ease-out | Opacity only, after the text has finished streaming |
| Stock or layer scrub | follows the pointer | none | Playing: real time scaled so a whole job takes 8 s at most |

Rules: nothing over 520 ms; nothing that is used every minute animates; a signature moment plays once per result
or visit and is cut by any input; Reduce Motion turns each into a cross-fade of 160 ms or less.

## What changed from Lightdesk

| Lightdesk today | Direction I | Why |
|---|---|---|
| Five stages: Describe, Design, Fit, Review, Make | Four modes: Design, Check, Make, Document | Decisions 1 to 3 |
| The pane is a different panel per stage; the pipeline is a second pane | One pane, one row grammar; the pipeline is its last line (as the app already does) | Decision 4 |
| No single place for studies, routes and documents | The Bench, docked and open | Decision 5; plan wave A |
| Eleven tools in one dock | Four universal, then the mode's; options at the head of the stage | Decisions 8 and 9 |
| View buttons at the foot of the stage | View cube and shading chip, top right | Decision 12 |
| The gutter line shows build progress | It also is the rollback bar | Decision 10 |
| Replies end in text | Replies end in Sources; numbers carry superscripts | Decision 13 |
| Describe as a stage | Overview from the design capsule, with decisions, questions, files, family | Decision 2 |
| Printer always in the top right | Only in Make with a print route | Decision 15 |
| Smallest type 9.5 px (role words in the listing) | Smallest type 11 px | The brief's "nothing tiny" |
| Role words (STRUCTURE, ACCESS) on each feature | The feature's own value and who made it | The role told less than the value; author marks are wave O |

Unchanged: the room and pool, glass, cyan as the one accent, Geist, the cue while building, the conversation
column and its fold, the prompt's thin caret and `›`, numbered completions, dimension tags on the part, evidence
words in mono capitals, pass and review as state colours only.

## What is real in the pictures

| In the pictures | How it is known |
|---|---|
| The part (a NEMA 17 motor mount), each stage of it, its 30 faces | **Computed**: built with build123d on OCCT by `tools/build.py`, stage by stage |
| 56.0 × 52.0 × 62.0 mm, 38.98 cm³; 39.87 cm³ at step 5 | **Computed** by the kernel in that build |
| 105.2 g | **Computed**: that volume × 2.70 g/cm³ (6061, a typical handbook density) |
| 22 mm pilot, 31 mm screw square, 3.4 mm clearance holes | **Specified**: the NEMA 17 frame and ISO 273 medium clearance for M3, from memory of those standards, not opened for this work |
| The drawing's views | **Computed**: OCCT hidden-line removal of that solid (`tools/hlr.py`). The dimensions drawn are the build's own values |
| The stock in the CNC screen; 137.0 of 213.8 cm³ removed | **Simulated** for these mockups: a height-map stock removal at 0.1 mm for a Ø6 flat tool with 2 mm steps (`tools/fields.py`). It is not the app's CAM, which does not exist yet |
| Sketches, handles, dimension lines, loads | Drawn over the render through the render's own camera, so they sit where the geometry is |
| The plate layouts | The real part, placed by hand at a 60 mm pitch on a 180 mm plate |
| Hand estimate 21.6 MPa | **Computed** here: 250 N × 29 mm over a 56 × 6 mm section (bh²/6 = 336 mm³) |
| **The stress map and every strength number** (14.2 MPa, 19.4, 0.006 mm, ≤ 2.8 %, 0.04 %, the convergence points) | **Illustrative.** No solver ran. The field is a hand-shaped function in `tools/fields.py`. They show how a result would read, not what this part does |
| 276 MPa yield for 6061-T6 | A typical handbook value, quoted from memory |
| Print time, filament, CAM time, file sizes, engine sizes, "98 %" fit, check counts, conversation text, dates, costs, the code in the Source pane | **Illustrative** demo values and wording |
| Echo dock, Kilo box thumbnails on Home | The app's own 3D view, cut out for direction H |

In the app each of these would carry its evidence word, as the mockups show. In this folder the last three rows are
invented for the demonstration and must not be quoted as results.

## What was checked, and what was not

Checked on the renders, at 200 % crops, dark and light: the tree and its opened row, the conversation with Sources,
the top row, the sketch on the face (registered to the face; the gusset in front masks it), the edge handle, the
legend strip, the Bench's rows, the drawing's front view and whole sheet, Home's shelf, the contract card. Found and
fixed on the way: a tool-options capsule crossing the part, a title capsule laid out in a column, a hint running
into the size line, stretched state dots, truncated labels, the picture's rectangle showing in light, a bloom that
hazed the whole part, text under 11 px on the sheet, sketch tint drawn over a gusset that hides it.

Not done, or not verified:

- **Not built.** These are HTML pictures. Glass here is `backdrop-filter`; in Qt it is `Glass.qml`, and the look of
  dense sheets over the room has to be checked there.
- **The part pictures are offline renders** (Blender Cycles of the kernel's mesh), chosen to match the app's clay.
  They are a target for the viewport, not a capture of it. The glow on the stress map in particular (an emissive
  map plus a bloom) has no equivalent in the app's view today.
- No hover, pressed, focus, empty, error or loading states were drawn, and no window under 1440 px.
- Only one state per screen. Assemblies, a failed study, a stale Bench, a design for moulding, sheet metal, motion,
  boards and the test plan have a place in the map but no picture.
- Light theme: every screen was rendered and looked at whole; fewer 200 % crops than dark.
- The storyboards are three stills each. The timings are a specification, not something watched in motion.
- Banding: looked for at 200 % on the room and the pools and not seen; the pages carry a fine noise layer, as the
  app dithers in its shaders. Not checked on an 8-bit external display.
- Wording was written for the pictures and has not had a copy pass.

## Choices for the owner

Each is drawn one way; the other way is described (or rendered, where said).

1. **Modes.** (a) Four modes, with Describe as the Overview and Fit as a study: drawn. (b) Keep Describe as a first
   mode, five in all: more familiar, but one mode is then a form rather than work on the part.
2. **The sheet in the dark theme.** (a) A night sheet, ink in light on a dark plate, dimensions in cyan:
   `drawing-dark.webp`. (b) White paper in the dark room, as it will print: `drawing-paper-dark.webp`. P would
   switch between them either way; the question is the default.
3. **The dock.** (a) Vertical at the stage's left edge, as today: drawn. (b) Horizontal under the part: closer to
   the hand, but it competes with the result strip and with the bar when the conversation is folded.
4. **The stress map's colours.** (a) One hue: clay, then cyan, then white at the peak, so the part "lights where it
   works" and cyan stays the only accent: drawn. (b) A conventional many-colour scale as an option in the legend,
   for people who read results in other tools all day.
5. **Feature rows.** (a) The value and who made it: drawn. (b) Keep the role word (STRUCTURE, ACCESS) as today and
   show the value only in the opened row.

## How the pictures are made

```
.venv/bin/python docs/design/directions/i/tools/build.py  OUT     # the part, stage by stage (kernel)
.venv/bin/python docs/design/directions/i/tools/fields.py OUT     # illustrative stress mesh; stock height map
.venv/bin/python docs/design/directions/i/tools/hlr.py    OUT     # hidden-line views
blender -b --python docs/design/directions/i/tools/render.py -- OUT RENDERS    # Cycles, transparent, orthographic
.venv/bin/python docs/design/directions/i/tools/assets.py OUT RENDERS          # feather, WebP, assets/geo.js
.venv/bin/python docs/design/directions/i/tools/shoot.py [screen ...]          # the screens, 2880 × 1800 WebP
```

`assets/geo.js` holds the cameras' projections, the hidden-line paths and the computed numbers the pages read.
The plate renders were made in a second run after a spacing change; `assets.py` expects all renders and one `proj.json` in RENDERS.
The screens are saved as WebP at quality 95 (about 300 kB each) rather than PNG (about 1.5 MB each).

## Approved (2026-11-28)

The owner approved direction I with the recommended choices: four modes (Describe becomes the Overview, Fit a
study in Check); the drawing sheet in the dark theme is a night sheet with cyan dimensions, and a key switches it
to white paper; the dock stays vertical at the stage's left edge; stress maps use one hue (clay to cyan to white),
with a many-colour scale as a legend option; feature rows show their value and who made the feature.

## Built so far (branch `direction-i`)

| Part | State |
|---|---|
| Tokens: 11 px minimum, edge 20, pane 332, the evidence word, the motion durations | Built |
| Four modes with a line of state; Describe as the Overview; Fit as a study in Check; Document | Built. The Overview holds the brief and the revisions; decisions, open questions, files by kind and the family are not built |
| View cube and shading chip; no view buttons at the foot | Built. The chip lists the build plate, the floor grid and the dimensions; the 3D view has no other shading modes yet |
| Legend strip under the part | Built for the four analysis maps. One band per stop, not a continuous scale with a marker |
| One row grammar (`BenchRow.qml`) | Built (branch `direction-i-2`). Every row of Check, Make and Document, and of the Bench sheet, is a `BenchRow`: mark, name, number, evidence word, or the state in words. No hand-written rows remain; Fit is the engine's entry. Slice, print simulation and CNC are listed in Make |
| The pane as the Bench's chapter, the selected row opened under the list (`Bench.qml`, `BenchCard.qml`) | Built. The checks (Check) and the release gate (Make) still open as the panels they were, under the list. No convergence plot or per-result detail lines as drawn for the strength study: the card shows the engine's headline, detail, note, inputs, files and request |
| The Bench as a sheet, Ctrl/⌘ B (`BenchSheet.qml`) | Built: four columns (two or one in a narrow window), filters, find, the selected row at the foot with its request. Not built: Edit the request, Pin, engine install progress in the foot |
| The tree: value and author per row, the rollback bar lighting the feature it passes, Values or Source | Built. The author is the origin of the first revision whose build log names the feature. Source is read-only and not syntax-coloured. The opened feature is the parameter panel that existed, not the mockup's card with constraints |
| Hovering a row lights its feature or region on the part | Built for the tree and for Fit (its clearance feature). Studies do not name a region yet, so their rows light nothing |
| The palette's ranking | Built: tiers by closeness; the modes answer to their old names |
| The conversation: Sources, the plan card, the live line, hand-edit notes, saved prompts, commands on the selection (`form/cite.py`, `TalkSources.qml`, `TalkPlan.qml`, `TalkCard.qml`) | Built (branch `di-talk-home`). Sources come from the turn's tool calls and their results' evidence classes; a number in the reply is marked only when it stands in a source's result. Not built: numbers as mono chips, "opened earlier / not opened / model knowledge" rows, naming a saved prompt, saved prompts on the Bench, Skip on a plan the agent did not ask about. Author marks are the tree's (built earlier); a message has none |
| Home | As it was built for Lightdesk, which the mockup follows: the composer, the numbered starts, Make it for, the shelf with its count, filters, sort and families. Changed here: no index number on a card. Not as drawn: the model chip stands in the well beside Design it, not under it; no Trash link; no check state in a card's second line |
| Settings | Grouped pages and glass rows as before; Reduce motion added. Not as drawn: the sheet keeps its own layout (a rail in a box, cards) and Engines is its own page, not a list on General |
| The palette | Restyled: lit well, the design as scope, grey group names, one lit row, a Saved prompts group. Not built: a row's preview, "Tab search everywhere", results from inside conversations |
| The Designing screen | Uses the conversation's live line and the same words for a tool. Its layout is unchanged |
| The mode-aware dock and tool options capsule, sketch on a face | Not built: the dock is still one list, and the sketch a sheet |
| Results on the part from the later engines (strength, DFM, CAM, sheet flat, the drawing sheet, motion) | Not built. `integrate-2` is merged: every one of its studies, routes and documents is a row of the docked Bench and of the sheet, and opens as the same card (headline, evidence, request, file). Nothing of theirs is drawn on the part yet, and the drawing has no sheet pane |
| The three signature moments | Not built. The rollback bar lights the feature it passes (a 420 ms highlight), without the outlines of later cuts |
