# AGENTS.md — vm

## Purpose

Virtual machines on this Linux machine, so Windows is tested without booting it (the owner,
2026-11-17: "Can you compile the windows part inside a VM so I donw need to start a windows machin
or reboot?"). `windows/` is Windows 11 Enterprise, Microsoft's 90-day evaluation, under QEMU and
KVM: built by `windows/vm.sh` in one command, and built again when the evaluation runs out (the
owner: "cant we just just the 90 day trial, and then reinstall it every 90 days?"). `linux/` is
Ubuntu 24.04 LTS with the minimal GNOME desktop (the owner, 2026-11-18: "build the Linux VM"), built
by `linux/vm.sh` from Ubuntu's cloud image: a tester's Linux, with no graphics card, to test the
portal, the plugins and MXM Player on.

## Ownership

- `windows/vm.sh` (`build`, `run`, `stop`, `reset`, `serve`, `ssh`, `copy`, `desktop`) and
  `windows/autounattend.xml`, the unattended install, are tracked.
- `mac/mac.sh` and `mac/mxm-input.swift`: the owner's MacBook Air, the macOS build machine, driven
  over SSH (`ssh mac`, its Bonjour name: its address changes): `screen`, `click`, `move`, `drag`
  (pressed, moved in steps, released: a note in a plugin's window, say), `type`,
  `key`, `front`, `windows <pid>` (a process's windows: id, bounds in points, title), `raise <pid>
  <title>` (that window in front, through Accessibility), and `install`, which builds the input
  helper on the Mac. **Over SSH macOS captures the whole screen only**: `screencapture -l` and
  ScreenCaptureKit refuse one window, so a window is raised and its rectangle captured
  (`screencapture -R`); a locked screen captures black. Screenshots need Screen
  Recording and input needs Accessibility for `/usr/libexec/sshd-keygen-wrapper`, both granted by
  the owner (2026-11-18). A screenshot holds the owner's whole screen: take one for a test, crop
  what it needs, delete the rest. Coordinates are a screenshot's pixels (2880×1800; the helper
  divides by the screen's scale).
- `linux/vm.sh` (the same commands, and `screen`, `click`, `key` for its desktop); its user-data,
  the first boot's whole setup, is in the script. `linux/state/` is machine-local and git-ignored.
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
- **Each VM's window has a workspace of its own, fullscreen, silently**: 5 the Linux VM's, 6 Windows'
  (the owner, 2026-11-18: "You can put the VMs on different workspaces and go fullscren if that is
  any help. 5 and 6 are not used"). The Linux VM's screen takes its window's size, so fullscreen
  keeps it the same every run; every other window an agent opens goes on 4.
- **DAW activations**: each rebuilt VM is a new computer to Bitwig and Ableton. DAW tests in the VM
  use Reaper's evaluation, or deactivate before a rebuild.
- Its account is the local administrator `mxm`, password `mxm`: a throwaway VM that nothing outside
  this machine can reach (QEMU's user networking has no way in but the one forward below).
- **An agent drives it over SSH**: Microsoft's OpenSSH for Windows (pinned by version and SHA-256 in
  `vm.sh`) is installed during setup from the answer-file disc, with a key made for this VM alone
  (`state/ssh/`, never in git); its port 22 is forwarded to this machine's 127.0.0.1:2222 only.
  Commands run in PowerShell. A program SSH starts has no desktop: `vm.sh desktop` starts one on
  the logged-on user's desktop through a scheduled task.

- **The Linux VM** (`linux/`): Ubuntu's own cloud image, checked against its `SHA256SUMS`, with
  `ubuntu-desktop-minimal` installed by cloud-init on its first boot (the same set the installer's
  "minimal installation" gives a tester), the generic kernel for the sound card, GNOME logged on
  by itself as `mxm` (password `mxm`), no automatic updates, no screen lock, no first-login wizard,
  and cloud-init switched off after; then the snapshot `clean`. SSH at 127.0.0.1:2223 alone, with
  its own key. Its display has no 3D: OpenGL is Mesa's software one, which is what a tester's VM or
  an older computer has. `MXM_VM_UBUNTU=jammy` builds 22.04 instead.

## Work Guidance

- `vm/windows/vm.sh build` (about ten minutes, unattended; it shuts down and takes the snapshot);
  `run`; `reset`; `serve <folder>` makes a folder `http://10.0.2.2:8000/` inside the VM; `ssh`,
  `copy <paths> <dest>`, `desktop <command>` once it runs.
- **Its screen is 2560×1440** (`MXM_VM_SCREEN`), the Linux VM's fullscreen on this machine's
  monitor (QEMU's menu bar off): QEMU's VGA offers that size to the firmware, and Windows' basic
  display driver keeps the firmware's mode, so it can't be changed from inside. A plugin's editor
  opens at a size its screen allows: at the clean install's 1280×800 it opened shorter and laid
  itself out otherwise (the platform check, 2026-11-18).
- **Its display has no OpenGL 3**, which every plugin's editor draws with, so no editor opens in it
  ("The plugin refused to create its interface"). Mesa's software OpenGL (mesa-dist-win's
  `opengl32.dll` and `libgallium_wgl.dll`, release-msvc x64) beside the program that loads the
  plugin stands in for a graphics card's driver: `collection-tests/platform-check`'s `--software-gl`.
- Setup comes up within seconds of booting: the script answers the ISO's boot prompt with `x`,
  which no button of setup's takes (Enter pressed its Cancel, 2026-11-17).
- Requires `qemu-desktop`, `edk2-ovmf`, `swtpm`, `xorriso` and `socat` (installed 2026-11-17), and
  `/dev/kvm`. The ISO: the Evaluation Center's Enterprise one, alone in `vm/windows/` (`NOTES.md`).
- **Windows builds for it, on Linux**: `XWIN_ACCEPT_LICENSE=1`, `eval "$(cargo xwin env --target
  x86_64-pc-windows-msvc)"`, **`unset RUSTFLAGS`** (cargo-xwin sets it empty, and Cargo then ignores
  any Windows flag in `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS`), then build with `--target
  x86_64-pc-windows-msvc` (a plugin: its xtask's `bundle`, with `MXM_INSTALL_CLAP=0`).
- **A fresh Windows has no Visual C++ runtime, and our builds need it**: the portal installs it for
  users (the owner, 2026-11-17); in the VM, install it before testing a plugin or the player, except
  when testing the portal's own install from the clean snapshot (`NOTES.md`).
- **A double-click is tested as a tester meets it**: the file with the Mark of the Web (a browser's
  `Zone.Identifier`), opened through `explorer.exe` with `vm.sh desktop`, never over SSH, which runs
  elevated and skips SmartScreen and UAC. The dialogs are answered with the monitor's `sendkey`
  (`NOTES.md`, *Driving the VM's desktop by keys*).
- **The Linux VM's desktop**: `vm.sh desktop <command>` starts a program in GNOME's session (through
  the user's systemd, which has its environment); `vm.sh screen <file.png>` takes the screen;
  `vm.sh click <x> <y>` clicks there through QEMU's tablet (QMP's input events, scaled from the
  1280×800 screen), and `vm.sh key <keys>` types (`sendkey` names).
- Check a DLL loads: copy in a `.ps1` that calls `LoadLibrary` and run it with `vm.sh ssh`; error 126
  is a missing DLL. `llvm-objdump -p <file> | grep "DLL Name"` lists what a build imports.

## Verification

None automated: a build ends with Windows at its desktop and the snapshot taken, and `vm.sh ssh
hostname` answers `MXM-TEST` once it runs (both held 2026-11-17). The history and the reasons are in
[NOTES.md](NOTES.md).

## Child DOX Index

None.
