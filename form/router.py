"""The hybrid router: which construction route each planned feature takes.

A design is no longer one kind of geometry. A sculpted creature head with a magnet pocket, a smooth mouse shell with
screw bosses, a modular wall with repeated bricks: each feature is best made by a different route, and the plan says
which one per feature.

  kernel        parametric B-rep in build123d / OCCT with form.craft: holes, threads, bosses, snaps, bearing seats,
                mating faces, plates and walls. Exact and editable through its Params.
  subd_cage     a quad cage (form.craft.subd.Cage) whose limit surface becomes exact CAD patches: smooth styled forms
                (a mouse shell, a fairing, a helmet crown). Edited by moving cage points and named Handles.
  sculpt_recon  sculpted mesh detail (model_mesh sculpt ops, when available), then brought back as a surface with
                subd.fit_cage or form/recon/freeform.py: creatures, faces, wrinkles, weathering. Approximate.
  procedural    repeated or generated detail: Geometry Nodes or craft.MeshTexture on the mesh tier, form.patterns
                (and craft.knurl and friends) on the kernel tier.

route_feature() is a keyword heuristic over the feature's words (English and Portuguese), and says so: it returns the
route, the words that chose it (`because`) and evidence "heuristic". It does not detect everything. A feature none of
whose words it knows gets the kernel route with confident False, and plan_design writes that back into the brief's
unknowns instead of pretending to know.

Plain data only: no kernel, no Blender.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ROUTES = ("kernel", "subd_cage", "sculpt_recon", "procedural")

#: words naming a mechanical interface: something another part, a screw, a bearing or a magnet has to fit. A feature
#: that names one is built in the kernel, whatever it sits on (a magnet pocket in a sculpted head is still a pocket)
INTERFACE = (
    # English
    "hole", "bore", "counterbore", "countersink", "countersunk", "thread", "threaded", "tapped", "screw", "bolt", "nut",
    "insert", "heat-set", "boss", "magnet", "magnetic", "snap", "snap-fit", "clip", "latch", "bearing",
    "press-fit", "mating", "mate", "mount", "mounting", "pin", "dowel", "shaft", "keyway", "socket", "hinge", "o-ring",
    "gasket", "standoff", "dovetail", "rail", "bayonet", "detent",
    # Portuguese (without accents)
    "furo", "rosca", "roscado", "roscada", "parafuso", "porca", "inserto", "iman", "ima", "magnete", "magnetico",
    "encaixe", "engate", "clipe", "trava", "rolamento", "pino", "eixo", "cavilha", "dobradica", "montagem",
    "fixacao", "rebaixo", "escareado", "baioneta",
)
#: a bare "seat" is a chair as often as a bearing: only these seats are interfaces
INTERFACE_PHRASES = ("mating face", "mating surface", "bearing seat", "valve seat", "magnet seat", "seal seat",
                     "press fit", "assento do rolamento", "assento de rolamento", "face de contacto",
                     "face de contato", "superficie de contacto", "encaixe de pressao")

#: words of sculpted, high-frequency organic detail
SCULPT = (
    "sculpt", "sculpted", "sculpting", "creature", "dragon", "monster", "facial", "bust", "anatomy", "anatomical",
    "muscle", "vein", "wrinkle", "wrinkled", "pore", "scales", "claw", "fur", "hair", "feather", "weathered", "eroded",
    "erosion", "damage", "damaged", "crack", "cracked", "folds", "drapery", "statue", "figurine", "character", "rock",
    "zbrush", "dyntopo", "scan", "scanned", "photogrammetry", "gnarled", "bark", "mane", "wart", "chipped", "broken",
    "cartilage", "tendon", "talon", "fang", "tusk",
    "esculpido", "esculpida", "esculpir", "escultura", "criatura", "dragao", "monstro", "busto", "rosto", "faciais",
    "anatomia", "anatomico", "musculo", "veia", "ruga", "poro", "escamas", "garra", "chifre", "cabelo", "pena",
    "erodida", "erodido", "erosao", "desgastado", "desgastada", "rachadura", "fissura", "prega", "estatua",
    "estatueta", "personagem", "rocha", "pedra", "verruga", "lascado", "lascada", "juba", "presa",
    "cartilagem",
)
SCULPT_PHRASES = ("battle damage", "cloth folds", "organic detail", "skin detail", "casca de arvore")

#: words of repeated or generated detail
PROCEDURAL = (
    "pattern", "patterned", "texture", "textured", "knurl", "knurled", "knurling", "voronoi", "gyroid", "lattice",
    "honeycomb", "array", "arrayed", "repeat", "repeating", "repeated", "scatter", "scattered", "tile", "tiles",
    "tiling", "brick", "rivet", "greeble", "perforated", "perforation", "grille", "ribbed", "ribs", "fluted", "flutes",
    "noise", "displacement", "procedural", "geonodes", "foliage", "grass", "modular", "infill", "emboss", "embossed",
    "grain", "leather", "woven", "weave", "stud", "louvre", "louver",
    "padrao", "padroes", "textura", "texturizado", "texturizada", "recartilhado", "recartilha", "colmeia", "trelica",
    "matriz", "repetido", "repetida", "repeticao", "espalhado", "espalhada", "espalhar", "azulejo", "ladrilho", "tijolo",
    "rebite", "grelha", "perfurado", "perfuracao", "nervuras", "canelado", "ruido", "folhagem", "relva", "grama",
    "aleta", "gravado", "relevo", "couro", "tecido", "trama",
)
PROCEDURAL_PHRASES = ("geometry nodes", "nos de geometria")

#: words of repetition: with one of them, repeated detail is procedural even when it is organic ("fish scales
#: repeated on the roof"), unless an interface is named
REPEAT = ("repeat", "repeating", "repeated", "array", "arrayed", "tiling", "tile", "tiles", "scatter", "scattered",
          "repetido", "repetida", "repeticao", "matriz", "espalhado", "espalhada", "espalhar", "ladrilho", "azulejo")

#: words of smooth, styled, designed surfaces
SUBD = (
    "smooth", "smoothly", "sleek", "flowing", "streamlined", "aerodynamic", "ergonomic", "curved", "curvy", "rounded",
    "soft", "organic", "styled", "fairing", "fuselage", "hull", "canopy", "bodywork", "shell", "helmet", "visor",
    "mouse", "controller", "grip", "dome", "pebble", "subd", "subdivision", "cage", "nurbs", "teardrop", "sculptural",
    "liso", "lisa", "suave", "fluido", "fluida", "aerodinamico", "aerodinamica", "ergonomico", "ergonomica", "curvo",
    "curva", "arredondado", "arredondada", "organico", "organica", "carenagem", "fuselagem", "casco", "carrocaria",
    "carroceria", "carcaca", "capacete", "viseira", "rato", "comando", "pega", "punho", "cupula", "confortavel",
    "escultural", "gota",
)
SUBD_PHRASES = ("car body", "class-a", "class a surface")

#: words of plain prismatic or turned construction (the kernel without an interface)
GENERAL = (
    "plate", "wall", "box", "bracket", "flange", "fillet", "chamfer", "chamfered", "cutout", "slot", "groove",
    "knuckle", "tab", "lid", "enclosure", "gusset", "spacer", "block", "frame", "step", "pocket", "recess", "notch",
    "extrude", "extruded", "prismatic", "revolve", "revolved", "turned", "web", "rib", "lip", "ledge",
    "placa", "parede", "caixa", "tampa", "suporte", "chanfro", "chanfrado", "filete", "ranhura", "rasgo", "aba",
    "bloco", "moldura", "recorte", "degrau", "bolso", "nervura", "batente",
)

#: the order a feature's route is picked in when its words name several (the interface first: it must be exact)
PRIORITY = ("sculpt_recon", "procedural", "subd_cage", "kernel")
_FAMILIES = {"sculpt_recon": (SCULPT, SCULPT_PHRASES), "procedural": (PROCEDURAL, PROCEDURAL_PHRASES),
             "subd_cage": (SUBD, SUBD_PHRASES), "kernel": (GENERAL, ())}

#: hardware phrases whose keyword is not form ("a bolt pattern" is holes, "a hex head" is a screw)
_NOT = re.compile(r"\b(?:bolt|hole|mounting|screw|drill|fixing)\s+patterns?\b|\bpatterns?\s+of\s+(?:holes|screws|bolts)\b",
                  re.I)

#: the helpers and tools each route builds with. Helper names are checked against staged.registry() (and form/recon
#: for recon.*) by tests/test_router.py; model_mesh is an MCP tool that may not be installed yet ("when available")
ROUTE_HELPERS = {
    "kernel": {"helpers": ["craft.safe_cut", "craft.safe_union", "craft.safe_fillet", "craft.magnet_pocket",
                           "craft.cantilever_snap", "craft.bearing_fit", "craft.boss_array"],
               "tools": [],
               "how": "build123d solids and form.craft helpers; every interface size is a Param"},
    "subd_cage": {"helpers": ["craft.subd.Cage", "craft.subd.Handle", "craft.subd.apply_handles",
                              "craft.subd.patches_solid", "craft.subd.seam_angles", "craft.subd.quad_sphere",
                              "craft.subd.dome_cage"],
                  "tools": ["model_mesh"],
                  "how": "a quad cage as data in the design (craft.subd.Cage), shaped by cage points and named Handles "
                         "(model_mesh cage ops in Blender when available); its limit surface becomes CAD patches "
                         "(patches_solid) with the seam angles measured"},
    "sculpt_recon": {"helpers": ["craft.subd.fit_cage", "craft.subd.Cage", "recon.freeform.fit_patch",
                                 "recon.freeform.candidates"],
                     "tools": ["model_mesh"],
                     "how": "sculpt the detail as a mesh (model_mesh sculpt ops, when available), then bring it back "
                            "as a surface: craft.subd.fit_cage onto a cage, or form/recon/freeform.py spline patches; "
                            "the result is approximate and its deviation is measured, never called exact"},
    "procedural": {"helpers": ["craft.MeshTexture", "patterns.hex_vents", "patterns.perforation_grid",
                               "patterns.slot_array", "patterns.grip_ribs", "patterns.knurl", "craft.knurl",
                               "craft.emboss_cells", "craft.wrapped_ribs", "craft.rib_grid", "craft.lattice"],
                   "tools": ["model_mesh"],
                   "how": "kernel tier: form.patterns (hex_vents, perforation_grid, slot_array, grip_ribs, knurl) or "
                          "craft.knurl / emboss_cells / wrapped_ribs as B-rep; mesh tier: craft.MeshTexture or "
                          "Geometry Nodes (model_mesh geonodes_array / geonodes_scatter, when available), which "
                          "STEP does not carry"},
}
#: helpers that keep a procedural feature in the kernel (B-rep): a feature naming one of them is not mesh-only
KERNEL_PROCEDURAL = ("patterns.", "craft.knurl", "craft.emboss_cells", "craft.wrapped_ribs", "craft.spiral_ribbed_body",
                     "craft.rib_grid", "craft.lattice", "craft.slot_grille", "craft.boss_array", "craft.patterns")
#: helpers that bring a sculpted feature back to a surface the kernel can cut
RECON_HELPERS = ("fit_cage", "freeform", "fit_patch")


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _tokens(text: str) -> set:
    """Words without accents, hyphenated words also split, a plural s (and Portuguese -es/-ns) dropped."""
    out = set()
    for w in re.findall(r"[a-z][a-z\-]*", text):
        for t in [w, *w.split("-")]:
            t = t.strip("-")
            if not t:
                continue
            out.add(t)
            if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
                out.add(t[:-1])
                if t.endswith("ns"):
                    out.add(t[:-2] + "m")
    return out


def _hits(words: set, low: str, kws, phrases=()) -> list[str]:
    return sorted({k for k in kws if k in words} | {p for p in phrases if p in low})


def interface_words(text: str) -> list[str]:
    """The mechanical-interface words in a text (hole, thread, magnet pocket, snap, bearing seat, mating face...).
    Helper names count by their words (craft.magnet_pocket names a magnet)."""
    low = _plain((text or "").replace("_", " "))
    return _hits(_tokens(low), low, INTERFACE, INTERFACE_PHRASES)


def feature_text(f: dict) -> str:
    """The words of a planned feature its route is read from: id (underscores as spaces), label and how."""
    return " ".join([str(f.get("id", "") or "").replace("_", " ")]
                    + [str(f.get(k, "") or "") for k in ("label", "how")])


#: helper references in a how: craft.x, craft.module.x, parts.x, patterns.x, marks.x, recon.module.x
_HELPER = re.compile(r"\b(?:form\.)?((?:craft|parts|patterns|marks|recon)(?:\.[A-Za-z_][A-Za-z0-9_]*){1,2})")
#: craft helpers that make repeated or generated detail
PROCEDURAL_HELPERS = ("MeshTexture", "knurl", "emboss_cells", "wrapped_ribs", "spiral_ribbed_body", "rib_grid",
                      "lattice", "slot_grille", "boss_array", "patterns", "meshtex")


def helpers_in(text: str) -> list[str]:
    """The helper names a text references (not checked here; staged.check_how and check_helper do that)."""
    return list(dict.fromkeys(m.group(1) for m in _HELPER.finditer(text or "")))


def _helper_route(name: str) -> str:
    parts = name.split(".")
    bare = parts[-1]
    if parts[0] == "recon" or bare == "fit_cage":
        return "sculpt_recon"
    if "subd" in parts[1:]:
        return "subd_cage"
    if parts[0] == "patterns" or bare in PROCEDURAL_HELPERS or (len(parts) > 2 and parts[1] in PROCEDURAL_HELPERS):
        return "procedural"
    return "kernel"


def route_feature(text: str) -> dict:
    """The route for one feature: {"route", "because", "evidence": "heuristic", "confident", "also"}.
    When the how names helpers, they state the construction and decide (craft.subd.* -> subd_cage, fit_cage or
    recon.* -> sculpt_recon, patterns.* / MeshTexture / knurl -> procedural, any other helper -> kernel). Otherwise
    the words decide: a mechanical interface always takes the kernel, then sculpt, procedural, smooth styled, plain
    construction, in that order. No known word and no helper: kernel with confident False (an unknown the brief
    should list)."""
    names = helpers_in(text)
    rest = _HELPER.sub(" ", text or "").replace("_", " ")
    low = _plain(_NOT.sub(" hole ", rest))
    words = _tokens(low)
    iface = _hits(words, low, INTERFACE, INTERFACE_PHRASES)
    fams = {r: _hits(words, low, *_FAMILIES[r]) for r in PRIORITY}
    if iface:
        fams["kernel"] = sorted(set(fams["kernel"]) | set(iface))
    if names:
        by = {}
        for n in names:
            by.setdefault(_helper_route(n), []).append(n)
        pick = next(r for r in PRIORITY if r in by)
        because = by[pick]
    elif iface:
        pick, because = "kernel", iface
    elif _hits(words, low, REPEAT):
        pick, because = "procedural", fams["procedural"]
    else:
        pick = next((r for r in PRIORITY if fams[r]), None)
        because = fams[pick] if pick else []
    also = {r: v for r, v in fams.items() if v and r != pick}
    out = {"route": pick or "kernel", "because": because, "evidence": "heuristic", "confident": pick is not None,
           "also": also}
    if not out["confident"]:
        out["note"] = "no word the router knows; kernel by default"
    return out


def feature_route(f: dict) -> dict:
    """A planned feature's route: the one the plan states (`route`, evidence "stated"), else route_feature()."""
    given = str(f.get("route") or "").strip()
    if given:
        return {"route": given, "because": ["stated in the plan"], "evidence": "stated", "confident": True, "also": {}}
    return route_feature(feature_text(f))


def validate(features: list) -> list[str]:
    """Problems with stated routes: unknown route names."""
    bad = []
    for f in features:
        r = f.get("route") if isinstance(f, dict) else None
        if r is not None and str(r).strip() not in ROUTES:
            bad.append(f"{f.get('id')}: {r!r}")
    return bad


def mesh_only(route: str, how: str = "") -> bool:
    """Is a feature on this route a mesh with no exact B-rep? sculpt_recon is (until a recon helper brings it back as
    an approximate surface, and even then it is not exact); procedural is unless its how names a kernel-tier helper."""
    low = (how or "").lower()
    if route == "sculpt_recon":
        return not any(h in low for h in RECON_HELPERS)
    if route == "procedural":
        return not any(h.lower() in low for h in KERNEL_PROCEDURAL)
    return False


def warnings(features: list) -> list[str]:
    """A mechanical interface (hole, thread, magnet pocket, snap, bearing seat, mating face) on a mesh-only route:
    stated on the feature itself, or cut into a body (the first feature of its part) that is mesh-only."""
    out = []
    routes = {f["id"]: feature_route(f) for f in features}
    body = {}                                         # part -> its first feature (the body later features cut into)
    for f in features:
        body.setdefault(f.get("part") or "", f)
    for f in features:
        iw = interface_words(feature_text(f))
        if not iw:
            continue
        r = routes[f["id"]]["route"]
        if mesh_only(r, str(f.get("how", ""))):
            out.append(f"{f['id']}: a mechanical interface ({', '.join(iw)}) on the {r} route, which is mesh only; "
                       "build it in the kernel so its size is exact and editable")
            continue
        b = body.get(f.get("part") or "")
        if b is not None and b is not f:
            br = routes[b["id"]]["route"]
            if mesh_only(br, str(b.get("how", ""))):
                out.append(f"{f['id']}: a mechanical interface ({', '.join(iw)}) cut into {b['id']}, which is on the "
                           f"{br} route (mesh only); fit that body back to a surface first (craft.subd.fit_cage or "
                           "form/recon/freeform.py) or put the interface on a kernel part")
    return out


def unknowns(features: list) -> list[str]:
    """The brief's unknowns for features whose route the router could not read."""
    return [f"Route of feature {f['id']} ({f.get('label', '')}) not detected from its words (heuristic); built in the "
            "kernel by default. Confirm it or give route= kernel, subd_cage, sculpt_recon or procedural."
            for f in features if not feature_route(f)["confident"]]


def model_mesh_available() -> bool:
    """Is the model_mesh MCP tool present in this build (registered by the Blender modelling bridge)?"""
    here = Path(__file__).resolve().parent
    for f in (here / "adapters" / "blender_model.py", here / "mcp_server.py"):
        try:
            if "model_mesh" in f.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
    return False


def recon_names(module: str = "freeform") -> set:
    """Public names of form/recon/<module>.py, read without importing it."""
    from .staged import _public_names
    return _public_names(Path(__file__).resolve().parent / "recon" / f"{module}.py")


def check_helper(name: str) -> bool:
    """Does this helper name exist? craft.*, parts.*, patterns.*, marks.* against staged.registry(); recon.<m>.<x>
    against form/recon/<m>.py."""
    if name.startswith("recon."):
        _, mod, attr = name.split(".", 2)
        return attr in recon_names(mod)
    from .staged import check_how
    c = check_how(name)
    return bool(c["helpers"]) and not c["unknown"]


def plan_for(route: str) -> dict:
    """What a step on this route builds with: real helper names, the tools (model_mesh only when present; otherwise
    named with "when available"), and how."""
    h = ROUTE_HELPERS[route]
    have = model_mesh_available()
    tools = [{"tool": t, "available": have} for t in h["tools"]]
    return {"helpers": list(h["helpers"]), "tools": tools, "how": h["how"]
            + ("" if have or not h["tools"] else " (model_mesh is not installed in this build: use the craft helpers)")}
