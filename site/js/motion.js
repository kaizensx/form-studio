// Scroll-driven motion with no library: one requestAnimationFrame loop that reads where each registered element is,
// eases a smoothed progress towards it, and hands it to a draw function. Nothing runs while nothing moves.
// With reduced motion the progress follows the scroll exactly (no easing), and reveals only fade.
import { reducedMotion } from "./data.js";

const RM = reducedMotion();
const items = [];
let raf = 0, last = 0;

export const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const easeOut = (t) => 1 - Math.pow(1 - t, 3);
export const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const expoOut = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
// a sub-range of a progress, as its own 0..1
export const span = (p, a, b) => clamp((p - a) / (b - a));

// where an element is: "pin" for a tall track holding a sticky child (0 when its top reaches the top of the
// viewport, 1 when its bottom reaches the bottom), "pass" for an element crossing the viewport, "page" for scrollY
function measure(it) {
  if (it.mode === "page") return clamp(scrollY / it.over());
  const r = it.el.getBoundingClientRect(), vh = innerHeight;
  it.near = r.bottom > -vh * 0.5 && r.top < vh * 1.5;
  if (it.mode === "pin") return clamp(-r.top / Math.max(1, r.height - vh));
  return clamp((vh - r.top) / (vh + r.height));
}

function frame(now) {
  raf = 0;
  const dt = Math.min(0.064, (now - (last || now)) / 1000); last = now;
  let moving = false;
  for (const it of items) {
    const target = measure(it);
    if (it.cur === null || RM) it.cur = target;
    else {
      it.cur += (target - it.cur) * (1 - Math.exp(-dt * it.smooth));
      if (Math.abs(target - it.cur) < 0.0004) it.cur = target; else moving = true;
    }
    if (it.cur !== it.drawn && (it.near !== false || it.drawn === undefined)) { it.drawn = it.cur; it.fn(it.cur); }
  }
  if (moving) kick(); else last = 0;
}
export function kick() { if (!raf) raf = requestAnimationFrame(frame); }
addEventListener("scroll", kick, { passive: true });
addEventListener("resize", () => { items.forEach((it) => (it.drawn = undefined)); kick(); });

// register: fn(progress) is called whenever the smoothed progress changes
export function scrub(el, fn, { mode = "pin", smooth = 10, over = () => innerHeight } = {}) {
  if (!el && mode !== "page") return;
  const it = { el, fn, mode, smooth, over, cur: null, drawn: undefined };
  items.push(it); kick();
  return { redraw: () => { it.drawn = undefined; kick(); } };
}

// reveals: .rv elements fade and rise once, as they come into view; siblings follow one another by 80 ms
export function reveals(root = document) {
  const els = [...root.querySelectorAll(".rv")];
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in"); io.unobserve(e.target);
  }), { rootMargin: "0px 0px -10% 0px", threshold: 0.12 });
  els.forEach((el) => {
    if (!el.style.getPropertyValue("--d")) {
      const sib = [...el.parentElement.children].filter((c) => c.classList.contains("rv"));
      const i = sib.indexOf(el);
      if (i > 0) el.style.setProperty("--d", `${Math.min(i, 4) * 80}ms`);
    }
    io.observe(el);
  });
}

// a number that counts up once, when it comes into view
export function countUp(el, to, { ms = 1400, fmt = (v) => String(Math.round(v)) } = {}) {
  if (!el) return;
  if (RM) { el.textContent = fmt(to); return; }
  el.textContent = fmt(0);
  const io = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return; io.disconnect();
    const t0 = performance.now();
    const step = (now) => { const k = clamp((now - t0) / ms); el.textContent = fmt(to * expoOut(k)); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }, { threshold: 0.6 });
  io.observe(el);
}

export const reduced = RM;
