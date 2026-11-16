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
- Animate only `opacity`, `scale`, `x`/`y`, colour. 120–320 ms, `Easing.OutCubic`. Nothing that is used all day animates.

## Components (all in the `Form` module; files in the same folder see each other without imports)

| Component | Use |
|---|---|
| `Txt { kind; mono; tone }` | all text. kind: `body fine cap lead h3 h2 h1 hero`. tone 1–4 = primary…muted |
| `Icon { name; size; color }` | Lucide glyph; names are in `Icons.qml` (underscores: `"arrow_left"`) |
| `Btn { text; icon; kind; small; active; tip; onClicked }` | kind: `default primary quiet danger` |
| `Tag { text; kind }` | evidence / status chip; colour from `Theme.evidence(kind)` |
| `Sec { title; note; tag }` | titled group; children stack in a column, spacing 8 |
| `Cap { text; note; tag }` | caption line |
| `KV { k; sub; value; tag; first }` | key/value row; children go on the right instead of `value` |
| `Delta { label; from; to; unit; tint }` | a change, from → to |
| `Note { kind; title; text }` | kind: `plain amber red green blue`; children allowed |
| `Field { text; placeholder; numeric; unit; onAccepted(text); onEdited(text) }` | one-line input |
| `Area { text; placeholder; minLines; submitOnEnter; onSubmit(text); onBlurred(text) }` | multi-line input |
| `Beam { from; to; step; value; base; tint; onMoved(value) }` | slider |
| `Pick { model:[{value,text}]; value; onPicked(value) }` | dropdown |
| `Seg { model; value; onPicked(value) }` | segmented control |
| `Check { checked; onToggled(checked) }` | checkbox |
| `ParamRow { p; prov }` | a recipe parameter bound to the draft; `prov: true` adds source and ±σ |
| `Tip { text; show }` | tooltip, put inside the hovered item |
| `Viewport`, `MiniView { projectId; turning }` | 3D |

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

A sheet is a `Column` with `property string title` and `property int sheetWidth`; register its file name in `SheetHost.qml`'s `files` map.
`Shape.qml`, `DraftCard.qml` and `ParamRow.qml` are the reference for style and density.
