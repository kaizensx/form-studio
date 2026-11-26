// Direction C, "Atelier": a notebook beside a gallery. Warm, editorial, serif titles; the part is shown like an object in a monograph.
const S = document.body.dataset.screen, D = DATA;
const nn = (i) => String(i).padStart(2, "0");
const words = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];

const head = () => `<header class="bar">${LOGO(15)}<span class="sp"></span><span class="ib">${I("search", 16)}</span><span class="ib">${I("gear", 16)}</span></header>`;
const chapters = (list) => `<nav class="chapters">${list.map(([n, name, sub, st]) => `<div class="${st === "on" ? "on" : ""}"><span class="mono">${n}</span><b>${name}</b><em class="${st}">${sub}</em></div>`).join("")}</nav>`;
function features(step) {
  return `<section class="features"><h2>Features <em>in build order</em><span class="mono">13</span></h2>${D.features.map(([name, tag], i) => {
    const st = step ? (i + 1 < step ? "done" : i + 1 === step ? "now" : "todo") : "";
    return `<div class="f ${st}"><i class="num">${i + 1}</i><b>${name}</b>${st === "done" ? I("check", 14, 2) : st === "now" ? `<span class="tagc">building</span>` : `<span class="tagc">${tag}</span>`}</div>`;
  }).join("")}</section>`;
}
const talk = (sugg, placeholder) => `<section class="talk"><p class="lead"><i></i>${D.chat.lead}</p>
  <div class="sugg">${sugg.map((s) => `<span>${s}${I("right", 13)}</span>`).join("")}</div>
  <div class="composer"><p>${placeholder}</p><footer>${I("clip", 16)}<span>${D.chat.agent}</span>${I("down", 13)}<b>${I("up", 16, 2)}</b></footer></div></section>`;
const stage = (inner, d, pipeline, printer) => `<main class="stage">
  <div class="views">${D.views.map((v, i) => `<span class="${i ? "" : "on"}">${v}</span>`).join("")}</div>
  ${printer ? `<div class="printer">${I("printer", 14)}${printer}</div>` : ""}
  <div class="tools">${D.tools.map(([ic], i) => `<span class="${i ? "" : "on"}">${I(ic, 17)}</span>`).join("")}</div>
  ${inner}
  <footer><p class="mono">${d.dims.join(" × ")} mm · ${d.volume} cm³<em>${d.note}</em></p><div class="stamps">${pipeline.map(([n, v, st]) => `<span class="${st}"><b>${n}</b><em class="mono">${v}</em></span>`).join("")}</div></footer></main>`;
const notebook = (d, stages, step, sugg, placeholder) => `<aside class="notebook">${head()}
  <p class="eyebrow"><span class="mono">${d.rev}</span>${d.state}</p><h1>${d.name}</h1>${chapters(stages)}${features(step)}${talk(sugg, placeholder)}</aside>`;

if (S === "workspace") { const d = D.design; document.body.insertAdjacentHTML("beforeend", `${notebook(d, D.stages, 0, D.chat.suggestions.slice(0, 2), D.chat.placeholder)}
  ${stage(`<div style="position:absolute;left:150px;top:150px">${part("case", 640)}</div>`, d, D.pipeline, d.printer)}`); }

if (S === "build") { const d = D.build; document.body.classList.add("building"); document.body.insertAdjacentHTML("beforeend", `${notebook(d, d.stages, d.step, d.suggestions.slice(0, 2), d.placeholder)}
  ${stage(`<div class="plate"><p class="over">Building<span class="mono">${d.step} / ${d.of}</span></p><h2>${d.feature}</h2><p class="it">step ${words[d.step]} of ${words[d.of]}</p></div>
    <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="46"/><circle class="arc" cx="50" cy="50" r="46" pathLength="${d.of}" stroke-dasharray="${d.step - .5} ${d.of}"/></svg><span class="ringn">${d.step}</span>
    <div style="position:absolute;left:200px;top:262px">${part("build", 560)}</div>`, d, d.pipeline, "")}`); }

if (S === "home") { const H = D.home; document.body.classList.add("home"); document.body.insertAdjacentHTML("beforeend", `
  <header class="bar wide">${LOGO(16)}<span class="sp"></span><span class="find">${I("search", 15)}Search<kbd>⌘K</kbd></span><span class="ib">${I("gear", 16)}</span></header>
  <section class="ask"><p class="eyebrow">${H.hello}</p><h1>What do you<br>want to <i>make?</i></h1>
    <div class="composer big"><p>${H.placeholder}</p><footer>${H.attach.map(([ic, t]) => `<span>${I(ic, 15)}${t}</span>`).join("")}<span>${I("mic", 15)}</span><b class="go">${H.go}${I("right", 15, 2)}</b></footer></div>
    <div class="under"><span>Make it for</span><span class="pill on">${H.purposes[0]}</span><span class="pill">${H.purposes[1]}<u>Beta</u></span><span class="ag">${I("spark", 14)}${H.agent}</span></div>
    <div class="starts">${H.starts.map(([ic, t]) => `<span>${I(ic, 15)}${t}</span>`).join("")}</div>
    <p class="resume">${H.resume}${I("right", 13)}</p></section>
  <section class="gallery"><h2>Designs<em>${H.count} · ${H.released}</em><span class="filters">${H.filters.map((f, i) => `<i class="${i ? "" : "on"}">${f}</i>`).join("")}</span></h2>
    <div class="cards">${H.designs.map(([n, kind, rev, st, slug], i) => `<figure class="c${i}"><div class="pic">${thumb(slug, i ? 150 : 250)}</div><figcaption><b>${n}</b><span class="mono">${rev}</span>${st ? `<span class="rel">${st}</span>` : ""}<em>${kind} · just now</em></figcaption></figure>`).join("")}</div>
    <p class="more"><span>${I("sort", 14)}${H.sort}</span><span>${I("import", 14)}Import…</span><b>All ${H.count} designs${I("right", 13)}</b></p></section>
  <p class="foot">${H.foot}</p>`); }

if (S === "tokens") document.body.insertAdjacentHTML("beforeend", tokenSheet({ letter: "C", name: "Atelier",
  why: "For designers, makers and first-time users who should feel at home, not examined. The app is a workshop notebook beside a gallery wall: warm paper tones, a serif that gives every design a title page, one stroke of vermilion like a drafting pencil. It feels human, generous and calm, closer to a beautiful book about objects than to engineering software. The signature is the title page: each design has a name set large, numbered features like a recipe, and the part hung in a softly lit frame. It suits an AI CAD studio because the conversation reads as notes in the margin of your own notebook.",
  type: [["d1", "What do you want to <i>make?</i>", "Fraunces 380 · 76/0.98 · opsz 144 · −0.03em"], ["d2", "Sensor case", "Fraunces 400 · 44/1.0 · design titles"],
    ["d3", "<i>Features</i> in build order", "Fraunces italic 400 · 18 · section heads"], ["d4", "Ask about this design, or describe a change.", "Instrument Sans 400 · 13.5/1.5 · reading"],
    ["d5 mono", "108.0 × 160.0 × 32.0 mm · r01", "Geist Mono 450 · 11.5 · every number"], ["d6", "STRUCTURE · INTERFACE", "Instrument Sans 600 · 9.5 · +0.14em caps"]],
  dark: [["wall", "#14110e", "the window"], ["page", "#1c1814", "the notebook"], ["ink", "#f3ecdf", "ivory text"], ["ink 2", "#b3a898", "labels"],
    ["frame", "#3a322b", "stage, lit"], ["vermilion", "#ff6a3d", "the pencil: selected, dimensions"], ["pass", "#a5cf9b", "known good"], ["review", "#e9b24c", "look at this"]],
  light: [["wall", "#ece5d8", "linen"], ["page", "#f7f2e8", "paper"], ["ink", "#1f1b17", ""], ["ink 2", "#6b6258", ""],
    ["frame", "#ded5c6", ""], ["vermilion", "#d6431c", ""], ["pass", "#3b7d3a", ""], ["review", "#9a6400", ""]],
  depth: [["l0", "Wall", "the window"], ["l1", "Page and frame", "radius 28 · no border · tone only"], ["l2", "Card", "radius 16 · soft shadow 12/32 at 28 %"]],
  shape: "Soft and generous: radius 28 on the stage frame, 16 on cards, full on pills. Hairlines only inside lists. 16 px from the window edge; 32 px inside the page. Numbers in the list are serif italics, as in a recipe.",
  motion: [["Title page", "the name rises 12 px and fades in, 420 ms, soft ease-out"], ["Feature lands", "its line is ticked and the vermilion ring advances, 320 ms"],
    ["Frame light", "the stage warms 6 % while building, 800 ms"], ["Cards", "lift 4 px with shadow on hover, 160 ms"], ["Camera", "480 ms ease-in-out, a slow, heavy turn"], ["Reduce Motion", "fades only"]],
  signature: "The title page (a serif name over a numbered feature list) and the vermilion ring that closes as the part is built.",
  qt: "Rounded Rectangles and gradients, RectangularShadow or MultiEffect shadow on cards only, Shape for the ring. Fraunces is a variable font: Qt 6.7+ sets its optical size and weight through font.variableAxes; on older Qt ship two static cuts (Display, Text). Layout is the current three zones folded into two, so every function keeps its place.",
}));
