# Visual direction: the drawing sheet

One direction for the whole app, and the reasons for it. `docs/DESIGN.md` says how the app is organised; this page
says what it looks and moves like. Tokens live in `form/app/qml/Form/Theme.qml`.

## The idea

Form Studio turns words into exact, checkable CAD. So the app looks like the two objects an engineer trusts: **a
drawing sheet** (lettered captions, a true grid, dimension lines, registration marks) and **a measuring instrument**
(dark plates, one datum colour, mono numerals, nothing decorative). The part is always the brightest, most detailed
thing on screen; everything else is drawn around it like the border of a drawing.

Three tests for any screen:

1. The part (or, on Home, the question) is the only bright thing.
2. Every line on screen means something: a plate's edge, a scale, a datum. No ornament.
3. A number is in mono, with its unit, and says how it is known.

## Structure: plates on a frame

A workspace is three plates resting on the window's frame, not one surface cut by divider lines.

| Layer | Token | Dark | Light | What it is |
|---|---|---|---|---|
| Frame | `frame` | `#070909` | `#dfe3e1` | The window itself, including the top bar. Shows in the 8 px gutters |
| Bench | `plate` | `#0e1113` | `#eceeed` | The 3D view's background; Home |
| Panels | `plate1` | `#121619` | `#f5f6f5` | The conversation and the inspector |
| Cards | `plate2` | `#181d21` | `#fafbfa` | Cards, sheets, the tool rail and the strip over the part |
| Raised | `plate3`, `plate4` | `#20272c`, `#2a3238` | `#ffffff`, `#e9eceb` | Menus, buttons, a control under the pointer |
| Inset | `well` | `#090b0d` | `#ffffff` | Inputs |

- Plate radius `rPanel` 12, gutter `gap` 8, edge `panelEdge` (a hairline at 8 % dark, 11 % light).
- The top bar has no fill and no rule of its own: it is the frame.
- The 3D view is a plate too. `PlateFrame.qml` rounds its corners with the frame's colour and draws the
  registration ticks of a drawing sheet in its corners.
- Home is one open bench with no plates: a different room from a workspace, on purpose.

**Depth strategy.** Three steps only: the frame (lowest), plates (resting), things that float (the tool rail, the
strip, menus, sheets, toasts: `Shadow`). Plates do not cast shadows; the gutter separates them. Higher is always
lighter, in both appearances.

## Type

Instrument Sans for words, Geist Mono for numbers and for lettering, lucide for icons. No new fonts.

| Token | px | Use |
|---|---|---|
| `tCap` | 10 | Captions and tags: **Geist Mono, capitals, weight 520, +0.7 tracking**. The lettering of a drawing |
| `tFine` | 11 | Notes, units |
| `tBody` | 13 | Everything read |
| `tLead` | 15 | A sentence that leads a panel |
| `tH3` `tH2` `tH1` | 18 22 30 | Titles, tighter as they grow (−0.2, −0.4, −0.8) |
| `tHero` `tDisplay` | 44 52 | One line per screen at most |

Hierarchy is weight and tone before size: a value 620 in full ink, a label 520 in second ink, a note 420 in third.
Section captions, evidence tags, stage numbers, revisions and every measured value are mono: when something is mono,
it is either a number or a label on the drawing.

## Colour

One accent. The datum colour (periwinkle on near-black, deep periwinkle on paper) marks what is selected, specified or "you
are here": the active tool, the active stage's mark, dimension lines, the focus ring. Evidence colours keep their
meanings (pass, amber, signal, blueprint) and never decorate. The part is clay in both appearances.

## The 3D view

It should look like a product photograph taken on a drafting table.

- **Floor.** Matte, lit in a pool under the part (`benchPool`) and falling off to the bench colour at the horizon
  (`benchGround` → `plate`). It carries a **true grid**: a line every 10 mm, a firmer one every 50 mm
  (`benchLine`), computed from the floor's own millimetres, strongest in the light and gone before the horizon;
  lines too close to tell apart are left out. In Fit, Review and Make of a print design the printer's plate and its
  own grid take over.
- **Grounding.** A soft shade on the floor under and just around the part’s footprint, with screen-space
  occlusion, so a part stands on the floor instead of hovering.
- **Light.** A warm key from the upper left front that casts the shadow, a warm fill, a cool rim, a little from
  above. By night the frame is toned with a filmic curve; by day with a linear one and a slightly lower key, so the
  floor is paper white instead of grey.
- **Material.** Satin clay (roughness 0.76) with a faint sheen at grazing angles. Edges are drawn as lines.
- **Overlays.** Dimension lines and labels in datum, mono. The tool rail and the strip float over the view on
  `plate2` with a shadow.

## Motion

Motion explains a change of place or state, then stops. Ease-out for arriving and answering (`easeOut`),
ease-in-out for travelling (`easeMove`), the drawer curve for sliding panels (`easeDrawer`). No bounce.

| Token | ms | For |
|---|---|---|
| `press` | 110 | A control answering a press |
| `fast` | 120 | Hover, colour |
| `pop` | 150 | Menus, popovers, tooltips |
| `base` | 180 | Sheets, toasts, the stage mark travelling |
| `screen` | 240 | One screen handing over to the next; the frame's colour changes with it |
| `panel` | 300 | Plates arriving after a screen, `stagger` 45 apart |
| `camera` | 420 | The camera |
| `exit` | 110 | Anything leaving |

Reduce Motion (`Theme.reduced`): movement and scale are dropped (`Theme.move`, `Theme.shift`, `Theme.from`); only
opacity and colour change. Things used all day (the palette, keyboard tab switches) do not animate.

## Signature elements

1. **Plates on a frame** with 8 px gutters and a 12 px radius.
2. **Drawing lettering**: mono capitals for every caption and tag.
3. **The true grid** on the studio floor.
4. **Registration ticks** in the corners of the 3D view.
5. **The datum mark**: a 2 px datum bar under the stage you are in, travelling with the lit tab; its number lights.
6. **Numbered stages** (`01 Describe … 04 Make`) and revisions (`r01`) in mono.

## For Settings and other surfaces

New or changed tokens to adopt: `frame`, `rPanel`, `gap`, `panelEdge`, `benchPool`, `benchLine`; `plate1…3` and
`well` moved by a point or two; `benchGround` is darker by night and paler by day. `Txt { kind: "cap" }` and `Tag`
are now mono (10 px, weight 520): a caption next to a long value may need a little more room. Nothing was removed
or renamed.
