# Every visible top-level window of one process, each as a PNG, and a JSON line about each
# (AGENTS.md): the platform check's Windows capture.
#
#   powershell -File windows.ps1 -ProcessId <pid> -Out <folder> -Prefix <name>
#
# Run it on the desktop of the logged-on user (a scheduled task), not over SSH: an SSH session has
# no desktop and sees no windows. PrintWindow with PW_RENDERFULLCONTENT reads a window's own content,
# OpenGL and Direct3D included, so a window over it doesn't spoil the picture; the process is made
# DPI-aware first, so sizes are the screen's pixels.
param([int]$ProcessId, [string]$Out, [string]$Prefix)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class MxmShot {
    public delegate bool EnumProc(IntPtr window, IntPtr data);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr window, out Rect rect);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr window, ref Rect point);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    public static List<IntPtr> Of(uint pid) {
        var found = new List<IntPtr>();
        EnumWindows((window, data) => {
            uint owner;
            GetWindowThreadProcessId(window, out owner);
            if (owner == pid && IsWindowVisible(window)) { found.Add(window); }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static string Text(IntPtr window, bool className) {
        var text = new StringBuilder(512);
        if (className) { GetClassName(window, text, text.Capacity); } else { GetWindowText(window, text, text.Capacity); }
        return text.ToString();
    }
}
"@
[MxmShot]::SetProcessDPIAware() | Out-Null
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$shot = 0
foreach ($window in [MxmShot]::Of([uint32]$ProcessId)) {
    $rect = New-Object MxmShot+Rect
    [MxmShot]::GetClientRect($window, [ref]$rect) | Out-Null
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -lt 8 -or $height -lt 8) { continue }
    $origin = New-Object MxmShot+Rect
    [MxmShot]::ClientToScreen($window, [ref]$origin) | Out-Null
    $bitmap = New-Object System.Drawing.Bitmap $width, $height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    $drawn = [MxmShot]::PrintWindow($window, $dc, 3)
    $graphics.ReleaseHdc($dc)
    $graphics.Dispose()
    if (-not $drawn) { $bitmap.Dispose(); continue }
    $shot += 1
    $name = "$Prefix-$shot.png"
    $bitmap.Save((Join-Path $Out $name), [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    [pscustomobject]@{
        file = $name; title = [MxmShot]::Text($window, $false); class = [MxmShot]::Text($window, $true)
        width = $width; height = $height; x = $origin.Left; y = $origin.Top
    } | ConvertTo-Json -Compress
}
