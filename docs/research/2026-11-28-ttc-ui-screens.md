# text-to-cad Studio: every public screen, read on 2026-11-28

This covers the main window (`screens/app.webp`), the four Toolbox shots, and the poster frames of the 12 clips on
texttocad.studio. They are compared here with Form Studio's direction I. We learn the behaviour from them and do not copy
their design.

## What they show

| Area | What the reference does | Form Studio today | To do |
|---|---|---|---|
| Window frame | A left sidebar with Studio, Home, Toolbox, Projects (each project nests its chats), Trash and Settings. Document tabs along the top: Overview, the part, reports, FEA, CAM, drawing, molding review, and more | Home is its own screen. No sidebar and no document tabs; each design is one window state | Add document tabs for the design, each study, each drawing and each report. Make the Home shelf reachable from a slim rail or ⌘O |
| Tool ribbon | Tabs: Features, Sketch, Evaluate, Drawing. Labelled tools grouped Create / Modify / More: Sketch, Extruded Boss, Extruded Cut, Revolved Boss, Revolved Cut, Swept, Lofted, Rib, Hole Wizard, Pattern, Mirror, Move Face, Fillet, Chamfer, Shell, Draft, Split, Delete Face. A "Hide CAD tools" toggle | A vertical dock that changes with the mode, icons only | Add a labelled ribbon per mode with group captions that can collapse to the dock. Fill the engine gaps (branch `more-features`) |
| Feature dialog | A property manager per feature, e.g. Extruded Cut: section, Direction 1 end condition (Blind, …), depth, reverse, draft, Direction 2, thin feature, a preview of the material taken away, then OK / Cancel | The tool-options capsule, with depth only | Add a pane-side property card per feature with end conditions, two directions, draft and thin feature (engine: `more-features`) |
| FeatureManager | Part, Equations, Material, Origin with its three planes, then features with visibility dots and expandable sketches. A PMI panel below: views, notes, datums, toleranced dimensions | A tree with values and author marks, and a rollback bar | Add origin planes, parameters as equations, material, purchased parts, visibility toggles and nested sketches. Add a PMI section from wave F |
| Sketch editing | A sketch editor with relations shown as green glyph pairs, "Under defined, 6 ways it can still move", named driving dimensions (SLOT_LENGTH), a Driven toggle, and Exit Sketch / Discard Changes | Sketch on the part with glyph tags, the DOF count in the capsule, and typed dimensions | Name dimensions inline, add a driven/reference toggle, Exit and Discard in the capsule, and say in words which ways the sketch can still move |
| Chat sketch | A "Draw a sketch" pad with Select, Line, Rectangle, Circle, Arrow, Dimension, Text and a sentence of intent. Only typed numbers count as sizes | A sketch pad exists (start photo/sketch) | Check it has Arrow and Text notes and the "only typed numbers are sizes" rule |
| Toolbox | Tiles grid in Analysis / Manufacturing / Documents, each tile with an icon and a short name; the list form gives one sentence each and a Run button; "See what each makes" | The Bench, with 30+ rows and an opened card | Add a tile view toggle to the Bench sheet and one sentence per row with Run. Keep our states and evidence, which they lack |
| Studies | A study panel: verdict ("Too weak, OK only to 0.7× this load"), hand check, held/pushed faces, material, a "What you see" list, deformation and load sliders, loads and fixtures toggle, and an on-screen caption | The result drawn on the part, the legend strip with its stated error, and a card with convergence | Add a load-scale slider (linear, so honest) and a verdict sentence on the card. Never claim a factor without its error |
| Versions | A versions list; "What changed": one model / side by side / script; dimensions that changed with values; volume and size deltas; Open in 3D | Revisions, branches and `geometry_diff` | Add a version compare sheet: one model with changes highlighted, side by side, the script diff, and dimension and volume deltas |
| Home | "Welcome back", a composer with Attach / Sketch / Project, project cards with renders, Import / New | Home with composer, starts, shelf and families | Keep it. It is already richer |

## Where Form Studio already leads

- Results are drawn on the part with stated error, singularities and "not told here". They show a scale and a sentence only.
- Every number carries its evidence class, and Sources come from the tool log.
- Real slicers on every printer, multi-plate, CAM simulated from the posted G-code, inverse design, and topology written back as features.
- A larger stage: their chat plus tree take about 700 px, and the toolbox overlays the part.
