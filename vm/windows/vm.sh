#!/usr/bin/env bash
# The Windows 11 test VM (vm/AGENTS.md): Microsoft's 90-day evaluation under QEMU and KVM, built by
# this script so a new one is one command when the evaluation runs out.
#
#   vm.sh build [--again]   a fresh VM from the one .iso here, unattended (about ten minutes); it
#                           ends with the snapshot "clean". --again replaces the VM there is.
#   vm.sh run               starts the VM; what is done in it stays until `reset`.
#   vm.sh stop              shuts Windows down, keeping what was done in it.
#   vm.sh reset             back to the clean install: its disk, firmware variables and TPM. A
#                           running VM is switched off first: nothing in it is kept anyway.
#   vm.sh serve <folder>    serves a folder to the VM, at http://10.0.2.2:8000/ inside it.
#   vm.sh ssh [command]     a PowerShell in the running VM, or one command there (as `mxm`).
#   vm.sh copy <path>... <dest>   copies files or folders into the VM (dest a Windows path).
#   vm.sh desktop <command> starts a program on the VM's desktop (SSH's own commands have none).
#
# The window opens on Hyprland's workspace 6, silently and fullscreen. MXM_VM_HEADLESS=1 runs it with no window;
# MXM_VM_MEMORY (8G), MXM_VM_CPUS (8) and MXM_VM_SCREEN (2560x1440) size it. SSH reaches the VM at this machine's
# 127.0.0.1:2222 alone, with the VM's own key in state/ssh/, made by `build`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HERE/state"
DISK="$STATE/windows.qcow2"
VARS="$STATE/vars.fd"
CLEAN_VARS="$STATE/vars-clean.fd"
TPM="$STATE/tpm"
CLEAN_TPM="$STATE/tpm-clean"
SOCK="$STATE/swtpm.sock"
MONITOR="$STATE/monitor.sock"
PIDFILE="$STATE/qemu.pid"
UNATTEND="$STATE/autounattend.iso"
KEY="$STATE/ssh/id_ed25519"
SSH_PORT=2222
# Microsoft's OpenSSH for Windows, installed during setup from the answer-file disc.
OPENSSH_URL=https://github.com/PowerShell/Win32-OpenSSH/releases/download/10.0.0.0p2-Preview/OpenSSH-Win64-v10.0.0.0.msi
OPENSSH_SHA256=ddec9c53864280759cf9f74791cefd387100e3946aa849a1c138a4ed1b96b7d9
CODE=/usr/share/edk2/x64/OVMF_CODE.4m.fd
VARS_TEMPLATE=/usr/share/edk2/x64/OVMF_VARS.4m.fd
MEMORY="${MXM_VM_MEMORY:-8G}"
CPUS="${MXM_VM_CPUS:-8}"
# The screen Windows starts with: the firmware takes VGA's preferred size, and Windows' basic display
# driver keeps the firmware's mode. At the clean install's 1280x800 a plugin's editor opened shorter
# than on the other platforms and laid itself out otherwise (the platform check, 2026-11-18); at
# 2560x1440 it opens as on the Linux VM, which takes its fullscreen window's size, this machine's
# monitor's.
SCREEN="${MXM_VM_SCREEN:-2560x1440}"

die() { echo "vm.sh: $*" >&2; exit 1; }

running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

the_iso() {
    local isos=()
    for iso in "$HERE"/*.iso; do [[ -f "$iso" ]] && isos+=("$iso"); done
    [[ ${#isos[@]} -eq 1 ]] || die "put exactly one Windows 11 Enterprise evaluation .iso in $HERE (found ${#isos[@]})"
    echo "${isos[0]}"
}

start_tpm() {
    mkdir -p "$TPM"
    rm -f "$SOCK"
    swtpm socket --tpm2 --tpmstate dir="$TPM" --ctrl type=unixio,path="$SOCK" \
        --terminate --daemon --log file="$STATE/swtpm.log"
    for _ in $(seq 50); do [[ -S "$SOCK" ]] && return; sleep 0.1; done
    die "swtpm did not start (see $STATE/swtpm.log)"
}

# The VM's QEMU command; every argument is free of spaces, so Hyprland can be handed it as one line.
qemu_args() {
    ARGS=(qemu-system-x86_64 -name MXM-Windows-VM
        -machine q35,accel=kvm -cpu host -smp "$CPUS" -m "$MEMORY"
        -drive "if=pflash,format=raw,readonly=on,file=$CODE"
        -drive "if=pflash,format=raw,file=$VARS"
        -chardev "socket,id=chrtpm,path=$SOCK" -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0
        -drive "file=$DISK,if=none,id=disk,format=qcow2,discard=unmap" -device ide-hd,drive=disk,bus=ide.0,bootindex=1
        -device qemu-xhci -device usb-tablet
        -nic "user,model=e1000e,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22"
        -vga none -device "VGA,xres=${SCREEN%x*},yres=${SCREEN#*x}"
        -audiodev pipewire,id=snd -device ich9-intel-hda -device hda-output,audiodev=snd
        -monitor "unix:$MONITOR,server,nowait"
        -pidfile "$PIDFILE")
    if [[ "${MXM_VM_HEADLESS:-0}" == 1 ]]; then ARGS+=(-display none); else ARGS+=(-display gtk,zoom-to-fit=on,show-menubar=off); fi
}

# QEMU's window fullscreen once it shows, so the VM's screen is the monitor's, the same every run.
fullscreen() {
    local address
    for _ in $(seq 100); do
        address="$(hyprctl clients -j | python3 -c 'import json, sys
print(next((c["address"] for c in json.load(sys.stdin) if c["title"] == "QEMU (MXM-Windows-VM)"), ""))')"
        if [[ -n "$address" ]]; then
            hyprctl dispatch "hl.dsp.window.fullscreen({ window = \"address:$address\" })" >/dev/null
            return
        fi
        sleep 0.2
    done
}

# Starts QEMU, fullscreen on workspace 6 under Hyprland, and returns once it runs. Each VM has a
# workspace of its own, 5 the Linux VM's and 6 Windows' (the owner, 2026-11-18: "You can put the VMs
# on different workspaces and go fullscren if that is any help. 5 and 6 are not used").
launch() {
    rm -f "$PIDFILE" "$MONITOR"
    for arg in "${ARGS[@]}"; do [[ "$arg" != *[[:space:]\"\']* ]] || die "an argument with a space or a quote: $arg"; done
    # A shell started outside the desktop (an agent's) lacks Hyprland's variable: take the running one's.
    local runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr"
    if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" && -d "$runtime" ]]; then
        HYPRLAND_INSTANCE_SIGNATURE="$(ls -t "$runtime" | head -1)"
        export HYPRLAND_INSTANCE_SIGNATURE
    fi
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null && [[ "${MXM_VM_HEADLESS:-0}" != 1 ]]; then
        hyprctl dispatch "hl.dsp.exec_cmd(\"${ARGS[*]}\", { workspace = \"6 silent\" })" >/dev/null
        fullscreen &
    else
        "${ARGS[@]}" >"$STATE/qemu.log" 2>&1 &
    fi
    for _ in $(seq 300); do running && return; sleep 0.1; done
    die "QEMU did not start"
}

wait_for_exit() { while running; do sleep 2; done; }

monitor() { printf '%s\n' "$1" | socat - "UNIX-CONNECT:$MONITOR" >/dev/null 2>&1 || true; }

build() {
    local again="${1:-}"
    local iso; iso="$(the_iso)"
    running && die "the VM is running; shut it down first"
    if [[ -e "$DISK" && "$again" != --again ]]; then
        die "there is a VM already; \`vm.sh build --again\` replaces it, \`vm.sh reset\` restores its clean install"
    fi
    rm -rf "$STATE"
    mkdir -p "$STATE/unattend" "$STATE/ssh"
    cp "$HERE/autounattend.xml" "$STATE/unattend/"
    ssh-keygen -q -t ed25519 -N "" -C mxm-windows-vm -f "$KEY"
    cp "$KEY.pub" "$STATE/unattend/administrators_authorized_keys"
    curl -fsSL -o "$STATE/unattend/OpenSSH-Win64.msi" "$OPENSSH_URL"
    echo "$OPENSSH_SHA256  $STATE/unattend/OpenSSH-Win64.msi" | sha256sum -c --quiet - ||
        die "the OpenSSH installer isn't the one pinned here"
    xorriso -as mkisofs -quiet -V UNATTEND -J -r -o "$UNATTEND" "$STATE/unattend"
    cp "$VARS_TEMPLATE" "$VARS"
    qemu-img create -q -f qcow2 "$DISK" 64G
    start_tpm
    qemu_args
    ARGS+=(-drive "file=$iso,media=cdrom,if=none,id=cd0,readonly=on" -device ide-cd,drive=cd0,bus=ide.1,bootindex=0
        -drive "file=$UNATTEND,media=cdrom,if=none,id=cd1,readonly=on" -device ide-cd,drive=cd1,bus=ide.2)
    echo "installing Windows from $(basename "$iso"): about ten minutes, unattended; it shuts down when done"
    launch
    # The ISO asks "Press any key to boot from CD or DVD" once: answer it for the first seconds only,
    # so setup's own reboots go on from the disk. With `x`, not Enter: setup's window comes up within
    # seconds, and Enter there pressed its Cancel button (2026-11-17); `x` is no button's shortcut.
    for _ in $(seq 40); do monitor "sendkey x"; sleep 0.5; done
    wait_for_exit
    local used; used="$(qemu-img info --output=json "$DISK" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["actual-size"])')"
    (( used > 8 * 1024 * 1024 * 1024 )) || die "the VM stopped before Windows was installed (its disk holds $((used / 1024 / 1024)) MB); \`vm.sh build --again\`"
    qemu-img snapshot -c clean "$DISK"
    cp "$VARS" "$CLEAN_VARS"
    cp -a "$TPM" "$CLEAN_TPM"
    rm -rf "$STATE/unattend" "$UNATTEND"
    echo "built: the snapshot \"clean\" is taken; \`vm.sh run\` starts it"
}

run() {
    [[ -e "$DISK" ]] || die "no VM yet: \`vm.sh build\`"
    running && die "the VM is running already"
    start_tpm
    qemu_args
    launch
    echo "the VM runs (QEMU's window fullscreen on workspace 6); shut Windows down to stop it"
}

stop() {
    running || { echo "the VM isn't running"; return; }
    monitor "system_powerdown"
    wait_for_exit
    echo "stopped"
}

reset() {
    [[ -e "$DISK" ]] || die "no VM yet: \`vm.sh build\`"
    # Switched off, not shut down: a shutdown can stop to install updates (2026-11-17), and nothing
    # in the VM is kept.
    if running; then
        monitor "quit"
        wait_for_exit
    fi
    qemu-img snapshot -a clean "$DISK"
    cp "$CLEAN_VARS" "$VARS"
    rm -rf "$TPM"
    cp -a "$CLEAN_TPM" "$TPM"
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
    (( $# >= 2 )) || die "copy needs what to copy and where, a Windows path"
    local dest="${*: -1}"
    scp -r -P "$SSH_PORT" -i "$KEY" -o StrictHostKeyChecking=accept-new \
        -o "UserKnownHostsFile=$STATE/ssh/known_hosts" -o LogLevel=ERROR "${@:1:$#-1}" "mxm@127.0.0.1:$dest"
}

# A program SSH starts runs with no desktop; a scheduled task for the logged-on user runs on it.
vm_desktop() {
    running || die "the VM isn't running: \`vm.sh run\`"
    (( $# >= 1 )) || die "desktop needs a command"
    local command="$*"
    ssh "${ssh_options[@]}" mxm@127.0.0.1 \
        "schtasks /create /tn mxm-desktop /tr '$command' /sc once /st 00:00 /it /f | Out-Null; schtasks /run /tn mxm-desktop | Out-Null; 'started on the desktop: $command'"
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
    *) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 2 ;;
esac
