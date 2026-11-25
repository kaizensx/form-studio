MECHANISMS (form.craft.mechanisms, form.craft.fits, form.parts)
Each returns a Mech: .shapes {name: solid}, .dims (value, unit, provenance, source), .checks, .axis/.origin for joints.
  mech["name"] is a dimension's value or, for a name in .shapes, that solid (planetary()["ring"], hinge["leaf_a"]).
  craft.pin_hinge(length, outer_d, pin_d, knuckles, clearance)    print-in-place; leaf_a carries the pin. Lying flat,
       axis along X at z = outer_d / 2. Standing on a wall: place = Pos(0, y_axis, z_axis) * Rot(90, 0, 0) *
       Pos(0, 0, -outer_d / 2) puts leaf_a below the axis and leaf_b above it, both on the +Y side. Fuse each leaf to
       its body and cut place * hinge.info["relief_a"] from the body leaf_b joins (relief_b from the other), or the
       knuckles fuse the two bodies. Keep the axis just outside the walls and bridge leaves to walls with webs.
  craft.living_hinge(width, gap, web_t, material="PP")           warns for PLA/PETG
  craft.cantilever_snap(length, thickness, width, undercut)       strain = 1.5 t y / L^2 (computed) vs allowed. Beam
       along +Z, lip +X. Hanging from a lid with the lip pointing -Y: Pos(...) * Rot(0, 0, -90) * Rot(180, 0, 0).
  craft.annular_snap(d, undercut, height, wall)                   male bead + groove cutter, hoop strain y / d
  craft.bayonet(d, height, lugs, twist)   male and female_cutter share ONE frame: same placement for both, cutter open
       at its top; turn the male by twist - 2 deg about Z to show it locked; attach the male's top end (z = height).
  craft.dovetail(length, width, height, angle)    craft.detent(ball_d, depth)
  craft.ratchet(teeth, od)    craft.cam(base_r, lift, rise, dwell_top, fall, follower_r)  (pressure angle checked)
  craft.four_bar(ground, crank, coupler, rocker)   Grashof class, swing, transmission angle; .shapes = printable links
  craft.four_bar_pose(ground, crank, coupler, rocker, crank_deg)  A, B, C, D where the loop sits at that crank angle;
  craft.link_between(p, q, width, thickness, hole_d, z)           a link placed between two pivots (pins along Z)
  craft.gear_train(module, teeth=(14, 28, 14))      craft.planetary(module, sun, planet, planets, ring_height=)
       ring_height makes one ring for several stacked stages (a 3-stage 64:1 box: 12/12/36 three times in one ring).
       (via form.parts)
  craft.iso_fit("H7/g6", d)   craft.bearing_fit("608", "shaft")   ISO 286 limits; FDM holds ~0.15 mm, say so
Rules:
  * Every moving pair has a clearance per side you can name (FDM: 0.2-0.35 mm sliding, 0.35-0.5 print-in-place).
  * Declare the motion: assembly() with hinge()/slide() joints and Mate() for pins and threads, so Form Studio sweeps it.
  * Put strain, ratio, centre distance and clearance in derived() with their source (Mech.derived(feature)).
  * Snap hooks bend along the layers: lay the beam flat in XY. Living hinges need PP, PE, nylon or TPU.
