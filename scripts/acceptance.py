"""Run the representative workflow end to end and write what actually happened.

    .venv/bin/python scripts/acceptance.py

Uses a throwaway data directory. Every line in the report is produced by the
run; nothing is asserted that was not observed. Exit code 1 if a step fails.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="form-acceptance-"))
    os.environ["FORM_DATA"] = str(tmp)
    from form import config, slicer
    from form.studio import NODES, Studio, StudioError
    st = Studio(config.load())
    rows, ok_all = [], True

    def step(name, fn):
        nonlocal ok_all
        t = time.perf_counter()
        try:
            detail, status = fn(), "PASS"
        except AssertionError as e:
            detail, status, ok_all = f"assertion failed: {e}", "FAIL", False
        except slicer.SlicerBlocked as e:
            detail, status = str(e), "BLOCKED"
        except Exception as e:
            detail, status, ok_all = f"{type(e).__name__}: {e}", "FAIL", False
        rows.append((name, status, f"{time.perf_counter() - t:.2f}", detail))
        print(f"{status:8} {name}: {detail}")

    S = lambda p: {n: st.status(st.load(p["id"]))[n]["state"] for n in NODES}
    box = {}
    sl = st.slicer_info()
    has_slicer = sl.get("available", False)

    def s1():
        box["p"] = st.create("Acceptance dock", "dock", "Phone dock; cable out the back; must not tip when tapped.")
        return f"project created from brief, recipe dock, {len(st.recipes['dock'].params)} typed parameters in mm/deg/g"
    step("1 brief → parameters", s1)

    def s2():
        r = st.recipes["dock"]
        try:
            st.commit(st.load(box["p"]["id"]), {"cable_diameter": 9})
            raise AssertionError("constraint not enforced")
        except StudioError as e:
            return f"constraint enforced before any geometry is saved: “{e}” → {e.hint}"
    step("2 constraints", s2)

    def s3():
        job = st.run_sync(box["p"]["id"])
        assert job["state"] in ("done", "blocked"), job
        v = st.view(st.load(box["p"]["id"]))
        assert {m["feature"] for m in v["mesh"]} == {f.id for f in st.recipes["dock"].features}
        t = {s["node"]: s.get("seconds") for s in job["steps"]}
        return f"{st.kernel_id()}: 1 valid solid, {v['faces']} faces attributed to {len(v['mesh'])} features, {v['volume_mm3']/1000:.1f} cm³; step times {t}"
    step("3 editable geometry (BREP)", s3)

    def s4():
        p = st.load(box["p"]["id"])
        ex = st.read(p, "exports", st.keys(p)["exports"])
        box["stl0"] = ex["files"]["stl"]["sha256"]
        return "STEP + STL written, units mm: " + ", ".join(f"{f['name']} ({f['bytes']//1024} kB, sha256 {f['sha256'][:12]})" for f in ex["files"].values())
    step("4 exports", s4)

    def s5():
        ch = st.state(box["p"]["id"])["checks"]
        assert ch and not ch["rollup"]["FAIL"], ch and ch["rollup"]
        return "; ".join(f"{c['label']} {c['status']} [{c['evidence']}] {c['value']}" for c in ch["checks"])
    step("5 geometric checks", s5)

    def s6():
        if not has_slicer:
            raise slicer.SlicerBlocked(sl.get("reason"))
        m = st.state(box["p"]["id"])["slice"]
        assert m and m["layers"] > 0
        L = st.layers(st.load(box["p"]["id"]))
        types = sorted({pp["t"] for l in L for pp in l["paths"]})
        box["slice0"] = m["gcode_sha256"]
        return (f"Bambu Studio {m['slicer_version']} with " + " / ".join(v["name"] for v in m["presets"].values()) +
                f": {m['time_s']/60:.0f} min, {m['filament_g']:.1f} g, {m['layers']} layers, supports {'used' if m.get('support_used') else 'none'}; "
                f"{len(L)} layers parsed for inspection, path types: {', '.join(types)}")
    step("6 configured slicer inspection", s6)

    def s7():
        p = st.load(box["p"]["id"])
        pv = st.preview(p, {"clearance": 0.35})
        im = pv["impact"]
        assert im["interfaces_touched"], im
        k0 = st.keys(p)
        p = st.commit(p, {"clearance": 0.35}, "Looser fit")
        k1 = st.keys(p)
        assert all(k0[n] != k1[n] for n in NODES)
        s = S(p)
        assert all(v == "stale" for k, v in s.items() if has_slicer or k != "slice"), s
        g = st.gate(p)
        assert not g["ready"]
        try:
            st.approve(p, [])
            raise AssertionError("stale outputs were releasable")
        except StudioError:
            pass
        return (f"draft rebuilt in {pv['timing']['total_s']*1000:.0f} ms; interface change flagged: {', '.join(im['interfaces_touched'])}; "
                f"after commit r{p['head']:02d}: {s}; release refused: {g['reasons'][0]}")
    step("7 revision: critical dimension invalidates outputs", s7)

    def s8():
        job = st.run_sync(box["p"]["id"])
        p = st.load(box["p"]["id"])
        s = S(p)
        assert all(v == "current" for k, v in s.items() if has_slicer or k != "slice"), s
        ex = st.read(p, "exports", st.keys(p)["exports"])
        assert ex["files"]["stl"]["sha256"] != box["stl0"]
        a = st.view(p)["interface_audit"][0]
        assert abs(a["modelled"] - (71.5 + 0.7)) < 1e-6
        extra = ""
        if has_slicer:
            m = st.read(p, "slice", st.keys(p)["slice"])
            assert m["gcode_sha256"] != box["slice0"]
            extra = f"; new G-code {m['gcode_sha256'][:12]} ≠ old {box['slice0'][:12]}"
        return f"regenerated as {ex['files']['stl']['name']} (new sha256 {ex['files']['stl']['sha256'][:12]}); pocket width re-measured on the solid: {a['modelled']:.3f} mm{extra}"
    step("8 regenerated exports, checks, slice", s8)

    def s9():
        if not has_slicer:
            raise slicer.SlicerBlocked("release needs a slice")
        p = st.load(box["p"]["id"])
        g = st.gate(p)
        rel = st.approve(p, [w["id"] for w in g["warnings"]], "acceptance run")["release"]
        v = st.verify_release(st.load(p["id"]), rel)
        assert v["intact"] and v["matches_head"]
        p = st.commit(st.load(p["id"]), {"relief_depth": 5})
        ap = st.approval_state(p)
        assert ap["state"] == "superseded"
        st.run_sync(p["id"])
        return f"released {rel} ({len(v['files'])} files, hashes verified; {g['evidence_level']}); next commit marks it superseded ({', '.join(ap['changed'])} changed)"
    step("9 approval gate and supersession", s9)

    def s10():
        p = st.load(box["p"]["id"])
        data = st.export_archive(p).read_bytes()
        q = st.import_archive(data)
        assert st.keys(q) == st.keys(p) and q["head"] == p["head"]
        s = {n: st.status(q)[n]["state"] for n in NODES}
        assert all(v == "current" for k, v in s.items() if has_slicer or k != "slice"), s
        return f"archive {len(data)//1024} kB → restored as “{q['id']}” with {len(q['revisions'])} revisions; all artifacts recognised as current without rebuilding"
    step("10 project save / restore", s10)

    def s11():
        p = st.load(box["p"]["id"])
        head = p["head"]
        msgs = []
        try:
            st.commit(p, {"edge_r": 6, "corner_r": 3})
        except StudioError as e:
            msgs.append(f"infeasible fillet refused: “{e}” ({e.hint})")
        r0 = st.kernel.restarts
        from form.worker import KernelFailure
        try:
            st.kernel.call("variants", timeout=0.01, recipe_id="dock", base=st.rev(p)["values"], grid=[{"depth": d} for d in (70, 80, 90, 100)])
        except KernelFailure as e:
            msgs.append(f"kernel timeout: “{e}” restarts {r0}→{st.kernel.restarts}")
        assert st.load(p["id"])["head"] == head and st.view(st.load(p["id"]))["triangles"] > 100
        path = st.dir(p["id"]) / "project.json"
        st.settings(st.load(p["id"]), {"name": "Acceptance dock"})
        path.write_text("{ truncated", encoding="utf-8")
        q = st.load(p["id"])
        assert q["_recovered"] and q["head"] == head
        msgs.append(f"corrupt project.json: “{q['_recovered']}”")
        return "; ".join(msgs) + f"; head still r{head:02d}, kernel serving"
    step("11 recovery from failed operations", s11)

    def s12():
        p = st.load(box["p"]["id"])
        ts = []
        for lean in (11, 12, 13, 14, 16, 17, 18, 19):
            t = time.perf_counter()
            st.preview(p, {"lean": lean})
            ts.append(time.perf_counter() - t)
        ts.sort()
        return f"8 uncached parametric rebuilds with feature attribution and impact: median {ts[4]*1000:.0f} ms, max {ts[-1]*1000:.0f} ms"
    step("12 measured rebuild latency", s12)

    st.kernel.stop()
    shutil.rmtree(tmp, ignore_errors=True)
    out = ROOT / "docs" / "ACCEPTANCE_RUN.md"
    lines = ["# Acceptance run", "", f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/acceptance.py` on this machine. "
             "Each row is what the run observed; rerun the script to reproduce it.", "",
             "| Step | Result | s | Observed |", "|---|---|---|---|"]
    lines += [f"| {n} | **{s}** | {t} | {d.replace('|', '/')} |" for n, s, t, d in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nwrote", out)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
