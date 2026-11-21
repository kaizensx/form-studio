# Third-party notices

Form Studio is MIT licensed (see `LICENSE`). This file credits outside projects whose ideas Form Studio's code builds on,
and records any outside material it contains.

Each entry says what was taken and whether any code or material was copied. Most entries are ideas
**reimplemented** in Form Studio's own code, with no code copied ("Ideas reimplemented, no code copied"). Two entries
contain outside material, under their own licences: kulibinai/CADEvolve (exemplars hand-ported from its seed examples,
Apache License 2.0) and CADFit (its code included and modified, CC BY-NC 4.0, with its author's permission). Each entry
names the exact commit that was read.

## nickpagz/stl2step

- Source: https://github.com/nickpagz/stl2step, commit `ae32fab1f8d081b125d6ad8727c11bf5a0947fd4`
- Licence: Apache License 2.0
- Ideas taken from `src/stlstep/featurecheck.py`: the slice-occupancy IoU on three axes, the per-opening shape match,
  the internal-void gap and a tolerance relative to the part's size.
- Where: `form/recon/gates.py` (new code on numpy and scipy, with winding-number voxels and Form Studio's own plane
  sections, `form/remodel/sections.py`).
- Ideas reimplemented, no code copied.

## kulibinai/cadena (CADENA)

- Source: https://github.com/kulibinai/cadena, commit `b636649d1c59e4a4b52f5b683af18d6b136b082b`
- Licence: MIT
- Idea taken from `utils/gms.py`: the GMS metric. Surfaces are matched within a distance and an angle tolerance, the
  precision and recall of the matches are combined, and the score is the area over the curve across angle tolerances
  from 0 to 25 degrees.
- Where: `form/recon/gms.py`. It is new code on scipy's `cKDTree`, labelled "GMS-compatible". It has not been
  cross-checked number for number against the upstream code. `tests/test_recon_gates.py` runs that check when
  pykdtree is installed and `FORM_GMS_UPSTREAM` points at your own copy of upstream `utils/gms.py`.
- Benchmark data: `scripts/cadena_bench.py` can score Form Studio on CADENA-Bench
  (https://huggingface.co/datasets/kulibinai/cadena-bench, tagged MIT). It downloads the data only when you pass
  `--download`, writes nothing into this repository and publishes aggregates only. The dataset card says its meshes
  come from the MCB, TMCAD and CADNet corpora. Form Studio has not checked those licences, so no mesh from the dataset
  is in this repository.
- Ideas reimplemented, no code copied.

## pberlizov/ViminCADConverter

- Source: https://github.com/pberlizov/ViminCADConverter, commit `dd27fa2da6e5a5dade590244f6a3b2edea7f8dc4`
- Licence: MIT
- Idea taken from `benchmarks/cases.json`: testing a mesh converter against scan artifacts (vertex noise and other
  imperfections of real scans).
- Where: the "scan artifacts" class of `scripts/recon_bench.py`, with `tests/recon_fixtures.py` `scan_artifact`
  (Gaussian noise, quantised coordinates, missing faces). This is new code.
- Ideas reimplemented, no code copied.

## kulibinai/CADEvolve

- Source: https://github.com/kulibinai/CADEvolve @ e30e6358648df661247815c67414cd42079f8b41; dataset
  huggingface.co/datasets/kulibinai/cadevolve @ 7543a3c1103b72c71f40ec71d6cacd1a50a77a16
- Licence: Apache License 2.0, Copyright 2025 Lomonosov Moscow State University. Copy: form/exemplars/LICENSE-CADEvolve
- Use: twelve exemplars in form/exemplars (their META "origin" names the seed) are modified works, hand-ported from
  its seed examples to build123d / Form Studio. The opt-in corpus (`form install exemplars.cadevolve`) downloads only
  CADEvolve-G/parametric_generators.json and reads it as text; nothing from the ABC-* or ShapeNet-* folders is kept.
- Many of CADEvolve's seed examples come from the CadQuery documentation examples (CadQuery, Apache License 2.0,
  https://github.com/CadQuery/cadquery), credited here as well.

## kulibinai/cadmageddon

- Source: https://github.com/kulibinai/cadmageddon @ 368fb87
- Licence: MIT
- Ideas taken: the residual as a work list of missing and extra bodies with angles about an axis
  (`contrib/instruments/residual.py`), pick-best by residual (`scripts/pick_best.py`) and the stall rule
  (`agent_run.py`).
- Where: `form/remodel/residual.py` and the `reference_parts` topic of `form/design_guide.py`. This is new code.
- Ideas reimplemented, no code copied.

## ghadinehme/CADFit

- Source: https://github.com/ghadinehme/CADFit, commit `227a7acdc6972c646859d7e12da279e6e4ae2789`. Work: "CADFit:
  Precise Mesh-to-CAD Program Generation with Hybrid Optimization" (ICML 2026), by Ghadi Nehme, Eamon Whalen and Faez
  Ahmed.
- Licence: Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0). Copy:
  `form/recon/cadfit/LICENSE`.
- **Code copied and modified.** CADFit's algorithm files are included in `form/recon/cadfit/vendor/` and modified for
  Form Studio, with the author's permission, as stated by the Form Studio project owner on 2026-11-21. Every vendored
  file keeps its attribution and names its changes; `form/recon/cadfit/PERMISSION.md` lists the files, the functions
  taken and every change.
- **Form Studio's MIT licence does not cover `form/recon/cadfit/`.** The whole folder (the vendored code and the files
  written to run it) is under CADFit's terms, so it can be removed or licensed as one unit.
- Use: an optional mesh-to-CAD candidate, off unless `[recon] cadfit = true`, needing `pip install
  form-studio[cadfit]`. The packaged app does not include the vendored search code; it ships the hook and this
  folder's `LICENSE` and `PERMISSION.md`, and reports that CADFit needs form-studio[cadfit].
