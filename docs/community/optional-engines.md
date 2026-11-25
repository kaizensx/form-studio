# Optional engines and programs

Form Studio builds, checks and exports CAD with nothing but its own kernel. Everything on this page is optional: an engine or a program that adds one capability, installed only when you ask for it. This guide says what each one does, when it is worth it, how big it is and under which licence it comes.

Optional engines installed in one click are new in version 1.1 (in the Preview channel first).

## How installing works

- **Settings › Software** lists everything Form Studio uses, what is installed, and an **Install** button for the rest. Each entry says what it does, what it gives you, its size and its licence before anything is downloaded.
- From a terminal: `form install --list` shows everything, `form install <id>` installs one item after showing its commands (`--dry-run` only shows them).
- Engines that need Python libraries Form Studio does not carry get **a Python of their own**, kept in `.engines` inside your Form Studio data folder, and run out of the app. Form Studio downloads a pinned release of uv and checks its SHA-256 before using it.
- An install is built in a temporary folder and moved into place only when every step worked. A failed or cancelled install leaves whatever was there before as it was.
- **Remove** deletes only what Form Studio itself downloaded for an engine. Programs installed by another installer (a slicer, Blender, an agent app) are never removed by Form Studio.

## CAD-Recode: learned mesh to CAD

- **What it does:** a learned model that reads a mesh as a point cloud and writes a sketch-and-extrude CAD program for it.
- **What it gives you:** one more mesh-to-CAD proposal for simple prismatic parts. Every proposal is snapped to the mesh and kept only when it verifies.
- **Worth it if** you often turn STL or 3MF files of simple, boxy parts into editable CAD. Mesh to CAD works fully without it.
- **Size:** 3.09 GB of weights, plus about 1 GB of PyTorch and Transformers.
- **Licence:** CC BY-NC 4.0, non-commercial use only. The download does not start until you accept it.
- **Runs** on your computer, offline once downloaded.
- **Install:** Settings › Software, or `form install recon.learned`.
- **Source:** [huggingface.co/filapro/cad-recode](https://huggingface.co/filapro/cad-recode)

## CADFit: mesh to CAD search

- **What it does:** a search that tries extrusions and revolves against a mesh and keeps the ones that fit it best, as an editable program (Nehme, Whalen, Ahmed).
- **What it gives you:** one more mesh-to-CAD candidate made of extrudes and revolves, kept only when it verifies.
- **Worth it when** a part made of extruded and turned shapes does not come out right with the built-in route. It is slower than the built-in route.
- **Size:** about 0.7 GB (its own Python 3.12 with build123d, trimesh, scikit-learn, SciPy and manifold3d).
- **Licence:** CC BY-NC 4.0, non-commercial use only, included with its author's permission. Form Studio's MIT licence does not cover the `form/recon/cadfit/` folder.
- **Off until installed.** Installing it sets `[recon] cadfit = true` in `studio.toml`.
- **Install:** Settings › Software, or `form install recon.cadfit`.
- **Source:** [github.com/ghadinehme/CADFit](https://github.com/ghadinehme/CADFit)

## CoACD: collision for game assets

- **What it does:** approximate convex decomposition. It splits a concave part into several convex pieces for a game engine's physics.
- **What it gives you:** tighter collision for game assets than one convex hull per part.
- **Worth it for** game assets with hollows, arches or handles, where one convex hull per part would close the openings. Without it, game assets get a convex hull per part.
- **Size:** about 60 MB (its own Python 3.12 with CoACD and NumPy).
- **Licence:** MIT.
- **Off until** a game asset asks for `collision="coacd"`.
- **Install:** Settings › Software, or `form install game.coacd`.
- **Source:** [github.com/SarahWeiii/CoACD](https://github.com/SarahWeiii/CoACD)

## The CADEvolve corpus: reference examples for the agent

- **What it is:** a library of about 8,000 parametric CadQuery example programs.
- **What it gives you:** more worked examples for the agent to learn constructions from, offered after Form Studio's own design examples and labelled as reference CadQuery, not the Form API.
- **Read as text, never run.** Designs are still written with Form Studio's own tools.
- **Size:** a 4.73 GB download, of which only `CADEvolve-G/parametric_generators.json` is kept.
- **Licence:** Apache-2.0.
- **Install:** Settings › Software, or `form install exemplars.cadevolve`.
- **Source:** [huggingface.co/datasets/kulibinai/cadevolve](https://huggingface.co/datasets/kulibinai/cadevolve)

## Blender

- **What Form Studio does with it:** runs it in the background to make studio-lit pictures of a design, to bake game assets (levels of detail, UVs and texture maps) and to run organic modelling steps on subdivision cages.
- **Never used for measurements.**
- **What it gives you:** photoreal renders, game assets and organic modelling.
- **Size:** about 400 MB.
- **Licence:** Blender's own. It is a separate program that Form Studio starts; it is installed by its own installer or found where you already have it.
- **Source:** [blender.org/download](https://www.blender.org/download/)

## FreeCAD

- **What Form Studio does with it:** **Open in FreeCAD** hands it a design, with a macro that puts every parameter in a spreadsheet. The checks also read each design's STEP export back in FreeCAD, as a second CAD program's check that it imports cleanly.
- **What it gives you:** Open in FreeCAD, and an independent check of every STEP export.
- **Size:** about 700 MB.
- **Licence:** FreeCAD's own. A separate program.
- **Source:** [freecad.org/downloads.php](https://www.freecad.org/downloads.php)

## OpenSCAD

- **What Form Studio does with it:** builds designs written in the OpenSCAD language. Customizer ranges become parameters.
- **Worth it if** you or your agent write OpenSCAD. Those designs are meshes: they export STL and 3MF, not STEP.
- **Size:** about 50 MB.
- **Licence:** OpenSCAD's own. A separate program.
- **Source:** [openscad.org/downloads.html](https://openscad.org/downloads.html)

## Slicers (only if you 3D print)

One slicer is enough, and none is needed unless you print. Form Studio reads the printer, filament and process you already have set up in it.

- **Bambu Studio** (about 200 MB): Bambu Lab printers.
- **OrcaSlicer** (about 150 MB): most printers, including Bambu Lab, Prusa, Creality and Voron.
- **PrusaSlicer** (about 100 MB): Prusa printers and many others.
- **SuperSlicer** (about 120 MB): a PrusaSlicer fork with more settings.
- **QIDISlicer** (about 170 MB): QIDI printers.
- **ElegooSlicer:** Elegoo printers.
- **Snapmaker Orca:** Snapmaker printers.

**What a slicer gives you:** a slice of each design made for printing (a simulation): print time, filament and the layers to look through. Each slicer is a separate program under its own licence. More in the guide **3D printing**.

## What is always there

- **The CAD kernel** (about 250 MB): build123d on OpenCascade, the geometry engine every design is built with. Required.
- **Standard-parts libraries** (about 5 MB): bd_warehouse and py_gearworks, for real screws, threads, bearings and gears at their catalogue sizes. Recommended.

The licences of everything Form Studio ships or can install are in [THIRD_PARTY_NOTICES.md](https://github.com/kaizensx/form-studio/blob/dev/THIRD_PARTY_NOTICES.md).
