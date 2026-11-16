---
name: verify-print
description: Verify a FORM revision before calling it printable or ready — regeneration, checks, measured interfaces, views, simulated slice, evidence stage. Use when geometry or exports changed, and whenever the user asks "is it ready to print?" or "will it fit?".
---

# Verify before you say "ready"

FORM tools: `run_pipeline()`, `get_job()`, `get_project()`, `render()`, `slice_test_piece()`, `setup_status()`, `open_in()`.

1. `run_pipeline()` (poll `get_job()` if it is still running). Every output must be **current** for the head revision;
   stale, failed or missing outputs mean you are not looking at this design.
2. `get_project()`: read every check with its evidence class (computed, heuristic, model) and the gate reasons.
   Confirm solid count, envelope against the printer, and the **interface** dimensions measured off the solid — not
   only the overall size or the input values.
3. Look: `render(view="sheet")`, `render(view="bottom")`, and a section or highlight of the interface
   (`render(highlight="feature_id")`). Confirm the images are of the current revision.
4. Slice: read the slicer machine, nozzle, filament and plate from `get_project()`; a slice is a **simulation** with the
   slicer's estimates. Look at the first layer, overhangs, supports and interface layers in the app's layer view.
5. If the slicer or kernel is missing, `setup_status()` says what and the command to fix it. Ask the user to run
   `form setup`; never run fixes yourself. Finish the checks that do not need it and name the missing evidence.

Report the highest stage actually reached, with a PASS / FAIL / NOT RUN list tied to the revision number:
draft → geometry checked → sliced and inspected (simulated) → physically validated for stated conditions (only with a
real print the user reported). Never turn a failed or unexecuted check into a pass, and never delete a check to get a
clean report. `open_in(what="3mf")` opens the slicer project for the user; it does not print.
