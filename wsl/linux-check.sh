#!/bin/bash
# Runs a repository's Linux checks inside the archlinux WSL distro, the way its CI's Linux job does.
# usage (from Windows): wsl -d archlinux -- bash /mnt/e/newDAWn/wsl/linux-check.sh <repo dir under /mnt/e> [clippy|test|cargo <args>]
# The build output stays on the distro's own disk (~/target/<repo>, or ~/target/shared with
# SHARED_TARGET=1), never in the Windows folder.
set -euo pipefail
repo="$1"
what="${2:-clippy}"
if [ -n "${SHARED_TARGET:-}" ]; then export CARGO_TARGET_DIR="$HOME/target/shared"
else export CARGO_TARGET_DIR="$HOME/target/$(basename "$repo")"; fi
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-8}"
cd "$repo"
case "$what" in
  clippy) cargo clippy --workspace --all-targets --locked -- -D warnings ;;
  test)   xvfb-run -a cargo test --locked --no-fail-fast ;;
  cargo)  shift 2; xvfb-run -a cargo "$@" ;;
  *) echo "unknown check: $what" >&2; exit 2 ;;
esac
