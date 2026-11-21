# Mesh to editable CAD: benchmark

Written by `scripts/recon_bench.py` from real runs of `form/recon` on synthetic build123d parts (`tests/recon_fixtures.py`, exported as STL). Two numbers, never merged:

- **B-rep**: share of the result's surface that is real CAD faces (analytic, B-spline, or made by a feature) rather than a facet copy of the mesh, counted only when the result is within the tolerance.
- **Editable**: share of the result's Params that are real dimensions and move 0.5 mm with the part still building. *Feature area* is the share of the surface the parametric features make.

**Deviation** is the two-sided Hausdorff distance to the mesh. Computed, not assumed.

Optional learned engine (CAD-Recode, non-commercial licence): not installed on the machine that wrote this, so only *without* is measured.

| Class | Part | Tol (mm) | Triangles | B-rep | Editable | Params moving / all | Feature area | Deviation (mm) | Within tol | Time (s) | Method | With learned engine |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bracket | filleted_bracket | 0.02 | 1800 | 90.89% | 75% | 6 / 8 | 90.89% | 0.001205 | yes | 41.7 | sketches and extrusions | not installed |
| bracket | stepped_bracket | 0.02 | 3216 | 100% | 100% | 18 / 18 | 100% | 0.001711 | yes | 106 | feature tree | not installed |
| flange | bolt_flange | 0.02 | 4812 | 100% | 100% | 9 / 9 | 100% | 0.01243 | yes | 15.9 | sketches and extrusions | not installed |
| turned shaft | turned_shaft | 0.02 | 10328 | 100% | 90.9% | 10 / 11 | 100% | 0.008252 | yes | 35 | sketches and extrusions | not installed |
| turned shaft | flanged_shaft | 0.02 | 13426 | 100% | 100% | 10 / 10 | 100% | 0.009965 | yes | 271.1 | feature tree | not installed |
| enclosure with holes | enclosure_with_holes | 0.02 | 4120 | 92.38% | 94.7% | 18 / 19 | 92.38% | 0.008697 | yes | 145.2 | sketches and extrusions | not installed |
| filleted block | filleted_block | 0.02 | 9480 | 52.71% | 100% | 4 / 4 | 66.4% | 0.001446 | yes | 819.7 | sketches and extrusions | not installed |

Per class, without the learned engine (median over its parts):

| Class | Parts | B-rep | Editable |
|---|---|---|---|
| bracket | 2 | 95.445% | 87.5% |
| flange | 1 | 100% | 100% |
| turned shaft | 2 | 100% | 95.45% |
| enclosure with holes | 1 | 92.38% | 94.7% |
| filleted block | 1 | 52.71% | 100% |

Before this round (the same bench on dev at 883372a, same machine, same parts):

| Part | B-rep | Editable | Params moving / all | Time (s) | Method |
|---|---|---|---|---|---|
| filleted_bracket | 90.89% | 75% | 6 / 8 | 45.3 | sketches and extrusions |
| stepped_bracket | 100% | 100% | 18 / 18 | 104.1 | feature tree |
| bolt_flange | 100% | 83.3% | 10 / 12 | 15.0 | sketches and extrusions |
| turned_shaft | 91.13% | 62.5% | 5 / 8 | 61.1 | sketches and extrusions |
| flanged_shaft | 100% | 100% | 10 / 10 | 261.4 | feature tree |
| enclosure_with_holes | 92.38% | 84.2% | 16 / 19 | 123.8 | sketches and extrusions |
| filleted_block | – | – | – | – | crashed: segmentation fault in OpenCascade defeaturing (twice) |

Largest gap between progress events: filleted_bracket 1.37 s, stepped_bracket 2.21 s, bolt_flange 1.17 s, turned_shaft 1.09 s, flanged_shaft 15.91 s, enclosure_with_holes 8.4 s, filleted_block 1.63 s.
