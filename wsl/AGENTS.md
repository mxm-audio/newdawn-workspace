# AGENTS.md — wsl

## Purpose

The Linux half of the cross-platform batch, on this Windows machine, run when the owner asks (CI
runs only when started by hand, 2026-10-07). Two WSL2 distros, each a disk image in its own folder,
and the scripts that drive them; `platform-sweep.sh` also runs the batch's macOS half on a Mac.

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
- **The cross-platform batch, one command** (2026-10-08): `wsl -d archlinux -- bash
  /mnt/e/newDAWn/wsl/platform-sweep.sh /mnt/e/newDAWn [repo ...]` runs fmt, clippy as CI runs it
  and the fast tier for mxm-kit, MXM Player, every instrument and effect and mxm-tools, sharing one
  build folder. The same script runs on a Mac with the workspace cloned (`bash
  ~/newDAWn/wsl/platform-sweep.sh ~/newDAWn`). Results: `~/sweep/summary.txt`, ending in "sweep
  done"; about 25 minutes here. It replaces `linux-sweep.sh`, which ran the tests alone.
- **MXM Player is checked in a clone, never through `/mnt/e`**: its tests load bundles from its own
  `target/`, which in the Windows checkout holds Windows DLLs ("invalid ELF header", about 180
  failures, 2026-10-07). `platform-sweep.sh` clones its committed HEAD and builds `cargo xtask
  fixtures --release`, `cargo build -p nice-plug-output-fixture` and `cargo xtask fetch` first.
- A crash that only CI shows: build in a clone inside `wsl -d Ubuntu-24.04`, then run
  `core-ubuntu.sh <clone> <test>` for every thread's backtrace from a core dump.

## Verification

- `wsl -d archlinux -- bash /mnt/e/newDAWn/wsl/check-arch.sh` reports the toolchain, the libraries and
  the free space.
