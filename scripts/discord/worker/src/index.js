// The Form Studio bot, live: slash commands, buttons, the role picker, the showcase form, levels and the weekly
// challenge. A Cloudflare Worker that Discord calls for every interaction (signed with the app's public key), plus
// a cron that counts XP and runs the challenge. Channel names, roles and texts come from config.json, written from
// scripts/discord/server.py. Secrets: DISCORD_BOT_TOKEN. Vars: APP_ID, PUBLIC_KEY, GUILD_ID. KV: STATE.
import C from "../config.json" with { type: "json" };

const API = "https://discord.com/api/v10";
const EPHEMERAL = 64;
const STAR = "⭐";

// ---- Discord REST ------------------------------------------------------------------------------------------------
export async function api(env, method, path, body) {
  for (let attempt = 0; attempt < 4; attempt++) {
    const r = await fetch(API + path, {
      method,
      headers: { Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://github.com/kaizensx/form-studio, 2.0) FormStudio" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (r.status === 429) {
      const j = await r.json().catch(() => ({}));
      console.log("429", path, JSON.stringify(j).slice(0, 200));
      if ((j.retry_after || 1) > 5) throw new Error(`${method} ${path}: rate limited for ${j.retry_after}s`);
      await new Promise((res) => setTimeout(res, (j.retry_after || 1) * 1000 + 100));
      continue;
    }
    if (r.status === 204) return null;
    const text = await r.text();
    if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${text.slice(0, 300)}`);
    return text ? JSON.parse(text) : null;
  }
  throw new Error(`${method} ${path}: rate limited`);
}

const cache = { at: 0, channels: null, roles: null };
async function guild(env) {
  if (!cache.channels || Date.now() - cache.at > 5 * 60 * 1000) {
    const [channels, roles] = await Promise.all([api(env, "GET", `/guilds/${env.GUILD_ID}/channels`),
                                                 api(env, "GET", `/guilds/${env.GUILD_ID}/roles`)]);
    Object.assign(cache, { at: Date.now(), channels, roles });
  }
  return cache;
}
const N = (key) => C.names[key] || key;
async function chan(env, key) { return (await guild(env)).channels.find((c) => c.name === N(key)); }
async function role(env, name) { return (await guild(env)).roles.find((r) => r.name === (C.roles[name] || name)); }
const mention = async (env, key) => { const c = await chan(env, key); return c ? `<#${c.id}>` : `#${key}`; };

// ---- small helpers ---------------------------------------------------------------------------------------------------
const footer = (section) => ({ text: `Form Studio · ${section}`, icon_url: C.icon });
const reply = (data, ephemeral = true) => ({ type: 4, data: { allowed_mentions: { parse: [] }, ...data,
                                                              flags: ephemeral ? EPHEMERAL : 0 } });
const linkBtn = (label, url, emoji) => ({ type: 2, style: 5, label, url, ...(emoji ? { emoji: { name: emoji } } : {}) });
const btn = (label, id, emoji, style = 2) => ({ type: 2, style, label, custom_id: id, ...(emoji ? { emoji: { name: emoji } } : {}) });
const row = (...c) => ({ type: 1, components: c.slice(0, 5) });
const userOf = (i) => i.member?.user || i.user;
const opt = (i, name) => (i.data.options || []).find((o) => o.name === name)?.value;
export const xpFor = (level) => 5 * level * level + 50 * level + 100;     // XP from level n to n+1
export function levelOf(xp) { let lv = 0; while (xp >= xpFor(lv)) { xp -= xpFor(lv); lv++; } return { level: lv, into: xp, next: xpFor(lv) }; }
const bar = (a, b, n = 14) => "█".repeat(Math.round((a / b) * n)) + "░".repeat(n - Math.round((a / b) * n));

// ---- state (KV) ------------------------------------------------------------------------------------------------------
async function load(env) { return (await env.STATE.get("state", "json")) || { xp: {}, cursors: {}, thanks: {}, challenge: null }; }
async function save(env, s) { await env.STATE.put("state", JSON.stringify(s)); }
// interactions add XP through small "bonus:" keys; the cron folds them in, so the two never overwrite each other
async function bonus(env, user, amount, why) {
  await env.STATE.put(`bonus:${Date.now()}:${user}:${Math.random().toString(36).slice(2, 8)}`, JSON.stringify({ user, amount, why }));
}

// ---- recipes and guides ----------------------------------------------------------------------------------------------
async function recipes() {
  const r = await fetch(C.site + "recipes/index.json", { cf: { cacheTtl: 600 } });
  return (await r.json()).recipes;
}
async function guideThreads(env) {
  const g = await chan(env, "guides");
  if (!g) return {};
  const [active, archived] = await Promise.all([api(env, "GET", `/guilds/${env.GUILD_ID}/threads/active`),
                                                api(env, "GET", `/channels/${g.id}/threads/archived/public?limit=100`)]);
  const out = {};
  for (const t of [...active.threads, ...archived.threads]) if (t.parent_id === g.id) out[t.name] = t.id;
  return out;
}
function recipeEmbed(r) {
  return { color: C.colors.violet, title: `🧩 ${r.title}`, url: C.site + "recipes/", description: r.summary,
           image: r.preview ? { url: r.preview } : undefined,
           fields: [{ name: "Parameters", value: String(r.params_count ?? "—"), inline: true },
                    { name: "Author", value: r.author || "—", inline: true },
                    { name: "Tags", value: (r.tags || []).slice(0, 6).join(", ") || "—", inline: false }],
           footer: footer("Recipes") };
}

// ---- commands --------------------------------------------------------------------------------------------------------
async function cmdHelp(env) {
  return reply({ embeds: [{ color: C.colors.blueprint, title: "🧭 Where to go", footer: footer("Help"), description:
    `🛟 **Stuck?** Post in ${await mention(env, "help")} with a tag; the bot answers with the right guides.\n` +
    `📘 **Learning?** ${await mention(env, "guides")}, or \`/guide\`.\n` +
    `🧩 **Building blocks?** ${await mention(env, "recipes")}, or \`/recipe\`.\n` +
    `🧠 **Design talk:** ${await mention(env, "design-tips")} · 🧬 **Mesh to CAD:** ${await mention(env, "mesh-to-cad")} · 🤖 **Agents:** ${await mention(env, "agents")}\n` +
    `🖨️ **3D printing (optional):** ${await mention(env, "printers")}\n` +
    `🐞 **A bug you can reproduce?** [Open an issue](${C.repo}/issues/new/choose).` }],
    components: [row(linkBtn("Docs", C.docs, "📘"), linkBtn("Download", C.repo + "/releases/latest", "⬇️"))] });
}

async function cmdGuide(env, i) {
  const want = opt(i, "topic");
  const g = C.guides.find(([t]) => t === want) || C.guides[0];
  const threads = await guideThreads(env);
  const where = threads[g[0]] ? `<#${threads[g[0]]}>` : await mention(env, "guides");
  return reply({ embeds: [{ color: C.colors.datum, title: `📘 ${g[0]}`, description: `The full guide: ${where}`, footer: footer("Guides") }],
                 components: [row(...g[2].slice(0, 5).map(([l, u]) => linkBtn(l, u)))] }, false);
}

async function cmdRecipe(env, i, random = false) {
  const all = await recipes();
  const want = (opt(i, "name") || "").toLowerCase();
  const r = random || !want ? all[Math.floor(Math.random() * all.length)]
    : all.find((x) => x.id === want || x.title.toLowerCase() === want) || all.find((x) => x.title.toLowerCase().includes(want));
  if (!r) return reply({ content: `No recipe matches “${want}”. Try \`/recipe\` and pick from the list.` });
  return reply({ embeds: [recipeEmbed(r)], components: [row(linkBtn("Open the gallery", C.site + "recipes/", "🧩"),
    btn("Another one", "open:recipe", "🎲"))] }, random || !want);
}

async function autocomplete(env, i) {
  const focused = (i.data.options || []).find((o) => o.focused);
  const q = String(focused?.value || "").toLowerCase();
  let choices = [];
  if (i.data.name === "recipe") {
    choices = (await recipes()).filter((r) => !q || r.title.toLowerCase().includes(q) || (r.tags || []).some((t) => t.includes(q)))
      .slice(0, 25).map((r) => ({ name: r.title, value: r.id }));
  }
  return { type: 8, data: { choices } };
}

async function cmdRank(env, i) {
  const who = opt(i, "user") || userOf(i).id;
  const s = await load(env);
  const me = s.xp[who] || { xp: 0, msgs: 0, kudos: 0 };
  const { level, into, next } = levelOf(me.xp);
  const ranked = Object.entries(s.xp).sort((a, b) => b[1].xp - a[1].xp);
  const place = ranked.findIndex(([u]) => u === who) + 1;
  const nextRole = C.levels.find(([lv]) => lv > level);
  return reply({ embeds: [{ color: C.colors.datum, title: `📈 Level ${level}`, footer: footer("Levels"),
    description: `<@${who}>\n\`${bar(into, next)}\` ${into} / ${next} XP\n\n` +
      `🏅 Rank **#${place || "—"}** · 💬 ${me.msgs || 0} messages · 🙏 ${me.kudos || 0} thanks` +
      (nextRole ? `\nNext role: **${nextRole[1]}** at level ${nextRole[0]}` : "\nEvery level role earned. 🏗️") }] }, false);
}

async function cmdLeaderboard(env) {
  const s = await load(env);
  const top = Object.entries(s.xp).sort((a, b) => b[1].xp - a[1].xp).slice(0, 10);
  const medal = ["🥇", "🥈", "🥉"];
  const lines = top.map(([u, v], n) => `${medal[n] || `\`${n + 1}.\``} <@${u}> · level ${levelOf(v.xp).level} · ${v.xp} XP`);
  return reply({ embeds: [{ color: C.colors.amber, title: "🏆 Most active makers", footer: footer("Levels"),
    description: lines.join("\n") || "Nobody has XP yet. Say hi in #introductions to be first." }] }, false);
}

async function cmdThanks(env, i) {
  const from = userOf(i).id, to = opt(i, "user");
  const target = i.data.resolved?.users?.[to];
  if (!to || to === from || target?.bot) return reply({ content: "Thank someone else: not yourself, and not a bot. 🙂" });
  const s = await load(env);
  const day = new Date().toISOString().slice(0, 10);
  const t = s.thanks[from]?.day === day ? s.thanks[from] : { day, count: 0 };
  if (t.count >= C.xp.thanks_per_day) return reply({ content: `You have thanked ${C.xp.thanks_per_day} people today. More tomorrow. 🙏` });
  t.count++; s.thanks[from] = t;
  await save(env, s);
  await bonus(env, to, C.xp.thanks, "thanks");
  const why = opt(i, "for");
  return { type: 4, data: { content: `🙏 <@${from}> thanks <@${to}>${why ? `: ${why}` : "."} (+${C.xp.thanks} XP)`,
                            allowed_mentions: { users: [to] } } };
}

function cmdShowcaseModal() {
  const input = (id, label, style, required, placeholder, max = 200) =>
    row({ type: 4, custom_id: id, label, style, required, placeholder, max_length: max });
  return { type: 9, data: { custom_id: "showcase", title: "Show something you designed", components: [
    input("title", "What is it?", 1, true, "Desk-edge cable clip", 90),
    input("story", "What is it for, and how did you make it?", 2, true, "A planetary gearbox: brief, plan, two critiques…", 1500),
    input("setup", "Agent, model and what you exported", 1, false, "Claude Code · Opus · STEP and a render", 120),
    input("image", "Link to a photo or render (optional)", 1, false, "https://…png", 400),
    input("file", "Link to the .formstudio file (optional)", 1, false, "https://…", 400)] } };
}

async function showcaseSubmit(env, i) {
  const v = {};
  for (const r of i.data.components) for (const c of r.components) v[c.custom_id] = (c.value || "").trim();
  const u = userOf(i);
  const forum = await chan(env, "showcase");
  const img = /^https:\/\/\S+$/.test(v.image) ? v.image : null;
  const emb = { color: C.colors.datum, title: `🧊 ${v.title}`, description: v.story, footer: footer("Showcase"),
                author: { name: u.global_name || u.username, icon_url: u.avatar ? `https://cdn.discordapp.com/avatars/${u.id}/${u.avatar}.png` : undefined },
                fields: v.setup ? [{ name: "🛠️ Made with", value: v.setup, inline: false }] : [],
                ...(img ? { image: { url: img } } : {}) };
  const tags = Object.fromEntries((forum.available_tags || []).map((t) => [t.name, t.id]));
  const t = await api(env, "POST", `/channels/${forum.id}/threads`, {
    name: v.title.slice(0, 100), applied_tags: [tags["3D model"]].filter(Boolean),
    message: { content: `Made by <@${u.id}>`, embeds: [emb], allowed_mentions: { parse: [] },
               components: /^https:\/\//.test(v.file) ? [row(linkBtn("Download the design", v.file, "📦"))] : [] } });
  await bonus(env, u.id, C.xp.showcase, "showcase");
  return reply({ content: `🔥 Posted: <#${t.id}> (+${C.xp.showcase} XP). Add photos by replying in it.` });
}

async function cmdChallenge(env) {
  const s = await load(env);
  const c = s.challenge;
  if (!c) return reply({ content: `The first challenge opens shortly in ${await mention(env, "challenges")}.` });
  const [title, brief, rule] = C.challenges[c.index % C.challenges.length];
  return reply({ embeds: [{ color: C.colors.amber, title: `🏁 ${title}`, footer: footer("Weekly challenge"),
    description: `${brief}\n\n**To count:** ${rule}\n\nPost your entry in <#${c.thread}>. Closes <t:${Math.floor(c.closes / 1000)}:R>.` }] }, false);
}

function cmdPoll(i) {
  const q = opt(i, "question");
  const answers = String(opt(i, "options")).split(/[;|\n]/).map((x) => x.trim()).filter(Boolean).slice(0, 10);
  if (answers.length < 2) return reply({ content: "Give at least two options, separated by `;`." });
  return { type: 4, data: { poll: { question: { text: q.slice(0, 300) }, duration: Math.min(168, Math.max(1, opt(i, "hours") || 24)),
    allow_multiselect: !!opt(i, "multiple"), answers: answers.map((a) => ({ poll_media: { text: a.slice(0, 55) } })) } } };
}

function cmdDownload() {
  const d = (os) => `${C.repo}/releases/latest/download/${os}`;
  return reply({ embeds: [{ color: C.colors.datum, title: "⬇️ Download Form Studio", footer: footer("Download"),
    description: "Free and open source. The first start installs what it needs by itself." }],
    components: [row(linkBtn("macOS (Apple silicon)", d("FORM-macos-arm64.zip"), "🍎"), linkBtn("macOS (Intel)", d("FORM-macos-x64.zip"), "🍏"),
                     linkBtn("Windows", d("FORM-windows-x64.zip"), "🪟"), linkBtn("Linux", d("FORM-linux-x64.tar.gz"), "🐧"))] }, false);
}

async function rolePicker(env, i) {
  const member = i.member;
  const g = await guild(env);
  const rows = C.picker.map(([key, placeholder, names]) => {
    const options = names.map((n) => g.roles.find((r) => r.name === n)).filter(Boolean)
      .map((r) => ({ label: r.name.split(" ").slice(1).join(" "), value: r.id, emoji: { name: r.name.split(" ")[0] },
                     default: (member?.roles || []).includes(r.id) }));
    return row({ type: 3, custom_id: `roles:${key}`, placeholder, min_values: 0, max_values: options.length, options });
  });
  return reply({ content: "🎭 Pick what fits; what you leave out is removed.", components: rows });
}

async function rolesChosen(env, i) {
  const key = i.data.custom_id.split(":")[1];
  const group = C.picker.find(([k]) => k === key);
  const g = await guild(env);
  const ids = group[2].map((n) => g.roles.find((r) => r.name === n)?.id).filter(Boolean);
  const want = new Set(i.data.values), have = new Set(i.member.roles);
  const u = userOf(i).id, add = [], drop = [];
  // the shared menu in #roles cannot show each member's roles, so there a pick toggles that role; the private picker
  // (/roles, the welcome button) shows your roles ticked, so there the picks are the whole set for the group
  const shared = !((i.message?.flags || 0) & EPHEMERAL);
  for (const id of ids) {
    const on = shared ? (want.has(id) ? !have.has(id) : have.has(id)) : want.has(id);
    if (on && !have.has(id)) { await api(env, "PUT", `/guilds/${env.GUILD_ID}/members/${u}/roles/${id}`); add.push(id); }
    if (!on && have.has(id)) { await api(env, "DELETE", `/guilds/${env.GUILD_ID}/members/${u}/roles/${id}`); drop.push(id); }
  }
  const say = [add.length && `Added ${add.map((r) => `<@&${r}>`).join(" ")}`, drop.length && `removed ${drop.map((r) => `<@&${r}>`).join(" ")}`]
    .filter(Boolean).join(", ");
  return reply({ content: say ? `✅ ${say}.` : "Nothing changed." });
}

async function markSolved(env, i) {
  const t = await api(env, "GET", `/channels/${i.channel_id}`);
  const helpF = await chan(env, "help");
  if (!helpF || t.parent_id !== helpF.id) return reply({ content: "Mark as solved works inside a post in the help forum." });
  const u = userOf(i).id;
  const staff = await role(env, "Maintainer");
  if (t.owner_id !== u && !(staff && i.member.roles.includes(staff.id))) return reply({ content: "Only the person who asked (or a maintainer) can mark it solved." });
  const solved = (helpF.available_tags || []).find((x) => x.name === "Solved");
  if (solved) await api(env, "PATCH", `/channels/${t.id}`, { applied_tags: [...new Set([...(t.applied_tags || []), solved.id])].slice(0, 5) });
  const msg = Object.values(i.data.resolved.messages)[0];
  const helper = msg.author.id;
  if (helper !== u && !msg.author.bot) await bonus(env, helper, C.xp.solved, "solved");
  return { type: 4, data: { content: `✅ Solved. The answer: ${`https://discord.com/channels/${env.GUILD_ID}/${t.id}/${msg.id}`}` +
    (helper !== u && !msg.author.bot ? ` · thank you <@${helper}> (+${C.xp.solved} XP)` : ""), allowed_mentions: { users: [helper] } } };
}

async function startHere(env) {
  return reply({ embeds: [{ color: C.colors.blueprint, title: "🧭 Where do I start?", footer: footer("Start"), description:
    `1️⃣ Say hi in ${await mention(env, "introductions")}: what you want to design and which agent you use.\n` +
    `2️⃣ Read the first guide in ${await mention(env, "guides")}, then download Form Studio.\n` +
    `3️⃣ Make something and post it in ${await mention(env, "showcase")}, or enter ${await mention(env, "challenges")}.\n` +
    `4️⃣ Stuck? ${await mention(env, "help")}. Everyone was a beginner once.` }],
    components: [row(btn("Pick my roles", "open:roles", "🎭", 1), linkBtn("Download", C.repo + "/releases/latest", "⬇️"))] });
}

// ---- interactions ----------------------------------------------------------------------------------------------------
export async function handle(env, i) {
  if (i.type === 1) return { type: 1 };
  if (i.type === 4) return autocomplete(env, i);
  if (i.type === 2) {
    switch (i.data.name) {
      case "help": return cmdHelp(env);
      case "guide": return cmdGuide(env, i);
      case "recipe": return cmdRecipe(env, i);
      case "rank": return cmdRank(env, i);
      case "leaderboard": return cmdLeaderboard(env);
      case "thanks": return cmdThanks(env, i);
      case "showcase": return cmdShowcaseModal();
      case "challenge": return cmdChallenge(env);
      case "poll": return cmdPoll(i);
      case "download": return cmdDownload();
      case "roles": return rolePicker(env, i);
      case "Mark as solved": return markSolved(env, i);
    }
  }
  if (i.type === 3) {
    const id = i.data.custom_id;
    if (id.startsWith("roles:")) return rolesChosen(env, i);
    if (id === "open:roles") return rolePicker(env, i);
    if (id === "open:start") return startHere(env);
    if (id === "open:recipe") return cmdRecipe(env, i, true);
  }
  if (i.type === 5 && i.data.custom_id === "showcase") return showcaseSubmit(env, i);
  return reply({ content: "That did not work. Try again in a moment." });
}

// answered at once: PING, autocomplete, the showcase form, and commands that need nothing from Discord
const INSTANT = new Set(["showcase", "poll", "download"]);
function immediate(i) { return i.type === 1 || i.type === 4 || (i.type === 2 && INSTANT.has(i.data.name)); }
const PUBLIC = new Set(["guide", "rank", "leaderboard", "thanks", "challenge", "Mark as solved", "recipe"]);
function ephemeral(i) {
  if (i.type !== 2 || !PUBLIC.has(i.data.name)) return true;
  if (i.data.name === "recipe") return !opt(i, "name");
  if (i.data.name === "challenge") return true;
  return false;
}

function hex(s) { return new Uint8Array(s.match(/../g).map((h) => parseInt(h, 16))); }
export async function verify(publicKey, signature, timestamp, body) {
  try {
    let key;
    try { key = await crypto.subtle.importKey("raw", hex(publicKey), { name: "Ed25519" }, false, ["verify"]); }
    catch { key = await crypto.subtle.importKey("raw", hex(publicKey), { name: "NODE-ED25519", namedCurve: "NODE-ED25519" }, false, ["verify"]); }
    return await crypto.subtle.verify(key.algorithm.name === "Ed25519" ? "Ed25519" : "NODE-ED25519", key, hex(signature),
                                      new TextEncoder().encode(timestamp + body));
  } catch { return false; }
}

// ---- the cron: XP, level roles, the weekly challenge -------------------------------------------------------------------
async function countXP(env, s) {
  const g = await guild(env);
  const everyone = env.GUILD_ID;
  const readable = (c) => !(c.permission_overwrites || []).some((o) => o.id === everyone && (BigInt(o.deny) & 1024n));
  const textish = g.channels.filter((c) => [0, 5].includes(c.type) && readable(c));
  const active = (await api(env, "GET", `/guilds/${env.GUILD_ID}/threads/active`)).threads;
  const parents = new Set(g.channels.filter(readable).map((c) => c.id));
  const places = [...textish, ...active.filter((t) => parents.has(t.parent_id))];
  const [lo, hi] = C.xp.message;
  let budget = 30;                                   // Cloudflare's free plan allows 50 requests per run
  for (const c of places) {
    if (!c.last_message_id || s.cursors[c.id] === c.last_message_id) continue;   // nothing new here
    if (budget-- <= 0) break;                        // the rest is read on the next run
    const msgs = await api(env, "GET", `/channels/${c.id}/messages?limit=100&after=${s.cursors[c.id] || "0"}`);
    msgs.sort((a, b) => (BigInt(a.id) < BigInt(b.id) ? -1 : 1));
    for (const m of msgs) {
      s.cursors[c.id] = m.id;
      if (m.author.bot || (m.type !== 0 && m.type !== 19 && m.type !== 21)) continue;
      const u = (s.xp[m.author.id] ||= { xp: 0, msgs: 0, kudos: 0, last: 0 });
      u.msgs++;
      const at = Date.parse(m.timestamp);
      if (at - (u.last || 0) >= C.xp.cooldown_s * 1000) { u.xp += lo + Math.floor(Math.random() * (hi - lo + 1)); u.last = at; }
    }
    if (!msgs.length) s.cursors[c.id] = c.last_message_id;
  }
  // bonuses from /thanks, solved answers and /showcase
  const list = await env.STATE.list({ prefix: "bonus:" });
  for (const k of list.keys) {
    const b = await env.STATE.get(k.name, "json");
    if (b) { const u = (s.xp[b.user] ||= { xp: 0, msgs: 0, kudos: 0, last: 0 }); u.xp += b.amount; if (b.why === "thanks") u.kudos++; }
    await env.STATE.delete(k.name);
  }
}

async function levelRoles(env, s) {
  const g = await guild(env);
  const lvRoles = C.levels.map(([lv, n]) => [lv, g.roles.find((r) => r.name === n)]).filter(([, r]) => r);
  const general = await chan(env, "general");
  s.levels ||= {};
  for (const [u, v] of Object.entries(s.xp)) {
    const { level } = levelOf(v.xp);
    const earned = lvRoles.filter(([lv]) => level >= lv).pop();
    if (!earned || s.levels[u] === earned[1].id) continue;
    try {
      await api(env, "PUT", `/guilds/${env.GUILD_ID}/members/${u}/roles/${earned[1].id}`);
      for (const [, r] of lvRoles) if (r.id !== earned[1].id) await api(env, "DELETE", `/guilds/${env.GUILD_ID}/members/${u}/roles/${r.id}`).catch(() => {});
      s.levels[u] = earned[1].id;
      if (general) await api(env, "POST", `/channels/${general.id}/messages`, { content: `🎉 <@${u}> reached level ${level} and is now **${earned[1].name}**!`,
                                                                                allowed_mentions: { users: [u] } });
    } catch (e) { console.log("level role", u, String(e)); }
  }
}

function nextClose(from) {        // the coming Sunday 21:00 UTC
  const d = new Date(from); d.setUTCHours(21, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() + ((7 - d.getUTCDay()) % 7));
  if (d.getTime() <= from) d.setUTCDate(d.getUTCDate() + 7);
  return d.getTime();
}

async function closeChallenge(env, s) {
  const c = s.challenge;
  const msgs = await api(env, "GET", `/channels/${c.thread}/messages?limit=100`);
  const entries = msgs.filter((m) => !m.author.bot && m.id !== c.thread)
    .map((m) => ({ m, stars: (m.reactions || []).find((r) => r.emoji.name === STAR)?.count || 0 }))
    .sort((a, b) => b.stars - a.stars || (a.m.id < b.m.id ? -1 : 1));
  const win = entries[0] && entries[0].stars > 0 ? entries[0] : null;
  const [title] = C.challenges[c.index % C.challenges.length];
  const text = win ? `🏆 **${title}** is won by <@${win.m.author.id}> with ${win.stars} ${STAR}. Congratulations!`
                   : `🏁 **${title}** closed with ${entries.length} entr${entries.length === 1 ? "y" : "ies"} and no stars. Next week's brief is open.`;
  await api(env, "POST", `/channels/${c.thread}/messages`, { content: text, allowed_mentions: { users: win ? [win.m.author.id] : [] } });
  const ev = await chan(env, "events");
  if (ev) await api(env, "POST", `/channels/${ev.id}/messages`, { content: text, allowed_mentions: { users: win ? [win.m.author.id] : [] } });
  if (win) { const r = await role(env, "🏆 Challenge winner"); if (r) await api(env, "PUT", `/guilds/${env.GUILD_ID}/members/${win.m.author.id}/roles/${r.id}`); }
  const forum = await api(env, "GET", `/channels/${(await chan(env, "challenges")).id}`);
  const closed = (forum.available_tags || []).find((t) => t.name === "Closed");
  await api(env, "PATCH", `/channels/${c.thread}`, { applied_tags: closed ? [closed.id] : [], locked: true, archived: true });
  s.challenge = { ...c, closed: Date.now() };
}

async function openChallenge(env, s) {
  const forum = await api(env, "GET", `/channels/${(await chan(env, "challenges")).id}`);
  const index = s.challenge ? s.challenge.index + 1 : 0;
  const [title, brief, rule] = C.challenges[index % C.challenges.length];
  const closes = nextClose(Date.now());
  const open = (forum.available_tags || []).find((t) => t.name === "Open");
  const ping = await role(env, "🏁 Challenge pings");
  const t = await api(env, "POST", `/channels/${forum.id}/threads`, {
    name: `🏁 Week ${index + 1}: ${title}`.slice(0, 100), applied_tags: open ? [open.id] : [], auto_archive_duration: 10080,
    message: { content: ping ? `<@&${ping.id}> a new challenge is open.` : "", allowed_mentions: { roles: ping ? [ping.id] : [] },
      embeds: [{ color: C.colors.amber, title: `🏁 ${title}`, footer: footer("Weekly challenge"),
        description: `${brief}\n\n**To count:** ${rule}\n\n**Enter:** reply here with a render or a photo and how you made it.\n` +
          `**Vote:** react ${STAR} on the entries you like.\n**Closes:** <t:${Math.floor(closes / 1000)}:F> (<t:${Math.floor(closes / 1000)}:R>). ` +
          "The most starred entry wins 🏆 Challenge winner." }],
      components: [row(linkBtn("Download Form Studio", C.repo + "/releases/latest", "⬇️"), linkBtn("Recipes", C.site + "recipes/", "🧩"))] } });
  s.challenge = { index, thread: t.id, opened: Date.now(), closes };
  try {     // the challenge in the server's Events tab
    await api(env, "POST", `/guilds/${env.GUILD_ID}/scheduled-events`, { name: `🏁 Challenge: ${title}`.slice(0, 100), privacy_level: 2,
      entity_type: 3, scheduled_start_time: new Date(Date.now() + 60000).toISOString(), scheduled_end_time: new Date(closes).toISOString(),
      entity_metadata: { location: `#${N("challenges")}` }, description: `${brief} ${rule}`.slice(0, 1000) });
  } catch (e) { console.log("event", String(e)); }
}

export async function tick(env) {
  const s = await load(env);
  await countXP(env, s);
  await levelRoles(env, s);
  if (s.challenge && !s.challenge.closed && Date.now() >= s.challenge.closes) await closeChallenge(env, s);
  if (!s.challenge || s.challenge.closed) await openChallenge(env, s);
  await save(env, s);
  return s;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET") return new Response("Form Studio bot is running.", { status: 200 });
    if (url.pathname === "/diag") {           // one Discord call, timed (Actions, with the bot token as the key)
      if (request.headers.get("Authorization") !== `Bot ${env.DISCORD_BOT_TOKEN}`) return new Response("no", { status: 401 });
      const t0 = Date.now();
      const r = await fetch(`${API}/guilds/${env.GUILD_ID}/channels`, { headers: { Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`,
        "User-Agent": "DiscordBot (https://github.com/kaizensx/form-studio, 2.0) FormStudio" } });
      const body = await r.text();
      return Response.json({ status: r.status, ms: Date.now() - t0, kv: !!env.STATE, body: r.ok ? `${JSON.parse(body).length} channels` : body.slice(0, 300) });
    }
    if (url.pathname === "/tick") {           // run the cron by hand (Actions, with the bot token as the key)
      if (request.headers.get("Authorization") !== `Bot ${env.DISCORD_BOT_TOKEN}`) return new Response("no", { status: 401 });
      const s = await tick(env);
      return Response.json({ users: Object.keys(s.xp).length, challenge: s.challenge });
    }
    const body = await request.text();
    const ok = await verify(env.PUBLIC_KEY, request.headers.get("X-Signature-Ed25519") || "",
                            request.headers.get("X-Signature-Timestamp") || "", body);
    if (!ok) return new Response("bad signature", { status: 401 });
    const i = JSON.parse(body);
    if (immediate(i)) {
      try { return Response.json(await handle(env, i)); }
      catch (e) { console.log("interaction", String(e)); return Response.json(reply({ content: "Something went wrong. Try again in a moment." })); }
    }
    // everything that calls Discord: acknowledge now (Discord allows 3 s), finish in the background, edit the reply in
    ctx.waitUntil((async () => {
      let out;
      try { out = await handle(env, i); } catch (e) { console.log("interaction", String(e)); out = reply({ content: "Something went wrong. Try again in a moment." }); }
      const data = { ...(out.data || {}) }; delete data.flags;
      const r = await fetch(`${API}/webhooks/${env.APP_ID}/${i.token}/messages/@original`, { method: "PATCH",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      if (!r.ok) console.log("follow-up", r.status, (await r.text()).slice(0, 300));
    })());
    return Response.json({ type: 5, data: { flags: ephemeral(i) ? EPHEMERAL : 0 } });
  },
  async scheduled(event, env, ctx) { ctx.waitUntil(tick(env)); },
};
