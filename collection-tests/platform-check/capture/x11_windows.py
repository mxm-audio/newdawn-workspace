"""Every viewable X11 client window on the display, each as a PNG, and a JSON line about it.

    python3 x11_windows.py <out folder> <prefix>

The platform check's Linux capture (AGENTS.md). A plugin's editor is an X11 window (baseview has
no Wayland), so on a Wayland desktop it is one of the few X11 windows XWayland holds; MXM Player
itself draws through Wayland and isn't one. A client window is one the window manager has given a
`WM_STATE`. Its pixels are read with `XGetImage` from the window itself, so a window over it
doesn't spoil the picture. Needs only libX11, which XWayland brings; run in the desktop's session,
where `DISPLAY` and `XAUTHORITY` are set.
"""

import ctypes
import ctypes.util
import json
import struct
import sys
import zlib
from pathlib import Path

x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")


class Attributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
                ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
                ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
                ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


class Image(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int),
                ("format", ctypes.c_int), ("data", ctypes.POINTER(ctypes.c_ubyte)), ("byte_order", ctypes.c_int),
                ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int), ("bitmap_pad", ctypes.c_int),
                ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int),
                ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong), ("blue_mask", ctypes.c_ulong)]


VIEWABLE = 2
ZPIXMAP = 2
ALL_PLANES = ctypes.c_ulong(~0 & 0xFFFFFFFFFFFFFFFF)

x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XInternAtom.restype = ctypes.c_ulong
x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x11.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                           ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                           ctypes.POINTER(ctypes.c_uint)]
x11.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Attributes)]
x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                   ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
x11.XGetImage.restype = ctypes.POINTER(Image)
x11.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                          ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
x11.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                      ctypes.POINTER(ctypes.c_ulong)]
x11.XFree.argtypes = [ctypes.c_void_p]

# A window that goes away between the walk and the read must cost its picture, not the run: Xlib's
# own handler would end the process on the error.
ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda display, event: 0)
x11.XSetErrorHandler(ERROR_HANDLER)


def prop(display, window, name, kind=0):
    """A property's bytes, or None."""
    atom = x11.XInternAtom(display, name, 1)
    if not atom:
        return None
    actual, fmt, count, after = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
    data = ctypes.c_void_p()
    if x11.XGetWindowProperty(display, window, atom, 0, 1 << 20, 0, kind, ctypes.byref(actual), ctypes.byref(fmt),
                              ctypes.byref(count), ctypes.byref(after), ctypes.byref(data)) != 0 or not data:
        return None
    try:
        if not actual.value:
            return None
        size = {8: 1, 16: ctypes.sizeof(ctypes.c_short), 32: ctypes.sizeof(ctypes.c_long)}[fmt.value]
        return ctypes.string_at(data, count.value * size)
    finally:
        x11.XFree(data)


def children(display, window):
    root, parent = ctypes.c_ulong(), ctypes.c_ulong()
    kids, count = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
    if not x11.XQueryTree(display, window, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(kids),
                          ctypes.byref(count)):
        return []
    found = [kids[i] for i in range(count.value)]
    if kids:
        x11.XFree(kids)
    return found


def png(width, height, rgb):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgb[row * width * 3:(row + 1) * width * 3] for row in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def capture(display, window, width, height):
    image = x11.XGetImage(display, window, 0, 0, width, height, ALL_PLANES, ZPIXMAP)
    if not image:
        return None
    image = image.contents
    if image.bits_per_pixel != 32:
        return None
    stride = image.bytes_per_line
    data = ctypes.string_at(image.data, stride * image.height)
    if stride != width * 4:
        data = b"".join(data[row * stride:row * stride + width * 4] for row in range(height))
    # Blue, green, red and a pad byte per pixel, as a little-endian 32-bit visual holds them.
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = data[2::4], data[1::4], data[0::4]
    return bytes(rgb)


def main():
    out, prefix = Path(sys.argv[1]), sys.argv[2]
    out.mkdir(parents=True, exist_ok=True)
    display = x11.XOpenDisplay(None)
    if not display:
        raise SystemExit("x11_windows: no X display (DISPLAY isn't set, or XWayland isn't running)")
    root = x11.XDefaultRootWindow(display)
    clients, queue = [], [root]
    while queue:
        window = queue.pop()
        if window != root and prop(display, window, b"WM_STATE") is not None:
            clients.append(window)
            continue
        queue.extend(children(display, window))
    shot = 0
    for window in clients:
        attributes = Attributes()
        if not x11.XGetWindowAttributes(display, window, ctypes.byref(attributes)):
            continue
        if attributes.map_state != VIEWABLE or attributes.width < 8 or attributes.height < 8:
            continue
        title = prop(display, window, b"_NET_WM_NAME") or prop(display, window, b"WM_NAME") or b""
        left, top, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        x11.XTranslateCoordinates(display, window, root, 0, 0, ctypes.byref(left), ctypes.byref(top),
                                  ctypes.byref(child))
        rgb = capture(display, window, attributes.width, attributes.height)
        if rgb is None:
            continue
        shot += 1
        path = out / f"{prefix}-{shot}.png"
        path.write_bytes(png(attributes.width, attributes.height, rgb))
        print(json.dumps({"file": path.name, "title": title.decode("utf-8", "replace").rstrip("\0"),
                          "width": attributes.width, "height": attributes.height,
                          "x": left.value, "y": top.value}), flush=True)


if __name__ == "__main__":
    main()
