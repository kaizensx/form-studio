"""The app's routes for modelling by hand (form/modelling.py): the feature tree, the rollback view, picked features.

    GET  /api/projects/<id>/tree                       features in build order, suppressed, what each depends on
    GET  /api/projects/<id>/rollback?feature=<fid>     the head as it stood after that feature (a view, never saved)
    POST /api/projects/<id>/tree   {ops, expect_head, preview}
                                   tree ops (suppress, restore, move, rename): previewed, then one revision
    POST /api/projects/<id>/model  {kind, picks, ...options, expect_head, preview}
                                   a picked feature (fillet, chamfer, hole, pattern, shell): preview=true builds the
                                   draft (with its mesh for the viewport) and saves nothing; otherwise one revision

The window, the MCP tools and the CLI call the same functions; a saved change starts the pipeline, so the checks are
computed again on the new solid.
"""
from __future__ import annotations

from . import modelling_more as _more

OPTIONS = ("sketch", "axis_entity", "label", "radius", "length", "thickness", "standard", "size", "fit", "nominal", "d", "style", "depth", "of", "mode",
           "count", "pitch", "angle", "axis", "origin", "after", "head_d", "head_depth", "head_clearance")
OPTIONS += tuple(k for k in _more.END_OPTIONS + _more.OPTIONS if k not in OPTIONS)   # end conditions, the more kinds


def route_global_post(st, path: str, body):
    """Routes that need no project: solve a sketch as it is drawn; start a design from one (Start blank, by hand)."""
    from . import handsketch, modelling
    body = body if isinstance(body, dict) else {}
    if path == "/api/sketch/solve":
        return handsketch.solve(body.get("sketch") or {}, body.get("values") or {}, body.get("prefix") or "")
    if path == "/api/start/sketch":
        p = modelling.start_from_sketch(st, body.get("name") or "Untitled design", body.get("sketch") or {},
                                        body.get("kind") or "extrude", body.get("purpose") or "model",
                                        **{k: body[k] for k in ("depth", "angle", "axis_entity", "label") if body.get(k) is not None})
        return {"id": p["id"], "head": p["head"], "job": st.run(p["id"])}
    return None


def route_get(st, p: dict, rest: str, q: dict):
    from . import modelling
    if rest == "/sketch":
        return modelling.get_sketch(st, p, str(q.get("feature") or ""))
    if rest == "/tree":
        return modelling.tree(st, p)
    if rest == "/rollback":
        return modelling.view_upto(st, p, str(q.get("feature") or ""))
    return None


def _said(st, body: dict, pid: str, h0: int, r: dict) -> None:
    """A hand edit, said where the work is followed: the activity log, and the open conversation (body.conversation)
    as a revision card, the same one an agent's reply gets ("You: Added Fillet 1: 2 edges, r2 mm", r04 to r05)."""
    st.activity(pid, "commit", f"r{r['head']:02d}: {r['said']}", by="you")
    cid = body.get("conversation")
    if not cid or not getattr(st, "chat", None):
        return
    try:
        st.chat.store.append(str(cid), {"t": "act", "by": "You", "text": r["said"],
                                        "change": {"project": pid, "from": h0, "to": r["head"]}})
    except Exception:                                  # noqa: BLE001 - the revision is saved; the card is a courtesy
        pass


def _ran(st, pid: str, p_after: dict) -> str | None:
    return st.run(pid) if p_after.get("auto_run", True) else None


def route_post(st, p: dict, action: str, body):
    from . import modelling
    if action not in ("tree", "model", "sketch", "sketch_plane"):
        return None
    body = body if isinstance(body, dict) else {}
    pid = p["id"]
    eh = body.get("expect_head")
    if action == "sketch_plane":
        return modelling.sketch_plane(st, p, body.get("at") or [0, 0, 0])
    if action == "sketch":                         # an existing sketch changed: whole (the editor) or by ops
        fid = str(body.get("feature") or "")
        ops, _new = modelling.sketch_edit_ops(st, p, fid, body.get("ops"), body.get("sketch"))
        if body.get("preview"):
            pv = modelling.preview(st, p, ops, view=True)
            pv.pop("rid", None)
            return pv
        h0 = p["head"]              # before the commit: the card says r04 → r05 (the commit may hand `p` back changed)
        r = modelling.commit(st, p, ops, eh, "you", note=f"Changed the sketch of {fid}")
        _said(st, body, pid, h0, r)
        q = r.pop("project")
        return {"head": r["head"], "said": r["said"], "preview": r["preview"], "job": _ran(st, pid, q)}
    if action == "tree":
        ops = body.get("ops") or []
        bad = [o for o in ops if not isinstance(o, dict) or o.get("op") not in modelling.TREE_OPS]
        if bad:
            from .studio import StudioError
            raise StudioError("Only the tree's ops go here: " + ", ".join(modelling.TREE_OPS) + ".",
                              "Other edits are code: ask your agent, or use edit_design.")
        if body.get("preview"):
            pv = modelling.preview(st, p, ops)
            pv.pop("rid", None)
            return pv
        h0 = p["head"]              # before the commit: the card says r04 → r05 (the commit may hand `p` back changed)
        r = modelling.commit(st, p, ops, eh, "you")
        _said(st, body, pid, h0, r)
        q = r.pop("project")
        return {"head": r["head"], "said": r["said"], "changed": r["changed"], "reused": len(r["reused"]),
                "preview": r["preview"], "job": _ran(st, pid, q)}
    kind = str(body.get("kind") or "")
    o = {k: body[k] for k in OPTIONS if body.get(k) is not None and body.get(k) != ""}
    pl = modelling.plan(st, p, kind, body.get("picks") or [], **o)
    if body.get("preview"):
        pv = modelling.preview(st, p, pl["ops"], view=True)
        pv.pop("rid", None)
        return {"feature": pl["feature"], "label": pl["label"], "summary": pl["summary"], "params": pl["params"],
                "picked": pl["picked"], "preview": pv}
    h0 = p["head"]              # before the commit: the card says r04 → r05 (the commit may hand `p` back changed)
    r = modelling.commit(st, p, pl["ops"], eh, "you", planned=pl)
    _said(st, body, pid, h0, r)
    q = r.pop("project")
    return {"head": r["head"], "feature": pl["feature"], "said": r["said"], "preview": r["preview"],
            "job": _ran(st, pid, q)}
