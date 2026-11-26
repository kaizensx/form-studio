# Working on FORM's native interface

The app is Qt Quick (QML) on PySide6. No web view. Everything is in `form/app/qml/Form/`.

## Run and check

```bash
FORM_DATA=$PWD/.dev/data-x FORM_CONFIG=/nonexistent .venv/bin/python -m form.app --check                       # load, print QML warnings
FORM_DATA=... .venv/bin/python -m form.app --shot out.png --project hallway-phone-dock --stage fit --wait 4500  # screenshot of a stage
FORM_DATA=... .venv/bin/python -m form.app --shot out.png --project ID --eval 'Store.openSheet("alternatives")' # run JS first
```

`--shot` prints every QML warning. A screen is done when it prints `ok: 0 warning(s)` and the screenshot looks right.
`--size 1440x1200` gives a taller window so a long panel is visible.

## Interaction tests: press the buttons

A screenshot does not show that a button works. `tests/journeys/*.py` drive the real window with synthetic mouse and
key events (`form/app/uitest.py`) and assert outcomes in the engine. Each journey runs in its own process with its own
data folder, window settings and a stand-in agent CLI; no model, no network, no native dialog, nothing opened outside.

```bash
.venv/bin/python -m unittest tests.test_ui_journeys                            # all journeys (about three minutes)
FORM_UI_SHOTS=.dev/uitest .venv/bin/python -m unittest tests.test_ui_journeys.Journeys.test_design   # one, keep its screenshots
FORM_DATA=/tmp/x FORM_CONFIG=/nonexistent .venv/bin/python -m form.app --uitest tests/journeys/tools.py::journey_measure
```

```python
def run(ui):                                   # or several functions named journey_…, run in file order
    ui.click("stage-fit")                      # by objectName; ui.click_text("Commit as r02") by what it reads
    ui.fill("fitHi", "0.5", enter=True)        # click a field, replace its text, press Return
    ui.key("Ctrl+K"); ui.type("measure"); ui.key("Return")
    ui.drag(beam, (40, 0)); ui.wheel("viewport", 240); ui.right_click("viewport")
    ui.wait_until(lambda: ui.store.get("measuring") is True, 3, "measuring")      # conditions, never sleeps
    ui.eq(ui.api("/projects/" + pid)["project"]["head"], 2)                       # the engine, not the screen
    ui.shot("fit-window")
```

- A control a journey presses needs an `objectName` (or a text that is unique where it is looked for with `within=`).
  `tests/test_qa.py` fails when a journey names one the QML no longer has.
- Open native dialogs with `Store.ask(dlg)`, never `dlg.open()`: under test the dialog is answered with a path in the
  test's folder (`ui.saved("name.step")`, `ui.pick_file(path)`), and its own `onAccepted` runs as usual.
- `Bridge.reveal / openLink / openDataFolder` are recorded under test (`ui.outside`) instead of opening Finder or a browser.
- A journey fails on any QML warning. `FORM_UITEST_WATCHDOG=120` prints every thread's stack if the event loop blocks.
- A new shortcut goes in `ShortcutsSheet.qml`; `tests/journeys/shell.py` presses every key the sheet lists.

To look at the app or run a journey without a window appearing on the desk, set `FORM_WINDOW_GHOST=1` (with `--shot`,
`--check`, `--tree` or `--uitest`): the real window, drawn by the GPU as usual, but fully transparent, deaf to the
real pointer and keyboard, and never the active app.

## Rules

- **QML's JavaScript is ES2016.** No `async/await`, no object spread (`{...a}`; use `Object.assign`). Promises, arrow functions,
  template strings, `?.` and `??` work.
- **`font.pixelSize` must be a whole number.**
- **Never mutate Store objects in place.** Replace them (`Store.x = Object.assign({}, Store.x, {...})`), or bindings do not update.
- **Never hard-code a colour, font or radius.** Use `Theme`. Colour means evidence: `Theme.pass` settled/measured, `Theme.datum`
  specified/selected, `Theme.amber` assumed/simulated/review, `Theme.signal` fail, `Theme.blueprint` draft/compare. One accent per view.
- **Honesty labels stay.** Every number shows how it is known (`Tag` with `measured | specified | assumed | photo | simulated |
  physical | calibrated | computed`). A slice is "simulated". A fit yield is "modelled". Do not soften or drop these words.
- Panels are a `Column { width: parent ? parent.width : 0 }` of `Sec` groups; the inspector is 360 px wide inside its padding.
- Numbers use `Txt { mono: true }`. Text wraps by default; add `wrapMode: Text.NoWrap; elide: Text.ElideRight` for single lines.
- Inside `Repeater` delegates declare `required property var modelData` (and `required property int index` if used).
- Animate only `opacity`, `scale`, `x`/`y`, colour, and only with the motion tokens below. Nothing that is used all day
  animates (the palette, keyboard actions, tab switches made from the keyboard).
- Every interactive element has hover, pressed, keyboard-focus (`FocusRing`) and disabled states. Use the shared controls
  and you get them; a hand-made `Rectangle` + `MouseArea` owes all four (`Theme.washHover / washPress / washOn`).
- New components must be added to `qmldir` if `Main.qml` uses them (files inside `Form/` see each other without it).

## Design tokens (`Theme.qml`)

The intent behind them is in `docs/DESIGN.md`. Every colour is a pair (dark, light): `Theme.dark` says which is
showing, and `FORM_APPEARANCE=light` (or `dark`) forces one for a run, for screenshots and journeys in both. Look at
every screen you change in both.

| Group | Tokens |
|---|---|
| The frame and its plates | `frame` (the window itself and the top bar) · `rPanel 12` · `gap 8` · `panelEdge`. A workspace's panels are plates on the frame; `PlateFrame {}` over a square view (the 3D view) rounds it and draws the registration ticks. See `docs/design/DIRECTION.md` |
| Surfaces, low to high | `well` (inputs) `plate` (the bench) `plate1` (panels) `plate2` (cards, sheets) `plate3` (menus, buttons) `plate4` |
| Ink | `ink` `ink2` `ink3` `ink4` (primary … muted) |
| Edges | `rule` 7 % · `rule2` 12 % · `rule3` 20 % (hovered or raised) · `focus` (keyboard ring). A low-opacity white (dark) or near-black (light), never a solid grey |
| Washes over any plate | `washHover` `washPress` `washOn` (selected) · `scrim` behind sheets |
| Meaning | `datum` (+ `datumHi`, `datumInk`) `blueprint` `amber` `signal` `pass` `clay`; `Theme.evidence(kind)` |
| The mark and the bench | `markPart` (the logo's arms) · `benchGround` `benchPool` `benchLine` `benchPlate` `benchGrid` `benchEdge` (the 3D bench: floor, its pool of light, its 10 mm grid, the printer's plate) · `gleam` (light on a raised top edge) · `lineBase` (what edges and washes are an alpha of) |
| Space | `s1 4` `s2 8` `s3 12` `s4 16` `s5 20` `s6 24` `s8 32` `s10 40` `s12 48` `s16 64` |
| Type | `tCap 10` `tFine 11` `tBody 13` `tLead 15` `tH3 18` `tH2 22` `tH1 30` `tHero 44` `tDisplay 52` · weights `wBody 420` `wMedium 520` `wSemi 620` `wBold 700` |
| Radii | `rXs 4` `rSm 6` `rMd 9` `rLg 14` `rXl 18`. Nested radii are concentric: inner = outer − padding |
| Control heights | `hSm 24` `hMd 28` `hLg 34` |
| Sheet widths | `sheetS 480` `sheetM 640` `sheetL 840` `sheetXl 1080` |
| Motion | `press 110` (a control answering) · `fast 120` (hover, colour) · `pop 150` (menus, tooltips) · `base 180` (sheets, toasts) · `exit 110` (anything leaving) · `slow 320` (entrances) · `stagger 45` |
| Motion, workspace | `ui 170` (tool options, inspector sections) · `cross 240` (cross-fades of the part) · `camera 420` · `part 300` (assembly parts travelling). `Motion.qml` only renames these for older code; use `Theme` |
| Easing (bezier points) | `easeOut` entering and answering · `easeMove` moving on screen · `easeDrawer` sliding panels |

`Theme.reduced` is read once at start from the OS "reduce motion" setting (or `FORM_REDUCED_MOTION=1`). Write movement so
it disappears when it is set: `Theme.move(ms)` → 0, `Theme.shift(px)` → 0, `Theme.from(scale)` → 1. Opacity and colour
still animate. Use the presets instead of spelling the curve out:

```qml
Behavior on scale { Glide { duration: Theme.press } }          // Glide = NumberAnimation with easeOut
Behavior on color { Tint {} }                                   // Tint  = ColorAnimation, Theme.fast
scale: pressed ? Theme.from(0.97) : 1                           // never from 0; never ease-in
```

Shortcuts are written the Qt way everywhere (`"Ctrl+Shift+O"`) and shown the platform's way by `Kbd` and
`Theme.keyText(seq)` (⇧⌘O on macOS).

## Components (all in the `Form` module; files in the same folder see each other without imports)

| Component | Use |
|---|---|
| `Txt { kind; mono; tone }` | all text. kind: `body fine cap lead h3 h2 h1 hero`. tone 1–4 = primary…muted |
| `Md { source }` | Markdown from an agent or a release note. Never `Text.MarkdownText`: Qt indents every list 40 px. `form/app/markdown.py` turns it into rich text with lists on the 8 px grid |
| `Icon { name; size; color }` | Lucide glyph; names are in `Icons.qml` (underscores: `"arrow_left"`) |
| `Btn { text; icon; kind; small; large; active; busy; tip; keys; onClicked }` | kind: `default primary quiet danger`. `busy` shows a spinner and ignores presses; `keys: "Ctrl+K"` adds the shortcut to the tooltip. Tab reaches it, Space/Enter press it |
| `Tag { text; kind }` | evidence / status chip; colour from `Theme.evidence(kind)` |
| `Sec { title; note; tag }` | titled group; children stack in a column, spacing 8 |
| `Cap { text; note; tag }` | caption line |
| `KV { k; sub; value; tag; first }` | key/value row; children go on the right instead of `value` |
| `Delta { label; from; to; unit; tint; tick }` | a change, from → to; `tick` counts a numeric `to` up from `start` over `Theme.cross` (set at once with reduced motion) |
| `Note { kind; title; text }` | kind: `plain amber red green blue`; children allowed |
| `Field { text; placeholder; numeric; unit; error; busy; bare; onAccepted(text); onEdited(text) }` | one-line input. `error: "Why it is wrong"` turns the edge red and shows the sentence under it; `bare` drops the well (palette) |
| `Area { text; placeholder; minLines; submitOnEnter; onSubmit(text); onBlurred(text) }` | multi-line input |
| `Beam { from; to; step; value; base; tint; onMoved(value) }` | slider |
| `Pick { model:[{value,text}]; value; onPicked(value) }` | dropdown (keyboard: Space/Down opens, arrows, Enter) |
| `Seg { model; value; onPicked(value) }` | segmented control: a choice among a few options inside a panel. The selection is one thumb that glides to a clicked option and lands at once for the keys |
| `Tabs { model:[{value,text,badge?}]; value; onPicked(value) }` | sections of a sheet or panel; the marker slides. Do not use `Seg` as tabs |
| `Check { checked; onToggled(checked) }` | checkbox: a choice confirmed later by a button |
| `Toggle { checked; onToggled(checked) }` | on/off switch: a setting that applies at once |
| `Pop { origin; … }` | a popover (`QtQuick.Controls.Popup`): grows from `origin` (`Popup.TopLeft`, `Popup.BottomLeft` …), shadow, Esc closes |
| `PopMenu { model:[{text,icon?,keys?,danger?,enabled?,checked?,run()} \| {sep:true}] }` | a menu; `open()` or `openAt(item, x, y)` for a right-click. Arrows, Enter, Esc |
| `Kbd { keys: "Ctrl+K"; quiet }` | shortcut hint as key caps |
| `Spinner { size; color }` · `Shadow { radius }` · `FocusRing { on; radius }` | indeterminate progress · drop shadow for a floating surface · keyboard focus ring |
| `ParamRow { p; prov }` | a recipe parameter bound to the draft; `prov: true` adds source and ±σ |
| `Tip { text; keys; show }` | tooltip, put inside the hovered item. After one has shown, its neighbours open without delay |
| `Viewport`, `MiniView { projectId; turning }` | 3D |
| `BuildLedger { label; at; of; running; pulse }` | the build's caption over the part: the feature arriving, "6 of 12", a progress hairline. The parent places and fades it |
| `Fold { title; note; tag; key; openByDefault }` | a section that folds. Its content fades and settles 6 px into place; its height is never animated |
| `Logo { size; mark; word }` | the Form Studio mark and wordmark as vectors in Theme colours (`size` = mark height: 12, 18, 24, 36). Never write the name as styled text; rules in `brand/README.md` |

`import "F.js" as F` gives `F.fmt(v, d)`, `F.trim(v, d)`, `F.pad(rev)` → `r04`, `F.dur(seconds)`, `F.ago(ts)`, `F.keys(o)`, `F.vals(o)`, `F.plural(n, word)`.
`import FormNative` gives `Bridge`: `Bridge.baseUrl`, `Bridge.save(apiPath, fileUrl) → bool`, `Bridge.downloads() → url`, `Bridge.reveal(fileUrl)`,
`Bridge.dataUrl(fileUrl) → "data:…"`, `Bridge.copy(text)`, `Bridge.openLink(url)`.

## Store (singleton) — what the old web bench called `S` and `A`

State: `Store.data` (project state: `.project .recipe .status .checks .fit .slice .exports .gate .approval .releases .calibration .actions .costs`),
`Store.project`, `Store.recipe`, `Store.head` (head revision: `.values .provenance .note .ts`), `Store.values` (head + draft),
`Store.view` (head geometry), `Store.preview` (draft geometry + impact), `Store.shown` (preview or view), `Store.studio` (`.env .projects .recipes .chat`),
`Store.slicer`, `Store.pid`, `Store.stage`, `Store.feature`, `Store.hasDraft`, `Store.draftValues`, `Store.draftProv`, `Store.job` ("" when idle),
`Store.ack` (array), `Store.compare` (`{rev, view, diff}`), `Store.layers` (`{count, z, types, n}`), `Store.sheet` (`{kind, props}`), `Store.viewer`.

Engine calls return Promises: `Store.pget(rest)`, `Store.ppost(rest, body)` (current project), `Store.get(path)`, `Store.post(path, body)`.
Errors are `{ message, hint }`; `Store.fail(e)` shows one as a toast. `Store.file(rest)` is an http URL for `Image.source`
(e.g. `Store.file("slice/current/plate_1.png")`); for downloads use `Bridge.save("/projects/" + Store.pid + "/file/…", fileUrl)` with a
`FileDialog { fileMode: FileDialog.SaveFile }` from `QtQuick.Dialogs`.

Actions: `refresh(withView)`, `setParam(key, value, immediate)`, `setProv(key, {source, sigma})`, `loadDraft(values, origin, note)`,
`discard()`, `commit()`, `checkout(n)`, `select(featureId)`, `hover(featureId)`, `run(nodes, force)`, `settings(body)`, `track(jobId)`,
`setStage(id)`, `setView(name)`, `setSection(axis, t)`, `setAck(id, on)`, `compareWith(n)`, `marker(check)`, `showLayers(on)`, `setLayer(n)`,
`openSheet(kind, props)` / `openSheet(null)`, `toast(msg, hint, bad)`, `spec(key)`, `featureById(id)`, `revision(n)`, `reloadStudio()`.

More shell state: `Store.talkWidth`, `Store.showImage(url, caption, note)` (the lightbox), `Store.renameProject(id, name)`,
`Store.duplicateProject(id)`, `Store.deleteProject(id)` (moves it to `.trash` in the projects folder).

## Sheets

A sheet is a `Column` in its own file, registered in `SheetHost.qml`'s `files` map and opened with `Store.openSheet(kind, props)`.
The host draws the header, the padding, the scrolling body with soft edges, and the action bar, so a sheet declares only:

```qml
Column {
    id: sh
    property string title: "Share card"
    property string note: "1600 × 900 PNG of r04"            // optional line under the title
    property int sheetWidth: Theme.sheetL                    // sheetS | sheetM | sheetL | sheetXl, nothing else
    readonly property var tabs: [{ value: "a", text: "First" }, { value: "b", text: "Second" }]   // optional; the host renders them
    property string tab: "a"
    property int sheetHeight: 520                            // optional: fixed body height so tabs do not make the card jump
    property Item firstFocus: name.input                     // optional: what has the keyboard when it opens
    function accept() { save() }                             // optional: Enter, when no field took it
    property Component footerLeft: Row { Btn { kind: "quiet"; text: "Open the folder" } }       // secondary, or one status line
    property Component footer: Row { spacing: 8              // primary LAST: it sits at the right edge
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { kind: "primary"; text: "Save"; busy: sh.saving; onClicked: sh.accept() } }
    spacing: 14                                              // no bottomPadding: the host pads
    …
}
```

Esc closes; Tab and Shift+Tab stay inside the sheet; it enters at scale 0.97 → 1 with a fade in 180 ms and leaves in 110 ms.

## The window

`Main.qml` remembers the window's place and size, the agent column's width (drag its edge; double-click resets) and the
recent palette commands, in the platform's settings store (`QtCore.Settings`). On macOS `MacMenu.qml` is the native menu
bar; elsewhere the same actions are in the top bar's menu button. A new command should be added in three places: its
button, `Palette.qml` (`add(group, id, icon, text, hint, run, keys)`), and `MacMenu.qml`.
`Shape.qml`, `DraftCard.qml` and `ParamRow.qml` are the reference for style and density.
