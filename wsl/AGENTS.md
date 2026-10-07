# AGENTS.md — wsl

## Purpose

The Linux half of every check before a tag, on this Windows machine. CI runs only on tags, so Linux
is checked here first. Two WSL2 distros, each a disk image in its own folder, and the scripts that
drive them.

## Ownership

- `archlinux/`: Arch Linux (glibc 2.44), user `maxm`, Rust 1.98.0, the system libraries the MXM CI
  installs, lavapipe Vulkan and Xvfb. Set up by `setup-arch.sh`. The everyday Linux check.
- `ubuntu-24.04/`: Ubuntu 24.04 (glibc 2.39), the same as GitHub's `ubuntu-latest`, with gdb. Set up
  by `setup-ubuntu.sh`. Reproduce a Linux CI failure here: the player's plugin-unload crash happened
  on 2.39 and never on Arch.
- The scripts. The disk images are not in git.

## Local Contracts

- Build output stays inside the distro (`~/target/...`), never in the Windows checkout: run cargo
  with `CARGO_TARGET_DIR` set, as `linux-check.sh` does.
- Call a script as a file. PowerShell 5.1 strips the quotes from an inline `bash -c` string.
- WSL 3.0.1 or later: the current Arch image does not start on WSL 2.4 (`Wsl/Service/E_UNEXPECTED`).

## Work Guidance

- One repository: `wsl -d archlinux -- bash /mnt/e/newDAWn/wsl/linux-check.sh
  /mnt/e/newDAWn/<group>/<repo> clippy|test|cargo <args>`. With `SHARED_TARGET=1` every repository
  shares one build folder (`~/target/shared`).
- Every product repository's fast tier: `wsl -d archlinux -- bash
  /mnt/e/newDAWn/wsl/linux-sweep.sh [repo ...]`. Results are in `~/sweep/summary.txt`.
- **MXM Player is checked in a clone inside the distro, never through `/mnt/e`**: its tests load
  bundles from its own `target/`, which in the Windows checkout holds Windows DLLs ("invalid ELF
  header", about 180 failures, 2026-10-07). In the clone: `cargo xtask fixtures --release`, `cargo
  build -p nice-plug-output-fixture`, `cargo xtask fetch`, then `cargo test`. The same holds on the Mac.
- A crash that only CI shows: build in a clone inside `wsl -d Ubuntu-24.04`, then run
  `core-ubuntu.sh <clone> <test>` for every thread's backtrace from a core dump.

## Verification

- `wsl -d archlinux -- bash /mnt/e/newDAWn/wsl/check-arch.sh` reports the toolchain, the libraries and
  the free space.
