// Recipe cards from recipes/index.json: the index the app's community browser reads (site/tools/build_recipe_index.py).

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const REPO = "https://github.com/kaizensx/form-studio";

let index;
export const loadIndex = (base) => (index ||= fetch(`${base}recipes/index.json`).then((r) => {
  if (!r.ok) throw new Error(`recipes/index.json: ${r.status}`);
  return r.json();
}));

// The preview as served next to this page (same origin); the index carries absolute URLs for the app.
const localPreview = (r, base) => r.preview ? base + "recipes/previews/" + r.preview.split("/recipes/previews/")[1] : "";

export function card(r, base) {
  const src = r.builtin ? `${REPO}/blob/main/form/recipes/${r.id}.py` : `${REPO}/tree/main/community/recipes/${r.id}`;
  const pic = localPreview(r, base);
  return `<li><a class="rcard" href="${src}" data-id="${esc(r.id)}">
    <div class="pic">${pic ? `<img src="${esc(pic)}" width="960" height="560" loading="lazy" decoding="async" alt="${esc(r.title)}, rendered by Form Studio's engine with its default values">` : ""}</div>
    <div class="body">
      <div class="t"><b>${esc(r.title)}</b><span class="chip ${r.builtin ? "c-datum" : ""}">${r.builtin ? "Built in" : "Community"}</span></div>
      <p>${esc(r.summary)}</p>
      <div class="meta"><span class="chip">${r.params_count ?? "?"} parameters</span><span class="chip">${r.kind === "scad" ? "OpenSCAD" : "Python"}</span>${r.builtin ? "" : `<span class="chip">by ${esc(r.author)}</span>`}</div>
    </div></a></li>`;
}

export async function initRecipeCards(list, { limit = 0, base = "" } = {}) {
  if (!list) return;
  list.innerHTML = Array.from({ length: limit || 6 }, () => '<li class="skel" aria-hidden="true"></li>').join("");
  try {
    const { recipes } = await loadIndex(base);
    // a teaser shows the community's recipes first, then fills up with built-in ones
    const shown = limit ? [...recipes.filter((r) => !r.builtin).slice(0, 2), ...recipes.filter((r) => r.builtin)].slice(0, limit) : recipes;
    list.innerHTML = shown.map((r) => card(r, base)).join("");
  } catch (e) {
    list.innerHTML = `<li class="empty">The recipe list could not be loaded. <a href="${REPO}/tree/main/community/recipes">Browse it on GitHub</a>.</li>`;
    console.error(e);
  }
}
