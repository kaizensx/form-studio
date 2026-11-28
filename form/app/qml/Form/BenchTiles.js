.pragma library

// The Bench's tile view (BenchTiles.qml): for each entry of form/studies.py an icon, a short name, the group it is
// tiled under within its chapter (Analysis, Manufacturing or Documents) and one plain sentence of what you get.
// The state, the number and how it is known still come from the engine's entry; nothing here says whether it ran.
// An id missing here falls back to the entry's own label and the first clause of its doc (see info()).

var T = {
    "features": ["layers", "Features", "A", "The feature tree as the build log records it: built, suppressed or left out, with why"],
    "proof": ["list_checks", "Requirements", "A", "The brief's requirements measured on the solid, each one a pass, a fail or unproven"],
    "materials": ["library", "Materials", "A", "Each material with its density and the document every property was read from"],
    "lighter": ["weight", "Lighter", "A", "Thinner walls and pockets that keep every passing check, each one built and checked"],
    "checks": ["shield_check", "Checks", "A", "Validity, size, wall thickness and fit of the head, each with a pass or fail"],
    "assembly": ["boxes", "Assembly", "A", "Overlaps, gaps, declared fits and every joint swept through its range"],
    "motion": ["play", "Motion", "A", "The mechanism played: loops closed, traces, the smallest gap and when, holding torque"],
    "calc": ["drafting_compass", "Calculation", "A", "The standard's equations behind the design, run again on this revision's values"],
    "mass": ["scale", "Mass", "A", "Mass, centre of mass and inertia on the B-rep, per part and assembled"],
    "stack": ["ruler_dim", "Stack-up", "A", "A gap through the mates: worst case, RSS, Monte Carlo and what to tighten first"],
    "lattice": ["grid_3x3", "Lattice", "A", "A lattice or TPMS inside the part with a skin, its density and stiffness"],
    "map.thickness": ["ruler", "Thickness", "A", "A map of wall thickness on the part, with the thinnest wall"],
    "map.overhang": ["triangle", "Overhangs", "M", "A map of the angles past vertical in the print orientation"],
    "map.section": ["scan_line", "Layer area", "M", "The area of every layer by height and the weakest neck"],
    "map.features": ["crosshair", "Small features", "M", "The walls, gaps and holes too small for the nozzle, on the part"],
    "strength": ["gauge", "Strength", "A", "A study with the stress plot, the peak stress, the safety factor and a pass or fail"],
    "print.strength": ["layers", "Printed strength", "M", "The safety factor with a layered material in the print orientation"],
    "inverse": ["target", "Inverse design", "A", "The variants that do what the part must do, each built and studied, on a front"],
    "topology": ["shapes", "Topology", "A", "Where material carries the load, written back as pockets you can edit"],
    "fit": ["target", "Fit yield", "M", "The share of prints whose fit lands in the window, from the printer's spread"],
    "critique": ["sparkles", "Critique", "A", "Close-ups and a checklist your agent answers by looking at the part"],
    "slice": ["layers", "Slice", "M", "The slicer's own slice: print time, filament and plates"],
    "simulation": ["film", "Print simulation", "M", "The sliced toolpaths layer by layer, with bridges and overhang walls"],
    "orientation": ["rotate_3d", "Orientations", "M", "Every way the part can lie on the plate, ranked by a stated score"],
    "print.orient": ["rotate_3d", "Orientation front", "M", "The orientations no other beats on support, time, strength and finish"],
    "printers": ["printer", "Every printer", "M", "The part sliced for real on every printer you set up, side by side"],
    "print.warp": ["triangle_alert", "Warp risk", "M", "An indicator of warping from shrinkage, the first layer and the corners"],
    "cost": ["coins", "Print cost", "M", "Filament, electricity and machine time of the current slice, at your prices"],
    "dfm_cnc": ["wrench", "CNC check", "M", "Every CNC rule measured on the solid, drawn on the part, with fixes checked again"],
    "dfm_injection": ["package", "Moulding check", "M", "Every injection moulding rule measured on the solid, with fixes checked again"],
    "dfm_fdm": ["printer", "FDM check", "M", "Every FDM printing rule measured on the solid, with fixes checked again"],
    "dfm_sla": ["flask_conical", "Resin check", "M", "Every resin printing rule measured on the solid, with fixes checked again"],
    "dfm_sls": ["boxes", "SLS check", "M", "Every SLS printing rule measured on the solid, with fixes checked again"],
    "dfm_mjf": ["boxes", "MJF check", "M", "Every MJF printing rule measured on the solid, with fixes checked again"],
    "dfm_lpbf": ["zap", "Metal print check", "M", "Every metal printing rule measured on the solid, with fixes checked again"],
    "cam_3axis": ["cog", "CNC, 3-axis", "M", "Toolpaths and G-code run on a stock model: gouges, leftover and cycle time"],
    "sheet_cutcheck": ["scissors", "Cut-file check", "M", "The flat pattern's DXF read as a laser shop reads it, rule by rule"],
    "sheet_bend_order": ["merge", "Bend order", "M", "A sequence a press brake can bend in, or the collision that rules it out"],
    "parts.standard": ["wrench", "Standard parts", "A", "The bought parts placed on the design, each mating cut checked for fit"],
    "board.fit": ["cuboid", "Board fit", "A", "The board against its enclosure: walls, standoffs, plugs and heights"],
    "board.checks": ["badge_check", "Board checks", "A", "KiCad's own DRC and ERC, and the board against the fabs' limits"],
    "board.copper": ["route", "Board copper", "A", "Our geometric check of tracks, vias and pads: clearances and edges"],
    "board.placement": ["layout_grid", "Placement", "A", "Every part on the board against the enclosure's constraints"],
    "board.schematic": ["git_branch", "Schematic", "A", "Our electrical checks of the schematic: open pins, undriven power, conflicts"],
    "doc.bom": ["list_checks", "Parts list", "D", "What to buy, with quantities, materials and supplier numbers, as CSV and PDF"],
    "doc.assembly": ["book_open", "Assembly notes", "D", "How the parts go together, in order, with pictures"],
    "doc.motion_checks": ["file_text", "Motion checks", "D", "Every joint's range and first contact, as computed"],
    "doc.print_report": ["file_text", "Print report", "D", "What was checked and sliced, and what was not"],
    "doc.measurement_plan": ["ruler", "Measuring plan", "D", "What to measure on the made part, and how"],
    "sequence": ["arrow_down_to_line", "Assembly steps", "D", "An order the parts can go together in, each with its direction"],
    "instructions": ["book_open", "Instructions", "D", "A PDF: a parts page, then one page per part going on"],
    "drawing": ["pencil_ruler", "Drawing", "D", "A shop drawing with views, a section, dimensions, fits, GD&T and a title block"],
    "views": ["layout_grid", "Four views", "D", "Iso, front, top and right, rendered from the kernel's geometry"],
    "photo": ["camera", "Render", "D", "A photoreal picture in Blender with the design's materials"],
    "turntable": ["rotate_ccw", "Turntable", "D", "The part turning, rendered from the real mesh"],
    "robot": ["bot", "Robot files", "D", "URDF, SRDF and MJCF with inertia from the B-rep, parsed back"],
    "share": ["share_2", "Share card", "D", "A picture of the design with its evidence labels"],
    "doc.board_fab": ["file_box", "Board fab files", "D", "Gerbers, drills, pick-and-place, BOM and the board STEP from KiCad"],
    "testplan": ["clipboard", "Test plan", "D", "What to measure on the made part, with limits and a checklist to fill in"],
    "report": ["newspaper", "Results report", "D", "Every check and study with its evidence, the measured results and a verdict"],
    "print.orientation": ["rotate_3d", "Print orientation", "M", "The orientation written to the print setup; the pick is yours"],
    "exports": ["file_down", "STEP, STL, OBJ", "D", "The solid as files for other CAD programs, renderers and slicers"],
    "threemf": ["file_box", "3MF in colour", "D", "One object per body with its colour and material name"],
    "drawing.pmi": ["file_code", "STEP with PMI", "D", "STEP AP242 with dimensions and GD&T on faces, read back and compared"],
    "slicer_project": ["external_link", "Slicer project", "M", "Sliced with settings chosen for this part, to open in your slicer"],
    "freecad": ["code", "FreeCAD macro", "D", "A macro that rebuilds this revision in FreeCAD"],
    "project_file": ["archive", "Project archive", "D", "The design, its revisions and conversations in one file"],
    "game": ["gamepad_2", "Game asset", "M", "LODs, UVs, baked maps and collision for Godot, Unity or Unreal"],
    "sheet_flat": ["square_dashed", "Flat pattern", "M", "The part unfolded, folded back to prove it, as a DXF"],
    "cost.process": ["coins", "Cost by process", "M", "Cost per part against quantity for each process, with sourced rates"],
    "release": ["lock", "Release", "D", "The gate, then your approval: the files frozen with their hashes"]
}

var GROUPS = { A: "Analysis", M: "Manufacturing", D: "Documents" }
var ORDER = ["Analysis", "Manufacturing", "Documents"]

function info(e) {
    var t = T[e.id]
    if (t) return { icon: t[0], short: t[1], group: GROUPS[t[2]], say: t[3] }
    var doc = String(e.doc || "")
    var cut = doc.split(/[:.;]/)[0]
    return { icon: "box", short: e.label || e.id, group: "Analysis", say: cut || doc }
}
