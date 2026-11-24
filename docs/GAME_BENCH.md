# Game bench

Six original game-asset briefs (tests/design_bench/game_briefs.json) and one deliberately bad control, made end to end from the game exemplars in form/exemplars/game/, twice: with design refinement off (the exemplar as written) and on (form/refine: cage and material operators, one bake checked at the end, the asset made from the refined head). Run 2026-11-25 on Darwin arm64 with Blender 5.2.3. Every number below is from those runs; failures are published as they came out. Budgets and thresholds are proposed values, not engine rules.

## Result

- Rubric with refinement on (median of three new blind passes, capped by the game evidence): 0 of 6 at 4.0 or more (gate: at least 5 of 6): **FAIL**.
- Control: fails the gate, as it must: **pass**.
- Technical checks pass on 6 of 6 with refinement on, 6 of 6 off.
- Scored by: three blind passes by Claude subagents (an AI model), not a person (2026-11-25). Each pass saw only the seven anonymous review sheets of the refinement-on run (no names, briefs, numbers or the key), in its own order; the letters were mapped back to briefs afterwards. The rubric is a model's judgement of rendered sheets, not a person's and not a measurement.
- The off column's rubric is the earlier scores file (game_scores.json), scored on the sheets of the run it came with.

| Brief | Validation off / on | LOD0 tris off / on | Bevel off / on | Contrast off / on | Wear off / on | Rubric off | Rubric on | Refinement (kept) |
|---|---|---|---|---|---|---|---|---|
| Sci-fi helmet prop | PASS / PASS | 9950 / 9950 | 100% / 100% | 0.719 / 0.719 | 3.1% / 3.1% | 3.00 FAIL | 2.56 FAIL | 3.0 s: no step gains 2 % |
| Stylised treasure chest | PASS / PASS | 11952 / 11952 | 94% / 94% | 0.268 / 0.268 | 5.1% / 5.1% | 3.31 FAIL | 3.25 FAIL | 43.5 s: Kit detail, not kept: Design source is larger than 200 kB. |
| Fantasy sword | PASS / PASS | 3342 / 3342 | 99% / 99% | 0.687 / 0.687 | 12.0% / 12.0% | 3.25 FAIL | 3.31 FAIL | 2.3 s: no step gains 2 % |
| Modular wall kit piece | PASS / PASS | 7436 / 7436 | 92% / 92% | 0.332 / 0.332 | 8.1% / 8.1% | 2.12 FAIL | 2.56 FAIL | 3.7 s: no step gains 2 % |
| Vehicle wheel | PASS / PASS | 5970 / 5970 | 97% / 97% | 0.582 / 0.582 | 5.5% / 5.5% | 2.88 FAIL | 3.38 FAIL | 3.9 s: no step gains 2 % |
| Remote control, CAD plus asset | PASS / PASS | 3980 / 3980 | 67% / 67% | 0.411 / 0.411 | 4.1% / 4.1% | 2.94 FAIL | 2.94 FAIL | 3.0 s: no operator applies |
| Control: plain blob (control) | PASS / PASS | 2984 / 2984 | 100% / 100% | 0.008 / 0.008 | 0.0% / 0.0% | 1.12 FAIL | 0.44 FAIL | 0.1 s: no operator applies |

## Refinement per brief

- **Sci-fi helmet prop**: deficit 0.1042 → 0.1042, 3.0 s, stopped: no step gains 2 %; kept: nothing; rejected: trim_strip (build: BlenderFailed: The modelling ops failed at op 10 (trim_strip): OpError: the edge selection is empty); panel_line (build: BlenderFailed: The modelling ops failed at op 10 (panel_line): OpError: the edge selection is empty)
- **Stylised treasure chest**: deficit 0.2499 → 0.2183, 43.5 s, stopped: no step gains 2 %, NOT COMMITTED: Design source is larger than 200 kB.; kept: Kit detail (Kit detail at a constant pitch in three sizes (1 : 0.38 : 0.15).); rejected: trim_strip (build: BlenderFailed: The modelling ops failed at op 14 (trim_strip): OpError: the edge selection is empty); panel_line (build: BlenderFailed: The modelling ops failed at op 14 (panel_line): OpError: the edge selection is empty); trim_strip (build: BlenderFailed: The modelling ops failed at op 17 (trim_strip): OpError: the edge selection is empty); panel_line (build: BlenderFailed: The modelling ops failed at op 17 (panel_line): OpError: the edge selection is empty)
- **Fantasy sword**: deficit 0.2074 → 0.2074, 2.3 s, stopped: no step gains 2 %; kept: nothing; rejected: trim_strip (build: BlenderFailed: The modelling ops failed at op 7 (trim_strip): OpError: the edge selection is empty); panel_line (build: BlenderFailed: The modelling ops failed at op 7 (panel_line): OpError: the edge selection is empty)
- **Modular wall kit piece**: deficit 0.2751 → 0.2751, 3.7 s, stopped: no step gains 2 %; kept: nothing
- **Vehicle wheel**: deficit 0.1119 → 0.1119, 3.9 s, stopped: no step gains 2 %; kept: nothing
- **Remote control, CAD plus asset**: deficit 0.2274 → 0.2274, 3.0 s, stopped: no operator applies; kept: nothing
- **Control: plain blob**: deficit 0.3833 → 0.3833, 0.1 s, stopped: no operator applies; kept: nothing

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
| Sci-fi helmet prop | subd_cage (subd_cage) | ok 4.1 s | 0.382 mm (0/2 exact) | PASS | 9950/10000 · 4974/5000 · 1990/2000 · 596/600 | 100% | 4 | 0.72 | 3/3 | 0.077 | yes | 2.56 FAIL |
| Stylised treasure chest | subd_cage (subd_cage) | ok 15.3 s | 1.4 mm (0/17 exact) | PASS | 11952/12000 · 5970/6000 · 2486/2500 · 796/800 | 94% | 3 | 0.27 | 3/3 | 0.018 | yes | 3.25 FAIL |
| Fantasy sword | subd_cage (subd_cage) | ok 5.0 s | 1.32 mm (0/5 exact) | PASS | 3342/4000 · 1990/2000 · 796/800 · 298/300 | 99% | 4 | 0.69 | 3/3 | 0.439 | yes | 3.31 FAIL |
| Modular wall kit piece | procedural (procedural) | ok 10.1 s | 0.103 mm (0/1 exact) | PASS | 7436/8000 · 2644/4000 · 1592/1600 · 496/500 | 92% | 3 | 0.33 | 3/3 | 0.052 | yes | 2.56 FAIL |
| Vehicle wheel | subd_cage (subd_cage) | ok 8.0 s | 1.23 mm (2/8 exact) | PASS | 5970/6000 · 2984/3000 · 1194/1200 · 496/500 | 97% | 4 | 0.58 | 3/3 | 0.061 | yes | 3.38 FAIL |
| Remote control, CAD plus asset | kernel (kernel) | ok 3.2 s | n/a (kernel) | PASS | 3980/4000 · 1990/2000 · 894/900 · 398/400 | 67% | 5 | 0.41 | 3/3 | 0.023 | yes | 2.94 FAIL |
| Control: plain blob (control) | — | ok 0.3 s | 0.0542 mm (0/1 exact) | PASS | 2984/3000 · 1492/1500 · 596/600 · 198/200 | 100% | 1 | 0.01 | 0/3 | 0.009 | no | 0.44 FAIL |

## Per brief

### Sci-fi helmet prop

- Originality: An original helmet built from generic hard-surface vocabulary (a recessed visor, cheek plates, a crest, vents, panel lines). It is no franchise's helmet: no character's visor shape, crest or markings were referenced; the proportions and layout were chosen here.
- Routes: shell → subd_cage; visor → subd_cage; cheeks → subd_cage; crest → subd_cage
- Model: 29 model_mesh ops (10 high_only) in 0.99 s.
- Cage: 652 points, 624 faces, 236 creased edges, regions brow, cheek, chin, crest, nape, vent_l, vent_r, visor; bake source 2252 faces.
- SubD→CAD: 2 part(s), worst max 1.23 mm, RMS 0.116 mm, 0.382 mm per 100 mm; 82 irregular point(s).
- STEP: valid, 1 solid(s), 277 faces, 1706 kB
- Game asset (unreal): 54.5 s, bake 25.2 s, size 313 x 323 x 293 mm, UVs smart, 2 collision hull(s).
- Checks: all PASS
  - LOD0: 9950 / 10000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD1: 4974 / 5000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD2: 1990 / 2000 triangles, cage level 2, decimated to the budget (automatic retopology)
  - LOD3: 596 / 600 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 100% (16 mm raw hard edge of 3114 mm feature edge, 10 mm baked); materials 4 (painted_metal #34383d, painted_metal #b8492a, painted_metal #d8d3c6, plastic #141c24); value contrast 0.719; scales primary yes (2 LOD3 part(s), min solidity 0.869), secondary yes (0.5% of LOD0 off LOD3), tertiary yes (normal blue std 0.01729, rg std 0.03675); silhouette complexity 0.0768 (front 0.8748, side 0.9201, top 0.9287, three_quarter 0.9692); wear yes (max 0.65, edge mask 1.2%).
- Rubric: silhouette 3.0 (passes 3/3/2), proportion 2.5 (passes 2/2/2), continuity 2.0 (passes 2/2/2), radius_hierarchy 2.5 (passes 2/2/2), break_up 3.0 (passes 3/3/2), detail_rhythm 2.0 (passes 2/2/2), material 3.5 (passes 4/4/3), would_sell 2.0 (passes 2/2/2); mean 2.56
- Blind pass 1 said: Helmet with an off-white shell, a dark crest and visor and orange ear pads; the lumpy, blobby shell surfaces and uneven rivets read as unfinished.
- Blind pass 2 said: Helmet with a dark visor, orange ear cups and a dark crest fin; the white shell is lumpy and blobby, and the trim wire and rivets are sparse and uneven.
- Blind pass 3 said: Lumpy white helmet shell with a dark visor, orange ear pads and a crest fin. The surfaces are wobbly and blobby, and the seam wire is thin and arbitrary.
- Wall time 78.1 s.

### Stylised treasure chest

- Originality: An original chest built from generic woodworking and hardware vocabulary (boarded body, barrel lid, riveted strap iron, a draw latch). It copies no game, film or brand prop; the proportions, plank count and hardware layout were chosen here.
- Routes: body → subd_cage; lid → subd_cage; straps → procedural; lock → subd_cage
- Model: 37 model_mesh ops (20 high_only) in 1.61 s.
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
- Rubric: silhouette 3 (passes 3/4/4) [cap 3: The outline at 64 px is nearly convex (convexity deficit 0.022, under 0.06) and only 5 value region(s) read inside it (of 6).], proportion 3.5 (passes 3/4/4), continuity 3.5 (passes 4/4/3), radius_hierarchy 2.5 (passes 2/3/2), break_up 3.5 (passes 4/4/4), detail_rhythm 3.5 (passes 4/4/4), material 3.5 (passes 4/4/4), would_sell 3.0 (passes 3/4/3); mean 3.25
- Blind pass 1 said: Domed chest with wood planks, iron bands on an even rivet pitch, a brass lock and a metal base; readable but generic, with the plank grooves only painted on.
- Blind pass 2 said: Domed wooden chest with plank grooves, two iron bands with evenly spaced rivets, a hasp plate and a steel base; it reads clearly, but the edges are fairly hard and the wood grain is generic.
- Blind pass 3 said: Domed wooden chest with plank grooves, two iron straps with evenly spaced rivets, a brass lock and a metal base trim. Many edges are still hard and the grain is noisy.
- Wall time 146.1 s.

### Fantasy sword

- Originality: An original arming-sword shape from generic sword anatomy (fuller, ground edges, a swept guard, a wrapped grip, a faceted pommel). It reproduces no named weapon from a game, film or book.
- Routes: blade → subd_cage; guard → subd_cage; grip → subd_cage; pommel → subd_cage
- Model: 11 model_mesh ops (1 high_only) in 0.62 s.
- Cage: 640 points, 626 faces, 378 creased edges, regions blade, fuller, grip, guard, pommel; bake source 1706 faces.
- SubD→CAD: 5 part(s), worst max 0.766 mm, RMS 0.0377 mm, 1.32 mm per 100 mm; 136 irregular point(s).
- STEP: valid, 1 solid(s), 482 faces, 3409 kB
- Game asset (gltf): 16.7 s, bake 6.1 s, size 260 x 46 x 1048 mm, UVs smart, 5 collision hull(s).
- Checks: all PASS
  - LOD0: 3342 / 4000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD1: 1990 / 2000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 796 / 800 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 298 / 300 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 99% (158 mm raw hard edge of 11700 mm feature edge, 887 mm baked); materials 4 (bare_metal #a27c38, brushed_metal #8f969d, brushed_metal #c4c9cf, leather #3f2517); value contrast 0.687; scales primary yes (5 LOD3 part(s), min solidity 0.3965), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02489, rg std 0.06673); silhouette complexity 0.4392 (front 0.4036, side 0.5838, top 0.8352, three_quarter 0.4207); wear yes (max 0.6, edge mask 17.4%).
- Rubric: silhouette 4.0 (passes 4/4/4), proportion 3.5 (passes 3/4/4) [cap 4: Bounding ratios are not near a classic ratio: long:mid 4.031, mid:short 5.599.], continuity 3.5 (passes 3/4/4), radius_hierarchy 3.0 (passes 2/3/3), break_up 3.0 (passes 2/3/3), detail_rhythm 3.0 (passes 2/3/3), material 3.5 (passes 3/4/4) [cap 4: Wear covers 12.0% of the surface (over 12%: it reads as damage, not use).], would_sell 3.0 (passes 2/3/3); mean 3.31
- Blind pass 1 said: Longsword with a fullered blade, a curved brass guard, a wrapped grip and a ball pommel; the outline is clear but the guard block and pommel are simple primitives.
- Blind pass 2 said: Longsword with a fullered steel blade, a curved brass guard, a leather-wrapped grip and a ball pommel; the silhouette is clear, but the asset is simple and sparse.
- Blind pass 3 said: Clean longsword with a fullered blade, a curved brass guard, a wrapped grip and a ball pommel. The steel, brass and leather pair well, but the guard block and pommel are simple.
- Wall time 47.5 s.

### Modular wall kit piece

- Originality: An original modular wall built from generic masonry (stretcher-bond brick, plinth, coping). Sizes follow a 0.5 m kit grid chosen here; it copies no game's kit.
- Routes: wall → kernel; bricks → procedural; trim → procedural
- Model: 47 model_mesh ops (31 high_only) in 1.98 s.
- Cage: 966 points, 895 faces, 560 creased edges, regions brick, cells, coping_b, coping_f, plinth_b, plinth_f, sunk, trim; bake source 1589 faces.
- SubD→CAD: 1 part(s), worst max 2.47 mm, RMS 0.0233 mm, 0.103 mm per 100 mm; 351 irregular point(s).
- STEP: valid, 1 solid(s), 1344 faces, 7421 kB
- Game asset (godot): 25.8 s, bake 14.4 s, size 2000 x 330 x 2400 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 7436 / 8000 triangles, cage level 1 (clean quads)
  - LOD1: 2644 / 4000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 1592 / 1600 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 496 / 500 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 92% (1469 mm raw hard edge of 18605 mm feature edge, 1948 mm baked); materials 3 (stone #6f6c66, stone #8c4f38, stone #9a958c); value contrast 0.332; scales primary yes (1 LOD3 part(s), min solidity 0.8425), secondary yes (0.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.04356, rg std 0.06575); silhouette complexity 0.0518 (front 1.0, side 0.8132, top 1.0, three_quarter 0.9797); wear yes (max 0.65, edge mask 3.9%).
- Rubric: silhouette 1.5 (passes 2/2/2), proportion 2.5 (passes 2/3/2) [cap 4: Bounding ratios are not near a classic ratio: mid:short 6.061.], continuity 3.0 (passes 3/3/2), radius_hierarchy 2.0 (passes 2/2/2), break_up 3.0 (passes 3/4/3), detail_rhythm 3.5 (passes 4/4/4), material 3.0 (passes 2/3/3), would_sell 2.0 (passes 2/2/2); mean 2.56
- Blind pass 1 said: Wall slab with a capstone and plinth; brick on one face and cinder block on the other is an odd pairing, and the bricks are texture only.
- Blind pass 2 said: Flat wall panel with red brick on the front, a stone coping and plinth, and grey block on the back; the outline is a slab, and the two faces do not match.
- Blind pass 3 said: Flat wall panel with a brick face, a block back, a coping cap and a base plinth. It is a thin slab with odd corner artifacts and a plain side view.
- Wall time 74.6 s.

### Vehicle wheel

- Originality: An original off-road wheel (lug tread, five-spoke rim, hub with lug nuts) from generic wheel anatomy. No maker's rim design, tread pattern, logo or lettering.
- Routes: tyre → subd_cage; rim → subd_cage; spokes → procedural; hub → kernel
- Model: 9 model_mesh ops (3 high_only) in 0.72 s.
- Cage: 1470 points, 1458 faces, 704 creased edges, regions hub, rim, tyre; bake source 2010 faces.
- SubD→CAD: 8 part(s), worst max 1.59 mm, RMS 0.0666 mm, 1.23 mm per 100 mm; 168 irregular point(s).
- STEP: valid, 1 solid(s), 631 faces, 4970 kB
- Game asset (unity): 37.1 s, bake 17.1 s, size 664 x 240 x 664 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 5970 / 6000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD1: 2984 / 3000 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD2: 1194 / 1200 triangles, cage level 1, decimated to the budget (automatic retopology)
  - LOD3: 496 / 500 triangles, cage level 1, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 97% (694 mm raw hard edge of 22653 mm feature edge, 862 mm baked); materials 4 (bare_metal #6e7277, bare_metal #8d9196, painted_metal #b4b9be, rubber #242424); value contrast 0.582; scales primary yes (8 LOD3 part(s), min solidity 0.7876), secondary yes (8.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.04988, rg std 0.06715); silhouette complexity 0.061 (front 0.7901, side 0.9968, top 0.9975, three_quarter 0.9716); wear yes (max 0.6, edge mask 1.6%).
- Rubric: silhouette 3.0 (passes 2/3/3), proportion 3.5 (passes 3/4/4), continuity 3.5 (passes 4/4/4), radius_hierarchy 3.0 (passes 3/4/3), break_up 3.5 (passes 3/4/4), detail_rhythm 4.0 (passes 4/4/4), material 3.5 (passes 4/4/4), would_sell 3.0 (passes 2/3/3); mean 3.38
- Blind pass 1 said: Wheel with a five-spoke chrome rim, a hub cap and a chevron tread on an even pitch; the outline is a plain disc and the tread is shallow.
- Blind pass 2 said: Rubber tire with a regular chevron tread and a five-spoke silver rim; the outline reads mostly as a disc, and the hub and spoke detail is thin.
- Blind pass 3 said: Tire with an even chevron tread pitch and a five-spoke silver rim with a stepped hub. The rubber and metal read clearly, but the outline is a plain disc and the spokes are simple.
- Wall time 86.7 s.

### Remote control, CAD plus asset

- Originality: A generic TV remote laid out from common remote anatomy (power, navigation pad, rockers, number grid). No maker's shape, logo or button legend.
- Routes: body → subd_cage; buttons → kernel; battery_cover → kernel
- STEP: valid, 1 solid(s), 181 faces, 592 kB
- Game asset (gltf): 18.2 s, bake 10.2 s, size 190 x 50 x 23 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 3980 / 4000 triangles, decimated to the budget (automatic retopology)
  - LOD1: 1990 / 2000 triangles, decimated to the budget (automatic retopology)
  - LOD2: 894 / 900 triangles, decimated to the budget (automatic retopology)
  - LOD3: 398 / 400 triangles, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 67% (1983 mm raw hard edge of 5971 mm feature edge, 2949 mm baked); materials 5 (plastic #0b0d10, plastic #2b2e33, plastic #c7ccd2, rubber #8a9099, rubber #c23a2b); value contrast 0.411; scales primary yes (1 LOD3 part(s), min solidity 0.9245), secondary yes (15.0% of LOD0 off LOD3), tertiary yes (normal blue std 0.02956, rg std 0.06537); silhouette complexity 0.0233 (front 0.9696, side 0.9937, top 0.9973, three_quarter 0.946); wear yes (max 0.45, edge mask 3.0%).
- Rubric: silhouette 2.0 (passes 2/2/2) [cap 3: The outline at 64 px is nearly convex (convexity deficit 0.047, under 0.06) and only 5 value region(s) read inside it (of 6).], proportion 3.0 (passes 3/3/3) [cap 4: Bounding ratios are not near a classic ratio: long:mid 3.8.], continuity 3.5 (passes 4/4/4), radius_hierarchy 3.0 (passes 3/4/3) [cap 4: Bevel coverage 67%: 1983 mm of raw hard edge in LOD0 of 5971 mm of feature edge (bevel it, or bevel it high_only so the bake rounds it).], break_up 3.0 (passes 3/4/3), detail_rhythm 3.5 (passes 4/4/4), material 3.0 (passes 3/4/3), would_sell 2.5 (passes 2/3/2); mean 2.94
- Blind pass 1 said: Remote with a rounded slab body, a grid keypad, a d-pad and a red button over a split seam; clean but bar-shaped and plain.
- Blind pass 2 said: Rounded slab remote with a seam line, a gridded keypad, a d-pad, a red button and a metal top plate; clean, but the outline is a plain bar.
- Blind pass 3 said: Rounded slab remote with a split shell line, a gridded keypad, a d-pad and a red button. The outline is a generic bar and the top panel material is muddy.
- Wall time 34.3 s.

### Control: plain blob (control)

- Originality: A deliberately bad control (an egg in one grey material); not a design.
- Cage: 56 points, 54 faces, 0 creased edges, regions none; bake source none (the cage itself).
- SubD→CAD: 1 part(s), worst max 0.163 mm, RMS 0.0419 mm, 0.0542 mm per 100 mm; 8 irregular point(s).
- STEP: valid, 1 solid(s), 35 faces, 192 kB
- Game asset (gltf): 15.9 s, bake 10.1 s, size 254 x 195 x 302 mm, UVs smart, 1 collision hull(s).
- Checks: all PASS
  - LOD0: 2984 / 3000 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD1: 1492 / 1500 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD2: 596 / 600 triangles, cage level 3, decimated to the budget (automatic retopology)
  - LOD3: 198 / 200 triangles, cage level 2, decimated to the budget (automatic retopology)
- Game evidence: bevel coverage 100% (0 mm raw hard edge of 0 mm feature edge, 0 mm baked); materials 1 (plastic #9a9893); value contrast 0.008; scales primary no (1 LOD3 part(s), min solidity 0.9832), secondary no (20.0% of LOD0 off LOD3), tertiary no (normal blue std 0.0, rg std 0.00329); silhouette complexity 0.0094 (front 0.9911, side 0.9905, top 0.9898, three_quarter 0.9911); wear no (max 0.0, edge mask 0.0%).
- Rubric: silhouette 0.5 (passes 0/0/0) [cap 2: The outline at 64 px is nearly convex (convexity deficit 0.027, under 0.06) and there is no detail: a blob.], proportion 0.5 (passes 0/0/0), continuity 2.0 (passes 2/2/2), radius_hierarchy 0.0 (passes 0/0/0), break_up 0.0 (passes 0/0/0) [cap 3: No secondary forms: LOD0 has no panel, bevel, trim or part that LOD3 drops.], detail_rhythm 0.0 (passes 0/0/0) [cap 2: One detail scale or none (none): missing primary, secondary, tertiary.], material 0.5 (passes 0/0/0) [cap 1: One material over everything; value contrast 0.01 (under 0.08: it reads as one flat tone); no edge wear (0.0% of the surface worn, under 2%).], would_sell 0.0 (passes 0/0/0); mean 0.44
- Blind pass 1 said: Featureless grey pebble blob with no breaks, no detail and one material.
- Blind pass 2 said: Featureless grey pebble blob in a single material, with no breaks or detail.
- Blind pass 3 said: Featureless grey egg-shaped blob with no structure, breaks or detail.
- Wall time 22.0 s.

## What failed

Technical: nothing failed.
Rubric: below the gate: Sci-fi helmet prop, Stylised treasure chest, Fantasy sword, Modular wall kit piece, Vehicle wheel, Remote control, CAD plus asset.
See each brief above for the measured reason.
