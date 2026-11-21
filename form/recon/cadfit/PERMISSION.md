# CADFit in Form Studio: licence and permission

**Form Studio's MIT licence does not cover this folder (`form/recon/cadfit/`).**

## Source

- Repository: https://github.com/ghadinehme/CADFit
- Pinned commit: `227a7acdc6972c646859d7e12da279e6e4ae2789`
- Work: CADFit, "Precise Mesh-to-CAD Program Generation with Hybrid Optimization" (ICML 2026), by Ghadi Nehme,
  Eamon Whalen and Faez Ahmed.
- Licence: Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0), kept verbatim in
  [`LICENSE`](LICENSE).

## Permission

The CADFit code in `vendor/` is CC BY-NC 4.0 by its author. It is included and modified in Form Studio with the
author's permission, as stated by the Form Studio project owner on 2026-11-21. That permission is the basis for
including it here; anyone reusing this folder outside Form Studio should read CADFit's licence and ask its author.

The other files in this folder (`__init__.py`, `_compat.py`, `cqrun.py`, `driver.py`, this file) were written for
Form Studio to run that code. They are kept in this folder and under the same terms so that the folder can be
removed, or licensed, as one unit.

The feature is off unless `[recon] cadfit = true` is set (or `FORM_RECON_CADFIT=1`), and needs the optional
`form-studio[cadfit]` libraries.

## What is included

Only the algorithm files the mesh-to-CAD search needs, fetched read-only at the pinned commit:

| File | Upstream file |
|---|---|
| `vendor/iou.py` | `iou.py` |
| `vendor/fit_primitives.py` | `fit_primitives.py` |
| `vendor/extract_planar_contours.py` | `extract_planar_contours.py` |
| `vendor/split_loops.py` | `split_loops.py` |
| `vendor/extract_sketches.py` | `extract_sketches.py` |
| `vendor/analyze_loop_translation.py` | `analyze_loop_translation.py` |
| `vendor/analyze_revolve_axis.py` | `analyze_revolve_axis.py` |
| `vendor/cadquery_ops.py` | `cadquery_ops.py` |
| `vendor/greedy_search.py` | `greedy_search.py` |
| `vendor/pipeline_steps.py` | an excerpt of `run_pipeline.py` (`_drop_nested_entries` only) |

Not included: `image_to_cad/` and anything Hunyuan3D (a separate licence), `filter_loops.py` (an optional DINOv2 loop
filter that downloads model weights), `refine_edges.py` (the fillet/chamfer pass, off by default upstream, written
for CadQuery), the rest of `run_pipeline.py` and `run_random_samples.py` (subprocess orchestration), `assets/`, and no
compiled `.pyc` file.

## Local modifications

Every vendored file keeps the authors' attribution in its header, followed by a "Modified for Form Studio" line that
names what changed in it. In all:

1. **No subprocess.** Upstream runs every generated CadQuery script with `subprocess.run([sys.executable, script])`
   (`cadquery_ops.execute_cadquery_script`, `greedy_search._rebuild_clean_stl`) and each pipeline step as its own
   program (`run_pipeline.py`). Here the scripts are parsed, never executed as programs, by `cqrun.py`, which accepts
   only the CadQuery subset CADFit writes and builds it with build123d (OCCT); exports may only be written inside the
   candidate's work folder. The steps run in one child process (`driver.py`), started and killed at a hard deadline
   by `__init__.py`.
2. **No pickle is loaded back** from disk (the greedy search's and the height search's on-disk caches are skipped).
3. **No file is written into the current directory** (`extract_planar_contours.py` wrote `decimated_mesh.stl` there;
   the decimated mesh is kept in memory).
4. **Optional libraries:** pymeshlab, matplotlib, tqdm and shapely are used when installed and not required
   (`_compat.py`: a sequential stand-in for the process pools, a numpy subset of shapely's polygon tests, no plots).
   Without pymeshlab the input mesh is kept as it is where upstream decimates it to 30 000 faces.
5. **Imports** between the files are relative (`from .iou import ...`), and `main()` of
   `extract_planar_contours.py` and `extract_sketches.py` takes an argument list so it can be called in-process.
6. **Bug fixes on paths upstream does not reach with shapely installed:** trimesh's `Line.discrete()` is given the
   path's vertices; the summary plot of the translation and revolve analyses is drawn only with `save_plots`.
7. **Environment:** the thread-count variables CADFit sets at import (`OMP_NUM_THREADS` and others) are set only when
   not already set (`setdefault`).

Nothing else in the algorithm (its thresholds, sweeps, greedy order, beam refinement or pruning) is changed.
