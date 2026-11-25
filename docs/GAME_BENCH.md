# Game bench

Six original game-asset briefs (tests/design_bench/game_briefs.json) and one deliberately bad control, made end to end from the game exemplars in form/exemplars/game/, twice: with design refinement off (the exemplar as written) and on (form/refine: cage and material operators, a quick bake of every candidate, one full bake checked at the end, the asset made from the refined head). Run 2026-11-25 on Darwin arm64 with Blender 5.2.3. Every number below is from those runs; failures are published as they came out. Budgets and thresholds are proposed values, not engine rules.

## Result

- Rubric with refinement on (median of three new blind passes, capped by the game evidence): 0 of 6 at 4.0 or more (gate: at least 5 of 6): **FAIL**.
- Control: fails the gate, as it must: **pass**.
- Technical checks pass on 6 of 6 with refinement on, 6 of 6 off.
- Scored by: three blind passes by Claude subagents (an AI model), not a person (2026-11-25). Three new blind passes by Claude subagents (an AI model), not a person, on 2026-11-25. Each pass saw only fourteen anonymous review sheets (LOD0 lit from four views and its 64 px outline): the seven assets of the refinement-on run and the seven of the refinement-off run, shuffled together with a fixed seed, the control among them, no names, briefs, numbers or key; each pass read them in its own order. The letters were mapped back to run and brief afterwards. One earlier third pass was discarded unused because it filed two sheets under each other's letters (its notes describe a wheel under a chest's letter and the reverse); a new third pass replaced it. The rubric is a model's judgement of rendered sheets, not a person's and not a measurement.
- The off column's rubric is game_scores.json: the same blind passes (the sheets of both runs were scored together, shuffled).

| Brief | Validation off / on | LOD0 tris off / on | Bevel off / on | Contrast off / on | Wear off / on | Rubric off | Rubric on | Refinement (kept) |
|---|---|---|---|---|---|---|---|---|
| Sci-fi helmet prop | PASS / PASS | 9950 / 9950 | 100% / 100% | 0.719 / 0.719 | 3.1% / 3.1% | 2.88 FAIL | 2.88 FAIL | 50.2 s: no step gains 2 % |
| Stylised treasure chest | PASS / PASS | 11952 / 11952 | 94% / 94% | 0.268 / 0.268 | 5.1% / 5.1% | 3.38 FAIL | 3.38 FAIL | 15.0 s: no operator applies |
| Fantasy sword | PASS / PASS | 3980 / 3980 | 99% / 99% | 0.687 / 0.687 | 12.7% / 12.7% | 3.25 FAIL | 3.25 FAIL | 47.0 s: no step gains 2 % |
| Modular wall kit piece | PASS / PASS | 7436 / 7756 | 92% / 93% | 0.332 / 0.328 | 8.1% / 8.4% | 2.81 FAIL | 2.81 FAIL | 100.5 s: Silhouette breaker |
| Vehicle wheel | PASS / PASS | 5970 / 5970 | 97% / 97% | 0.582 / 0.582 | 5.5% / 5.5% | 3.38 FAIL | 3.38 FAIL | 17.6 s: no operator applies |
| Remote control, CAD plus asset | PASS / PASS | 3980 / 3980 | 67% / 67% | 0.411 / 0.411 | 4.1% / 4.1% | 3.12 FAIL | 3.12 FAIL | 3.1 s: no operator applies |
| Control: plain blob (control) | PASS / PASS | 2984 / 2984 | 100% / 100% | 0.008 / 0.008 | 0.0% / 0.0% | 0.69 FAIL | 0.69 FAIL | 6.5 s: no operator applies |

## Refinement per brief

- **Sci-fi helmet prop**: deficit 0.0199 → 0.0199, 50.2 s, stopped: no step gains 2 %; kept: nothing; rejected: kit_place (game: validator fails: LOD3 has no flipped faces); panel_line (game: validator fails: LOD0 is closed and manifold, LOD0 has no flipped faces, LOD1 is closed and manifold, LOD1 has no flipped faces)
- **Stylised treasure chest**: deficit 0.1467 → 0.1467, 15.0 s, stopped: no operator applies; kept: nothing
- **Fantasy sword**: deficit 0.2192 → 0.2192, 47.0 s, stopped: no step gains 2 %; kept: nothing; rejected: kit_place (game: validator fails: LOD3 has no flipped faces); crisp_regions (game: validator fails: LOD0 is closed and manifold, LOD1 is closed and manifold, LOD1 has no flipped faces, LOD2 is closed and manifold); panel_line (game: validator fails: LOD0 is closed and manifold, LOD0 has no flipped faces, LOD1 is closed and manifold, LOD1 has no flipped faces)
- **Modular wall kit piece**: deficit 0.2229 → 0.1912, 100.5 s, stopped: no operator applies; kept: Silhouette breaker (The coping_b region pushed out 19.8 mm along its normal, its seat creased, breaks the plainest view's outline.); rejected: inset (game: validator fails: LOD0's baked normals face out of the surface)
- **Vehicle wheel**: deficit 0.0613 → 0.0613, 17.6 s, stopped: no operator applies; kept: nothing
- **Remote control, CAD plus asset**: deficit 0.2405 → 0.2405, 3.1 s, stopped: no operator applies; kept: nothing
- **Control: plain blob**: deficit 0.3799 → 0.3799, 6.5 s, stopped: no operator applies; kept: nothing

## Refinement on: every number

How it is measured:

- **Model**: the exemplar's model_mesh op list run in Blender's fixed runner (blocks, bevel, inset, panel_line, trim_strip, kit_place); ops tagged high_only build the bake source only. The remote is a kernel design (build123d).
- **Build**: the design created with the purpose "game" and built by the kernel; STEP exported and read back with OCCT.
- **SubD to CAD**: per connected cage part, the CAD patches against the Catmull-Clark limit surface (form/craft/subd_report.py); the worst part's max deviation per 100 mm of its size.
- **Game asset**: form/game (Blender bakes; the GLB is written and checked here): every validation check, LOD triangles against budgets (2% over passes).
- **Game evidence** (form/critique.game_evidence, computed; thresholds proposed): *bevel* coverage (share of LOD0's feature-edge length that is not a raw hard edge: bevelled in the mesh, or baked: the normal map leans >= 12 deg just inside it); *materials* (distinct kind and tint); *contrast* (base colour luminance p95 - p5 over LOD0); *scales* (primary: LOD3 shows more than one mass; secondary: LOD0 holds forms LOD3 drops; tertiary: the normal map carries surface detail); *silhouette* complexity (1 - mean solidity of LOD0's outline in four views); *wear* (a worn material and a lit curvature mask).
- **Rubric**: form/critique.py's eight items, 0-5. Three blind passes, each over the anonymous review sheets (four lit views of LOD0 and a 64 px outline, the seven assets shuffled, the control among them); each item is the median of the passes, capped by the game evidence. Gate: mean >= 4.0 and none under 3 (proposed).

| Brief | Route (expected) | Build | SubD→CAD max / 100 mm | Validation | LOD0..LOD3 tris / budget | Bevel | Mat. | Contrast | Scales | Silh. | Wear | Rubric |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Sci-fi helmet prop | subd_cage (subd_cage) | ok 4.1 s | 0.382 mm (0/2 exact) | PASS | 9950/10000 · 4974/5000 · 1990/2000 · 596/600 | 100% | 4 | 0.72 | 3/3 | 0.077 | yes | 2.88 FAIL |
| Stylised treasure chest | subd_cage (subd_cage) | ok 16.5 s | 1.4 mm (0/17 exact) | PASS | 11952/12000 · 5970/6000 · 2486/2500 · 796/800 | 94% | 3 | 0.27 | 3/3 | 0.018 | yes | 3.38 FAIL |
| Fantasy sword | subd_cage (subd_cage) | ok 5.8 s | 1.34 mm (0/7 exact) | PASS | 3980/4000 · 1990/2000 · 796/800 · 298/300 | 99% | 4 | 0.69 | 3/3 | 0.455 | yes | 3.25 FAIL |
| Modular wall kit piece | procedural (procedural) | ok 10.2 s | 0.103 mm (0/1 exact) | PASS | 7756/8000 · 2798/4000 · 1592/1600 · 496/500 | 93% | 3 | 0.33 | 3/3 | 0.061 | yes | 2.81 FAIL |
| Vehicle wheel | subd_cage (subd_cage) | ok 8.1 s | 1.23 mm (2/8 exact) | PASS | 5970/6000 · 2984/3000 · 1194/1200 · 496/500 | 97% | 4 | 0.58 | 3/3 | 0.061 | yes | 3.38 FAIL |
| Remote control, CAD plus asset | kernel (kernel) | ok 3.4 s | n/a (kernel) | PASS | 3980/4000 · 1990/2000 · 894/900 · 398/400 | 67% | 5 | 0.41 | 3/3 | 0.023 | yes | 3.12 FAIL |
| Control: plain blob (control) | — | ok 0.3 s | 0.0542 mm (0/1 exact) | PASS | 2984/3000 · 1492/1500 · 596/600 · 198/200 | 100% | 1 | 0.01 | 0/3 | 0.009 | no | 0.69 FAIL |

## Per brief

### Sci-fi helmet prop

- Originality: An original helmet built from generic hard-surface vocabulary (a recessed visor, cheek plates, a crest, vents, panel lines). It is no franchise's helmet: no character's visor shape, crest or markings were referenced; the proportions and layout were chosen here.
- Routes: shell → subd_cage; visor → subd_cage; cheeks → subd_cage; crest → subd_cage
- Model: 29 model_mesh ops (10 high_only) in 0.99 s.
- Cage: 652 points, 624 faces, 236 creased edges, regions brow, cheek, chin, crest, nape, vent_l, vent_r, visor; bake source 2252 faces.
- SubD→CAD: 2 part(s), worst max 1.23 mm, RMS 0.116 mm, 0.382 mm per 100 mm; 82 irregular point(s).
- STEP: valid, 1 solid(s), 277 faces, 1706 kB
- Game asset (unreal): 54.4 s, bake 25.0 s, size 313 x 323 x 293 mm, UVs smart, 2 collision hull(s).
- Checks: all PASS
  - LOD0: 9950 / 10000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 4974 / 5000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD2: 1990 / 2000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD3: 596 / 600 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 100% (16 mm raw hard edge of 3114 mm feature edge, 10 mm baked); materials 4 (painted_metal #34383d, painted_metal #b8492a, painted_metal #d8d3c6, plastic #141c24); value contrast 0.719; scales primary yes (2 LOD3 part(s), min solidity 0.869), secondary yes (0.5% of LOD0 off LOD3), tertiary yes (normal blue std 0.01729, rg std 0.03675); silhouette complexity 0.0768 (front 0.8748, side 0.9201, top 0.9287, three_quarter 0.9692); wear yes (max 0.65, edge mask 1.2%).
- Rubric: silhouette 3.5 (passes 3/4/4), proportion 2.5 (passes 2/2/2), continuity 2.5 (passes 2/2/2), radius_hierarchy 3.0 (passes 3/3/2), break_up 3.0 (passes 3/4/3), detail_rhythm 2.5 (passes 2/2/2), material 3.5 (passes 4/4/4), would_sell 2.5 (passes 2/2/2); mean 2.88
- Blind pass 1 said: Same helmet as A: crest, visor and orange pods on a soft, lumpy white shell, with irregular small detail.
- Blind pass 2 said: Stylized helmet with a dark fin, a visor recess and orange ear pods; the shell is lumpy and the rear bulges look unresolved.
- Blind pass 3 said: Same stylized helmet: crest fin, dark visor, orange pods; the soft, lumpy shell lacks crisp form control.
- Wall time 125.1 s.

### Stylised treasure chest

- Originality: An original chest built from generic woodworking and hardware vocabulary (boarded body, barrel lid, riveted strap iron, a draw latch). It copies no game, film or brand prop; the proportions, plank count and hardware layout were chosen here.
- Routes: body → subd_cage; lid → subd_cage; straps → procedural; lock → subd_cage
- Model: 37 model_mesh ops (20 high_only) in 1.6 s.
- Cage: 1528 points, 1494 faces, 700 creased edges, regions gold, iron, lidplank_0, lidplank_1, lidplank_2, lidplank_3, lockface, plank_0, plank_1, plank_2, plank_3, plank_4; bake source 3312 faces.
- SubD→CAD: 17 part(s), worst max 8.09 mm, RMS 0.283 mm, 1.4 mm per 100 mm; 520 irregular point(s).
- STEP: valid, 1 solid(s), 941 faces, 8596 kB
- Game asset (unreal): 31.0 s, bake 9.7 s, size 614 x 407 x 451 mm, UVs smart, 16 collision hull(s).
- Checks: all PASS
  - LOD0: 11952 / 12000 triangles, cage level 1 (clean quads)
  - LOD1: 5970 / 6000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 2486 / 2500 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 796 / 800 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 94% (1706 mm raw hard edge of 28194 mm feature edge, 1569 mm baked); materials 3 (bare_metal #3e3c3a, bare_metal #c9982f, wood #8a5a32); value contrast 0.268; scales primary yes (17 LOD3 part(s), min solidity 0.9647), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02243, rg std 0.05864); silhouette complexity 0.0185 (front 0.9757, side 0.9881, top 0.9928, three_quarter 0.9693); wear yes (max 0.75, edge mask 2.2%).
- Rubric: silhouette 3.0 (passes 3/3/4) [cap 3: The outline at 64 px is nearly convex (convexity deficit 0.022, under 0.06) and only 5 value region(s) read inside it (of 6).], proportion 3.0 (passes 3/3/4), continuity 3.5 (passes 4/4/4), radius_hierarchy 2.5 (passes 2/2/3), break_up 4.0 (passes 4/4/4), detail_rhythm 3.5 (passes 4/4/4), material 4.0 (passes 4/4/4), would_sell 3.5 (passes 4/4/4); mean 3.38
- Blind pass 1 said: Classic domed chest with plank grooves, iron straps on an even rivet pitch, a brass lock and a base band; a clean but generic stylized prop.
- Blind pass 2 said: Domed wooden chest with plank grooves, riveted iron bands, a metal base trim and a brass lock plate; the outline reads well but is close to a box.
- Blind pass 3 said: Domed wooden chest with plank grooves, iron bands with evenly spaced rivets, a gold lock plate and a metal base trim; a solid, familiar prop.
- Wall time 118.9 s.

### Fantasy sword

- Originality: An original arming-sword shape from generic sword anatomy (fuller, ground edges, a swept guard, a wrapped grip, a faceted pommel). It reproduces no named weapon from a game, film or book.
- Routes: blade → subd_cage; guard → subd_cage; grip → subd_cage; pommel → subd_cage
- Model: 11 model_mesh ops (1 high_only) in 0.62 s.
- Cage: 752 points, 734 faces, 426 creased edges, regions blade, fuller, grip, guard, pommel; bake source 1814 faces.
- SubD→CAD: 7 part(s), worst max 0.779 mm, RMS 0.0385 mm, 1.34 mm per 100 mm; 200 irregular point(s).
- STEP: valid, 1 solid(s), 562 faces, 4069 kB
- Game asset (gltf): 16.8 s, bake 6.1 s, size 292 x 46 x 1048 mm, UVs smart, 7 collision hull(s).
- Checks: all PASS
  - LOD0: 3980 / 4000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD1: 1990 / 2000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 796 / 800 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 298 / 300 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 99% (133 mm raw hard edge of 12785 mm feature edge, 1264 mm baked); materials 4 (bare_metal #a27c38, brushed_metal #8f969d, brushed_metal #c4c9cf, leather #3f2517); value contrast 0.687; scales primary yes (7 LOD3 part(s), min solidity 0.3839), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02503, rg std 0.06782); silhouette complexity 0.4549 (front 0.3764, side 0.5838, top 0.8333, three_quarter 0.3868); wear yes (max 0.6, edge mask 18.6%).
- Rubric: silhouette 4.0 (passes 4/4/4), proportion 3.5 (passes 4/3/4) [cap 4: Bounding ratios are not near a classic ratio: long:mid 3.594, mid:short 6.28.], continuity 3.5 (passes 4/4/4), radius_hierarchy 2.5 (passes 2/2/3), break_up 3.0 (passes 3/3/4), detail_rhythm 3.0 (passes 3/2/4), material 3.5 (passes 4/4/4) [cap 4: Wear covers 12.7% of the surface (over 12%: it reads as damage, not use).], would_sell 3.0 (passes 3/2/4); mean 3.25
- Blind pass 1 said: Same sword as E: a clear cruciform read, steel blade with brass and leather hilt, and minimal guard detail.
- Blind pass 2 said: Longsword with a fullered blade, a curved brass guard, a wrapped grip and a ball pommel; readable but simple, with a thin guard and few detail tiers.
- Blind pass 3 said: Longsword with a fuller, brass crossguard, wrapped grip and pommel; clear read with a strong steel/brass/leather pairing.
- Wall time 96.2 s.

### Modular wall kit piece

- Originality: An original modular wall built from generic masonry (stretcher-bond brick, plinth, coping). Sizes follow a 0.5 m kit grid chosen here; it copies no game's kit.
- Routes: wall → kernel; bricks → procedural; trim → procedural
- Model: 47 model_mesh ops (31 high_only) in 1.99 s.
- Cage: 966 points, 895 faces, 560 creased edges, regions brick, cells, coping_b, coping_f, plinth_b, plinth_f, sunk, trim; bake source 1589 faces.
- SubD→CAD: 1 part(s), worst max 2.47 mm, RMS 0.0233 mm, 0.103 mm per 100 mm; 351 irregular point(s).
- STEP: valid, 1 solid(s), 1344 faces, 7421 kB
- Game asset (godot): 26.0 s, bake 14.8 s, size 2000 x 350 x 2400 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 7756 / 8000 triangles, cage level 1 (clean quads)
  - LOD1: 2798 / 4000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 1592 / 1600 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 496 / 500 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 93% (1900 mm raw hard edge of 26359 mm feature edge, 1550 mm baked); materials 3 (stone #6f6c66, stone #8c4f38, stone #9a958c); value contrast 0.328; scales primary yes (1 LOD3 part(s), min solidity 0.7919), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.03158, rg std 0.05941); silhouette complexity 0.0612 (front 1.0, side 0.7871, top 1.0, three_quarter 0.9682); wear yes (max 0.65, edge mask 4.4%).
- Rubric: silhouette 1.5 (passes 2/2/2) [cap 3: The outline at 64 px is nearly convex (convexity deficit 0.059, under 0.06) and only 2 value region(s) read inside it (of 6).], proportion 3.0 (passes 3/3/3) [cap 4: Bounding ratios are not near a classic ratio: mid:short 6.061.], continuity 3.0 (passes 4/3/3), radius_hierarchy 2.0 (passes 2/2/2), break_up 3.5 (passes 3/4/4), detail_rhythm 3.5 (passes 4/4/4), material 3.5 (passes 4/4/2), would_sell 2.5 (passes 3/2/2); mean 2.81
- Blind pass 1 said: Same wall slab as B, with slightly cleaner corners: brick and block faces with cap and plinth tiers, and a flat box silhouette.
- Blind pass 2 said: Brick wall slab with a coping cap, a plinth and a block-faced back; cleanly built, but the outline is a flat slab with hard edges.
- Blind pass 3 said: Flat wall slab with a coping and plinth; brick front and block back don't match; slightly cleaner corners than the twin version.
- Wall time 179.1 s.

### Vehicle wheel

- Originality: An original off-road wheel (lug tread, five-spoke rim, hub with lug nuts) from generic wheel anatomy. No maker's rim design, tread pattern, logo or lettering.
- Routes: tyre → subd_cage; rim → subd_cage; spokes → procedural; hub → kernel
- Model: 9 model_mesh ops (3 high_only) in 0.73 s.
- Cage: 1470 points, 1458 faces, 704 creased edges, regions hub, rim, tyre; bake source 2010 faces.
- SubD→CAD: 8 part(s), worst max 1.59 mm, RMS 0.0666 mm, 1.23 mm per 100 mm; 168 irregular point(s).
- STEP: valid, 1 solid(s), 631 faces, 4970 kB
- Game asset (unity): 36.7 s, bake 16.9 s, size 664 x 240 x 664 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 5970 / 6000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD1: 2984 / 3000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 1194 / 1200 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 496 / 500 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 97% (694 mm raw hard edge of 22653 mm feature edge, 862 mm baked); materials 4 (bare_metal #6e7277, bare_metal #8d9196, painted_metal #b4b9be, rubber #242424); value contrast 0.582; scales primary yes (8 LOD3 part(s), min solidity 0.7876), secondary yes (8.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.04988, rg std 0.06715); silhouette complexity 0.061 (front 0.7901, side 0.9968, top 0.9975, three_quarter 0.9716); wear yes (max 0.6, edge mask 1.6%).
- Rubric: silhouette 3.0 (passes 4/3/3), proportion 3.5 (passes 4/4/4), continuity 3.5 (passes 4/4/4), radius_hierarchy 3.0 (passes 3/3/3), break_up 3.5 (passes 4/4/4), detail_rhythm 3.5 (passes 4/4/4), material 4.0 (passes 4/4/4), would_sell 3.0 (passes 4/3/3); mean 3.38
- Blind pass 1 said: Wheel with chevron tread on an even pitch, a five-spoke alloy rim and a hub cap; rubber and metal read well, and the back of the rim is simple.
- Blind pass 2 said: Wheel with a chevron-tread tire, a five-spoke alloy rim and a hub cap; solid two-material read, but the tread looks shallow.
- Blind pass 3 said: Tyre with a chevron tread and a five-spoke silver rim with a hub cap; credible, though the tread is shallow and the outline shows small holes.
- Wall time 100.1 s.

### Remote control, CAD plus asset

- Originality: A generic TV remote laid out from common remote anatomy (power, navigation pad, rockers, number grid). No maker's shape, logo or button legend.
- Routes: body → subd_cage; buttons → kernel; battery_cover → kernel
- STEP: valid, 1 solid(s), 181 faces, 592 kB
- Game asset (gltf): 18.0 s, bake 10.0 s, size 190 x 50 x 23 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 3980 / 4000 triangles, decimated to the budget (automatic retopology)
  - LOD1: 1990 / 2000 triangles, decimated to the budget (automatic retopology)
  - LOD2: 894 / 900 triangles, decimated to the budget (automatic retopology)
  - LOD3: 398 / 400 triangles, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 67% (1983 mm raw hard edge of 5971 mm feature edge, 2949 mm baked); materials 5 (plastic #0b0d10, plastic #2b2e33, plastic #c7ccd2, rubber #8a9099, rubber #c23a2b); value contrast 0.411; scales primary yes (1 LOD3 part(s), min solidity 0.9245), secondary yes (15.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02956, rg std 0.06537); silhouette complexity 0.0233 (front 0.9696, side 0.9937, top 0.9973, three_quarter 0.946); wear yes (max 0.45, edge mask 3.0%).
- Rubric: silhouette 2.0 (passes 2/2/2) [cap 3: The outline at 64 px is nearly convex (convexity deficit 0.047, under 0.06) and only 5 value region(s) read inside it (of 6).], proportion 3.0 (passes 3/3/4) [cap 4: Bounding ratios are not near a classic ratio: long:mid 3.8.], continuity 3.5 (passes 4/4/4), radius_hierarchy 3.5 (passes 3/4/4) [cap 4: Bevel coverage 67%: 1983 mm of raw hard edge in LOD0 of 5971 mm of feature edge (bevel it, or bevel it high_only so the bake rounds it).], break_up 3.5 (passes 3/4/4), detail_rhythm 3.5 (passes 4/4/4), material 3.0 (passes 3/3/4), would_sell 3.0 (passes 3/3/4); mean 3.12
- Blind pass 1 said: Remote with rounded body, a seam line, a button grid on a steady pitch, a d-pad and a red power key; a plain bar silhouette, and the metal back reads well.
- Blind pass 2 said: Rounded-slab remote with a split-line shell, a button grid, a nav ring and a red key; clean but a generic bar silhouette.
- Blind pass 3 said: Rounded-slab TV remote with a keypad grid, D-pad, red button and a seam line; clean but the outline is a generic bar.
- Wall time 34.4 s.

### Control: plain blob (control)

- Originality: A deliberately bad control (an egg in one grey material); not a design.
- Cage: 56 points, 54 faces, 0 creased edges, regions none; bake source none (the cage itself).
- SubD→CAD: 1 part(s), worst max 0.163 mm, RMS 0.0419 mm, 0.0542 mm per 100 mm; 8 irregular point(s).
- STEP: valid, 1 solid(s), 35 faces, 192 kB
- Game asset (gltf): 15.7 s, bake 9.9 s, size 254 x 195 x 302 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 2984 / 3000 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD1: 1492 / 1500 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD2: 596 / 600 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD3: 198 / 200 triangles, cage level 2, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 100% (0 mm raw hard edge of 0 mm feature edge, 0 mm baked); materials 1 (plastic #9a9893); value contrast 0.008; scales primary no (1 LOD3 part(s), min solidity 0.9832), secondary no (20.0% of LOD0 off LOD3), tertiary no (normal blue std 0.0, rg std 0.00329); silhouette complexity 0.0094 (front 0.9911, side 0.9905, top 0.9898, three_quarter 0.9911); wear no (max 0.0, edge mask 0.0%).
- Rubric: silhouette 0.5 (passes 0/0/0) [cap 2: The outline at 64 px is nearly convex (convexity deficit 0.027, under 0.06) and there is no detail: a blob.], proportion 1.0 (passes 1/0/1), continuity 3.0 (passes 3/2/3), radius_hierarchy 0.5 (passes 0/0/0), break_up 0.0 (passes 0/0/0) [cap 3: No secondary forms: LOD0 has no panel, bevel, trim or part that LOD3 drops.], detail_rhythm 0.0 (passes 0/0/0) [cap 2: One detail scale or none (none): missing primary, secondary, tertiary.], material 0.5 (passes 0/0/0) [cap 1: One material over everything; value contrast 0.01 (under 0.08: it reads as one flat tone); no edge wear (0.0% of the surface worn, under 2%).], would_sell 0.0 (passes 0/0/0); mean 0.69
- Blind pass 1 said: Featureless grey egg or pebble blob; no form language, no detail and a single material.
- Blind pass 2 said: Featureless grey pebble blob with no breaks, details or material separation.
- Blind pass 3 said: Featureless grey pebble/egg blob with no detail, materials or intent.
- Wall time 28.3 s.

## What failed

Technical: nothing failed.
Rubric: below the gate: Sci-fi helmet prop, Stylised treasure chest, Fantasy sword, Modular wall kit piece, Vehicle wheel, Remote control, CAD plus asset.
See each brief above for the measured reason.
