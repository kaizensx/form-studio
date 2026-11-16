---
name: print-feedback
description: Turn a real print's outcome into the next FORM revision — failed prints, warping, poor fit, broken parts, photos of the result, printer state. Use when the user reports what happened after printing.
---

# Print feedback

FORM tools: `get_project()`, `record_physical_result()`, `compare_revisions()`, `preview_change()`, `commit_change()`,
`form_overview()`.

1. Collect what distinguishes causes: photos under ordinary light, the measured deviation (calipers), material and
   nozzle, orientation, which revision was printed and any slicer setting the user changed. Ask only for evidence
   that separates causes.
2. Separate geometry causes (wrong interface, thin root), process causes (first layer, cooling, supports, seam) and
   material causes (moisture, creep, heat). Rank the plausible causes and propose the smallest test that tells them
   apart. Change one variable at a time where you can.
3. Record only what the user observed: `record_physical_result(kind="fit", result=...)` for this part, or
   `kind="widths"` for measured pairs. Never record a result the user did not report.
4. Keep the printed revision; make the fix a new revision (`preview_change()`, then `commit_change()` with a note that
   names the observation). `compare_revisions()` shows what changed since the printed one.

Printer state: `form_overview()` reports the configured printer. FORM only reads; it never starts, pauses or uploads a
print. A camera frame or status is only as fresh as its timestamp: do not infer adhesion or a successful print from a
stale frame, and do not claim to be monitoring a print. Never promise strength from appearance.
