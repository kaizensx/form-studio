# Game assets

Form Studio can make a design ready for a game engine: levels of detail inside triangle budgets, UVs, baked textures and collision, exported for Unreal, Unity, Godot and glTF. The design stays real CAD underneath.

Game assets are **Beta** and new in version 1.1 (in the Preview channel first). Every asset passes its technical checks; visual quality is still improving.

## What you need

- **Blender.** The Game asset sheet builds the asset in Blender, run in the background by Form Studio. Install it from Settings › Engines & software, or let Form Studio find the one you have.
- **Optional: CoACD** for tighter collision than one convex hull per part. See the guide **Optional engines**.

## Start a game asset

- On Home choose **Make it for: Game asset**, set it in the brief, or just say so in your request ("a stylised treasure chest as a game prop").
- A design whose purpose is "game" is never sliced and never checked against a printer.
- It stays real CAD: STEP exports as always.

## The Game asset sheet

The sheet builds everything a game engine needs from the design:

- **LOD0 to LOD3** at triangle budgets. Subdivision cage levels come first. Decimated LODs are automatic retopology, and the sheet says so.
- **UVs.**
- **Baked maps:** base colour, normal, ORM and AO, at 1k, 2k or 4k.
- **Collision:** convex hulls, one per part. With CoACD installed, a game asset can ask for `collision="coacd"` to split concave parts into several convex pieces.

The viewport switches between LODs and shows each one's triangle count against its budget. It can show the asset shaded with its maps, as a UV checker, one map as it is stored, or as a wireframe.

## Engine presets

- **glTF and Godot:** GLB, metres, +Y up.
- **Unity:** FBX, metres.
- **Unreal:** FBX, centimetres, Z up, with collision hulls named `UCX_<asset>_LOD0_NN` after the LOD0 mesh.

**Export** saves every file as one zip.

## What is checked

The checks run on the files as they were written, not on what was intended:

- triangle budgets for every LOD
- closed and manifold meshes
- flipped faces
- UVs inside 0..1 and UV overlap
- texel density
- scale
- the baked normal map facing out of the surface
- FBX and USD read back at the design's size

## For agents

Agents use two tools: `model_mesh` (a cage modelled in Blender by declarative operations, streamed into the app as it is made) and `game_asset` (the LODs, UVs, bakes, collision and export). Both are in the [MCP reference](https://github.com/kaizensx/form-studio/blob/main/docs/MCP.md).

## What to expect from a Beta

- The technical side is checked on every asset: budgets, topology, UVs, maps and export.
- The look is the part still improving. Design refinement runs on a game asset only when you ask for it.
- How assets are measured, with every number and every failure published as it came out, is in [the game bench](https://github.com/kaizensx/form-studio/blob/dev/docs/GAME_BENCH.md).

## Tips

- Say the style and the budget in the request: "low-poly, under 5,000 triangles at LOD0".
- Say which engine it is for, so the preset, the units and the up axis are right from the start.
- For props with hollows, arches or handles, install CoACD: one convex hull per part would close the openings.
- Show what you made in #show-and-tell and talk pipelines, engines and budgets in #game-assets. For a problem, post in #help with the tag **Game assets**, your Blender version and the engine preset.
