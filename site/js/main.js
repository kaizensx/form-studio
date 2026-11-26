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

// ---------- before and after: a range input moves the divider ----------
document.querySelectorAll(".ba-frame").forEach((f) => {
  const r = f.querySelector("input");
  const set = () => f.style.setProperty("--p", `${r.value}%`);
  r.addEventListener("input", set); set();
});

reveals();

// ---------- the proof sheet: one real run in three moments. It plays once when it arrives; a click takes over ----------
{
  const win = $("#proof-win");
  if (win) {
    const tabs = [...win.querySelectorAll(".pf-tabs button")], rev = $("#pf-rev"), order = tabs.map((b) => b.dataset.at);
    let timer = 0;
    const show = (k) => {
      win.dataset.at = k;
      tabs.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.at === k)));
      if (rev) rev.textContent = k === "brief" ? "brief" : k;
    };
    const stop = () => { clearTimeout(timer); win.classList.remove("pf-play"); };
    tabs.forEach((b) => b.addEventListener("click", () => { stop(); show(b.dataset.at); }));
    if (!reduced) {
      const dwell = 3400;
      win.style.setProperty("--dwell", `${dwell}ms`);
      show(order[0]);
      const io = new IntersectionObserver(([e]) => {
        if (!e.isIntersecting) return; io.disconnect();
        win.classList.add("pf-play");
        const step = (i) => { show(order[i]); if (i < order.length - 1) timer = setTimeout(() => step(i + 1), dwell); else timer = setTimeout(stop, dwell); };
        step(0);
      }, { threshold: 0.55 });
      io.observe(win);
    }
  }
}

// ---------- your agent: the numbers count up as they arrive ----------
countUp($("#why-tools"), +$("#why-tools").dataset.count);     // docs/MCP.md: N tools (site/tools/check_site.py keeps it in step)
countUp($("#why-skills"), +$("#why-skills").dataset.count);   // plugins/form/skills: one folder per skill

// the terminal session plays once when it comes into view: each command types, then its real output follows.
// Without script, or with reduced motion, the whole session is simply there; the lines keep their room either way.
{
  const term = $("#term");
  if (term && !reduced) {
    const lines = [...term.querySelectorAll(".ln")];
    term.classList.add("play");
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return; io.disconnect();
      let t = 250;
      const at = (ms, fn) => setTimeout(fn, ms);
      for (const ln of lines) {
        const tx = ln.querySelector(".tx");
        if (tx) {
          const full = tx.textContent;
          at(t, () => { tx.textContent = ""; ln.classList.add("on", "typing"); });
          for (let i = 1; i <= full.length; i++) at(t + 120 + i * 26, () => { tx.textContent = full.slice(0, i); });
          t += 120 + full.length * 26 + 260;
          at(t, () => ln.classList.remove("typing"));
          t += 120;
        } else {
          at(t, () => ln.classList.add("on"));
          t += 45;
        }
      }
      at(t + 600, () => term.classList.remove("play"));
    }, { threshold: 0.45 });
    io.observe(term);
  }
}

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
  near($("#try"), () => import("./desk.js").then((m) => m.initDesk()).catch(console.error));
  near($("#recon"), () => import("./recon.js").then((m) => m.initRecon()).catch(console.error));
  near($("#how-track"), () => import("./how.js").then((m) => m.initHow()).catch(console.error));
  near($("#moves-track"), () => import("./moves.js").then((m) => m.initMoves()).catch(console.error));
})();
