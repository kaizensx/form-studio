// The worker against a fake Discord and a fake KV, with real Ed25519 signatures.  node scripts/discord/worker/test.mjs
import assert from "node:assert/strict";
import worker, { levelOf, tick } from "./src/index.js";
import C from "./config.json" with { type: "json" };
import { COMMANDS } from "./commands.mjs";

const GUILD = "100", BOT = "900";
const N = (k) => C.names[k];
const roles = Object.values(C.roles).filter((v, i, a) => a.indexOf(v) === i).map((name, n) => ({ id: `r${n}`, name }));
const R = (name) => roles.find((r) => r.name === name).id;
const channels = [
  ...Object.entries(C.names).map(([k, name], n) => ({ id: `c${n}`, name, type: ["showcase", "guides", "help", "ideas", "challenges"].includes(k) ? 15 : 0,
      permission_overwrites: k === "mod-log" ? [{ id: GUILD, deny: "1024" }] : [] })),
];
const ch = (k) => channels.find((c) => c.name === N(k));
ch("help").available_tags = [{ id: "tSolved", name: "Solved" }, { id: "tInstall", name: "Install" }];
ch("showcase").available_tags = [{ id: "t3d", name: "3D model" }];
ch("challenges").available_tags = [{ id: "tOpen", name: "Open" }, { id: "tClosed", name: "Closed" }];
ch("general").last_message_id = "5000";
const calls = [];
const messages = { [ch("general").id]: [
  { id: "4000", type: 0, author: { id: "u1" }, timestamp: "2026-11-19T10:00:00Z" },
  { id: "4500", type: 0, author: { id: "u1" }, timestamp: "2026-11-19T10:00:30Z" },     // inside the cooldown
  { id: "5000", type: 0, author: { id: "u2" }, timestamp: "2026-11-19T10:02:00Z" },
  { id: "4900", type: 0, author: { id: BOT, bot: true }, timestamp: "2026-11-19T10:01:00Z" }] };

globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  const method = init.method || "GET";
  const json = (b, status = 200) => new Response(b === null ? null : JSON.stringify(b), { status: b === null ? 204 : status });
  const path = url.replace("https://discord.com/api/v10", "");
  const body = init.body ? JSON.parse(init.body) : undefined;
  calls.push([method, path, body]);
  if (path === `/guilds/${GUILD}/channels`) return json(channels);
  if (path === `/guilds/${GUILD}/roles`) return json(roles);
  if (path === `/guilds/${GUILD}/threads/active`) return json({ threads: [{ id: "g1", parent_id: ch("guides").id, name: C.guides[0][0] }] });
  if (path.includes("/threads/archived/public")) return json({ threads: [] });
  if (method === "POST" && path.endsWith("/threads")) return json({ id: "th1" });
  const m = path.match(/^\/channels\/(\w+)\/messages\?limit=100&after=(\w+)/);
  if (m) return json((messages[m[1]] || []).filter((x) => BigInt(x.id) > BigInt(m[2])));
  if (path === "/channels/hthread") return json({ id: "hthread", parent_id: ch("help").id, owner_id: "u1", applied_tags: ["tInstall"] });
  if (path.startsWith("/channels/c") && method === "GET" && !path.includes("/messages")) return json(channels.find((c) => path.endsWith(c.id)));
  if (method === "PUT" || method === "DELETE") return json(null);
  return json({ id: "m1" });
};

const kv = new Map();
const env = { GUILD_ID: GUILD, APP_ID: "app", DISCORD_BOT_TOKEN: "t",
  STATE: { get: async (k, t) => (kv.has(k) ? (t === "json" ? JSON.parse(kv.get(k)) : kv.get(k)) : null),
           put: async (k, v) => kv.set(k, v), delete: async (k) => kv.delete(k),
           list: async ({ prefix }) => ({ keys: [...kv.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) }) } };

const keys = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
env.PUBLIC_KEY = Buffer.from(await crypto.subtle.exportKey("raw", keys.publicKey)).toString("hex");
async function send(i, sign = true) {
  const body = JSON.stringify(i), ts = "1700000000";
  const sig = Buffer.from(await crypto.subtle.sign("Ed25519", keys.privateKey, new TextEncoder().encode(ts + body))).toString("hex");
  const pending = [];
  const r = await worker.fetch(new Request("https://bot/", { method: "POST", body,
    headers: { "X-Signature-Ed25519": sign ? sig : "00".repeat(64), "X-Signature-Timestamp": ts } }), env,
    { waitUntil: (p) => pending.push(p) });
  if (r.status !== 200) return r.status;
  const out = await r.json();
  if (out.type !== 5) return out;
  await Promise.all(pending);                    // a deferred reply: what the follow-up edited in
  const edit = calls.filter(([m, p]) => m === "PATCH" && p.includes("/messages/@original")).pop();
  return { type: 4, deferred: out.data, data: { ...edit[2], flags: out.data.flags } };
}
const member = (id, rs = []) => ({ user: { id, username: id }, roles: rs });
const cmd = (name, options = [], extra = {}) => ({ type: 2, guild_id: GUILD, channel_id: ch("general").id, member: member("u1"),
                                                   data: { name, options, ...extra } });
let ok = 0; const t = async (name, fn) => { await fn(); ok++; console.log("ok", name); };

await t("rejects a bad signature, answers PING", async () => {
  assert.equal(await send({ type: 1 }, false), 401);
  assert.deepEqual(await send({ type: 1 }), { type: 1 });
});
await t("every command has a handler and fits Discord's limits", async () => {
  for (const c of COMMANDS) { assert.ok(c.name.length <= 32); if (c.description) assert.ok(c.description.length <= 100, c.name); }
  assert.ok(COMMANDS.find((c) => c.name === "guide").options[0].choices.length === C.guides.length);
});
const noEmbeds = (r) => { assert.ok(!r.data.embeds || !r.data.embeds.length, "plain text, no embeds"); assert.ok(!/^>/m.test(r.data.content || ""), "no quote blocks"); return r; };
await t("/help, /download, /docs and /bug answer in plain text", async () => {
  assert.match(noEmbeds(await send(cmd("help"))).data.content, /Where to go/);
  const dl = noEmbeds(await send(cmd("download")));
  assert.equal(dl.data.components[0].components.length, 5);
  assert.match(dl.data.content, /FORM-macos-arm64\.zip[\s\S]*FORM-windows-x64\.zip[\s\S]*FORM-linux-x64\.tar\.gz/);
  assert.ok(dl.data.content.length <= 2000);
  const docs = noEmbeds(await send(cmd("docs")));
  assert.equal((docs.data.content.match(/^- \[/gm) || []).length, C.docs_pages.length);
  assert.ok(docs.data.content.length <= 2000);
  const one = await send(cmd("docs", [{ name: "topic", value: C.docs_pages[2][0] }]));
  assert.equal((one.data.content.match(/^- \[/gm) || []).length, 1);
  const ac = await send({ type: 4, guild_id: GUILD, member: member("u1"), data: { name: "docs", options: [{ name: "topic", value: "mcp", focused: true }] } });
  assert.ok(ac.data.choices.length >= 1 && ac.data.choices.every((c) => /mcp/i.test(c.name)));
  const bug = noEmbeds(await send(cmd("bug")));
  assert.match(bug.data.content, /form setup --check/);
  assert.match(bug.data.components[0].components[0].url, /template=1-bug\.yml/);
  assert.ok(bug.data.content.length <= 2000);
});
await t("Report to moderators: to #mod-log once, nobody pinged, the reporter told in private", async () => {
  const i = (who) => ({ type: 2, guild_id: GUILD, channel_id: ch("general").id, member: member(who),
    data: { name: "Report to moderators", type: 3, resolved: { messages: { m7: { id: "m7", content: "buy @everyone cheap", author: { id: "u9" } } } } } });
  calls.length = 0;
  const r = await send(i("u1"));
  assert.match(r.data.content, /moderators have your report/);
  assert.equal(r.deferred.flags, 64);
  const post = calls.find(([m, p]) => m === "POST" && p === `/channels/${ch("mod-log").id}/messages`);
  assert.match(post[2].content, /<@u1> reported a message by <@u9>/);
  assert.deepEqual(post[2].allowed_mentions, { parse: [] });
  assert.ok(!post[2].content.includes("@everyone"));
  calls.length = 0;
  assert.match((await send(i("u1"))).data.content, /already reported/);
  assert.ok(!calls.some(([m, p]) => m === "POST" && p.endsWith("/messages")));
  const own = await send({ ...i("u9") });
  assert.match(own.data.content, /your own message/);
});
await t("/guide links the guide's own post", async () => {
  const r = await send(cmd("guide", [{ name: "topic", value: C.guides[0][0] }]));
  assert.match(noEmbeds(r).data.content, /<#g1>/);
  assert.match(r.data.components[0].components[0].url, /docs\/community\/.*\.md$/);
});
await t("/thanks: not yourself, three a day, XP via a bonus", async () => {
  assert.match((await send(cmd("thanks", [{ name: "user", value: "u1" }]))).data.content, /someone else/);
  for (let n = 0; n < 3; n++) assert.match((await send(cmd("thanks", [{ name: "user", value: "u2" }], { resolved: { users: { u2: { id: "u2" } } } }))).data.content, /thanks <@u2>/);
  assert.match((await send(cmd("thanks", [{ name: "user", value: "u2" }], { resolved: { users: { u2: { id: "u2" } } } }))).data.content, /tomorrow/);
  assert.equal([...kv.keys()].filter((k) => k.startsWith("bonus:")).length, 3);
});
await t("/poll builds a native poll", async () => {
  const r = await send(cmd("poll", [{ name: "question", value: "Next?" }, { name: "options", value: "A; B; C" }]));
  assert.equal(r.data.poll.answers.length, 3);
});
await t("role picker adds and removes within its group only", async () => {
  calls.length = 0;
  const sys = C.picker.find(([k]) => k === "system")[2];
  const r = await send({ type: 3, guild_id: GUILD, member: member("u1", [R(sys[1]), R("Maintainer")]),
                         message: { flags: 64 }, data: { custom_id: "roles:system", values: [R(sys[0])] } });
  assert.match(r.data.content, /Added/);
  assert.ok(calls.some(([m, p]) => m === "PUT" && p.endsWith(`/roles/${R(sys[0])}`)));
  assert.ok(calls.some(([m, p]) => m === "DELETE" && p.endsWith(`/roles/${R(sys[1])}`)));
  assert.ok(!calls.some(([, p]) => p.endsWith(`/roles/${R("Maintainer")}`)));
});
await t("the shared #roles menu toggles only what was picked", async () => {
  calls.length = 0;
  const pings = C.picker.find(([k]) => k === "pings")[2];
  const r = await send({ type: 3, guild_id: GUILD, member: member("u1", [R(pings[0]), R(pings[1])]), message: { flags: 0 },
                         data: { custom_id: "roles:pings", values: [R(pings[1])] } });
  assert.match(r.data.content, /removed/);
  assert.ok(calls.some(([m, p]) => m === "DELETE" && p.endsWith(`/roles/${R(pings[1])}`)));
  assert.ok(!calls.some(([, p]) => p.endsWith(`/roles/${R(pings[0])}`)));     // the role not picked is left alone
});
await t("showcase: a modal, then a forum post with XP", async () => {
  assert.equal((await send(cmd("showcase"))).type, 9);
  const v = (id, value) => ({ type: 1, components: [{ custom_id: id, value }] });
  const r = await send({ type: 5, guild_id: GUILD, member: member("u1"), data: { custom_id: "showcase",
    components: [v("title", "Clip"), v("story", "Holds cables"), v("setup", "P1S"), v("image", "https://x/i.png"), v("file", "")] } });
  assert.match(r.data.content, /<#th1>/);
  const post = calls.find(([m, p]) => m === "POST" && p.endsWith("/threads"));
  assert.deepEqual(post[2].applied_tags, ["t3d"]);
  assert.ok(!post[2].message.embeds && /Made by <@u1>[\s\S]*Holds cables[\s\S]*https:\/\/x\/i\.png/.test(post[2].message.content));
});
await t("Mark as solved: only the asker, tags Solved, rewards the helper", async () => {
  const i = (who) => ({ type: 2, guild_id: GUILD, channel_id: "hthread", member: member(who),
    data: { name: "Mark as solved", type: 3, resolved: { messages: { m9: { id: "m9", author: { id: "u2" } } } } } });
  assert.match((await send(i("u3"))).data.content, /Only the person/);
  calls.length = 0;
  assert.match((await send({ ...i("u3"), member: member("u3", [R("Moderator")]) })).data.content, /Solved/);   // staff may
  calls.length = 0;
  assert.match((await send(i("u1"))).data.content, /Solved.*u2/);
  assert.deepEqual(calls.find(([m, p]) => m === "PATCH" && p === "/channels/hthread")[2].applied_tags, ["tInstall", "tSolved"]);
});
await t("cron: XP with cooldown, no bots, bonuses folded in, a challenge opened", async () => {
  const s = await tick(env);
  assert.equal(s.xp.u1.msgs, 2);
  assert.ok(s.xp.u1.xp >= 15 + C.xp.showcase && s.xp.u1.xp <= 25 + C.xp.showcase);   // one message counted (cooldown) + showcase
  assert.ok(s.xp.u2.xp >= 15 + 3 * C.xp.thanks + C.xp.solved);
  assert.equal(s.xp.u2.kudos, 3);
  assert.equal(s.xp[BOT], undefined);
  assert.equal([...kv.keys()].filter((k) => k.startsWith("bonus:")).length, 0);
  assert.equal(s.challenge.thread, "th1");
  const opened = calls.filter(([m, p]) => m === "POST" && p === `/channels/${ch("challenges").id}/threads`).pop();
  assert.ok(!opened[2].message.embeds && opened[2].message.content.startsWith("# "));
  assert.ok(s.challenge.closes > Date.now());
  const again = await tick(env);                                  // nothing is counted twice
  assert.equal(again.xp.u1.msgs, 2);
});
await t("levels follow 5n²+50n+100", async () => {
  assert.deepEqual(levelOf(0), { level: 0, into: 0, next: 100 });
  assert.equal(levelOf(100 + 155).level, 2);
});
console.log(`${ok} worker tests passed`);
