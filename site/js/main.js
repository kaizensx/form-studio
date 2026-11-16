// FORM site. Plain modules, no build step, no third-party requests except GitHub's public release API.
// Reveal styles only apply once this module is running, so a failed script never hides content.
document.documentElement.classList.add("js");
const reduce = matchMedia("(prefers-reduced-motion: reduce)");
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ---- nav hairline once the page has scrolled
const nav = $("#nav");
if (nav) {
  const onScroll = () => nav.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

// ---- reveals, dimension lines that draw themselves, numbers that settle
const GLYPHS = "0123456789";
function settle(el) {
  const node = [...el.childNodes].find((n) => n.nodeType === 3 && n.nodeValue.trim());
  if (!node || reduce.matches) return;
  const final = node.nodeValue;
  const t0 = performance.now(), dur = 420;
  const tick = (now) => {
    const k = Math.min(1, (now - t0) / dur);
    const fixed = Math.floor(k * final.length);
    node.nodeValue = [...final].map((ch, i) => (i < fixed || !/\d/.test(ch) ? ch : GLYPHS[(Math.random() * 10) | 0])).join("");
    if (k < 1) requestAnimationFrame(tick); else node.nodeValue = final;
  };
  requestAnimationFrame(tick);
}
if ("IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("in");
      $$(".dim.draw", e.target).forEach((d) => d.classList.add("in"));
      if (e.target.matches(".dim.draw")) e.target.classList.add("in");
      const s = e.target.matches("[data-settle]") ? e.target : $("[data-settle]", e.target);
      if (s) settle(s);
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  $$(".reveal, .dim.draw").forEach((el) => io.observe(el));
} else {
  $$(".reveal, .dim.draw").forEach((el) => el.classList.add("in"));
}

// ---- tabs (pipeline strip, terminal). Arrow keys move, as the ARIA tabs pattern expects.
function tabs(list, onChange) {
  if (!list) return;
  const btns = $$('[role="tab"]', list);
  const select = (btn, focus) => {
    btns.forEach((b) => {
      const on = b === btn;
      b.setAttribute("aria-selected", on);
      b.tabIndex = on ? 0 : -1;
      const panel = document.getElementById(b.getAttribute("aria-controls"));
      if (panel) {
        panel.hidden = !on;
        if (on) { panel.classList.remove("swap"); void panel.offsetWidth; panel.classList.add("swap"); }
      }
    });
    if (focus) btn.focus();
    if (btn.scrollIntoView && list.scrollWidth > list.clientWidth) btn.scrollIntoView({ block: "nearest", inline: "center", behavior: reduce.matches ? "auto" : "smooth" });
    onChange && onChange(btn, btns);
  };
  btns.forEach((b, i) => {
    b.addEventListener("click", () => select(b));
    b.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: btns.length - 1 - i }[e.key];
      if (d === undefined) return;
      e.preventDefault();
      select(btns[(i + d + btns.length) % btns.length], true);
    });
  });
}
tabs($("#pipe-tabs"), (btn, btns) => {
  const at = btns.indexOf(btn);
  btns.forEach((b, i) => b.classList.toggle("done", i < at));   // everything upstream of the open node is done
});
tabs($("#term-tabs"), (btn) => {
  const copy = $(".term .copy-btn");
  if (copy) copy.hidden = btn.id !== "tt-cli";
});

// ---- copy buttons
$$("[data-copy]").forEach((b) => {
  const label = b.textContent;
  b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(b.dataset.copy);
      b.textContent = "Copied"; b.classList.add("ok");
    } catch { b.textContent = "Select and copy"; }
    setTimeout(() => { b.textContent = label; b.classList.remove("ok"); }, 1600);
  });
});

// ---- downloads: mark the visitor's system, then ask GitHub for the latest published release
const dl = $("#downloads");
if (dl) {
  const ua = navigator.userAgent, plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  let os = null;
  if (/Win/i.test(plat) || /Windows/i.test(ua)) os = "win";
  else if (/Mac/i.test(plat) || /Macintosh/i.test(ua)) os = "mac-arm";   // a browser cannot tell Apple Silicon from Intel reliably
  else if (/Linux/i.test(plat) && !/Android/i.test(ua)) os = "linux";
  const mine = os && $(`.dl[data-os="${os}"]`, dl);
  if (mine) mine.classList.add("you");

  const status = $("#rel-text");
  const mb = (n) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(n / 1048576) + "\u00a0MB";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  fetch("https://api.github.com/repos/kaizensx/form-studio/releases?per_page=10", { signal: ctl.signal, headers: { Accept: "application/vnd.github+json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
    .then((list) => {
      const rel = list.find((r) => !r.draft && !r.prerelease && r.assets && r.assets.length) || list.find((r) => !r.draft && r.assets && r.assets.length);
      if (!rel) {
        status.textContent = "No release is published yet. Bundles from every push are on the Desktop app workflow page (GitHub sign-in needed).";
        return;
      }
      let n = 0;
      $$(".dl", dl).forEach((a) => {
        const asset = rel.assets.find((x) => x.name === a.dataset.asset);
        if (!asset) return;
        a.href = asset.browser_download_url;
        $("[data-go]", a).textContent = `Download · ${mb(asset.size)}`;
        n++;
      });
      const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(rel.published_at));
      status.innerHTML = "";
      status.append(`Latest release: `);
      const v = document.createElement("span"); v.className = "num"; v.textContent = `${rel.tag_name} · ${date}`;
      status.append(v, n ? "" : " (no app bundles attached; see the releases page)");
    })
    .catch(() => { /* offline or rate-limited: the cards already link to the releases page */ })
    .finally(() => clearTimeout(timer));
}

// ---- hero: wire the instrument now, load the 3D viewer when the browser is idle
if ($("#stage")) {
  const start = () => import("./hero.js").then((m) => m.start()).catch((e) => console.warn("hero", e));
  if ("requestIdleCallback" in window) requestIdleCallback(start, { timeout: 1500 }); else setTimeout(start, 200);
}
