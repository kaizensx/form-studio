# Troubleshooting and reporting bugs

Most problems are one of five things: the app will not open, something was not found on your computer, the agent does not answer, a design does not build, or a slice fails. This guide walks through each, then shows how to ask for help and how to write a bug report that gets fixed fast.

## First: see what Form Studio found

Open **Settings › Software**, or run:

```bash
form setup --check
```

It lists what Form Studio found on your computer, which slicers and agents it can use, and how to fix each gap. `form doctor` prints the kernel, slicer, printer, purpose and agents it found. `form setup` offers to fix what is missing, showing every command before it runs (`--dry-run` only shows them).

## The app will not open

- **macOS:** the first time, right-click **Form Studio.app** and choose **Open**.
- **Windows:** in SmartScreen choose **More info**, then **Run anyway**.
- **Linux:** unpack the archive and run `FORM/FORM`. The packaged app needs glibc 2.35 or newer.
- **Check the download.** Compare the file's SHA-256 with `SHA256SUMS` on the release page, and download it again if they differ.
- **Run from source** to see the error: the commands are in the guide **Contributing**.

## The agent does not answer

- Settings › Software shows whether the agent app was found and whether it is signed in.
- Sign in once in the agent's own terminal, or add an API key in **Settings › Agents**. Keys are stored privately and never shown again.
- A local model must be running: Form Studio finds Ollama, LM Studio and llama.cpp from their running servers.
- A model that cannot call tools is left out of the model menu. If your model is missing, that is usually why.
- An agent that reached its plan's limit is named, with when it can work again.
- An outside agent (Claude Code in a terminal, Cursor) cannot see Form Studio: run `form setup` again so it rewrites the MCP entry. On macOS, an entry that points at the old FORM.app path must be added again.

## A design does not build, or a check fails

- Press **Fix**. Failed checks, pipeline steps, slices, drafts that do not build and Blender renders have a Fix button that sends the failure, with its evidence, to the design's conversation.
- Constraints refuse impossible combinations and say which feature, which parameters and a way forward. Read the message: it names the fix.
- Nothing is lost. Every commit is a revision; go back to any earlier one in the timeline.
- A check that is "heuristic" is a stated rule of thumb. It asks for a look, not for obedience.

## A slice fails, or the printer is wrong

- Printing must be on: **Settings › General › Set up for**.
- Form Studio reads the printer, filament and process from your slicer. Open the slicer once and set up your printer there.
- When a program's version outside the supported range is why something failed, the error names the supported versions and what to do.
- The slicers and versions tested are in [Compatibility and testing](https://github.com/kaizensx/form-studio/blob/main/docs/VERIFICATION.md).

## An optional engine will not install

- The install log in Settings › Software shows every command and where it stopped.
- A failed or cancelled install leaves nothing new behind, so it is safe to press Install again.
- CAD-Recode needs about 4 GB free, and the CADEvolve corpus is a 4.73 GB download.

## Ask for help

Post in #help: one post per question, with a tag. Include:

- your operating system and your Form Studio version (About, or `form update --check`)
- your agent and model, and what you asked for
- what you did, what you expected and what happened
- for setup problems, the output of `form setup --check` (you can remove home folder paths)
- a screenshot when it is about something you see

The bot answers a new post with the guides for its tag. A person follows. When it is solved, right-click the answer › **Apps › Mark as solved**.

## Report a bug

A bug is something you can reproduce. Open it on GitHub, where it is tracked until it is fixed: [new bug report](https://github.com/kaizensx/form-studio/issues/new?template=1-bug.yml). The form asks for:

1. **Area:** the desktop app, conversations and agents, design and revisions, checks and fit, slicing, release and export, installer and first start, or the CLI and MCP server.
2. **What happened:** what you did, step by step, what you expected, and what Form Studio did instead. Screenshots are welcome.
3. **Form Studio version.**
4. **Operating system.**
5. **Agent and slicer,** if they were involved.
6. **`form setup --check` output** (optional, but it says what was found on your computer).

If a design shows the problem, attach its `.formstudio` file (renamed to `.zip`): it carries the revisions and the code the design was built from, so the bug can be reproduced exactly.

Search [existing issues](https://github.com/kaizensx/form-studio/issues) first. If yours is there, add what you know to it.

## Security problems

Never post a vulnerability in a channel or a public issue. Report it privately: [open a security advisory](https://github.com/kaizensx/form-studio/security/advisories/new).

## Ideas are not bugs

Something Form Studio should do, and does not: post it in #ideas, the problem first, then what you would want. Other people vote on it there.
