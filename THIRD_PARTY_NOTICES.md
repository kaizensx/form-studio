# Third-party notices

Form Studio is MIT licensed (see `LICENSE`). This file credits outside projects whose ideas Form Studio's code builds on,
and records any outside material it contains.

Each entry says what was taken and whether any code or material was copied. Most entries are ideas
**reimplemented** in Form Studio's own code, with no code copied ("Ideas reimplemented, no code copied"). Two entries
contain outside material, under their own licences: kulibinai/CADEvolve (exemplars hand-ported from its seed examples,
Apache License 2.0) and CADFit (its code included and modified, CC BY-NC 4.0, with its author's permission). Each entry
names the exact commit that was read. The last two sections list the libraries the app ships and the optional engines
that Settings › Software installs only when you ask.

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

## Standard-parts libraries that ship with the app

These are used as libraries (installed from PyPI, bundled in the packaged app by `packaging/form.spec`), not copied
into Form Studio's source. Form Studio's own tables in `form/parts.py` repeat a few of their published dimension
values (screw heads, nuts, washers, tap drills, bearings) so the common sizes work without them; a test checks the
tables against the library.

- **gumyr/bd_warehouse** 0.4.0 (https://github.com/gumyr/bd_warehouse, tag `v0.4.0`, commit
  `8e9be0645b53db3d7414f74828c2d67b0da21138`). Licence: Apache License 2.0. Used by `form/parts.py` for ISO screws,
  nuts, washers and heat-set inserts, ISO, trapezoidal, ACME and plastic-bottle threads, deep-groove bearings,
  roller-chain sprockets, ASME B16.5 flanges and the pipe-size table. Form Studio works around two 0.4.0 issues
  without changing the library: the ISO 1580 length list reads 6 and 8 mm as 68 (fixed upstream after 0.4.0), and
  `Pipe` does not resolve the materials "pvc", "steel" and "iron", so `parts.pipe` builds the tube from the size table.
- **bd_materials** 0.2.6 (https://github.com/bernhard-42/bd_materials, tag `v0.2.6`, commit
  `c3299932006f87ac44f063eed983fe46b67f1abb`; gumyr/bd_materials is a fork of it). Licence: Apache License 2.0.
  Used by `form/material_library.py` for densities and typical property ranges. bd_warehouse depends on it.
- **threejs-materials** 1.2.5 (https://github.com/bernhard-42/threejs-materials). Licence: Apache License 2.0.
  bd_materials reads its PBR values from it; the metal colours come from physicallybased.info (CC0 1.0). The packaged
  app leaves out its texture maps (`pbr_properties/_assets`, about 87 MB); Form Studio reads values only.
- **py_gearworks** 0.0.24 (https://github.com/GarryBGoode/py_gearworks). Licence: Apache License 2.0. Involute gear
  profiles, meshing and contact ratio in `form/parts.py` and `form/craft/mechanisms.py`.
- **gumyr/cq_warehouse** (https://github.com/gumyr/cq_warehouse, commit `a57bb7a24762d367d66369f280a24c38a64e73dd`).
  Licence: Apache License 2.0. Read for comparison only: it is the CadQuery predecessor of bd_warehouse, and CadQuery
  cannot share an environment with build123d here. bd_warehouse covers its fasteners, threads, bearings and
  sprockets; its `Chain` (a chain wrapped over sprockets at any positions) has no build123d port, and Form Studio's
  two-sprocket `chain_drive` uses the standard chain-length formula instead. Nothing copied.

## Optional engines, installed only when you ask

None of these is bundled. Settings › Software (or `form install`) installs each one into an environment of its own
under the data folder (`form/engines.py`), showing its size and licence first. The versions are the pins in
`form/engines.py`; licences are from each package's published metadata or the project's own licence file.

- **CAD-Recode** (learned mesh-to-CAD, `recon.learned`). Weights: https://huggingface.co/filapro/cad-recode, licence
  Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0), **non-commercial use only**; the
  download refuses to start until that licence is accepted. Its code (https://github.com/filaPro/cad-recode) is
  CC BY-NC 4.0 too (`LICENSE.md`). The model is built on Qwen2-1.5B (https://huggingface.co/Qwen/Qwen2-1.5B,
  Apache License 2.0), whose tokenizer files are downloaded with the weights. Form Studio ships neither the weights nor
  CAD-Recode's code. Libraries in its environment: PyTorch 2.11.0 (BSD-3-Clause), transformers 4.57.6, safetensors
  0.8.0, tokenizers 0.22.2 and huggingface-hub 0.36.2 (Apache License 2.0), NumPy 2.5.5 (BSD-3-Clause, with parts
  under 0BSD, MIT, Zlib and CC0-1.0).
- **CADFit** (`recon.cadfit`): its code is in this repository (see ghadinehme/CADFit above). Libraries in its
  environment: build123d 0.13.0 (Apache License 2.0), NumPy 2.5.4, SciPy 1.18.1 and scikit-learn 1.9.1
  (BSD-3-Clause), trimesh 5.2.1 (MIT), manifold3d 3.5.5 (Apache License 2.0).
- **CoACD** 1.0.14 (game collision, `game.coacd`; https://github.com/SarahWeiii/CoACD). Licence: MIT. With NumPy 2.5.4.
- **uv** 0.13.7 (https://github.com/astral-sh/uv), downloaded from its GitHub release and checked against a pinned
  SHA-256 before use, makes these environments. Licence: MIT OR Apache-2.0. The Python 3.12 it installs for them is
  CPython (Python Software Foundation License) from uv's managed builds.
