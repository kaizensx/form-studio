---
name: fit-calibration
description: Get a printed fit right in FORM — clearance conventions, the modelled fit yield and its uncertainty, fit coupons, test pieces and calibrating from measured coupons. Use when something must slide, press, snap or drop into the part, or when a fit came out tight or loose.
---

# Fit and calibration

FORM tools: `get_project()`, `set_print_setup()`, `slice_test_piece()`, `create_project()`, `record_physical_result()`,
`preview_change()`, `commit_change()`.

Conventions
- Per side versus total: for a radial clearance c, hole = shaft + 2c. A total gap of 0.30 mm is 0.15 mm per side.
  Say which one you mean every time.
- Keep nominal dimensions, the clearance parameter and process compensation separate.
- The acceptable total gap is the project's fit window: `set_print_setup(fit_gap_min_mm=..., fit_gap_max_mm=...)`.

The fit model
- `get_project()` reports a fit yield: the modelled share of prints whose gap lands in the window, from the measured
  object's uncertainty (σ), the printer's calibration and the clearance. It is a statistical model, not print success.
- Compare the uncertainty contributions and ask for the smallest measurement that would narrow the biggest one
  (often: measure the mating object with calipers, three readings).

Evidence, cheapest first
1. `slice_test_piece()`: a thin ring through the fit interface of this revision, sliced (simulated time and material).
2. A sweep coupon: `create_project(recipe="coupon")` varies one clearance; sweep one variable at a time.
3. After the user prints and measures: `record_physical_result(kind="widths", widths=[{"nominal":..,"measured":..}],
   source="coupon")` calibrates this printer profile; `kind="fit", result="too_tight|good|too_loose"` records this part.
   Only values the user reported. Record printer, nozzle, material, orientation and layer height in the note.
4. Change only the parameters the evidence supports, `preview_change()`, then `commit_change()`.

Do not transfer a calibration blindly between materials, nozzle sizes, or upright and horizontal holes. Snap fits need
their real geometry printed; a flat clearance coupon does not test strain, root radius or relaxation.
