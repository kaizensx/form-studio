# Visual direction: Lightdesk

One direction for the whole app, and the reasons for it. `docs/DESIGN.md` says how the app is organised; this page
says what it looks and moves like. Tokens live in `form/app/qml/Form/Theme.qml`. The mockups it was approved from are
in `docs/design/directions/h/` (`workspace-dark.png`, `build-dark.png`, `home-dark.png`, `workspace-light.png`,
`tokens.png`, and their HTML and CSS).

## The idea

Form Studio turns words into exact, checkable CAD. The window is a **photo studio**: the part alone in a pool of warm
light, and every control a pane of glass floating over it. Set into the glass are two instruments: the features as a
**program** that runs line by line while the agent builds, and a **command line** with numbered completions as the
one bar under the part. A lighting desk does the same job in a theatre: a quiet console that runs a cue list and
moves the light.

Three tests for any screen:

1. The part (or, on Home, the question) is the only bright thing.
2. Nothing is drawn that is not a pane, a word or a number. The one drawn line is the program's gutter, and it is the
   progress bar.
3. A number is in mono, with its unit, and is computed. During a build it is the number of the build so far.

## Structure: a room and its panes

| Layer | Token | Dark | Light | What it is |
|---|---|---|---|---|
| Room | `frame`, `plate`, `room` | `#0b0b0c` | `#eeece8` | The window itself and the 3D view, edge to edge. Home stands in the same room |
| Key light | `key`, `benchPool` | warm `#ffe9cf` | white | The pool under the part, on the floor (`benchPool`) and as a faint breathing glow over it |
| Glass | `glass`, `glassTint`, `glassEdge` | white 7 % over the blurred room | white 62 % | Every pane: capsules, the dock, the Program, the pipeline, the bar, sheets, menus |
| Raised | `glass2` | white 14 % | white 95 % | The lit stage, the line being built, a key, a hovered row |
| Well | `glassWell` | the room at 66 % | white 82 % | The prompt |
| Solid | `glassSolid`, `plate1`…`plate4` | | | What glass is when nothing can be blurred, and surfaces inside sheets |

- Panes sit `edge` 20 px from the window and `gap` 12 px from each other. Pane radius `rPane` / `rPanel` 22; buttons
  and capsules are fully round; listing lines and keys 10; sheets `rXl` 26. The hairline of a pane is `panelEdge`.
- `Glass.qml` is the material. It blurs a quarter-size copy of the part of the room under the pane, lays `glassTint`
  and `glass` over it, and draws a 1 px edge of light, a highlight along the top and a soft shadow. The copy is only
  redrawn when the room changes, so a still view costs nothing. With "Reduce transparency", in Low Power Mode, on a
  software renderer or with `FORM_GLASS=solid` the pane is `glassSolid` and nothing is blurred (`Theme.blur`).
- No dividers. Space separates; a pane inside a pane is `glass2`.

## The workspace

- **Top:** three capsules. The title (the mark, the design, its revision, its state), the stages in the centre
  (Describe, Design, Fit, Review, Make, each with its one line; the lit segment glides), and tools on the right (the
  printer when printing is on, search, settings).
- **Left:** the tool dock, one capsule. The active tool is the one filled disc. The tool's options sit beside it.
- **Bottom left:** the size line (W × D × H mm · volume cm³, and which arrangement that is) above the view buttons
  and the floor-grid button. During a build it reads "as modelled so far" with the size of what is built, no volume.
- **Right:** the Program. In Design it is the feature list as a listing: line numbers, the name, the role in neutral
  mono capitals. In the other stages the same pane holds that stage.
- **Bottom right:** the pipeline as a capsule: a state dot, the step, one mono line with its real value; Auto.
- **Bottom centre:** the conversation as one bar: a status line, numbered suggestions (keys 1 to 4 pick them while the
  prompt is empty), the prompt with a `›` and a block caret, attach, the agent, send. It opens upward into the
  transcript, as tall as what was said and at most about half the window, and folds back on Ctrl/⌘ J.

**The cue.** While a build plays, the lower third of the room is a film title: `BUILDING 6 OF 12`, the feature in
large type with its number, a track with one segment per step and the current one glowing, and "built 05 … / next
07 …". The same step is lit in the Program: the gutter is lit down to it, the lines above are ticked, the ones below
wait. The tools and view buttons step back to 45 %, the key light narrows and warms, and the transcript folds so the
part has the room. All of it is driven by the real build (the stages the kernel streams, or the build-up of a new
revision); nothing counts on its own.

## Type

Geist for words, Geist Mono for numbers and lettering (both SIL OFL 1.1, bundled), lucide for icons.

| Token | px | Use |
|---|---|---|
| `tCap` | 10 | Tags and overlines: Geist Mono, capitals, medium, +0.1 em |
| `tFine` | 11 | Notes, units, line numbers |
| `tBody` | 13 | Everything read |
| `tLead` | 15 | The prompt, a sentence that leads a pane |
| `tH3` `tH2` `tH1` | 18 22 30 | Titles, tighter as they grow |
| `tCue` | 54 | The feature being built |
| `tDisplay` | 68 | Home's question |

Weights: 400 to read, 500 for labels, 600 for names, titles and buttons.

## Colour

One accent, electric cyan (`datum`: `#3ee6ff` on the dark room, `#087f9f` on paper, where `#0a8fb3` is its brighter step for fills). It has one meaning: **this is where
you are**: the stage you are in, the line being built, the prompt, a selection, focus, the dimension lines on the
part. It is the complement of the warm key light. Green (`pass`) only means pass, released, built: a status, never a control. Amber only
means review. Red (`signal`) only means fail. The one filled button is ink on the room (`send`, `sendInk`): send,
Design it, the active tool. The part is clay in both appearances; the origin of the logo mark is the accent too.

## The 3D view

A product photograph: a matte floor that falls to the room's colour at the horizon, lit in a warm pool under the
part (`benchPool`), a soft shade under its footprint, a warm key from the upper left, satin clay, edges drawn as
lines. The corners of the room fall away in a vignette. The floor's 10 mm grid (`benchLine`, a firmer line every
50 mm) is off until the grid button asks for it; in Fit, Review and Make of a print design the printer's plate takes
its place. Dimension labels are small capsules in the accent.

## Motion

Motion explains a change of place or state, then stops.

| What | How |
|---|---|
| Panes arriving (launch, a design opening) | Fade and an 8 px rise, 180 ms ease-out, `stagger` 45 ms apart |
| The stage you pick | The lit segment glides, 240 ms; the pane's content slides in from the side it lies on |
| A line of the program executes | The gutter lights down to the next line, 140 ms; a built line is ticked with a small spring |
| The cue | The title slides up and fades between features; a segment fills in 220 ms |
| The key light | Narrows and warms on a build, 600 ms; breathes very slightly while nothing happens |
| The transcript | Opens and folds on a spring (`springK`, `springDamp`) |
| Send | Turns into stop while a reply is written: the disc goes to glass, the arrow to a square |
| The camera | Eases (`camera` 420 ms) whenever what covers the view changes |
| Hover, press | 120 ms colour; a chip lifts 1 px; a press scales to 0.97 |

Reduce Motion (`Theme.reduced`): movement, scale and springs are dropped (`Theme.move`, `Theme.shift`, `Theme.from`);
only opacity and colour change, the gutter jumps, nothing breathes. Idle breathing (the key light, the caret) is
stepped a few times a second instead of animated, so a still window does not redraw at the display's rate.

## Signature

The cue: the lower-third title over the room and the same line lit in the program, with the gutter filled down to it.

## For other surfaces

Use `Glass { source: Store.backdrop }` for anything that floats; `flat: true` inside something that scrolls. Use
tokens only: `glass`, `glass2`, `glassWell`, `send`, `datum`, `pass`, `amber`, `signal`, the inks and `rule`. The
older names (`frame`, `plate1`…`plate4`, `well`, `rPanel`, `gap`, `panelEdge`, `benchPool`, `benchLine`) still exist
with Lightdesk values.
