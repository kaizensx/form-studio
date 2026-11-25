# Security

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue, discussion or Discord channel:

1. Open [**Report a vulnerability**](https://github.com/kaizensx/form-studio/security/advisories/new) (the
   repository's Security tab). Private vulnerability reporting is on, so only the maintainers see the report.
2. Include the Form Studio version (About in the app, or `form doctor`), your platform, what an attacker could do, and the
   steps to reproduce. A proof of concept helps, but is not required.

What happens next:

| When | What |
|---|---|
| Within 3 working days | A reply that confirms the report was received and read |
| Within 10 working days | An assessment: accepted or declined, with the reasons, and the planned fix |
| With the fix | A patch release (see [RELEASING.md](docs/RELEASING.md)), a published GitHub security advisory with a CVE when one applies, and credit in the advisory and release notes if you would like it |

Please give us a reasonable time to ship a fix before you disclose the issue publicly; we will agree a date with you.

## Supported versions

| Version | Security fixes |
|---|---|
| Latest stable release | Yes, as a patch release |
| Latest preview | Yes, in the next preview |
| Older releases | No; please update |

## Verifying a download

Every release is built by GitHub Actions from a tagged commit ([`app.yml`](.github/workflows/app.yml)). Each release
lists `SHA256SUMS` and an SPDX SBOM, and every download carries signed build provenance and SBOM attestations:

```bash
gh attestation verify FORM-macos-arm64.zip --repo kaizensx/form-studio
shasum -a 256 -c SHA256SUMS --ignore-missing
```

## How the repository is kept safe

- Every GitHub Action is pinned to a full commit SHA, updated weekly by Dependabot after a cooling-off week.
- Workflows run with read-only tokens by default; write access is granted per job, only where a job needs it.
  Code from a fork's pull request never runs with a write token: the few jobs that need one for a fork (labels,
  preview comments) run only the base branch's own scripts and read the pull request as data.
- CodeQL (`security-extended`), [zizmor](https://docs.zizmor.sh/) for the workflows and OpenSSF Scorecard report to
  Security › Code scanning. Dependency review checks every pull request and comments when it fails
  (on a fork's pull request, whose token cannot comment, the findings are in the job summary); pip-audit checks
  `requirements.lock` and writes its findings to the workflow's job summary.
- Dependabot alerts and security updates, secret scanning and push protection are on.

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
