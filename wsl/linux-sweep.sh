#!/bin/bash
# Runs the fast tier (`cargo test`) of every MXM product repository on Linux, one shared build folder,
# and reports each repository's failing tests. Logs: ~/sweep/<repo>.log; summary: ~/sweep/summary.txt.
# usage (from Windows): wsl -d archlinux -- bash /mnt/e/newDAWn/wsl/linux-sweep.sh [repo-name ...]
set -uo pipefail
export CARGO_TARGET_DIR="$HOME/target/shared"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-8}"
export RUST_TEST_THREADS="${RUST_TEST_THREADS:-4}"
mkdir -p ~/sweep
: > ~/sweep/summary.txt
for dir in /mnt/e/newDAWn/instruments/* /mnt/e/newDAWn/effects/* /mnt/e/newDAWn/tools/*; do
  repo=$(basename "$dir")
  if [ $# -gt 0 ] && ! printf '%s\n' "$@" | grep -qx "$repo"; then continue; fi
  start=$(date +%s)
  (cd "$dir" && xvfb-run -a cargo test --locked --no-fail-fast) > ~/sweep/"$repo".log 2>&1
  code=$?
  failed=$(grep -E '^---- .* stdout ----$' ~/sweep/"$repo".log | sed 's/^---- \(.*\) stdout ----$/\1/' | tr '\n' ' ')
  line="$repo: exit $code in $(( $(date +%s) - start )) s${failed:+ — failing: $failed}"
  echo "$line" | tee -a ~/sweep/summary.txt
done
echo "sweep done"
