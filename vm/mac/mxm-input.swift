// Mouse and keyboard on the owner's Mac, for an agent driving it over SSH (vm/AGENTS.md).
// Built on the Mac by `mac.sh install` into ~/.local/bin/mxm-input. It needs Accessibility for
// /usr/libexec/sshd-keygen-wrapper (the owner granted it, 2026-11-18); `check` says whether it has it.
//
//   mxm-input check              whether macOS lets it send events; the screen's size and scale
//   mxm-input click <x> <y>      a left click at a screenshot's pixel coordinates
//   mxm-input move <x> <y>       the pointer there, no click
//   mxm-input drag <x> <y> <x2> <y2>  pressed at the first point, moved to the second in steps,
//                                released there: a note dragged in a plugin's window, say
//   mxm-input type <text>        the text, as typed
//   mxm-input key <name>         one key, with modifiers: return, tab, escape, space, delete, up,
//                                down, left, right, or a letter; cmd+q, shift+tab, cmd+shift+g …
//   mxm-input windows <pid>      the process's windows on screen, one per line: id, x, y, width,
//                                height (points) and title, tab-separated (titles need Screen
//                                Recording)
//   mxm-input raise <pid> <title>  that process's window of that title in front, its app frontmost
//                                (Accessibility): for `screencapture -R` of just its rectangle,
//                                since neither `screencapture -l` nor ScreenCaptureKit may capture one
//                                window over SSH (2026-11-18)
//
// Coordinates are pixels as `screencapture` takes them; macOS places events in points, so they are
// divided by the main display's scale (2 on a Retina screen).

import ApplicationServices
import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

let display = CGMainDisplayID()
let scale: CGFloat = {
    guard let mode = CGDisplayCopyDisplayMode(display), mode.width > 0 else { return 1 }
    return CGFloat(mode.pixelWidth) / CGFloat(mode.width)
}()

func point(_ x: String, _ y: String) -> CGPoint {
    guard let x = Double(x), let y = Double(y) else { fail("mxm-input: x and y are numbers") }
    return CGPoint(x: CGFloat(x) / scale, y: CGFloat(y) / scale)
}

func post(_ event: CGEvent?) {
    guard let event = event else { fail("mxm-input: macOS made no event") }
    event.post(tap: .cghidEventTap)
}

func mouse(_ type: CGEventType, _ at: CGPoint) {
    post(CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: at, mouseButton: .left))
}

let keys: [String: CGKeyCode] = [
    "return": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35,
    "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
]

func key(_ combination: String) {
    var parts = combination.lowercased().split(separator: "+").map(String.init)
    guard let name = parts.popLast(), let code = keys[name] else {
        fail("mxm-input: no key named \(combination)")
    }
    var flags: CGEventFlags = []
    for modifier in parts {
        switch modifier {
        case "cmd": flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "alt", "option": flags.insert(.maskAlternate)
        case "ctrl": flags.insert(.maskControl)
        default: fail("mxm-input: no modifier named \(modifier)")
        }
    }
    for down in [true, false] {
        let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down)
        event?.flags = flags
        post(event)
        usleep(30_000)
    }
}

func type(_ text: String) {
    for character in text {
        let units = Array(String(character).utf16)
        for down in [true, false] {
            let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: down)
            event?.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
            post(event)
        }
        usleep(15_000)
    }
}

let args = Array(CommandLine.arguments.dropFirst())
switch args.first {
case "check":
    let bounds = CGDisplayBounds(display)
    print("trusted \(AXIsProcessTrusted()) screen \(Int(bounds.width))x\(Int(bounds.height)) points, scale \(scale)")
case "click" where args.count == 3:
    let at = point(args[1], args[2])
    mouse(.mouseMoved, at)
    usleep(120_000)
    mouse(.leftMouseDown, at)
    usleep(60_000)
    mouse(.leftMouseUp, at)
case "move" where args.count == 3:
    mouse(.mouseMoved, point(args[1], args[2]))
case "drag" where args.count == 5:
    let (from, to) = (point(args[1], args[2]), point(args[3], args[4]))
    mouse(.mouseMoved, from)
    usleep(120_000)
    mouse(.leftMouseDown, from)
    usleep(150_000)
    let steps = 20
    for step in 1...steps {
        let t = CGFloat(step) / CGFloat(steps)
        mouse(.leftMouseDragged, CGPoint(x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t))
        usleep(20_000)
    }
    usleep(150_000)
    mouse(.leftMouseUp, to)
case "type" where args.count == 2:
    type(args[1])
case "key" where args.count == 2:
    key(args[1])
case "windows" where args.count == 2:
    guard let pid = Int(args[1]) else { fail("mxm-input: a pid is a number") }
    let listed = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
    for window in (listed as? [[String: Any]]) ?? [] {
        guard (window[kCGWindowOwnerPID as String] as? Int) == pid,
              (window[kCGWindowLayer as String] as? Int) == 0,
              let id = window[kCGWindowNumber as String] as? Int,
              let bounds = window[kCGWindowBounds as String] as? [String: Double] else { continue }
        let title = (window[kCGWindowName as String] as? String) ?? ""
        let values = ["X", "Y", "Width", "Height"].map { String(Int(bounds[$0] ?? 0)) }
        print(([String(id)] + values + [title]).joined(separator: "\t"))
    }
case "raise" where args.count == 3:
    guard let pid = pid_t(args[1]) else { fail("mxm-input: a pid is a number") }
    let app = AXUIElementCreateApplication(pid)
    var listed: CFTypeRef?
    AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &listed)
    var raised = false
    for window in (listed as? [AXUIElement]) ?? [] {
        var title: CFTypeRef?
        AXUIElementCopyAttributeValue(window, kAXTitleAttribute as CFString, &title)
        if (title as? String) == args[2] {
            AXUIElementPerformAction(window, kAXRaiseAction as CFString)
            raised = true
        }
    }
    AXUIElementSetAttributeValue(app, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
    if !raised { fail("mxm-input: no window titled \(args[2])") }
default:
    fail("usage: mxm-input check | click <x> <y> | move <x> <y> | drag <x> <y> <x2> <y2> | type <text> | key <name> | windows <pid> | raise <pid> <title>")
}
