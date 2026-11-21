# Mesh to editable CAD: benchmark

Written by `scripts/recon_bench.py` from real runs of `form/recon` on synthetic build123d parts (`tests/recon_fixtures.py`, exported as STL). Two numbers, never merged:

- **B-rep**: share of the result's surface that is real CAD faces (analytic, B-spline, or made by a feature) rather than a facet copy of the mesh, counted only when the result is within the tolerance.
- **Editable**: share of the result's Params that are real dimensions and move 0.5 mm with the part still building. *Feature area* is the share of the surface the parametric features make.

**Deviation** is the two-sided Hausdorff distance to the mesh. Computed, not assumed. Run: dev f5210ea plus the critics, one worker.

The critics compare the result's STEP with the part (`form/recon/gates.py`, `form/recon/gms.py`):

- **Occupancy IoU**: both filled on one voxel grid (winding number, so orientation counts); intersection over union of the volumes.
- **GMS**: a GMS-compatible surface score (positions within 5 % of the part's largest extent, normals within 0 to 25 degrees); 1.0 is the same surface. Reimplemented on scipy, not yet cross-checked against the upstream code.
- **Gates**: `pass`, or which gates failed: *occupancy* (volume missing or added beyond a skin of the size-relative tolerance over the surface), *voids* (a void the part's slices enclose filled solid), *openings* (a hole, slot or pocket missing, added, or of another shape in a plane section). The time is what the gates took.
- **Scan artifacts**: `bolt_flange` with Gaussian vertex noise (0.01 mm), coordinates quantised to 0.02 mm, or 1 % of its triangles removed. Its critics are measured against the clean part.

Optional learned engine (CAD-Recode, non-commercial licence): not installed on the machine that wrote this, so only *without* is measured.

| Class | Part | Tol (mm) | Triangles | B-rep | Editable | Params moving / all | Feature area | Deviation (mm) | Within tol | Occupancy IoU | GMS | Gates | Time (s) | Method | With learned engine |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bracket | filleted_bracket | 0.02 | 1800 | 90.89% | 75% | 6 / 8 | 90.89% | 0.001205 | yes | 1 | 0.9879 | pass (0.27 s) | 42.7 | sketches and extrusions | not installed |
| bracket | stepped_bracket | 0.02 | 3216 | 100% | 100% | 18 / 18 | 100% | 0.001711 | yes | 1 | 0.9774 | pass (0.39 s) | 106.8 | feature tree | not installed |
| flange | bolt_flange | 0.02 | 4812 | 100% | 100% | 9 / 9 | 100% | 0.01243 | yes | 0.9997 | 0.9673 | pass (0.53 s) | 16.3 | sketches and extrusions | not installed |
| turned shaft | turned_shaft | 0.02 | 10328 | 100% | 90.9% | 10 / 11 | 100% | 0.008252 | yes | 0.9995 | 0.9675 | pass (0.31 s) | 35.4 | sketches and extrusions | not installed |
| turned shaft | flanged_shaft | 0.02 | 13426 | 100% | 100% | 10 / 10 | 100% | 0.009965 | yes | 0.9996 | 0.9409 | pass (0.65 s) | 282.9 | feature tree | not installed |
| enclosure with holes | enclosure_with_holes | 0.02 | 4120 | 92.38% | 94.7% | 18 / 19 | 92.38% | 0.008697 | yes | 0.9868 | 0.9791 | pass (0.42 s) | 135.3 | sketches and extrusions | not installed |
| filleted block | filleted_block | 0.02 | 9480 | 52.71% | 100% | 4 / 4 | 66.4% | 0.001446 | yes | 1 | 0.9723 | pass (0.46 s) | 556.3 | sketches and extrusions | not installed |
| scan artifacts | bolt_flange+noise | 0.05 | 4812 | 74.76% | 0% | 0 / 1 | 0% | 0.03872 | yes | 0.9987 | 0.9538 | pass (0.56 s) | 296.3 | feature tree | not installed |
| scan artifacts | bolt_flange+quantised | 0.05 | 4812 | 100% | 100% | 9 / 9 | 100% | 0.01696 | yes | 0.9998 | 0.9688 | pass (0.46 s) | 14.8 | sketches and extrusions | not installed |
| scan artifacts | bolt_flange+dropout | 0.05 | 4764 | 0% | – | – / – | – | – | no | – | – | no STEP | 0.2 | The mesh is not closed (1 open boundaries, 0 non-manifold edges), so it does not bound a s | not installed |

Before this run (the previous version of this file, same parts):

| Part | B-rep before | B-rep now | Editable before | Editable now | Time before (s) | Time now (s) |
|---|---|---|---|---|---|---|
| filleted_bracket | 90.89% | 90.89% | 75% | 75% | 41.7 | 42.7 |
| stepped_bracket | 100% | 100% | 100% | 100% | 106 | 106.8 |
| bolt_flange | 100% | 100% | 100% | 100% | 15.9 | 16.3 |
| turned_shaft | 100% | 100% | 90.9% | 90.9% | 35 | 35.4 |
| flanged_shaft | 100% | 100% | 100% | 100% | 271.1 | 282.9 |
| enclosure_with_holes | 92.38% | 92.38% | 94.7% | 94.7% | 145.2 | 135.3 |
| filleted_block | 52.71% | 52.71% | 100% | 100% | 819.7 | 556.3 |
| bolt_flange+noise | new | 74.76% | new | 0% | – | 296.3 |
| bolt_flange+quantised | new | 100% | new | 100% | – | 14.8 |
| bolt_flange+dropout | new | 0% | new | – | – | 0.2 |

Per class, without the learned engine (median over its parts):

| Class | Parts | B-rep | Editable |
|---|---|---|---|
| bracket | 2 | 95.445% | 87.5% |
| flange | 1 | 100% | 100% |
| turned shaft | 2 | 100% | 95.45% |
| enclosure with holes | 1 | 92.38% | 94.7% |
| filleted block | 1 | 52.71% | 100% |
| scan artifacts | 3 | 74.76% | 0% |

Largest gap between progress events: filleted_bracket 1.39 s, stepped_bracket 2.03 s, bolt_flange 1.18 s, turned_shaft 1.04 s, flanged_shaft 16.74 s, enclosure_with_holes 8.57 s, filleted_block 1.72 s, bolt_flange+noise 1.42 s, bolt_flange+quantised 1.19 s, bolt_flange+dropout 0.14 s.
