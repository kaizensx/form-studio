"""Photograph designs for the website and the README with the app's own Blender scene.

    .venv/bin/python scripts/media/showcase/product_shots.py [shots.json] [name ...]

Each shot in the list names an exemplar (form/exemplars/<name>.py) or a design file, is built as a project in a
scratch data folder and rendered with the scene script, presets and finishes of render_photo
(form/adapters/blender.py, blender_scene.py). The one difference from render_photo: a design with several parts is
placed by its own assembly() (assembled or exploded) instead of lying in the print layout. Materials come from the
design's appearance(); a shot's "mats" ({part or feature: [finish, colour]}) or "finish"/"color" fill in where a
design declares none. A shot with "pid" (and "rev") photographs an existing project of the data folder.

Scratch goes to .dev/showcase (SHOWCASE_WORK), projects to its data/ (SHOWCASE_DATA); renders to its out/.
Needs Blender. An illustration with invented light, not a photo of a made part.
"""
import base64, json, os, struct, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
S = Path(os.environ.get("SHOWCASE_WORK") or ROOT / ".dev" / "showcase")      # scratch: projects, zones, renders
S.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["FORM_DATA"] = os.environ.get("SHOWCASE_DATA") or str(S / "data")
os.environ["FORM_CONFIG"] = "/nonexistent"
from form import config, exemplars, appearance
from form import render as rendering
from form.adapters import blender as bl
from form.studio import Studio


def arr(b64, dt, cols):
    return np.frombuffer(base64.b64decode(b64), dtype=dt).reshape(-1, cols)


def write_stl(path, P, T):
    tri = P[T].astype("<f4")
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-20
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as f:
        f.write(b"Form Studio".ljust(80, b"\0") + struct.pack("<I", len(T)))
        f.write(rec.tobytes())


def main():
    spec = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("shots.json")).read_text())
    only = set(sys.argv[2:])
    cfg = config.load()
    app = bl.resolve(cfg)["app"]
    (S / "out").mkdir(exist_ok=True)
    idx_f = S / "projects.json"
    idx = json.loads(idx_f.read_text()) if idx_f.exists() else {}
    st = Studio(cfg)
    try:
        for shot in spec["shots"]:
            name = shot["name"]
            if only and shot.get("as", name) not in only:
                continue
            key = name + json.dumps(shot.get("values") or {}, sort_keys=True)
            try:
                if shot.get("pid"):
                    idx[key] = shot["pid"]
                if key not in idx and not shot.get("pid"):
                    p = st.create_design(name.replace("_", " "), Path(shot["file"]).read_text() if shot.get("file") else exemplars.get(name)["source"], purpose="model", values=shot.get("values"))
                    idx[key] = p["id"]
                    idx_f.write_text(json.dumps(idx, indent=1))
                p = st.load(idx[key])
                rev = shot.get("rev")
                view = st.view(p, n=rev, tol=shot.get("tol", 0.02), timeout=600)
                r = st.recipe(p, rev)
                try:
                    zones = appearance.declared(r, r.validate(st.rev(p, rev)["values"]))
                except Exception:
                    zones = []
                if shot.get("info"):
                    a = view.get("assembly") or {}
                    print("INFO", name, "parts", [(x["id"], x.get("explode_total")) for x in a.get("parts", [])],
                          "features", sorted({m["feature"] for m in view["mesh"]}), "zones", zones, flush=True)
                for v in shot.get("views", [{}]):
                    t = time.time()
                    pose = v.get("pose", "assembled")
                    vd = view
                    if pose in ("assembled", "exploded") and (view.get("assembly") or {}).get("parts"):
                        if pose == "exploded" and v.get("explode", 1.0) != 1.0:
                            a = json.loads(json.dumps(view["assembly"]))
                            for part in a["parts"]:
                                part["explode_total"] = [c * v["explode"] for c in part["explode_total"]]
                            vd = rendering.posed({**view, "assembly": a}, pose)
                        else:
                            vd = rendering.posed(view, pose)
                    mats = v.get("mats") or shot.get("mats") or {}
                    groups = {}
                    for m in vd["mesh"]:
                        z = next((z for z in zones if m["feature"] in z["features"]), None)
                        fin, col = (z["finish"], z["color"]) if z else (None, None)
                        for k in (m.get("part"), m["feature"]):
                            if k in mats:
                                fin, col = mats[k]
                        if m["feature"] in (v.get("hide") or []) or m.get("part") in (v.get("hide") or []):
                            continue
                        groups.setdefault((fin, col), []).append(m)
                    d = S / "zones" / f"{shot.get('as', name)}-{v.get('tag', 'a')}"
                    d.mkdir(parents=True, exist_ok=True)
                    zf = []
                    for i, ((fin, col), ms) in enumerate(groups.items()):
                        Ps, Ts, off = [], [], 0
                        for m in ms:
                            P = arr(m["positions"], np.float32, 3)
                            Ps.append(P); Ts.append(arr(m["indices"], np.uint32, 3) + off); off += len(P)
                        f = d / f"z{i}.stl"
                        write_stl(f, np.concatenate(Ps), np.concatenate(Ts))
                        zf.append({"stl": str(f), "finish": fin, "color": col})
                    out = S / "out" / f"{shot.get('as', name)}-{v.get('tag', 'a')}.png"
                    cam = bl.photo_view(v.get("view"), v.get("az"), v.get("el"))
                    job = bl.build_job(Path(zf[0]["stl"]), out, v.get("preset", "dark"), v.get("finish", "matte"),
                                       v.get("color", "#d9d6cf"), None, False, samples=v.get("samples") or spec.get("samples", 24),
                                       size=tuple(v.get("size") or spec.get("size", (800, 600))), view=cam, zones=zf)
                    rep = bl.run_job(app, job, d / "job.json", timeout=1500)
                    print("OK", name, v.get("tag"), rep.get("engine"), rep.get("device"), round(time.time() - t), "s", out, flush=True)
            except Exception as e:
                import traceback
                print("FAIL", name, type(e).__name__, str(e)[:500], traceback.format_exc()[-600:], flush=True)
    finally:
        st.kernel.stop()


if __name__ == "__main__":
    main()
