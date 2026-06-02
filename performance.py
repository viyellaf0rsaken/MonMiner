import os
import json
import shutil
import subprocess
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PERF_STATE_FILE = os.path.join(SCRIPT_DIR, "runtime", "perf_state.json")

PERF_SET_HIGH_PERFORMANCE_POWER_PLAN = True
PERF_DISABLE_SECOND_MONITOR = True
PERF_SET_BLACK_WALLPAPER = True


def _ensure_runtime():
    os.makedirs(os.path.dirname(PERF_STATE_FILE), exist_ok=True)


def _run_powershell(command, timeout=10):
    try:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None


def _windows_tools_available():
    return (
        shutil.which("powershell.exe") is not None
        or os.path.exists("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    )


def _load_state():
    try:
        with open(PERF_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    _ensure_runtime()
    try:
        with open(PERF_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _get_active_power_scheme_guid():
    result = _run_powershell("powercfg /getactivescheme")
    if not result or result.returncode != 0:
        return None

    text = (result.stdout or "") + "\n" + (result.stderr or "")
    match = re.search(
        r"([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})",
        text,
    )
    return match.group(1) if match else None


def _set_power_scheme(guid_or_alias):
    _run_powershell(f"powercfg /setactive {guid_or_alias}")


def _display_switch(mode):
    command = 'Start-Process "$env:WINDIR\\System32\\DisplaySwitch.exe" ' + f'-ArgumentList "{mode}" -Wait'
    _run_powershell(command, timeout=15)


def _get_wallpaper_state():
    command = r'''
$wallpaper = (Get-ItemProperty "HKCU:\Control Panel\Desktop").WallPaper
$style = (Get-ItemProperty "HKCU:\Control Panel\Desktop").WallpaperStyle
$tile = (Get-ItemProperty "HKCU:\Control Panel\Desktop").TileWallpaper
$bg = (Get-ItemProperty "HKCU:\Control Panel\Colors").Background
[PSCustomObject]@{
  Wallpaper = $wallpaper
  WallpaperStyle = $style
  TileWallpaper = $tile
  Background = $bg
} | ConvertTo-Json -Compress
'''
    result = _run_powershell(command, timeout=5)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        return json.loads(result.stdout.strip())
    except Exception:
        return None


def _set_black_wallpaper():
    command = r'''
Set-ItemProperty "HKCU:\Control Panel\Colors" -Name Background -Value "0 0 0"
Set-ItemProperty "HKCU:\Control Panel\Desktop" -Name WallPaper -Value ""
Set-ItemProperty "HKCU:\Control Panel\Desktop" -Name WallpaperStyle -Value "0"
Set-ItemProperty "HKCU:\Control Panel\Desktop" -Name TileWallpaper -Value "0"
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class NativeWallpaper { [DllImport("user32.dll", SetLastError=true)] public static extern bool SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni); }'
[NativeWallpaper]::SystemParametersInfo(20, 0, "", 3) | Out-Null
'''
    _run_powershell(command, timeout=8)


def _restore_wallpaper(state):
    if not state:
        return

    wallpaper = str(state.get("Wallpaper", "")).replace("'", "''")
    style = str(state.get("WallpaperStyle", "10")).replace("'", "''")
    tile = str(state.get("TileWallpaper", "0")).replace("'", "''")
    bg = str(state.get("Background", "0 0 0")).replace("'", "''")

    command = f'''
Set-ItemProperty "HKCU:\\Control Panel\\Colors" -Name Background -Value '{bg}'
Set-ItemProperty "HKCU:\\Control Panel\\Desktop" -Name WallPaper -Value '{wallpaper}'
Set-ItemProperty "HKCU:\\Control Panel\\Desktop" -Name WallpaperStyle -Value '{style}'
Set-ItemProperty "HKCU:\\Control Panel\\Desktop" -Name TileWallpaper -Value '{tile}'
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class NativeWallpaper {{ [DllImport("user32.dll", SetLastError=true)] public static extern bool SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni); }}'
[NativeWallpaper]::SystemParametersInfo(20, 0, '{wallpaper}', 3) | Out-Null
'''
    _run_powershell(command, timeout=8)


def apply_performance_mode_noninteractive():
    """Console-safe Performance Mode. Smart Cleanup is intentionally not included."""
    if not _windows_tools_available():
        return False, "Windows PowerShell not available; Performance Mode skipped."

    state = _load_state()

    if "active_power_scheme" not in state:
        state["active_power_scheme"] = _get_active_power_scheme_guid()

    if PERF_SET_HIGH_PERFORMANCE_POWER_PLAN:
        _set_power_scheme("SCHEME_MIN")
        state["power_plan_changed"] = True

    if PERF_DISABLE_SECOND_MONITOR:
        _display_switch("/internal")
        state["display_switched"] = True

    if PERF_SET_BLACK_WALLPAPER:
        if "wallpaper_state" not in state:
            state["wallpaper_state"] = _get_wallpaper_state()
        _set_black_wallpaper()
        state["wallpaper_changed"] = True

    _save_state(state)
    return True, "Performance Mode enabled."


def restore_performance_mode():
    state = _load_state()
    if not state:
        return False, "No active Performance Mode state found."

    if not _windows_tools_available():
        return False, "Windows PowerShell not available; cannot restore Performance Mode."

    if state.get("wallpaper_changed"):
        _restore_wallpaper(state.get("wallpaper_state"))

    if state.get("display_switched"):
        _display_switch("/extend")

    saved_scheme = state.get("active_power_scheme")
    if saved_scheme:
        _set_power_scheme(saved_scheme)

    try:
        os.remove(PERF_STATE_FILE)
    except Exception:
        pass

    return True, "Performance Mode restored/off."

