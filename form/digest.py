"""Compact, agent-friendly views of engine state. Shared by the MCP server and the JSON CLI."""
from __future__ import annotations

from typing import Any

from .studio import NODES


def _fmt(v: float) -> str:
    return f"{v:g}"


def digest(st, pid: str, bench: str | None = None) -> dict:
    s = st.state(pid)
    p = s["project"]
    recipe = st.recipe(p)
    head = st.rev(p)
    params = {}
    for k, v in head["values"].items():
        sp = recipe.spec(k)
        src = head["provenance"].get(k, {}).get("source", "assumed")
        params[k] = f"{_fmt(v)} {sp.unit} ({src})"
    out: dict[str, Any] = {
        "project": p["id"], "name": p["name"], "head": head["n"],
        "recipe": p["recipe"] if not p["recipe"].startswith(("src:", "scad:")) else
                  ("design written in OpenSCAD" if p["recipe"].startswith("scad:") else "design written as code"),
        "brief": p["brief"]["text"],
        "parameters": params,
        "outputs": {n: s["status"][n]["state"] + (f" (last made for r{s['status'][n]['last_rev']})" if s["status"][n].get("last_rev") else "")
                    for n in NODES},
        "release_gate": {"ready": s["gate"]["ready"], "blocking": s["gate"]["reasons"],
                         "warnings_to_acknowledge": [f"{w['label']}: {w['value']}" for w in s["gate"]["warnings"]],
                         "evidence": s["gate"]["evidence_level"].replace(" · ", "; ")},
        "approval": s["approval"],
        "orientation": p["orientation"],
    }
    if getattr(recipe, "mesh", False):
        out["mesh_design"] = recipe.public().get("notes", [])
    parts = [r for r in p["brief"].get("references", []) if r.get("kind") == "part"]
    if parts:
        out["reference_parts"] = [f"{r['file']}: " + " × ".join(f"{b - a:.1f}" for a, b in zip(*r["bbox"])) + " mm (computed); "
                                  f"use self.reference({r['file']!r}) in a Python design" for r in parts]
    if s["status"]["slice"].get("unavailable"):
        out["slicer_unavailable"] = s["status"]["slice"]["unavailable"]
    if s["checks"]:
        out["checks"] = [f"{c['status']}  {c['label']}: {c['value']}  [{c['evidence']}]" for c in s["checks"]["checks"]]
    if s["fit"]:
        f = s["fit"]
        out["fit_model"] = {
            "interface": f["label"], "expected_gap_mm": round(f["expected_gap"], 3), "window_mm": f["window"],
            "modelled_yield": f"{f['yield'] * 100:.0f}%", "p_too_tight": f"{f['p_tight'] * 100:.0f}%",
            "p_too_loose": f"{f['p_loose'] * 100:.0f}%",
            "uncertainty_from": {k: f"{v['source']} ±{v['sigma']:.2f} mm ({v['share'] * 100:.0f}% of variance)"
                                 for k, v in f["sources"].items()},
            "note": "Statistical model, not a measurement.",
        }
    if s["actions"]:
        out["next_best_actions"] = [{"do": a["title"], "why": a["why"], "cost": a["cost"],
                                     "yield_after": f"{a['after'] * 100:.0f}%", **({"change": a["change"]} if a.get("change") else {})}
                                    for a in s["actions"][:4]]
    if s["slice"]:
        sl = s["slice"]
        out["slice_simulated"] = {"time_min": round(sl["time_s"] / 60) if sl.get("time_s") is not None else None, "filament_g": sl["filament_g"], "layers": sl["layers"],
                                  "supports": sl.get("support_used"), "slicer": f"{sl.get('slicer_version')}",
                                  "presets": " / ".join(v["name"] for v in sl["presets"].values())}
    files = {}
    if s["exports"]:
        d = st.apath(p, "exports", s["status"]["exports"]["key"])
        for kind, f in s["exports"]["files"].items():
            files[kind] = str(d / f["name"])
    if s["slice"]:
        d = st.apath(p, "slice", s["status"]["slice"]["key"])
        files["gcode"] = str(d / s["slice"]["gcode"])
        if s["slice"].get("threemf"):
            files["3mf"] = str(d / s["slice"]["threemf"])
    if files:
        out["files"] = files
    out["recent_revisions"] = [f"r{r['n']:02d} [{r.get('origin', 'user')}] {r['note']}" for r in p["revisions"][-5:]]
    if s["releases"]:
        out["releases"] = s["releases"]
    if s.get("recovered"):
        out["recovered"] = s["recovered"]
    if bench:
        out["bench"] = f"{bench}/#p={pid}"
    return out


def impact_digest(imp: dict) -> dict:
    return {
        "changes": [f"{c['label']}: {_fmt(c['from'])} -> {_fmt(c['to'])} {c['unit']}" for c in imp["params"]],
        "features": [f"{f['label']} ({f['role']}): {f['change']}" for f in imp["features"]],
        "interfaces_touched": imp["interfaces_touched"],
        "derived": [f"{d['label']}: {_fmt(round(d['from'], 3))} -> {_fmt(round(d['to'], 3))} {d['unit']}" for d in imp["derived"]],
        "metrics": [f"{m['label']}: {m['from']:.2f} -> {m['to']:.2f} {m['unit']}" for m in imp["metrics"]],
        "would_invalidate": imp["invalidates"],
        "revokes_current_approval": imp["revokes_approval"],
    }


def job_digest(job: dict) -> dict:
    out = {"job": job.get("id"), "state": job["state"],
           "steps": [f"{s['label']}: {s['state']}" + (f" ({s['seconds']} s)" if s.get("seconds") is not None else "")
                     + (f" - {s['error']['message']}" if s.get("error") else "")
                     + (f" [{s['progress'].get('label')}" + (f" at {s['progress']['value']}" if s['progress'].get('value') is not None else "")
                        + f", {s['progress'].get('seconds')} s]" if s.get("progress") and s["state"] == "running" else "")
                     for s in job.get("steps", [])]}
    if job.get("error"):
        out["error"] = job["error"]
    return out
