"""The topology optimisation's entry point. Runs in the FEA engine's Python, out of the app:

    <engine python> -m form.topo.run <job folder>

The job folder holds job.json: {"step": the solid, "spec": the strength study as the engine reads it
(form/fea/core.py), "topology": the settings (form/topo/study.py SETTINGS)}. While it runs, one JSON object per line
goes to standard output ({"progress", "fraction", "iteration", "compliance", ...}) and `live.json` holds the newest
density picture, so a window can show the layout forming. At the end:

    result.json   the record: settings as used, mesh, every iteration's compliance and volume, the density result's
                  own numbers, the layout (pockets with outlines, ribs with widths) and the mesh body's file
    frames.json   the density field of every iteration, from the even start (iteration 0): the picture across the
                  pull direction and the density at the vertices of the part's surface (what direction I plays back)
    body.stl      the smoothed surface of the dense region: the mesh-body way out, always written

A file named `cancel` stops the run at the next iteration; nothing is written for a cancelled run.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import numpy as np


def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def _u8(a) -> str:
    return _b64(np.clip(np.round(np.asarray(a, float) * 255), 0, 255).astype(np.uint8))


def write_stl(path: Path, V: np.ndarray, F: np.ndarray) -> None:
    tri = V[F].astype("<f4")
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-30)[:, None]
    rec = np.zeros(len(F), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as f:
        f.write(b"Form Studio topology optimisation: smoothed density surface".ljust(80, b" "))
        f.write(np.uint32(len(F)).tobytes())
        f.write(rec.tobytes())


def mesh_volume(V: np.ndarray, F: np.ndarray) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def solve(job: dict, d: Path, progress, cancelled) -> dict:
    from ..fea import mesh as mesh_mod
    from ..fea import solve as S
    from . import mesh3d, recon, simp
    o = job["topology"]
    spec = job["spec"]
    t0 = time.perf_counter()
    progress("Reading the solid", 0.0)
    geo = mesh_mod.load(job["step"])
    if geo.solids != 1:
        raise mesh3d.TopologyError("Topology optimisation works on one solid; this design has several.",
                                   "Optimise each part as its own design.")
    pull = o.get("pull")
    mode = o.get("mode", "pockets")
    if mode == "pockets" and pull is None:
        raise mesh3d.TopologyError("Pockets need a pull direction.")
    h = float(o.get("h") or 0) or geo.diag / 40.0
    progress(f"Meshing at {h:.3g} mm", 0.02)
    elements_max = int(o.get("elements_max", 60000))
    for _ in range(5):
        prob = mesh3d.TetProblem(geo, spec, h, pull=pull if mode == "pockets" else None, cancelled=cancelled)
        if prob.n <= elements_max:
            break
        h *= (prob.n / elements_max) ** (1 / 3) * 1.05   # coarser, to stay inside the stated size
    rmin = float(o.get("rmin") or 0) or 2.0 * h
    rmin = max(rmin, 1.05 * h) if mode == "pockets" else max(rmin, 1.2 * h)
    prob.check_filter(rmin)
    keep_mm = float(o["keep"]) if o.get("keep") is not None else rmin
    # a rim keeps every pocket inside the silhouette; half the smallest member is enough for that, and a wider one
    # takes material the layout needs for its diagonals (measured: a rim of rmin on a slender plate leaves a frame)
    rim_mm = float(o["rim"]) if o.get("rim") is not None else (max(0.5 * rmin, h) if mode == "pockets" else 0.0)
    solid = prob.keep(keep_mm, rim_mm if mode == "pockets" else 0.0)
    md, sp = prob.model, prob.model.sp
    vtot = float(prob.vol.sum())
    volfrac = float(o["volfrac"])
    sam = mesh3d.Sampler(prob, pull if pull is not None else [0, 0, 1])
    surf = prob.surface()
    frames, surf_frames = [], []
    max_iter = int(o.get("max_iter", 80))
    budget = float(o.get("budget_s", 240.0))

    # the solid part first: what the layout is compared with
    progress(f"Solving the solid part: {sp.ndof:,} unknowns", 0.05)
    c_full, _ce = prob.solve(np.ones(prob.n))
    u_full = prob.u.copy()

    def on_iter(rec, xp):
        img = sam.image(xp)
        frames.append({**{k: rec[k] for k in ("iteration", "compliance", "volume", "change", "seconds")}, "image": _u8(img)})
        surf_frames.append(_u8(surf["to_vertices"] @ xp))
        if rec["iteration"] == 0:                        # the even start: a frame to play from, nothing to report yet
            return
        live = {"iteration": rec["iteration"], "max_iter": max_iter, "compliance": rec["compliance"],
                "volume": rec["volume"], "grid": sam.grid(), "image": frames[-1]["image"]}
        tmp = d / "live.json.tmp"
        tmp.write_text(json.dumps(live), encoding="utf-8")
        tmp.replace(d / "live.json")
        progress(f"Iteration {rec['iteration']}: compliance {rec['compliance']:.4g} N mm, change {rec['change']:.2f}",
                 0.08 + 0.8 * min(1.0, max(rec["iteration"] / max_iter, rec["seconds"] / budget)),
                 iteration=rec["iteration"], compliance=rec["compliance"], volume=rec["volume"])
    out = simp.optimise(prob, volfrac, rmin, penal=float(o.get("penal", 3.0)), ft=o.get("filter", "density"),
                        max_iter=max_iter, tol=float(o.get("tol", 0.02)), solid=solid, on_iter=on_iter,
                        cancelled=cancelled, emin=mesh3d.EMIN_3D, budget_s=budget)
    if out["stopped"] == "cancelled":
        raise mesh3d.TopologyError("Cancelled.", kind="cancelled")
    xp = out["density"]
    progress("Reading the layout", 0.9)

    # the density result's own numbers, on its own mesh: the dense elements at full stiffness, the rest nearly empty
    t_img = recon.threshold_for(xp, np.ones(prob.n, bool), volfrac, prob.vol)
    dense = (xp > t_img) | solid
    E_bw = np.where(dense, 1.0, mesh3d.EMIN_3D)
    c_bw, _ = prob.solve(E_bw)
    u_bw = prob.u.copy()
    sq = sp.element_stress_q(u_bw, md.lam, md.mu)                # the solid material's stress for these strains
    s6 = np.stack([sq[..., 0, 0], sq[..., 1, 1], sq[..., 2, 2], sq[..., 0, 1], sq[..., 1, 2], sq[..., 0, 2]], axis=-1)
    vm_q = S.von_mises(s6)                                       # at the quadrature points
    vm_el = (vm_q * sp.dx).sum(axis=1) / sp.vol                  # element mean
    judged = dense & ~solid                                      # not at the supports and loads, where stress is singular
    raw = {"volume_fraction": round(float(prob.vol[dense].sum() / vtot), 4),
           "volume_mm3": round(float(prob.vol[dense].sum()), 2),
           "compliance_N_mm": round(float(c_bw), 6), "compliance_grey_N_mm": round(float(out["compliance"]), 6),
           "compliance_solid_part_N_mm": round(float(c_full), 6),
           "max_displacement_mm": round(float(np.linalg.norm(u_bw.reshape(-1, 3), axis=1)[np.unique(sp.edofs[:, dense])].max()), 6),
           "max_displacement_solid_part_mm": round(float(np.linalg.norm(u_full.reshape(-1, 3), axis=1).max()), 6),
           "threshold": round(float(t_img), 4),
           "how": "the optimisation's own mesh, elements denser than the threshold at full stiffness and the rest "
                  "nearly empty; one mesh, a jagged boundary, no refinement: indicative, not a strength study"}
    if judged.any():
        vm = vm_el[judged]
        # the peak is read at the quadrature points: the mean over an element of this size hides the rise of stress
        # at a member's edge (measured: half the peak the study of the rebuilt part finds)
        raw["peak_von_mises_MPa"] = round(float(vm_q[judged].max()), 4)
        raw["peak_von_mises_element_mean_MPa"] = round(float(vm.max()), 4)
        raw["von_mises_p99_MPa"] = round(float(np.percentile(vm, 99)), 4)
        raw["stress_left_out"] = f"elements within {keep_mm:.3g} mm of the faces that carry supports and loads"
        if md.has_yield:
            y = float(np.nanmin(md.yld))
            raw["safety_factor"] = round(y / max(float(vm_q[judged].max()), 1e-300), 4)
            raw["safety_factor_element_mean"] = round(y / max(float(vm.max()), 1e-300), 4)
    rho = float(md.rho.mean()) * 1e12 if np.any(md.rho > 0) else None        # kg/m3
    if rho:
        raw["mass_g"] = round(raw["volume_mm3"] * rho * 1e-6, 4)

    # the mesh body: always written, so there is a way out when the features do not fit
    nodal = np.zeros(len(prob.m.P))
    wsum = np.zeros(len(prob.m.P))
    for k in range(4):
        np.add.at(nodal, prob.m.T[:, k], xp * prob.vol)
        np.add.at(wsum, prob.m.T[:, k], prob.vol)
    nodal /= np.maximum(wsum, 1e-300)
    # the level at which the elements above it hold the volume asked for (the body's own volume is then measured)
    level = recon.threshold_for(nodal[prob.m.T].mean(axis=1), np.ones(prob.n, bool), volfrac, prob.vol)
    Vb, Fb = recon.iso_mesh(prob.m.P, prob.m.T, prob.m.S[md.surf["outside"]], nodal, level, smooth=int(o.get("smooth", 8)))
    body = None
    if len(Fb):
        write_stl(d / "body.stl", Vb, Fb)
        body = {"file": "body.stl", "triangles": int(len(Fb)), "volume_mm3": round(mesh_volume(Vb, Fb), 2),
                "volume_fraction": round(mesh_volume(Vb, Fb) / vtot, 4), "level": round(float(level), 4),
                "label": "mesh body (not editable CAD): the smoothed surface of the dense region of the density field",
                "smoothing": f"Taubin, {int(o.get('smooth', 8))} passes; vertices on the part's own surface stay there"}
        if rho:
            body["mass_g"] = round(body["volume_mm3"] * rho * 1e-6, 4)

    layout = None
    if mode == "pockets":
        img = sam.image(xp)
        keep_px = sam.any(prob.keep(keep_mm, 0.0))       # the rim is kept by rim_px, on the picture itself
        min_pocket = float(o.get("min_pocket") or 0) or 1.5 * rmin
        layout = recon.pockets(img, sam.inside, keep_px, sam.grid(), volfrac, min_pocket, sam.thickness,
                               rim_px=int(round(rim_mm / sam.px)), tol_mm=float(o.get("outline_tol") or 0.2 * rmin))
        layout["grid"] = sam.grid()
        layout["thickness_mm"] = {"min": round(float(sam.thickness[sam.inside].min()), 3),
                                  "max": round(float(sam.thickness[sam.inside].max()), 3)}
    grid = sam.grid()
    fr = {"grid": grid, "inside": _b64(sam.inside.astype(np.uint8)), "encoding": "u1 per pixel, row by row, 255 = solid",
          "frames": frames,
          "surface": {"positions": _b64(surf["positions"]), "indices": _b64(surf["indices"]),
                      "vertices": int(len(surf["positions"])), "triangles": int(len(surf["indices"])),
                      "encoding": "positions f4 xyz, indices u4, frames u1 per vertex (255 = solid)",
                      "frames": surf_frames}}
    result = {
        "kind": "topology", "mode": mode, "seconds": round(time.perf_counter() - t0, 2),
        "settings": {"volfrac": volfrac, "h_mm": round(h, 4), "rmin_mm": round(rmin, 4), "penal": float(o.get("penal", 3.0)),
                     "filter": o.get("filter", "density"), "update": "optimality criteria, move limit 0.2",
                     "pull": [float(x) for x in prob.pull] if prob.pull is not None else None,
                     "keep_mm": round(keep_mm, 4), "rim_mm": round(rim_mm, 4), "max_iter": max_iter, "budget_s": budget,
                     "void_stiffness": mesh3d.EMIN_3D},
        "mesh": {"tets": int(prob.n), "unknowns": int(sp.ndof), "h_mm": round(h, 4), "element": "quadratic tetrahedra",
                 "solver": prob.method, "solves": int(prob.solves)},
        "resolution": f"{prob.n:,} elements of about {h:.3g} mm; members thinner than {rmin:.3g} mm are not resolved",
        "iterations": out["iterations"], "converged": out["converged"], "stopped": out["stopped"],
        "optimise_seconds": out["seconds"],
        "history": out["history"], "grey": round(out["grey"], 4),
        "non_design_fraction": round(float(prob.vol[solid].sum() / vtot), 4),
        "volume_mm3": round(vtot, 2), "density_kg_m3": rho,
        "mass_solid_part_g": round(vtot * rho * 1e-6, 4) if rho else None,
        "density_result": raw, "layout": layout, "body": body,
        "method": "SIMP, minimum compliance at a volume fraction: density filter (Bruns and Tortorelli 2001), penalty 3, "
                  "optimality criteria update (Bendsøe and Sigmund 2003; Andreassen et al. 2011)",
        "assumptions": ["one load case: the strength study's loads and supports",
                        "stiffness is optimised, not stress: the safety factor is checked afterwards, on the rebuilt part",
                        "linear elastic, isotropic material; one fixed mesh during the optimisation"],
    }
    return result, fr


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        sys.exit("usage: python -m form.topo.run <job folder>")
    d = Path(argv[0])
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    t0 = time.perf_counter()

    def progress(text, fraction=None, **more):
        print(json.dumps({"progress": text, "fraction": fraction, "seconds": round(time.perf_counter() - t0, 1), **more}),
              flush=True)

    def cancelled():
        return (d / "cancel").exists()

    def write(name, data):
        tmp = d / (name + ".tmp")
        tmp.write_text(json.dumps(data, default=float), encoding="utf-8")
        tmp.replace(d / name)
    try:
        result, frames = solve(job, d, progress, cancelled)
        from ..fea import verify
        result["versions"] = verify.versions()
        write("frames.json", frames)
        write("result.json", result)
        return 0
    except Exception as e:                           # noqa: BLE001 - every failure is reported, none is hidden
        kind = getattr(e, "kind", None) or ("mesh" if type(e).__name__ == "MeshError" else "engine")
        if str(e) == "cancelled":
            kind = "cancelled"
        err = {"message": str(e), "hint": getattr(e, "hint", ""), "kind": kind, "type": type(e).__name__}
        if kind == "engine":
            import traceback
            err["trace"] = traceback.format_exc()[-3000:]
        write("result.json", {"error": err})
        return 2 if kind == "cancelled" else 1


if __name__ == "__main__":
    sys.exit(main())
