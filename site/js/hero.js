// The hero instrument: part picker, parameter slider, readouts. The numbers work without WebGL;
// the 3D view (viewer.js + three.js, about 180 KB compressed) is loaded after first paint.
const $ = (s) => document.querySelector(s);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const still = new URLSearchParams(location.search).has("still");

const fmt = (n, d = 1) => n.toFixed(d);
const value = (p, st) => `${Number.isInteger(st.value) ? st.value : fmt(st.value)}${p.param.unit ? " " + p.param.unit : ""}`;

export async function start() {
  const stage = $("#stage"), scrub = $("#scrub"), ticks = $("#ticks"), radios = [...document.querySelectorAll("#parts [role=radio]")];
  const out = { label: $("#p-label"), value: $("#p-value"), size: $("#r-size"), vol: $("#r-vol"), tag: $("#r-tag"), count: $("#n-count"), build: $("#n-build") };
  const man = await fetch("assets/parts/parts.json").then((r) => r.json());
  const parts = Object.fromEntries(man.parts.map((p) => [p.id, p]));
  const bins = {};
  let part = parts.dock, step = part.start, viewer = null, shown = null, dragging = false, settleT = 0;

  function tag(kind) {
    out.tag.textContent = kind;
    out.tag.className = "tag " + (kind === "draft" ? "blueprint" : kind === "computed" ? "datum" : "plain");
  }

  function readout() {
    const st = part.steps[step];
    out.label.textContent = part.param.label;
    out.value.textContent = value(part, st);
    out.size.textContent = `${fmt(st.size[0])} × ${fmt(st.size[1])} × ${fmt(st.size[2])} mm`;
    out.vol.textContent = `${fmt(st.volume_cm3)} cm³`;
    out.build.textContent = `bed outline 180 × 180 mm · kernel build ${st.build_ms} ms · ${st.faces} faces`;
    scrub.setAttribute("aria-valuetext", `${part.param.label} ${value(part, st)}: ${out.size.textContent}, ${out.vol.textContent}`);
    [...ticks.children].forEach((t, i) => t.classList.toggle("on", i === step));
  }

  function layout() {
    scrub.max = part.steps.length - 1;
    scrub.value = step;
    ticks.replaceChildren(...part.steps.map(() => document.createElement("i")));
    out.count.textContent = `${part.steps.length} real builds`;
    readout();
  }

  async function bin(p) {
    return (bins[p.id] ||= fetch("assets/parts/" + p.bin).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(r.status)))));
  }

  async function show() {
    if (!viewer) return;
    if (shown !== part.id) {
      const want = part;
      if (!bins[want.id]) { out.tag.textContent = `loading ${(want.bytes / 1048576).toFixed(1)} MB`; out.tag.className = "tag plain"; }
      const buf = await bin(want);
      if (part !== want) return;                       // the visitor moved on while it loaded
      viewer.setPart(want, buf, step);
      shown = want.id;
      tag("computed");
    } else {
      viewer.setStep(step, dragging);
    }
  }

  function settle() {
    dragging = false;
    tag("computed");
    viewer && viewer.settle();
  }

  scrub.addEventListener("input", () => {
    step = +scrub.value;
    dragging = true;
    tag("draft");
    readout();
    show();
    clearTimeout(settleT);
    settleT = setTimeout(settle, 520);                 // keyboard steps have no pointerup; a draft settles by itself
  });
  scrub.addEventListener("change", () => { clearTimeout(settleT); settleT = setTimeout(settle, 160); });

  function pick(id, focus) {
    part = parts[id];
    step = part.start;
    radios.forEach((r) => {
      const on = r.dataset.part === id;
      r.setAttribute("aria-checked", on);
      r.tabIndex = on ? 0 : -1;
      if (on && focus) r.focus();
    });
    layout();
    show();
  }
  radios.forEach((r, i) => {
    r.addEventListener("click", () => pick(r.dataset.part));
    r.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!d) return;
      e.preventDefault();
      pick(radios[(i + d + radios.length) % radios.length].dataset.part, true);
    });
  });

  layout();

  // 3D: only when WebGL is there. Otherwise the poster stays and the numbers still follow the slider.
  const probe = document.createElement("canvas");
  if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) {
    $("#bench-note").append(Object.assign(document.createElement("span"), { textContent: "This browser has no WebGL, so the picture is a still." }));
    return;
  }
  try {
    const [{ create }, buf] = await Promise.all([import("./viewer.js"), bin(part)]);
    viewer = create({ canvas: $("#view"), labels: $("#dims"), reduce, still });
    viewer.setPart(part, buf, step);
    shown = part.id;
    requestAnimationFrame(() => requestAnimationFrame(() => stage.classList.add("live")));
    if (still) window.__viewer = viewer;
  } catch (e) {
    console.warn("3D view unavailable", e);
  }
}
