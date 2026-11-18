"""Shared checks for the built-in recipe library (used by tests/test_library_*.py).

Builds a recipe in this process with the real kernel and the same attribution the worker uses (form.kernel._build),
then checks what every library recipe promises: it validates, builds the declared number of valid solids, fits a
180 mm cube (the smallest common bed, an A1 mini) at its defaults, every face belongs to a declared feature, every
interface dimension reads back off the solid as intended, and its assembly (if any) is well formed.
"""
from __future__ import annotations

BED = 180.0


def build(rid: str, **over):
    from form.kernel import _build
    from form.recipes import registry
    r = registry()[rid]
    return _build(rid, {**r.defaults(), **over}, 0.1)


def check(case, rid: str, bed: bool = True, **over):
    """Build `rid` with `over` applied and assert the library contract. Returns the built model."""
    from form.recipes import registry
    r = registry()[rid]
    m = build(rid, **over)
    shape = m["shape"]
    case.assertTrue(shape.is_valid, f"{rid} {over}: invalid solid")
    case.assertEqual(len(shape.solids()), r.solids, f"{rid} {over}: solid count")
    lo, hi = m["bbox"]
    if bed:
        size = sorted(hi[i] - lo[i] for i in range(3))
        case.assertLessEqual(size[-1], BED, f"{rid} {over}: {size} does not fit a {BED:g} mm bed")
    case.assertAlmostEqual(lo[2], 0.0, 3, msg=f"{rid} {over}: not on the plate")
    feats = {f.id for f in r.features}
    case.assertTrue(set(m["by_feature"]) <= feats, f"{rid}: faces on undeclared features {set(m['by_feature']) - feats}")
    v = m["values"]
    for row in r.measure(v, m["by_feature"]):
        case.assertAlmostEqual(row["modelled"], row["intended"], delta=1e-3,
                               msg=f"{rid} {over}: {row['label']} modelled {row['modelled']} vs {row['intended']}")
    a = r.assembly(v)
    if a is not None:
        case.assertEqual(a.validate(len(shape.solids())), [], f"{rid}: assembly")
    return m


def library_contract(case, rid: str):
    """Metadata every listed recipe carries."""
    from form.recipes import registry
    r = registry()[rid]
    case.assertFalse(r.legacy)
    case.assertTrue(r.title and r.summary and r.category and r.tags, f"{rid}: title, summary, category, tags")
    case.assertLessEqual(len(r.summary), 200, f"{rid}: keep the summary short")
    ids = {f.id for f in r.features}
    for p in r.params:
        case.assertIn(p.feature, ids | {""}, f"{rid}: {p.key} names an unknown feature")
        case.assertTrue(p.min <= p.default <= p.max, f"{rid}: {p.key} default outside its range")
    r.validate(r.defaults())
