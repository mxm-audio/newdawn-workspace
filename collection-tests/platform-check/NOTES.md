# NOTES.md — collection-tests/platform-check

The reasoning behind [AGENTS.md](AGENTS.md), and what its first runs found.

## Why it is built this way

- **The release archives, not a build**: what a tester gets is what the portal installs, so the
  check unpacks `ws.py release`'s archives as the portal does (the CLAP and its control map, the
  presets into the factory folder the plugin reads) and loads presets from there, as factory ones.
- **Through MXM Player's shipped command line**, `mxm-cli`, so the check drives the player a tester
  runs. It needed two verbs, added for it (mxm-player's NOTES, *What the platform check needs*):
  `preset <file>`, a preset loaded through the plugin's own CLAP `preset-load` as a DAW's browser
  loads one, and `loadseq <file>`.
- **The renders are the player's `export`**: offline, from a second instance with the live state,
  so a render is the same on every machine but for the platform's arithmetic; the live device
  plays nothing a test listens to, and in a VM it would sound on this machine's speakers.
- **The windows are captured by the operating system, from the window itself**: XGetImage on Linux
  (an editor is an X11 window under XWayland), PrintWindow with full content on Windows, and
  `screencapture -l` on macOS. A window over another doesn't spoil either picture, and the editor is
  seen as it is drawn on that platform, its OpenGL included.
- **Only what a change reaches** (the owner, 2026-11-18): the fingerprint of each stored result is
  the case, its sequence, the plugin's archive, the player's, and the target's environment and
  screen. A library change reaches the plugins relocked onto it, each a new archive.
- **The effect source** is MXM Thanks EG's tine keys on `source.mid`: loud enough to cross a
  compressor's threshold. MXM Poly 06's pluck was first, at −42 dB RMS, and both of MXM FX Curve's
  compressor presets left it as it was.

## The screens (2026-11-18)

An editor opens at a size its screen allows, and on a smaller screen lays itself out otherwise:
MXM Mono 00 opened at 1195×592 with four tab pages on a 2536×688 screen, at 1694×987 with two on
1920×1080. So the two VMs have one screen, 2560×1440 (this machine's monitor; each VM fullscreen on
a workspace of its own, the owner: "5 and 6 are not used"), and the report compares two pictures
only when both editors opened at one size in points. The Mac's is the owner's own, 1440×900 points;
its pictures are compared by eye where the sizes differ.

- The Linux VM's GNOME takes its QEMU window's size, but didn't always follow a later change of it
  (it stayed at 2536×1390 after going fullscreen), so the VM boots at the size it is shown at.
- The Windows VM's basic display driver keeps the firmware's mode: `ChangeDisplaySettings` refused
  1920×1080 (−2, a mode it doesn't have), so the size is QEMU's VGA's preferred one, set at boot.
- **The Mac's windows** are raised through Accessibility and captured as their rectangle of the
  screen: over SSH `screencapture -l` said "could not create image from window" and ScreenCaptureKit
  "Failed to start stream due to audio/video capture failure", while the whole screen was allowed.
  Its pictures include the title bar. **A locked screen stops the Mac's run**: it captures black,
  and the player draws no frames, so it takes no command (MXM Mono 00 never loaded, 2026-11-18). A
  run there refuses a locked screen; the owner unlocks it.
- The Windows VM has no OpenGL 3, so no editor opens there ("The plugin refused to create its
  interface"); Mesa's software OpenGL beside the player stands in for a driver (`--software-gl`).

## What the first runs found (2026-11-18)

- **MXM Player opened no audio on a fresh Ubuntu 24.04**: cpal's ALSA default is named "Default
  Audio Device" and isn't in ALSA's list, so the name the player picked first was the one it
  couldn't find. Fixed in the player.
- **A preset loaded into an instrument with no audio running never reached it**: the two MXM Mono 01
  presets rendered alike and showed the default patch, the preset's name marked changed. The
  instrument had no main-thread `params.flush`, which effects had had since 2026-09-30. Fixed in
  the player.
- **Loads in the software-drawn Linux VM can take over 10 seconds**, the time `mxm-cli` waits for an
  answer; with the Windows VM booting and a build on every core beside it, every load after the
  first failed. A late answer is now waited out and the dump read.
- **Open: MXM Player stopped answering when the Linux VM's screen grew under an editor GNOME had
  maximised** (MXM Para 07's: GNOME maximises a window nearly as big as its screen, and the screen
  was 2536×688 for a moment). Its main thread ran a core flat out for minutes. A tester's small
  laptop screen maximises an editor the same way. Not reproduced on a steady screen; the release
  build is stripped, so its stack has no names yet.
- **Open: on the Windows VM's 1280×800 screen MXM Mono 01's editor opened 781 pixels high, switched
  to tab pages and drew one narrow column, the rest of the window empty.** A small laptop's screen
  would do the same.
- **Flagged, not failed**: MXM Para 07's two presets, MXM Creative Sampler's Long bass and MXM
  Chorus 06's Slow drift peak above full scale in the render (+0.4 to +1.6 dBFS).

## The first full runs (2026-11-18)

The merged player (mxm-player's `platform-check` branch on `e520d1d`), the release archives of
2026-11-18, the VMs at 2560×1440:

- **Linux VM and Windows VM: 49 cases each, all ran.** Every render alike on both, 0.0 dB in level
  and in every band; 32 of the 49 bit-identical, the other 17 apart in the last bits (each
  platform's maths library). Every picture alike where the editors opened at one size (0 to 1.3 out
  of 255).
- **Failing: MXM Classic Verb's Lush hall on Linux**, its editor captured black and white, before its
  first frame (Room drew; Windows drew both). To do before the next release run: look at an editor's
  picture as soon as it is taken, and take it again after a wait when it is blank.
- **MXM Classic Verb's editor opens 68 points taller on Linux than on Windows** (476 against 408),
  an empty band below its panels.
- **Tooltips in the pictures**: MXM Para 07's, MXM Poly 06's and MXM FX EQ-N's show one where the
  VM's pointer rests, the same on both VMs but for FX EQ-N. To do: park the pointer before a capture.
- **MXM FX Curve's two presets change the effect source gently**: a residual 34 and 40 dB under it.
  The report's "left as it was" is now a pass-through only, the residual under −60 dB.
- **The Mac: not run.** Its screen was locked, and the player there takes no command while it is;
  then it left the network. A run needs the owner at it, the screen unlocked.
