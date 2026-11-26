"""Draw the home page's proof sheet from a real run of scripts/proof_demo.py.

    .venv/bin/python site/tools/export_proof.py            # runs the demo (a few seconds), then stamps the page
    .venv/bin/python site/tools/export_proof.py run.json   # stamps from a run saved with proof_demo.py --json

Writes site/assets/data/proof.json (the run, as the tools returned it) and the section between <!--proof--> and
<!--/proof--> in site/index.html. Every requirement, measurement, tolerance and count on the page is copied from the
run; nothing is typed in here but the words around them.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE.parent
KEEP = ("brief_goal", "contract_trap", "audit_trap", "first", "repaired", "repair_op", "repair_edit")


def run() -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import proof_demo
    out: dict = {"steps": []}
    asyncio.run(proof_demo.run(out))
    return out


def t(s) -> str:
    """A value from the run, typeset: a real multiplication sign and minus, nothing else changed."""
    s = re.sub(r"(?<=\d) x (?=[\dØ])", " × ", str(s))
    s = re.sub(r"(?<=[\d)]) - (?=\d)", " − ", s)
    return html.escape(s)


def rev(proof) -> str:
    return re.search(r"\((r\d+)\)", proof["summary"]).group(1)


def sheet(proof, key: str, lead: str = "") -> str:
    rows = []
    for i, r in enumerate(proof["rows"]):
        ok = r["status"] == "PASS"
        tag = "t-pass" if ok else "t-signal" if r["status"] == "FAIL" else "t-amber"
        why = ""
        if not ok and r.get("why"):
            why = f'<span class="pf-why">{t(r["why"])} · {t(r.get("where", ""))}</span>'
        rows.append(
            f'<li class="pf-row{"" if ok else " bad"}" style="--i:{i}"><span class="tag {tag}">{t(r["status"])}</span>'
            f'<span class="pf-req">{t(r["requirement"])}{why}</span><span class="pf-meas mono">{t(r["measured"])}</span>'
            f'<span class="pf-tol mono">{t(r["tolerance"])}</span><span class="pf-feat mono">{t(r.get("feature", ""))}</span>'
            f'<span class="tag t-ink">{t(r["evidence"])}</span></li>')
    summary = t(proof["summary"]).replace(f" ({rev(proof)})", "")
    return (f'<div class="pf-pane" data-pane="{key}">{lead}'
            '<div class="pf-head" aria-hidden="true"><span>Status</span><span>Requirement</span><span>Measured</span>'
            '<span>Tolerance</span><span>Owed by</span><span>Evidence</span></div>'
            f'<ol class="pf-rows">{"".join(rows)}</ol>'
            f'<p class="pf-sum{" green" if proof["green"] else ""}"><i aria-hidden="true"></i>{summary}</p></div>')


def section(d: dict) -> str:
    first, fixed, audit = d["first"], d["repaired"], d["audit_trap"]
    n = len(fixed["rows"])
    passed = lambda p: sum(r["status"] == "PASS" for r in p["rows"])  # noqa: E731
    r1, r2 = rev(first), rev(fixed)
    op, edit = d["repair_op"], d["repair_edit"]
    built = ", ".join(c["feature"] for c in edit["changed"])
    value = op.get("default", op.get("value"))
    asserts = "".join(f"<li>{t(a)}</li>" for a in d["contract_trap"])
    conflicts = "".join(f'<p>{t(c["why"][0].upper() + c["why"][1:])}.</p>' for c in audit["conflicting"])
    brief = (f'<div class="pf-pane" data-pane="brief"><p class="pf-goal">“{t(d["brief_goal"])}”</p>'
             f'<ul class="pf-asserts" aria-label="The contract read from the brief">{asserts}</ul>'
             f'<div class="pf-audit"><span class="tag t-signal">Conflict</span>{conflicts}'
             f'<span class="pf-ev">{t(audit["evidence"][0].upper() + audit["evidence"][1:])}.</span></div>'
             '<p class="pf-sum"><i aria-hidden="true"></i>The numbers cannot all hold, so there is nothing to build to yet.</p></div>')
    lead = (f'<p class="pf-edit"><code>edit_design</code><span class="mono">{t(op["op"])} {t(op["param"])} = {t(value)}</span>'
            f'<span class="pf-built">rebuilt: {t(built)} · reused: {edit["reused"]}</span></p>')
    return f"""<!--proof-->
<section class="fx proof" id="proof" data-nav="how" aria-labelledby="proof-title">
  <div class="wrap fx-grid">
    <div class="fx-copy">
      <p class="eyebrow rv">The proof sheet</p>
      <h2 id="proof-title" class="rv">A brief is<br class="br"> a contract.</h2>
      <p class="rv">The numbers in your brief become requirements. They are audited by arithmetic before any code is written, then measured on the kernel's solid after every build. A red row names the feature that owes it, and one edit rebuilds only what changed.</p>
      <dl class="readout rv">
        <div><dt>Requirements</dt><dd class="mono">{n}</dd></div>
        <div><dt>Proved at {r1}</dt><dd class="mono">{passed(first)} of {n}</dd></div>
        <div><dt>Proved at {r2}</dt><dd class="mono">{passed(fixed)} of {n}</dd></div>
      </dl>
      <p class="rv"><a class="more" href="docs/features.html#checks-and-evidence">How a design is proved <span aria-hidden="true">→</span></a></p>
    </div>
    <figure class="proof-win island rv" id="proof-win" data-at="{r2}">
      <div class="mtb"><span class="lights" aria-hidden="true"><i></i><i></i><i></i></span><b class="pn">Bolted flange</b><span class="rv-chip mono" id="pf-rev" data-brief="brief" data-{r1}="{r1}" data-{r2}="{r2}">{r2}</span><span class="sp"></span><span class="tag t-datum">Proof sheet</span></div>
      <div class="pf-tabs" role="group" aria-label="The run, step by step">
        <button type="button" data-at="brief" aria-pressed="false"><span class="mono">01</span><b>The brief</b><em>audited, not built</em></button>
        <button type="button" data-at="{r1}" aria-pressed="false"><span class="mono">02</span><b>First build</b><em>{r1} · {passed(first)} of {n} proved</em></button>
        <button type="button" data-at="{r2}" aria-pressed="true"><span class="mono">03</span><b>One edit</b><em>{r2} · {passed(fixed)} of {n} proved</em></button>
      </div>
      <div class="pf-body">
        {brief}
        {sheet(first, r1)}
        {sheet(fixed, r2, lead)}
      </div>
      <figcaption>A real run of <code>scripts/proof_demo.py</code>: a script calls the same MCP tools an agent calls. Pass and fail are measured on the kernel's solid of that revision; nothing here is a physical result.</figcaption>
    </figure>
  </div>
</section>
<!--/proof-->"""


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    d = json.loads(Path(args[0]).read_text(encoding="utf-8")) if args else run()
    d = {k: d[k] for k in KEEP}
    (SITE / "assets" / "data" / "proof.json").write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    page = SITE / "index.html"
    text = page.read_text(encoding="utf-8")
    new, k = re.subn(r"<!--proof-->.*?<!--/proof-->", lambda _m: section(d), text, count=1, flags=re.S)
    if not k:
        sys.exit("site/index.html has no <!--proof--> ... <!--/proof--> block")
    page.write_text(new, encoding="utf-8")
    print("stamped the proof sheet:", d["first"]["summary"], "->", d["repaired"]["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
