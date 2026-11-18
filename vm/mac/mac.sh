#!/usr/bin/env bash
# The owner's Mac, driven over SSH (vm/AGENTS.md): `ssh mac` (its Bonjour name; its address changes).
# Screenshots need Screen Recording and input needs Accessibility for /usr/libexec/sshd-keygen-wrapper,
# both granted by the owner (2026-11-18).
#
#   mac.sh install            builds mxm-input.swift on the Mac into ~/.local/bin/mxm-input
#   mac.sh screen <file.png>  the Mac's screen, as a picture here (the Mac's copy deleted)
#   mac.sh click <x> <y>      a click at the picture's pixel coordinates
#   mac.sh move <x> <y>       the pointer there
#   mac.sh type <text>        typed text
#   mac.sh key <keys>…        keys, as `mxm-input key` names them (return, cmd+shift+g …)
#   mac.sh front              the app in front
#   mac.sh windows <pid>      a process's windows on screen (id, x, y, width, height, title)
#   mac.sh raise <pid> <title>  that window in front, its app frontmost
#
# A screenshot holds whatever is on the owner's screen: take one for a test, crop what the test
# needs, delete the rest.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${MXM_MAC:-mac}"
INPUT='~/.local/bin/mxm-input'

die() { echo "mac.sh: $*" >&2; exit 1; }

case "${1:-}" in
    install)
        scp -q "$HERE/mxm-input.swift" "$HOST:/tmp/mxm-input.swift"
        ssh "$HOST" 'mkdir -p ~/.local/bin && swiftc -O /tmp/mxm-input.swift -o ~/.local/bin/mxm-input && rm /tmp/mxm-input.swift && ~/.local/bin/mxm-input check'
        ;;
    screen)
        [[ -n "${2:-}" ]] || die "screen needs a file name"
        ssh "$HOST" 'screencapture -x /tmp/mxm-screen.png'
        scp -q "$HOST:/tmp/mxm-screen.png" "$2"
        ssh "$HOST" 'rm -f /tmp/mxm-screen.png'
        echo "$2"
        ;;
    click|move)
        (( $# == 3 )) || die "$1 needs x and y"
        ssh "$HOST" "$INPUT $1 $2 $3"
        ;;
    type)
        (( $# == 2 )) || die "type needs one text"
        ssh "$HOST" "$INPUT type $(printf '%q' "$(printf '%q' "$2")")"
        ;;
    key)
        shift
        for k in "$@"; do ssh "$HOST" "$INPUT key $k"; done
        ;;
    front)
        ssh "$HOST" 'lsappinfo info -only name "$(lsappinfo front)"'
        ;;
    windows)
        (( $# == 2 )) || die "windows needs a pid"
        ssh "$HOST" "$INPUT windows $2"
        ;;
    raise)
        (( $# == 3 )) || die "raise needs a pid and a window title"
        ssh "$HOST" "$INPUT raise $2 $(printf '%q' "$(printf '%q' "$3")")"
        ;;
    *)
        awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 2 ;;
esac
