"""The platform check: every plugin of the collection, played and looked at in MXM Player on Linux,
Windows and macOS (AGENTS.md).

    python3 check.py run <target> --release <folder> --player <archive> --out <folder> [--only <plugin>…]
    python3 check.py report <out folder> [--reference <target>]

`run` puts one platform's release (the archives `ws.py release` makes, as the portal installs them)
and a player archive on a target, starts the player on its desktop, and for every case of
`cases.json` loads the plugin, loads the preset through the plugin's own loader, captures every
window the player's process shows, plays the sequence and renders it to a WAV. Everything comes
back to `<out>/<target>/`: `results.json`, the WAVs, the pictures and the player's log.

`report` reads every target under `<out>`, checks each render and picture on its own and against the
same case on the other platforms, and draws contact sheets to look at before anything is reported
(the workspace's *Look before reporting*): `report/` beside the targets.

Targets: `linux-vm` and `windows-vm` (vm/, running), `mac` (the owner's Mac: windows open on its
screen; ask first).
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent
CASES = HERE / "cases.json"
SETTLE = 2.0  # seconds a preset and an editor are given before the windows are captured


def log(message):
    print(f"[platform-check] {message}", flush=True)


# ------------------------------------------------------------------------------------------------
# The cases
# ------------------------------------------------------------------------------------------------

def load_cases(only):
    spec = json.loads(CASES.read_text())
    cases = []
    for c in spec["instruments"]:
        cases.append({"kind": "instrument", **c})
    for c in spec["effects"]:
        cases.append({"kind": "effect", **c})
    for c in cases:
        stem = (c["preset"] or "init").removesuffix(".json")
        c["name"] = f"{c['plugin']}--{stem}"
        if c["kind"] == "effect":
            # What feeds an effect is part of its case: a new source runs every effect again.
            c["source"] = {k: v for k, v in spec["effect_source"].items() if not k.startswith("_")}
    # The source dry, what every effect's render is compared with.
    source = {k: v for k, v in spec["effect_source"].items() if not k.startswith("_")}
    cases.append({"kind": "instrument", **source, "name": "effect-source"})
    if only:
        cases = [c for c in cases if c["plugin"] in only
                 or (c["name"] == "effect-source" and any(o["kind"] == "effect" and o["plugin"] in only for o in cases))]
    return spec, cases


# ------------------------------------------------------------------------------------------------
# Targets
# ------------------------------------------------------------------------------------------------

class Target:
    """One machine the check runs on, reached over SSH."""
    name = ""
    platform = ""  # the release folder: target-shared/release/<platform>
    ssh_command = []

    def sh(self, command, timeout=900, check=True):
        done = subprocess.run(self.ssh_command + [command], capture_output=True, text=True, timeout=timeout)
        if check and done.returncode != 0:
            raise RuntimeError(f"{self.name}: `{command[:200]}` failed ({done.returncode}): "
                               f"{(done.stderr or done.stdout).strip()[-2000:]}")
        return done.stdout

    def scp(self, sources, destination):
        subprocess.run(self.scp_command + ["-r", *map(str, sources), destination], check=True, timeout=1800)

    def put(self, sources, remote_folder):
        self.scp(sources, f"{self.host}:{self.scp_path(remote_folder)}")

    def get(self, remote, local_folder):
        local_folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(self.scp_command + [f"{self.host}:{self.scp_path(remote)}", str(local_folder)],
                       check=True, timeout=600)

    def scp_path(self, path):
        return path

    def ready(self):
        """Refuses a target that can't run the check now, with what to do about it."""

    def environment(self):
        """What a case's result depends on of the target's setup: the player's environment and the
        screen's size, in points. **An editor opens at a size its screen allows**, and on a smaller
        one lays itself out otherwise (mxm-mono-00 had four tab pages on a 688-point screen, two at
        1080), so a picture is compared with another only when both opened at one size, and a
        result made on another screen is made again."""
        return {**self.env(), "screen": self.screen()}

    def screen(self):
        raise NotImplementedError

    def cli(self, line, timeout=60):
        """One mxm-cli command: its JSON answer, or `{"error": …}` when the player can't be reached."""
        try:
            out = self.sh(self.cli_command(line), timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return {"error": f"mxm-cli did not answer `{line}` within {timeout}s"}
        for text in reversed(out.strip().splitlines()):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        return {"error": f"no answer to `{line}`: {out.strip()[-500:]}"}


class Posix(Target):
    """Linux and macOS: a POSIX shell over SSH."""

    def q(self, text):
        return shlex.quote(str(text))

    def join(self, *parts):
        return "/".join(str(p) for p in parts)

    def clean(self):
        self.sh(f"rm -rf {self.q(self.root)} && mkdir -p {self.q(self.root)}/shots {self.q(self.root)}/in")

    def unzip(self, archive, folder):
        raise NotImplementedError

    def install(self, products, archives, player_archive):
        """Unpacks each archive: the CLAP and its control map into plugins/<name>/, its presets into
        the factory folder the plugin reads (mxm-preset's `factory_dir`), as the portal does."""
        r = self.q(self.root)
        script = [f"set -e; cd {r}"]
        for product in products:
            name, version = product["name"], product["version"]
            factory = self.q(self.join(self.data_dir, "mxm", product["id"], "factory", version))
            script += [
                f"rm -rf unpacked && mkdir -p unpacked plugins/{name} {factory}",
                self.unzip(f"in/{product['file']}", "unpacked"),
                f"top=$(ls unpacked | head -1)",
                f"mv \"unpacked/$top/{name}.clap\" plugins/{name}/",
                f"if [ -e \"unpacked/$top/{name}.control-map.json\" ]; then mv \"unpacked/$top/{name}.control-map.json\" plugins/{name}/; fi",
                f"if [ -d \"unpacked/$top/{name}.presets\" ]; then cp -R \"unpacked/$top/{name}.presets/.\" {factory}/; fi",
            ]
        script += ["rm -rf unpacked player && mkdir -p player", self.unpack_player(f"in/{player_archive.name}")]
        self.sh("\n".join(script), timeout=1800)

    def env(self):
        # Only the test folder is searched (the player's `MXM_PLAYER_SEARCH`): a machine's own
        # plugins are never scanned, nor their code run.
        return {"MXM_PLAYER_SEARCH": self.join(self.root, "plugins"), "MXM_PLAYER_THEME": "dark",
                **self.home_env()}

    def env_words(self):
        return " ".join(f"{k}={self.q(v)}" for k, v in self.env().items())

    def cli_command(self, line):
        return f"env {self.env_words()} {self.q(self.cli_path)} {' '.join(self.q(w) for w in line.split(' '))}"

    def pattern(self):
        """The player's path as a pattern that doesn't match the shell asking: `[/]tmp/…`."""
        return self.q(f"[{self.player_path[0]}]{self.player_path[1:]}")

    def pid(self):
        out = self.sh(f"pgrep -f {self.pattern()} || true").split()
        return int(out[0]) if out else None

    def stop(self):
        self.sh(f"pkill -f {self.pattern()} || true; sleep 1; pkill -9 -f {self.pattern()} || true")


class LinuxVM(Posix):
    name = "linux-vm"
    platform = "linux-x64"
    host = "mxm@127.0.0.1"
    root = "/home/mxm/mxm-check"

    def __init__(self):
        state = WORKSPACE / "vm" / "linux" / "state" / "ssh"
        options = ["-i", str(state / "id_ed25519"), "-o", "StrictHostKeyChecking=accept-new",
                   "-o", f"UserKnownHostsFile={state / 'known_hosts'}", "-o", "ConnectTimeout=10",
                   "-o", "LogLevel=ERROR"]
        self.ssh_command = ["ssh", *options, "-p", "2223", self.host]
        self.scp_command = ["scp", "-q", *options, "-P", "2223"]
        self.data_dir = f"{self.root}/home/data"
        self.player_path = f"{self.root}/player/mxm-player"
        self.cli_path = f"{self.root}/player/mxm-cli"

    def home_env(self):
        home = f"{self.root}/home"
        return {"XDG_CONFIG_HOME": f"{home}/config", "XDG_DATA_HOME": f"{home}/data",
                "XDG_CACHE_HOME": f"{home}/cache"}

    def screen(self):
        """The VM's screen as QEMU shows it (`vm.sh screen`): GNOME takes its window's size."""
        picture = HERE / ".screen.png"
        subprocess.run([str(WORKSPACE / "vm" / "linux" / "vm.sh"), "screen", str(picture)], check=True,
                       capture_output=True, timeout=60)
        try:
            header = picture.read_bytes()[16:24]
        finally:
            picture.unlink()
        return [int.from_bytes(header[:4], "big"), int.from_bytes(header[4:], "big")]

    def unzip(self, archive, folder):
        return f"python3 -m zipfile -e {archive} {folder}"

    def unpack_player(self, archive):
        # The tarball's folder holds the player, its command line, a desktop entry and an installer.
        return (f"tar -xzf {archive} -C player --strip-components=1 && "
                f"test -x player/mxm-player && test -x player/mxm-cli")

    def start(self):
        settings = " ".join(f"--setenv={k}={v}" for k, v in self.env().items())
        self.sh(f"systemd-run --user --collect --quiet --unit=mxm-check-player {settings} "
                f"bash -c {self.q(f'exec {self.player_path} > {self.root}/player.log 2>&1')}")

    def stop(self):
        self.sh("systemctl --user stop mxm-check-player 2>/dev/null || true; "
                "systemctl --user reset-failed mxm-check-player 2>/dev/null || true")
        super().stop()

    def shoot(self, prefix):
        out = self.sh(f"systemd-run --user --collect --quiet --wait --pipe python3 "
                      f"{self.root}/capture/x11_windows.py {self.root}/shots {self.q(prefix)}", timeout=120)
        return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


class Mac(Posix):
    name = "mac"
    platform = "macos-universal"
    host = os.environ.get("MXM_MAC", "mac")
    root = "/tmp/mxm-check"

    def __init__(self):
        self.ssh_command = ["ssh", "-o", "ConnectTimeout=10", self.host]
        self.scp_command = ["scp", "-q"]
        home = f"{self.root}/home"
        self.data_dir = f"{home}/Library/Application Support"
        self.app = f"{self.root}/player/MXM Player.app"
        self.player_path = f"{self.app}/Contents/MacOS/mxm-player"
        self.cli_path = f"{self.app}/Contents/MacOS/mxm-cli"

    def home_env(self):
        # The player's settings, its exports and the plugins' data all live under HOME on macOS, so
        # a home of its own keeps the owner's untouched.
        return {"HOME": f"{self.root}/home"}

    def ready(self):
        """A locked screen stops more than the pictures: the player draws no frames, so it takes no
        command (MXM Mono 00 never loaded, 2026-11-18). The owner unlocks it; nobody else does."""
        if '"IOConsoleLocked" = Yes' in self.sh("ioreg -n Root -d1"):
            raise SystemExit("mac: its screen is locked; the owner unlocks it, then run again")

    def screen(self):
        """The Mac's main screen in points (`mxm-input check`): the owner's, as it is set."""
        words = self.sh("~/.local/bin/mxm-input check").split()
        width, height = words[words.index("screen") + 1].split("x")
        return [int(width), int(height)]

    def unzip(self, archive, folder):
        return f"ditto -x -k {archive} {folder}"

    def unpack_player(self, archive):
        return f"ditto -x -k {archive} player && test -d {self.q(self.app)}"

    def start(self):
        envs = " ".join(f"--env {self.q(f'{k}={v}')}" for k, v in self.env().items())
        self.sh(f"mkdir -p {self.q(self.root)}/home && open -n {envs} --stdout {self.root}/player.log "
                f"--stderr {self.root}/player.log {self.q(self.app)}")

    def shoot(self, prefix):
        """Each of the player's windows, brought in front through Accessibility and captured as
        its rectangle of the screen (`screencapture -R`): over SSH macOS lets neither `screencapture
        -l` nor ScreenCaptureKit capture one window, and a full screen is never saved. The pictures
        include each window's title bar; sizes are in points, the pictures at the screen's pixels.
        A locked screen captures black, so it is refused with its reason."""
        if '"IOConsoleLocked" = Yes' in self.sh("ioreg -n Root -d1"):
            raise RuntimeError("the Mac's screen is locked: no window can be captured")
        pid = self.pid()
        listed = [line.split("\t") for line in self.sh(f"~/.local/bin/mxm-input windows {pid}").splitlines()]
        shots = []
        for n, (wid, x, y, w, h, *title) in enumerate(listed, 1):
            title = "\t".join(title)
            name = f"{prefix}-{n}.png"
            self.sh(f"~/.local/bin/mxm-input raise {pid} {self.q(title)}; sleep 0.4; "
                    f"screencapture -x -R{x},{y},{w},{h} {self.root}/shots/{name}")
            shots.append({"file": name, "title": title, "x": int(x), "y": int(y),
                          "width": int(w), "height": int(h)})
        return shots


class WindowsVM(Target):
    name = "windows-vm"
    platform = "windows-x64"
    host = "mxm@127.0.0.1"
    root = "C:\\Users\\mxm\\mxm-check"

    def __init__(self):
        state = WORKSPACE / "vm" / "windows" / "state" / "ssh"
        options = ["-i", str(state / "id_ed25519"), "-o", "StrictHostKeyChecking=accept-new",
                   "-o", f"UserKnownHostsFile={state / 'known_hosts'}", "-o", "ConnectTimeout=10",
                   "-o", "LogLevel=ERROR"]
        self.ssh_command = ["ssh", *options, "-p", "2222", self.host]
        self.scp_command = ["scp", "-q", *options, "-P", "2222"]
        self.player_path = f"{self.root}\\player\\mxm-player.exe"
        self.cli_path = f"{self.root}\\player\\mxm-cli.exe"

    def scp_path(self, path):
        return "/" + path.replace("\\", "/")

    def q(self, text):
        return "'" + str(text).replace("'", "''") + "'"

    def join(self, *parts):
        return "\\".join(str(p) for p in parts)

    def clean(self):
        r = self.q(self.root)
        # Our builds need Microsoft's Visual C++ runtime, which a fresh Windows lacks and the portal
        # installs for a user (vm/AGENTS.md): installed here the same way, when it's missing.
        self.sh("if (-not (Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64' "
                "-ErrorAction SilentlyContinue).Installed) { "
                "Invoke-WebRequest https://aka.ms/vc14/vc_redist.x64.exe -OutFile $env:TEMP\\vc_redist.x64.exe; "
                "Start-Process -Wait $env:TEMP\\vc_redist.x64.exe -ArgumentList '/install','/quiet','/norestart' }",
                timeout=600)
        self.sh(f"Get-Process mxm-player -ErrorAction SilentlyContinue | Stop-Process -Force; "
                f"Remove-Item -Recurse -Force {r} -ErrorAction SilentlyContinue; "
                f"Remove-Item -Recurse -Force \"$env:APPDATA\\mxm-player\" -ErrorAction SilentlyContinue; "
                f"New-Item -ItemType Directory -Force {self.q(self.root + chr(92) + 'shots')}, "
                f"{self.q(self.root + chr(92) + 'in')} | Out-Null")

    def install(self, products, archives, player_archive):
        lines = ["$ErrorActionPreference = 'Stop'", f"Set-Location {self.q(self.root)}"]
        for product in products:
            name, version = product["name"], product["version"]
            factory = f"$env:LOCALAPPDATA\\mxm\\{product['id']}\\factory\\{version}"
            lines += [
                "Remove-Item -Recurse -Force unpacked -ErrorAction SilentlyContinue",
                f"Expand-Archive -Path 'in\\{product['file']}' -DestinationPath unpacked",
                "$top = (Get-ChildItem unpacked)[0].FullName",
                f"New-Item -ItemType Directory -Force 'plugins\\{name}', \"{factory}\" | Out-Null",
                f"Move-Item \"$top\\{name}.clap\" 'plugins\\{name}\\'",
                f"if (Test-Path \"$top\\{name}.control-map.json\") {{ Move-Item \"$top\\{name}.control-map.json\" 'plugins\\{name}\\' }}",
                f"if (Test-Path \"$top\\{name}.presets\") {{ Copy-Item \"$top\\{name}.presets\\*\" \"{factory}\" -Recurse -Force }}",
            ]
        lines += ["Remove-Item -Recurse -Force unpacked, player -ErrorAction SilentlyContinue",
                  f"Expand-Archive -Path 'in\\{player_archive.name}' -DestinationPath player-unpacked",
                  "$exe = Get-ChildItem player-unpacked -Recurse -Filter mxm-player.exe | Select-Object -First 1",
                  "Move-Item $exe.Directory.FullName player",
                  "Remove-Item -Recurse -Force player-unpacked -ErrorAction SilentlyContinue",
                  "if (-not (Test-Path player\\mxm-cli.exe)) { throw 'no mxm-cli.exe in the player archive' }"]
        script = HERE / ".install.ps1"
        script.write_text("\r\n".join(lines) + "\r\n")
        try:
            self.put([script], self.root + "\\in")
        finally:
            script.unlink()
        self.sh(f"powershell -NoProfile -ExecutionPolicy Bypass -File {self.q(self.root + chr(92) + 'in' + chr(92) + '.install.ps1')}",
                timeout=1800)

    software_gl = None

    def env(self):
        env = {"MXM_PLAYER_SEARCH": f"{self.root}\\plugins", "MXM_PLAYER_THEME": "dark"}
        if self.software_gl:
            env["GALLIUM_DRIVER"] = "llvmpipe"
        return env

    def use_software_gl(self, folder):
        """Mesa's software OpenGL beside the player (`--software-gl`): the VM's display has no
        OpenGL 3, which a plugin's editor draws with, so without it no editor opens there. A plugin
        loads `opengl32.dll` from the program's folder first. A tester's machine has its graphics
        card's driver instead."""
        self.software_gl = folder
        self.put([Path(folder) / "opengl32.dll", Path(folder) / "libgallium_wgl.dll"], self.root + "\\player")

    def cli_command(self, line):
        return f"& {self.q(self.cli_path)} {' '.join(self.q(w) for w in line.split(' '))}"

    def desktop(self, command_file):
        """Runs a .cmd on the logged-on user's desktop through a scheduled task (vm/AGENTS.md)."""
        self.sh(f"schtasks /create /tn mxm-check /tr {self.q(command_file)} /sc once /st 00:00 /it /f | Out-Null; "
                f"schtasks /run /tn mxm-check | Out-Null")

    def on_desktop(self, name, command, timeout=120):
        """Runs one command line on the desktop and waits for it to finish."""
        done = f"{self.root}\\{name}.done"
        self.sh(f"Remove-Item -Force {self.q(done)} -ErrorAction SilentlyContinue; exit 0")
        self.write_remote(f"{name}.cmd", f"@echo off\r\n{command}\r\necho done> \"{done}\"\r\n")
        self.desktop(f"{self.root}\\{name}.cmd")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.sh(f"Test-Path {self.q(done)}").strip() == "True":
                return
            time.sleep(1)
        raise RuntimeError(f"windows-vm: {name} did not finish on the desktop")

    # The Linux VM's, fullscreen on this machine's monitor: the two VMs' editors open at one size.
    SCREEN = (2560, 1440)

    def screen(self):
        return list(self.SCREEN)

    def start(self):
        # The clean install's screen is 1280x800: an editor taller than that opens shorter and lays
        # itself out otherwise, which no other platform's picture can be compared with.
        width, height = self.SCREEN
        self.on_desktop("screen", f"powershell -NoProfile -ExecutionPolicy Bypass -File "
                                  f"\"{self.root}\\capture\\screen.ps1\" -Width {width} -Height {height} "
                                  f"-Out \"{self.root}\\screen.txt\"")
        changed = self.sh(f"Get-Content {self.q(self.root + chr(92) + 'screen.txt')}").split()
        if not changed or changed[0] != "0":
            raise RuntimeError(f"windows-vm: its screen can't be {width}x{height} ({' '.join(changed)}): "
                               "start the VM with that screen (vm/windows/vm.sh, MXM_VM_SCREEN)")
        lines = ["@echo off"] + [f"set {k}={v}" for k, v in self.env().items()] + [
            f"start \"\" /b \"{self.player_path}\" > \"{self.root}\\player.log\" 2>&1"]
        self.write_remote("start.cmd", "\r\n".join(lines) + "\r\n")
        self.desktop(f"{self.root}\\start.cmd")

    def write_remote(self, name, text):
        local = HERE / f".{name}"
        local.write_text(text)
        try:
            self.put([local], self.root)
            self.sh(f"Move-Item -Force {self.q(self.root + chr(92) + '.' + name)} {self.q(self.root + chr(92) + name)}")
        finally:
            local.unlink()

    def pid(self):
        out = self.sh("(Get-Process mxm-player -ErrorAction SilentlyContinue | Select-Object -First 1).Id").strip()
        return int(out) if out.isdigit() else None

    def stop(self):
        self.sh("Get-Process mxm-player -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 1")

    def shoot(self, prefix):
        pid = self.pid()
        if pid is None:
            return []
        shots = f"{self.root}\\shots"
        self.on_desktop("shot", f"powershell -NoProfile -ExecutionPolicy Bypass -File "
                                f"\"{self.root}\\capture\\windows.ps1\" -ProcessId {pid} -Out \"{shots}\" "
                                f"-Prefix {prefix} > \"{shots}\\{prefix}.json\" 2>&1")
        out = self.sh(f"Get-Content {self.q(shots + chr(92) + prefix + '.json')}")
        return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


TARGETS = {"linux-vm": LinuxVM, "windows-vm": WindowsVM, "mac": Mac}


# ------------------------------------------------------------------------------------------------
# run
# ------------------------------------------------------------------------------------------------

def wait_for(target, done, timeout, step=0.5):
    """Asks for the dump until `done(dump)` holds; the last dump, or None on timeout."""
    deadline = time.time() + timeout
    dump = None
    while time.time() < deadline:
        dump = target.cli("dump")
        if "state" in dump and done(dump):
            return dump
        time.sleep(step)
    return None


class Player:
    """The player on the target: started, restarted after a crash, and asked."""

    def __init__(self, target):
        self.target = target
        self.source_ready = False
        # The effect source's own windows, so an effect case can tell its editor from the source's:
        # on Windows an editor's window has no title.
        self.source_windows = set()

    def start(self):
        self.target.stop()
        self.target.start()
        dump = wait_for(self.target, lambda d: len(d["state"]["found"]) > 0, timeout=240, step=2)
        if dump is None:
            raise RuntimeError(f"{self.target.name}: the player didn't come up with its scan done")
        answer = self.target.cli("normalise off")
        if "ok" not in answer:
            raise RuntimeError(f"normalise off: {answer}")
        self.source_ready = False
        return dump

    def alive(self):
        return self.target.pid() is not None

    def ask(self, line, timeout=60):
        """The player's answer to `line`. **A late answer isn't a refusal**: the player answers
        within 10 s or says it didn't (`cli.rs`), and in a VM drawing in software a load or a render
        can take longer. Then this waits for the player to answer again and returns None; the
        caller reads the dump for what happened."""
        answer = self.target.cli(line, timeout=timeout)
        if "ok" in answer:
            return answer["ok"]
        if "did not answer within" in str(answer.get("error", "")):
            if wait_for(self.target, lambda d: True, timeout=300, step=2) is None:
                raise CaseError(f"`{line}`: the player stopped answering")
            return None
        raise CaseError(f"`{line}`: {answer.get('error', answer)}")


class CaseError(Exception):
    pass


def window_key(shot):
    """What tells one window from another across two captures: its class or title, and its size."""
    return (shot.get("class") or shot.get("title") or "", shot["width"], shot["height"])


def factory_file(target, product, preset):
    return target.join(target_data_dir(target), "mxm", product["id"], "factory", product["version"], preset)


def target_data_dir(target):
    if isinstance(target, WindowsVM):
        return target.sh("$env:LOCALAPPDATA").strip()
    return target.data_dir


def load_plugin(player, product):
    player.ask(f"load {product['id']}")
    dump = wait_for(player.target, lambda d: (d["state"]["plugin"] or {}).get("id") == product["id"], 60)
    if dump is None:
        raise CaseError(f"{product['id']} didn't load")
    return dump


def play_sequence(player, sequence, bars):
    player.ask(f"loadseq {player.target.join(player.target.root, 'sequences', sequence)}")
    status = player.target.cli("dump")["state"].get("status") or ""
    if "could not be kept" in status:
        raise CaseError(f"{sequence} lost something on loading: {status}")
    player.ask(f"bars {bars}")


def export(player, name):
    answer = player.ask(f"export {name}", timeout=300)
    if answer is None:
        # Late: the status line names the file it saved (`Saved <path> — …`).
        status = player.target.cli("dump")["state"].get("status") or ""
        if not status.startswith("Saved ") or name not in status:
            raise CaseError(f"export {name}: no file was saved ({status})")
        return status.removeprefix("Saved ").split(" — ")[0].strip()
    return answer.removeprefix("exported ").strip()


def run_case(player, case, products, spec, local):
    target = player.target
    product = products[case["plugin"]]
    result = {"case": case["name"], "plugin": case["plugin"], "id": product["id"], "kind": case["kind"],
              "preset": case["preset"], "version": product["version"], "shots": [], "problems": []}
    started = time.time()
    if case["kind"] == "instrument":
        load_plugin(player, product)
        player.source_ready = False
        if case["preset"]:
            player.ask(f"preset {factory_file(target, product, case['preset'])}")
        sequence, bars = case["sequence"], case["bars"]
    else:
        source = spec["effect_source"]
        if not player.source_ready:
            load_plugin(player, products[source["plugin"]])
            player.ask(f"preset {factory_file(target, products[source['plugin']], source['preset'])}")
            time.sleep(SETTLE)
            player.source_windows = {window_key(s) for s in target.shoot("effect-source")}
            player.source_ready = True
        while target.cli("dump")["state"]["fx"]:
            player.ask("fx remove 1")
        player.ask(f"fx add {product['id']}")
        if case["preset"]:
            player.ask(f"fx preset 1 {factory_file(target, product, case['preset'])}")
        player.ask("fx editor 1")
        sequence, bars = source["sequence"], source["bars"]
    time.sleep(SETTLE)
    try:
        result["shots"] = target.shoot(case["name"])
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        # A picture that can't be taken costs the picture, not the render; the next run takes it.
        result["shots"], result["shot_error"] = [], str(error)
    editors = [s for s in result["shots"] if s.get("title") != "MXM Player"
               and (case["kind"] == "instrument" or window_key(s) not in player.source_windows)]
    editor = max(editors, key=lambda s: s["width"] * s["height"], default=None)
    result["editor"] = editor["file"] if editor else None
    play_sequence(player, sequence, bars)
    wav = export(player, case["name"])
    dump = target.cli("dump")
    result["status"] = dump.get("state", {}).get("status")
    result["log"] = dump.get("state", {}).get("log", [])
    result["sample_rate"] = dump.get("state", {}).get("audio")
    target.get(wav, local / "wav")
    result["wav"] = "wav/" + wav.replace("\\", "/").rsplit("/", 1)[-1]
    for shot in result["shots"]:
        target.get(target.join(target.root, "shots", shot["file"]), local / "shots")
    if case["kind"] == "effect":
        player.ask("fx remove 1")
    result["seconds"] = round(time.time() - started, 1)
    return result


def sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(case, product, player_sha, environment):
    """What a case's result depends on: the case itself, its sequence, the plugin's archive, the
    player's, and the player's environment on the target (`--software-gl`, say). **Not the effect source's archive**: a change to the source re-runs the source's own
    cases, not every effect it plays through (the owner, 2026-11-18: test what a change reaches)."""
    import hashlib
    sequence = case.get("sequence") or json.loads(CASES.read_text())["effect_source"]["sequence"]
    parts = [json.dumps({k: case[k] for k in sorted(case)}), (HERE / "sequences" / sequence).read_text("latin-1"),
             product["sha256"], player_sha, json.dumps(environment, sort_keys=True)]
    return hashlib.sha256("\n".join(parts).encode("utf-8", "surrogateescape")).hexdigest()


def select(cases, products, player_sha, environment, previous, everything):
    """The cases a run must make: each whose fingerprint differs from its stored result's, or that
    has none, or that failed, and why; the rest keep their stored result."""
    stored = {c["case"]: c for c in previous.get("cases", [])}
    chosen = []
    for case in cases:
        product = products.get(case["plugin"])
        if product is None:
            continue
        old = stored.get(case["name"])
        if everything:
            why = "--all"
        elif old is None:
            why = "never run here"
        elif "failed" in old:
            why = "it failed last time"
        elif old.get("shot_error"):
            why = f"its windows weren't captured ({old['shot_error']})"
        elif old.get("fingerprint") == fingerprint(case, product, player_sha, environment):
            continue
        elif old.get("archive") != product["sha256"]:
            why = f"its archive changed ({(old.get('commit') or '?')[:7]} -> {product['commit'][:7]})"
        elif old.get("player") != player_sha:
            why = "the player changed"
        elif old.get("environment") != environment:
            why = "the player's environment changed"
        else:
            why = "its case or sequence changed"
        chosen.append((case, why))
    return chosen


def cmd_run(args):
    target = TARGETS[args.target]()
    spec, cases = load_cases(args.only)
    release = Path(args.release)
    manifest = json.loads((release / "manifest.json").read_text())
    if manifest["platform"] != target.platform:
        raise SystemExit(f"{release} is {manifest['platform']}'s release, not {target.platform}'s")
    by_name = {p["name"]: p for p in manifest["products"] if p["kind"] == "plugin"}
    player_sha = sha256(args.player)
    local = Path(args.out) / target.name
    local.mkdir(parents=True, exist_ok=True)
    results_path = local / "results.json"
    previous = json.loads(results_path.read_text()) if results_path.exists() else {}
    missing = sorted({c["plugin"] for c in cases} - set(by_name))

    target.ready()
    if args.software_gl:
        if not isinstance(target, WindowsVM):
            raise SystemExit("--software-gl is for the Windows VM")
        target.software_gl = args.software_gl
    environment = target.environment()
    chosen = select(cases, by_name, player_sha, environment, previous, args.all)
    if not chosen:
        log(f"{target.name}: nothing to run: every case's plugin, sequence and player are as last checked")
        return
    wanted = {c["plugin"] for c, _ in chosen}
    if any(c["kind"] == "effect" for c, _ in chosen):
        wanted.add(spec["effect_source"]["plugin"])
    products = {name: by_name[name] for name in sorted(wanted)}
    log(f"{target.name}: {len(chosen)} of {len(cases)} cases, {len(products)} plugins; "
        f"not in the release: {missing or 'none'}")
    for case, why in chosen:
        log(f"  {case['name']}: {why}")
    if args.dry_run:
        return

    target.clean()
    log("copying the release")
    target.put([release / p["file"] for p in products.values()] + [Path(args.player)], target.join(target.root, "in"))
    target.put([HERE / "sequences", HERE / "capture"], target.root)
    log("unpacking")
    target.install(list(products.values()), None, Path(args.player))
    if args.software_gl:
        target.use_software_gl(args.software_gl)

    player = Player(target)
    log("starting the player")
    first = player.start()
    found = {f["id"]: f for f in first["state"]["found"]}
    stored = {c["case"]: c for c in previous.get("cases", [])}
    results = {"target": target.name, "platform": target.platform, "release": str(release),
               "player": Path(args.player).name, "player_sha256": player_sha, "missing": missing,
               "found": first["state"]["found"], "engine": first["state"].get("engine"),
               "audio": first["state"].get("audio")}

    def save():
        order = [c["name"] for c in cases]
        merged = sorted(stored.values(), key=lambda c: order.index(c["case"]) if c["case"] in order else len(order))
        results_path.write_text(json.dumps({**results, "cases": merged}, indent=1))

    for number, (case, why) in enumerate(chosen, 1):
        product = products[case["plugin"]]
        for old in list((local / "shots").glob(f"{case['name']}-*.png")) if (local / "shots").exists() else []:
            old.unlink()
        identity = {"case": case["name"], "plugin": case["plugin"], "archive": product["sha256"],
                    "commit": product["commit"], "player": player_sha, "environment": environment,
                    "fingerprint": fingerprint(case, product, player_sha, environment), "why": why,
                    "ran": time.strftime("%Y-%m-%d %H:%M")}
        if product["id"] not in found:
            stored[case["name"]] = {**identity, "failed": "the player's scan didn't find it"}
            save()
            continue
        log(f"{number}/{len(chosen)} {case['name']}")
        try:
            result = {**identity, **run_case(player, case, products, spec, local)}
        except (CaseError, RuntimeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
            result = {**identity, "failed": str(error)}
            try:
                alive = player.alive()
            except (RuntimeError, subprocess.TimeoutExpired) as lost:
                stored[case["name"]] = result
                save()
                raise SystemExit(f"{target.name}: lost it ({lost}); the results so far are kept")
            if not alive:
                result["failed"] += " (the player died)"
                log(f"  the player died: {error}; starting it again")
                player.start()
            else:
                log(f"  failed: {error}")
        stored[case["name"]] = result
        save()
    try:
        target.get(target.join(target.root, "player.log"), local)
    except subprocess.CalledProcessError:
        pass
    if not args.keep:
        target.stop()
    save()
    ran = [stored[c["name"]] for c, _ in chosen]
    failed = [c for c in ran if "failed" in c]
    log(f"{target.name}: {len(ran) - len(failed)} of {len(ran)} cases ran; {len(failed)} failed. {results_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("target", choices=sorted(TARGETS))
    run.add_argument("--release", required=True, help="target-shared/release/<platform>")
    run.add_argument("--player", required=True, help="the player's archive for that platform")
    run.add_argument("--out", default=os.path.join(os.environ.get("MXM_BUILD_ROOT", str(WORKSPACE / "target-shared")),
                                                   "platform-check"),
                     help="where every target's results are kept between runs (default: below MXM_BUILD_ROOT)")
    run.add_argument("--only", nargs="*", help="these plugins' cases alone")
    run.add_argument("--keep", action="store_true", help="leave the player running")
    run.add_argument("--all", action="store_true", help="every case, changed or not")
    run.add_argument("--software-gl", help="the Windows VM: a folder with Mesa's opengl32.dll and libgallium_wgl.dll "
                                           "(mesa-dist-win's release-msvc x64), put beside the player")
    run.add_argument("--dry-run", action="store_true", help="say which cases would run, and why")
    report = commands.add_parser("report")
    report.add_argument("out", nargs="?", default=os.path.join(
        os.environ.get("MXM_BUILD_ROOT", str(WORKSPACE / "target-shared")), "platform-check"))
    report.add_argument("--reference", default="linux-vm")
    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args)
    else:
        sys.path.insert(0, str(HERE))
        import report as reporting
        reporting.main(args)


if __name__ == "__main__":
    main()
