# Agents and MCP: Claude Code, Codex and others

Form Studio is an MCP server as well as an app. Add it once to your agent and the agent can design, check, review and prepare a release from its own window, while the open app follows along. This guide covers the agents inside the app, connecting an outside agent, and the rules every agent works under.

## Two ways to work with an agent

- **Inside the app.** Each conversation picks its agent, model and reasoning effort. Form Studio starts the agent, gives it its tools and shows its steps, the views it rendered, and the time, tokens and cost of every reply.
- **From the agent's own window.** Claude Code in a terminal, Codex, Cursor or any MCP client calls Form Studio's tools. When that agent changes a design, the open app shows the new revision, labelled with the agent that made it.

Both use the same engine, the same checks and the same refusals.

## Agents and models the app can run

- **Agent apps:** Claude Code, Codex, Gemini CLI, Cursor CLI, OpenCode, Qwen Code and GitHub Copilot CLI. Each runs on your own account.
- **Model APIs:** Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, DeepSeek and Groq, found from your keys. No agent app is needed: Form Studio runs the conversation and gives the model its tools.
- **Local models:** Ollama, LM Studio and llama.cpp, found from their running servers.
- **Any other provider:** Settings › Agents & models › **Add a provider…** (or `form providers add URL`) takes a base URL and an optional key, finds the format (OpenAI-, Anthropic- or Gemini-compatible, or Ollama), reads the models and which of them call tools, and shows what it found before you save.

Keys are kept in Form Studio's private secrets file and never shown again. Models without tool calls are left out of the model menu, because a model that cannot call tools cannot design here.

## Connect an outside agent

The quick way: run `form setup`. It finds the agents on your computer and writes the entry for each.

By hand:

**Claude Code**

```bash
claude mcp add --scope user form -- form-mcp
```

Thirteen design skills (intake, parametric design, industrial design, assemblies and mechanisms, design review and more) install as a plugin:

```bash
claude plugin marketplace add kaizensx/form-studio
claude plugin install form@form-studio
```

**Codex**

```bash
codex mcp add form -- form-mcp
```

**Gemini CLI** (`~/.gemini/settings.json`), **Cursor** (`~/.cursor/mcp.json`), **Claude Desktop** and any other MCP client:

```json
{ "mcpServers": { "form": { "command": "form-mcp" } } }
```

Restart Claude Desktop after adding it. `form mcp` is the same server as `form-mcp`.

If you added Form Studio to an agent by the old Mac app's path (FORM.app), add it again: the app is now called Form Studio.app, and `form setup` writes the new entry.

## What an agent does, step by step

- **See what exists:** `form_overview`.
- **Start a design from its own code:** `design_guide`, then `create_design`. For a complex design, `design_brief` first.
- **Offer concepts for a new idea:** `propose_concepts`, then you pick (`pick_concept`).
- **Look at it:** `render` (`view="sheet"` gives four views).
- **Try a change without saving:** `preview_change`.
- **Keep a change:** `commit_change` with `expect_head`, so a newer revision is never overwritten.
- **Read the design and its checks:** `get_project`.
- **Ask you for a number you can measure:** `ask_measurement`.
- **Ask for a release:** `request_release`. It returns a link that opens the release in Form Studio. You approve there.

Every tool with its arguments is in the [MCP reference](https://github.com/kaizensx/form-studio/blob/main/docs/MCP.md). The guide written for coding agents is [AGENTS.md](https://github.com/kaizensx/form-studio/blob/main/AGENTS.md).

## The rules every agent follows

- Units are millimetres, degrees and grams.
- Preview before commit.
- Provenance is evidence. A value is "measured" only when you measured it and told the agent the number. An agent never invents a physical result.
- No agent can approve a release, start a print or send your files anywhere.
- An agent is told whether you print and what each design is for, so a designer is never asked about a printer.

## Without MCP: the command line

Every action is a `form` command that prints JSON, and every MCP tool can be called as `form tool NAME '{json}'`.

```bash
form start --text "a planetary stage, 1:5, on a 5 mm shaft" --purpose model
form start --text "a hook for my headphones under the desk" --photo desk.jpg
form chat "Make the base 92 mm deep" --project desk-stand --agent codex
form commit desk-stand lean=18 --expect-head 1
form tool get_project '{"project": "desk-stand"}'
form tool            # every MCP tool with a one-line summary
```

`form chat` asks the agent's questions in the terminal. The full list is in the [CLI reference](https://github.com/kaizensx/form-studio/blob/main/docs/CLI.md).

## Getting good designs from your agent

- **Say what it is for and what it must fit.** The agent asks only what changes fit, load or safety and cannot be looked up.
- **Give numbers with their source.** "The shaft is 5.0 mm, measured with calipers" is worth more than "a small shaft".
- **Let complex designs be staged.** For a mechanism, a styled form, a texture or several parts, the agent writes a brief and a feature plan first, then builds, then critiques its own result on renders and metrics computed from the solid.
- **Use reasoning effort.** A mesh to make editable, a mechanism, a styled form, a texture or several parts runs at high effort automatically.
- **Retry with another model.** Any reply can be retried with a different model, and **Fork from here** on a message starts a branch of the conversation from that point.
- **Use Fix.** Failed checks, pipeline steps, drafts that do not build and renders have a **Fix** button that sends the failure, with its evidence, to the design's conversation.

## When the agent does not answer

- Open **Settings › Engines & software** (or run `form setup --check`): it shows whether the agent was found and whether it is signed in.
- Sign in once in the agent's own terminal (for example `claude`, `codex`, `cursor-agent login`, `opencode auth login`) or add an API key in Settings › Agents & models.
- An agent that reached its plan's limit is named, with when it can work again and what is kept.
- Still stuck: post in #help with the tag **Agents & models**, your agent, your model and what `form setup --check` printed.

Talk about which agents and models design best in #agents-and-models.
