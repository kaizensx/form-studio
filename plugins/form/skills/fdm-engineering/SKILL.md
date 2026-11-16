---
name: fdm-engineering
description: Engineer a FORM part for FDM printing — orientation, material, load direction, walls, overhangs, supports, first layer, heat and creep. Use when choosing how a part is printed or what it is printed in, or when a part carries load or lives somewhere hot, wet or sunny.
---

# FDM engineering

FORM tools: `form_overview()`, `set_print_setup()`, `get_project()`, `render()`, `optimize()`, `preview_change()`.

Numbers here are starting hypotheses. The filament's datasheet, printed coupons and the selected slicer profile win.

1. Confirm printer, nozzle, material and plate from `form_overview()` (presets read from the slicer). Do not assume
   the installed nozzle or filament. Respect the printer envelope minus the plate margin.
2. Service conditions: load magnitude and direction, static / sustained / cyclic / impact, temperature, water, UV,
   chemicals. Material first candidates: PLA for indoor, stiff, low-temperature parts (creeps under sustained load,
   softens near 55 °C); PETG for general functional parts and damp places; TPU for grip and bumpers. Hot car, sun,
   weather or demanding load: reassess the polymer and process; do not promise PLA or PETG on an open printer is enough.
3. Orientation: `set_print_setup(orientation=...)` and read the orientation comparison in the checks. Choose it for the
   load path first (no small layer-bonded root in peel under sustained load), then visible faces and removable supports.
4. Walls: with a 0.4 mm nozzle start at 1.2–1.6 mm for low load and check the slice gives continuous perimeters
   (`min_wall_mm` in checks). Overhangs: 45° from vertical is a heuristic, not a limit; prefer chamfers and 45° ceilings.
   No sealed cavities that need support. Keep fit-critical features off the first layer or relieve the bottom edge,
   but not together with slicer elephant-foot compensation unless measured.
5. More infill does not fix a poor load path. For structural parts, separate rough estimates (`statics.*`, labelled
   model) from validated properties. Isotropic FEA or a datasheet modulus is not proof that a layered part is safe.
   Escalate to another material, process or qualified testing when the consequence of failure is high.

FORM never writes generic G-code and never starts a print. A slice is a simulation; report it as one.
