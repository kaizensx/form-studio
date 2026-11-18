#!/usr/bin/env bash
# Run a command as an unprivileged user with no network, for code submitted by people outside the project.
#
#   sudo is required (GitHub's Linux runners have it without a password).
#   scripts/ci/sandbox.sh setup                     create the user `fsbuild` and /srv/fsbuild/{home,out,in}
#   scripts/ci/sandbox.sh run -- CMD [ARGS...]      run CMD as fsbuild in a fresh network namespace (loopback only)
#
# What the command can not do: reach the network, read the runner's files under /home/runner (where the checkout,
# the job's tokens and the runner's own process environment are), or write anywhere but /srv/fsbuild/{home,out}.
# Inputs are copied to /srv/fsbuild/in (read-only to fsbuild); results are written to /srv/fsbuild/out.
# Environment: only what is listed after `--env NAME=VALUE` options plus HOME, PATH, LANG, TMPDIR.
set -euo pipefail

ROOT=/srv/fsbuild
USER_NAME=fsbuild

case "${1:-}" in
  setup)
    if ! id "$USER_NAME" >/dev/null 2>&1; then
      sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$USER_NAME"
    fi
    sudo install -d -m 0755 -o root -g root "$ROOT" "$ROOT/in"
    sudo install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$ROOT/home" "$ROOT/tmp"
    sudo install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$ROOT/out"
    # The runner's home must not be readable by the sandbox user.
    sudo chmod o-rwx /home/runner || true
    echo "sandbox: user $USER_NAME, root $ROOT"
    ;;
  run)
    shift
    envs=()
    while [ "${1:-}" = "--env" ]; do envs+=("$2"); shift 2; done
    [ "${1:-}" = "--" ] && shift
    [ "$#" -gt 0 ] || { echo "sandbox: no command" >&2; exit 2; }
    # unshare -n: a new network namespace with only a loopback interface, which is brought up for local IPC.
    # setpriv: drop to fsbuild with no supplementary groups and a clean environment.
    exec sudo unshare --net -- sh -c 'ip link set lo up 2>/dev/null || true; cd /srv/fsbuild/home; exec "$@"' sandbox \
      setpriv --reuid="$USER_NAME" --regid="$USER_NAME" --clear-groups --reset-env -- \
      env -i HOME="$ROOT/home" TMPDIR="$ROOT/tmp" PATH="/opt/fsci/venv/bin:/usr/local/bin:/usr/bin:/bin" \
      LANG=C.UTF-8 FORM_NO_UPDATE_CHECK=1 "${envs[@]}" "$@"
    ;;
  *)
    sed -n '2,12p' "$0"
    exit 2
    ;;
esac
