// Direction H, "Lightdesk": A's room and glass, with three instruments from B set into the panes:
// large readouts, the features as a program listing that runs, and a command line with numbered completions.
const S = document.body.dataset.screen, D = DATA;
const nn = (i) => String(i).padStart(2, "0");
P.enter = "M19 5v7a3 3 0 01-3 3H6M10 11l-4 4 4 4";
// The same cut-outs with cleaner edges (tools/refine_cutout.py). Same size, so the dimension lines still land.
for (const k in PARTS) PARTS[k].src = "../h/assets/" + PARTS[k].src;

const stages = (list) => `<nav class="stages glass">${list.map(([n, name, sub, st]) =>
  `<div class="seg ${st === "on" ? "on" : ""}"><b>${name}</b><span class="${st}">${sub}</span></div>`).join("")}</nav>`;
const title = (d) => `<div class="cap tl glass">${MARK(18)}<b>${d.name}</b><span class="mono rev">${d.rev}</span><span class="tag">${d.state}</span>${I("down", 14)}</div>`;
const right = (printer) => `<div class="cap tr glass">${printer ? `<span class="printer">${I("printer", 15)}${printer}</span><i></i>` : ""}<span class="btn">${I("search", 16)}<kbd>⌘K</kbd></span><span class="btn">${I("gear", 16)}</span></div>`;
const dock = () => `<div class="dock glass">${D.tools.map(([ic], i) => `${i === 7 || i === 9 ? "<hr>" : ""}<span class="${i ? "" : "on"}">${I(ic, 18)}</span>`).join("")}</div>`;
const views = () => `<div class="views glass">${I("grid", 15)}${D.views.map((v, i) => `<span class="${i ? "" : "on"}">${v}</span>`).join("")}</div>`;
const pipe = (list) => `<div class="pipe glass">${list.map(([n, v, st]) => `<div><b><i class="${st}"></i>${n}</b><span class="mono">${v}</span></div>`).join("")}<div class="auto"><b>Auto</b><span class="switch"></span></div></div>`;

// From B: the readout. Four numbers you can read from across the room.
const readout = (d) => `<section class="readout glass"><header><b>Readout</b><em>${d.note}</em></header><div class="cells">${
  [["X", d.dims[0], "mm"], ["Y", d.dims[1], "mm"], ["Z", d.dims[2], "mm"], ["Volume", d.volume, "cm³"]].map(([k, v, u]) =>
    `<div><span class="mono">${k}<small>${u}</small></span><b>${v}</b></div>`).join("")}</div></section>`;

// From B: the features as a program listing. While the agent builds, the listing runs: the gutter lights down to the current line.
function program(step, of) {
  return `<aside class="program glass ${step ? "running" : ""}"><header><b>Program</b><span class="mono">13</span>${
    step ? `<em class="mono run"><i class="live"></i>${step} of ${of}</em>` : `<em>build order</em>`}</header>
    ${step ? `<i class="pc" style="height:${(step - 1) * 32 + 16}px"></i>` : ""}${D.features.map(([name, tag], i) => {
    const st = step ? (i + 1 < step ? "done" : i + 1 === step ? "now" : "todo") : "";
    return `<div class="ln ${st}"><span class="mono no">${nn(i + 1)}</span><span class="gl">${st === "done" ? I("check", 13, 2.2) : st === "now" ? I("play", 10, 2.4) : ""}</span><b>${name}</b><span class="mono kw">${st === "now" ? "building" : tag}</span></div>`;
  }).join("")}</aside>`;
}

// From B: the command line with numbered completions, as A's one bar under the part.
const completions = (list) => `<div class="sugg">${list.map((s, i) => `<span><kbd class="k">${i + 1}</kbd>${s}</span>`).join("")}</div>`;
const prompt = (placeholder) => `<div class="prompt"><span class="gt mono">›</span><i class="caret"></i><p>${placeholder}</p></div>`;

if (S === "workspace") document.body.insertAdjacentHTML("beforeend", `
  <div class="room"></div><div class="pool" style="left:286px;top:330px"></div>
  <div style="position:absolute;left:326px;top:124px">${part("case", 620)}</div>
  ${title(D.design)}${stages(D.stages)}${right(D.design.printer)}${dock()}${program(0)}${pipe(D.pipeline)}${readout(D.design)}${views()}
  <section class="talk">
    <p class="lead"><span class="live"></span>${D.chat.lead}</p>
    <div class="cmd glass">${completions(D.chat.suggestions)}
      <div class="well">${prompt(D.chat.placeholder)}<footer>${I("clip", 17)}<span class="agent">${I("spark", 15)}${D.chat.agent}${I("down", 13)}</span><em>${D.chat.hint}</em><span class="send">${I("enter", 17, 2)}</span></footer></div></div>
  </section>`);

if (S === "build") { const B = D.build; document.body.classList.add("building"); document.body.insertAdjacentHTML("beforeend", `
  <div class="room"></div><div class="pool" style="left:276px;top:250px"></div>
  <div style="position:absolute;left:366px;top:150px">${part("build", 540)}</div>
  ${title(B)}${stages(B.stages)}${right("")}${dock()}${program(B.step, B.of)}${pipe(B.pipeline)}${readout(B)}${views()}
  <section class="third">
    <p class="over mono"><span class="live"></span>Building<i>${B.step} of ${B.of}</i></p>
    <h1><span class="mono">${nn(B.step)}</span>${B.feature}</h1>
    <div class="track">${Array.from({ length: B.of }, (_, i) => `<i class="${i + 1 < B.step ? "done" : i + 1 === B.step ? "now" : ""}"></i>`).join("")}</div>
    <p class="around"><span>built<b class="mono">05</b>${D.features[4][0]}</span><span>next<b class="mono">07</b>${D.features[6][0]}</span></p>
  </section>
  <section class="talk slim"><div class="cmd glass"><div class="well">${prompt(B.placeholder)}<footer>${I("clip", 17)}<span class="agent">${I("spark", 15)}${D.chat.agent}</span><span class="send">${I("enter", 17, 2)}</span></footer></div></div></section>`); }

if (S === "home") { const H = D.home; document.body.classList.add("home"); document.body.insertAdjacentHTML("beforeend", `
  <div class="room"></div>
  <div class="cap tl bare">${LOGO(17)}</div>${right("")}
  <section class="ask">
    <p class="over mono">${H.hello}</p><h1>${H.ask}</h1>
    <div class="cmd glass big"><div class="well">${prompt(H.placeholder)}<footer>${H.attach.map(([ic, t]) => `<span class="att">${I(ic, 16)}${t}</span>`).join("")}<span class="att">${I("mic", 16)}</span><span class="go">${H.go}${I("enter", 15, 2)}</span></footer></div>
      ${completions([...H.starts.map(([, t]) => t), H.resume])}</div>
    <div class="under"><span class="for">Make it for<span class="segs glass"><b class="on">${H.purposes[0]}</b><b>${H.purposes[1]}<u>Beta</u></b></span></span><span class="agent">${I("spark", 15)}${H.agent}</span></div>
  </section>
  <section class="shelf">
    <header><h2>Designs</h2><span class="mono">${H.count} · ${H.released}</span><span class="segs glass">${H.filters.map((f, i) => `<b class="${i ? "" : "on"}">${f}</b>`).join("")}</span><span class="link">${I("sort", 15)}${H.sort}</span><span class="link">${I("import", 15)}Import…</span></header>
    <div class="objects">${H.designs.map(([n, kind, rev, st, slug], i) => `<figure><div class="plinth">${thumb(slug, 196)}</div><figcaption><span class="mono no">${nn(i + 1)}</span><b>${n}</b><span class="mono">${rev}</span>${st ? `<span class="tag ok">${st}</span>` : ""}<em>${kind} · just now</em></figcaption></figure>`).join("")}
      <figure class="more"><div class="plinth glass"><b class="mono">+4</b></div><figcaption><b>All ${H.count} designs</b>${I("right", 13)}<em>${H.extra[0]} and three more</em></figcaption></figure></div>
  </section>`); }

if (S === "tokens") document.body.insertAdjacentHTML("beforeend", tokenSheet({ letter: "H", name: "Lightdesk",
  why: "A's room with B's instruments. The window is still a photo studio: the part alone in a pool of warm light, every control a pane of glass. Set into those panes are the three things that made Console honest: the dimensions as numbers you can read from across the room, the features as a program that runs line by line while the agent builds, and a command line with numbered completions as the one bar under the part. A lighting desk does the same job in a theatre: a quiet console that runs a cue list and moves the light. One signal colour, periwinkle, for one meaning: this is where you are. It is the complement of the warm key light, keeps its hue on paper, and leaves green free to mean pass.",
  type: [["d1", "What do you want to make?", "Geist 600 · 68/1.0 · −0.04em"], ["d2", "<span class='mono'>06</span>Board screw holes", "Geist 600 · 52/1.0 · −0.035em"],
    ["d7", "108.0<small>mm</small>", "Geist 600 tabular · 38/1.0 · readouts"], ["d3", "Sensor case", "Geist 600 · 15 · names, buttons"],
    ["d4", "Ask about this design, or describe a change.", "Geist 400 · 13/1.45 · reading"],
    ["d5 mono", "06  Board screw holes  BUILDING", "Geist Mono 500 · 11 · listing, keys, small numbers"], ["d6 mono", "BUILDING · 6 OF 12", "Geist Mono 500 · 11 · +0.14em caps"]],
  dark: [["room", "#0b0b0c", "the studio"], ["glass", "rgba(255,255,255,.07)", "blur 28, every pane"], ["ink", "#f4f3f1", "text, readouts"], ["ink 2", "#a9a8a5", "labels"],
    ["key light", "#ffe9cf", "the pool, warm"], ["signal", "#a9b8ff", "the one accent: here, now"], ["pass", "#86d9a8", "state dot, built line"], ["review", "#f2c36b", "state only"]],
  light: [["room", "#eeece8", "paper sweep"], ["glass", "rgba(255,255,255,.62)", "blur 28"], ["ink", "#161616", ""], ["ink 2", "#5d5c59", ""],
    ["key light", "#ffffff", ""], ["signal", "#3d55d6", "same hue, as ink"], ["pass", "#1f8a52", ""], ["review", "#a86a00", ""]],
  depth: [["l0", "Room", "the 3D view, edge to edge"], ["l1 glass", "Glass", "blur 28 · 1 px light edge · shadow 24/60"], ["l2 glass", "Well / raised", "the prompt, the running line"]],
  shape: "Capsules: radius 22 on panes, full on buttons, 10 on listing lines and keys. No dividers: the one drawn line is the listing's gutter, and it is the progress bar. 20 px from the window edge, 12 px between panes.",
  motion: [["Line executes", "the gutter lights down to the next line, 140 ms; the row's glass follows"], ["Light answers", "pool narrows and warms on build, 600 ms ease-in-out"],
    ["Readout changes", "digits roll per place, 160 ms"], ["Completions", "instant, no fade: the bar is used all day"], ["Panes", "fade + 8 px rise, 180 ms ease-out"], ["Reduce Motion", "opacity only; the gutter jumps, digits swap"]],
  signature: "The cue: the lower-third title over the room and the same line lit in the program listing, with the gutter filled down to it.",
  qt: "As A: glass is MultiEffect blur over a ShaderEffectSource of the View3D, with a solid fallback (plate at 92 %). The listing is the existing feature ListView with a mono number and a 1 px gutter Rectangle whose lit height animates. The readout is four Text items in Geist with tabular figures. The bar is the existing composer; completions are the existing suggestion chips given number keys.",
}));
