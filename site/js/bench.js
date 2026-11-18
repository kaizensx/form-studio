// /bench/: build, check, slice and start-up times over time (data.json, copied from the ci-assets branch at deploy).
import "./nav.js";
import { ago, esc, lineChart, loadJSON, tile, when } from "./cidata.js";

const $ = (s) => document.querySelector(s);

const REPO = "https://github.com/kaizensx/form-studio/commit/";
const sec = (v) => (Number.isFinite(v) ? (v < 10 ? v.toFixed(2) : v.toFixed(1)) : "—");
const median = (xs) => {
  const v = xs.filter(Number.isFinite).sort((a, b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)] : NaN;
};

// change of the newest value against the median of the five runs before it
function delta(hist, get) {
  const last = get(hist.at(-1));
  const base = median(hist.slice(-6, -1).map(get));
  if (!Number.isFinite(last) || !Number.isFinite(base) || !base) return "";
  const pct = ((last - base) / base) * 100;
  const cls = pct > 5 ? "up" : pct < -5 ? "down" : "";
  return `<span class="d ${cls}">${pct >= 0 ? "+" : ""}${pct.toFixed(0)}% vs. the 5 runs before</span>`;
}

function card(title, hist, get, unit = "s") {
  const pts = hist.map((h) => ({
    x: new Date(h.date), y: get(h), href: h.commit ? REPO + h.commit : undefined,
    label: `${when(h.date)} · ${sec(get(h))} ${unit} · ${(h.subject || "").slice(0, 70)}`,
  }));
  const last = get(hist.at(-1));
  return `<div class="ci-card"><h3>${esc(title)}<span>${esc(sec(last))} ${esc(unit)}</span></h3>` +
    lineChart(pts, { fmt: (v) => sec(v), title, width: 320, height: 140 }) + "</div>";
}

async function main() {
  let hist;
  try {
    hist = (await loadJSON("data.json")).filter((h) => h && h.recipes);
  } catch {
    hist = [];
  }
  if (!hist.length) {
    $("#stamp").textContent = "";
    $("#charts").innerHTML = '<div class="ci-empty">The first benchmark run has not been published yet.</div>';
    return;
  }
  const last = hist.at(-1);
  $("#stamp").innerHTML = `Latest ${esc(when(last.date))} (${esc(ago(last.date))}) · ` +
    (last.commit ? `<a href="${REPO}${esc(last.commit)}">${esc(last.commit.slice(0, 7))}</a> ` : "") +
    esc((last.subject || "").slice(0, 90)) + ` · ${hist.length} runs`;
  const T = (k) => (h) => (h.totals || {})[k];
  const A = (k) => (h) => (h.app || {})[k];
  $("#tiles").innerHTML = [
    tile(sec(A("warm_s")(last)), "s", "app start (interface and CAD kernel ready)", delta(hist, A("warm_s"))),
    tile(sec(T("pipeline_s")(last)), "s", `every built-in recipe through the pipeline`, delta(hist, T("pipeline_s"))),
    tile(sec(T("geometry_s")(last)), "s", "building the solids", delta(hist, T("geometry_s"))),
    tile(sec(T("slice_s")(last)), "s", `slicing${last.slicer && last.slicer.name ? " with " + last.slicer.name : ""}`, delta(hist, T("slice_s"))),
  ].join("");
  $("#charts").innerHTML = [
    card("App start, warm", hist, A("warm_s")),
    card("App start, cold", hist, A("cold_s")),
    card("Whole pipeline, all recipes", hist, T("pipeline_s")),
    card("Building the solids", hist, T("geometry_s")),
    card("Checks", hist, T("checks_s")),
    card("Slicing", hist, T("slice_s")),
  ].join("");
  const ids = Object.keys(last.recipes).sort();
  const cols = [["geometry_s", "Build"], ["exports_s", "STEP + STL"], ["checks_s", "Checks"], ["slice_s", "Slice"], ["pipeline_s", "Pipeline"]];
  $("#recipes").innerHTML = `<thead><tr><th scope="col">Recipe</th>${cols.map(([, l]) => `<th scope="col">${l}</th>`).join("")}<th scope="col">Pipeline trend</th></tr></thead><tbody>` +
    ids.map((id) => {
      const r = last.recipes[id];
      const d = delta(hist, (h) => ((h.recipes || {})[id] || {}).pipeline_s).replace(" vs. the 5 runs before", "");
      return `<tr><th scope="row">${esc(id.replace(/_/g, " "))}</th>${cols.map(([k]) => `<td>${sec(r[k])} s</td>`).join("")}<td>${d || "—"}</td></tr>`;
    }).join("") + "</tbody>";
  $("#machine").innerHTML = 'For tools: <a href="data.json">data.json</a>, every run with its commit (schema 1).';
}
main();
