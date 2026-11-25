# 3D printing (optional)

Printing is one way out of Form Studio among several, next to STEP for CAD and CNC, meshes for renders and the web, and game assets. It is off until you turn it on. Turn it on when you print and every design can be checked for your printer, sliced by your own slicer and played back layer by layer; leave it off and none of it gets in the way.

## Turn it on

- In the first-start launcher, tick **3D printing**, or later in **Settings › General › Set up for**.
- From a terminal: `form capabilities on print`.
- While it is off there is no printer chip, no Fit stage, no slicer install, no print rows in Review, no Printing tab and no print tools for agents. New designs are 3D models.
- If you printed with Form Studio before this became optional, a configured slicer or printer turns it on once at the first start.

## Every design has a purpose

A design is either **For 3D printing** or **Just a 3D model** (for rendering, CAD exchange, CNC, laser cutting, moulding or visualisation). Choose it on Home, change it in Describe, or from a terminal: `form purpose <project> model`.

A 3D model is checked as a model: size, a valid solid, a closed mesh, the STEP round trip, loads and assembly checks. Overhangs, bridges, plate contact, the build volume, nozzle walls, the fit model and the slice do not run, and Review says so.

## Your slicer, your presets

Form Studio does not replace your slicer. It drives the one you already use:

- Bambu Studio, OrcaSlicer, PrusaSlicer, SuperSlicer, QIDISlicer, ElegooSlicer and Snapmaker Orca.
- It finds every printer set up in every installed slicer and lets you choose printer, filament and process per design or as the default.
- OrcaSlicer 2.5 packed profiles (`.opc`) are read directly. A profile never has to be exported by hand.
- `form printers` lists them; agents use `list_printers` and `choose_printer`.

## Checks for a printed part

With printing on, Review adds the checks that matter on a printer: overhangs, bridges, plate contact, the build volume and nozzle walls, next to the checks every design gets. Each result says whether it was computed, a rule of thumb, a model or a simulation.

A slice is a simulation, not a print. Form Studio says so wherever it reports one.

## Fit

The gap between a printed cavity and the object it holds is modelled from three uncertainties: the object's dimension (measured, specified or assumed), your printer's bias and spread for this filament, and the tolerance window you accept. The Fit stage reports:

- the **chance the gap lands in the window**, with the chance of too tight and too loose
- a **section** through the interface with the clearance per side
- the **recommended clearance** for a centred gap
- the **cheapest way to raise the odds**: measure the object, print the fit coupon, or print a thin test ring cut from the real interface

Measurements from a printed fit coupon calibrate the printer profile and are reused by every later design. The fit yield is a model, and it is labelled as one.

## Slicing and watching it print

- **Watch it print.** The G-code is read back and played in 3D with a nozzle marker, line-type filters, a per-layer time chart and the slicer's own time and filament estimate. Jump to the next bridge or overhang wall.
- **Several plates.** A design whose parts do not fit one plate is laid out part by part on as many plates as needed, each in its own orientation and sliced, with time, filament and cost added up.
- **Copies on a plate:** does N fit, and how they pack.
- **Cost:** filament, electricity and machine time from the slice and your prices. Form Studio never guesses a price.

## Open in your slicer, ready to print

Review › **Open in Bambu Studio** (or OrcaSlicer, PrusaSlicer and the others) chooses the settings for this part on this printer and says why, one line each, labelled computed or heuristic: orientation, layer height, walls, top and bottom layers, infill, supports only where overhangs need them, a brim for tall, narrow or warping parts, the seam, the filament and the speed profile.

It starts from the slicer's preset and overrides only those keys, slices for real so time and grams show first, writes a project 3MF with the plate, the oriented part, the settings and the filament, and opens it in the slicer. `form slicer-open`; MCP `open_in_slicer`.

## Every printer you have, compared

Review › **Every printer** slices the design for real on each printer set up in each installed slicer, with its own process and filament, and shows time, filament and cost side by side, with the fastest, the least filament and the cheapest marked. `form compare-printers`.

## Releasing a printed part

A release of a design made for printing freezes STEP, STL, OBJ, GLB, 3MF and the G-code with SHA-256 hashes and a report of every check. Only you approve it. Form Studio never starts a print and never sends a file to a printer.

## Which slicers are tested

The official build of each slicer is installed in continuous integration and a design is sliced through Form Studio, on Linux and Windows. The versions and platforms are in [Compatibility and testing](https://github.com/kaizensx/form-studio/blob/main/docs/VERIFICATION.md), and a nightly matrix runs the sample designs through every slicer: [compatibility](https://kaizensx.github.io/form-studio/compat/).

## Tips

- Print the **fit coupon** once per printer and filament. It is the cheapest way to make fits land.
- Measure the thing the part must fit, and tell the agent how you measured it.
- If a slice fails, press **Fix**: the failure and its evidence go to the design's conversation.
- Talk printers, slicers, presets and filaments in #printing. For a problem, post in #help with the tag **3D printing**, your slicer and its version, your printer and what `form setup --check` printed.
