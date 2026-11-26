// Direction A, "Lightbox": the window is the studio. One full-bleed 3D view; every control floats over it as glass.
const S = document.body.dataset.screen, D = DATA;
const tagTone = { Structure: "t1", Access: "t2", Interface: "t3", Finish: "t4" };

const stages = (list) => `<nav class="stages glass">${list.map(([n, name, sub, st]) =>
  `<div class="seg ${st === "on" ? "on" : ""}"><b>${name}</b><span class="${st}">${sub}</span></div>`).join("")}</nav>`;
const title = (d) => `<div class="cap tl glass">${MARK(18)}<b>${d.name}</b><span class="mono rev">${d.rev}</span><span class="tag">${d.state}</span>${I("down", 14)}</div>`;
const right = (printer) => `<div class="cap tr glass">${printer ? `<span class="printer">${I("printer", 15)}${printer}</span><i></i>` : ""}<span class="btn">${I("search", 16)}<kbd>⌘K</kbd></span><span class="btn">${I("gear", 16)}</span></div>`;
const dock = () => `<div class="dock glass">${D.tools.map(([ic], i) => `${i === 7 || i === 9 ? "<hr>" : ""}<span class="${i ? "" : "on"}">${I(ic, 18)}</span>`).join("")}</div>`;
const views = () => `<div class="views glass">${I("grid", 15)}${D.views.map((v, i) => `<span class="${i ? "" : "on"}">${v}</span>`).join("")}</div>`;
const readout = (d) => `<p class="readout mono">${d.dims.join(" × ")} mm<i>·</i>${d.volume} cm³<em>${d.note}</em></p>`;
const pipe = (list) => `<div class="pipe glass">${list.map(([n, v, st]) => `<div><b><i class="${st}"></i>${n}</b><span class="mono">${v}</span></div>`).join("")}<div class="auto"><b>Auto</b><span class="switch"></span></div></div>`;

function rail(step) {
  return `<aside class="rail glass"><header><b>Features</b><span class="mono">13</span><em>build order</em></header>${D.features.map(([name, tag], i) => {
    const st = step ? (i + 1 < step ? "done" : i + 1 === step ? "now" : "todo") : "";
    return `<div class="row ${st}"><span class="mono n">${String(i + 1).padStart(2, "0")}</span><b>${name}</b>${st === "done" ? I("check", 14, 2) : st === "now" ? `<span class="spin"></span>` : `<span class="t ${tagTone[tag]}">${tag}</span>`}</div>`;
  }).join("")}</aside>`;
}

if (S === "workspace") document.body.insertAdjacentHTML("beforeend", `
  <div class="room"></div><div class="pool" style="left:286px;top:330px"></div>
  <div style="position:absolute;left:326px;top:132px">${part("case", 620)}</div>
  ${title(D.design)}${stages(D.stages)}${right(D.design.printer)}${dock()}${rail(0)}${pipe(D.pipeline)}${views()}${readout(D.design)}
  <section class="talk">
    <p class="lead"><span class="live"></span>${D.chat.lead}</p>
    <div class="chips">${D.chat.suggestions.map((s) => `<span class="chip glass">${s}${I("right", 13)}</span>`).join("")}</div>
    <div class="composer glass"><p>${D.chat.placeholder}</p><footer>${I("clip", 17)}<span class="agent">${I("spark", 15)}${D.chat.agent}${I("down", 13)}</span><em>${D.chat.hint}</em><span class="send">${I("up", 17, 2)}</span></footer></div>
  </section>`);

if (S === "build") { const B = D.build; document.body.classList.add("building"); document.body.insertAdjacentHTML("beforeend", `
  <div class="room"></div><div class="pool" style="left:276px;top:250px"></div>
  <div style="position:absolute;left:366px;top:150px">${part("build", 540)}</div>
  ${title(B)}${stages(B.stages)}${right("")}${dock()}${rail(B.step)}${pipe(B.pipeline)}${views()}${readout(B)}
  <section class="third">
    <p class="over mono"><span class="live"></span>Building<i>${B.step} of ${B.of}</i></p>
    <h1>${B.feature}</h1>
    <div class="track">${Array.from({ length: B.of }, (_, i) => `<i class="${i + 1 < B.step ? "done" : i + 1 === B.step ? "now" : ""}"></i>`).join("")}</div>
    <p class="around"><span>built<b class="mono">05</b>${D.features[4][0]}</span><span>next<b class="mono">07</b>${D.features[6][0]}</span></p>
  </section>
  <section class="talk slim"><div class="composer glass"><p>${B.placeholder}</p><footer>${I("clip", 17)}<span class="agent">${I("spark", 15)}${D.chat.agent}</span><span class="send">${I("up", 17, 2)}</span></footer></div></section>`); }

if (S === "home") { const H = D.home; document.body.classList.add("home"); document.body.insertAdjacentHTML("beforeend", `
  <div class="room"></div>
  <div class="cap tl bare">${LOGO(17)}</div>${right("")}
  <section class="ask">
    <p class="over mono">${H.hello}</p><h1>${H.ask}</h1>
    <div class="composer glass big"><p>${H.placeholder}</p><footer>${H.attach.map(([ic, t]) => `<span class="att">${I(ic, 16)}${t}</span>`).join("")}<span class="att">${I("mic", 16)}</span><span class="go">${H.go}${I("right", 15, 2)}</span></footer></div>
    <div class="under"><span class="for">Make it for<span class="segs glass"><b class="on">${H.purposes[0]}</b><b>${H.purposes[1]}<u>Beta</u></b></span></span><span class="agent">${I("spark", 15)}${H.agent}</span></div>
    <p class="starts">${H.starts.map(([ic, t]) => `<span>${I(ic, 15)}${t}</span>`).join("<i>·</i>")}<i>·</i><span class="resume">${H.resume}${I("right", 13)}</span></p>
  </section>
  <section class="shelf">
    <header><h2>Designs</h2><span class="mono">${H.count} · ${H.released}</span><span class="segs glass">${H.filters.map((f, i) => `<b class="${i ? "" : "on"}">${f}</b>`).join("")}</span><span class="link">${I("sort", 15)}${H.sort}</span><span class="link">${I("import", 15)}Import…</span></header>
    <div class="objects">${H.designs.map(([n, kind, rev, st, slug]) => `<figure><div class="plinth">${thumb(slug, 196)}</div><figcaption><b>${n}</b><span class="mono">${rev}</span>${st ? `<span class="tag ok">${st}</span>` : ""}<em>${kind} · just now</em></figcaption></figure>`).join("")}
      <figure class="more"><div class="plinth glass"><b class="mono">+4</b></div><figcaption><b>All ${H.count} designs</b>${I("right", 13)}<em>${H.extra[0]} and three more</em></figcaption></figure></div>
  </section>`); }

if (S === "tokens") document.body.insertAdjacentHTML("beforeend", tokenSheet({ letter: "A", name: "Lightbox",
  why: "For people who came to make an object, not to run CAD software. The window is a photo studio: the part stands alone in a pool of light and every control floats over it as a pane of glass, so the product you are making is the interface. It feels cinematic and quiet. The signature is the light itself, which answers the work: it warms and narrows while the agent builds and opens when the part is ready. It suits an AI CAD studio because the conversation becomes a single bar under the part: you speak to the object, not to a side panel.",
  type: [["d1", "What do you want to make?", "Geist 600 · 68/1.0 · −0.04em"], ["d2", "Board screw holes", "Geist 600 · 52/1.0 · −0.035em"],
    ["d3", "Sensor case", "Geist 600 · 15 · names, buttons"], ["d4", "Ask about this design, or describe a change.", "Geist 400 · 13/1.45 · reading"],
    ["d5 mono", "108.0 × 160.0 × 32.0 mm · r01", "Geist Mono 500 · 11–12 · every number"], ["d6 mono", "BUILDING · 6 OF 12", "Geist Mono 500 · 11 · +0.14em caps"]],
  dark: [["room", "#0b0b0c", "the studio"], ["glass", "rgba(255,255,255,.07)", "blur 28, every pane"], ["ink", "#f4f3f1", "text"], ["ink 2", "#a9a8a5", "labels"],
    ["key light", "#ffe9cf", "the pool, warm"], ["signal", "#a9b8ff", "you are here, dimensions"], ["pass", "#86d9a8", "known good"], ["review", "#f2c36b", "look at this"]],
  light: [["room", "#eeece8", "paper sweep"], ["glass", "rgba(255,255,255,.62)", "blur 28"], ["ink", "#161616", ""], ["ink 2", "#5d5c59", ""],
    ["key light", "#ffffff", ""], ["signal", "#3d55d6", ""], ["pass", "#1f8a52", ""], ["review", "#a86a00", ""]],
  depth: [["l0", "Room", "the 3D view, edge to edge"], ["l1 glass", "Glass", "blur 28 · 1 px light edge · shadow 24/60"], ["l2 glass", "Raised", "active segment, send, menus"]],
  shape: "Capsules: radius 22 on panes, full on buttons and chips, 12 on rows. No dividers; groups are separated by space and by the room showing between panes. 20 px from the window edge, 12 px between panes.",
  motion: [["Light answers", "pool narrows and warms on build, 600 ms ease-in-out"], ["Feature lands", "segment fills, 220 ms; the part's new faces flash key-light, 320 ms"],
    ["Panes", "fade + 8 px rise, 180 ms ease-out, 40 ms stagger"], ["Camera", "420 ms, the panes do not move"], ["Idle", "panes fade to 55 % after 4 s with the pointer on the part"], ["Reduce Motion", "opacity only; the light changes without travel"]],
  signature: "The light pool under the part and the lower-third title while building: the feature's name set large over the room, with a twelve-segment track.",
  qt: "Glass is MultiEffect blur over a ShaderEffectSource of the View3D, behind each pane, with a solid fallback (plate at 92 %) when Reduce Transparency is on or the GPU is weak. The pool is the existing benchPool light. All panes are ordinary Items anchored to the window; every current function keeps its control.",
}));
