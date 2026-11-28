# Starts from a photo, and from a motion

Two ways to begin a design from something other than words: a photo of a flat part beside an object of known size,
and a statement of how a linkage must move.

| | Photo to profile | Four-bar synthesis |
|---|---|---|
| Code | `form/phototrace.py` | `form/linkage/` |
| MCP | `photo_profile` | `linkage_synthesis` |
| Terminal | `form photo-profile PHOTO ...` | `form linkage motion \| function \| path ...` |
| Tests | `tests/test_phototrace.py` | `tests/test_linkage.py` |

## Photo plus scale to a profile

Take the photo square on, the part lying beside the reference on a plain background of another colour.

1. **Foreground.** Each pixel's distance in colour from the background (the median of the image's border), smoothed
   with a 1-pixel Gaussian; the threshold between background and objects by Otsu's method.
2. **Edges and contours.** The level line is traced by marching squares with the crossing interpolated along each
   pixel edge, so the outline is at sub-pixel positions. Each object is then traced again at half its own height
   above the background: one threshold for the whole photo sits at a different fraction of a dark part's edge and a
   pale card's edge. Holes are the loops inside the part.
3. **Scale.**

   | Reference | What it gives |
   |---|---|
   | `{"kind": "card"}` | An ISO/IEC 7810 ID-1 card, 85.60 × 53.98 mm. Its four sides are fitted as lines, their intersections are the corners, and the homography of those four points onto the card's rectangle maps pixels to millimetres in the card's plane: perspective in that plane is removed. |
   | `{"kind": "coin", "coin": "eur_1"}` or `"diameter_mm"` | Scale only. Euro coins from the ECB's diameters, US coins from the US Mint's. An ellipse means the camera was tilted; the axis ratio is reported. |
   | `{"kind": "scale", "points": [[x, y], [x, y]], "length_mm": L}` | Scale only: two pixel points a known distance apart, such as two ruler marks. |

4. **Lines and arcs.** The outline is simplified (Douglas and Peucker) at a tolerance above the pixel noise (1.5
   pixels by default), runs that fit a circle become arcs (Kasa's fit, then the geometric residual), the rest are
   lines by total least squares. Neighbours are joined where they intersect; a line that touches an arc meets it at
   the foot of the arc's centre on the line, and the sketch gets a tangent constraint.
5. **A `form.sketch2d` profile**: points, lines, arcs and circles, horizontal and vertical where a line is within
   1.5° of an axis, and the driving dimensions (each radius and diameter, each hole's position, each length that
   still takes a degree of freedom away).

OpenCV is Apache-2.0 and scikit-image is BSD; both are usable under this project's licence. Neither is needed for
these steps, so the pipeline is Pillow and numpy and adds no dependency.

### Uncertainty

Every dimension carries ± at k = 2 (about 95 %):

    U(D) = 2 √( (√2 u_edge / s)² + (D u_s / s)² )

- `u_edge` = 0.5 pixel: how well one edge is located (assumed; the blur and the threshold). A length spans two edges.
- `u_s / s`: the scale's relative uncertainty, from the reference's own tolerance (the card's ISO limits; a coin's
  0.1 mm, assumed; a ruler's 0.25 mm, assumed unless given) and the same edge term over the reference's length.
- A radius read from an arc is worse by 1 / (1 − cos(sweep / 2)); a line that ends at a tangent arc carries the
  arc's centre.

Not in the figure, and returned as `uncertainty.not_included`: parallax (a part thicker than the reference, or not
in its plane, reads large), lens distortion, and for coin and scale references any tilt of the camera.

Every dimension is marked **estimated from the photo** and `how_known: assumed`. `build=True` writes a design (the
profile extruded by `depth`, which a photo does not show and is assumed); its parameters are assumed, never measured.

### Verification

Synthetic photos drawn at a known scale: a 60 × 40 mm bracket with a 12 mm corner radius and a 10 mm hole.

| Photo | Largest error | Stated ± (k = 2) |
|---|---|---|
| Card, 6 px/mm, square on | 0.03 mm on 60 mm; radius 0.02 mm | 0.37 mm; radius 0.72 mm |
| Card, part turned 17°, noise | 0.06 mm on 60 mm | 0.37 mm |
| Card, 3 px/mm | 0.13 mm on 28 mm | 1.58 mm (ends at an arc) |
| Card, camera tilted (card reads as a trapezium, sides 3.9 % apart) | 0.13 mm on 60 mm | 0.37 mm |
| One-euro coin, 7 px/mm | 0.07 mm on 28 mm | 0.72 mm |

All dimensions lie within their stated uncertainty in every case (`tests/test_phototrace.py`).

## Four-bar linkage synthesis

| Mode | Give | Method | Result |
|---|---|---|---|
| `motion` | three poses of the coupler, `{"at": [x, y], "angle": deg}` | Burmester theory for three positions in the standard dyad form (Erdman and Sandor): W (e^{iβⱼ} − 1) + Z (e^{iαⱼ} − 1) = δⱼ, linear in W and Z once the grounded link's two rotations are chosen. The free choices are searched on a grid. | Exact at the three poses |
| `function` | three pairs of input and output angles | Freudenstein's equation K₁ cos ψ − K₂ cos φ + K₃ = cos(φ − ψ), three linear equations | Exact at the three pairs |
| `path` | 4 to 60 target points of a coupler curve | nine numbers by differential evolution and a Nelder-Mead polish on the mean squared distance from each target to the curve; deterministic for a seed | An approximation: RMS and largest error returned |

Checks on every result:

- **Grashof** and the class (crank-rocker, double crank, double rocker, triple rocker).
- **Transmission angle** over the driven range against 40° (Norton, *Design of Machinery*, sect. 3.3: a guideline).
- **Branch defect**: the positions must lie on one assembly mode.
- **Order and circuit defect**: the driver must reach the positions 1, 2, 3 in one direction without passing a
  dead point.

**Verification by simulation.** The linkage is written as an assembly (three hinges and the loop that pins the
coupler to the rocker) and played by `form/motion.py`, whose Newton solver knows nothing of the synthesis. For
`motion` and `function` the point and angle at each position are compared with the targets (accepted: 1e-4 mm and
1e-4°). For `path` the distance from each target to the simulated path is returned.

`build=True` writes the linkage as a design: four bars stacked in layers, with that assembly, and plays it again on
the real parts. Pins are coincident axes; no pin hardware is modelled.

### Verification

| Check | Reference | Result |
|---|---|---|
| Dyad equation, 50 random free choices | 0 | under 1e-9 mm |
| Coupler through three poses, closed form | the poses | under 1e-9 mm, 1e-9° |
| The same, played by the motion solver | the poses | 5e-10 mm, PASS |
| Freudenstein from a known linkage (20, 60, 50, 55) | its lengths | equal to 1e-6 mm |
| Transmission angle of that linkage | closed form at the crank in line with the ground | within 0.02° |
| Path through 16 points of that linkage's coupler curve (41 mm across) | 0 | RMS 0.11 mm, largest 0.23 mm (0.6 %) |

## What they do not do

- The photo gives a profile, not a solid: one view, one depth that you supply.
- Ruler marks are not read automatically; you give two pixel points.
- Synthesis is for planar four-bars with revolute joints: no sliders, no six-bars, no four or five precision
  positions.
- Path synthesis does not prescribe timing, and a different seed can find a different linkage.
