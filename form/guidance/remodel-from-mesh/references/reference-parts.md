REFERENCE PARTS: meshes (STL, OBJ, 3MF) the person gives you to understand, make editable, or rebuild
When someone brings meshes and wants them editable, understood or changed, rebuild them as clean CAD: named features
and Params, like a part designed from scratch. The meshes stay blueprint references, never the design.

FIRST: triage(path), or reconstruct(path), which runs it. This workflow is for a MECHANICAL part whose reconstruction
was not editable enough. A sculpt, a scan or a figure (triage: organic) is not rebuilt as features: reconstruct makes
it a surface body or a mesh body, and features are added to that (design_guide topic "organic", SCULPTED MESHES).

NEVER
  * never embed the raw meshes as the design (self.reference("part.stl") as the body): nothing is editable, every
    triangle is a face, and the viewport is a wireframe of facets. A reference mesh is only for looking and comparing.
  * never guess what a mechanism does from its outline: measure it (analyze_assembly) and read the sections.

STAGES
  1. Import every mesh into the project: import_reference(project, path), one per part, keeping their coordinates.
     "Make editable" (reconstruct) is the deterministic route; when it does not reach a verified Layer 2 recipe, do
     this workflow instead.
  2. analyze_reference(project, reference) for each mesh: principal axes, section pictures with dimensions (look at
     them), vector outlines, and features with sizes: holes, bosses, openings (pockets, slots, cutouts), walls, ribs,
     rails and grooves, plates, steps (levels), ramps with angles, draft, fillets and chamfers with radii and widths,
     detail areas (text, embossing, knurls), symmetry and wall thicknesses. Ask for sections where you need them
     (levels={"z": [3.2, 6.5]}).
  3. Several parts: analyze_assembly(project, references=[fixed part first, ...]) gives mating surfaces and clearances,
     each part's travel (slide axes with their range, hinge axes with their range, bumps on the way: detents, snaps or
     flexing arms) and couplings (a slide meshing with a part that turns: rack and gear or cam, with the ratio; a slide
     on a leaning face: a ramp, with the lift per mm). State the mechanism in one sentence before modelling it.
  4. Plan: the features in build order, each named after what it is ("base_plate", "side_rail", "card_slot",
     "pivot_pin", "rack", "cascade_steps"), with the dimension that drives it as a Param (card slot width, wall
     thickness, rail clearance, ramp angle, step height, pin diameter). Read sizes off the analysis: round to the
     designer's evident grid (0.1 mm, 0.5 mm, whole degrees) when the mesh agrees within the tolerance.
  5. Write clean build123d (algebra API, design_guide core): sketch the main profile from the section outlines and
     extrude it, then cut pockets and slots, add rails and ribs, then holes, then chamfers and fillets last. One Stage
     per feature. Model in the meshes' coordinates so the comparison lines up. For several parts: one Part per mesh
     (solid=(x, y, z) a point inside it, move=(0, 0, 0) when modelled in place) and the joints analyze_assembly found
     (slide(part, axis, (lo, hi)), hinge(part, axis, origin, (lo, hi))), Mate() for pins in holes; gears and racks are
     not joints: model their teeth in mesh and put the ratio in derived().
  6. compare_to_reference(project, reference, part=...) after every build: two-sided Hausdorff, the worst regions
     with where they are and whether the design has too much or too little material there, and per-feature
     differences (the design's diameters and radii next to the mesh's). Fix the worst first.
  7. Refine until every part is within the tolerance. The default for a remodel is 0.1 mm (two-sided Hausdorff);
     say which tolerance you used. Where you choose not to follow the mesh (scan noise, a facet artefact, text you
     left out), say where and by how much; never hide a difference.

THE RESIDUAL LOOP (one feature at a time, kept only when it helps)
  a. Measure first (analyze_reference), then build the main body only.
  b. reference_residual(project, reference, part=...): the work list. missing bodies are material the mesh has and
     the design lacks (add them); extra bodies are material the design has and the mesh lacks (cut them). Each has
     its volume, centre, axis, size and shape; alike bodies come grouped as one pattern (polar at equal angles with
     the radius and start angle, linear with a pitch, grid with two pitches). Write down residual_pct.
  c. Build ONE line of the work list as one feature (a pattern is one feature with a count and a pitch Param), then
     run reference_residual again. Keep the change only if residual_pct dropped; otherwise go back to the previous
     revision (checkout_revision) and try the next line or a different reading of the same one.
  d. Stop after 3 steps in a row that did not lower residual_pct (stalled): more of the same will not help. Say what
     is left and why.
  e. When no body is left, the difference is in the sizes: fit_params(project, reference, params=[...]) tunes only
     the Params the design declares, inside their limits, and keeps the result only if the design gets closer. Then
     compare_to_reference for the tolerance.
  f. Deliver the revision with the smallest residual you reached (not simply the last one): name it, give its
     residual_pct and its Hausdorff, and say where it still differs.

TIPS
  * Sections across the up axis give the plan shapes (outlines and openings); sections along it give the steps,
    rails and chamfers in profile.
  * A narrow strip between two planes is usually a chamfer or a fillet; equal strips around a rim are one edge
    treatment with one Param.
  * Repeated openings with a pitch are one feature with a count and a pitch Param.
  * A "bump" in the travel of a slide is often a flexing detent arm: model the arm and its bump as features.
  * measure(project, at=[x, y, z]) and measure(project, from_point=[...], to_point=[...]) check single values on
    your design.
