#!/bin/bash
# Runs one test binary until it crashes, with core dumps on, and prints every thread's backtrace from
# the core. For a crash only Linux CI shows: build the repository in a clone inside the Ubuntu-24.04
# distro first (glibc 2.39, as on GitHub's ubuntu-latest).
# usage: wsl -d Ubuntu-24.04 -- bash /mnt/e/newDAWn/wsl/core-ubuntu.sh <clone> <test> [runs]
#   e.g. core-ubuntu.sh ~/repro/mxm-player p1_engine 40
set -uo pipefail
. ~/.cargo/env
clone="$1"; test="$2"; runs="${3:-40}"
cd "$clone" || exit 1
cargo test --locked --no-run --test "$test" 2>&1 | tail -1
bin=$(ls -t target/debug/deps/"$test"-* | grep -v '\.d$' | head -1)
sudo sysctl -q -w kernel.core_pattern=/tmp/core.%p
ulimit -c unlimited
rm -f /tmp/core.*
for i in $(seq 1 "$runs"); do
  RUST_TEST_THREADS=4 xvfb-run -a "$bin" > /tmp/run.log 2>&1
  code=$?
  if [ "$code" -ne 0 ]; then echo "crashed on run $i (exit $code)"; break; fi
done
core=$(ls -t /tmp/core.* 2>/dev/null | head -1)
[ -z "$core" ] && { echo "no crash in $runs runs"; exit 0; }
gdb -q -batch -ex 'set pagination off' -ex 'info threads' -ex 'thread apply all bt 30' "$bin" "$core" 2>&1 \
  | grep -vE '^\[New LWP|^warning: ' | head -220
