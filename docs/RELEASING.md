# Releasing Form Studio

Form Studio ships on two update channels, chosen in Settings › General (`[updates] channel` in `studio.toml`):
**Stable** sees stable releases only, **Preview** also sees pre-releases. Releases are few and deliberate, so people
who watch the repository or the Discord server are told about something worth their time.

## Branches

| Branch | What it holds | Releases from it |
|---|---|---|
| `dev` | Every finished change, as soon as it passes its tests | Previews only |
| `main` | Exactly what was last released as stable, plus patches | Stable releases and patches |

`main` moves only when a stable release or a patch is cut. Day-to-day work never lands on `main` directly. One exception: changes to the README, the website or the docs that describe what the latest stable release already does may go to `main` directly, since they change no code and need no release.

## Three kinds of release

| Kind | Tag | When | Who is told |
|---|---|---|---|
| **Preview** | `v1.1.0-preview.1`, `-preview.2`, ... | At most once a week, from `dev`, when a set of features is ready to try | Preview channel in the app; GitHub pre-release; Discord #releases only |
| **Stable** | `v1.1.0` | Every 2 to 4 weeks, after a preview has run for at least 3 days with no serious bug, and every workflow is green on the commit, real slicers included | Everyone: Stable channel, GitHub latest release, Discord #releases and #announcements |
| **Patch** | `v1.1.1` | Only for a bug in a stable release that hurts people (a crash, lost or damaged data, a wrong slice or check) | Everyone, like a stable release |

A patch carries fixes only, never features. The fix lands on `main` and is merged back into `dev` the same day.

## Version numbers

`MAJOR.MINOR.PATCH`:

- **MAJOR** (1 → 2): something stops working the old way: the project or archive format, MCP tool names or
  arguments, CLI commands or their JSON output.
- **MINOR** (1.0 → 1.1): new features. Every minor version is a preview first.
- **PATCH** (1.1.0 → 1.1.1): fixes only.

## The changelog

`CHANGELOG.md` always starts with a `## Unreleased` section that collects what is on `dev`. Previews use it for their
notes (`scripts/ci/release_notes.py`). When a stable release is cut, `## Unreleased` is renamed to the version
(`## 1.1.0`) in the release commit, and a new empty `## Unreleased` is not added until the next change lands.

## Cutting a release

1. Check what is there: `git fetch --tags`, `git tag -l`, `git log origin/main..origin/dev`. When several people or
   sessions work on the repository, agree who tags: only one does.
2. Run the unit tests (`FORM_SKIP_UI=1 python -m unittest discover -s tests`) and the interface journeys that touch
   what changed.
3. **Preview:** tag `vX.Y.0-preview.N` on `dev` and push the tag. `app.yml` builds the four downloads and publishes a
   pre-release.
4. **Stable:** rename `## Unreleased` to `## X.Y.0`, set the version in `form/__init__.py` and `pyproject.toml`,
   commit on `dev`, fast-forward `main` to `dev`, tag `vX.Y.0` and push. `app.yml` builds a draft release; publish it
   once all four downloads and `SHA256SUMS` are attached.
5. **Patch:** fix on `main`, set the version, tag `vX.Y.Z`, publish, then merge `main` into `dev`.

The website deploys from `main`, so it shows what the stable release can do.
