#!/bin/bash
# The cross-platform batch: every MXM repository's fmt, clippy (as CI runs it) and fast tier, on
# Linux (inside WSL) or macOS, the builds sharing one folder. MXM Player is checked in a clone of its
# own, with its fixtures and fetched plugins built first: its tests load bundles from its own
# target/, which a shared checkout fills with another platform's builds (AGENTS.md).
#
# usage: platform-sweep.sh <workspace root> [repo ...]
#   Linux, from Windows: wsl -d archlinux -- bash /mnt/e/newDAWn/wsl/platform-sweep.sh /mnt/e/newDAWn
#   macOS:               bash ~/newDAWn/wsl/platform-sweep.sh ~/newDAWn
# Logs: ~/sweep/<repo>.log. Summary: ~/sweep/summary.txt, one line a repository, then "sweep done".
set -uo pipefail
root="${1:?usage: platform-sweep.sh <workspace root> [repo ...]}"
shift
logs="$HOME/sweep"
shared="$HOME/target/shared"
mkdir -p "$logs"
: > "$logs/summary.txt"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN)}"
export RUST_TEST_THREADS="${RUST_TEST_THREADS:-4}"
run=""
if [ "$(uname)" = "Linux" ]; then run="xvfb-run -a"; fi

wanted() {
  [ $# -eq 1 ] && return 0
  local repo="$1"; shift
  printf '%s\n' "$@" | grep -qx "$repo"
}

# fmt, clippy and the fast tier in the current folder; the player's preparation first.
check() {
  local player="$1"
  echo "=== $(git log --oneline -1)"
  local prep=0
  if [ "$player" = 1 ]; then
    echo "=== fixtures"; cargo xtask fixtures --release || prep=$?
    echo "=== output fixture"; cargo build -p nice-plug-output-fixture || prep=$?
    echo "=== fetch"; cargo xtask fetch || prep=$?
  fi
  echo "=== fmt"; cargo fmt --all -- --check; local f=$?
  echo "=== clippy"; cargo clippy --workspace --all-targets --locked -- -D warnings; local c=$?
  echo "=== test"; $run cargo test --locked --no-fail-fast; local t=$?
  echo "=== codes prepare=$prep fmt=$f clippy=$c test=$t"
}

for dir in "$root"/kit/mxm-kit "$root"/player/mxm-player "$root"/instruments/* "$root"/effects/* "$root"/tools/*; do
  repo=$(basename "$dir")
  [ -f "$dir/Cargo.toml" ] || continue
  wanted "$repo" "$@" || continue
  log="$logs/$repo.log"
  start=$(date +%s)
  if [ "$repo" = mxm-player ]; then
    # Its committed HEAD, in a clone with its own target/.
    clone="$HOME/check/mxm-player"
    rm -rf "$clone"
    mkdir -p "$HOME/check"
    (git clone -q "$dir" "$clone" && cd "$clone" && unset CARGO_TARGET_DIR && check 1) > "$log" 2>&1
  else
    (cd "$dir" && export CARGO_TARGET_DIR="$shared" && check 0) > "$log" 2>&1
  fi
  codes=$(grep '^=== codes' "$log" | sed 's/^=== codes //')
  failed=$(grep -E '^---- .* stdout ----$' "$log" | sed 's/^---- \(.*\) stdout ----$/\1/' | tr '\n' ' ')
  echo "$repo: ${codes:-did not finish} in $(( $(date +%s) - start )) s${failed:+ | failing: $failed}" | tee -a "$logs/summary.txt"
done
echo "sweep done" | tee -a "$logs/summary.txt"
