.pragma library
// The tools of each mode, as the ribbon at the head of the stage shows them (ToolRibbon.qml): groups with a caption,
// each tool an icon and a label. The dock shows the same tools as icons when the ribbon is hidden.
//
// `need` says what a tool waits for, so that nothing is shown that cannot do anything yet:
//   kind:  ["sweep"]      a feature kind the engine builds (GET /studio feature_kinds, form/modelling.py KINDS).
//                         Sweep, loft, rib, mirror, draft, split, move face and the planes are registered here and
//                         appear by themselves when the engine lists their kind. The window has no panel of its
//                         own for them yet: `ask` is put in the conversation, written for the person to finish,
//                         and the agent adds the feature (add_feature: the same engine call).
//   bench: ["strength"]   a Bench entry (form/studies.py) the design has; the first one that applies is opened.
//   when:  "assembly"     the design declares how its parts go together; "print" it is made for printing;
//                         "companions" it carries a reference part; "game" a game asset.
// Workspace.qml says what each tool does (toolRun) and whether it is lit (toolState).

var MODES = {
    shape: [
        { id: "create", caption: "Create", tools: [
            { id: "sketch", icon: "pen_tool", label: "Sketch", keys: "S", hint: "Pick a flat face or a plane and draw a profile on it; then extrude, cut or revolve it." },
            { id: "extrude", icon: "arrow_up", label: "Extrude", keys: "Shift+E", hint: "A profile drawn on a face or a plane, pulled out of it." },
            { id: "cut", icon: "arrow_down_to_line", label: "Cut", keys: "Shift+X", hint: "A profile drawn on a face, cut into the part: a pocket, a slot, a hole of any shape." },
            { id: "revolve", icon: "rotate_3d", label: "Revolve", keys: "Shift+R", hint: "A profile turned about one of its lines." },
            { id: "sweep", icon: "spline", label: "Sweep", hint: "A profile carried along a path.", extra: true, need: { kind: ["sweep"] }, ask: "Add a sweep to this design: carry the profile  along the path . Twist: none." },
            { id: "loft", icon: "layers_2", label: "Loft", hint: "A solid through two or more profiles.", extra: true, need: { kind: ["loft"] }, ask: "Add a loft to this design, through these profiles: " },
            { id: "rib", icon: "separator_vertical", label: "Rib", hint: "A thin wall from an open profile, grown to the faces around it.", extra: true, need: { kind: ["rib"] }, ask: "Add a rib to this design: an open line from  to , 2 mm thick." }
        ] },
        { id: "modify", caption: "Modify", tools: [
            { id: "fillet", icon: "radius", label: "Fillet", keys: "Shift+F", hint: "Pick the edges to round." },
            { id: "chamfer", icon: "triangle", label: "Chamfer", keys: "Shift+C", hint: "Pick the edges to bevel." },
            { id: "hole", icon: "circle_dot", label: "Hole", keys: "Shift+H", hint: "Pick a flat face: a hole there, to a standard size." },
            { id: "pattern", icon: "layout_grid", label: "Pattern", keys: "Shift+P", hint: "Repeat a feature along a line or about an axis. Select the feature first, on the part or in the tree." },
            { id: "mirror", icon: "flip_horizontal_2", label: "Mirror", hint: "A feature or the body, mirrored about a plane.", extra: true, need: { kind: ["mirror"] }, ask: "Mirror  about the plane  in this design." },
            { id: "shell", icon: "box", label: "Shell", keys: "Shift+S", hint: "Pick a flat face: the part hollowed out and open there." },
            { id: "draft", icon: "cone", label: "Draft", hint: "Faces tilted from the pull direction, for a mould or a print.", extra: true, need: { kind: ["draft"] }, ask: "Add a draft to this design: tilt the faces  by 2° from the pull direction, neutral plane ." },
            { id: "split", icon: "slice", label: "Split", hint: "The body cut in two by a plane or a face.", extra: true, need: { kind: ["split"] }, ask: "Split this design’s body at the plane  and keep ." },
            { id: "move_face", icon: "move", label: "Move face", hint: "A face pushed or pulled; the features around it follow.", extra: true, need: { kind: ["move_face", "moveface"] }, ask: "Move the face  of this design by  mm." }
        ] },
        { id: "reference", caption: "Reference", tools: [
            { id: "plane", icon: "diamond", label: "Plane", hint: "A datum plane to sketch on or mirror about.", extra: true, need: { kind: ["plane", "datum_plane"] }, ask: "Add a datum plane to this design: offset  mm from ." },
            { id: "axis", icon: "move_3d", label: "Axis", hint: "A datum axis to revolve or pattern about.", extra: true, need: { kind: ["axis", "datum_axis"] }, ask: "Add a datum axis to this design through ." }
        ] },
        { id: "insert", caption: "Insert", tools: [
            { id: "part", icon: "wrench", label: "Part here", keys: "Shift+B", hint: "Pick a hole or a face: a screw, insert, bearing or other bought part on it, its hole cut and its fit checked." },
            { id: "lattice", icon: "hexagon", label: "Lattice", hint: "A strut lattice or TPMS inside the part, with a skin: its density, stiffness and printability (a study in Check).", need: { bench: ["lattice"] } },
            { id: "text", icon: "type", label: "Text", hint: "Pick a flat face: raised or sunk lettering on it, as a feature of the design." }
        ] }
    ],
    prove: [
        { id: "inspect", caption: "Inspect", tools: [
            { id: "analyze", icon: "scan_line", label: "Analyze", keys: "A", hint: "Colour the part by wall thickness, overhang, section area or small features." },
            { id: "mass", icon: "weight", label: "Mass", keys: "C", hint: "The centre of mass and the principal axes, with the mass and inertia (computed on the B-rep)." },
            { id: "section", icon: "scissors", label: "Section", keys: "X", hint: "Cut the part open along X, Y or Z." }
        ] },
        { id: "studies", caption: "Studies", tools: [
            { id: "strength", icon: "gauge", label: "Strength", hint: "Stress, displacement and a safety factor with its stated error.", need: { bench: ["strength", "print.strength"] } },
            { id: "dfm", icon: "factory", label: "DFM", hint: "Can it be made: CNC, moulding or printing rules, each fix proved by checking again.", need: { bench: ["dfm_cnc", "dfm_injection", "dfm_fdm", "dfm_sla", "dfm_sls", "dfm_mjf", "dfm_lpbf"] } },
            { id: "fit", icon: "scaling", label: "Fit", hint: "How likely the part is to fit, from what is known of the printer.", need: { bench: ["fit"] } },
            { id: "stack", icon: "align_vertical_space_around", label: "Stack-up", hint: "A gap through the mates: worst case, RSS and Monte Carlo.", need: { bench: ["stack"] } },
            { id: "motion", icon: "orbit", label: "Motion", hint: "Play the mechanism: traces, clearance over the cycle.", need: { bench: ["motion"] } }
        ] },
        { id: "review", caption: "Review", tools: [
            { id: "assembly", icon: "boxes", label: "Assembly", keys: "E", hint: "Assembled, exploded or as printed. Move the joints.", need: { when: "assembly" } },
            { id: "history", icon: "history", label: "History", keys: "T", hint: "Scrub through the revisions. Looking changes nothing." },
            { id: "holds", icon: "box", label: "What it holds", hint: "The object or reference part, drawn in blueprint.", need: { when: "companions" } }
        ] }
    ],
    release: [
        { id: "print", caption: "Print", tools: [
            { id: "orient", icon: "rotate_3d", label: "Print orient", hint: "Orientations over support, time, strength and surface: the front, and the pick written to the print setup.", need: { bench: ["print.orient", "orientation"] } },
            { id: "plates", icon: "grid_3x3", label: "Plates", hint: "The parts as they lie on the plates.", need: { when: "plates" } },
            { id: "slice", icon: "layers", label: "Slice", hint: "Play the slicer’s toolpaths. Simulated, not a print.", need: { when: "print" } }
        ] },
        { id: "machine", caption: "Machine", tools: [
            { id: "cam", icon: "drill", label: "CAM", hint: "3-axis toolpaths and G-code, run on a stock model. Simulated, not proven on a machine.", need: { bench: ["cam_3axis"] } },
            { id: "flat", icon: "fold_horizontal", label: "Flat pattern", hint: "The sheet unfolded as a DXF, proved by folding it back.", need: { bench: ["sheet_flat"] } },
            { id: "board", icon: "circuit_board", label: "Board", hint: "The circuit board and its enclosure: fit, checks and fab files.", need: { bench: ["board.fit", "board.checks"] } }
        ] },
        { id: "output", caption: "Output", tools: [
            { id: "game", icon: "gamepad_2", label: "Game asset", hint: "LODs at triangle budgets, UVs, baked maps and collision, for Godot, Unity or Unreal (built in Blender).", need: { when: "game" } },
            { id: "render", icon: "camera", label: "Photo render", hint: "Render the current revision in Blender (an illustration)." }
        ] }
    ],
    document: [
        { id: "sheets", caption: "Sheets", tools: [
            { id: "drawing", icon: "drafting_compass", label: "Drawing", hint: "The engineering drawing from the solid: dimensions bound to parameters.", need: { bench: ["drawing"] } },
            { id: "views", icon: "cuboid", label: "Views", keys: "W", hint: "Front, side, top or the three-quarter view." },
            { id: "dims", icon: "ruler_dim", label: "Dimensions", hint: "The overall dimensions on the part." },
            { id: "pmi", icon: "crosshair", label: "PMI", hint: "STEP AP242 with the dimensions and tolerances in it, read back.", need: { bench: ["drawing.pmi"] } }
        ] },
        { id: "lists", caption: "Lists", tools: [
            { id: "bom", icon: "list", label: "BOM", hint: "The parts list to buy from.", need: { bench: ["doc.bom"] } },
            { id: "report", icon: "file_check", label: "Report", hint: "Measured results, every check and study with its evidence, open items and the verdict.", need: { bench: ["report"] } }
        ] },
        { id: "picture", caption: "Picture", tools: [
            { id: "frame", icon: "maximize_2", label: "Frame", keys: "F", hint: "Frame the part, or the selection." },
            { id: "render", icon: "camera", label: "Photo render", hint: "Render the current revision in Blender (an illustration)." }
        ] }
    ]
}

// the four tools of every mode. With the ribbon showing they are its first group, icons only and never moved into
// More, and no mode's group repeats them; with the ribbon hidden they head the dock at the stage's edge.
var UNIVERSAL = ["select", "measure", "section", "annotate"]
var COMMON = { id: "common", caption: "", fixed: true, tools: [
    { id: "select", icon: "mouse_pointer_2", label: "Select", keys: "V", hint: "Click a feature to edit it. Drag to orbit, shift-drag to pan." },
    { id: "measure", icon: "pencil_ruler", label: "Measure", keys: "M", hint: "Distances, faces and hole diameters, computed from the part’s surface." },
    { id: "section", icon: "scissors", label: "Section", keys: "X", hint: "Cut the part open along X, Y or Z." },
    { id: "annotate", icon: "map_pin", label: "Annotate", keys: "N", hint: "Pick faces, edges and points or paint a region; see what the solid says there, keep it with a note, ask the agent about it." }
] }

function modeOf(stage) { return stage === "fit" ? "prove" : stage === "brief" ? "shape" : (MODES[stage] ? stage : "shape") }
