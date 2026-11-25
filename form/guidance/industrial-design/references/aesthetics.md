AESTHETICS: an industrial designer's method, step by step. Plain and correct is not the goal; an object a person
would pick off a shelf is. Exemplars that show every step (design_examples(name=...)): cable_dock, valet_tray,
ribbon_phone_stand, lamp_base, cube_speaker, slim_remote, floating_wall_hook, sofa_arm_clip.

1. DESIGN LANGUAGE FIRST (write it down before any code, three to five lines)
  * Pick ONE archetype and say it:
      soft monolith    one calm block, details cut into it (cable_dock, cube_speaker)
      bent band        one strip that never stops, bends with true radii (ribbon_phone_stand, sofa_arm_clip)
      stacked turned   plinth, body, crown on one axis, each a material (lamp_base)
      tray / vessel    one plan shape at several sizes: shell, well, foot (valet_tray)
      pebble / bar     crowned sections, split into two shells (slim_remote)
      stem and rose    a disc on the wall and one tapering limb (floating_wall_hook)
  * One gesture carries the form (a crown, a curl, a taper). Every detail repeats it or is cut into it, never
    stuck on. Say which.
  * Name the three radius tiers in mm, where the surface break runs, and the two or three materials.

2. PROPORTION SYSTEM
  * Relate the main masses: 1:1 (calm), 1:1.414, 1:1.618 (golden), 1:2. Never "almost equal" (1:1.1 reads as a
    mistake). Split a length at 0.382/0.618, not in the middle (valet_tray's ridge).
  * Heights of stacked tiers about 1 : 2.5 : 1.2; diameters falling by about a quarter each tier.
  * Odd counts on a rhythm (3 channels, 3 keys) centred on the axis read as designed; even counts split a face.

3. CONTINUITY (G1 is the minimum, aim for G2 on the main form)
  * A box with filleted corners is G1: the curvature jumps where the fillet starts and the highlight kinks. A
    superellipse plan is curvature-continuous all round. Use it for every main plan form:
        plan = craft.superellipse_face(a, b, 4.0, count=96)      # n 4-6: flat sides, soft G2 corners
        body = Pos(0, 0, foot_h) * extrude(plan, h)
  * Lofts through superellipse sections are one smooth skin (C2 inside): crown a top by shrinking the last
    sections a few mm (slim_remote):
        secs = [craft.superellipse_face(a - s, b - 0.6 * s, 2.7, z=z) for z, s in ((w, 0), (w + 4, .5), (t, 3.6))]
        top = craft.loft_sections(secs)
  * A revolved spline profile that leaves the base near vertical and lands on the crown near flat reads tense;
    a circular arc reads as half a ball (lamp_base: craft.revolve_profile(points, spline=True)).
  * A band or limb along a path: place sections with a fixed x_dir so they cannot twist, and put the rounding IN
    the section (a superellipse n 2.4-6), so there is no fillet left to fail:
        pl = Plane(origin=path.position_at(s), x_dir=(0, 1, 0), z_dir=path.tangent_at(s))
        secs.append(craft.superellipse_face(w / 2, t / 2, 6.0, plane=pl))
    Bent strips: straight runs joined by tangent arcs (Edge.make_tangent_arc), then Wire.offset_2d(t / 2,
    kind=Kind.ARC, side=Side.BOTH) and extrude: exact radii, constant wall (sofa_arm_clip). A free spline through
    the same points overshoots and loops.
  * Round a cut END with the loft itself: add sections past the end that shrink on a quarter ellipse.
  * Tension: a surface almost flat but not quite (a slight crown, a taper toward the nose) reads as designed; one
    that bulges evenly everywhere reads as inflated. Put the fullness where the use is; let the rest run taut.

4. RADIUS HIERARCHY: three tiers, each about a third of the one above
  * Tier 1, the form: R 5-10 on the main body's crown or wrap (or the superellipse corner itself).
  * Tier 2, secondary edges: R 1.5-3 on feet, plinths, side outlines of a band, rims.
  * Tier 3, details: R 0.5-1 on lips, key domes, channel mouths, rib tops.
  * One radius everywhere looks inflated; none looks machined raw. Fillet big before small, outside before inside.
  * Round the cutter, not the cavity: give a pocket tool its floor radius before the cut (valet_tray):
        tool = craft.safe_fillet(tool, tool.edges().group_by(Axis.Z)[0], floor_r)
        body = craft.safe_cut(body, tool)
  * A FILLET THAT FAILS IS NEVER A REASON TO DROP ROUNDING. In order: craft.safe_fillet (it retries at 75 %,
    50 %, 25 % and edge by edge, and notes it), a smaller radius, one edge loop at a time
    (for y in (L, -L): loop = [e for e in body.edges() if abs(e.center().Y - y) < 1e-3]), rounding the profile
    before the boolean, or rounding in the section (above). Ship nothing with raw edges where a hand goes.

5. SURFACE BREAKS AND SHADOW GAPS
  * A plain surface needs one considered break. The cheapest premium detail is a shadow gap:
      floating foot   a foot inset 1-1.5 mm under the body (cable_dock, valet_tray, cube_speaker)
      stand-off       a disc 3-4 mm smaller than a wall rose (floating_wall_hook)
      inset panel     a grille plate in a pocket with a constant 0.6-1 mm gap all round (cube_speaker)
      split line      a 0.6-0.8 mm groove where two shells meet (slim_remote): a thin superellipse ring cut
      recess ring     a small part set into a recess 1.5 mm larger (lamp_base's collar, every key)
  * Stepped tiers: each part steps in 1.5-2 mm from the one below; the step's shadow does the work.
  * Fillet the body BEFORE cutting a pocket into a face, so the pocket never meets a fillet.
  * On a lofted or sculpted skin, character lines and trim are craft.organic.surface_band regions and openings are
    two_view_cutter cuts that follow the form (design_guide topic "organic"), never where booleans happen to meet.

6. DETAIL RHYTHM
  * Repeated details on one pitch, aligned to the form's axes, centred: perforations on a staggered grid (hole
    55-65 % of pitch, stopped a pitch from the edge, cut as one Compound), keys at equal pitch with the main one
    larger, two or three turned grooves (exact torus cuts) on a plinth, ribs at equal spacing.
  * Concentrate detail where the hand works; keep the rest calm.

7. MATERIAL AND COLOUR PAIRING (appearance(); finishes: matte petg silk gloss carbon smoke rubber metal)
  * Two or three materials, chosen by function: the body calm, contact surfaces soft (rubber: pads, feet, grip
    ribs, linings), one precise accent (metal: a collar, a ring, a grille).
        def appearance(self, v):
            return [{"features": ["body", "crown"], "finish": "matte", "color": "#d9d2c5"},
                    {"features": ["channels"], "finish": "rubber", "color": "#d2703f"},
                    {"features": ["foot"], "finish": "rubber", "color": "#2b2c2e"}]
    A cut feature's faces belong to it: a well or a channel can be its own lining colour.
  * Palettes that work: warm stone + terracotta + charcoal; glazed white + deep green felt + cork; black + brass +
    stone; slate + coral; graphite + warm grey. One hue family plus one accent.
  * Any other finish name is invalid and the photo silently falls back to one material.

8. LOOK, SCORE, FIX (the loop; never skip it on a "make it beautiful" request)
  * render_photo from three angles (three_quarter, front or right, three_quarter_back) and look at each one.
  * critique(project, aesthetic={silhouette, proportion, continuity, radius_hierarchy, break_up, detail_rhythm,
    material, would_sell}, reads_as=...), each 0-5, scored honestly from the photos. Geometry caps what it cannot
    support (no fillets caps radius_hierarchy, one zone caps material). The gate: mean >= 4, nothing under 3.
  * Fix the lowest item first, render again, critique again: at least two passes. Answer "would I pay for this
    next to a real product?" and name what gives it away as a model; fix that.
  * Silhouette first: a product is recognised by its outline in three views before any detail. If any view looks
    like a primitive (a box, a puck, an egg, a slab), it is not done.
