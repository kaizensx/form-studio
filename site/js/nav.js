// The top bar every page shares (written by site/tools/chrome.py): theme, the compact menu, the scroll progress.
// Importing this module sets it up once.
import { initTheme } from "./theme.js";

const nav = document.getElementById("nav");
if (nav && !nav.dataset.ready) {
  nav.dataset.ready = "1";
  initTheme(document.getElementById("theme"));

  // a little more surface once the page has moved under it
  let queued = false;
  const bar = document.getElementById("scroll-bar");
  const draw = () => {
    queued = false;
    nav.classList.toggle("scrolled", scrollY > 8);
    if (bar) { const h = document.documentElement.scrollHeight - innerHeight; bar.style.setProperty("--p", h > 0 ? Math.min(1, scrollY / h).toFixed(4) : 0); }
  };
  addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(draw); } }, { passive: true });
  draw();

  // a group in the bar (3D printing): hover or focus opens it; a click or tap keeps it open until you leave it
  const groups = [...nav.querySelectorAll(".grp-btn")];
  const closeGroups = (except) => groups.forEach((b) => { if (b !== except) b.setAttribute("aria-expanded", "false"); });
  groups.forEach((b) => b.addEventListener("click", () => {
    const open = b.getAttribute("aria-expanded") !== "true";
    closeGroups(b);
    b.setAttribute("aria-expanded", String(open));
  }));
  document.addEventListener("click", (e) => { if (!e.target.closest(".grp")) closeGroups(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = groups.find((b) => b.getAttribute("aria-expanded") === "true" || b.parentElement.contains(document.activeElement));
    closeGroups();
    if (open) { open.focus(); open.blur(); }
  });

  // the compact menu: below 900 px the links live in a sheet under the bar
  const btn = document.getElementById("menu-btn"), menu = document.getElementById("menu");
  if (btn && menu) {
    const set = (open) => {
      btn.setAttribute("aria-expanded", String(open));
      nav.classList.toggle("open", open);
      document.documentElement.style.overflow = open ? "hidden" : "";
      if (open) { menu.hidden = false; requestAnimationFrame(() => menu.classList.add("on")); }
      else { menu.classList.remove("on"); setTimeout(() => { if (!nav.classList.contains("open")) menu.hidden = true; }, 260); }
    };
    btn.addEventListener("click", () => set(btn.getAttribute("aria-expanded") !== "true"));
    menu.addEventListener("click", (e) => { if (e.target.closest("a")) set(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && nav.classList.contains("open")) { set(false); btn.focus(); } });
    matchMedia("(min-width: 900px)").addEventListener("change", (e) => { if (e.matches) set(false); });
  }
}
