"""Mesh to editable CAD, before and after, on a synthetic part of tests/recon_fixtures.py.

    .venv/bin/python scripts/media/showcase/recon_shots.py stepped_bracket -55 28

Exports the fixture as STL, runs form/recon on it, then draws the input mesh (its triangles) and the result (the
STEP's faces and B-rep edges) with the engine's headless renderer in the website's dark colours. Prints the report's
result (dimensions, deviation) and the triangle and face counts the page quotes. Never give it a file of your own.
"""
import base64, json, os, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
S = Path(os.environ.get("SHOWCASE_WORK") or ROOT / ".dev" / "showcase")      # scratch: projects, zones, renders
S.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def main():
    name = sys.argv[1]
    az, el = float(sys.argv[2]), float(sys.argv[3])
    import recon_fixtures as fx
    from build123d import import_step
    from form import kernel, render
    from form.recon import mesh as rmesh, pipeline
    d = S / "recon" / name
    d.mkdir(parents=True, exist_ok=True)
    stl, _solid, _facts = fx.export(name, d)
    rep_f = d / f"{name}_report.json"
    if not rep_f.exists():
        t = time.time()
        rep = pipeline.reconstruct(stl, d, name=name, tolerance=0.02)
        print("reconstructed in", round(time.time() - t, 1), "s", flush=True)
    rep = json.loads(rep_f.read_text())
    print(json.dumps({k: rep.get(k) for k in ("result", "deviation", "verified")}, default=str)[:1500])
    V, F = pipeline.load(stl)[:2]
    V, F = np.asarray(V, np.float32), np.asarray(F, np.uint32)
    tri_edges = np.concatenate([V[F[:, [0, 1]]].reshape(-1, 6), V[F[:, [1, 2]]].reshape(-1, 6), V[F[:, [2, 0]]].reshape(-1, 6)])
    shape = import_step(str(d / rep["result"]["step"]))
    P, T = kernel._tessellate(shape, 0.02)
    E = kernel._edges(shape)
    render.PAPER, render.INK = (19, 23, 26), (150, 160, 157)
    render.PALETTE = [(74, 82, 80)]
    size = (1200, 900)
    lo, hi = V.min(0), V.max(0)
    a = render.render_png({"mesh": [{"positions": b64(V), "indices": b64(F), "feature": "m"}], "edges": b64(tri_edges.astype(np.float32))},
                          [{"id": "m", "label": ""}], camera=(az, el), size=size, overlay=False)
    (S / "out" / f"recon-{name}-mesh.png").write_bytes(a)
    render.INK = (185, 232, 215)
    render.PALETTE = [(216, 211, 200)]
    c = render.render_png({"mesh": [{"positions": b64(np.asarray(P, np.float32)), "indices": b64(np.asarray(T, np.uint32)), "feature": "m"}],
                           "edges": b64(np.asarray(E, np.float32))},
                          [{"id": "m", "label": ""}], camera=(az, el), size=size, overlay=False)
    (S / "out" / f"recon-{name}-cad.png").write_bytes(c)
    print("triangles", len(F), "faces", len(shape.faces()), "edges", len(E))


if __name__ == "__main__":
    main()
