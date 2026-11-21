# Mesh to editable CAD: benchmark

Written by `scripts/recon_bench.py` from real runs of `form/recon` on synthetic build123d parts (`tests/recon_fixtures.py`, exported as STL). Two numbers, never merged:

- **B-rep**: share of the result's surface that is real CAD faces (analytic, B-spline, or made by a feature) rather than a facet copy of the mesh, counted only when the result is within the tolerance.
- **Editable**: share of the result's Params that are real dimensions and move 0.5 mm with the part still building. *Feature area* is the share of the surface the parametric features make.

**Deviation** is the two-sided Hausdorff distance to the mesh. Computed, not assumed. Run: dev 2d484ea plus the candidate list with the gates in the ranking, hole filling and noise-tolerant reading; one worker.

The critics compare the result's STEP with the part (`form/recon/gates.py`, `form/recon/gms.py`):

- **Occupancy IoU**: both filled on one voxel grid (winding number, so orientation counts); intersection over union of the volumes.
- **GMS**: a GMS-compatible surface score (positions within 5 % of the part's largest extent, normals within 0 to 25 degrees); 1.0 is the same surface. Reimplemented on scipy, not yet cross-checked against the upstream code.
- **Gates**: `pass`, or which gates failed: *occupancy* (volume missing or added beyond a skin of the size-relative tolerance over the surface), *voids* (a void the part's slices enclose filled solid), *openings* (a hole, slot or pocket missing, added, or of another shape in a plane section). The time is what the gates took.
- **Scan artifacts**: `bolt_flange` with Gaussian vertex noise (0.01 mm), coordinates quantised to 0.02 mm, or 1 % of its triangles removed. Its critics are measured against the clean part. The pipeline fills small holes (form/recon/mesh.py fill_holes) and measures the noise; a noisy mesh is read through a denoised copy (form/recon/denoise.py) and verified against the mesh as given.
- **Gates in the pipeline**: since this run the pipeline itself ranks its candidates by verified, then these gates, then editable share, within 4 % of the budget (pipeline._Gates).

Optional learned engine (CAD-Recode, non-commercial licence): not installed on the machine that wrote this, so only *without* is measured.

| Class | Part | Tol (mm) | Triangles | B-rep | Editable | Params moving / all | Feature area | Deviation (mm) | Within tol | Occupancy IoU | GMS | Gates | Time (s) | Method | With learned engine |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bracket | filleted_bracket | 0.02 | 1800 | 90.89% | 75% | 6 / 8 | 90.89% | 0.001205 | yes | 1 | 0.9879 | pass (0.26 s) | 39.8 | sketches and extrusions | not installed |
| bracket | stepped_bracket | 0.02 | 3216 | 100% | 100% | 18 / 18 | 100% | 0.001711 | yes | 1 | 0.9774 | pass (0.38 s) | 112.5 | feature tree | not installed |
| flange | bolt_flange | 0.02 | 4812 | 100% | 100% | 9 / 9 | 100% | 0.01243 | yes | 0.9997 | 0.9673 | pass (0.52 s) | 16.9 | sketches and extrusions | not installed |
| turned shaft | turned_shaft | 0.02 | 10328 | 100% | 100% | 11 / 11 | 100% | 0.008252 | yes | 0.9995 | 0.9675 | pass (0.31 s) | 35.3 | sketches and extrusions | not installed |
| turned shaft | flanged_shaft | 0.02 | 13426 | 100% | 100% | 10 / 10 | 100% | 0.009965 | yes | 0.9996 | 0.9409 | pass (0.61 s) | 145 | feature tree | not installed |
| enclosure with holes | enclosure_with_holes | 0.02 | 4120 | 100% | 100% | 19 / 19 | 100% | 0.001191 | yes | 1 | 0.9794 | pass (0.24 s) | 153.9 | feature tree | not installed |
| filleted block | filleted_block | 0.02 | 9480 | 66.4% | 100% | 4 / 4 | 66.4% | 0.001446 | yes | 1 | 0.9723 | pass (0.46 s) | 162.6 | sketches and extrusions | not installed |
| scan artifacts | bolt_flange+noise | 0.05 | 4812 | 100% | 100% | 9 / 9 | 100% | 0.04187 | yes | 0.9995 | 0.9685 | pass (0.44 s) | 26.6 | sketches and extrusions | not installed |
| scan artifacts | bolt_flange+quantised | 0.05 | 4812 | 100% | 100% | 9 / 9 | 100% | 0.01696 | yes | 0.9998 | 0.9688 | pass (0.44 s) | 15 | sketches and extrusions | not installed |
| scan artifacts | bolt_flange+dropout | 0.05 | 4764 | 100% | 100% | 9 / 9 | 100% | 0.01243 | yes | 0.9995 | 0.9685 | pass (0.44 s) | 14.8 | sketches and extrusions | not installed |

Before this run (the previous version of this file, same parts):

| Part | B-rep before | B-rep now | Editable before | Editable now | Time before (s) | Time now (s) |
|---|---|---|---|---|---|---|
| filleted_bracket | 90.89% | 90.89% | 75% | 75% | 42.7 | 39.8 |
| stepped_bracket | 100% | 100% | 100% | 100% | 106.8 | 112.5 |
| bolt_flange | 100% | 100% | 100% | 100% | 16.3 | 16.9 |
| turned_shaft | 100% | 100% | 90.9% | 100% | 35.4 | 35.3 |
| flanged_shaft | 100% | 100% | 100% | 100% | 282.9 | 145 |
| enclosure_with_holes | 92.38% | 100% | 94.7% | 100% | 135.3 | 153.9 |
| filleted_block | 52.71% | 66.4% | 100% | 100% | 556.3 | 162.6 |
| bolt_flange+noise | 74.76% | 100% | 0% | 100% | 296.3 | 26.6 |
| bolt_flange+quantised | 100% | 100% | 100% | 100% | 14.8 | 15 |
| bolt_flange+dropout | 0% | 100% | – | 100% | 0.2 | 14.8 |

Per class, without the learned engine (median over its parts):

| Class | Parts | B-rep | Editable |
|---|---|---|---|
| bracket | 2 | 95.445% | 87.5% |
| flange | 1 | 100% | 100% |
| turned shaft | 2 | 100% | 100% |
| enclosure with holes | 1 | 100% | 100% |
| filleted block | 1 | 66.4% | 100% |
| scan artifacts | 3 | 100% | 100% |

Scan input, as the pipeline measured it: bolt_flange+noise noise 0.01013 mm (read through the denoised copy), bolt_flange+quantised noise 0 mm, bolt_flange+dropout noise 0 mm, 47 holes filled.

Largest gap between progress events: filleted_bracket 1.21 s, stepped_bracket 1.26 s, bolt_flange 1.18 s, turned_shaft 1.19 s, flanged_shaft 1.25 s, enclosure_with_holes 1.2 s, filleted_block 1.4 s, bolt_flange+noise 1.22 s, bolt_flange+quantised 1.17 s, bolt_flange+dropout 1.06 s.
