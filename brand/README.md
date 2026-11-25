# Form Studio brand

The mark is the letter F drawn as a coordinate frame. The top arm is X, the stem is Y, and the square where they
meet is the origin, in the datum colour. Every part Form Studio builds is measured from that origin. The mark sits
next to the wordmark "Form Studio": "Form" is set heavier and "Studio" lighter.

This direction (option 1, "Frame") was chosen from six. The other five, with their sheets, are kept in
[`options/`](options/) for reference ([`options/overview.png`](options/overview.png)).

## Files

| File | Use |
|---|---|
| `lockup.svg` | Mark + wordmark, for graphite and other dark backgrounds. **The primary logo.** |
| `lockup-light.svg` | The same for white and light backgrounds |
| `lockup-mono.svg` | One colour (graphite), for print, engraving, embossing, single-colour stickers |
| `mark.svg` | The mark alone, 24 px and up |
| `mark-32.svg` | The mark tuned for 32 px and below: no hairline cut |
| `mark-mono.svg` | The mark in one colour; the hairline cut keeps the origin readable without colour |
| `wordmark.svg`, `wordmark-light.svg` | "Form Studio" alone, when the mark is already on screen |
| `icon.svg` | The app icon (macOS grid: 824 px body in a 1024 px canvas) |
| `build.py` | Builds all of the above, plus the app icons, the web icons, `og.png` and the outlines the app draws |
| `og-part.png` | A real build (the hero helmet, rendered by scripts/media/showcase), used on the right of `site/assets/og.png` |

Rebuild everything with `.venv/bin/python brand/build.py` (it needs `skia-pathops` and `fonttools` in the dev
environment, and macOS for `iconutil`). Never edit an output by hand: change `build.py` or `options/build.py`
(where the geometry lives) and rebuild.

Outputs outside `brand/`: `form/app/assets/icon.{svg,png,icns,ico}` and `icon-{16…512}.png`,
`form/app/qml/Form/LogoPaths.js` (drawn by `Logo.qml`), `site/assets/{favicon.svg,favicon.png,apple-touch-icon.png,
icon-192.png,icon-512.png,og.png}` and `site/favicon.ico`.

## Geometry

The mark is drawn on a 64-unit grid, where 4 units equal 1 px at 16 px. The F spans 40 × 48 units. The stroke is
12 units. The origin is a 12 × 12 square. The middle arm is 20 units long. A 2-unit hairline separates the origin
from the rest of the F. It is dropped below 24 px, where it would only blur.

In the lockup, the mark is 1.5 × the wordmark's cap height and is centred on the cap height. The gap between mark
and wordmark is 0.42 × the mark's height.

## Clear space and minimum size

- **Clear space:** keep the height of the origin square (¼ of the mark's height) empty on every side of the mark
  or the lockup. Nothing else enters that space: text, edges, other logos.
- **Minimum size:** the lockup is 18 px tall on screen and 6 mm in print. The mark alone is 16 px, using
  `mark-32.svg` below 32 px. Below 16 px, use the app icon or nothing.
- **In the app:** `Logo { size: 18 }` in the top bar, `24` on first run and in About, `36` on the start screen.
  A multiple of 12 puts every edge on a whole pixel at 1×. A multiple of 6 does the same at 2×.

## Colours

These are the app's own tokens (`form/app/qml/Form/Theme.qml`).

| Role | On graphite | On white |
|---|---|---|
| Background | Plate `#0e1113` | White `#ffffff` |
| The F (the part) | Clay `#d8d3c8` | Graphite `#0e1113` |
| The origin | Datum `#b9e8d7` | Datum, dark `#2f8a6c` |
| "Form" | Ink `#e8edeb` | Graphite `#0e1113` |
| "Studio" | Ink 2 `#a8b2af` | `#5b6562` |
| One colour | Graphite `#0e1113`, or white on a dark photo | |

The datum mint is the only accent. It marks the origin and nothing else in the logo.

## Type

The wordmark is **Instrument Sans**: "Form" at weight 640 and "Studio" at weight 420. It uses the font's own
kerning and no added tracking. The letters are converted to outlines (shaped by Qt, with overlaps merged by
skia-pathops), so the files need no font and render the same everywhere. Instrument Sans is also the interface
typeface.

The licence is the **SIL Open Font License 1.1**, © 2022 The Instrument Sans Project Authors
(`form/app/assets/fonts/InstrumentSans-LICENSE.txt`). The OFL allows the font to be used, embedded and
redistributed in any project, open source or commercial. It may not be sold on its own. Logo artwork made from it
is not covered by the OFL and is MIT, like the rest of this repository. Geist Mono, used by option 5 in
`options/`, is also under the OFL.

## Do

- Use `lockup.svg` on graphite wherever there is room. Use the mark alone where the name is already visible
  (title bar, app icon, favicon, avatar).
- Keep the two-tone F: clay part, mint origin. In one colour, use the `-mono` files, which keep the hairline cut.
- Write the name "Form Studio" in text, in sentence case, as two words.

## Don't

- Don't stretch, rotate, outline, add shadows to or put a gradient on the lockup or the mark. The app icon's soft
  light is part of the icon only.
- Don't recolour the origin with anything other than the datum mint (or its dark version on white), and don't
  colour any other part of the F mint.
- Don't re-typeset the wordmark in another font or weight, and don't set it in capitals ("FORM STUDIO") or as one
  word.
- Don't put the mark inside another shape, except the app icon squircle and the favicon tile.
- Don't place the light lockup on graphite or the dark lockup on white.

## What keeps the old name

The command `form`, the Python package, `FORM_*` environment variables, the data folder `~/FORM`, the release
assets (`FORM-macos-arm64.zip` …) and the bundle and executable names (`FORM.app`, `FORM.exe`) stay as they are, so
updates, CI and existing installs keep working. The macOS bundle shows "Form Studio" through `CFBundleName` and
`CFBundleDisplayName` in `packaging/form.spec`.
