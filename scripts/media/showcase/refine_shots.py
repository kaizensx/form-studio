"""Automatic design refinement, before and after, on an exemplar.

    .venv/bin/python scripts/media/showcase/refine_shots.py screw_post_enclosure

Creates the exemplar as a project with refinement off, then runs the refinement engine on it and prints what it
kept (operators, deficit before and after, seconds) and the project id with its two revisions. Photograph them with
product_shots.py: SHOWCASE_DATA=.dev/showcase/refine-data and shots that name "pid" and "rev".
"""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
S = Path(os.environ.get("SHOWCASE_WORK") or ROOT / ".dev" / "showcase")      # scratch: projects, zones, renders
S.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["FORM_DATA"] = str(S / "refine-data")
os.environ["FORM_CONFIG"] = "/nonexistent"
os.environ["FORM_REFINE"] = "off"


def main():
    from form import config, exemplars
    from form.refine import engine
    from form.refine.ledger import Ledger
    from form.studio import Studio
    st = Studio(config.load())
    idx_f = S / "refine.json"
    idx = json.loads(idx_f.read_text()) if idx_f.exists() else {}
    try:
        for name in sys.argv[1:]:
            p = st.create_design("refine " + name.replace("_", " "), exemplars.get(name)["source"], purpose="model")
            before = p["head"]
            os.environ.pop("FORM_REFINE", None)
            t = time.time()
            r = engine.refine(st, p["id"], ledger=Ledger.memory())
            os.environ["FORM_REFINE"] = "off"
            p = st.load(p["id"])
            idx[name] = {"pid": p["id"], "before": before, "after": p["head"], "seconds": round(time.time() - t, 1),
                         "skipped": r.get("skipped"), "stopped": r.get("stopped"),
                         "base": (r.get("base") or {}).get("total"), "final": (r.get("final") or {}).get("total"),
                         "applied": [{"operator": a["operator"], "label": a["label"], "reason": a.get("reason")} for a in r.get("applied", [])]}
            idx_f.write_text(json.dumps(idx, indent=1, default=str))
            print("REFINED", name, json.dumps(idx[name], default=str)[:1500], flush=True)
    finally:
        st.kernel.stop()


if __name__ == "__main__":
    main()
