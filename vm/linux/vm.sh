#!/usr/bin/env bash
# The Linux test VM (vm/AGENTS.md): Ubuntu 24.04 LTS with the minimal GNOME desktop, as a tester
# installs it, under QEMU and KVM; built by this script from Ubuntu's own cloud image, so a new one
# is one command (the owner, 2026-11-18: "build the Linux VM").
#
#   vm.sh build [--again]   a fresh VM: Ubuntu's cloud image, checked against its SHA256SUMS, with
#                           the desktop installed on its first boot by cloud-init (fifteen minutes or
#                           so, unattended); it ends with the snapshot "clean". --again replaces it.
#   vm.sh run               starts the VM; what is done in it stays until `reset`.
#   vm.sh stop              shuts Ubuntu down, keeping what was done in it.
#   vm.sh reset             back to the clean install. A running VM is switched off first.
#   vm.sh serve <folder>    serves a folder to the VM, at http://10.0.2.2:8000/ inside it.
#   vm.sh ssh [command]     a shell in the running VM, or one command there (as `mxm`).
#   vm.sh copy <path>... <dest>   copies files or folders into the VM.
#   vm.sh desktop <command> starts a program in the logged-on user's GNOME session.
#   vm.sh screen <file.png> the VM's screen, as a picture.
#   vm.sh click <x> <y>     a click at the screen's coordinates, as `screen` shows them.
#   vm.sh key <keys>        keys, as QEMU's `sendkey` names them (`ret`, `ctrl-c`).
#
# The window opens on Hyprland's workspace 5, silently and fullscreen. MXM_VM_HEADLESS=1 runs it with no window;
# MXM_VM_MEMORY (8G), MXM_VM_CPUS (8) and MXM_VM_SCREEN (2560x1440) size it. SSH reaches the VM at this machine's
# 127.0.0.1:2223 alone, with the VM's own key in state/ssh/, made by `build`. The account is `mxm`,
# password `mxm`, logged on to GNOME by itself.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HERE/state"
DISK="$STATE/ubuntu.qcow2"
SEED="$STATE/seed.iso"
MONITOR="$STATE/monitor.sock"
QMP="$STATE/qmp.sock"
PIDFILE="$STATE/qemu.pid"
KEY="$STATE/ssh/id_ed25519"
SSH_PORT=2223
RELEASE="${MXM_VM_UBUNTU:-noble}"
IMAGES="https://cloud-images.ubuntu.com/$RELEASE/current"
MEMORY="${MXM_VM_MEMORY:-8G}"
CPUS="${MXM_VM_CPUS:-8}"
# The screen QEMU gives the VM at first, the size of its fullscreen window on this machine's monitor
# (MXM_VM_SCREEN, the Windows VM's too, so a plugin's editor opens at one size in both: the platform
# check, 2026-11-18). GNOME may follow a later change of QEMU's window, so `click` measures the
# screen each time.
SCREEN="${MXM_VM_SCREEN:-2560x1440}"
SCREEN_W="${SCREEN%x*}"
SCREEN_H="${SCREEN#*x}"

die() { echo "vm.sh: $*" >&2; exit 1; }

running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

# The VM's QEMU command; every argument is free of spaces, so Hyprland can be handed it as one line.
qemu_args() {
    ARGS=(qemu-system-x86_64 -name MXM-Linux-VM
        -machine q35,accel=kvm -cpu host -smp "$CPUS" -m "$MEMORY"
        -drive "file=$DISK,if=virtio,format=qcow2,discard=unmap"
        -device qemu-xhci -device usb-tablet -device usb-kbd
        -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22"
        -device "virtio-vga,xres=$SCREEN_W,yres=$SCREEN_H"
        -audiodev pipewire,id=snd -device ich9-intel-hda -device hda-output,audiodev=snd
        -monitor "unix:$MONITOR,server,nowait"
        -qmp "unix:$QMP,server,nowait"
        -pidfile "$PIDFILE")
    if [[ "${MXM_VM_HEADLESS:-0}" == 1 ]]; then ARGS+=(-display none); else ARGS+=(-display gtk,zoom-to-fit=on,show-menubar=off); fi
}

# QEMU's window fullscreen once it shows, so the VM's screen is the monitor's, the same every run.
fullscreen() {
    local address
    for _ in $(seq 100); do
        address="$(hyprctl clients -j | python3 -c 'import json, sys
print(next((c["address"] for c in json.load(sys.stdin) if c["title"] == "QEMU (MXM-Linux-VM)"), ""))')"
        if [[ -n "$address" ]]; then
            hyprctl dispatch "hl.dsp.window.fullscreen({ window = \"address:$address\" })" >/dev/null
            return
        fi
        sleep 0.2
    done
}

# Starts QEMU, fullscreen on workspace 5 under Hyprland, and returns once it runs. Each VM has a
# workspace of its own, 5 the Linux VM's and 6 Windows' (the owner, 2026-11-18: "You can put the VMs
# on different workspaces and go fullscren if that is any help. 5 and 6 are not used").
launch() {
    rm -f "$PIDFILE" "$MONITOR" "$QMP"
    for arg in "${ARGS[@]}"; do [[ "$arg" != *[[:space:]\"\']* ]] || die "an argument with a space or a quote: $arg"; done
    # A shell started outside the desktop (an agent's) lacks Hyprland's variable: take the running one's.
    local runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
    if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" && -d "$runtime" ]]; then
        HYPRLAND_INSTANCE_SIGNATURE="$(ls -t "$runtime" | head -1)"
        export HYPRLAND_INSTANCE_SIGNATURE
    fi
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null && [[ "${MXM_VM_HEADLESS:-0}" != 1 ]]; then
        hyprctl dispatch "hl.dsp.exec_cmd(\"${ARGS[*]}\", { workspace = \"5 silent\" })" >/dev/null
        fullscreen &
    else
        "${ARGS[@]}" >"$STATE/qemu.log" 2>&1 &
    fi
    for _ in $(seq 300); do running && return; sleep 0.1; done
    die "QEMU did not start"
}

wait_for_exit() { while running; do sleep 2; done; }

monitor() { printf '%s\n' "$1" | socat - "UNIX-CONNECT:$MONITOR" >/dev/null 2>&1 || true; }

# What cloud-init does on the first boot: the user, the desktop, the rest a tester's install has.
user_data() {
    local hash; hash="$(openssl passwd -6 mxm)"
    cat <<EOF
#cloud-config
hostname: mxm-linux-test
users:
  - name: mxm
    gecos: MXM
    groups: [sudo, audio, video]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: false
    passwd: "$hash"
    ssh_authorized_keys:
      - $(cat "$KEY.pub")
ssh_pwauth: false
package_update: true
package_upgrade: false
# The minimal desktop, as Ubuntu's installer's "minimal installation" gives it; the generic kernel
# for its sound card's driver (the cloud image's kernel leaves it out).
packages:
  - ubuntu-desktop-minimal
  - linux-generic
write_files:
  # No Firefox: Ubuntu's package installs its snap, and the snap store didn't answer from the VM,
  # which held the install for its 50 minutes of retries (2026-11-18). Files are copied in over SSH.
  - path: /etc/apt/preferences.d/99mxm-no-firefox
    content: |
      Package: firefox*
      Pin: release o=Ubuntu
      Pin-Priority: -1
  - path: /etc/gdm3/custom.conf
    content: |
      [daemon]
      AutomaticLoginEnable=true
      AutomaticLogin=mxm
  - path: /etc/apt/apt.conf.d/99mxm-no-automatic-updates
    content: |
      APT::Periodic::Update-Package-Lists "0";
      APT::Periodic::Unattended-Upgrade "0";
  - path: /etc/dconf/profile/user
    content: |
      user-db:user
      system-db:local
  - path: /etc/dconf/db/local.d/00-mxm-test
    content: |
      [org/gnome/desktop/session]
      idle-delay=uint32 0
      [org/gnome/desktop/screensaver]
      lock-enabled=false
      [org/gnome/desktop/notifications]
      show-banners=false
runcmd:
  - [systemctl, set-default, graphical.target]
  - [sh, -c, "systemctl disable --now unattended-upgrades apt-daily.timer apt-daily-upgrade.timer || true"]
  - [dconf, update]
  - [sh, -c, "install -d -o mxm -g mxm /home/mxm/.config && echo yes > /home/mxm/.config/gnome-initial-setup-done && chown mxm:mxm /home/mxm/.config/gnome-initial-setup-done"]
  # Ubuntu's Software Updater asks to update over whatever is being tested (2026-11-18).
  - [rm, -f, /etc/xdg/autostart/update-notifier.desktop]
  - [touch, /etc/cloud/cloud-init.disabled]
power_state:
  mode: poweroff
  condition: true
EOF
}

build() {
    local again="${1:-}"
    running && die "the VM is running; shut it down first"
    if [[ -e "$DISK" && "$again" != --again ]]; then
        die "there is a VM already; \`vm.sh build --again\` replaces it, \`vm.sh reset\` restores its clean install"
    fi
    rm -rf "$STATE"
    mkdir -p "$STATE/seed" "$STATE/ssh" "$STATE/download"
    local name="$RELEASE-server-cloudimg-amd64.img"
    echo "downloading Ubuntu's $RELEASE cloud image"
    curl -fsSL -o "$STATE/download/SHA256SUMS" "$IMAGES/SHA256SUMS"
    curl -fL --progress-bar -o "$STATE/download/$name" "$IMAGES/$name"
    (cd "$STATE/download" && grep " \*\?$name\$" SHA256SUMS | sed 's/ \*/  /' | sha256sum -c --quiet -) ||
        die "the cloud image isn't the one Ubuntu's SHA256SUMS names"
    qemu-img convert -q -O qcow2 "$STATE/download/$name" "$DISK"
    qemu-img resize -q "$DISK" 40G
    rm -rf "$STATE/download"
    ssh-keygen -q -t ed25519 -N "" -C mxm-linux-vm -f "$KEY"
    user_data > "$STATE/seed/user-data"
    printf 'instance-id: mxm-linux-test\nlocal-hostname: mxm-linux-test\n' > "$STATE/seed/meta-data"
    xorriso -as mkisofs -quiet -V CIDATA -J -r -o "$SEED" "$STATE/seed"
    qemu_args
    ARGS+=(-drive "file=$SEED,media=cdrom,if=none,id=cd0,readonly=on" -device ide-cd,drive=cd0,bus=ide.1)
    echo "installing the desktop on the first boot: fifteen minutes or so, unattended; it shuts down when done"
    launch
    wait_for_exit
    local used; used="$(qemu-img info --output=json "$DISK" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["actual-size"])')"
    (( used > 5 * 1024 * 1024 * 1024 )) || die "the VM stopped before the desktop was installed (its disk holds $((used / 1024 / 1024)) MB); \`vm.sh build --again\`"
    qemu-img snapshot -c clean "$DISK"
    rm -rf "$STATE/seed" "$SEED"
    echo "built: the snapshot \"clean\" is taken; \`vm.sh run\` starts it"
}

run() {
    [[ -e "$DISK" ]] || die "no VM yet: \`vm.sh build\`"
    running && die "the VM is running already"
    qemu_args
    launch
    echo "the VM runs (QEMU's window fullscreen on workspace 5); \`vm.sh stop\` shuts it down"
}

stop() {
    running || { echo "the VM isn't running"; return; }
    monitor "system_powerdown"
    wait_for_exit
    echo "stopped"
}

reset() {
    [[ -e "$DISK" ]] || die "no VM yet: \`vm.sh build\`"
    if running; then
        monitor "quit"
        wait_for_exit
    fi
    qemu-img snapshot -a clean "$DISK"
    echo "reset to the clean install"
}

ssh_options=(-i "$KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new
    -o "UserKnownHostsFile=$STATE/ssh/known_hosts" -o ConnectTimeout=10 -o LogLevel=ERROR)

vm_ssh() {
    running || die "the VM isn't running: \`vm.sh run\`"
    exec ssh "${ssh_options[@]}" mxm@127.0.0.1 "$@"
}

vm_copy() {
    running || die "the VM isn't running: \`vm.sh run\`"
    (( $# >= 2 )) || die "copy needs what to copy and where"
    local dest="${*: -1}"
    scp -r -P "$SSH_PORT" -i "$KEY" -o StrictHostKeyChecking=accept-new \
        -o "UserKnownHostsFile=$STATE/ssh/known_hosts" -o LogLevel=ERROR "${@:1:$#-1}" "mxm@127.0.0.1:$dest"
}

# A program SSH starts has no desktop; one the user's systemd starts has GNOME's environment.
vm_desktop() {
    running || die "the VM isn't running: \`vm.sh run\`"
    (( $# >= 1 )) || die "desktop needs a command"
    local command; command="$(printf '%q ' "$@")"
    ssh "${ssh_options[@]}" mxm@127.0.0.1 "systemd-run --user --collect --quiet -- bash -lc $(printf '%q' "$command") && echo 'started on the desktop: $*'"
}

screen() {
    running || die "the VM isn't running: \`vm.sh run\`"
    [[ -n "${1:-}" ]] || die "screen needs a file name"
    local file; file="$(realpath -m "$1")"
    monitor "screendump $file -f png"
    for _ in $(seq 50); do [[ -s "$file" ]] && { echo "$file"; return; }; sleep 0.1; done
    die "no picture came"
}

# QMP's input events: the tablet takes absolute positions, 0 to 32767 across the screen.
qmp() {
    python3 -I - "$QMP" "$@" <<'EOF'
import json, socket, sys, time
path, kind, args = sys.argv[1], sys.argv[2], sys.argv[3:]
s = socket.socket(socket.AF_UNIX); s.connect(path); f = s.makefile("rw")
def say(command, **arguments):
    f.write(json.dumps({"execute": command, "arguments": arguments} if arguments else {"execute": command}) + "\n"); f.flush()
    while True:
        answer = json.loads(f.readline())
        if "return" in answer or "error" in answer:
            return answer
json.loads(f.readline()); say("qmp_capabilities")
if kind == "click":
    x, y, w, h = map(int, args)
    say("input-send-event", events=[
        {"type": "abs", "data": {"axis": "x", "value": x * 32767 // (w - 1)}},
        {"type": "abs", "data": {"axis": "y", "value": y * 32767 // (h - 1)}}])
    time.sleep(0.15)
    for down in (True, False):
        say("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": "left"}}])
        time.sleep(0.08)
EOF
}

click() {
    running || die "the VM isn't running: \`vm.sh run\`"
    (( $# == 2 )) || die "click needs x and y"
    # The screen's size now, from a screendump's PNG header: it follows QEMU's window.
    local shot="$STATE/click-size.png" size
    rm -f "$shot"
    monitor "screendump $shot -f png"
    for _ in $(seq 50); do [[ -s "$shot" ]] && break; sleep 0.1; done
    size="$(python3 -I -c 'import struct,sys; print(*struct.unpack(">II", open(sys.argv[1],"rb").read()[16:24]))' "$shot")"
    rm -f "$shot"
    qmp click "$1" "$2" $size
}

key() {
    running || die "the VM isn't running: \`vm.sh run\`"
    for k in "$@"; do monitor "sendkey $k"; sleep 0.1; done
}

serve() {
    local folder="${1:-}"
    [[ -d "$folder" ]] || die "serve needs a folder"
    echo "serving $folder at http://10.0.2.2:8000/ inside the VM (this machine's 127.0.0.1:8000); Ctrl+C stops it"
    exec python3 -I -m http.server 8000 --bind 127.0.0.1 --directory "$folder"
}

case "${1:-}" in
    build) build "${2:-}" ;;
    run) run ;;
    stop) stop ;;
    reset) reset ;;
    serve) serve "${2:-}" ;;
    ssh) shift; vm_ssh "$@" ;;
    copy) shift; vm_copy "$@" ;;
    desktop) shift; vm_desktop "$@" ;;
    screen) screen "${2:-}" ;;
    click) shift; click "$@" ;;
    key) shift; key "$@" ;;
    *) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 2 ;;
esac
