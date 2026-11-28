"""What an agent needs to write a FORM design: the contract, the rules, and an example that builds.

The texts live once, as Agent Skills, in form/guidance/<skill>/ (see form/guidance/__init__.py): each topic is one
reference file there, returned here unchanged. The MCP skills extension (form/mcp_skills.py) and the Claude Code plugin
(plugins/form/skills, written by scripts/gen_skills.py) serve the same bytes.
"""
from . import guidance as _g

# rules 5-6 depend on what the design is for (form/purpose.py): bed orientation, overhangs and nozzle walls only for a print
_PRINT = {"pipeline": "renders, checks, fit model, slice, revisions, optimizer, animation, release.",
          "rules_5_6": """\
  5. Print orientation: model every part as it sits on the bed (flat face on z = 0). Put multiple parts
     side by side with at least 5 mm between them and set solids = N.
  6. Prefer chamfers on bottom edges and 45° ceilings over flat overhangs. Walls >= 1.2 mm (3 lines).
"""}
_MODEL = {"pipeline": "renders, checks, exports (STEP, STL, 3MF, OBJ, GLB), revisions, optimizer, animation, release.",
          "rules_5_6": """\
  5. Model each part in the coordinates it is used in (base on z = 0 where it has one). Put multiple parts side
     by side with a gap and set solids = N, or declare an assembly() so they are shown in place.
  6. Design for how it will be made when the person says (CNC, moulding, casting, sheet metal: the checks name the
     smallest feature that process holds). Otherwise favour proportion and finish: real fillets and chamfers,
     consistent wall thickness, no knife edges.
"""}


def guide(purpose: str | None = "model") -> str:
    """The guide for a design made for `purpose`: "print" adds bed orientation, overhang and nozzle-wall rules.
    The stored contract (cad-core/references/contract.md) is the model variant; a print swaps its two
    purpose-dependent passages."""
    text = _g.topic_text("core")
    if purpose != "print":
        return text
    for k in ("pipeline", "rules_5_6"):
        assert text.count(_MODEL[k]) == 1, k
        text = text.replace(_MODEL[k], _PRINT[k])
    return text


GUIDE = guide("model")
EXAMPLE = _g.example("recipe")
FEATURE_EXAMPLE = _g.example("features")
SURFACING = _g.topic_text("surfacing")
MECHANISMS = _g.topic_text("mechanisms")
ORGANIC = _g.topic_text("organic")
TEXTURE = _g.topic_text("texture")
AESTHETICS = _g.topic_text("aesthetics")
DFM = _g.topic_text("dfm")
REFERENCE_PARTS = _g.topic_text("reference_parts")
HYBRID = _g.topic_text("hybrid")
GAME = _g.topic_text("game")
STRENGTH = _g.topic_text("strength")

TOPICS = {"core": None, "surfacing": SURFACING, "mechanisms": MECHANISMS, "organic": ORGANIC, "texture": TEXTURE,
          "aesthetics": AESTHETICS, "dfm": DFM, "reference_parts": REFERENCE_PARTS, "hybrid": HYBRID, "game": GAME,
          "strength": STRENGTH}


def game_available() -> bool:
    """Is the game-asset pipeline (form/game) in this build?"""
    return _g.game_available()


def skill_ref(name: str) -> dict:
    """Where a topic lives as an MCP skill: {"skill": "skill://<skill>/SKILL.md", "skill_file": "skill://<skill>/<file>"}."""
    skill, rel = _g.topic_skill(name)
    return {"skill": f"skill://{skill}/SKILL.md", "skill_file": f"skill://{skill}/{rel}"}


def topic(name: str = "core", purpose: str | None = None) -> dict:
    """The guide for one topic. core is the contract, the rules and an example that builds; dfm applies only to
    designs for printing. Each result names the skill that carries the same text (skill, skill_file)."""
    name = (name or "core").strip().lower()
    if name not in TOPICS:
        raise KeyError(name)
    return {**_topic(name, purpose), **skill_ref(name)}


def _topic(name: str, purpose: str | None) -> dict:
    if name == "core":
        return {"topic": "core", "guide": guide(purpose), "purpose": purpose, "example_source": EXAMPLE,
                "example_source_features": FEATURE_EXAMPLE, "retries_per_feature": 2, "topics": list(TOPICS)}
    if name == "dfm" and purpose == "model":
        return {"topic": "dfm", "guide": "Not applicable: this design is a 3D model, not for printing. Design for its "
                "process (CNC, moulding, rendering) instead; print rules would only constrain it.", "topics": list(TOPICS)}
    if name == "game":
        ok = game_available()
        return {"topic": "game", "guide": GAME, "available": ok, "topics": list(TOPICS),
                **({} if ok else {"status": "The game-asset pipeline is not in this build yet: this is the plan it "
                                            "follows. Design the object as a 3D model and export GLB meanwhile."})}
    return {"topic": name, "guide": TOPICS[name], "topics": list(TOPICS)}
