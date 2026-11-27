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

OPTIONS = ("radius", "length", "thickness", "standard", "size", "fit", "nominal", "d", "style", "depth", "of", "mode",
           "count", "pitch", "angle", "axis", "origin", "after", "head_d", "head_depth", "head_clearance")


def route_get(st, p: dict, rest: str, q: dict):
    from . import modelling
    if rest == "/tree":
        return modelling.tree(st, p)
    if rest == "/rollback":
        return modelling.view_upto(st, p, str(q.get("feature") or ""))
    return None


def _ran(st, pid: str, p_after: dict) -> str | None:
    return st.run(pid) if p_after.get("auto_run", True) else None


def route_post(st, p: dict, action: str, body):
    from . import modelling
    if action not in ("tree", "model"):
        return None
    body = body if isinstance(body, dict) else {}
    pid = p["id"]
    eh = body.get("expect_head")
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
        r = modelling.commit(st, p, ops, eh, "you")
        st.activity(pid, "commit", f"r{r['head']:02d}: {r['said']}", by="you")
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
    r = modelling.commit(st, p, pl["ops"], eh, "you", planned=pl)
    st.activity(pid, "commit", f"r{r['head']:02d}: {r['said']}", by="you")
    q = r.pop("project")
    return {"head": r["head"], "feature": pl["feature"], "said": r["said"], "preview": r["preview"],
            "job": _ran(st, pid, q)}
