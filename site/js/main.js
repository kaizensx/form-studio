// Form Studio website, home page. Plain modules, no build step, no third-party requests.
import "./nav.js";
import { siteData } from "./data.js";
import { scrub, reveals, countUp, easeOut, reduced } from "./motion.js";

const $ = (s) => document.querySelector(s);

// ---------- hero: the photograph settles as the page scrolls; the drawn window stands up as it arrives ----------
{
  const shot = $("#hero-shot img"), copy = $("#hero-copy"), par = [...document.querySelectorAll("[data-par]")];
  if (shot && !reduced) {
    scrub(null, (q) => {
      const e = easeOut(q), y = scrollY;
      shot.style.setProperty("--hs", (1.08 - 0.08 * e).toFixed(4));
      shot.style.setProperty("--hy", `${(18 * e).toFixed(2)}px`);
      copy.style.transform = `translateY(${(y * 0.2).toFixed(1)}px)`;
      copy.style.opacity = String(Math.max(0, 1 - y / (innerHeight * 0.8)).toFixed(3));
      par.forEach((el) => { el.style.translate = `0 ${(y * +el.dataset.par).toFixed(1)}px`; });
    }, { mode: "page", smooth: 12, over: () => innerHeight * 0.9 });
  } else if (shot) shot.style.setProperty("--hs", "1");
  const tilt = $("#stage-tilt");
  if (tilt && !reduced) {
    scrub($("#try"), (q) => {
      const e = easeOut(Math.min(1, q / 0.42)), t = innerWidth < 900 ? 8 : 14;
      tilt.style.setProperty("--tilt", `${(t * (1 - e)).toFixed(3)}deg`);
      tilt.style.setProperty("--sc", (0.94 + 0.06 * e).toFixed(4));
    }, { mode: "pass", smooth: 12 });
  }
}

// ---------- before and after: a range input moves the divider ----------
document.querySelectorAll(".ba-frame").forEach((f) => {
  const r = f.querySelector("input");
  const set = () => f.style.setProperty("--p", `${r.value}%`);
  r.addEventListener("input", set); set();
});

reveals();

// ---------- your agent: the numbers count up as they arrive ----------
countUp($("#why-tools"), +$("#why-tools").dataset.count);     // docs/MCP.md: N tools (site/tools/check_site.py keeps it in step)
countUp($("#why-skills"), +$("#why-skills").dataset.count);   // plugins/form/skills: one folder per skill

// a soft light follows the pointer over the cards
document.addEventListener("pointermove", (e) => {
  const c = e.target.closest && e.target.closest(".why-grid article");
  if (!c) return;
  const r = c.getBoundingClientRect();
  c.style.setProperty("--mx", `${e.clientX - r.left}px`);
  c.style.setProperty("--my", `${e.clientY - r.top}px`);
}, { passive: true });

// ---------- downloads: point the hero button at the visitor's system ----------
{
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
}

// ---------- the drawn app: the hero window first, then the pinned scenes as they come near ----------
const near = (el, fn) => {
  if (!el) return;
  const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: "120% 0px" });
  io.observe(el);
};
(async () => {
  near($("#try"), () => import("./app.js").then((m) => m.initHero()).catch(console.error));
  near($("#how-track"), () => import("./how.js").then((m) => m.initHow()).catch(console.error));
  near($("#moves-track"), () => import("./moves.js").then((m) => m.initMoves()).catch(console.error));
})();
