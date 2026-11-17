# AGENTS.md — vm

## Purpose

Virtual machines on this Linux machine, so Windows is tested without booting it (the owner,
2026-11-17: "Can you compile the windows part inside a VM so I donw need to start a windows machin
or reboot?"). `windows/` is Windows 11 Enterprise, Microsoft's 90-day evaluation, under QEMU and
KVM: built by `windows/vm.sh` in one command, and built again when the evaluation runs out (the
owner: "cant we just just the 90 day trial, and then reinstall it every 90 days?").

## Ownership

- `windows/vm.sh` (`build`, `run`, `reset`, `serve`) and `windows/autounattend.xml`, the unattended
  install, are tracked.
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
  this machine can reach (QEMU's user networking has no way in).

## Work Guidance

- `vm/windows/vm.sh build` (about half an hour, unattended; it shuts down and takes the snapshot);
  `run`; `reset`; `serve <folder>` makes a folder `http://10.0.2.2:8000/` inside the VM.
- Requires `qemu-desktop`, `edk2-ovmf`, `swtpm`, `xorriso` and `socat` (installed 2026-11-17), and
  `/dev/kvm`.

## Verification

None automated: a build ends with Windows at its desktop and the snapshot taken.

## Child DOX Index

None.
