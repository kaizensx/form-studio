# Acceptance run

Generated 2026-11-15 23:20 by `scripts/acceptance.py` on this machine. Each row is what the run observed; rerun the script to reproduce it.

| Step | Result | s | Observed |
|---|---|---|---|
| 1 brief → parameters | **PASS** | 0.00 | project created from brief, recipe dock, 20 typed parameters in mm/deg/g |
| 2 constraints | **PASS** | 1.58 | constraint enforced before any geometry is saved: “Cable channel leaves under 1.2 mm of bridged roof beneath the pocket” → Raise the pocket floor or use a thinner channel. |
| 3 editable geometry (BREP) | **PASS** | 1.56 | build123d 0.13.0 / OCP 8.0.1.1: 1 valid solid, 56 faces attributed to 6 features, 166.4 cm³; step times {'geometry': 0.201, 'exports': 0.046, 'checks': 0.233, 'slice': 0.812} |
| 4 exports | **PASS** | 0.00 | STEP + STL written, units mm: acceptance-dock_r01.step (272 kB, sha256 09b63be9f465), acceptance-dock_r01.stl (429 kB, sha256 e3b64c101a8e) |
| 5 geometric checks | **PASS** | 0.00 | One valid solid PASS [computed] 1 solid; Interfaces as modelled PASS [computed] Δ 0.0000 mm; Export mesh is closed PASS [computed] 8,804 triangles; STL matches the CAD solid PASS [computed] 0.003% volume; Fits the build volume PASS [computed] 86.0 × 78.0 × 35.4 mm; Thinnest wall PASS [computed] 4.72 mm; Unsupported overhangs PASS [computed] 0 mm²; Bridged ceilings PASS [heuristic] 4.5 mm span; Plate contact PASS [heuristic] 6052 mm²; Tip-over resistance WARN [model] 0.74 N; Fit within tolerance window WARN [model] 70% modelled |
| 6 configured slicer inspection | **PASS** | 0.12 | Bambu Studio 02.09.01.70 with Bambu Lab A1 mini 0.4 nozzle / 0.28mm Extra Draft @BBL A1M / Generic PLA @BBL A1M: 89 min, 55.1 g, 127 layers, supports none; 127 layers parsed for inspection, path types: Bottom surface, Bridge, Floating vertical shell, Gap infill, Inner wall, Internal solid infill, Outer wall, Overhang wall, Sparse infill, Top surface |
| 7 revision: critical dimension invalidates outputs | **PASS** | 0.19 | draft rebuilt in 178 ms; interface change flagged: Pocket width, Pocket thickness; after commit r02: {'geometry': 'stale', 'exports': 'stale', 'checks': 'stale', 'slice': 'stale'}; release refused: Solid is stale (last made for r1). |
| 8 regenerated exports, checks, slice | **PASS** | 1.45 | regenerated as acceptance-dock_r02.stl (new sha256 f93697d54b81); pocket width re-measured on the solid: 72.200 mm; new G-code 35dee9080434 ≠ old 34d13545bc8d |
| 9 approval gate and supersession | **PASS** | 1.42 | released r02-836579 (4 files, hashes verified; Geometry computed · slice simulated · not physically validated); next commit marks it superseded (Solid, STEP + STL, Checks, Slice changed) |
| 10 project save / restore | **PASS** | 0.36 | archive 6283 kB → restored as “acceptance-dock-2” with 3 revisions; all artifacts recognised as current without rebuilding |
| 11 recovery from failed operations | **PASS** | 1.75 | infeasible fillet refused: “Edge radius needs a corner radius at least 1 mm larger” (Raise the corner radius or lower the edge radius.); kernel timeout: “The geometry kernel did not answer within 0.01 s and was restarted.” restarts 0→1; corrupt project.json: “project.json was unreadable; restored from the previous save.”; head still r03, kernel serving |
| 12 measured rebuild latency | **PASS** | 1.44 | 8 uncached parametric rebuilds with feature attribution and impact: median 181 ms, max 184 ms |
