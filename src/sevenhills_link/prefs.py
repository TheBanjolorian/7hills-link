"""Window and startup preferences, kept in %LOCALAPPDATA%\\7HillsLink\\app.json."""

from __future__ import annotations

import json
import sys

from .paths import data_dir

DEFAULTS = {
    "start_with_windows": True,   # opens minimized in the tray, no music
    "tray": True,                 # minimize and close hide the window to the tray
    "play_on_start": True,        # play the music when the window opens (not on autostart)
    "install_declined": False,    # "Run without installing" was pressed: do not offer to install again
    "share_position": False,      # send the exact position on a planet or moon with the place (position.py)
}


class Prefs:
    def __init__(self) -> None:
        self.path = data_dir() / "app.json"
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        self.values = {k: bool(stored.get(k, v)) for k, v in DEFAULTS.items()}

    def get(self, key: str) -> bool:
        return self.values[key]

    def set(self, key: str, value: bool) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.values[key] = bool(value)
        try:
            self.path.write_text(json.dumps(self.values), encoding="utf-8")
        except OSError:
            pass
        if key == "start_with_windows":
            apply_startup(self.values[key])

    def as_dict(self) -> dict:
        return dict(self.values)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "7HillsLink"


def can_autostart() -> bool:
    """Windows: the packaged exe (a Run entry). Linux: always (an XDG autostart entry)."""
    return (sys.platform == "win32" and bool(getattr(sys, "frozen", False))) or sys.platform.startswith("linux")


def _linux_autostart(on: bool) -> bool:
    import os
    from pathlib import Path
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"
    entry = base / "7hills-link.desktop"
    if not on:
        try:
            entry.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" --autostart'
    else:
        src = Path(__file__).resolve().parent.parent   # .../src, so the module is found from anywhere
        cmd = f'env PYTHONPATH="{src}" "{sys.executable}" -m sevenhills_link --autostart'
    try:
        base.mkdir(parents=True, exist_ok=True)
        entry.write_text("[Desktop Entry]\nType=Application\nName=7Hills Link\n"
                         "Comment=Star Citizen telemetry for 7hills.space\n"
                         f"Exec={cmd}\nX-GNOME-Autostart-enabled=true\nTerminal=false\n", encoding="utf-8")
        return True
    except OSError:
        return False


def apply_startup(on: bool, exe=None) -> bool:
    """Add or remove start-on-login. Windows: the per-user Run entry for the
    packaged exe. Linux: ~/.config/autostart/7hills-link.desktop.

    The entry points at the current exe (or Python and the source folder), so
    it follows the client if it moves (it is rewritten on every start).
    """
    if sys.platform.startswith("linux"):
        return _linux_autostart(on)
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{exe or sys.executable}" --autostart')
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
