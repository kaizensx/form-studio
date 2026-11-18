// Shared by /compat/ and /bench/: fetch CI data published next to the page, escape it, and draw small line charts.

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export async function loadJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

export function ago(iso) {
  const t = Date.parse(iso);
  if (!t) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

export const when = (iso) => {
  const t = new Date(iso);
  return isNaN(t) ? "" : t.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};

export function tile(value, unit, label, delta) {
  return `<div class="ci-tile"><span class="v">${esc(value)}${unit ? `<small>${esc(unit)}</small>` : ""}</span>` +
    `<span class="k">${esc(label)}</span>${delta || ""}</div>`;
}

const nice = (v) => {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v)), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
};

// points: [{x: Date|number, y: number, label?: string, href?: string}]
export function lineChart(points, { fmt = (v) => v.toFixed(1), height = 150, zero = true, title = "", max, width = 560 } = {}) {
  const pts = points.filter((p) => Number.isFinite(p.y));
  if (pts.length === 0) return '<p class="fine">No data yet.</p>';
  const W = width, H = height, L = 44, R = 8, T = 10, B = 22;
  const xs = pts.map((p, i) => i);
  const ymax = Number.isFinite(max) ? max : nice(Math.max(...pts.map((p) => p.y)) * 1.1);
  const ymin = zero ? 0 : Math.min(...pts.map((p) => p.y)) * 0.9;
  const sx = (i) => L + (pts.length === 1 ? (W - L - R) / 2 : (i / (pts.length - 1)) * (W - L - R));
  const sy = (v) => T + (1 - (v - ymin) / (ymax - ymin || 1)) * (H - T - B);
  const ticks = [0, 0.5, 1].map((f) => ymin + f * (ymax - ymin));
  const grid = ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${sy(v)}" y2="${sy(v)}"/><text x="${L - 6}" y="${sy(v) + 3}" text-anchor="end">${esc(fmt(v))}</text>`).join("");
  const d = xs.map((i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(pts[i].y).toFixed(1)}`).join("");
  const area = `${d}L${sx(xs.length - 1).toFixed(1)},${sy(ymin)}L${sx(0).toFixed(1)},${sy(ymin)}Z`;
  const first = pts[0].x instanceof Date ? pts[0].x.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
  const last = pts.at(-1).x instanceof Date ? pts.at(-1).x.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
  const showPts = pts.length <= 60;
  const dots = pts.map((p, i) => {
    const c = `<circle class="pt" cx="${sx(i).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${showPts ? 3 : 0}"><title>${esc(p.label || fmt(p.y))}</title></circle>`;
    return p.href ? `<a href="${esc(p.href)}" aria-label="${esc(p.label || fmt(p.y))}">${c}</a>` : c;
  }).join("");
  return `<svg class="ci-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">` +
    `<g class="grid">${grid}</g><path class="area" d="${area}"/><path class="line" d="${d}"/>${dots}` +
    `<g class="axis"><text x="${L}" y="${H - 6}">${esc(first)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${esc(last)}</text></g></svg>`;
}
