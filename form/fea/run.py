"""The FEA engine's entry point. Runs in the engine's own Python, out of the app:

    <engine python> -m form.fea.run <job folder>
    <engine python> -m form.fea.run --versions

The job folder holds job.json: {"step": path of the STEP file, "spec": the study (form/fea/core.py)}. While it runs,
one JSON object per line goes to standard output: {"progress": text, "fraction": 0..1}. At the end result.json (the
study's result, or {"error": {...}}) and field.json (what the viewport colours) are written there. A file named
`cancel` in the folder stops the run at the next check; the parent may also end the process.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--versions"]:
        from . import verify
        print(json.dumps(verify.versions()))
        return 0
    if len(argv) != 1:
        sys.exit("usage: python -m form.fea.run <job folder>")
    d = Path(argv[0])
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    t0 = time.perf_counter()

    def progress(text, fraction=None):
        print(json.dumps({"progress": text, "fraction": fraction, "seconds": round(time.perf_counter() - t0, 1)}), flush=True)

    def cancelled():
        return (d / "cancel").exists()

    def write(name, data):
        tmp = d / (name + ".tmp")
        tmp.write_text(json.dumps(data, default=float), encoding="utf-8")
        tmp.replace(d / name)
    try:
        from . import core
        from . import mesh as mesh_mod
        from . import verify
        progress("Reading the solid", 0.0)
        geo = mesh_mod.load(job["step"])
        result, field = core.run(geo, job["spec"], progress, cancelled)
        result["versions"] = verify.versions()
        write("field.json", field)
        write("result.json", result)
        return 0
    except Exception as e:                           # noqa: BLE001 - every failure is reported, none is hidden
        kind = getattr(e, "kind", None) or ("mesh" if type(e).__name__ == "MeshError" else "engine")
        err = {"message": str(e), "hint": getattr(e, "hint", ""), "kind": kind, "type": type(e).__name__}
        if kind == "engine":
            import traceback
            err["trace"] = traceback.format_exc()[-3000:]
        write("result.json", {"error": err})
        return 2 if kind == "cancelled" else 1


if __name__ == "__main__":
    sys.exit(main())
