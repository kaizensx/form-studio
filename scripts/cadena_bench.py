"""Mesh to editable CAD on CADENA-Bench (real mechanical parts), opt-in, aggregates only.

    .venv/bin/python scripts/cadena_bench.py --data ~/datasets/cadena-bench --out ~/cadena.md --limit 20
    .venv/bin/python scripts/cadena_bench.py --download --out ~/cadena.md --limit 20     # fetches it first, see below

CADENA-Bench (huggingface.co/datasets/kulibinai/cadena-bench, tagged MIT; from kulibinai/cadena) holds 3396 parts in
six families. Its card says the meshes come from the MCB, TMCAD and CADNet corpora, whose own licences Form Studio has
not checked, so the meshes are never committed and never copied into this repository:

- Nothing is downloaded unless you pass --download. Without it, point --data at a copy you already have: a folder of
  STL files (searched recursively; a subfolder name is used as the family), or the dataset's Parquet files
  (part_id, family, mesh as STL bytes; reading them needs pyarrow).
- --download needs huggingface_hub and stores the dataset under --cache (default ~/.cache/form-studio/cadena-bench).
- The report (--out), the cache and the working folder must be outside this repository; the script refuses otherwise.
- The report holds aggregates only (counts, rates, means and medians, overall and per family): no part ids, no meshes.
  The working folder with the extracted meshes and results is deleted at the end unless you pass --keep.

Each part runs through form/recon exactly as scripts/recon_bench.py runs a part (its own process, without the learned
engine), and the result's STEP is scored by the critics: occupancy IoU and the gates (form/recon/gates.py) and the
GMS-compatible score (form/recon/gms.py). As in CADENA's protocol, a part whose reconstruction gives no STEP counts as
invalid and is left out of every mean; the invalid rate is reported beside them.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

DATASET = "kulibinai/cadena-bench"
DEFAULT_CACHE = Path.home() / ".cache" / "form-studio" / "cadena-bench"


def outside_repo(p: Path, what: str) -> Path:
    """p, resolved, or SystemExit when it is inside this repository (meshes and per-part results stay out of it)."""
    q = Path(p).expanduser().resolve()
    if q == ROOT or ROOT in q.parents:
        raise SystemExit(f"refusing: {what} {q} is inside the repository {ROOT}. Choose a folder outside it.")
    return q


def download(cache: Path, revision: str | None) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise SystemExit("--download needs huggingface_hub (pip install huggingface_hub), or pass --data with a copy "
                         "you already have.")
    print(f"downloading {DATASET} (revision {revision or 'main'}) into {cache} ...", flush=True)
    return Path(snapshot_download(repo_id=DATASET, repo_type="dataset", revision=revision, local_dir=str(cache),
                                  allow_patterns=["*.parquet", "*.md", "*.json"]))


def parts(data: Path, work: Path, limit: int | None, family: str | None):
    """(family, stl path) for up to `limit` parts of the copy at `data`, meshes written into `work`."""
    data = Path(data).expanduser()
    stls = sorted(data.rglob("*.stl")) if data.is_dir() else ([data] if data.suffix.lower() == ".stl" else [])
    if stls:
        n = 0
        for p in stls:
            fam = p.parent.name if p.parent != data else "all"
            if family and fam != family:
                continue
            yield fam, p
            n += 1
            if limit and n >= limit:
                return
        return
    pq = sorted(data.rglob("*.parquet")) if data.is_dir() else [data]
    if not pq:
        raise SystemExit(f"no STL or Parquet files under {data}")
    try:
        import pyarrow.parquet as pqm
    except ImportError:
        raise SystemExit("reading the dataset's Parquet files needs pyarrow (pip install pyarrow)")
    n = 0
    for f in pq:
        pf = pqm.ParquetFile(f)
        for batch in pf.iter_batches(columns=["family", "mesh"], batch_size=32):
            for fam, blob in zip(batch.column("family").to_pylist(), batch.column("mesh").to_pylist()):
                if family and fam != family:
                    continue
                if isinstance(blob, dict):              # datasets may store binary as {"bytes": ...}
                    blob = blob.get("bytes")
                p = work / f"part{n:05d}.stl"
                p.write_bytes(blob)
                yield str(fam), p
                n += 1
                if limit and n >= limit:
                    return


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


def aggregate(rows: list) -> dict:
    valid = [r for r in rows if r.get("gates") not in (None, "no STEP") and not str(r.get("gates")).startswith("error")]
    return {"parts": len(rows), "valid": len(valid),
            "invalid_rate": round(1 - len(valid) / len(rows), 4) if rows else None,
            "within_tolerance_rate": round(sum(1 for r in rows if r.get("within")) / len(rows), 4) if rows else None,
            "gms_mean": _mean([r.get("gms") for r in valid]),
            "occupancy_iou_mean": _mean([r.get("occupancy_iou") for r in valid]),
            "gates_pass_rate": round(sum(1 for r in valid if r.get("gates") == "pass") / len(valid), 4) if valid else None,
            "brep_pct_median": _median([r.get("brep_pct") for r in valid]),
            "editable_pct_median": _median([r.get("editable_pct") for r in valid]),
            "seconds_median": _median([r.get("seconds") for r in rows]),
            "gate_seconds_median": _median([r.get("gate_seconds") for r in valid])}


def write(path: Path, overall: dict, fams: dict, meta: dict):
    def f(x):
        return "–" if x is None else f"{x:g}"
    cols = ["parts", "valid", "invalid_rate", "within_tolerance_rate", "gms_mean", "occupancy_iou_mean",
            "gates_pass_rate", "brep_pct_median", "editable_pct_median", "seconds_median", "gate_seconds_median"]
    L = ["# Mesh to editable CAD on CADENA-Bench (aggregates only)", "",
         f"Written by `scripts/cadena_bench.py` on {meta['date']}: {meta['parts']} parts from {meta['source']}, "
         f"tolerance {meta['tol']} mm, budget {meta['budget']:g} s per part, without the learned engine. "
         "Invalid parts (no STEP) are left out of every mean. GMS is GMS-compatible (form/recon/gms.py), not the "
         "upstream code.", "",
         "| Family | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for name, agg in [("all", overall)] + sorted(fams.items()):
        L.append(f"| {name} | " + " | ".join(f(agg[c]) for c in cols) + " |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", help="your copy of CADENA-Bench: a folder of STL files or the dataset's Parquet files")
    src.add_argument("--download", action="store_true", help="download the dataset first (needs huggingface_hub)")
    ap.add_argument("--revision", default=None, help="dataset revision for --download (default: main)")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="where --download stores the dataset")
    ap.add_argument("--out", required=True, help="Markdown report, outside the repository")
    ap.add_argument("--json", default=None, help="also write the aggregates as JSON (outside the repository)")
    ap.add_argument("--limit", type=int, default=20, help="number of parts (0 for all)")
    ap.add_argument("--family", default=None, help="only this family")
    ap.add_argument("--tol", type=float, default=0.05, help="reconstruction tolerance in mm")
    ap.add_argument("--budget", type=float, default=240.0, help="seconds per part")
    ap.add_argument("--keep", action="store_true", help="keep the working folder (extracted meshes and results)")
    a = ap.parse_args(argv)
    out = outside_repo(Path(a.out), "the report")
    js = outside_repo(Path(a.json), "the JSON") if a.json else None
    if a.download:
        data = download(outside_repo(Path(a.cache), "the cache"), a.revision)
        source = f"{DATASET} (downloaded, revision {a.revision or 'main'})"
    else:
        data = Path(a.data).expanduser()
        source = "a local copy"
    work = outside_repo(Path(tempfile.mkdtemp(prefix="cadena-bench-")), "the working folder")
    import recon_bench
    rows = []
    try:
        for k, (fam, p) in enumerate(parts(data, work, a.limit or None, a.family)):
            print(f"part {k + 1} ({fam}) ...", flush=True)
            r = recon_bench.isolated(p, a.tol, False, work / f"r{k:05d}", a.budget, p)
            r["family"] = fam
            rows.append({key: r.get(key) for key in ("family", "gates", "gms", "occupancy_iou", "within", "brep_pct",
                                                    "editable_pct", "seconds", "gate_seconds")})
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    if not rows:
        raise SystemExit("no parts found")
    fams = {}
    for r in rows:
        fams.setdefault(r["family"], []).append(r)
    overall = aggregate(rows)
    per = {k: aggregate(v) for k, v in fams.items()}
    meta = {"date": time.strftime("%Y-%m-%d"), "parts": len(rows), "source": source, "tol": a.tol, "budget": a.budget}
    write(out, overall, per, meta)
    if js:
        js.write_text(json.dumps({"meta": meta, "all": overall, "families": per}, indent=1))
    print(f"wrote {out}" + (f" (working folder kept: {work})" if a.keep else ""))


if __name__ == "__main__":
    main()
