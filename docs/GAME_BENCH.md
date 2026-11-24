# Game bench

Six original game-asset briefs (tests/design_bench/game_briefs.json) and one deliberately bad control, made end to end (`python scripts/game_bench.py`) from the game exemplars in form/exemplars/game/, run 2026-11-24 on Darwin arm64 with Blender 5.2.3. Textures 1024 px, the fast bake. Every number below is from that run; failures are published as they came out. Budgets and thresholds are proposed values, not engine rules.

## Result

- Rubric (median of three blind passes, capped by the game evidence): 0 of 6 at 4.0 or more; 3 under 3.0; technical checks pass on 6 of 6.
- Control (Control: plain blob): rubric 1.12, fails the gate, as it must.
- Scored by: three blind passes by Claude subagents (an AI model), not a person (2026-11-24). Each pass saw only the seven anonymous review sheets (no names, briefs or numbers), in its own order; the letters were mapped back to briefs afterwards.

How it is measured:

- **Model**: the exemplar's model_mesh op list run in Blender's fixed runner (blocks, bevel, inset, panel_line, trim_strip, kit_place); ops tagged high_only build the bake source only. The remote is a kernel design (build123d).
- **Build**: the design created with the purpose "game" and built by the kernel; STEP exported and read back with OCCT.
- **SubD to CAD**: per connected cage part, the CAD patches against the Catmull-Clark limit surface (form/craft/subd_report.py); the worst part's max deviation per 100 mm of its size.
- **Game asset**: form/game (Blender bakes; the GLB is written and checked here): every validation check, LOD triangles against budgets (2% over passes).
- **Game evidence** (form/critique.game_evidence, computed; thresholds proposed): *bevel* coverage (share of LOD0's feature-edge length that is not a raw hard edge: bevelled in the mesh, or baked: the normal map leans >= 12 deg just inside it); *materials* (distinct kind and tint); *contrast* (base colour luminance p95 - p5 over LOD0); *scales* (primary: LOD3 shows more than one mass; secondary: LOD0 holds forms LOD3 drops; tertiary: the normal map carries surface detail); *silhouette* complexity (1 - mean solidity of LOD0's outline in four views); *wear* (a worn material and a lit curvature mask).
- **Rubric**: form/critique.py's eight items, 0-5. Three blind passes, each over the anonymous review sheets (four lit views of LOD0 and a 64 px outline, the seven assets shuffled, the control among them); each item is the median of the passes, capped by the game evidence. Gate: mean >= 4.0 and none under 3 (proposed).

| Brief | Route (expected) | Build | SubD→CAD max / 100 mm | Validation | LOD0..LOD3 tris / budget | Bevel | Mat. | Contrast | Scales | Silh. | Wear | Rubric |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Sci-fi helmet prop | subd_cage (subd_cage) | ok 3.6 s | 0.215 mm (0/2 exact) | PASS | 9950/10000 · 4974/5000 · 1990/2000 · 596/600 | 97% | 4 | 0.72 | 3/3 | 0.028 | yes | 3.00 FAIL |
| Stylised treasure chest | subd_cage (subd_cage) | ok 16.2 s | 1.4 mm (0/17 exact) | PASS | 11952/12000 · 5970/6000 · 2486/2500 · 796/800 | 94% | 3 | 0.28 | 3/3 | 0.018 | yes | 3.38 FAIL |
| Fantasy sword | subd_cage (subd_cage) | ok 5.2 s | 1.32 mm (0/5 exact) | PASS | 3342/4000 · 1990/2000 · 796/800 · 298/300 | 99% | 4 | 0.69 | 3/3 | 0.439 | yes | 3.25 FAIL |
| Modular wall kit piece | procedural (procedural) | ok 10.4 s | 0.103 mm (0/1 exact) | PASS | 7436/8000 · 2644/4000 · 1592/1600 · 496/500 | 93% | 3 | 0.25 | 3/3 | 0.052 | yes | 2.12 FAIL |
| Vehicle wheel | subd_cage (subd_cage) | ok 8.3 s | 1.23 mm (2/8 exact) | PASS | 5970/6000 · 2984/3000 · 1194/1200 · 496/500 | 97% | 4 | 0.58 | 3/3 | 0.061 | yes | 2.88 FAIL |
| Remote control, CAD plus asset | kernel (kernel) | ok 3.1 s | n/a (kernel) | PASS | 3980/4000 · 1990/2000 · 894/900 · 398/400 | 70% | 5 | 0.40 | 3/3 | 0.023 | yes | 2.94 FAIL |
| Control: plain blob (control) | — | ok 0.3 s | 0.0542 mm (0/1 exact) | PASS | 2984/3000 · 1492/1500 · 596/600 · 198/200 | 100% | 1 | 0.01 | 0/3 | 0.009 | no | 1.12 FAIL |

## Per brief

### Sci-fi helmet prop

- Originality: An original helmet built from generic hard-surface vocabulary (a recessed visor, cheek plates, a crest, vents, panel lines). It is no franchise's helmet: no character's visor shape, crest or markings were referenced; the proportions and layout were chosen here.
- Routes: shell → subd_cage; visor → subd_cage; cheeks → subd_cage; crest → subd_cage
- Model: 16 model_mesh ops (7 high_only) in 0.81 s.
- Cage: 586 points, 582 faces, 232 creased edges, regions cheek, crest, visor; bake source 1958 faces.
- SubD→CAD: 2 part(s), worst max 0.603 mm, RMS 0.0358 mm, 0.215 mm per 100 mm; 80 irregular point(s).
- STEP: valid, 1 solid(s), 267 faces, 1619 kB
- Game asset (unreal): 37.1 s, bake 22.5 s, size 238 x 290 x 263 mm, UVs smart, 2 collision hull(s).
- Checks: all PASS
  - LOD0: 9950 / 10000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 4974 / 5000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD2: 1990 / 2000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD3: 596 / 600 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 97% (59 mm raw hard edge of 1880 mm feature edge, 102 mm baked); materials 4 (painted_metal #34383d, painted_metal #b8492a, painted_metal #d8d3c6, plastic #141c24); value contrast 0.723; scales primary yes (2 LOD3 part(s), min solidity 0.9488), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02069, rg std 0.03673); silhouette complexity 0.0279 (front 0.9514, side 0.9738, top 0.9777, three_quarter 0.9856); wear yes (max 0.65, edge mask 1.3%).
- Rubric: silhouette 3.0 (passes 3/3/2), proportion 3.0 (passes 3/3/3), continuity 3.0 (passes 3/3/3), radius_hierarchy 3.0 (passes 4/3/3), break_up 3.5 (passes 3/4/4), detail_rhythm 3.0 (passes 2/3/3), material 3.0 (passes 3/3/3), would_sell 2.5 (passes 2/2/2); mean 3.00
- Blind pass 1 said: Sci-fi helmet with visor, crest fin and orange vent pods: the main mass is a blobby rounded cube, the visor edges are jagged, and the crest fin floats loosely on top.
- Blind pass 2 said: Sci-fi helmet with a visor, orange cheek vents and a top fin; the shell is a lumpy box-egg, the visor and window cuts have jagged edges, and it reads as a blob at 64 px.
- Blind pass 3 said: Retro sci-fi helmet with a visor, orange vented side plates and a crest fin; the boxy shell collapses to a blob at 64 px, and the visor and window edges are jagged and noisy.
- Wall time 55.5 s.

### Stylised treasure chest

- Originality: An original chest built from generic woodworking and hardware vocabulary (boarded body, barrel lid, riveted strap iron, a draw latch). It copies no game, film or brand prop; the proportions, plank count and hardware layout were chosen here.
- Routes: body → subd_cage; lid → subd_cage; straps → procedural; lock → subd_cage
- Model: 19 model_mesh ops (11 high_only) in 1.13 s.
- Cage: 1528 points, 1494 faces, 700 creased edges, regions gold, iron, lockface; bake source 2802 faces.
- SubD→CAD: 17 part(s), worst max 8.09 mm, RMS 0.283 mm, 1.4 mm per 100 mm; 520 irregular point(s).
- STEP: valid, 1 solid(s), 918 faces, 8353 kB
- Game asset (unreal): 33.1 s, bake 9.7 s, size 614 x 407 x 451 mm, UVs smart, 16 collision hull(s).
- Checks: all PASS
  - LOD0: 11952 / 12000 triangles, cage level 1 (clean quads)
  - LOD1: 5970 / 6000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 2486 / 2500 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 796 / 800 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 94% (1746 mm raw hard edge of 28194 mm feature edge, 1529 mm baked); materials 3 (bare_metal #3e3c3a, bare_metal #c9982f, wood #8a5a32); value contrast 0.277; scales primary yes (17 LOD3 part(s), min solidity 0.9647), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02219, rg std 0.05223); silhouette complexity 0.0185 (front 0.9757, side 0.9881, top 0.9928, three_quarter 0.9693); wear yes (max 0.75, edge mask 2.6%).
- Rubric: silhouette 3.5 (passes 4/4/4), proportion 3.5 (passes 4/4/4), continuity 3.5 (passes 4/4/4), radius_hierarchy 3.0 (passes 3/3/3), break_up 4.0 (passes 4/4/4), detail_rhythm 3.5 (passes 3/4/4), material 3.0 (passes 3/4/3), would_sell 3.0 (passes 3/4/3); mean 3.38
- Blind pass 1 said: Domed treasure chest with metal bands, base trim and lock plate: the silhouette is classic, but the wood grain is a noisy procedural swirl, the back and sides have no detail, and the lock is crude.
- Blind pass 2 said: Banded wooden treasure chest with plank seams, riveted iron straps, a lock plate and a base trim; it is solid, but the wood grain is a busy stylised pattern and the planks and edges are too clean, with no wear.
- Blind pass 3 said: Domed treasure chest with riveted iron bands, a lock plate, plank seams and a metal base trim; the wood grain is a noisy procedural ring pattern that reads synthetic, and the hard edges carry little bevel or wear.
- Wall time 106.7 s.

### Fantasy sword

- Originality: An original arming-sword shape from generic sword anatomy (fuller, ground edges, a swept guard, a wrapped grip, a faceted pommel). It reproduces no named weapon from a game, film or book.
- Routes: blade → subd_cage; guard → subd_cage; grip → subd_cage; pommel → subd_cage
- Model: 11 model_mesh ops (1 high_only) in 0.65 s.
- Cage: 640 points, 626 faces, 378 creased edges, regions blade, fuller, grip, guard, pommel; bake source 1706 faces.
- SubD→CAD: 5 part(s), worst max 0.766 mm, RMS 0.0377 mm, 1.32 mm per 100 mm; 136 irregular point(s).
- STEP: valid, 1 solid(s), 482 faces, 3409 kB
- Game asset (gltf): 16.1 s, bake 5.2 s, size 260 x 46 x 1048 mm, UVs smart, 5 collision hull(s).
- Checks: all PASS
  - LOD0: 3342 / 4000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD1: 1990 / 2000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 796 / 800 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 298 / 300 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 99% (158 mm raw hard edge of 11700 mm feature edge, 887 mm baked); materials 4 (bare_metal #a27c38, brushed_metal #8f969d, brushed_metal #c4c9cf, leather #3f2517); value contrast 0.688; scales primary yes (5 LOD3 part(s), min solidity 0.3965), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02489, rg std 0.06673); silhouette complexity 0.4392 (front 0.4036, side 0.5838, top 0.8352, three_quarter 0.4207); wear yes (max 0.6, edge mask 17.4%).
- Rubric: silhouette 4.0 (passes 4/4/4), proportion 3.5 (passes 3/4/4) [cap 4: Bounding ratios are not near a classic ratio: long:mid 4.031, mid:short 5.599.], continuity 3.5 (passes 3/4/4), radius_hierarchy 3.0 (passes 2/3/3), break_up 3.0 (passes 3/3/4), detail_rhythm 3.0 (passes 3/3/4), material 3.0 (passes 3/3/3), would_sell 3.0 (passes 2/3/4); mean 3.25
- Blind pass 1 said: Longsword with fuller, curved brass guard, wrapped grip and round pommel: the blade is very long against a short grip, edges and fuller are simple, and the guard texture is flat.
- Blind pass 2 said: Longsword with a fuller, brass crossguard, wrapped grip and pommel; the silhouette is clear, but materials are flat and clean with no wear, and the guard and pommel lack secondary detail.
- Blind pass 3 said: Classic longsword with a strong, readable silhouette, a fuller, a brass crossguard, a wrapped grip and a pommel; the guard and pommel are simple primitives, and the materials are clean with no wear or edge character.
- Wall time 45.1 s.

### Modular wall kit piece

- Originality: An original modular wall built from generic masonry (stretcher-bond brick, plinth, coping). Sizes follow a 0.5 m kit grid chosen here; it copies no game's kit.
- Routes: wall → kernel; bricks → procedural; trim → procedural
- Model: 19 model_mesh ops (3 high_only) in 0.97 s.
- Cage: 966 points, 895 faces, 560 creased edges, regions brick, cells, coping_b, coping_f, plinth_b, plinth_f, sunk, trim; bake source 1587 faces.
- SubD→CAD: 1 part(s), worst max 2.47 mm, RMS 0.0233 mm, 0.103 mm per 100 mm; 351 irregular point(s).
- STEP: valid, 1 solid(s), 1344 faces, 7421 kB
- Game asset (godot): 23.9 s, bake 12.5 s, size 2000 x 330 x 2400 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 7436 / 8000 triangles, cage level 1 (clean quads)
  - LOD1: 2644 / 4000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 1592 / 1600 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 496 / 500 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 93% (1241 mm raw hard edge of 18605 mm feature edge, 2176 mm baked); materials 3 (stone #6f6c66, stone #8c4f38, stone #9a958c); value contrast 0.25; scales primary yes (1 LOD3 part(s), min solidity 0.8425), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.06812, rg std 0.06685); silhouette complexity 0.0518 (front 1.0, side 0.8132, top 1.0, three_quarter 0.9797); wear yes (max 0.65, edge mask 2.8%).
- Rubric: silhouette 1.5 (passes 2/2/2), proportion 3.0 (passes 3/3/2) [cap 4: Bounding ratios are not near a classic ratio: mid:short 6.061.], continuity 2.5 (passes 2/2/2), radius_hierarchy 2.0 (passes 2/2/2), break_up 2.5 (passes 2/2/2), detail_rhythm 2.0 (passes 2/2/2), material 2.0 (passes 2/2/2), would_sell 1.5 (passes 2/2/2); mean 2.12
- Blind pass 1 said: Brick wall panel with stone caps: it is a flat slab whose bricks are uniform painted ovals, the back is blank, and the side shows gaps.
- Blind pass 2 said: Brick wall segment with stone caps; it reads as a flat slab, with cartoony pill-shaped bricks painted on the front only, a blank untextured back and raw unbevelled edges.
- Blind pass 3 said: Brick wall panel with stone cap and base trims; the bricks are puffy cartoon blobs with uniform rhythm, the back is a blank flat slab, and the outline is just a rectangle.
- Wall time 70.1 s.

### Vehicle wheel

- Originality: An original off-road wheel (lug tread, five-spoke rim, hub with lug nuts) from generic wheel anatomy. No maker's rim design, tread pattern, logo or lettering.
- Routes: tyre → subd_cage; rim → subd_cage; spokes → procedural; hub → kernel
- Model: 8 model_mesh ops (2 high_only) in 0.68 s.
- Cage: 1470 points, 1458 faces, 704 creased edges, regions hub, rim, tyre; bake source 2138 faces.
- SubD→CAD: 8 part(s), worst max 1.59 mm, RMS 0.0666 mm, 1.23 mm per 100 mm; 168 irregular point(s).
- STEP: valid, 1 solid(s), 631 faces, 4970 kB
- Game asset (unity): 34.5 s, bake 14.5 s, size 664 x 240 x 664 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 5970 / 6000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD1: 2984 / 3000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 1194 / 1200 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 496 / 500 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 97% (694 mm raw hard edge of 22653 mm feature edge, 862 mm baked); materials 4 (bare_metal #6e7277, bare_metal #8d9196, painted_metal #b4b9be, rubber #242424); value contrast 0.582; scales primary yes (8 LOD3 part(s), min solidity 0.7876), secondary yes (8.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02692, rg std 0.05704); silhouette complexity 0.061 (front 0.7901, side 0.9968, top 0.9975, three_quarter 0.9716); wear yes (max 0.6, edge mask 2.0%).
- Rubric: silhouette 3.0 (passes 3/3/3), proportion 3.5 (passes 4/4/4), continuity 3.0 (passes 4/2/3), radius_hierarchy 3.0 (passes 4/3/3), break_up 3.0 (passes 3/3/3), detail_rhythm 2.5 (passes 3/2/2), material 2.5 (passes 3/2/2), would_sell 2.5 (passes 3/2/2); mean 2.88
- Blind pass 1 said: Wheel with tyre and five-spoke rim: it reads clearly, but the tread is scattered square blocks instead of a patterned rhythm, and the rim and hub are plain flat grey.
- Blind pass 2 said: Car wheel with a five-spoke rim and hub; the tread blocks are scattered, artifact-like tiles with no consistent pattern, and the rim and tire materials are flat.
- Blind pass 3 said: Five-spoke wheel and tyre with a solid rim and hub; the tread blocks are crude, noisy rectangles that also bleed onto the sidewall, and the rubber and metal are flat with no wear.
- Wall time 81.5 s.

### Remote control, CAD plus asset

- Originality: A generic TV remote laid out from common remote anatomy (power, navigation pad, rockers, number grid). No maker's shape, logo or button legend.
- Routes: body → subd_cage; buttons → kernel; battery_cover → kernel
- STEP: valid, 1 solid(s), 162 faces, 530 kB
- Game asset (gltf): 19.1 s, bake 10.8 s, size 190 x 50 x 23 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 3980 / 4000 triangles, decimated to the budget (automatic retopology)
  - LOD1: 1990 / 2000 triangles, decimated to the budget (automatic retopology)
  - LOD2: 894 / 900 triangles, decimated to the budget (automatic retopology)
  - LOD3: 398 / 400 triangles, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 70% (1183 mm raw hard edge of 3966 mm feature edge, 1880 mm baked); materials 5 (plastic #0b0d10, plastic #2b2e33, plastic #c7ccd2, rubber #8a9099, rubber #c23a2b); value contrast 0.403; scales primary yes (1 LOD3 part(s), min solidity 0.9274), secondary yes (18.6% of LOD0 off LOD3), tertiary yes (normal blue std 0.02217, rg std 0.05451); silhouette complexity 0.0234 (front 0.9696, side 0.9937, top 0.9973, three_quarter 0.9459); wear yes (max 0.45, edge mask 1.7%).
- Rubric: silhouette 2.0 (passes 2/2/2), proportion 3.5 (passes 4/4/4) [cap 4: Bounding ratios are not near a classic ratio: long:mid 3.8.], continuity 3.5 (passes 4/4/4), radius_hierarchy 3.5 (passes 4/4/4) [cap 4: Bevel coverage 70%: 1183 mm of raw hard edge in LOD0 of 3966 mm of feature edge (bevel it, or bevel it high_only so the bake rounds it).], break_up 3.0 (passes 3/3/3), detail_rhythm 3.0 (passes 3/3/3), material 2.5 (passes 2/3/2), would_sell 2.5 (passes 2/2/2); mean 2.94
- Blind pass 1 said: TV remote with buttons, D-pad and red power key: it is a generic rounded slab with a flat, low-contrast material, and one end cap shows white stretched shading.
- Blind pass 2 said: TV remote with a button grid, D-pad and red power key; the body is a generic rounded bar, buttons are uniform blobs, and the plastic material is plain.
- Blind pass 3 said: TV remote with a clean, softly rounded body and a believable button layout; it reads as a plain slab at 64 px, the top texture shifts from dark plastic to brushed silver between views, and it shows no wear.
- Wall time 31.2 s.

### Control: plain blob (control)

- Originality: A deliberately bad control (an egg in one grey material); not a design.
- Cage: 56 points, 54 faces, 0 creased edges, regions none; bake source none (the cage itself).
- SubD→CAD: 1 part(s), worst max 0.163 mm, RMS 0.0419 mm, 0.0542 mm per 100 mm; 8 irregular point(s).
- STEP: valid, 1 solid(s), 35 faces, 192 kB
- Game asset (gltf): 16.0 s, bake 10.1 s, size 254 x 195 x 302 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 2984 / 3000 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD1: 1492 / 1500 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD2: 596 / 600 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD3: 198 / 200 triangles, cage level 2, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 100% (0 mm raw hard edge of 0 mm feature edge, 0 mm baked); materials 1 (plastic #9a9893); value contrast 0.008; scales primary no (1 LOD3 part(s), min solidity 0.9832), secondary no (20.0% of LOD0 off LOD3), tertiary no (normal blue std 0.0, rg std 0.00329); silhouette complexity 0.0094 (front 0.9911, side 0.9905, top 0.9898, three_quarter 0.9911); wear no (max 0.0, edge mask 0.0%).
- Rubric: silhouette 0.5 (passes 0/0/1), proportion 2.0 (passes 1/2/2), continuity 3.0 (passes 2/3/4), radius_hierarchy 2.0 (passes 1/2/2), break_up 0.0 (passes 0/0/0) [cap 3: No secondary forms: LOD0 has no panel, bevel, trim or part that LOD3 drops.], detail_rhythm 0.0 (passes 0/0/0) [cap 2: One detail scale or none (none): missing primary, secondary, tertiary.], material 1.0 (passes 0/1/1) [cap 1: One material over everything; value contrast 0.01 (under 0.08: it reads as one flat tone); no edge wear.], would_sell 0.5 (passes 0/0/0); mean 1.12
- Blind pass 1 said: A featureless grey egg or pebble blob: it has no recognisable function, no surface breaks, no detail and no material definition.
- Blind pass 2 said: Featureless grey pebble or egg blob with no surface breaks, detail or material definition, so it does not read as a designed prop.
- Blind pass 3 said: Featureless smooth pebble or egg blob with no surface detail, no material definition and no identifiable function.
- Wall time 21.8 s.

## What failed

Technical: nothing failed.
Rubric: below the gate: Sci-fi helmet prop, Stylised treasure chest, Fantasy sword, Modular wall kit piece, Vehicle wheel, Remote control, CAD plus asset.
See each brief above for the measured reason.
