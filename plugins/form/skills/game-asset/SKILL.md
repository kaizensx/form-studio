---
name: game-asset
description: Plan a Form Studio design as a game asset with triangle budgets, LODs, UVs, texture bakes, collision and engine presets for glTF, Godot, Unity and Unreal. Use when the person wants a model for a game engine rather than for printing or CAD exchange.
---

# Game assets

FORM tools: `design_guide()`, `create_design()`, `render_photo()`, `get_project()`.

1. Read `references/game.md` (also `design_guide(topic="game")`, which also says whether the game pipeline is in this
   build): budgets per LOD, UVs, bakes, collision, pivot and scale, and the engine presets.
2. The design source stays the authority; the asset is derived from it like STEP and STL. Pick the route per part:
   a subd cage for styled hard surface, sculpt for creatures and rocks, procedural for kits, the kernel for anything
   that must also fit a real object (see remodel-from-mesh, `references/hybrid.md`).
3. Print checks do not apply and nothing is sliced. Never ask about printers, filament or orientation for a game asset.
4. Where this build has no asset step yet, design the object as a 3D model (purpose "model") and export GLB; say that
   budgets, LODs, UVs and bakes wait for the game pipeline.

Textures are procedural or baked here, never downloaded.
