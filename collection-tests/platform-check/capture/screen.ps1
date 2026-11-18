# Sets the Windows VM's screen to a size (AGENTS.md): its clean install starts at 1280x800, where an
# editor taller than the screen opens shorter and lays itself out differently, so its picture can't
# be compared with the other platforms'. Run on the user's desktop (a scheduled task).
#
#   powershell -File screen.ps1 -Width 1920 -Height 1080 -Out <file>
param([int]$Width = 1920, [int]$Height = 1080, [string]$Out)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MxmScreen {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DevMode {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        public short SpecVersion, DriverVersion, Size, DriverExtra;
        public int Fields, PositionX, PositionY, DisplayOrientation, DisplayFixedOutput;
        public short Color, Duplex, YResolution, TTOption, Collate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string FormName;
        public short LogPixels;
        public int BitsPerPel, PelsWidth, PelsHeight, DisplayFlags, DisplayFrequency;
        public int IcmMethod, IcmIntent, MediaType, DitherType, Reserved1, Reserved2, PanningWidth, PanningHeight;
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern bool EnumDisplaySettings(string device, int mode, ref DevMode devMode);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int ChangeDisplaySettings(ref DevMode devMode, int flags);
}
"@
$mode = New-Object MxmScreen+DevMode
$mode.Size = [System.Runtime.InteropServices.Marshal]::SizeOf($mode)
[MxmScreen]::EnumDisplaySettings($null, -1, [ref]$mode) | Out-Null
$mode.PelsWidth = $Width
$mode.PelsHeight = $Height
# DM_PELSWIDTH | DM_PELSHEIGHT
$mode.Fields = 0x80000 -bor 0x100000
# CDS_UPDATEREGISTRY: 0 is DISP_CHANGE_SUCCESSFUL
$result = [MxmScreen]::ChangeDisplaySettings([ref]$mode, 1)
"$result $Width x $Height" | Out-File -Encoding ascii $Out
