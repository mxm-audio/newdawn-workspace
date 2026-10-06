# AGENTS.md — the newDAWn and MXM workspace

`E:\newDAWn` holds every newDAWn and MXM repository, and this file is the DOX rail above them.
Claude Code loads it in every session started anywhere below this folder, so it holds only what is
true in all of them. Each repository has its own `AGENTS.md` chain: read that next.

## DOX

- `AGENTS.md` files are binding work contracts for their subtree. There is no `CLAUDE.md`: Claude Code
  reads `AGENTS.md` itself, and a `CLAUDE.md` beside one would be read instead of it.
- Before editing: read this file, then every `AGENTS.md` from the repository's root down to each path
  you will touch. The nearest one controls local detail; no child may weaken a parent.
- After editing: update the closest owning `AGENTS.md`, and any parent or index it affects, when
  purpose, structure, contracts, workflows or the owner's preferences changed. Correct stale text;
  its history and detail move to `NOTES.md`, never just deleted (the owner, 2026-10-06).
- Make a child `AGENTS.md` when a folder becomes a durable boundary. Sections, in order: Purpose ·
  Ownership · Local Contracts · Work Guidance · Verification · Child DOX Index.
- Keep each file under about 200 lines: commands, rules, decisions and gotchas, not descriptions of
  code that can be read. That is Claude Code's guidance (checked 2026-10-06). History, measurements,
  rationale and worked examples go in the `NOTES.md` beside an `AGENTS.md` (in `newdawn/`, in its
  `docs/`), linked from it; the conventions every plugin keeps are mxm-kit's
  `docs/plugin-conventions.md`. Moving text out never drops it: `ops/dox/check_moved.py` proves it.

## What is here

| Path | What | Repository |
|---|---|---|
| `newdawn/` | The DAW | `maxmcorp/newDAWn`, moving to `mxm-audio/newdawn`; GPL-3.0 |
| `kit/mxm-kit/` | The shared crates every instrument and the DAW use | `mxm-audio/mxm-kit`, MIT |
| `kit/nice-plug/`, `kit/egui-baseview/` | Forks: upstream plus each `PATCHES.md` | `mxm-audio`, ISC and MIT/Apache |
| `player/mxm-player/` | MXM Player, the CLAP host the plugins' host tests run in | `mxm-audio/mxm-player`, GPL-3.0 |
| `instruments/<name>/` (11), `effects/<name>/` (9) | One repository per product | `mxm-audio/<name>`, GPL-3.0 |
| `tools/mxm-tools/` | The listener, room simulator and measurement harnesses | `mxm-audio/mxm-tools`, GPL-3.0 |
| `ops/` | The owner's split, publishing and move scripts | local and private |
| `wsl/` | The Linux build environments (WSL) and their scripts | this workspace |
| `collection-tests/` | Tests across every product, waiting for this workspace's test package | this workspace |
| `archive/` | The private monorepo and research repository, with their worktrees; read-only | private |
| `projects/` | The owner's song projects | not in git |
| `rust/` | `RUSTUP_HOME` and `CARGO_HOME` | not in git |

The folder is itself a git repository, the workspace, which ignores every repository inside it.

## Contracts across repositories

- **Dependencies by tag, never by path.** The kit is at `v0.3.1` (the two drum repositories stay on
  `v0.3.0`, which their mxm-tools is built on), the player at `v0.1.2` for host tests, and the
  products at `v0.1.0`. A published tag never moves: a fix gets the next tag, then each dependent
  moves to it and relocks (`cargo update -p <crate>`). The order is kit, player, plugins, tools,
  drums. `ops/split/bump_player.py` shows the pattern.
- **CI runs only on `v*` tags, or when started by hand** (the owner, 2026-10-06). Before a push,
  check locally: `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D
  warnings` and `cargo test` on Windows, and the same on Linux in WSL (`wsl/AGENTS.md`). Only CI
  reaches macOS.
- **Bit-exact pins are Windows'.** Golden digests and recorded renders hold Windows' bits, because
  each platform's maths library rounds differently. Elsewhere a test compares within rounding or
  skips the pin (the owner, 2026-10-06).
- **Never unmap a plugin's library on Linux.** Load every plugin through `mxm_player::entry::load`,
  never `PluginEntry::load` directly: Rust plugins leave per-thread destructors behind, and glibc
  2.39 crashes on them at thread exit.
- **Publishing needs the owner.** Creating a repository, pushing a release tag or pushing to a public
  `main` is outward-facing: ask first.
- **Licences.** The products are GPL-3.0-or-later and the kit is MIT. "MXM" is the owner's trademark
  (`TRADEMARKS.md` in each product), and contributions go through the CLA.

## Disk and build output

- C: is kept as empty as possible (the owner, 2026-10-06), so project work stays under `E:\newDAWn`.
- One build folder per repository, or one shared folder for checks across many; never one per
  worktree. The `build_output.py` hook in `~/.claude/hooks` warns, blocks on low disk space and lists
  stale folders. `python ~/.claude/hooks/build_output.py clean <folder>` empties one, keeping
  `bundled/`.
- `cargo xtask fetch` clones the plugins a repository's tests need into `$CARGO_HOME/mxm-fetch`.

## Child DOX Index

| Doc | Scope |
|---|---|
| `newdawn/AGENTS.md` | The DAW: vision, decisions, open questions and its own chain |
| `kit/mxm-kit/AGENTS.md` | The kit's crates, their MSRVs, the design system and theory docs |
| `player/mxm-player/AGENTS.md` | MXM Player and its test harness |
| `instruments/<name>/AGENTS.md`, `effects/<name>/AGENTS.md` | One product each, from the shared plugin conventions down |
| `tools/mxm-tools/AGENTS.md` | The listener, room simulator and measurement tools |
| `wsl/AGENTS.md` | The Linux distros, and how to run a repository's checks in them |
| `ops/AGENTS.md` | The split, publishing and move scripts |
