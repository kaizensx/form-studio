SKELETON FIRST, ONE VALIDATED FEATURE AT A TIME (do this for every design that is more than a block)
  1. Write the design as a FeatureDesign: one @feature method per feature, in build order. The first one returns the
     skeleton (the main body only); each later one takes the body so far and returns the body after it. Declare
     every Param up front: one that names a feature not written yet waits for it (changing params later changes
     the shared code and rebuilds every feature).
  2. create_design with the skeleton feature only. It is on screen in seconds. render / look at the sheet before
     you commit to more.
  3. Add one feature per call: add_feature(project, kind="code", feature="bore", code="def bore(self, v, body): ...").
     Only that feature is built; the ones before it load from their checkpoints. Fix one with
     edit_design(project, ops=[{"op": "replace", "feature": "bore", "code": ...}]) (EDIT, DO NOT RESEND below).
     Look after every feature that changes the silhouette.
  4. A feature that fails comes back with its diagnosis and the body unchanged. Retry it at most 2 times (apply the
     diagnosis' first fix, then a simpler construction). Still failing: defer it, go on with the next feature, and
     list every deferred feature in your final message. Never let one feature block the design.
  5. A risky single feature (a loft, a band on a skin, a texture, a tight boolean) with two or three plausible
     constructions: build_candidates(project=..., candidates=[{label, feature, code}, ...]). The versions share
     the checkpoint of the features before it and are built in parallel; the best is kept.
  6. design_brief gives the route (prismatic, revolve, skin+features, mechanism) and plan_design returns these
     steps in order with their risk and fallback; plan helpers must exist (unknown names are refused).

  from build123d import Box, Cylinder, Pos
  from form.featureprog import FeatureDesign, feature
  from form.recipes.base import Param

  class Design(FeatureDesign):
      title, summary = "Bracket", "A plate with a bore."
      params = [Param("w", "Width", 60, 20, 200, 1, "mm", "form", "plate"),
                Param("bore_d", "Bore", 8, 3, 20, 0.5, "mm", "interface", "bore")]

      @feature("Plate")                                # the skeleton: create_design with only this one
      def plate(self, v, body):
          return Box(v["w"], 40, 6)

      @feature("Bore", role="interface")              # then add_feature(kind="code", feature="bore", code=...)
      def bore(self, v, body):
          return body - Cylinder(v["bore_d"] / 2, 20)
  (example_source_features has the complete file with fillets and slots; setup(self, v) returns values every
  feature reads as self.ctx.) Several parts: declare solids = N and start from a one-solid skeleton; each part is a
  feature that says how many parts it adds, @feature("Lenses", parts=2), returning craft.parts(**craft.named_parts(
  body), lens_l=a, lens_r=b); every revision is saved while parts are still to come. A slow feature gets
  @feature(..., budget=seconds); one that hangs is stopped and left out, and the features before it are kept.

EDIT, DO NOT RESEND (every change after the first build)
  Read the source once: get_design_source(project) returns it in canonical form, one method per feature, with the
  feature ids (feature="bore" returns that one method and the values it reads). Then name what changes:
    edit_design(project, expect_head=N, ops=[
      {"op": "replace", "feature": "bore", "code": "def bore(self, v, body): ..."},       # one feature
      {"op": "replace", "def": "constraints", "code": "def constraints(self, v): ..."},   # a helper or method
      {"op": "replace", "find": "amount=L", "with": "amount=-L"},                         # text found exactly once
      {"op": "insert", "feature": "ribs", "code": "...", "after": "plate", "label": "Ribs", "role": "structure"},
      {"op": "insert", "param": {"key": "rib_t", "label": "Rib", "default": 2, "min": 1, "max": 4}},
      {"op": "delete", "feature": "ribs"},
      {"op": "set_param", "param": "wall", "value": 2.4}])            # with default/min/max: the declaration too
  One call is one build and one revision. Only the changed feature and the ones after it are built; the rest load
  from their checkpoints. The result lists what was built, not the file. A small fix inside a long feature is a
  find/with; a rewritten feature is a replace by name. update_design(source=...) is for a different design, not for
  a change. A design written as a plain Recipe is edited the same way: its build() is lifted into one method per
  Stage (kept only when the kernel finds the same volume, faces and bounding box), and those are its feature ids.

THE CONTRACT AND THE PROOF SHEET (done is not correct)
  A build that returns a valid solid says nothing about whether the four holes are there. design_brief turns the
  brief into a contract: assertions the kernel checks, each with a tolerance and where it came from. Numbers in the
  goal and requirements are read ("4 x Ø5.2 on a 60 mm bolt circle", "2.4 mm wall", "80 x 60 x 20 mm", "M6 thread",
  "two-part"); pass the rest as assertions=[{"kind": "hole_count", "count": 2, "d": 3.4}, ...] (kinds: bbox, volume,
  part_count, face_count, hole_count, cylinder, bolt_circle, pattern, min_wall, thread).
  * design_brief returns the audit: what is missing, conflicting or impossible in the numbers themselves. Put
    audit.ask to the person once (ask_user), before any code. Conflicting or impossible numbers cannot be built from.
  * Every assertion is an obligation of one feature (named, or matched to the feature that makes that kind of
    thing; otherwise the finished design). Promise it in the code and it is checked the moment the feature is built:
        from form import contract
        @feature("Bolt holes", role="interface", expects=[contract.bolt_circle(4, 5.2, 60)])
        def holes(self, v, body): ...
    A miss fails that feature with measured against wanted ("measured 0 hole(s) Ø5.2 (round holes found: Ø5)"),
    the features before it stay built, and one edit_design op repairs it.
  * get_project and every commit return the proof sheet: one row per requirement with what was measured, the
    tolerance, the evidence class (computed: read off the B-rep; heuristic: thread presence) and PASS, FAIL or
    UNPROVEN. A FAIL names the feature to repair and whether it was never met or lost at a later feature. UNPROVEN
    is not a pass. Report the sheet as it is; claim only the PASS rows; a release waits while a row fails.

PREFLIGHT (before the kernel, all at once)
  create_design, update_design and edit_design first check the source without building anything and return every
  problem together: a constraint its own values violate; a name, keyword or enum member build123d, form.craft,
  form.parts or form.patterns do not have (with the closest real ones); a v["key"] that is not a Param; a Polygon
  whose points wind clockwise and is extruded with a positive amount (it goes to -Z: list points counter-clockwise);
  a bolt and its threaded hole that share too little flank (give both the same nominal major_d and set the play
  with clearance=, never both); a thread the contract asks for that nothing makes (a plain bore holds no bolt);
  parts= that add up to more than solids. Warnings: edges()[3] (select what a feature made instead:
  craft.made_by(after, before) for its edges, "faces" for its faces, or filter_by / sort_by / group_by), and a
  fillet of every edge placed before a pattern (finish last). Errors refuse the call; fix them all in one go.

A Form Studio design is one Python file that defines one subclass of Recipe. Form Studio imports it, builds it in the
CAD kernel (build123d on OpenCascade), attributes every face to a feature, and runs the full pipeline:
renders, checks, exports (STEP, STL, 3MF, OBJ, GLB), revisions, optimizer, animation, release.

CONTRACT
  from build123d import *                      # algebra API only: Box, Cylinder, Pos, Rot, Plane, fillet, ...
  from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

  class Design(Recipe):
      title, summary = "...", "..."
      solids = 1                               # separate bodies in the result (2 for case + lid)
      params = [Param(key, label, default, min, max, step, unit, group, feature, doc, provenance), ...]
                                               # provenance of the default: "assumed" (yours), "specified" (a
                                               # datasheet or standard named in doc), "measured" only from the person
      features = [Feature(id, label, role), ...]          # role: structure | interface | access | finish
      fit = None or {"cavity": derived_key, "mating": param_key, "clearance": param_key,
                     "label": "...", "per_side": True, "window": [min_gap, max_gap]}
      def constraints(self, v): return [RecipeError(msg, feature, hint, [param keys]), ...]
      def build(self, v): return [Stage(feature_id, whole_solid_after_this_feature), ...]
      def derived(self, v): return [{"key", "label", "value", "unit", "feature", "formula", "interface": bool}]
      def measure(self, v, faces_by_feature): return [{"key", "label", "intended", "modelled"}]   # read back off the solid
      def statics(self, v, volume_mm3, com): return {"some_metric": x, "checks": [{...}]}          # optional models
      def test_piece(self, v, shape): return (small_solid, {"label", "doc", "height"})              # optional
      def assembly(self, v): return Assembly(parts=[Part(...)], joints=[hinge(...)], hardware=[Hardware(...)])  # optional

RULES
  1. Units: mm, degrees, grams. Every Param has a unit and a range. Integers use step=1 and unit "".
  2. group: "brief" = facts about the world (measure them; record provenance), "interface" = how parts
     meet (clearances), "form" = free design choices, "process" = printing assumptions.
  3. Use the build123d ALGEBRA API (Box(...), a + b, a - b, Pos(...) * shape). Do NOT use BuildPart/with-blocks:
     objects created inside an active builder silently join the part.
  4. Each Stage holds the WHOLE solid after that feature. Order matters: a face belongs to the last stage
     that created its surface. Give each feature its own stage so renders and impact can name it.
  5. Model each part in the coordinates it is used in (base on z = 0 where it has one). Put multiple parts side
     by side with a gap and set solids = N, or declare an assembly() so they are shown in place.
  6. Design for how it will be made when the person says (CNC, moulding, casting, sheet metal: the checks name the
     smallest feature that process holds). Otherwise favour proportion and finish: real fillets and chamfers,
     consistent wall thickness, no knife edges.
  7. Dimensions from datasheets or drawings (open them with read_document): put them in params with
     provenance="specified" and the source in doc ("Raspberry Pi 5 mechanical drawing"). Values the user
     measured: provenance="measured". Your own estimates stay "assumed". Say in your reply which you could not confirm.
  8. constraints() must catch every combination that would build something useless or invalid, naming the
     feature, the parameters, and a fix.
  9. After every create/update: render(view="sheet") and LOOK. Most mistakes are visible before any check.
 10. Fit: if something must slide in/onto the part, declare `fit`, derive the cavity and measure() it.

 11. Designing around an existing part (a board, a device, a motor): import its STEP or STL with
     import_reference(project, path) (or create_design(..., references=[path])). It is drawn in the 3D view as a
     blueprint companion. In build(), self.reference("pi5.step") returns it as a build123d shape in the file's own
     coordinates (STEP: its B-rep; STL: a sewn mesh). Use it for clearance cuts, e.g.
         pi = self.reference("pi5.step"); bb = pi.bounding_box()
         body = body - Pos(bb.center().X, bb.center().Y, bb.min.Z) * Box(bb.size.X + 2 * c, bb.size.Y + 2 * c, bb.size.Z, align=A)
     Boolean cuts with a full manufacturer STEP are slow and fragile; cut its bounding box or a few chosen
     features rather than the whole assembly. Its dimensions are "computed" from the file, not "measured".

OPENSCAD (create_design(..., language="openscad"))
  The source is a .scad file. Each top-level number with a Customizer range comment becomes a Form Studio parameter:
      // Inner width (mm)          <- the comment line above is the label; "(deg)" sets the unit to degrees
      width = 40; // [20:1:120]    <- [min:step:max] or [min:max]; /* [Hidden] */ ends the parameters
  Form Studio runs `openscad -o part.stl -D width=...` and brings the mesh into the pipeline. It is a mesh design:
  no STEP export, no B-rep validity check, one feature only (no per-feature picking or impact), no FreeCAD
  re-check. Those are reported as "not available for mesh designs", never faked. Mesh volume, closed-mesh,
  wall thickness (ray-cast on the triangles), overhangs, build volume and the slice still run. Prefer Python
  (build123d) when the part needs STEP, feature-level edits or a fit interface.

HARDWARE: form.parts  (use it; do not guess screw, nut, insert, bearing or gear dimensions)
  from form import parts
  Each call returns a HardwarePart: .shape (build123d solid), .kind ("cut" or "add"), .dims {name: {value, unit,
  provenance, source}}; part["hole_d"] reads one value; part.derived(feature, prefix) gives derived() rows.
  Cutters: axis on Z, opening at z = 0, going down (-Z). Place with body - Pos(x, y, z_top) * part.shape;
  turn with Rot(180, 0, 0) for a hole opening on the bed face, Rot(90, 0, 0) for a hole along +Y.
    parts.screw_clearance("M3", length, head="socket"|"pan"|"countersunk", fit="close"|"normal", recess=True)
    parts.heat_insert_pocket("M3")      # CNC Kitchen hole; ["boss_min_d"] = smallest boss that keeps the wall
    parts.self_tap_pilot("M3", depth)   parts.nut_trap("M3", "hex"|"square", slot=0)   parts.magnet_pocket(d, h)
    parts.bearing_seat("608")           parts.thread(major_d, pitch, length, external=True)   # pitch >= 1 mm
    parts.spur_gear(module, teeth, thickness, bore)   parts.gear_pair(module, z1, z2, thickness, bore_a, bore_b,
    backlash)  -> .a, .b (b at +X, in mesh), .centre_distance = m (z1 + z2) / 2, .contact_ratio
    parts.tap_hole("M3", depth, "soft"|"hard")   # ISO tap drill, for metal or wood stock (printed: inserts or pilots)
    parts.trapezoidal_thread(8, 2, length, starts=4, external=False, clearance=0.3, acme=False)  # lead screws (Tr8x8)
    parts.bottle_thread("PCO1881"|"M38SP400", external=False)   # a cap for a real soda bottle, or a neck
    parts.sprocket(teeth, "06B"|"08B"|"ANSI 40", bore)   parts.chain_drive(chain, z1, z2, centre)  # even links, exact C
    parts.pipe_socket('3/4', depth)   parts.pipe_size('3/4', '40', 'pvc') -> (OD, wall)   # stock pipe in a printed part
  The hardware itself (kind "hardware": place it, never fuse it; .grams, .material, .bom(qty, note, after) -> an
  Assembly Hardware row with its mass): parts.screw("M3", 10, "socket"|"pan"|"countersunk"|"button"|"hex"),
  parts.nut, parts.washer, parts.heat_insert, parts.bearing("608"), parts.pipe, parts.pipe_flange.
  A whole screw joint, with a STOCK screw length chosen for you (never type one):
    j = parts.bolted_joint("M3", clamp=4, into="insert"|"nut"|"tap"|"self_tap", head="socket")
    lid = lid - Pos(x, y, z_top) * j.top.shape;  box = box - Pos(x, y, z_top) * j.bottom.shape   # same position
    j.length, j.base_min (thinnest base that holds it), j.dims (engagement), j.hardware(qty, after="lid") -> BOM rows
  Materials for parts that are not printed (density, look): from form import material_library as ml;
    ml.get("aluminum"), ml.mass_g(volume_mm3, "brass"), ml.zone("stainless", [features]) -> an appearance() zone.
  M2-M6 screws, nuts, washers, inserts and 6xx bearings work everywhere from tables. Other sizes, threads, sprockets,
  pipes and gears need bd_warehouse and py_gearworks (they ship with the app); without them a RecipeError says how
  to install. Exemplars: lead_screw_axis, chain_drive, bottle_pipe_adapter.
  Example: a boss with an insert, sized from the published minimum wall
    ins = parts.heat_insert_pocket("M3")
    boss = Cylinder(ins["boss_min_d"] / 2 + 0.4, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    boss = boss - Pos(0, 0, 10) * ins.shape        # derived(): rows += ins.derived("boss", "insert.")

ASSEMBLIES (for solids >= 2; without one the app can show the parts only as modelled and pulled apart, never
  assembled, and checks nothing about how they meet)
  from form.recipes.base import Access, Assembly, Hardware, Mate, Part, fixed, hinge, slide
  Part(id, label, solid, move, rotate, explode, note, attach="")   solid = index of the printed body, numbered left to
       right on the plate (bounding-box centre X, then Y, then Z), OR an (x, y, z) point inside that body as built: use a
       point whenever parts share an axis (a gearbox's housing, suns and carriers), so you never count solids by hand.
       Assembled placement = Pos(*move) * Rot(*rotate) applied to the
       part as printed. explode = offset in mm for the exploded view, RELATIVE TO ITS PARENT (a child separates with its
       parent and then by its own offset). List parts in assembly order; note is the assembly step ("Press the lid on.").
       attach="arm": the part is rigidly fixed to the arm and moves with it (a bolt in its hole, a cap on a tube).
  hinge(part, axis, origin, (lo_deg, hi_deg), samples, parent="", step=0, id=, label=) / slide(part, axis, (lo, hi), samples,
       parent="") / fixed(part, parent): the joint moves `part` AND everything attached below it, relative to `parent`
       ("" = the world). Axis and origin are in the assembled frame with every joint at 0; a child joint's axis rides
       with its parent's motion. 0 is the assembled position. step > 0 = a ratchet or detent: only multiples of step are
       checked (the positions it can rest at). samples = the coarse sweep; Form Studio adds positions near contact.
  KINEMATIC CHAINS: the parts form a tree. Each part has at most ONE link to a parent: attach=..., or one joint that
       moves it. Example, a wall arm with a tilting cup:
         Part("base", ...),                                   # fixed to the world
         Part("pin", ..., attach="base"),                    # rides with the base
         Part("arm", ...), Part("cup", ...), Part("cup_bolt", ..., attach="cup"),
         joints=[hinge("arm", (1, 0, 0), pivot1, (-60, 60), parent="base", id="arm_tilt", label="Arm tilt"),
                 hinge("cup", (1, 0, 0), pivot2, (-90, 90), parent="arm", id="cup_tilt", label="Cup tilt")]
       Moving Arm tilt swings the arm, the cup and the cup bolt together; Cup tilt swings the cup and its bolt about an
       axis that is wherever the arm put it. Never give a part both attach= and a joint, or two joints; no loops.
       A closed linkage (a four-bar) is a loop: declare its pins as Mate(..., "pin") and put its motion in derived()
       from craft.four_bar (swing, transmission angle), not as joints. Gears are not joints either: model them in mesh
       with their backlash as the gap.
  Mate(a, b, kind, clearance, label): two parts that touch or interlock BY DESIGN, kind = pin | thread | slip | snap |
       press | contact. Declare one for every pin in its hole and every thread in its thread: they are then not booleaned
       (fine threads are slow and always "collide"); their gap is measured once and compared with clearance (designed
       gap per side, mm). Everything not mated is checked for overlap at rest and through every joint's motion.
  Hardware(name, size, qty, source, note, after=part_id, access=(Access(at, axis, tool_d, length),))
       bought parts for the BOM; access = a straight tool path ending at the screw head, pointing the way it is driven,
       checked against the parts in place after `after`.
  Assembly(parts, joints, hardware, mates, clearance_warn=0.1, budget_s=None)   budget_s: seconds for the assembly checks
       (default [assembly].budget_s = 45); when it runs out the checks say which ranges they reached, never "clear".
  Form Studio then checks, from the solids: overlap when assembled, the smallest gap, each mated fit, each joint swept
  through its range with its whole chain (first contact angle, worst overlap; free between samples is proven where the
  clearance exceeds the travel, otherwise reported as sampled only), and tool access. A wrong declaration (unknown part,
  loop, two parents) is refused by create_design/update_design with the reason.
  The app shows Assembled / Exploded / Print layout with a slider per joint, and a release adds BOM.csv and ASSEMBLY.md.

TEXT AND MARKS: form.marks   PATTERNS: form.patterns
  from form import marks, patterns
  marks.emboss_text(shape, "DOCK", on=(x, y, z), normal=(0, -1, 0), height=6, depth=0.6)   # raised; returns the new shape
  marks.deboss_text(shape, "v2", on=a_planar_face, height=5, depth=0.5)                    # sunk
  marks.revision_stamp(shape)        # "r04 a3f1" (revision + hash of its values) sunk 0.4 mm into the underside
       on = a planar Face, a Plane, or a point with normal=. height is the CAP height in mm. Flat faces only.
       The font ships with Form Studio (never a system font). Text reads left to right seen from outside; on walls capitals point up.
       marks.context() gives {"rev", "text", "hash", "nozzle"} while Form Studio builds for a project: "text" is the project's
       label text (form mark <project> --text ..., or the Label text field), so use marks.context().get("text") or "FORM".
       If the geometry depends on it, declare on the class:  mark_params = ("label", "stamp")  (the parameters that switch
       marks on; Form Studio then keys the geometry by label text and revision) and  wall_exempt = ("mark",)  (the feature whose
       faces are lettering, so letter corners are not reported as thin walls).
       Printability: statics() can return checks from marks.checks(marks.analyse(text, height), raised=True): stroke
       width against the nozzle (computed) and cap height against a 4 mm legibility floor (heuristic). Raised text on a
       wall is a small overhang; sunk text prints cleaner. Keep capitals >= 5 mm on a 0.4 mm nozzle.
  patterns.hex_vents(w, d, cell, web, depth)   patterns.perforation_grid(w, d, hole_d, web, depth, stagger)
  patterns.slot_array(slot_w, slot_l, count | w=, web, depth)   patterns.knurl(diameter, height, pitch, depth)
  patterns.grip_ribs(w, d, rib_w, pitch, height)      # kind "add"; the others are cutters
       Each returns a Pattern: .shape (cutter: centred, opening at z = 0, going down, like form.parts), .computed
       {"count", "open_area_ratio", "min_web_mm", ...}, .derived(feature, prefix) rows, .check() (webs >= 2 perimeters),
       .apply(body, on=(x, y, z), normal=(0, 0, 1)). Through-cut: depth = wall + 0.2.
       lid = lid - Pos(0, 0, lid_t) * patterns.hex_vents(60, 36, cell=5, web=1.2, depth=lid_t + 0.2).shape

WORKFLOW
  design_guide -> write source -> create_design -> render -> get_project (checks, the proof sheet, slice)
  -> fix with edit_design (ops, not the file) -> request_release. Parameter-only changes: preview_change /
  commit_change, as for any project.

  Anything complex (a mechanism, an organic or styled form, a texture, several parts) is staged, and the tools
  enforce it:
    1. design_brief: requirements, key dimensions with their source, constraints, style, and the unknowns (list
       them; never guess a dimension that changes fit, load or safety: ask_user / ask_measurement). It returns
       the contract and its audit (THE CONTRACT AND THE PROOF SHEET above): settle the audit before coding.
    2. design_guide(topic=...) for the topics the brief needs, and design_examples(query) for a close exemplar.
       Read the exemplar's source: it shows the construction a top designer would use.
    3. plan_design: every feature with HOW it is built (which form.craft helper, which sections), the parts, key
       dimensions, mechanisms with their clearances, textures with their tier, and the risks.
    4. create_design(..., plan=<brief id>) with the skeleton feature only: it returns a six-view sheet and a
       section. LOOK at both. Then the plan's steps one add_feature(kind="code") at a time (SKELETON FIRST above).
    5. critique(project): close-ups per feature, metrics, a checklist. Fix with edit_design, critique again.
       A briefed design cannot be released until its head revision has a critique pass.
  The helper library for all of this is form.craft (topics surfacing, mechanisms, organic, texture).

WHEN IT FAILS OR LOOKS WRONG
  * A failed build comes back diagnosed: the operation (fillet, loft, fuse, cut, shell...), the feature, the line,
    the likely cause read from the shapes on that line (an invalid operand, parts 0.01 mm apart, sections with 6 and
    14 edges, a fillet wider than the shortest edge) and ranked fixes. Apply the first fix; do not guess.
  * Write risky operations with the robust helpers; each retries the way OCCT needs and notes what it gave up:
      craft.safe_union(a, b, ...) / craft.safe_cut(body, tool) / craft.fuse / craft.cut   one boolean engine: the plain
                                       boolean first, verified; on failure it measures overlap, gap and shared faces,
                                       names the cause (coincident faces, grazing tool, invalid operand, parts that
                                       touch) and tries only that cause's repairs; the error carries the numbers.
                                       Separate parts are never fused: use craft.parts(name=solid, ...)
      craft.safe_loft(sections)        smooth, re-seamed and resampled sections (craft.reseam), ruled, pairwise
      craft.safe_fillet / craft.safe_chamfer   smaller sizes, then edge by edge
      craft.safe_shell(solid, t, openings)     arc, intersection offset, then thinner walls
      craft.repair(shape), craft.inspect(shape)   ShapeFix + face merge; validity, faults, shortest edge
  * Two or three plausible constructions for a risky step: write them all and call build_candidates once. They build
    in parallel (one kernel worker each), are scored (builds, brief targets, quality, robustness, editability over
    each parameter's range) and the best becomes the design; failures carry their diagnosis.
  * design_examples(technique="...") returns just the block of an exemplar that does one thing well.
  * "The result is N solid(s); this design declares M. Solids per stage: ..." Read the per-stage counts: the step
    where the count jumps is the one that split a body (a slit that runs out of material) or fused two parts (they
    touch: leave 0.3 mm). "The X step left no solid": a boolean failed there; overlap by 0.2 mm, keep it off a loft
    seam, or simplify the shape.
  * get_project's craft_fallbacks lists every helper that could not do what you asked (a fillet built smaller or edge
    by edge, a loft in runs) and every stage that is not a valid solid. Fix them or say so; never hide them.
  * Check a risky boolean yourself while you write: (a - b).is_valid. A smooth loft through sections that are close
    together AND shifted sideways can fold over itself; its booleans then come back invalid and larger, not smaller.
  * Heavy designs (a helmet, 15 gears) take a minute or more: create_design/update_design say when exports and checks
    are still running; run_pipeline(project) finishes them and reuses what is done.
  * Through form tool (the CLI), pictures come back as file paths under "images": open them, they are the sheet,
    the section and the close-ups.

AFTER THE BUILD: REFINEMENT (automatic)
  * Every build is refined in the background: named refine features (role="refine": fillet tiers, an edge break, a
    parting line, a grip texture, a recessed panel, button pads, ribs; materials and contrast) land as one more
    revision, "Refined: N changes", each kept only when the checks still pass, the faces of fit, access, mechanism
    and interface features are unchanged and the walls hold. Give your interfaces those roles and they stay exact.
  * A plain Recipe is refined too: its build() becomes the skeleton feature of a FeatureDesign and the refine
    features follow it. refine = False on the design class, create_design(refine="off") or
    refine_design(action="off") turn it off; refine_design(action="undo", feature=...) takes one change out.
  * A game asset (purpose "game") is not refined unless it is asked for: refine_design(action="on") for one design,
    or Settings › Refine game assets ([refine] game = true) for all.
