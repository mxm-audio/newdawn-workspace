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
| `newdawn/` | The DAW | `maxmcorp/newDAWn`, private until it is ready (2026-10-06); GPL-3.0 |
| `kit/mxm-kit/` | The shared crates every instrument and the DAW use | `mxm-audio/mxm-kit`, MIT |
| `kit/nice-plug/`, `kit/egui-baseview/` | Forks: upstream plus each `PATCHES.md` | `mxm-audio`, ISC and MIT/Apache |
| `player/mxm-player/` | MXM Player, the CLAP host the plugins' host tests run in | `mxm-audio/mxm-player`, GPL-3.0 |
| `instruments/<name>/` (11), `effects/<name>/` (9) | One repository per product | `mxm-audio/<name>`, GPL-3.0; `mxm-model-drums` private until it is ready (2026-10-06) |
| `tools/mxm-tools/` | The listener, room simulator and measurement harnesses | `mxm-audio/mxm-tools`, GPL-3.0 |
| `ws.py`, `ws.cmd` | The workspace tool: one step in every repository at once (below) | this workspace |
| `ops/` | The owner's split, publishing and move scripts | `mxm-audio/newdawn-ops`, private |
| `wsl/` | The Linux build environments (WSL) and their scripts | this workspace |
| `collection-tests/` | Tests across every product, waiting for this workspace's test package | this workspace |
| `archive/` | The monorepo (archived on GitHub 2026-10-07; its worktrees' work is on `archive/*` branches) and the research repository; read-only | private |
| `projects/` | The owner's song projects | not in git |
| `rust/` | `RUSTUP_HOME` and `CARGO_HOME` | not in git |

The folder is itself a git repository, the workspace (`mxm-audio/newdawn-workspace`, public, MIT),
which ignores every repository inside it. `repos.txt` lists them all, and `python ws.py clone`
brings the missing ones to a new machine: add a new repository there. Nothing private goes in the
workspace's own files; it is public.

## Working across repositories

The owner works from this folder, not repository by repository (2026-10-06: "doing stuff repo by
repo gets tired real soon"). Start sessions here. Use `python ws.py` (or `.\ws` in PowerShell) for any
step that repeats across repositories, rather than a loop by hand:

- `status`: one row per repository (changed files, unpushed and behind, last commit, the kit and player commits its lock
  pins). Start here. `clone` fetches any repository in `repos.txt` that isn't here.
- `reach`: what each repository's uncommitted or unpushed change reaches: "docs only", "comments
  only", or the packages to test (the changed ones and everything using them).
- `check`: fmt, then clippy and the fast-tier tests of just those packages, Windows only. A
  plugin's `host-tests` (the slow tier) run only on purpose, for an audible change.
- `commit -m "…"`, `push`, `pull`: every changed, ahead or behind repository, with one message.
- `update`: moves each repository's mxm-audio dependencies to their current `main` and relocks;
  every crates.io package stays pinned. `tag` is refused: no tags (2026-10-07).
- `each <command>`: any command in every repository.
- `link kit [player]` / `unlink`: build against the local mxm-kit (and player) instead of their main,
  for one change across the kit and its users. `link` writes a marked block into the root
  `.cargo/config.toml`, which Cargo finds from every repository; `unlink` removes it and restores the
  lockfiles `link` changed. `push` refuses while linked. If the kit's version changed, run
  `cargo update -p <crate>` in the repository you build.
- `--only <names>`: repositories, or the groups `newdawn`, `kit` (mxm-kit alone, as in `link` and
  `bump`), `forks` (nice-plug, egui-baseview), `player`, `instruments`, `effects`, `plugins`, `tools`.

Each public repository still builds and tests alone from a fresh clone: nothing in one may need this
folder, and its docs must not send a contributor here.

## Contracts across repositories

- **Dependencies follow `main`, locked** (the owner, 2026-10-07: "Stop with all the tagging. It
  makes the CI run... We are in pre-alpha and development speed is more important than
  correctness"). Each `Cargo.toml` names every mxm-audio dependency, the forks included, with
  `branch = "main"`; its `Cargo.lock` pins the exact commit. `python ws.py update` moves a
  repository to the current mains, upstream first: forks, kit, player, the products whose crates
  others use (mono-00, mono-01, poly-06, classic-verb, creative-sampler), tools, then the rest.
  The old tags stay where they are; `test-bundles.txt` still names them, because a fetch clone is
  reused and must not move. A change across repositories is built and tested first with
  `python ws.py link`, which must be undone before any push.
- **A fork patch only applies while it is the newest release.** When upstream publishes a newer
  nice-plug or egui-baseview, Cargo resolves it instead and lists the fork under `[[patch.unused]]`,
  silently dropping our patches (egui-baseview 0.7.2, 2026-10-06). Refresh the fork onto it before
  relocking any plugin; `python ws.py status` warns when a lock shows an unused fork.
- **Work and verify on Windows only; test the other platforms later, together** (the owner,
  2026-10-06: "Just work on windows and then test the rest later. These runs takes faaar to long").
  Before a push: `cargo fmt --all -- --check`, `cargo clippy` and the tests the change reaches, on
  Windows, once. No Linux (WSL) or macOS run, and no waiting on CI, during the work: those come in
  one batch when the owner asks. Code stays cross-platform all the same.
- **CI runs only when started by hand** (the owner, 2026-10-07; tags no longer start it either).
- **Test a minimum, smartly** (the owner, 2026-10-06: "Development time is far more important than
  0 bugs on all platforms at this point"; earlier: "You have a tendency to overtest each step, dont
  do that"). A comment or format change gets `rustfmt --check`; a layout change gets the layout
  tests; otherwise `python ws.py check`. **A gate enforces it**: the PreToolUse hook
  `~/.claude/hooks/no_unnecessary_builds.py` blocks builds and tests on the Mac or in WSL, waiting on
  CI, loops across repositories, any build for a docs-only change, a test or clippy run wider than
  `ws reach`, and the same command again with nothing changed. Only when the owner asks for more in
  the conversation: put `MXM_GATE_OK='<their words>'` in the command.
- **Bit-exact pins are Windows'.** Golden digests and recorded renders hold Windows' bits, because
  each platform's maths library rounds differently. Elsewhere a test compares within rounding or
  skips the pin (the owner, 2026-10-06).
- **Never unmap a plugin's library on Linux.** Load every plugin through `mxm_player::entry::load`,
  never `PluginEntry::load` directly: Rust plugins leave per-thread destructors behind, and glibc
  2.39 crashes on them at thread exit.
- **Publishing needs the owner.** Creating a repository, pushing a tag or pushing to a public
  `main` is outward-facing: ask first.
- **Pre-alpha: nothing is released** (the owner, 2026-10-06: "We are still in pre alpha and are not
  releasing anything to anybody. No really."). There are no tags (2026-10-07) and no builds go to
  anyone. `repos.txt` records `public` or `private`
  for each repository; the private ones are `newdawn` and `mxm-model-drums`
  (private until they are ready) and `ops`.
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
