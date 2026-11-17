// The recipe gallery page: search and filter over recipes/index.json.
import { initTheme } from "./theme.js";
import { card, loadIndex } from "./recipes.js";

const $ = (s) => document.querySelector(s);
initTheme($("#theme"));

const grid = $("#grid"), q = $("#q"), count = $("#count"), filter = $("#filter");
let all = [], mode = "all";

function render() {
  const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = all.filter((r) => (mode === "all" || (mode === "builtin") === r.builtin) &&
    words.every((w) => [r.title, r.summary, r.author, r.id, ...(r.tags || [])].join(" ").toLowerCase().includes(w)));
  grid.innerHTML = shown.length ? shown.map((r) => card(r, "../")).join("")
    : '<li class="empty">No recipe matches. <a href="https://github.com/kaizensx/form-studio/issues/new?template=3-recipe.yml">Request one</a>.</li>';
  count.textContent = `${shown.length} of ${all.length}`;
}

grid.innerHTML = Array.from({ length: 6 }, () => '<li class="skel" aria-hidden="true"></li>').join("");
loadIndex("../").then((d) => { all = d.recipes; render(); }, (e) => {
  grid.innerHTML = '<li class="empty">The recipe list could not be loaded. <a href="https://github.com/kaizensx/form-studio/tree/main/community/recipes">Browse it on GitHub</a>.</li>';
  console.error(e);
});
q.addEventListener("input", render);
filter.addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  mode = b.dataset.f;
  filter.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  render();
});
