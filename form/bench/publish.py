"""docs/BENCHMARKS.md and site/benchmarks.html, written from docs/benchmarks/*.json and nothing else.

Every row is printed, failures included, with the commit, branch, machine and date it was measured on.
"""
from __future__ import annotations

import html
import importlib.util
import math
from pathlib import Path

from . import CADBENCH_JSON, ROOT, SUITES, SUITES_JSON, load
from .cadbench import DIGEST, SOURCES

DOC = ROOT / "docs" / "BENCHMARKS.md"
PAGE = ROOT / "site" / "benchmarks.html"
REPO = "https://github.com/kaizensx/form-studio"
OWNER_CMD = ("form bench cadbench --download ~/cadbench-v3\n"
             "form bench cadbench --tasks ~/cadbench-v3 --agent claude-code --model <model id> --effort <effort>")
MODES = (("create", "Create", 30), ("create_edit", "Create and edit", 30), ("image_to_cad", "Image to CAD", 40))


def num(x) -> str:
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        if math.isnan(x):
            return "NaN"
        if x == 0:
            return "0"
        return f"{x:.6g}"
    if isinstance(x, (list, tuple)):
        return "(" + ", ".join(num(v) for v in x) + ")"
    return "" if x is None else str(x)


def pct(x) -> str:
    return "" if x is None else f"{100 * x:.2f} %"


def _tol(r: dict) -> str:
    t = r.get("tolerance")
    if t in (None, "") or isinstance(t, str):
        return "" if t is None else str(t)
    return f"{100 * t:g} %" if r.get("relative") else num(t)


def _err(r: dict) -> str:
    e = r.get("error")
    if e is None or isinstance(e, str):
        return ""
    return f"{100 * e:.3g} %" if r.get("relative") else num(e)


def _src(entry: dict) -> str:
    c = (entry.get("commit") or "")[:10]
    b = entry.get("branch") or ""
    return f"{c}" + (f" ({b})" if b and b not in ("HEAD",) else "") + (" with local changes" if entry.get("dirty") else "")


def _suites() -> list[tuple[dict, dict | None]]:
    saved = load(SUITES_JSON, {"suites": {}})["suites"]
    return [(s, saved.get(s["id"])) for s in SUITES]


def _cad() -> dict:
    return load(CADBENCH_JSON, {"runs": []})


# ---- Markdown ---------------------------------------------------------------------------------------------------

def markdown() -> str:
    cad = _cad()
    out = ["# Benchmarks", "",
           "Every number here comes from a run you can repeat, with the commit, the machine and the date it ran on. "
           "Failures are printed with the rest. This page is written by `form bench publish` from "
           "`docs/benchmarks/suites.json` and `docs/benchmarks/cadbench.json`; never edit it by hand.", ""]
    out += ["## Parametric CAD Bench v3", "",
            f"[Parametric CAD Bench v3]({SOURCES['paper']}) (Chen, Xia and Mao, 2026) gives an agent 100 FreeCAD tasks: "
            "30 text to CAD, 30 create then edit, 40 engineering drawing to CAD. A separate verifier scores the saved "
            "model's geometry and its consistency with a held-back specification, between 0 and 1. The tasks "
            f"([`gnucleus-ai/cad-bench@v3`]({SOURCES['tasks']}), content digest `{DIGEST}`), their reference models and "
            f"the [submission tools]({SOURCES['submission']}) are Apache-2.0; the [scorer]({SOURCES['validator']}) is "
            "Apache-2.0 too. FreeCAD and Open CASCADE are LGPL-2.1.", ""]
    real = [r for r in cad.get("runs", []) if not r.get("standin")]
    stand = [r for r in cad.get("runs", []) if r.get("standin")]
    if not real:
        out += ["**Score: pending a run with a real model.** The harness, the scoring and the plumbing are proven "
                "below; the score itself needs an agent and model run with their owner's account. To run it:", "",
                "```", OWNER_CMD, "```", "",
                "That writes the results into `docs/benchmarks/cadbench.json` and this page. A full run is 100 tasks "
                "with up to 9000 s each; the spending cap per task is `--budget-usd` (default 10).", ""]
    for r in real + stand:
        out += _cad_run_md(r)
    p = cad.get("parity")
    if p:
        out += ["### Scorer parity", "",
                f"{p['what']}. Every row must be 1.0. Measured {p['date']} on {p['machine']}, commit "
                f"`{(p.get('commit') or '')[:10]}`.", "", "| Task | Mode | Reward |", "|---|---|---|"]
        out += [f"| `{x['task']}` | {x['mode']} | {num(x['reward'])} |" for x in p["rows"]]
        out.append("")
    out += ["### How Form Studio runs it", "",
            "- **Agent:** the agent's own CLI through Form Studio's adapter (`form/agents`), with Form Studio's MCP "
            "server attached, exactly as a conversation in the app runs it, plus Read, Write and Edit inside the trial "
            "folder and Bash limited to FreeCAD's command line. The verifier accepts only a FreeCAD PartDesign feature "
            "tree: the agent builds with Form Studio's tools and writes the answer with `freecad_partdesign`, Form "
            "Studio's PartDesign export (recomputed and checked in FreeCAD); writing the FreeCAD script itself stays "
            "the fallback.",
            "- **Prompt:** each task's `instruction.md` as published, with `/app` replaced by the trial's folder, after "
            "a short preamble saying where that folder is, that Form Studio's tools are attached, that "
            "`freecad_partdesign` writes the answer files, and where FreeCAD's command line is.",
            "- **Isolation:** each trial has its own Form Studio data folder and settings. The agent sees only the "
            "task's environment files (the drawing); `solution/` and `tests/` stay out of its folder.",
            "- **Scoring:** the task's own `tests/test.sh` and `run_scorer.py` in the image its `tests/Dockerfile` "
            "builds (FreeCAD 1.1.0, gnucleus-freecad-validator 0.6.0), with no network. Failures and missing files "
            "count zero; mode means are over 30, 30 and 40 tasks, as on the leaderboard.",
            "- **Not a leaderboard entry:** the agent runs on the host, not in the task's container, so a result here "
            "is not a Harbor job. Submitting needs `harbor run` with an adapter that installs Form Studio in the task "
            "container.", ""]
    out += ["## Form Studio's own suites", "",
            "Each suite compares a value Form Studio computes with a published one. `form bench run --save` runs them; "
            "each runs on the source tree that has its code, and says which.", "",
            "| Suite | Rows | Pass | Fail | Source | Machine | Date | Time |", "|---|---|---|---|---|---|---|---|"]
    for s, e in _suites():
        if not e:
            out.append(f"| {s['title']} | | | | not run yet | | | |")
        elif not e.get("available"):
            out.append(f"| {s['title']} | 0 | | | not in this build: {e.get('reason', '')} | {e['machine']} | {e['date']} | |")
        else:
            out.append(f"| [{s['title']}](#{s['id']}) | {len(e['rows'])} | {e['passed']} | {e['failed']} | `{_src(e)}` | "
                       f"{e['machine']} | {e['date']} | {e['seconds']} s |")
    out.append("")
    for s, e in _suites():
        if not e or not e.get("available"):
            continue
        out += [f"<a id=\"{s['id']}\"></a>", f"### {s['title']}", "",
                f"Wave {s['wave']}. {len(e['rows'])} rows, {e['passed']} pass, {e['failed']} fail. Commit `{_src(e)}`, "
                f"{e['machine']}, Python {e.get('python', '')}, {e['date']}."
                + (f" Versions: {', '.join(f'{k} {v}' for k, v in e['versions'].items())}." if e.get("versions") else "")
                + (f" Not in the tree of {e['absent_on']['commit'][:10]} ({e['absent_on']['date']}): "
                   f"{e['absent_on']['reason']}." if e.get("absent_on") else ""), "",
                "| Group | Quantity | Expected | Computed | Unit | Error | Accepted | Result | Source |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in e["rows"]:
            cells = [r["group"], r["item"], num(r["expected"]), num(r["got"]), r.get("unit", ""), _err(r), _tol(r),
                     "pass" if r["pass"] else "**FAIL**", (r.get("source") or "") + (f"; {r['note']}" if r.get("note") else "")]
            out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _cad_run_md(r: dict) -> list[str]:
    s = r["summary"]
    who = "Stand-in agent (deterministic, no model): proves the plumbing, is not a score" if r.get("standin") else \
        f"{r['agent']}, model {r['model']}, effort {r.get('effort', 'default')}"
    out = [f"### {who}", "",
           f"{s['tasks']} of 100 tasks" + ("" if s.get("complete") else " (a subset: not comparable with the leaderboard)")
           + f". Mean reward **{num(s['mean_reward'])}**; scored {s['scored']}, errors {s['errors']}, perfect "
           f"{s['perfect']}. Form Studio {r['form_version']}, commit `{r['commit'][:10]}`"
           + (" with local changes" if r.get("dirty") else "") + f", {r['machine']}, FreeCAD on the host: "
           f"{r['freecad_on_host']}, {r['date']}.", "",
           "| Mode | Tasks | Mean reward |", "|---|---|---|"]
    for m, label, _n in MODES:
        x = s["modes"].get(m)
        if x:
            out.append(f"| {label} | {x['tasks']} | {num(x['mean_reward'])} |")
    out += ["", "| Task | Mode | Reward | Geometry | Spec | Files | Form Studio tools | Seconds | Why |",
            "|---|---|---|---|---|---|---|---|---|"]
    for t in r["trials"]:
        d = t.get("details") or {}
        geo = d.get("geometry_similarity", (d.get("target") or {}).get("geometry_similarity"))
        spec = d.get("cad_spec_consistency", (d.get("target") or {}).get("cad_spec_consistency"))
        why = t.get("error") or d.get("reason") or d.get("geometry_similarity_reason") or \
            (d.get("target") or {}).get("geometry_similarity_reason") or ""
        ag = t.get("agent") or {}
        out.append(f"| `{t['id']}` | {t['mode']} | {num(t.get('reward'))} | {num(geo)} | {num(spec)} | "
                   f"{', '.join(t.get('answers') or []) or 'none'} | {', '.join(ag.get('form_tools') or []) or 'none'} | "
                   f"{num(ag.get('seconds'))} | {str(why)[:160].replace('|', '/')} |")
    out.append("")
    return out


# ---- HTML -------------------------------------------------------------------------------------------------------

def _chrome():
    spec = importlib.util.spec_from_file_location("site_chrome", ROOT / "site" / "tools" / "chrome.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _md_inline(s: str) -> str:
    """Escape, then `code`, **bold** and [text](url) of the Markdown cells above."""
    import re
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+|#[^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def page() -> str:
    """The Markdown above as the site's page, in the style of the hand-written pages."""
    md = markdown().splitlines()
    body, i = [], 0
    while i < len(md):
        line = md[i]
        if line.startswith("```"):
            j = i + 1
            code = []
            while j < len(md) and not md[j].startswith("```"):
                code.append(md[j])
                j += 1
            body.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            i = j + 1
            continue
        if line.startswith("|") and i + 1 < len(md) and md[i + 1].startswith("|---"):
            head = [c.strip() for c in line.strip("|").split(" | ")]
            rows = []
            j = i + 2
            while j < len(md) and md[j].startswith("|"):
                rows.append([c.strip().replace("\\|", "|") for c in md[j].strip().strip("|").split(" | ")])
                j += 1
            th = "".join(f"<th>{_md_inline(h)}</th>" for h in head)
            trs = []
            for r in rows:
                tds = []
                for c in r:
                    cls = ' class="r-pass"' if c == "pass" else ' class="r-fail"' if c == "**FAIL**" else ""
                    tds.append(f"<td{cls}>{_md_inline(c)}</td>")
                trs.append("<tr>" + "".join(tds) + "</tr>")
            body.append(f'<div class="tablewrap"><table>\n<thead><tr>{th}</tr></thead>\n<tbody>\n' + "\n".join(trs)
                        + "\n</tbody></table></div>")
            i = j
            continue
        if line.startswith("<a id="):
            body.append(line)
        elif line.startswith("# "):
            body.append(f"<h1>{_md_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{_md_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            body.append(f"<h3>{_md_inline(line[4:])}</h3>")
        elif line.startswith("- "):
            items = []
            while i < len(md) and md[i].startswith("- "):
                items.append(f"<li>{_md_inline(md[i][2:])}</li>")
                i += 1
            body.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.strip():
            body.append(f"<p>{_md_inline(line)}</p>")
        i += 1
    if body and body[1].startswith("<p>"):
        body[1] = body[1].replace("<p>", '<p class="lede">', 1)
    ch = _chrome()
    desc = ("Form Studio's benchmarks: Parametric CAD Bench v3 through Form Studio's tools, and its own verification "
            "suites, every row with its commit, machine and date.")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Benchmarks · Form Studio</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="theme-color" content="#0b0b0c" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#eeece8" media="(prefers-color-scheme: light)">
<link rel="canonical" href="https://kaizensx.github.io/form-studio/benchmarks.html">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Form Studio">
<meta property="og:title" content="Benchmarks · Form Studio">
<meta property="og:description" content="Every score with its commit, machine and date, failures included.">
<meta property="og:image" content="https://kaizensx.github.io/form-studio/assets/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="favicon.ico" sizes="48x48">
<link rel="icon" type="image/svg+xml" href="assets/favicon.svg">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<link rel="preload" href="fonts/Geist.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="css/site.css">
<script>document.documentElement.classList.add("js");try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<script type="module" src="js/nav.js"></script>
</head>
<body>
{ch.nav("", "")}

<div class="wrap measure">
<main id="main" class="prose">
{chr(10).join(body)}
</main>
</div>

{ch.foot("")}
</body>
</html>
"""


def publish() -> dict:
    DOC.write_text(markdown(), encoding="utf-8")
    PAGE.write_text(page(), encoding="utf-8")
    return {"markdown": str(DOC), "page": str(PAGE)}
