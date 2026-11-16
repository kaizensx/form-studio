# Pictures the site still needs

Every picture on the site today comes from `docs/screenshots/app-*.jpg` (FORM 10). The slots below show an older
picture until a newer one exists. To fill a slot: take the screenshot with `python -m form.app --shot ...` at
1800 × 1160, add a crop for it to `CROPS` in `site/tools/make_assets.py`, run that script, and change the `src`
(and `width`/`height`, `alt`) of the `<img>` named below in `site/index.html`. Keep the copy true to what the
picture shows.

| Slot (`data-slot` or section) | Shows today | Wanted | Copy to revisit |
|---|---|---|---|
| `print-simulation` (section "See the print before you print it", left) | `shots/layers.webp`: the slice layer viewer, layer 4 of 127 | The print simulation playing: nozzle position, layer counter, time elapsed. About 876 × 760 visible. | The h3 "The slice, layer by layer" and its paragraph describe only the layer viewer. |
| `analysis-map` (same section, right) | `shots/checks.webp`: the checks list | A wall-thickness or overhang map drawn on the model, with its legend. About 500 × 660 visible. | The h3 "Checks on the real solid" does not mention maps yet. Add one sentence once the feature ships. |
| Pipeline → Describe (`#p-describe`) | `shots/conversation.webp`: cropped by hand from the conversations workstream's `.dev/final-conversation.png` (not in `docs/screenshots` yet) | The same screenshot committed under `docs/screenshots/`, plus a crop in `make_assets.py`; ideally with the conversation list open. | The panel text does not mention history, search, rename or pin. Add when the picture shows them. |
| Section "One window" (`shots/app.webp`, `shots/app-m.webp`) | FORM 10 window | The FORM 11 window, same state (a blue uncommitted draft with its consequences). | The three notes under the picture. |
| Section "Parts that go together" (`shots/assembly.webp`) | Hinged box, assembled | The same box exploded, or mid-swing with the hinge slider moved. | None. |
| Works with (`shots/render.webp`) | Render sheet, dark scene | A finished photoreal render if the renderer changes. | The caption must keep saying it is an illustration, not a photo of a print. |
| First-run setup (not on the page yet) | — | The welcome screen that finds and installs the kernel, slicer and agent from inside the app. | The works-with intro says "sets up only what you tick"; a picture would go under the table. |

## Not pictures

- **Hero models** (`assets/parts/*.bin`) are exported by `site/tools/export_parts.py` from the sample projects in
  `.dev/data`. Run it again after a recipe changes. Each step is one kernel build; the page says so, so keep it true.
- **Poster and social card** (`assets/hero-poster*.webp`, `assets/og.png`) are screenshots of the hero itself
  (`index.html?still` stops the slow orbit). Retake them if the hero changes.
- **Download cards** read the latest published release from GitHub's API. Until a release with the four
  `FORM-*.zip`/`.tar.gz` assets is published (not a draft), the cards link to the releases page and say so.
