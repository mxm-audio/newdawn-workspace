# AGENTS.md — vm

## Purpose

Virtual machines on this Linux machine, so Windows is tested without booting it (the owner,
2026-11-17: "Can you compile the windows part inside a VM so I donw need to start a windows machin
or reboot?"). `windows/` is Windows 11 Enterprise, Microsoft's 90-day evaluation, under QEMU and
KVM: built by `windows/vm.sh` in one command, and built again when the evaluation runs out (the
owner: "cant we just just the 90 day trial, and then reinstall it every 90 days?").

## Ownership

- `windows/vm.sh` (`build`, `run`, `reset`, `serve`, `ssh`, `copy`, `desktop`) and
  `windows/autounattend.xml`, the unattended install, are tracked.
- `windows/*.iso`, the evaluation ISO the owner downloads from Microsoft's Evaluation Center (the
  Enterprise ISO, not LTSC), and `windows/state/`, the disk, firmware variables, TPM and sockets,
  are machine-local and git-ignored.

## Local Contracts

- **The VM tests; it does not build.** Windows builds are made on Linux and copied or served in, so
  a rebuilt VM needs nothing installed. Visual Studio's build tools in the VM would have to be
  installed again every 90 days.
- **The snapshot `clean` is the fresh install**: `vm.sh reset` restores it, disk, firmware variables
  and TPM together. It is the clean machine the portal's install test needs (`plan-v1-release.md`
  gate 5).
- **Its window goes on Hyprland's workspace 4, silently**, as every window an agent opens.
- **DAW activations**: each rebuilt VM is a new computer to Bitwig and Ableton. DAW tests in the VM
  use Reaper's evaluation, or deactivate before a rebuild.
- Its account is the local administrator `mxm`, password `mxm`: a throwaway VM that nothing outside
  this machine can reach (QEMU's user networking has no way in but the one forward below).
- **An agent drives it over SSH**: Microsoft's OpenSSH for Windows (pinned by version and SHA-256 in
  `vm.sh`) is installed during setup from the answer-file disc, with a key made for this VM alone
  (`state/ssh/`, never in git); its port 22 is forwarded to this machine's 127.0.0.1:2222 only.
  Commands run in PowerShell. A program SSH starts has no desktop: `vm.sh desktop` starts one on
  the logged-on user's desktop through a scheduled task.

## Work Guidance

- `vm/windows/vm.sh build` (about ten minutes, unattended; it shuts down and takes the snapshot);
  `run`; `reset`; `serve <folder>` makes a folder `http://10.0.2.2:8000/` inside the VM; `ssh`,
  `copy <paths> <dest>`, `desktop <command>` once it runs.
- Setup comes up within seconds of booting: the script answers the ISO's boot prompt with `x`,
  which no button of setup's takes (Enter pressed its Cancel, 2026-11-17).
- Requires `qemu-desktop`, `edk2-ovmf`, `swtpm`, `xorriso` and `socat` (installed 2026-11-17), and
  `/dev/kvm`. The ISO: the Evaluation Center's Enterprise one, alone in `vm/windows/` (`NOTES.md`).
- **Windows builds for it, on Linux**: `XWIN_ACCEPT_LICENSE=1`, `eval "$(cargo xwin env --target
  x86_64-pc-windows-msvc)"`, **`unset RUSTFLAGS`** (cargo-xwin sets it empty, and Cargo then ignores
  the Windows flags), add `-C target-feature=+crt-static` to
  `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS`, then build with `--target
  x86_64-pc-windows-msvc` (a plugin: its xtask's `bundle`, with `MXM_INSTALL_CLAP=0`). Without the
  static C runtime nothing loads on a fresh Windows (`NOTES.md`).
- Check a DLL loads: copy in a `.ps1` that calls `LoadLibrary` and run it with `vm.sh ssh`; error 126
  is a missing DLL. `llvm-objdump -p <file> | grep "DLL Name"` lists what a build imports.

## Verification

None automated: a build ends with Windows at its desktop and the snapshot taken, and `vm.sh ssh
hostname` answers `MXM-TEST` once it runs (both held 2026-11-17). The history and the reasons are in
[NOTES.md](NOTES.md).

## Child DOX Index

None.
