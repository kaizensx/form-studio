// Form Studio website. Plain modules, no build step, no third-party requests.
import { reducedMotion } from "./data.js";
import { initTheme } from "./theme.js";
import { initRecipeCards } from "./recipes.js";

const $ = (s) => document.querySelector(s);

initTheme($("#theme"));

// nav: a surface only once the page has scrolled under it
const nav = $("#nav");
const onScroll = () => nav.classList.toggle("scrolled", scrollY > 8);
addEventListener("scroll", onScroll, { passive: true }); onScroll();

// scroll reveals: everything is visible without JS; only what starts below the fold is hidden, then revealed once
const rv = [...document.querySelectorAll(".rv")];
{
  const below = rv.filter((el) => el.getBoundingClientRect().top > innerHeight * 0.92);
  below.forEach((el) => el.classList.add("pre"));
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.classList.remove("pre"); io.unobserve(e.target);
  }), { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  below.forEach((el, i) => { el.style.setProperty("--d", (el.classList.contains("sec-head") ? 0 : 70) + "ms"); io.observe(el); });
}

// downloads: point the hero button at the visitor's system
const ua = navigator.userAgent, plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
const os = /Win/i.test(plat + ua) ? "win" : /Linux|X11/i.test(plat) && !/Android/i.test(ua) ? "linux" : /Mac/i.test(plat + ua) && !/iPhone|iPad/i.test(ua) ? "mac" : "";
(async () => {
  let key = os;
  if (os === "mac") {
    key = "mac-arm";
    try { const h = await navigator.userAgentData?.getHighEntropyValues?.(["architecture"]); if (h && h.architecture === "x86") key = "mac-intel"; } catch { /* Safari: Apple Silicon is the default */ }
  }
  const card = key && document.querySelector(`#dl a[data-os="${key}"]`);
  if (!card) return;
  card.classList.add("yours");
  const cta = $("#cta-dl");
  cta.href = card.href;
  cta.querySelector("span:last-child").textContent = { "mac-arm": "Download for macOS", "mac-intel": "Download for macOS (Intel)", win: "Download for Windows", linux: "Download for Linux" }[key];
})();

// tour: real screenshots; tabs advance on their own until the visitor picks one
{
  const box = $("#tour-box");
  if (box) {
    const tabs = [...box.querySelectorAll('[role="tab"]')], figs = [...box.querySelectorAll("figure")];
    tabs.forEach((t) => t.insertAdjacentHTML("beforeend", "<i></i>"));
    let cur = 0, auto = !reducedMotion(), t0 = 0, seen = false, hold = false, last = 0;
    const load = (i) => { const im = figs[i] && figs[i].querySelector("img[data-src]"); if (im) { im.src = im.dataset.src; im.removeAttribute("data-src"); } };
    const show = (i, focus) => {
      cur = (i + tabs.length) % tabs.length;
      load(cur); load(cur + 1);
      tabs.forEach((t, k) => { const on = k === cur; t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1; t.style.setProperty("--t", 0); });
      figs.forEach((f, k) => f.classList.toggle("on", k === cur));
      if (focus) tabs[cur].focus();
      t0 = performance.now();
    };
    const DUR = 5200;
    const tick = (now) => {
      if (hold || !seen) t0 += now - (last || now);                 // paused while the pointer rests on it, or off screen
      last = now;
      if (auto && seen && !hold) {
        const p = Math.min(1, (now - t0) / DUR);
        tabs[cur].style.setProperty("--t", p);
        if (p >= 1) show(cur + 1);
      }
      requestAnimationFrame(tick);
    };
    const stop = () => { auto = false; tabs.forEach((t) => t.style.setProperty("--t", 0)); };
    box.querySelector('[role="tablist"]').addEventListener("click", (e) => { const b = e.target.closest('[role="tab"]'); if (!b) return; stop(); show(tabs.indexOf(b)); });
    box.querySelector('[role="tablist"]').addEventListener("keydown", (e) => {
      const d = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
      if (d) { e.preventDefault(); stop(); show(cur + d, true); }
    });
    box.addEventListener("pointerenter", () => { hold = true; });
    box.addEventListener("pointerleave", () => { hold = false; });
    new IntersectionObserver((es) => es.forEach((e) => { seen = e.isIntersecting; }), { threshold: 0.35 }).observe(box);
    requestAnimationFrame(tick);
  }
}

// recipes: the same index the app reads
initRecipeCards($("#recipe-teaser"), { limit: 8, base: "" });

// the hero first, then each demo as it comes near
const boot = async () => {
  const { initHero } = await import("./app.js");
  try { await initHero(); } catch (e) { console.error(e); }
  const D = await import("./demos.js");
  D.whenNear($("#fit-demo"), D.initFit);
  D.whenNear($("#checks-demo"), D.initChecks);
  D.whenNear($("#print-demo"), D.initPrint);
  D.whenNear($("#asm-demo"), D.initAssembly);
  D.whenNear($("#ag-list"), D.initWorks);
  D.whenNear($("#term"), D.initTerminal);
};
boot();
