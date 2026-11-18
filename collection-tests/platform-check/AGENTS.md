# AGENTS.md — collection-tests/platform-check

## Purpose

The platform check: every plugin of the collection, played and looked at in MXM Player on Linux,
Windows and macOS, from the release archives the portal installs (the owner, 2026-11-18: "we need
to test automatically that the instruments are working on all 3 platforms. They should look correct
in screenshots and must render sound from the player ... Not a full test, but some at least from
every plugin"). Each case loads a plugin, loads a factory preset through the plugin's own loader,
captures its editor's window, plays a sequence and renders it. The report checks each render and
picture on its own and against the same case on the reference platform.

## Ownership

- `cases.json`: the fixed set. Every plugin, two factory presets of different categories, each
  played by one of `sequences/`; an effect is played by `effect_source` through it, and the source
  dry is a case of its own, so an effect that changes nothing shows.
- `sequences/make.py` writes `sequences/*.mid`, written as MXM Player writes one, so it loads with
  nothing lost: run it after changing it, and commit both.
- `check.py`: `run <target>` drives one target; `report` checks and draws every target's results.
  `report.py` is its report.
- `capture/`: each platform's window capture. `x11_windows.py` (Linux: XGetImage through ctypes;
  an editor is an X11 window under XWayland, the player a Wayland one, so it isn't captured),
  `windows.ps1` (PrintWindow with full content, run on the desktop through a scheduled task). macOS
  uses `vm/mac`'s `mxm-input windows <pid>` and `screencapture -l`.
- `build_player.py`: a player archive from any checkout, built as `ws.py release` builds it, for a
  player not released yet.

## Local Contracts

- **It runs before a release, and only then** (the owner, 2026-11-18: "And these tests should only
  be done before a release"): on the release candidate's archives, once `ws.py release` has made
  them, never as a step of ordinary work. Plan-v1-release's gate 3 names it.
- **Only what a change reaches is tested** (the owner, 2026-11-18: "you should only test relevant
  plugins for the code changes that are made ... If you change a library that multiple plugins are
  using you should test those it regards"). The unit is the release archive: each stored result
  keeps the fingerprint it was made with (the case, its sequence, the plugin's archive, the
  player's), and `run` makes only the cases whose fingerprint changed, that never ran on that
  target, or that failed. A library change reaches exactly the plugins relocked onto it, since
  each gets a new commit and archive. A player change reaches every case: the player hosts them all.
  The effect source's archive isn't in an effect's fingerprint. `--dry-run` says what would run and
  why; `--all` runs everything; `--only` narrows to plugins.
- **What is tested is what ships**: the plugins from `target-shared/release/<platform>/` (`ws.py
  release`), each archive's CLAP and control map in a test folder, the only one the player searches
  (its `MXM_PLAYER_SEARCH`: a machine's own plugins are never scanned), and its
  presets in the factory folder the plugin reads (mxm-kit's `factory_dir`), as the portal puts them.
  Presets load by that path, so they load as factory presets.
- **A target never touches the machine's own setup**: on Linux the player and the plugins get
  their own XDG folders, on macOS their own `HOME` (`/tmp/mxm-check/home`); the VMs are throwaway
  and their player settings are cleared. Results stay below `MXM_BUILD_ROOT`
  (`platform-check/<target>/`), never in git.
- **The Mac is the owner's**: a run there opens windows on its screen for minutes. Ask first, every
  time, and the owner unlocks its screen: a locked one is refused (the player takes no command).
  Its window pictures hold only the player's windows.
- **The player is driven only through `mxm-cli`**, the shipped command line: `load`, `preset`,
  `fx add|preset|editor|remove`, `loadseq <file>`, `bars`, `normalise off`, `export`, `dump`.

## Work Guidance

```bash
python3 collection-tests/platform-check/check.py run linux-vm \
    --release target-shared/release/linux-x64 --player <mxm-player-…-linux-x64.tar.gz> [--dry-run]
python3 collection-tests/platform-check/check.py report      # then read every LOOK
```

- The VMs run first: `vm/linux/vm.sh run`, `vm/windows/vm.sh run` (`vm/AGENTS.md`): each fullscreen
  on its own workspace, both with a 2560×1440 screen, so an editor opens at one size in both. A run
  records each target's screen, and a case made on another screen is made again; the report
  compares two pictures only when both editors opened at one size in points.
- **The Windows VM**: `run windows-vm … --software-gl <folder>`, the folder holding Mesa's
  `opengl32.dll` and `libgallium_wgl.dll` (mesa-dist-win's release-msvc x64, kept below
  `MXM_BUILD_ROOT/platform-check/cache/`): its display has no OpenGL 3 and no editor opens without
  it. The run installs Microsoft's Visual C++ runtime when it's missing, and refuses a screen it
  can't set.
- **The Mac**: its player archive is built there (`packaging/package.py` in a copy of the player's
  checkout) and its `mxm-input` must have `windows` (`vm/mac/mac.sh install`).
- `build_player.py` makes the Linux and Windows player archives from a checkout not released yet.
- A crash restarts the player and marks the case failed; the run goes on.
- Read every sheet the report prints before saying anything about a run (the workspace's *Look
  before reporting*).

## Verification

The check is its own verification: `run` on a target and `report`. Its first runs, and what they
found, are in [NOTES.md](NOTES.md).

## Child DOX Index

None.
