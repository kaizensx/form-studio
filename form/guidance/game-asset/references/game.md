GAME ASSETS (purpose "game", when the game pipeline is available in this build)
A game asset is a mesh an engine draws many times a second: triangles, UVs and textures are the budget, not
tolerances. The design source stays the authority; the asset is derived from it like STEP and STL are.

WHAT A GAME ASSET NEEDS
  * Budgets: a triangle count per LOD (a hand prop about 2-8 k triangles at LOD0, a hero character far more); each
    LOD is checked against its budget.
  * LODs: LOD0 to LOD3, each about half the triangles of the one before. A subd cage gives clean LODs from its
    subdivision levels; CAD or sculpted bodies are decimated or retopologised automatically, which is not hand
    topology, and is said so.
  * UVs: unwrapped with seams at region borders (or a smart unwrap), packed inside 0-1 with little overlap and an even
    texel density.
  * Bakes: base colour, normal (high poly to low poly), ORM (occlusion, roughness, metallic) and AO, at 1k, 2k or 4k.
    Textures are procedural or baked here, never downloaded.
  * Collision: a convex hull per part by default; a convex decomposition when the shape needs it.
  * Pivot and scale: pivot at the base or the grip, real-world scale in the engine's unit.

ENGINE PRESETS
  * glTF / Godot: GLB, metres, +Y up (glTF is the primary format).
  * Unity: FBX, metres.
  * Unreal: FBX, centimetres, Z up, collision hulls named UCX_<render mesh>_NN, the render mesh being the exported
    LOD0 node, so UCX_<asset>_LOD0_00, UCX_<asset>_LOD0_01... (Unreal pairs UCX_ hulls with the mesh they name).

ROUTES FOR GAME ASSETS (design_guide topic "hybrid")
  Styled hard surface: subd_cage, so LODs come from the cage. Creatures and rocks: sculpt_recon, baked down to a low
  poly. Kits and repeated detail: procedural. Parts that must also fit a real object stay kernel.

Print checks do not apply to a game asset, and nothing is sliced. Until the pipeline is in this build, design the
object as a 3D model (purpose "model") and export GLB; budgets, LODs, UVs and bakes then wait for it.
