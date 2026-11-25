"""Re-export every saved revision whose export was not a closed mesh, on a copy of a data folder.

    .venv/bin/python scripts/export_corpus.py [--data ~/FORM] [--work DIR] [--json OUT]

The data folder is only read: the projects (trashed ones too), their design sources and imported parts are copied to
--work (a new temporary folder by default) and the exports are made there with the current kernel. A revision is in
the corpus when its saved STL fails the topology screen (open boundary, non-manifold, flipped, duplicate or degenerate
faces: form/mesh_audit.py), when its saved checks say the STL does not match the CAD solid, or when its export failed.
Each one is exported again and reported: closed or not, the export ladder's rung, the stated deviation from the CAD
surface, and for the ones that stay open, the cause.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# an export is closed when none of these is found (a solid with an internal void has an inward shell of negative
# volume: the audit flags it as nonpositive_component_volume, which is reported, not counted as open)
TOPOLOGY = {"degenerate_faces", "duplicate_faces", "open_boundary", "nonmanifold_edges", "inconsistent_winding"}
FOUND = TOPOLOGY | {"nonpositive_component_volume"}


def _project_dirs(data: Path) -> dict:
    """{project id: folder} for live and trashed projects (the newest trashed copy of an id wins over older ones)."""
    out = {}
    for f in sorted(glob.glob(str(data / ".trash" / "*" / "project.json"))) + sorted(glob.glob(str(data / "*" / "project.json"))):
        try:
            pid = json.loads(Path(f).read_text(encoding="utf-8"))["id"]
        except (OSError, ValueError, KeyError):
            continue
        out[pid] = Path(f).parent
    return out


def corpus(data: Path) -> list[dict]:
    """[{project, folder, rev, why, stl}] — the saved revisions whose export was not closed or did not match."""
    from form import mesh_audit
    rows, seen = [], set()
    for pid, d in _project_dirs(data).items():
        ex = d / "artifacts" / "exports"
        for meta in sorted(ex.glob("*/meta.json")):
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                stl = meta.parent / m["files"]["stl"]["name"]
                a = mesh_audit.audit(mesh_audit.read_stl(stl)[0], bed=(1e5, 1e5, 1e5), margin=0)
            except (OSError, ValueError, KeyError):
                continue
            bad = sorted(set(a["failures"]) & FOUND)
            if bad and (pid, m["rev"]) not in seen:
                seen.add((pid, m["rev"]))
                rows.append({"project": pid, "folder": str(d), "rev": m["rev"], "why": bad, "stl": str(stl)})
        for chk in sorted((d / "artifacts" / "checks").glob("*.json")):
            try:
                c = json.loads(chk.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            conv = next((x for x in c.get("checks", []) if x.get("id") == "conversion"), None)
            if conv and conv.get("status") == "FAIL" and (pid, c.get("rev")) not in seen:
                seen.add((pid, c.get("rev")))
                rows.append({"project": pid, "folder": str(d), "rev": c.get("rev"), "why": ["conversion " + conv["value"]],
                             "stl": None})
        for failed in sorted(ex.glob("*.failed.json")):
            tmp = failed.with_name(failed.name.replace(".failed.json", ".tmp"))
            revs = [int(s.stem.rsplit("_r", 1)[-1]) for s in tmp.glob("*.stl") if s.stem.rsplit("_r", 1)[-1].isdigit()]
            for n in revs:
                if (pid, n) not in seen:
                    seen.add((pid, n))
                    why = json.loads(failed.read_text(encoding="utf-8")).get("kind", "failed")
                    rows.append({"project": pid, "folder": str(d), "rev": n, "why": ["export " + why], "stl": None})
    return rows


def copy_data(data: Path, work: Path, pids: set, folders: dict) -> None:
    """The projects, design sources and imported parts the corpus needs, without their artifacts."""
    work.mkdir(parents=True, exist_ok=True)
    for name in (".sources", ".references"):
        if (data / name).is_dir():
            shutil.copytree(data / name, work / name, dirs_exist_ok=True)
    for pid in pids:
        src, dst = Path(folders[pid]), work / pid
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("artifacts", "*.bak"), dirs_exist_ok=True)


def measure(stl: Path, cad_volume: float | None) -> dict:
    from form import mesh_audit
    a = mesh_audit.audit(mesh_audit.read_stl(stl)[0], bed=(1e5, 1e5, 1e5), margin=0, expected_components=1)
    vol = float(sum(a.get("signed_component_volumes_mm3") or [0]))
    return {"closed": not (set(a["failures"]) & TOPOLOGY), "failures": a["failures"], "components": a.get("components"),
            "boundary_edges": a.get("boundary_edges"), "volume_mm3": vol,
            "volume_delta": (abs(vol - cad_volume) / cad_volume) if cad_volume else None}


def c_note(r) -> str:
    """What a closed export still shows in the audit, and why: a mesh texture, internal voids."""
    c = r.get("export", {}).get("closure", {})
    if c.get("rung") == "texture":
        return f"mesh texture: volume {100 * (r.get('volume_delta') or 0):.1f}% above the smooth CAD by design"
    voids = [v for x in c.get("per_solid", []) for v in x.get("voids_mm3", [])]
    if voids:
        return f"closed with {len(voids)} internal void(s) of {', '.join(f'{v:g}' for v in voids)} mm³ (the audit counts each as a shell)"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default="~/FORM")
    ap.add_argument("--work", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--only", default="", help="comma-separated project ids")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args(argv)
    data = Path(a.data).expanduser().resolve()
    rows = corpus(data)
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["project"] in keep]
    work = Path(a.work).expanduser() if a.work else Path(tempfile.mkdtemp(prefix="form-export-corpus-"))
    copy_data(data, work, {r["project"] for r in rows}, {r["project"]: r["folder"] for r in rows})
    os.environ["FORM_DATA"] = str(work)
    from form import config
    from form.studio import Studio, STL_TOL
    st = Studio(config.load())
    out = []
    try:
        for r in rows:
            res = {k: r[k] for k in ("project", "rev", "why")}
            t0 = time.time()
            try:
                p = st.load(r["project"])
                rev = st.rev(p, r["rev"])
                keys = st.keys(p, r["rev"])
                d = work / "_out" / f"{r['project']}_r{r['rev']:02d}"
                e = st._k("export", key=keys["geometry"], recipe_id=st.rid(p, r["rev"]), values=rev["values"],
                          out_dir=str(d), name=f"{r['project']}_r{r['rev']:02d}", orientation=p["orientation"],
                          tol=STL_TOL, p=p, rev=r["rev"], timeout=a.timeout)
                res.update(measure(Path(e["stl"]), e.get("brep_volume_mm3")))
                res["export"] = {k: v for k, v in e.items() if k in ("stl_tolerance_mm", "closure", "brep_volume_mm3")}
            except Exception as ex:                    # noqa: BLE001 - every revision is reported, failures included
                res.update({"closed": False, "error": f"{type(ex).__name__}: {ex}"[:400]})
            res["seconds"] = round(time.time() - t0, 1)
            out.append(res)
            c = res.get("export", {}).get("closure", {})
            print(f"{r['project']} r{r['rev']:02d}: {'closed' if res.get('closed') else 'OPEN'}"
                  f" rung={c.get('rung')} dev={c.get('deviation_mm')} dV={res.get('volume_delta')} "
                  f"{res.get('error', '') or ','.join(res.get('failures', []))} ({res['seconds']} s)", flush=True)
    finally:
        st.kernel.stop()
    def dev(r):
        d = r.get("export", {}).get("closure", {}).get("deviation_mm")
        return float("inf") if d is None else d

    ok = [r for r in out if r.get("closed") and dev(r) <= 0.02]
    print(f"\n{len(ok)}/{len(out)} closed within 0.02 mm")
    for r in out:                              # the rest, each with its cause
        if r in ok:
            continue
        c = r.get("export", {}).get("closure", {})
        if r.get("error"):
            why = r["error"]
        elif r.get("closed"):
            worst = max(c.get("per_solid", []), key=lambda x: x.get("deviation_mm", 0), default={})
            why = (f"closed, but up to {dev(r):g} mm from the CAD ({c.get('rung')}"
                   + (f": {worst.get('holes_filled')} holes filled, largest {worst.get('largest_hole_mm')} mm, fill measured "
                      f"{worst.get('fill_measured_mm')} mm from the surface" if worst.get("holes_filled") else "") + ")")
        else:
            why = c.get("why") or ", ".join(r.get("failures", []))
        print(f"  {r['project']} r{r['rev']:02d}: {why}")
    notes = [r for r in ok if c_note(r)]
    for r in notes:
        print(f"  note {r['project']} r{r['rev']:02d}: {c_note(r)}")
    if a.json:
        Path(a.json).write_text(json.dumps({"corpus": rows, "results": out}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
