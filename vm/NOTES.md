# NOTES.md — vm

The reasoning behind `AGENTS.md`, what the first builds taught, and the owner's rulings. The rules
are in `AGENTS.md`; this is why they are so.

## The owner's rulings (2026-11-17)

- *"Can you compile the windows part inside a VM so I donw need to start a windows machin or
  reboot?"*: the answer was to build on Linux and test in a VM (below).
- *"cant we just just the 90 day trial, and then reinstall it every 90 days? Or is that too
  bothersome?"*: the evaluation, rebuilt by script, so it isn't bothersome.
- *"yes to the MS license"*: cargo-xwin may download Microsoft's C runtime and Windows SDK files.
- The packages, installed by the owner: `sudo pacman -S qemu-desktop libvirt virt-manager`, then
  `swtpm`. `edk2-ovmf`, `xorriso` and `socat` were there already.
- *"And remember to write down what youu have done with the vm so it builds well the next time."*:
  this file.

## The ISO

- **Microsoft's Evaluation Center, the Enterprise ISO, 64-bit**:
  https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise. Its form asks for a
  name and an email, so the owner downloads it. Not the consumer download page
  (`microsoft.com/…/software-download/windows11`): that is Home and Pro, which want a key and are
  no trial. Not **LTSC**: it lacks the Store and other consumer parts, so it is a poorer stand-in
  for a tester's PC.
- The first one: `26300.9457.260913-1737.26h2_ge_release_svc_refresh_CLIENTENTERPRISEEVAL_OEMRET_x64FRE_en-us.iso`,
  8.2 GB. The browser saved it in `~/Downloads`; `vm.sh` wants it in `vm/windows/`, alone there.

## The first builds (2026-11-17)

- **About seven minutes**, not the half hour expected: KVM, 8 cores, 8 GB.
- **Setup's window is up within seconds** of booting from the ISO. The script answered the ISO's
  "Press any key to boot from CD or DVD" with Enter for 20 seconds, and the later presses landed on
  setup's Cancel button: a "quit?" dialog, its focus luckily on No (closed with one more Enter
  through the monitor; the install went on). The script now presses `x`: the boot prompt takes any
  key, and `x` is no button's shortcut in setup. The second build went through untouched.
- **Look before trusting a long run**: `screendump <file> -f png` through the monitor socket
  (`state/monitor.sock`, with `socat`) shows the screen; read it within the first minute.
- **An agent's shell lacks `HYPRLAND_INSTANCE_SIGNATURE`**, so the window opened wherever it liked;
  `vm.sh` now takes the newest instance under `$XDG_RUNTIME_DIR/hypr` and opens it on workspace 4.
- **Plain QEMU, not libvirt**: one script holds the whole machine, which `build` can make again from
  nothing; libvirt's daemon and XML add a second place where it lives. virt-manager isn't needed.
- **Windows 11's checks**: swtpm gives it a TPM 2.0; the answer file also sets setup's `LabConfig`
  bypasses for the TPM, Secure Boot and RAM, in case. Device encryption is kept off
  (`PreventDeviceEncryption`): the disk is restored from snapshots, and no recovery key is kept.

## SSH into the VM

- **Why**: an agent tests in the VM without clicking: copy builds in, start them, read results. The
  owner asked for the portal's command line for the same reason.
- **Microsoft's OpenSSH for Windows from GitHub, pinned** (`10.0.0.0p2-Preview`, its SHA-256 from
  GitHub's release), installed in setup's specialize pass from the answer-file disc. Not Windows'
  optional feature (`Add-WindowsCapability`): that downloads through Windows Update, and a first
  logon may not be elevated enough to install it.
- **The VM's own key**, made by `build` in `state/ssh/`; its public half goes on the answer-file
  disc as `administrators_authorized_keys` (the file an administrator's key must be in for
  Windows' sshd), with its rights cut to Administrators and SYSTEM, or sshd ignores it.
- **Port 22 forwarded to 127.0.0.1:2222 only**: nothing beyond this machine reaches it.
- **Commands run in PowerShell 5.1** (sshd's `DefaultShell`). Its quoting does not survive a
  command line passed through SSH well: copy a `.ps1` in and run it with
  `powershell -NoProfile -ExecutionPolicy Bypass -File <it>`.
- **A program SSH starts has no desktop** (it runs in the SSH session); `vm.sh desktop` starts one
  in the logged-on user's session through a one-off scheduled task.

## Windows builds, made on Linux

- **cargo-xwin** (`cargo install --locked cargo-xwin`, and `rustup target add
  x86_64-pc-windows-msvc`): its `env` sets the compilers and the linker; Rust's own `rust-lld` links,
  no system `lld` needed. Its Microsoft files take 1.2 GB in `~/.cache/cargo-xwin`.
- **`cargo xwin env` sets an empty `RUSTFLAGS`**, and Cargo then ignores every
  `CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS`: `unset RUSTFLAGS` after `eval`, or no
  Windows-only flag takes effect (linking still works, through its `LIB`).
- The plugins bundle with their own xtask and `--target x86_64-pc-windows-msvc`, with
  `MXM_INSTALL_CLAP=0` so a Windows DLL is never installed into Linux's plugin folders. A VST3 built
  so has no `moduleinfo.json` (it is made by loading the plugin on the build machine); hosts don't
  need it.
- **A fresh Windows 11 has no Visual C++ runtime** (`vcruntime140.dll` is missing; checked in the VM,
  2026-11-17). A plugin or program built the default way imports it, and `LoadLibrary` fails with
  error 126 on such a machine: mxm-fx-delay did. Built with `-C target-feature=+crt-static` it
  imports only Windows' own DLLs and loads (167 KB larger). Machines with a DAW usually have the
  runtime, which is why it never showed; a tester's may not. **The owner's ruling** (2026-11-17:
  *"Can the portal not just install once and for all it is it is needed and dont exist?"*): the
  portal's installer installs Microsoft's runtime when it's missing, and only the portal is built
  static (ops' `plans/plan-sales-portal.md` §5). So a plugin tested in the VM needs the runtime
  installed there first, except when the test is the portal's own install on a clean machine.
- **The first test, 2026-11-17**: Microsoft's runtime installed in the VM from
  `https://aka.ms/vc14/vc_redist.x64.exe` (`/install /quiet /norestart`, 14.52); MXM Player built on
  Linux started on the desktop (`vm.sh desktop`), its window up after about ten seconds, drawn in
  software (the VM has no 3D graphics); its scan opened mxm-fx-delay's CLAP and VST3 from the system
  folders. A plugin's editor draws with OpenGL 3, which the VM's display likely lacks, so editors
  are tested on real machines (unverified in the VM). `mxm-cli` found no running player there (no
  `cli.json` beside its settings): not looked into yet.
- **The beta, end to end, 2026-11-17**, from the clean snapshot: `mxm-portal.exe` downloaded from
  https://portal.mxm.dk/download/, `setup` (the user's part, then the machine's: the MXM folders,
  writable by Users, and Microsoft's runtime 14.52), the beta key activated, `install all`: 25
  products in 6 seconds over the LAN; index 2 (mxm-drum-machine added) picked up by `install all`
  again. A plugin loaded from the MXM folder; MXM Player, installed by the portal, scanned all 50
  bundles inside the MXM subfolders (its first start about 40 seconds, in software). An SSH session
  runs elevated already, so its UAC prompt is the next test's.
- **The double-click, 2026-11-17**, from the clean snapshot, as a tester meets it: downloaded with
  the Mark of the Web (a `Zone.Identifier` stream, `ZoneId=3`, as a browser writes it; PowerShell's
  `Invoke-WebRequest` writes none), opened through `explorer.exe` on the desktop, which is how
  SmartScreen gets to look. SmartScreen's *"Windows protected your PC"*, *More info*, *Run anyway*;
  Defender's ten-second cloud scan; then the UAC prompt. **It waited on the taskbar**, a flashing
  shield behind the portal's window, where a tester could miss it: PowerShell had asked for it, and
  Windows shows the prompt at once only to the program in front (on Windows 11 that is Windows
  Terminal). The portal now asks itself, with the window in front as the owner (mxm-portal
  `crates/portal/AGENTS.md`); then the prompt came up at once, from the download and from the
  Start-menu entry. No answered *"Windows' question was answered No; run MXM Portal again"*; the
  Start-menu entry then set up, took the key and installed all 26. The installed copy has no Mark of
  the Web, so SmartScreen asks once only.
- **Formats and uninstalling, 2026-11-17**, in the rebuilt VM: VST3 chosen on the first double-click
  installed 25 VST3s and no CLAP; `mxm-portal formats both` added the 25 CLAPs (24 control maps) at
  each plugin's version. The uninstall Windows' *Installed apps* runs took out every plugin, the
  presets, MXM Player, the portal's state and entries and both `MXM` folders, but left the program:
  the shell meant to delete it after the portal exits shared the portal's console, and Windows
  Terminal closed both together. It now waits on the portal's process in a hidden console of its
  own, and the program goes when its window is closed. **Typing into the VM's window while an agent
  drives it sends the keys elsewhere**: a key went into Windows' Start search, which may pass what
  is typed to Bing.
- **Driving the VM's desktop by keys**: QEMU's monitor `mouse_move` goes to the PS/2 mouse, not the
  tablet, and moves nothing that lands; `sendkey` works everywhere, the UAC prompt's secure desktop
  too (`alt-y`, `alt-n`). SmartScreen: `tab`, `ret` opens *More info*; then `tab` twice puts the
  focus on *Run anyway* (a dotted frame), and `spc` presses it. A taskbar button: `meta_l-t` once
  per button from the left. `vm.sh desktop` breaks on a path with a space: start a `.cmd` instead.
  Look with `screendump` after every step; the typed key is masked in any picture kept.
- **A hard stop spoils a file being written** (2026-11-17): QEMU quit mid-install, and the
  portal's `state.json` came back as 334 bytes of zeros, Windows having recorded the length but
  not the data; the portal would not start. Its state is now synced before it replaces the last
  one, with a fallback (mxm-portal `crates/portal/AGENTS.md`). Don't close the VM's window while a
  test writes.
- **Clicking in the VM**: a window without a visible focus ring (MXM Portal's) is driven by the
  pointer. A `.ps1` calling `user32`'s `SetCursorPos` and `mouse_event`, started on the desktop with
  `vm.sh desktop "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File <it> x y"`,
  clicks at screen coordinates (the VM's screen is 1280×800 at 100 %); `screendump` gives them.
  **Not while a program `vm.sh desktop` started still runs** (2026-11-18): its one task,
  `mxm-desktop`, is replaced but its running copy keeps it busy, and Windows ignores the second start
  without a word. Start the click as a task of its own name over `vm.sh ssh` (`schtasks /create /tn
  mxm-click /tr '<the powershell line>' /sc once /st 00:00 /it /f; schtasks /run /tn mxm-click`),
  and give PowerShell a few seconds to compile its `Add-Type`.
- **A windowed program over SSH** (the portal is one): PowerShell doesn't wait for it, and the SSH
  session's end kills it before it is done; pipe it (`… | Out-String`) to wait and to see what it
  prints (2026-11-18).
- **Updates at shutdown**: an hour after a reset Windows Update had downloaded updates, and a
  shutdown stopped to install them ("updates are under way"). `vm.sh reset` now switches the VM off
  instead (nothing in it is kept), `vm.sh stop` shuts it down properly, and the answer file turns
  automatic updates off (`NoAutoUpdate`), from the next `build`.
