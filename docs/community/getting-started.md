# Getting started

Form Studio is an open-source desktop app for macOS, Windows and Linux. You describe what you want, the agent of your choice writes it as a parametric design in build123d, and the OpenCascade kernel builds it as a real solid you can edit, check and export. This guide takes you from the download to your first released design.

## What you need

- **A computer running** macOS (Apple silicon or Intel), Windows 10 or 11 (x64), or Linux x64 (glibc 2.35 or newer).
- **Someone to design with you.** An agent app (Claude Code, Codex, Gemini CLI, Cursor CLI, OpenCode, Qwen Code or GitHub Copilot CLI), a model API key (Anthropic, OpenAI, Gemini, OpenRouter, Mistral, xAI, DeepSeek or Groq) or a local model (Ollama, LM Studio or llama.cpp). You can also work without an agent: **Start blank** opens an empty design.
- **Nothing else.** A 3D printer and a slicer are optional. The first start installs what is missing after asking you.

## Install on macOS

1. Download `FORM-macos-arm64.zip` (Apple silicon) or `FORM-macos-x64.zip` (Intel) from the [latest release](https://github.com/kaizensx/form-studio/releases/latest).
2. Unzip it.
3. The first time, right-click **Form Studio.app** and choose **Open**.

Or from a terminal:

```bash
curl -LsSf https://raw.githubusercontent.com/kaizensx/form-studio/main/install.sh | sh
form app
```

The script installs uv if it is missing (after asking), then Form Studio with its own Python 3.12, then runs `form setup`.

## Install on Windows

1. Download `FORM-windows-x64.zip` from the [latest release](https://github.com/kaizensx/form-studio/releases/latest).
2. Unzip it and run `FORM.exe`.
3. In SmartScreen choose **More info**, then **Run anyway**.

Or with [uv](https://docs.astral.sh/uv/):

```powershell
uv tool install --python 3.12 "form-studio[all] @ git+https://github.com/kaizensx/form-studio"
form app
```

## Install on Linux

1. Download `FORM-linux-x64.tar.gz` from the [latest release](https://github.com/kaizensx/form-studio/releases/latest).
2. Unpack it and run `FORM/FORM`.

Or from a terminal:

```bash
curl -LsSf https://raw.githubusercontent.com/kaizensx/form-studio/main/install.sh | sh
form app
```

## Check the download

Every release ships with `SHA256SUMS`, signed build provenance and an SBOM. Compare the hash of the file you downloaded with the line for it in `SHA256SUMS` on the release page.

## The first start

The first start installs what Form Studio needs and shows every command before it runs. It pauses only when you have to sign in or download something, then carries on.

From version 1.1 (in the Preview channel first) the first start is a launcher that asks three things:

1. **What do you want to make?** One card for each thing Form Studio can be set up for: parametric CAD (always on), mechanical parts, mesh to CAD, photoreal renders (Blender), CAD exchange (FreeCAD and OpenSCAD) and, last and optional, 3D printing (one slicer). Each card names what it installs, and the total download updates as you tick.
2. **Your agent.** An agent app, a model API key or a local model.
3. **Set up.** Only what you chose is installed, one item after another, with every command in the log.

You can change all of it later in **Settings › General › Set up for**. Turning a card on installs only what it needs. Turning one off hides it and never uninstalls anything. From a terminal, `form capabilities` shows the same list and `form capabilities on <id>` or `off <id>` changes it.

## Your first design

1. **Open Home.** One composer takes whatever you have: words, a photo, a sketch, a STEP, STL, OBJ or 3MF part, a PDF drawing or a link.
2. **Describe it.** For example: `a hook for my headphones that clamps under a 25 mm desk`. Say the numbers you know. If you have a photo, put a bank card, a coin or a ruler in the picture so the agent can estimate sizes from it. Sizes read off a photo are labelled "estimated from the photo" and stay *assumed* until you measure them.
3. **Pick a concept.** For a new idea the agent proposes three or four genuinely different concepts, each a real CAD model. Continue with one, or ask in words for a mix ("the base of A with the hook of C").
4. **Watch it build.** The workspace opens at once and the design grows into the viewport feature by feature, each one named as it arrives.
5. **Answer the measurement cards.** When a number decides the fit, the agent shows where to measure, the unit and the tolerance that matters. The number you enter becomes a new revision with how you measured it.
6. **Change it.** In **Design**, select a feature on the model or in the list and drag a slider: the part rebuilds in place and the draft shows its computed impact before you commit. Or just ask the agent in the conversation.
7. **Review it.** **Review** lists every check with its evidence. Each result says how it is known: computed, heuristic, simulated or measured.
8. **Release it.** In **Make**, one approval by you freezes STEP, STL, OBJ, GLB and 3MF with their SHA-256 hashes and a report of every check. No agent can approve a release.

## The window in one minute

- **Conversation** (left): your messages, the agent's steps and the views it looked at. Ctrl/⌘ J hides it.
- **Viewport** (centre): the kernel's geometry, one mesh per feature. The tool rail holds Select, Measure, Annotate, Section, Analyze, Assembly, History and Photo render.
- **Stages** (right): Describe, Design, Fit, Review and Make. Fit appears only for a design made for 3D printing.
- **Pipeline** (bottom): Parameters › Solid › Exports › Checks › Slice › Release. A step is current only when it describes the revision on screen.
- **Command palette**: Ctrl/⌘ K finds every action and every design. **Settings**: Ctrl/⌘ ,.

## Where your work is kept

- Every commit is a revision. Nothing is overwritten: scrub the timeline, branch from any earlier revision and compare any two.
- A design travels as one `.formstudio` file with its revisions, its conversations and the code it was built from. Export it, import it on another computer and carry on.
- Form Studio never uploads your files on its own. With a cloud agent, the conversation and the renders you share go to that agent's provider.

## Updates

Form Studio checks for a newer version once a day. In **Settings › Updates** choose the **Stable** channel (releases) or **Preview** (pre-releases with new features to try). `form update --check` shows the same from a terminal.

## Next

- Use it from your own agent: the guide **Agents and MCP**.
- Bring a mesh you already have: **Mesh to editable CAD**.
- Something not working: **Troubleshooting and reporting bugs**, or ask in #help.
- The full reference: [Features](https://github.com/kaizensx/form-studio/blob/main/docs/FEATURES.md) and [the desktop app](https://github.com/kaizensx/form-studio/blob/main/docs/APP.md).
