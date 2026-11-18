// Form Studio website, home page. Plain modules, no build step, no third-party requests.
import "./nav.js";
import { siteData } from "./data.js";
import { scrub, reveals, countUp, easeOut, reduced } from "./motion.js";

const $ = (s) => document.querySelector(s);

// ---------- hero: the drawn window lies back on the bench, then stands up as the page scrolls ----------
{
  const tilt = $("#stage-tilt"), copy = $("#hero-copy"), par = [...document.querySelectorAll("[data-par]")];
  if (tilt && !reduced) {
    const narrow = () => innerWidth < 900;
    scrub(null, (q) => {
      const e = easeOut(q), t = narrow() ? 9 : 16;
      tilt.style.setProperty("--tilt", `${(t * (1 - e)).toFixed(3)}deg`);
      tilt.style.setProperty("--sc", (0.94 + 0.06 * e).toFixed(4));
      tilt.style.setProperty("--ty", `${(-24 * e).toFixed(2)}px`);
      const y = scrollY;
      copy.style.transform = `translateY(${(y * 0.28).toFixed(1)}px)`;
      copy.style.opacity = String(Math.max(0, 1 - y / (innerHeight * 0.75)).toFixed(3));
      par.forEach((el) => { el.style.translate = `0 ${(y * +el.dataset.par).toFixed(1)}px`; });
    }, { mode: "page", smooth: 12, over: () => innerHeight * 0.7 });
  }
}

reveals();

// ---------- why: the numbers are the sample project's, counted up as they arrive ----------
siteData().then(({ dock: d }) => {
  countUp($("#why-faces"), d.faces);
  countUp($("#why-checks"), d.checks.length);
  $("#why-faces2").textContent = `a ${d.faces}-face solid`;
  $("#why-ms").textContent = `${d.build_ms} ms`;
});
countUp($("#why-tools"), +$("#why-tools").dataset.count);     // docs/MCP.md: N tools (site/tools/check_site.py keeps it in step)

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
  const { initHero } = await import("./app.js");
  try { await initHero(); } catch (e) { console.error(e); }
  near($("#how-track"), () => import("./how.js").then((m) => m.initHow()).catch(console.error));
  near($("#moves-track"), () => import("./moves.js").then((m) => m.initMoves()).catch(console.error));
})();
