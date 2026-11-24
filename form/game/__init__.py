"""Game assets: a design made ready for a game engine (the purpose "game", form/purpose.py).

    presets.py    engine presets (glTF, Godot, Unity, Unreal), budgets, texture sizes, bake presets
    lod.py        LOD plan from cage levels, convex hulls per part, optional CoACD (its own environment)
    materials.py  the procedural material library and a design's materials() (read from source, never run)
    pipeline.py   the build: here, then Blender's fixed runner (form/adapters/blender_game.py), then the GLB here
    validate.py   pure numpy checks of a GLB (budgets, manifold, normals, UV bounds and overlap, texel density, scale)

The design stays the geometry authority: an asset is derived output under <data>/.cache/game/<key>/, keyed by the
design's geometry key and every option, and never edited by hand. game_asset() reads a project and never changes it.

register(mcp) adds the game_asset tool; form/mcp_server.py wires it (integration package).
"""
from __future__ import annotations

import json
from pathlib import Path

ACTIONS = ("build", "validate", "export")


def _source_for(st, p: dict, materials, progress=None) -> tuple[dict, str, list]:
    """(pipeline source, geometry key, notes) for a project: the cage literal in its source when there is one, else
    the CAD solid's exported STL with its appearance() zones as materials."""
    from .. import meshio
    from ..studio import StudioError
    from . import pipeline
    notes = []
    keys = st.keys(p)
    text = st.source_text(p) or ""
    try:
        cages = pipeline.cages_in_source(text)
    except SyntaxError:
        cages = []
    if cages:
        if len(cages) > 1:
            notes.append(f"The source holds {len(cages)} cages; they are used together, as written.")
        from ..refine import game_eval
        from ..refine.ops_cage import refine_ops_of
        if refine_ops_of(text):                  # refinement's cage ops: replayed on the low cage, the bake source kept
            cage = game_eval.refined_cage(text, getattr(st, "cfg", None), Path(st.root) / ".cache" / "refine_cage")
            notes.append(f"{len(refine_ops_of(text))} refinement op(s) replayed on the cage (REFINE_OPS); the bake "
                         "source is the design's own.")
            return {"cage": cage, "materials": materials}, keys["geometry"], notes
        return {"cage": pipeline.merge_cages(cages), "materials": materials}, keys["geometry"], notes
    if st.read(p, "exports", keys["exports"]) is None:
        j = st.run_sync(p["id"], ["geometry", "exports"])
        if j["state"] != "done":
            raise StudioError("The design could not be exported, so there is no mesh to make a game asset from.",
                              "Fix the design first (get_project shows what failed).", status=422)
        p = st.load(p["id"])
        keys = st.keys(p)
    ex = st.read(p, "exports", keys["exports"])
    stl = st.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
    zones = []
    try:
        zd = st.apath(p, "exports", keys["exports"]).parent.parent / "game-zones" / keys["geometry"]
        zr = st._k("photo_zones", key=keys["geometry"], recipe_id=st.rid(p), values=st.rev(p)["values"],
                   out_dir=str(zd), p=p, timeout=600)
        zones = zr.get("zones") or []
    except Exception as e:                                       # noqa: BLE001 - zones are a nicety
        notes.append(f"Material zones were not read ({e}); one material is used.")
    import numpy as np
    by_name = materials if isinstance(materials, dict) else {}
    if zones:
        Vs, Ts, fm, mats = [], [], [], []
        off = 0
        for i, z in enumerate(zones):
            v, f = meshio.read_stl(Path(z["stl"]))
            Vs.append(v)
            Ts.append(f + off)
            fm.append(np.full(len(f), i))
            off += len(v)
            label = z.get("label") or f"zone{i}"
            # a zone takes the material named for its label or one of its features, else its appearance() finish
            pick = next((by_name[k] for k in [label] + list(z.get("features") or []) if k in by_name), None)
            if pick is None and label == "rest":
                pick = by_name.get("default")
            if pick is None:
                pick = {"finish": z.get("finish") or "matte", "color": z.get("color") or "#b8b2a7"}
            mats.append({**pick, "label": label})
        V = np.concatenate(Vs)
        T = np.concatenate(Ts)
        u, inv = np.unique(np.round(V, 6), axis=0, return_inverse=True)   # weld across zone borders
        return {"mesh": (u, inv.reshape(-1)[T]), "face_material": np.concatenate(fm), "materials": mats}, \
            keys["geometry"], notes
    V, T = meshio.read_stl(stl)
    if isinstance(materials, list):
        mats = materials[:1] or None
    else:
        mats = [by_name["default"]] if by_name.get("default") else None
    named = sorted(k for k in by_name if k != "default")
    if named:
        notes.append(f"Materials for {', '.join(named)} were not used: this CAD design declares no appearance() "
                     "zones, so its mesh is one material zone.")
    return {"mesh": (V, T), "materials": mats}, keys["geometry"], notes


def game_asset(st, project: str, action: str = "build", preset: str = "gltf", budgets=None, texture_px: int = 1024,
               bake: str = "fast", pivot: str = "bottom_center", uv: str = "auto", collision: str = "hull",
               retopo: str = "decimate", formats=None, materials=None, timeout: float | None = None,
               progress=None) -> dict:
    """Build, validate or export a project's game asset. Reads the project, never writes it: the asset goes to
    <data>/.cache/game/<key>/ (key: the geometry key and every option)."""
    from ..studio import StudioError
    from . import pipeline
    if action not in ACTIONS:
        raise StudioError(f"Unknown action “{action}”.", "Actions: build, validate, export.")
    try:
        opts = pipeline.check_options(preset, budgets, texture_px, bake, pivot, uv, retopo, collision, formats)
    except pipeline.GameError as e:
        raise StudioError(str(e), e.hint)
    from . import materials as matlib
    if materials is not None:
        try:
            if isinstance(materials, list):
                for i, m in enumerate(materials):
                    matlib.spec(f"zone{i}", m)
            else:
                matlib.check_map(materials)
        except matlib.MaterialError as e:
            raise StudioError(str(e), e.hint)
    p = st.load(project)
    from ..studio import H
    base = Path(st.root) / ".cache" / "game"
    keys = st.keys(p)
    source_note = ""
    if materials is None:                        # the design's own materials() (read, never run), as the app builds
        materials, source_note = matlib.materials_in_source(st.source_text(p) or "")
    key = H("game", keys["geometry"], pipeline.options_key(opts, materials))
    out = base / key
    if action == "validate":
        if not (out / "report.json").is_file():
            raise StudioError("There is no game asset with these options yet.", "Run game_asset with action=build.",
                              status=404)
        v = pipeline.revalidate(out)
        return {"project": project, "key": key, "dir": str(out), "validation": v, "evidence": "computed"}
    if (out / "report.json").is_file():
        rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
        rep.update(cached=True)
    else:
        src, _gk, notes = _source_for(st, p, materials, progress)
        from ..adapters.blender import BlenderFailed, BlenderMissing
        try:
            rep = pipeline.build(src, out, asset=p.get("name") or project, preset=opts["preset"]["id"],
                                 budgets=opts["budgets"], texture_px=opts["texture_px"], bake=bake, pivot=pivot, uv=uv,
                                 retopo=retopo, collision=collision, formats=formats, cfg=getattr(st, "cfg", None),
                                 timeout=timeout or pipeline.TIMEOUT_S, progress=progress)
        except pipeline.GameError as e:
            raise StudioError(str(e), e.hint)
        except BlenderMissing as e:
            raise StudioError(str(e), "Install Blender (Settings › Software); the game pipeline bakes in Blender.",
                              status=424)
        except BlenderFailed as e:
            raise StudioError(str(e), getattr(e, "hint", ""), status=422, log=getattr(e, "log", "")[-3000:])
        rep["notes"] = ([source_note] if source_note else []) + notes + rep.get("notes", [])
        rep.update(cached=False)
    files = {f: str(out / f) for f in rep.get("files", [])}
    res = {"project": project, "rev": p["head"], "key": key, "dir": str(out), "cached": rep["cached"],
           "preset": rep["preset"], "lods": rep["lods"], "uv": rep["uv"], "bake": rep.get("bake"),
           "collision": rep["collision"], "validation": {"ok": rep["validation"]["ok"],
                                                         "failed": [c for c in rep["validation"]["checks"]
                                                                    if c["status"] != "PASS"]},
           "size_mm": rep["size_mm"], "notes": rep.get("notes", []), "retopology_note": rep["retopology_note"],
           "materials": rep.get("materials", [])}
    if action == "export":
        res["files"] = files
    else:
        res["files"] = {k: v for k, v in files.items() if k.endswith((".glb", ".fbx", ".usd", "report.json"))}
    return res


def register(mcp, get_studio=None, run=None) -> None:
    """Add game_asset(project, action, preset, budgets, texture_px, ...) to an MCP server. Not wired here: the
    integration package calls it from form/mcp_server.py."""
    async def game_asset_tool(project: str, action: str = "build", preset: str = "gltf", budgets: list | None = None,
                              texture_px: int = 1024, bake: str = "fast", pivot: str = "bottom_center",
                              uv: str = "auto", collision: str = "hull", retopo: str = "decimate",
                              formats: list | None = None, materials: dict | None = None) -> dict:
        """Make a design a game asset: LOD0-LOD3 at triangle budgets (from subdivision cage levels first; decimated
        LODs are automatic retopology), UVs (region seams or Smart UV, packed), materials from the design's zones,
        Cycles-baked base colour, normal, ORM and AO maps (texture_px 1024|2048|4096; bake fast|quality), convex-hull
        collision per part (collision="coacd" when CoACD is installed), pivot and scale.
        preset: gltf | godot (GLB, metres, +Y up) | unity (FBX metres) | unreal (FBX cm, Z up; collision hulls
        UCX_<asset>_LOD0_NN, named after the LOD0 render mesh as Unreal pairs them).
        formats: extra fbx/usd. action: build | validate (re-check the GLB) | export (list every file).
        budgets: four triangle ceilings, LOD0 first (default 12000, 6000, 2500, 800).
        materials: {region or zone name | "default": {material, tint "#rrggbb", grain_mm, wear 0..1, roughness,
        emission}}; material is one of wood, bare_metal, brushed_metal, painted_metal, leather, plastic, rubber, stone,
        fabric, emissive (each with a baked height pattern; edge wear, cavity dirt and roughness breakup from the high
        poly's curvature, AO and thickness). The older {finish, color, pattern} form is still read. Left out, the
        design's own materials() method is used (a literal dict in its source, read without running it).
        Reads the project, never changes it. Every check is computed from the written GLB. Needs Blender 4.2+."""
        st = (get_studio or _default_studio)()

        def go():
            return game_asset(st, project, action, preset, budgets, texture_px, bake, pivot, uv, collision, retopo,
                              formats, materials)
        if run is not None:
            return await run(go)
        from ..mcp_server import _run as default_run
        return await default_run(go)
    game_asset_tool.__name__ = "game_asset"
    game_asset_tool.__qualname__ = "game_asset"
    try:
        from mcp.types import ToolAnnotations
        ann = {"annotations": ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                              open_world_hint=False)}
    except ImportError:
        ann = {}
    mcp.tool(name="game_asset", **ann)(game_asset_tool)


def _default_studio():
    from ..mcp_server import studio
    return studio()
