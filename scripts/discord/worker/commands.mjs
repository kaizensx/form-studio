// The bot's slash commands and its message commands, registered for the Form Studio server.
//   DISCORD_BOT_TOKEN=... APP_ID=... GUILD_ID=... node scripts/discord/worker/commands.mjs
import C from "./config.json" with { type: "json" };

const STR = 3, INT = 4, BOOL = 5, USER = 6;
export const COMMANDS = [
  { name: "help", description: "Where to ask, learn and find things" },
  { name: "guide", description: "Show a Form Studio guide", options: [{ type: STR, name: "topic", description: "Which guide",
    required: true, choices: C.guides.slice(0, 25).map(([t]) => ({ name: t.slice(0, 100), value: t.slice(0, 100) })) }] },
  { name: "docs", description: "Find a page of the documentation", options: [{ type: STR, name: "topic",
    description: "What you are looking for (empty: every page)", autocomplete: true }] },
  { name: "download", description: "Download Form Studio for macOS, Windows or Linux" },
  { name: "bug", description: "How to report a bug so it gets fixed" },
  { name: "showcase", description: "Post something you designed to show-and-tell" },
  { name: "challenge", description: "This week's design challenge" },
  { name: "roles", description: "Pick your system, agent, what you make and your pings" },
  { name: "rank", description: "Your level and XP", options: [{ type: USER, name: "user", description: "Someone else's" }] },
  { name: "leaderboard", description: "The most active makers" },
  { name: "thanks", description: "Thank someone who helped (+XP for them)", options: [
    { type: USER, name: "user", description: "Who helped", required: true },
    { type: STR, name: "for", description: "What for", max_length: 200 }] },
  { name: "poll", description: "Ask the server a question", options: [
    { type: STR, name: "question", description: "The question", required: true, max_length: 300 },
    { type: STR, name: "options", description: "Answers separated by ;  (2 to 10)", required: true },
    { type: INT, name: "hours", description: "How long it runs (default 24)", min_value: 1, max_value: 168 },
    { type: BOOL, name: "multiple", description: "Allow several answers" }] },
  { name: "Mark as solved", type: 3 },
  { name: "Report to moderators", type: 3 },
];

if (import.meta.url === `file://${process.argv[1]}`) {
  const r = await fetch(`https://discord.com/api/v10/applications/${process.env.APP_ID}/guilds/${process.env.GUILD_ID}/commands`, {
    method: "PUT", headers: { Authorization: `Bot ${process.env.DISCORD_BOT_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(COMMANDS) });
  const out = await r.json();
  if (!r.ok) { console.error(JSON.stringify(out).slice(0, 800)); process.exit(1); }
  console.log(`registered ${out.length} commands: ${out.map((c) => c.name).join(", ")}`);
}
