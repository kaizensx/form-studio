# Security

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub's private security advisories](https://github.com/kaizensx/form-studio/security/advisories/new), not in a
public issue. Include the version, your platform and the steps to reproduce. You will get a reply within a few days,
and credit in the release notes if you would like it.

## Supported versions

Security fixes are made on the latest release.

## Security model

Form Studio runs on your computer. Its engine, the desktop app, the CLI and the MCP server share one local project folder.

| Area | Behaviour |
|---|---|
| **Network** | The engine's HTTP interface listens on `127.0.0.1` only and refuses requests with any other `Host` header. Outbound requests happen only when you or your agent ask for them: reading a datasheet, checking for an update, installing software. |
| **Files** | Served paths are confined to the project folder. Project and archive imports reject path traversal. |
| **Printing and uploads** | Form Studio never sends a file to a printer and never uploads a design. |
| **Releases** | Only a person can approve a release. There is no MCP tool or CLI flag that lets an agent approve one. |
| **Installs** | Every install command is shown before it runs and needs your confirmation. Form Studio never asks for a password. |
| **Agent configuration** | `form setup` edits an agent's configuration only for the items you select, backs each file up first, and refuses to rewrite a file it cannot parse. |
| **Secrets** | API keys (for example a Gemini key) are stored in a private file readable only by your user, never in `studio.toml`, and are not readable over MCP. |
| **External programs** | `open_in` passes a file from the project to your system's `open` / `xdg-open`, or to the app named in `studio.toml`. |
