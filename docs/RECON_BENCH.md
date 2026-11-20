# Mesh to editable CAD: benchmark

Written by `scripts/recon_bench.py` from real runs of `form/recon` on the synthetic fixtures in `tests/recon_fixtures.py` (build123d parts exported as STL). **Editable** is the share of the result's surface that its Params make; **deviation** is the two-sided Hausdorff distance to the mesh. *Before* is the same pipeline without the program route (Layer 1 surfaces and the feature tree only). Computed, not assumed.

Median editable after: **100%** over 8 parts.

| Part | Tol (mm) | Triangles | Before: editable, deviation, time | After: editable | After: deviation (mm) | Within tol | After: time (s) | Method | Params | Params that change the part and rebuild over 80% of their range |
|---|---|---|---|---|---|---|---|---|---|---|
| box_with_holes | 0.02 | 2552 | 100%, 0.001243 mm, 18.2 s | 100% | 0.001243 | yes | 12.5 | sketches and extrusions | 7 | 5 of 7 |
| stepped_bracket | 0.02 | 3216 | 100%, 0.001711 mm, 48.9 s | 100% | 0.001711 | yes | 160.5 | feature tree | – | – |
| filleted_bracket | 0.02 | 1800 | 100%, 0.00119 mm, 51.5 s | 90.89% | 0.001205 | yes | 47.7 | sketches and extrusions | 8 | 7 of 8 |
| turned_part | 0.02 | 9828 | 100%, 0.004635 mm, 41 s | 100% | 0.004635 | yes | 136.2 | feature tree | – | – |
| flanged_shaft | 0.02 | 13426 | 100%, 0.009965 mm, 67.1 s | 100% | 0.009965 | yes | 291.7 | feature tree | – | – |
| gear | 0.05 | 3708 | 100%, 0.03831 mm, 14.4 s | 100% | 0.03831 | yes | 14.6 | spur gear | – | – |
| organic_blob | 0.02 | 44778 | 8.64%, 0.007715 mm, 243.3 s | 8.64% | 0.007715 | yes | 251.8 | feature tree | – | – |
| wallet_plate | 0.02 | 3504 | 0%, 0.004035 mm, 235.9 s | 100% | 0.005382 | yes | 14.5 | sketches and extrusions | 25 | 22 of 25 |

Largest gap between progress events, after: box_with_holes 1.25 s, stepped_bracket 2.91 s, filleted_bracket 1.95 s, turned_part 1.47 s, flanged_shaft 19.2 s, gear 1.25 s, organic_blob 15.88 s, wallet_plate 1.22 s.
