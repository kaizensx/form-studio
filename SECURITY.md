# Security

FORM runs locally. What it does and doesn't do:

- **Network:** the bench listens on `127.0.0.1` only, and requests with another `Host` header are refused.
- **Files:** served paths are confined to the project folder. Archive imports reject path traversal.
- **Uploads and printing:** FORM never uploads files and never sends anything to a printer.
- **Config files:** `form setup` edits agent configuration only for items you select. It backs each file up first, and refuses to rewrite a file it can't parse.
- **Commands:** `open_in` runs your system's `open` / `xdg-open` with a file from the project, or the app named in your `studio.toml`.

To report a vulnerability, please open a private security advisory on GitHub rather than a public issue.
