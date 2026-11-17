#!/usr/bin/env bash
# The Windows 11 test VM (vm/AGENTS.md): Microsoft's 90-day evaluation under QEMU and KVM, built by
# this script so a new one is one command when the evaluation runs out.
#
#   vm.sh build [--again]   a fresh VM from the one .iso here, unattended (about half an hour); it
#                           ends with the snapshot "clean". --again replaces the VM there is.
#   vm.sh run               starts the VM; what is done in it stays until `reset`.
#   vm.sh reset             back to the clean install: its disk, firmware variables and TPM.
#   vm.sh serve <folder>    serves a folder to the VM, at http://10.0.2.2:8000/ inside it.
#
# The window opens on Hyprland's workspace 4, silently. MXM_VM_HEADLESS=1 runs it with no window;
# MXM_VM_MEMORY (8G) and MXM_VM_CPUS (8) size it.
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
CODE=/usr/share/edk2/x64/OVMF_CODE.4m.fd
VARS_TEMPLATE=/usr/share/edk2/x64/OVMF_VARS.4m.fd
MEMORY="${MXM_VM_MEMORY:-8G}"
CPUS="${MXM_VM_CPUS:-8}"

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
        -nic user,model=e1000e
        -vga std
        -audiodev pipewire,id=snd -device ich9-intel-hda -device hda-output,audiodev=snd
        -monitor "unix:$MONITOR,server,nowait"
        -pidfile "$PIDFILE")
    if [[ "${MXM_VM_HEADLESS:-0}" == 1 ]]; then ARGS+=(-display none); else ARGS+=(-display gtk,zoom-to-fit=on); fi
}

# Starts QEMU, on workspace 4 under Hyprland, and returns once it runs.
launch() {
    rm -f "$PIDFILE" "$MONITOR"
    for arg in "${ARGS[@]}"; do [[ "$arg" != *[[:space:]\"\']* ]] || die "an argument with a space or a quote: $arg"; done
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null && [[ "${MXM_VM_HEADLESS:-0}" != 1 ]]; then
        hyprctl dispatch "hl.dsp.exec_cmd(\"${ARGS[*]}\", { workspace = \"4 silent\" })" >/dev/null
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
    mkdir -p "$STATE/unattend"
    cp "$HERE/autounattend.xml" "$STATE/unattend/"
    xorriso -as mkisofs -quiet -V UNATTEND -J -r -o "$UNATTEND" "$STATE/unattend"
    cp "$VARS_TEMPLATE" "$VARS"
    qemu-img create -q -f qcow2 "$DISK" 64G
    start_tpm
    qemu_args
    ARGS+=(-drive "file=$iso,media=cdrom,if=none,id=cd0,readonly=on" -device ide-cd,drive=cd0,bus=ide.1,bootindex=0
        -drive "file=$UNATTEND,media=cdrom,if=none,id=cd1,readonly=on" -device ide-cd,drive=cd1,bus=ide.2)
    echo "installing Windows from $(basename "$iso"): about half an hour, unattended; it shuts down when done"
    launch
    # The ISO asks "Press any key to boot from CD or DVD" once: answer it for the first seconds only,
    # so setup's own reboots go on from the disk.
    for _ in $(seq 40); do monitor "sendkey ret"; sleep 0.5; done
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
    echo "the VM runs (QEMU's window on workspace 4); shut Windows down to stop it"
}

reset() {
    [[ -e "$DISK" ]] || die "no VM yet: \`vm.sh build\`"
    running && die "the VM is running; shut it down first"
    qemu-img snapshot -a clean "$DISK"
    cp "$CLEAN_VARS" "$VARS"
    rm -rf "$TPM"
    cp -a "$CLEAN_TPM" "$TPM"
    echo "reset to the clean install"
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
    reset) reset ;;
    serve) serve "${2:-}" ;;
    *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
