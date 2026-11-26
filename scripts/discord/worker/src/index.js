// The Form Studio bot, live: slash commands, buttons, the role picker, the showcase form, reports to moderators,
// levels and the weekly challenge. A Cloudflare Worker that Discord calls for every interaction (signed with the
// app's public key), plus a cron that counts XP and runs the challenge. Everything it says is plain text: no embeds. Channel names, roles and texts come from config.json, written from
// scripts/discord/server.py. Secrets: DISCORD_BOT_TOKEN. Vars: APP_ID, PUBLIC_KEY, GUILD_ID. KV: STATE.
import C from "../config.json" with { type: "json" };

const API = "https://discord.com/api/v10";
const EPHEMERAL = 64;
const NO_PREVIEWS = 4;             // SUPPRESS_EMBEDS: links stay links, with no preview box under the text
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
const reply = (data, ephemeral = true) => ({ type: 4, data: { allowed_mentions: { parse: [] }, ...data,
                                                              flags: (ephemeral ? EPHEMERAL : 0) | NO_PREVIEWS } });
const linkBtn = (label, url) => ({ type: 2, style: 5, label, url });
const btn = (label, id, style = 2) => ({ type: 2, style, label, custom_id: id });
const clean = (text) => String(text || "").replace(/@/g, "@\u200b");       // what a member typed never pings anyone
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

// ---- guides ----------------------------------------------------------------------------------------------------------
async function guideThreads(env) {
  const g = await chan(env, "guides");
  if (!g) return {};
  const [active, archived] = await Promise.all([api(env, "GET", `/guilds/${env.GUILD_ID}/threads/active`),
                                                api(env, "GET", `/channels/${g.id}/threads/archived/public?limit=100`)]);
  const out = {};
  for (const t of [...active.threads, ...archived.threads]) if (t.parent_id === g.id) out[t.name] = t.id;
  return out;
}
// ---- commands --------------------------------------------------------------------------------------------------------
async function cmdHelp(env) {
  return reply({ content:
    `## Where to go\n` +
    `- **Stuck?** Post in ${await mention(env, "help")} with a tag. The bot answers with the right guide, a person follows.\n` +
    `- **Learning?** ${await mention(env, "guides")} has complete guides; \`/guide\` shows one, \`/docs\` finds a page of the documentation.\n` +
    `- **Installing?** \`/download\`, then the guide Getting started.\n` +
    `- **A bug you can reproduce?** \`/bug\` shows how to report it so it gets fixed.\n` +
    `- **An idea?** ${await mention(env, "ideas")}. **Something you made?** ${await mention(env, "showcase")} or \`/showcase\`.\n` +
    `- **Agents and models:** ${await mention(env, "agents")} · **Mesh to CAD:** ${await mention(env, "mesh-to-cad")} · **Game assets:** ${await mention(env, "game-assets")}\n` +
    `- **3D printing (optional):** ${await mention(env, "printers")}\n` +
    `- **Someone breaking the rules?** Right-click the message › Apps › Report to moderators.`,
    components: [row(linkBtn("Docs", C.docs), linkBtn("Download", C.repo + "/releases/latest"), linkBtn("GitHub", C.repo))] });
}

async function cmdGuide(env, i) {
  const want = opt(i, "topic");
  const g = C.guides.find(([t]) => t === want) || C.guides[0];
  const threads = await guideThreads(env);
  const where = threads[g[0]] ? `<#${threads[g[0]]}>` : await mention(env, "guides");
  return reply({ content: `## ${g[0]}\n${g[2]}\n\nRead it here: ${where}`,
                 components: [row(linkBtn("The same guide on GitHub", g[3]), linkBtn("All docs", C.docs))] }, false);
}

function cmdDocs(i) {
  const want = opt(i, "topic");
  const pages = want ? C.docs_pages.filter(([n]) => n === want) : C.docs_pages;
  const list = (pages.length ? pages : C.docs_pages).map(([n, u]) => `- [${n}](${u})`).join("\n");
  return reply({ content: `## Documentation\n${list}\n\nThe guides on this server: \`/guide\`.` }, !want);
}

async function cmdBug(env) {
  return reply({ content:
    `## Reporting a bug\n` +
    `A bug is something you can reproduce. It goes to GitHub, where it is tracked until it is fixed. Not sure it is a bug? Ask in ${await mention(env, "help")} first.\n\n` +
    `**A report that gets fixed fast has**\n` +
    `1. **What happened:** what you did, step by step, what you expected, and what Form Studio did instead.\n` +
    `2. **Your Form Studio version** (About, or \`form update --check\`) and **your operating system**.\n` +
    `3. **Your agent and model**, and your slicer and printer if they were involved.\n` +
    `4. **The output of** \`form setup --check\`. You can remove home folder paths.\n` +
    `5. **A screenshot**, and the design's \`.formstudio\` file (renamed to \`.zip\`) when a design shows the problem.\n\n` +
    `Search the open issues first: if yours is there, add what you know to it.\n` +
    `**Security problems are never posted in public.** Report them privately with the button below.`,
    components: [row(linkBtn("Open a bug report", C.repo + "/issues/new?template=1-bug.yml"), linkBtn("Search issues", C.repo + "/issues"),
                     linkBtn("Report a vulnerability", C.repo + "/security/advisories/new"))] }, false);
}

async function autocomplete(env, i) {
  const focused = (i.data.options || []).find((o) => o.focused);
  const q = String(focused?.value || "").toLowerCase();
  let choices = [];
  if (i.data.name === "docs") {
    choices = C.docs_pages.filter(([n]) => !q || n.toLowerCase().includes(q)).slice(0, 25).map(([n]) => ({ name: n, value: n }));
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
  return reply({ content: `## Level ${level}\n<@${who}> · \`${bar(into, next)}\` ${into} / ${next} XP\n` +
      `Rank **#${place || "—"}** · ${me.msgs || 0} messages · ${me.kudos || 0} thanks` +
      (nextRole ? `\nNext role: **${nextRole[1]}** at level ${nextRole[0]}` : "\nEvery level role earned.") }, false);
}

async function cmdLeaderboard(env) {
  const s = await load(env);
  const top = Object.entries(s.xp).sort((a, b) => b[1].xp - a[1].xp).slice(0, 10);
  const lines = top.map(([u, v], n) => `${n + 1}. <@${u}> · level ${levelOf(v.xp).level} · ${v.xp} XP`);
  return reply({ content: `## Most active makers\n` + (lines.join("\n") || "Nobody has XP yet. Say hello in #general to be first.") }, false);
}

async function cmdThanks(env, i) {
  const from = userOf(i).id, to = opt(i, "user");
  const target = i.data.resolved?.users?.[to];
  if (!to || to === from || target?.bot) return reply({ content: "Thank someone else: not yourself, and not a bot." });
  const s = await load(env);
  const day = new Date().toISOString().slice(0, 10);
  const t = s.thanks[from]?.day === day ? s.thanks[from] : { day, count: 0 };
  if (t.count >= C.xp.thanks_per_day) return reply({ content: `You have thanked ${C.xp.thanks_per_day} people today. More tomorrow.` });
  t.count++; s.thanks[from] = t;
  await save(env, s);
  await bonus(env, to, C.xp.thanks, "thanks");
  const why = opt(i, "for");
  return { type: 4, data: { content: `<@${from}> thanks <@${to}>${why ? `: ${clean(why)}` : "."} (+${C.xp.thanks} XP)`,
                            allowed_mentions: { users: [to] }, flags: NO_PREVIEWS } };
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
  const tags = Object.fromEntries((forum.available_tags || []).map((t) => [t.name, t.id]));
  const text = `Made by <@${u.id}>\n\n${clean(v.story)}` + (v.setup ? `\n\n**Made with:** ${clean(v.setup)}` : "") + (img ? `\n${img}` : "");
  const t = await api(env, "POST", `/channels/${forum.id}/threads`, {
    name: v.title.slice(0, 100), applied_tags: [tags["3D model"]].filter(Boolean),
    message: { content: text.slice(0, 2000), allowed_mentions: { parse: [] },
               components: /^https:\/\//.test(v.file) ? [row(linkBtn("Download the design", v.file))] : [] } });
  await bonus(env, u.id, C.xp.showcase, "showcase");
  return reply({ content: `Posted: <#${t.id}> (+${C.xp.showcase} XP). Add photos by replying in it.` });
}

async function cmdChallenge(env) {
  const s = await load(env);
  const c = s.challenge;
  if (!c) return reply({ content: `The first challenge opens shortly in ${await mention(env, "challenges")}.` });
  const [title, brief, rule] = C.challenges[c.index % C.challenges.length];
  return reply({ content: `## This week: ${title}\n${brief}\n\n**To count:** ${rule}\n\nPost your entry in <#${c.thread}>. Closes <t:${Math.floor(c.closes / 1000)}:R>.` }, false);
}

function cmdPoll(i) {
  const q = opt(i, "question");
  const answers = String(opt(i, "options")).split(/[;|\n]/).map((x) => x.trim()).filter(Boolean).slice(0, 10);
  if (answers.length < 2) return reply({ content: "Give at least two options, separated by `;`." });
  return { type: 4, data: { poll: { question: { text: q.slice(0, 300) }, duration: Math.min(168, Math.max(1, opt(i, "hours") || 24)),
    allow_multiselect: !!opt(i, "multiple"), answers: answers.map((a) => ({ poll_media: { text: a.slice(0, 55) } })) } } };
}

function cmdDownload() {
  const d = (file) => `${C.repo}/releases/latest/download/${file}`;
  return reply({ content:
    `## Download Form Studio\nFree and open source, for macOS, Windows and Linux. The first start installs what it needs after asking you.\n\n` +
    `- **macOS, Apple silicon:** [FORM-macos-arm64.zip](${d("FORM-macos-arm64.zip")}). Unzip, then right-click **Form Studio.app** › **Open** the first time.\n` +
    `- **macOS, Intel:** [FORM-macos-x64.zip](${d("FORM-macos-x64.zip")}). The same.\n` +
    `- **Windows 10 and 11:** [FORM-windows-x64.zip](${d("FORM-windows-x64.zip")}). Unzip and run \`FORM.exe\`; in SmartScreen choose **More info** › **Run anyway**.\n` +
    `- **Linux x64:** [FORM-linux-x64.tar.gz](${d("FORM-linux-x64.tar.gz")}). Unpack and run \`FORM/FORM\`.\n\n` +
    `Or from a terminal on macOS and Linux:\n\`\`\`bash\ncurl -LsSf https://raw.githubusercontent.com/kaizensx/form-studio/main/install.sh | sh\nform app\n\`\`\`\n` +
    `Every release ships with \`SHA256SUMS\`. The guide Getting started (\`/guide\`) covers each system and your first design.`,
    components: [row(linkBtn("macOS (Apple silicon)", d("FORM-macos-arm64.zip")), linkBtn("macOS (Intel)", d("FORM-macos-x64.zip")),
                     linkBtn("Windows", d("FORM-windows-x64.zip")), linkBtn("Linux", d("FORM-linux-x64.tar.gz")),
                     linkBtn("All releases", C.repo + "/releases"))] }, false);
}

async function rolePicker(env, i) {
  const member = i.member;
  const g = await guild(env);
  const rows = C.picker.map(([key, placeholder, names]) => {
    const options = names.map((n) => g.roles.find((r) => r.name === n)).filter(Boolean)
      .map((r) => ({ label: r.name, value: r.id, ...(C.role_emoji[r.name] ? { emoji: { name: C.role_emoji[r.name] } } : {}),
                     default: (member?.roles || []).includes(r.id) }));
    return row({ type: 3, custom_id: `roles:${key}`, placeholder, min_values: 0, max_values: options.length, options });
  });
  return reply({ content: "Pick what fits; what you leave out is removed.", components: rows });
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
  return reply({ content: say ? `${say}.` : "Nothing changed." });
}

async function markSolved(env, i) {
  const t = await api(env, "GET", `/channels/${i.channel_id}`);
  const helpF = await chan(env, "help");
  if (!helpF || t.parent_id !== helpF.id) return reply({ content: "Mark as solved works inside a post in the help forum." });
  const u = userOf(i).id;
  if (t.owner_id !== u && !(await isStaff(env, i))) return reply({ content: "Only the person who asked (or a maintainer) can mark it solved." });
  const solved = (helpF.available_tags || []).find((x) => x.name === "Solved");
  if (solved) await api(env, "PATCH", `/channels/${t.id}`, { applied_tags: [...new Set([...(t.applied_tags || []), solved.id])].slice(0, 5) });
  const msg = Object.values(i.data.resolved.messages)[0];
  const helper = msg.author.id;
  if (helper !== u && !msg.author.bot) await bonus(env, helper, C.xp.solved, "solved");
  return { type: 4, data: { flags: NO_PREVIEWS, content: `**Solved.** The answer: ${`https://discord.com/channels/${env.GUILD_ID}/${t.id}/${msg.id}`}` +
    (helper !== u && !msg.author.bot ? ` · thank you <@${helper}> (+${C.xp.solved} XP)` : ""), allowed_mentions: { users: [helper] } } };
}

async function isStaff(env, i) {
  const g = await guild(env);
  const ids = C.staff.map((n) => g.roles.find((r) => r.name === n)?.id).filter(Boolean);
  return (i.member?.roles || []).some((r) => ids.includes(r));
}

// "Report to moderators" on a message: the report goes to #mod-log with a link; only the reporter sees the answer
async function reportMessage(env, i) {
  const msg = Object.values(i.data.resolved?.messages || {})[0];
  const log = await chan(env, "mod-log");
  if (!msg || !log) return reply({ content: "The report could not be sent. Please tell a moderator directly." });
  const from = userOf(i).id;
  if (msg.author?.id === from) return reply({ content: "That is your own message. You can edit or delete it yourself." });
  const key = `report:${msg.id}:${from}`;
  if (await env.STATE.get(key)) return reply({ content: "You already reported that message. The moderators have it." });
  await env.STATE.put(key, "1", { expirationTtl: 7 * 24 * 3600 });
  const where = `https://discord.com/channels/${env.GUILD_ID}/${i.channel_id}/${msg.id}`;
  const text = clean(msg.content || "").replace(/\s+/g, " ").slice(0, 600) || "(no text: a picture, a file or an embed)";
  await api(env, "POST", `/channels/${log.id}/messages`, { flags: NO_PREVIEWS, allowed_mentions: { parse: [] },
    content: `**Report** · <@${from}> reported a message by <@${msg.author?.id}> in <#${i.channel_id}>\n${where}\n\n${text}` });
  return reply({ content: "Thank you. The moderators have your report; only they can see it." });
}

async function startHere(env) {
  return reply({ content:
    `## Where do I start?\n` +
    `1. Read ${await mention(env, "rules")}, then pick your roles: your system, your agent and the pings you want.\n` +
    `2. Open ${await mention(env, "guides")} and read **Getting started**: install, the first start and your first design.\n` +
    `3. Download Form Studio (\`/download\`) and describe something small you need.\n` +
    `4. Show it in ${await mention(env, "showcase")}, or enter ${await mention(env, "challenges")}.\n` +
    `5. Stuck? ${await mention(env, "help")}. Everyone was a beginner once.`,
    components: [row(btn("Pick my roles", "open:roles", 1), linkBtn("Download", C.repo + "/releases/latest"))] });
}

// ---- interactions ----------------------------------------------------------------------------------------------------
export async function handle(env, i) {
  if (i.type === 1) return { type: 1 };
  if (i.type === 4) return autocomplete(env, i);
  if (i.type === 2) {
    switch (i.data.name) {
      case "help": return cmdHelp(env);
      case "guide": return cmdGuide(env, i);
      case "rank": return cmdRank(env, i);
      case "leaderboard": return cmdLeaderboard(env);
      case "thanks": return cmdThanks(env, i);
      case "showcase": return cmdShowcaseModal();
      case "challenge": return cmdChallenge(env);
      case "poll": return cmdPoll(i);
      case "download": return cmdDownload();
      case "docs": return cmdDocs(i);
      case "bug": return cmdBug(env);
      case "Report to moderators": return reportMessage(env, i);
      case "roles": return rolePicker(env, i);
      case "Mark as solved": return markSolved(env, i);
    }
  }
  if (i.type === 3) {
    const id = i.data.custom_id;
    if (id.startsWith("roles:")) return rolesChosen(env, i);
    if (id === "open:roles") return rolePicker(env, i);
    if (id === "open:start") return startHere(env);
  }
  if (i.type === 5 && i.data.custom_id === "showcase") return showcaseSubmit(env, i);
  return reply({ content: "That did not work. Try again in a moment." });
}

// answered at once: PING, autocomplete, the showcase form, and commands that need nothing from Discord
const INSTANT = new Set(["showcase", "poll", "download", "docs"]);
function immediate(i) { return i.type === 1 || i.type === 4 || (i.type === 2 && INSTANT.has(i.data.name)); }
const PUBLIC = new Set(["guide", "rank", "leaderboard", "thanks", "challenge", "Mark as solved", "bug"]);
function ephemeral(i) {
  if (i.type !== 2 || !PUBLIC.has(i.data.name)) return true;
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
      if (general) await api(env, "POST", `/channels/${general.id}/messages`, { content: `<@${u}> reached level ${level} and is now **${earned[1].name}**.`,
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
  const text = win ? `**${title}** is won by <@${win.m.author.id}> with ${win.stars} ${STAR}. Congratulations!`
                   : `**${title}** closed with ${entries.length} entr${entries.length === 1 ? "y" : "ies"} and no stars. Next week's brief is open.`;
  await api(env, "POST", `/channels/${c.thread}/messages`, { content: text, allowed_mentions: { users: win ? [win.m.author.id] : [] } });
  if (win) { const r = await role(env, "Challenge winner"); if (r) await api(env, "PUT", `/guilds/${env.GUILD_ID}/members/${win.m.author.id}/roles/${r.id}`); }
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
  const ping = await role(env, "Challenge pings");
  const t = await api(env, "POST", `/channels/${forum.id}/threads`, {
    name: `Week ${index + 1}: ${title}`.slice(0, 100), applied_tags: open ? [open.id] : [], auto_archive_duration: 10080,
    message: { allowed_mentions: { roles: ping ? [ping.id] : [] }, flags: NO_PREVIEWS,
      content: `# ${title}\n${brief}\n\n**To count:** ${rule}\n\n` +
        `- **Enter:** reply here with a render or a photo, and how you made it.\n` +
        `- **Vote:** react ${STAR} on the entries you like.\n` +
        `- **Closes:** <t:${Math.floor(closes / 1000)}:F> (<t:${Math.floor(closes / 1000)}:R>). The most starred entry wins the Challenge winner role.` +
        (ping ? `\n\n-# <@&${ping.id}> a new challenge is open. Change this ping in #roles.` : ""),
      components: [row(linkBtn("Download Form Studio", C.repo + "/releases/latest"), linkBtn("Docs", C.docs))] } });
  s.challenge = { index, thread: t.id, opened: Date.now(), closes };
  try {     // the challenge in the server's Events tab
    await api(env, "POST", `/guilds/${env.GUILD_ID}/scheduled-events`, { name: `Challenge: ${title}`.slice(0, 100), privacy_level: 2,
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
      const data = { ...(out.data || {}) }; data.flags = (data.flags || 0) & NO_PREVIEWS;
      const r = await fetch(`${API}/webhooks/${env.APP_ID}/${i.token}/messages/@original`, { method: "PATCH",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      if (!r.ok) console.log("follow-up", r.status, (await r.text()).slice(0, 300));
    })());
    return Response.json({ type: 5, data: { flags: ephemeral(i) ? EPHEMERAL : 0 } });
  },
  async scheduled(event, env, ctx) { ctx.waitUntil(tick(env)); },
};
