# Showcase pictures

The product pictures on the website (`site/assets/shots/`), in the README (`docs/readme/hero-render.jpg`,
`made-*.jpg`) and on the social card (`brand/og-part.png`) are made here, from designs in this repository. Nothing is
drawn by hand: each picture is a build of the engine, rendered.

| Script | What it makes |
|---|---|
| `product_shots.py` | Blender renders of exemplars with the app's own scene and materials, listed in `shots.json` |
| `refine_shots.py` | A project before and after automatic refinement; `refine_shots.json` photographs its two revisions |
| `game_shots.py` | Game assets from the game exemplars (GLB with baked textures), then a hero render and the LOD ladder |
| `recon_shots.py` | Mesh to editable CAD on a synthetic fixture: the mesh and the result, drawn by the headless renderer |
| `encode.py` | Crops and encodes the chosen renders into the site, the README and the social card |

Run from the repository root. Scratch (projects, renders) goes to `.dev/showcase/`, which git ignores. Blender must
be installed; the game assets and the reconstruction take a few minutes each.

```
.venv/bin/python scripts/media/showcase/product_shots.py
.venv/bin/python scripts/media/showcase/refine_shots.py screw_post_enclosure
SHOWCASE_DATA=.dev/showcase/refine-data .venv/bin/python scripts/media/showcase/product_shots.py scripts/media/showcase/refine_shots.json
.venv/bin/python scripts/media/showcase/game_shots.py make treasure_chest vehicle_wheel
.venv/bin/python scripts/media/showcase/game_shots.py shoot treasure_chest 35 18 hero 1600 1200 128
.venv/bin/python scripts/media/showcase/game_shots.py shoot treasure_chest 14 16 ladder 2400 800 96
.venv/bin/python scripts/media/showcase/game_shots.py shoot vehicle_wheel 35 14 hero 1600 1200 128
.venv/bin/python scripts/media/showcase/recon_shots.py stepped_bracket -55 28
.venv/bin/python scripts/media/showcase/encode.py
QT_QPA_PLATFORM=offscreen .venv/bin/python brand/build.py     # site/assets/og.png from brand/og-part.png
```

Rules for these pictures:

- Only designs in this repository: exemplars (`form/exemplars/`), `scripts/readme_designs/` and the synthetic parts of
  `tests/recon_fixtures.py`. Never a file of your own.
- A render is an illustration: invented light and material on real geometry. The page says what was built, and every
  number beside a picture (parts, triangles, dimensions, seconds) is printed by the script that made it. When a
  number changes, change the page.
- Several parts are photographed assembled or exploded, placed by the design's own `assembly()`; colours come from
  its `appearance()`. Where a design declares none, the shot list names the finish and colour, and that is a choice
  made here, not the design's.
- The drawn app on the website is not a picture: its data comes from `site/tools/export_site_data.py`.
