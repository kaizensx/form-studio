// Direction B, "Console": a command line under everything, the part's features as a program listing, numbers as readouts.
const S = document.body.dataset.screen, D = DATA;
const nn = (i) => String(i).padStart(2, "0");
const tone = { Structure: "k1", Access: "k2", Interface: "k3", Finish: "k4" };

const topbar = (d, stages) => `<header class="top">${LOGO(14)}${d ? `<span class="sl">/</span><b>${d.name}</b><span class="mono rev">${d.rev}</span><span class="tag">${d.state}</span>` : ""}
  <nav>${(stages || []).map(([n, name, sub, st]) => `<div class="tab ${st === "on" ? "on" : ""}"><span class="mono">${n}</span><b>${name}</b><em class="mono ${st}">${sub}</em></div>`).join("")}</nav>
  <span class="find">${I("search", 14)}Search<kbd>⌘K</kbd></span><span class="sq">${I("gear", 15)}</span></header>`;

function program(step) {
  return `<section class="program"><h2>Program<em>13 features · build order</em></h2>${D.features.map(([name, tag], i) => {
    const st = step ? (i + 1 < step ? "done" : i + 1 === step ? "now" : "todo") : "";
    return `<div class="ln ${st}"><span class="mono no">${nn(i + 1)}</span><span class="gl">${st === "done" ? I("check", 13, 2.2) : st === "now" ? I("play", 11, 2) : ""}</span><b>${name}</b><span class="mono kw ${tone[tag]}">${st === "now" ? "building" : tag}</span></div>`;
  }).join("")}</section>`;
}
const pipeline = (list) => `<section class="pipeline"><h2>Pipeline<em>auto <i class="on">on</i></em></h2>${list.map(([n, v, st]) => `<div class="kv"><i class="${st}"></i><b>${n}</b><span class="mono">${v}</span></div>`).join("")}</section>`;
const readout = (d, faces) => `<section class="readout"><h2>Readout<em>${d.note}</em></h2><div class="cells">${[["X", d.dims[0], "mm"], ["Y", d.dims[1], "mm"], ["Z", d.dims[2], "mm"], ["Volume", d.volume, "cm³"]].map(([k, v, u]) => `<div><span class="mono">${k}</span><b class="mono">${v}<u>${u}</u></b></div>`).join("")}</div></section>`;
const talk = () => `<section class="talkinfo"><h2>Conversation<em>${I("down", 13)}</em></h2><p class="t"><i></i>${D.chat.title}</p><p class="lead">${D.chat.lead}</p><p>${D.chat.body}</p></section>`;
const view = (inner, status) => `<main class="view"><div class="tools">${D.tools.map(([ic], i) => `<span class="${i ? "" : "on"}">${I(ic, 17)}</span>`).join("")}</div>
  <div class="vtabs mono">${I("grid", 14)}${D.views.map((v, i) => `<span class="${i ? "" : "on"}">${v}</span>`).join("")}</div>
  <i class="reg a"></i><i class="reg b"></i><i class="reg c"></i><i class="reg d"></i>${inner}<footer class="mono">${status}</footer></main>`;
const command = (sugg, placeholder) => `<section class="command"><div class="sugg">${sugg.map((s, i) => `<span><kbd>${i + 1}</kbd>${s}</span>`).join("")}</div>
  <div class="prompt"><span class="gt">›</span><p>${placeholder}</p><i class="caret"></i><span class="agent">${I("clip", 16)}<b>${D.chat.agent}</b>${I("down", 13)}</span><span class="key">⏎</span></div>
  <p class="hint mono">${D.chat.hint}</p></section>`;

if (S === "workspace") { const d = D.design; document.body.insertAdjacentHTML("beforeend", `${topbar(d, D.stages)}
  <aside class="left">${program(0)}${pipeline(D.pipeline)}</aside>
  ${view(`<div style="position:absolute;left:112px;top:128px">${part("case", 590)}</div>`, `<span>${d.dims.join(" × ")} mm</span><span>${d.volume} cm³</span><span>${d.note}</span><span class="r">${I("printer", 13)}${d.printer}</span>`)}
  <aside class="right">${readout(d)}${talk()}</aside>${command(D.chat.suggestions, D.chat.placeholder)}`); }

if (S === "build") { const d = D.build; document.body.classList.add("building"); document.body.insertAdjacentHTML("beforeend", `${topbar(d, d.stages)}
  <aside class="left">${program(d.step)}${pipeline(d.pipeline)}</aside>
  ${view(`<div class="hud"><span class="mono big">${nn(d.step)}</span><div><span class="mono over">Building · ${d.step} of ${d.of}</span><b>${d.feature}</b></div><div class="blocks">${Array.from({ length: d.of }, (_, i) => `<i class="${i + 1 < d.step ? "done" : i + 1 === d.step ? "now" : ""}"></i>`).join("")}</div></div>
    <div style="position:absolute;left:148px;top:226px">${part("build", 520)}</div>`, `<span>${d.dims.join(" × ")} mm</span><span>${d.volume} cm³</span><span>${d.note}</span>`)}
  <aside class="right">${readout(d)}${talk()}</aside>${command(d.suggestions, d.placeholder)}`); }

if (S === "home") { const H = D.home; document.body.classList.add("home"); document.body.insertAdjacentHTML("beforeend", `${topbar(null, [])}
  <main class="start">
    <p class="over mono">${H.hello}</p>
    <h1><span class="gt">›</span>${H.ask}</h1>
    <div class="box"><p>${H.placeholder}<i class="caret"></i></p><footer>${H.attach.map(([ic, t]) => `<span>${I(ic, 15)}${t}</span>`).join("")}<span>${I("mic", 15)}</span>
      <em>Make it for</em><span class="opt on">${H.purposes[0]}</span><span class="opt">${H.purposes[1]}<u>Beta</u></span><em class="ag">${I("spark", 14)}${H.agent}</em><b class="go">${H.go}<kbd>⏎</kbd></b></footer></div>
    <div class="cmds">${H.starts.map(([ic, t]) => `<div>${I(ic, 15)}<b>${t}</b>${I("right", 14)}</div>`).join("")}<div>${I("history", 15)}<b>${H.resume}</b>${I("right", 14)}</div></div>
    <section class="table"><h2>Designs<em class="mono">${H.count} · ${H.released}</em><span class="filters mono">${H.filters.map((f, i) => `<i class="${i ? "" : "on"}">${f}</i>`).join("")}</span><span class="lk">${I("sort", 14)}${H.sort}</span><span class="lk">${I("import", 14)}Import…</span><span class="lk">${I("folder", 14)}</span></h2>
      <div class="tr th mono"><span></span><span>Name</span><span>Kind</span><span>Rev</span><span>State</span><span>Changed</span></div>
      ${H.designs.map(([n, kind, rev, st, slug]) => `<div class="tr"><span class="pic">${thumb(slug, 74)}</span><b>${n}</b><span>${kind}</span><span class="mono">${rev}</span><span class="mono ${st ? "ok" : "dimmed"}">${st || "In progress"}</span><span class="mono dimmed">just now</span></div>`).join("")}
      <div class="tr more mono"><span></span><span>+ 4 more · show all ${H.count}</span></div></section>
  </main>`); }

if (S === "tokens") document.body.insertAdjacentHTML("beforeend", tokenSheet({ letter: "B", name: "Console",
  why: "For engineers and makers who think in steps and numbers, and for anyone who likes to see how a thing is made. The app is an instrument: square, ruled, dense, quiet. The part's features read as a program listing, the dimensions as large readouts, and one command line runs under the whole window: ask, search and act in the same place. The signature is that line and the listing executing above it, line by line, while the agent builds. It suits an AI CAD studio because it shows the truth of the product: a model writes a parametric program and a kernel runs it.",
  type: [["d1", "<span class='gt'>›</span>What do you want to make?", "IBM Plex Sans 500 · 44/1.05 · −0.03em"], ["d2 mono", "108.0<u>mm</u>", "IBM Plex Mono 500 · 28 · readouts"],
    ["d3", "Board screw holes", "IBM Plex Sans 600 · 13.5 · names"], ["d4", "Ask about this design, or describe a change.", "IBM Plex Sans 400 · 13/1.5 · reading"],
    ["d5 mono", "06  Board screw holes  INTERFACE", "IBM Plex Mono 400 · 12 · listing"], ["d6 mono", "PROGRAM · 13 FEATURES", "IBM Plex Mono 500 · 10.5 · +0.1em caps"]],
  dark: [["ground", "#0a0c0d", "window"], ["panel", "#0f1213", "columns, command line"], ["ink", "#eef1ee", "text"], ["ink 2", "#9aa39d", "labels"],
    ["rule", "#22282a", "every 1 px line"], ["phosphor", "#c5f25c", "prompt, selected, built"], ["access", "#7ad3e0", "tag class"], ["review", "#ffb84d", "look at this"]],
  light: [["ground", "#f5f5f0", "paper"], ["panel", "#fbfbf8", ""], ["ink", "#101311", ""], ["ink 2", "#5a625c", ""],
    ["rule", "#d9dbd3", ""], ["phosphor", "#3f7d00", "as ink; fill #c5f25c"], ["access", "#0f7f93", ""], ["review", "#a35f00", ""]],
  depth: [["l0", "Ground", "the window and the 3D view"], ["l1", "Panel", "one step lighter, ruled 1 px"], ["l2", "Selected", "phosphor rule on the left, 8 % fill"]],
  shape: "Square. Radius 0 on panels and rows, 2 on keys and tags. No shadows anywhere: depth is a 1 px rule and one step of tone. A 4 px grid; rows 28–32 px; columns meet at rules, with no gutters.",
  motion: [["Line executes", "phosphor bar travels down the listing, 140 ms per line, linear"], ["Readout changes", "digits roll per place, 160 ms"],
    ["Completions", "appear instantly, no fade: the command line is used all day"], ["Panels", "no travel; content cross-fades 90 ms"], ["Camera", "420 ms ease-in-out"], ["Reduce Motion", "the bar jumps, digits swap"]],
  signature: "The command line across the bottom with numbered completions, and the program listing that runs while a part is built.",
  qt: "The simplest of the three to build: Rectangles, 1 px rules and Text; no effects, no blur, no shadows, so it is also the fastest on weak GPUs. The listing is the existing feature ListView with a monospace delegate; the command line is the existing composer and palette merged into one Item docked to the window's bottom.",
}));
