// Form Studio website. Plain modules, no build step, no third-party requests.
import { reducedMotion } from "./data.js";

const $ = (s) => document.querySelector(s);

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
