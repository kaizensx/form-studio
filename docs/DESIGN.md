# Design brief

How Form Studio's desktop app looks, is organised and moves, and why. The visual direction (Lightdesk: a room, panes
of glass over the 3D view, the program and the bar) is in `docs/design/DIRECTION.md`. The tokens live in
`form/app/qml/Form/Theme.qml`; the rules for writing QML are in `form/app/qml/CONTRIBUTING-UI.md`. This page is the
intent those two serve. Change it first, then the code.

## Intent

Form Studio is a creation tool. A person describes something and watches it become real, editable CAD. The interface
is a bench: quiet, exact, and always pointed at the part. It is a native desktop app and should feel like one: no web
page furniture, no decoration that carries no meaning, nothing that moves without a reason.

Three tests for any screen:

1. **One focal point.** Home's is the question and the composer. The workspace's is the part. A sheet's is its primary
   action. If two things compete, one of them is too loud.
2. **Creation first.** The words on screen follow the work: describe, design, review, make. 3D printing is one way to
   make and appears only when it is turned on, and then only where the printer matters. Not printing is the normal
   case and needs no label.
3. **Honest.** Every number says how it is known, and nothing is drawn that the engine did not compute.

## Organisation

| Screen | What it is for | Order of what is on it |
|---|---|---|
| Opening | Under a second while the engine starts | The mark drawn on its origin, the name, one status line |
| First run | Three choices, then only what was chosen is downloaded | Rail of steps, the step, the log |
| Home | Start a design; find the ones you made | The question and composer, concepts waiting for a pick, designs (one card per family), conversations |
| Workspace | One design | The part, edge to edge. Over it, as panes of glass: title, stages and tools (top), the tool dock (left), the size line and views (bottom left), the Program, which is the stage's panel (right), the pipeline (bottom right), the conversation bar (bottom centre, opening upward into the transcript, with a strip of its designs when it made several) |
| Designing | A design being made, or a conversation with none yet | The empty studio floor, what the agent is doing, then the cue and the program so far as stages arrive; or "No design yet" and Continue the conversation |
| Sheets | One task that needs the whole attention | Title, body, actions with the primary one last |

**The stages** are the flow of making something, left to right: **Describe** (what it is for, what is known),
**Design** (features and parameters), **Fit** (clearances; only for a design made for printing), **Review** (the
checks and their evidence), **Make** (approve, then the files). The engine, the CLI, MCP and the code keep the ids
`brief`, `shape`, `fit`, `prove`, `release`; the old words still find each stage in the command palette.

**Design families.** A design and everything that came from it (copies, saved variants, the concept that was picked)
share `lineage.root`. Home shows one card per family: the member changed last is its face, a count opens the family
under its row, the first design first. Conversations are grouped the same way by `thread`.

**Top bar.** Three capsules: the mark, the design's name, revision and release state; the stages; search and
settings. It never labels a design as "not for printing". The printer chip (`PrinterChip.qml`) sits in the right
capsule for a design made for printing, in every stage.

**Conversations and designs.** Opening a conversation lands on its design within a second; with several, a strip
under its title lists them; with none, Designing says "No design yet". Once the person has worked on the open design
(selected a feature, changed a value, opened it themselves), an agent working elsewhere is named with Show and never
jumped to.

**The ground.** Every design stands on a neutral studio floor: matte, fading to the horizon, a faint origin cross and a
scale cue (a round length at the part's distance). The viewport's `stageMode` is `studio` by default and `plate` only
in Fit, Review and Make of a design made for printing, or on **Show build plate**: then the printer's plate, its 10 mm
grid and its outline ease in, and leave on the way back. Home, cards and Designing are always studio.

## Appearance

Two appearances, one design: the dark studio (the default) and paper (light). Settings › General ›
Appearance chooses Dark, Light or Match system. Every colour token is a pair, so a screen that uses only tokens is
right in both; a hard-coded colour is a bug.

| | Dark | Light |
|---|---|---|
| Bench (`plate`) | near-black `#0b0b0c` | paper `#eeece8` |
| Panels, cards, raised (`plate1…3`) | each step lighter | each step whiter |
| Inputs (`well`) | darkest | white |
| Ink (`ink…ink4`) | `#f4f3f1` to `#4c4b48` | `#161616` to `#a5a39e` |
| Edges and washes | white at 5 to 20 % | near-black at 5 to 26 % |
| Datum (the one accent) | periwinkle `#a9b8ff` | deep periwinkle `#3d55d6` |
| Pass, review, fail (state only) | `#86d9a8`, `#f2c36b`, `#ff6f51` | `#1f8a52`, `#a86a00`, `#c8452b` |
| The part (`clay`) | `#d8d3c8` | the same |

**Depth** comes from the surface steps and a hairline edge, not from heavy shadows. Shadows are kept for things that
float (menus, sheets, toasts, a card under the pointer) and are drawn at 30 % strength in light. Higher always means
nearer the light.

**Colour is evidence**, never decoration: datum is specified or selected, pass is measured or settled, amber is
assumed or simulated, signal is a failure, blueprint is a draft or a comparison. One accent per view.

## Type

Instrument Sans for words, Geist Mono for numbers, lucide for icons. The scale steps by about 1.2 from 13 px:

`tCap 10 · tFine 11 · tBody 13 · tLead 15 · tH3 18 · tH2 22 · tH1 30 · tHero 44 · tDisplay 52`

Hierarchy comes from weight and tone before size: a value is 620 and full ink, a label 520 and second ink, a note 420
and third ink. Large type is set tighter, small capitals wider. `tDisplay` is used once in the app, for Home's
question.

## Space

A 4 px base: `s1 4 · s2 8 · s3 12 · s4 16 · s5 20 · s6 24 · s8 32 · s10 40 · s12 48 · s16 64`. Inside a control 8;
between related rows 12; card padding 16; between groups 24; between the bands of a page 48 to 64. Radii
`4 · 6 · 9 · 14 · 18`, concentric when nested. Control heights `24 · 28 · 34`. Sheets come in four widths
(`480 · 640 · 840 · 1080`); do not invent a fifth.

## Motion

Motion explains a change of place or state and then gets out of the way. Ease-out for anything arriving or answering,
ease-in-out for something already on screen that travels; no bounce, no overshoot.

| Token | ms | For |
|---|---|---|
| `press` | 110 | a control answering a press |
| `fast` | 120 | hover and colour |
| `pop` | 150 | menus, popovers, tooltips |
| `base` | 180 | sheets, toasts, a family opening |
| `screen` | 240 | one screen handing over to the next |
| `slow` | 320 | first-run and entrance moments |
| `exit` | 110 | anything leaving: always faster than it came |

Things used all day (the palette, keyboard actions, tabs switched from the keyboard) do not animate. When the system
asks for reduced motion, movement and scale are dropped and only opacity and colour change (`Theme.move`,
`Theme.shift`, `Theme.from`).

**The opening screen** is the one authored moment. The mark is a coordinate frame, so the app opens on its origin: two
construction lines meet there, the mark is built on them, the name sets beside it. When the engine is ready the lockup
travels to the top bar and lands on the logo that stays, while the plate fades to Home behind it. No cut, no flash,
and no longer than the engine needs (at least 0.8 s, so the mark is always finished).

The lockup is complete within 0.45 s and centred in the window, with the bar and one status line centred under it.
That line is bound to what has really happened (`Store.bootStatus`, fed by `/api/boot` and `/api/studio`): the
engine answering, the CAD kernel answering, the designs and setup being read. The bar is indeterminate; nothing
feeds it a fraction, so it never shows one. While the lockup travels the top bar holds its own logo back, so there
are never two.

## What this pass changed

- Creation-first shell: no printer or purpose in the top bar; the studio floor instead of a build plate everywhere
  but Fit, Review and Make of a print; conversations open their designs, with a strip for several and "No design yet"
  for none; a new design is a 3D model unless printing is asked for.

- The opening screen was rebuilt (it was a centred mark on banded glow rings, held for 2.3 s).
- Home groups designs into families and puts designs before conversations; the sentence under the question shows only
  on a first visit.
- The stages are named for what you do in them.
- A light appearance, and the 3D bench's colours as tokens.
- Screen changes take 240 ms instead of 380.
