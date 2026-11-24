# Small helpers to drive Deadlock for offline screenshot tests (dot-source: . .\tools\game.ps1).
# Console commands are pasted into the in-game console, so the console must be enabled (launch option -console)
# and bound to $env:DAYLOCK_CONSOLE_KEY (default F7). Your clipboard and the window you were in are restored by
# Restore-Desktop. Only use this in a local game you started yourself, never in an online match.
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
if (-not ('DaylockInput' -as [type])) {
Add-Type -ReferencedAssemblies System.Drawing @"
using System; using System.Drawing; using System.Runtime.InteropServices; using System.Threading;
public class DaylockInput {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit, Size=40)] struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KEYBDINPUT ki; }
  [DllImport("user32.dll")] static extern uint SendInput(uint n, INPUT[] i, int size);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public static bool Focus(IntPtr h) {
    if (h == IntPtr.Zero) return false;
    if (GetForegroundWindow() == h && !IsIconic(h)) return true;
    if (IsIconic(h)) ShowWindow(h, 9);
    keybd_event(0x12, 0, 0, IntPtr.Zero); keybd_event(0x12, 0, 2, IntPtr.Zero);
    uint fg = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero), me = GetCurrentThreadId();
    AttachThreadInput(me, fg, true); BringWindowToTop(h); SetForegroundWindow(h); AttachThreadInput(me, fg, false);
    for (int i = 0; i < 30 && GetForegroundWindow() != h; i++) Thread.Sleep(50);
    return GetForegroundWindow() == h;
  }
  static void Send(ushort scan, uint flags) {
    var a = new INPUT[1]; a[0].type = 1; a[0].ki.wScan = scan; a[0].ki.dwFlags = flags;
    SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  }
  public static void Key(ushort sc) { Send(sc, 0x8); Thread.Sleep(25); Send(sc, 0xA); Thread.Sleep(25); }
  public static void Paste() { Send(0x1D, 0x8); Thread.Sleep(15); Send(0x2F, 0x8); Thread.Sleep(15); Send(0x2F, 0xA); Thread.Sleep(15); Send(0x1D, 0xA); Thread.Sleep(30); }
  public static Bitmap Grab(IntPtr h) {
    RECT r; GetWindowRect(h, out r); int w = r.R - r.L, hh = r.B - r.T;
    var bmp = new Bitmap(w, hh); using (var g = Graphics.FromImage(bmp)) g.CopyFromScreen(r.L, r.T, 0, 0, new Size(w, hh)); return bmp;
  }
}
"@
}
# keyboard scan codes
$script:ScanCodes = @{ F1 = 0x3B; F2 = 0x3C; F3 = 0x3D; F4 = 0x3E; F5 = 0x3F; F6 = 0x40; F7 = 0x41; F8 = 0x42; F9 = 0x43
  F10 = 0x44; F11 = 0x57; F12 = 0x58; GRAVE = 0x29; ENTER = 0x1C; ESC = 0x01; SPACE = 0x39 }
$script:ConsoleKey = if ($env:DAYLOCK_CONSOLE_KEY) { $env:DAYLOCK_CONSOLE_KEY.ToUpper() } else { 'F7' }
if (-not $script:ScanCodes.ContainsKey($script:ConsoleKey)) { throw "DAYLOCK_CONSOLE_KEY must be one of: $($script:ScanCodes.Keys -join ', ')" }

# what to give back at the end: the window you were in and your clipboard
$script:StartWindow = [DaylockInput]::GetForegroundWindow()
$script:ClipSaved = $null
function Save-Clipboard {
  try {
    $o = [System.Windows.Forms.Clipboard]::GetDataObject(); $copy = New-Object System.Windows.Forms.DataObject
    if ($o) { foreach ($f in $o.GetFormats($false)) { try { $copy.SetData($f, $o.GetData($f)) } catch {} } }
    $script:ClipSaved = $copy
  } catch { $script:ClipSaved = New-Object System.Windows.Forms.DataObject }
}
function Restore-Desktop {
  try {
    if ($script:ClipSaved -and $script:ClipSaved.GetFormats().Count) { [System.Windows.Forms.Clipboard]::SetDataObject($script:ClipSaved, $true) }
    elseif ($script:ClipSaved) { [System.Windows.Forms.Clipboard]::Clear() }
  } catch {}
  [void][DaylockInput]::Focus($script:StartWindow)
}

function Get-GameWindow { (Get-Process deadlock -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1).MainWindowHandle }
function Focus-Game {
  $h = Get-GameWindow; if (-not $h) { throw 'Deadlock is not running' }
  for ($i = 0; $i -lt 30; $i++) { if ([DaylockInput]::Focus($h)) { return $h }; Start-Sleep -Milliseconds 500 }
  throw 'could not bring the Deadlock window to the front'
}
function Send-GameKey([string]$name) { [void](Focus-Game); [DaylockInput]::Key($script:ScanCodes[$name]) }
# run one console line: open console, paste, Enter, close
function Send-GameCommand([string]$cmd, [int]$waitMs = 300) {
  if ($null -eq $script:ClipSaved) { Save-Clipboard }
  [System.Windows.Forms.Clipboard]::SetText($cmd)
  Send-GameKey $script:ConsoleKey; Start-Sleep -Milliseconds 300
  [void](Focus-Game); [DaylockInput]::Paste(); [DaylockInput]::Key($script:ScanCodes.ENTER); Start-Sleep -Milliseconds 60
  Send-GameKey $script:ConsoleKey; Start-Sleep -Milliseconds $waitMs
}
# screenshot of the game window only, scaled to $width
function Save-GameShot([string]$out, [int]$width = 1280) {
  $b = [DaylockInput]::Grab((Focus-Game))
  $hh = [int]($b.Height * $width / $b.Width); $s = New-Object System.Drawing.Bitmap $width, $hh
  $g = [System.Drawing.Graphics]::FromImage($s); $g.InterpolationMode = 'Bilinear'; $g.DrawImage($b, 0, 0, $width, $hh)
  New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
  $s.Save($out, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $s.Dispose(); $b.Dispose()
}
function Wait-Until([scriptblock]$test, [int]$timeoutSec = 120, [int]$pollMs = 500) {
  $t = [Diagnostics.Stopwatch]::StartNew()
  while ($t.Elapsed.TotalSeconds -lt $timeoutSec) { if (& $test) { return $true }; Start-Sleep -Milliseconds $pollMs }
  $false
}
