// /compat/: the nightly slicer matrix (data.json and history.json, copied from the ci-assets branch at deploy).
import "./nav.js";
import { ago, esc, lineChart, loadJSON, tile, when } from "./cidata.js";

const $ = (s) => document.querySelector(s);

const fmtTime = (s) => {
  if (!Number.isFinite(s)) return "";
  const m = Math.round(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${m} min`;
};

function cell(c) {
  if (!c) return '<td><span class="fine">—</span></td>';
  const cls = { ok: "ok", "check-failed": "warn", "slice-failed": "bad", "build-failed": "err" }[c.state] || "err";
  const head = { ok: "Sliced", "check-failed": "Sliced", "slice-failed": "No slice", "build-failed": "No build" }[c.state] || c.state;
  const sliced = c.state === "ok" || c.state === "check-failed";
  const sub = sliced ? `${fmtTime(c.time_s)} · ${Number.isFinite(c.filament_g) ? c.filament_g.toFixed(1) + " g" : ""}` : "";
  const fails = c.rollup && c.rollup.FAIL ? `${c.rollup.FAIL} check${c.rollup.FAIL > 1 ? "s" : ""} fail` : "";
  const tip = [head, sub, fails, c.layers ? `${c.layers} layers` : "", c.error || ""].filter(Boolean).join(" · ");
  return `<td><div class="ci-cell ${cls}" title="${esc(tip)}"><b>${esc(head)}</b><span>${esc(sub || fails || (c.error || "").slice(0, 40))}</span></div></td>`;
}

async function main() {
  let d;
  try {
    d = await loadJSON("data.json");
  } catch (e) {
    $("#stamp").textContent = "";
    $("#matrix").outerHTML = '<div class="ci-empty">The first nightly run has not been published yet.</div>';
    return;
  }
  const t = d.totals || {};
  $("#stamp").innerHTML = `Last run ${esc(when(d.generated))} (${esc(ago(d.generated))})` +
    (d.run_url ? ` · <a href="${esc(d.run_url)}">workflow run</a>` : "") +
    (d.commit ? ` · commit <a href="https://github.com/kaizensx/form-studio/commit/${esc(d.commit)}">${esc(d.commit.slice(0, 7))}</a>` : "");
  const pct = t.cells ? Math.round((100 * t.sliced) / t.cells) : 0;
  $("#tiles").innerHTML = [
    tile(`${t.sliced ?? 0}/${t.cells ?? 0}`, "", "recipe × slicer pairs sliced"),
    tile(pct, "%", "of the matrix sliced"),
    tile(t.ok ?? 0, "", "sliced with every check passing"),
    tile((d.slicers || []).length, "", "slicers"),
    tile((d.recipes || []).length, "", "recipes"),
  ].join("");
  const slicers = d.slicers || [];
  const head = `<thead><tr><th scope="col">Recipe</th>${slicers.map((s) => `<th scope="col">${esc(s.name)}<span class="ver">${esc(s.version || "")}</span></th>`).join("")}</tr></thead>`;
  const body = (d.recipes || []).map((r) => `<tr><th scope="row">${esc(r.title)}${r.builtin ? "" : '<span class="tag">community</span>'}</th>` +
    slicers.map((s) => cell((d.cells[r.id] || {})[s.kind])).join("") + "</tr>").join("");
  $("#matrix").innerHTML = head + `<tbody>${body}</tbody>`;
  $("#machine").innerHTML = 'For tools: <a href="data.json">data.json</a> (schema 1), <a href="history.json">history.json</a> and <a href="badge.json">badge.json</a>, a shields.io endpoint.';
  try {
    const h = await loadJSON("history.json");
    const rows = h.filter((x) => x.cells);
    $("#trend").innerHTML = lineChart(rows.map((x) => ({
      x: new Date(x.date), y: x.sliced ?? x.ok, label: `${when(x.date)}: ${x.sliced ?? x.ok} of ${x.cells} sliced`,
    })), { fmt: (v) => v.toFixed(0), title: "Cells sliced per night", max: Math.max(...rows.map((x) => x.cells)) });
  } catch {
    $("#trend").innerHTML = '<p class="fine">No history yet.</p>';
  }
}
main();
