# GitHub profile text

The repository's description, website and topics, ready to apply by a maintainer under **Settings › General** (the
description and website) and the **About** gear on the repository page (topics). Nothing here is applied
automatically.

## Description

At most 350 characters; GitHub shows the first line in search results and link previews.

```text
The open-source AI CAD studio: describe anything, and an engineer-grade agent builds it as real, editable CAD in build123d on OpenCascade. Parametric, checked on the solid, released with hashes. STEP for CAD and CNC, meshes for renders, your slicer if you print. Desktop app and MCP server for macOS, Windows and Linux.
```

## Website

```text
https://kaizensx.github.io/form-studio/
```

## Topics

In this order (GitHub keeps the order you enter them in; at most 20, lowercase, hyphens only):

```text
ai-cad
text-to-cad
build123d
parametric
cad
mcp
mcp-server
opencascade
b-rep
step
generative-design
mechanical-engineering
ai-agents
claude-code
desktop-app
open-source
3d-printing
```

`3d-printing` stays last on purpose: printing is one optional output among STEP, CNC and renders.

## Social preview

The social preview image stays `site/assets/og.png` (1200 × 630). When it is redrawn, it should show a created design,
not a print.

## Applying it

With the GitHub CLI, from a checkout, by a maintainer:

```bash
gh repo edit kaizensx/form-studio \
  --description "The open-source AI CAD studio: describe anything, and an engineer-grade agent builds it as real, editable CAD in build123d on OpenCascade. Parametric, checked on the solid, released with hashes. STEP for CAD and CNC, meshes for renders, your slicer if you print. Desktop app and MCP server for macOS, Windows and Linux." \
  --homepage https://kaizensx.github.io/form-studio/
gh api -X PUT repos/kaizensx/form-studio/topics \
  -f "names[]=ai-cad" -f "names[]=text-to-cad" -f "names[]=build123d" -f "names[]=parametric" -f "names[]=cad" \
  -f "names[]=mcp" -f "names[]=mcp-server" -f "names[]=opencascade" -f "names[]=b-rep" -f "names[]=step" \
  -f "names[]=generative-design" -f "names[]=mechanical-engineering" -f "names[]=ai-agents" -f "names[]=claude-code" \
  -f "names[]=desktop-app" -f "names[]=open-source" -f "names[]=3d-printing"
```
