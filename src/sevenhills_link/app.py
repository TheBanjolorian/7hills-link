"""The window (pywebview + a local HTML page in 7Net's look)."""

from __future__ import annotations

import os
import threading
import webbrowser

from . import install as installer
from . import instance, updater
from .core import Core
from .paths import resource
from .prefs import DEFAULTS, apply_startup

SITE = "https://www.7hills.space"

# The org's channels, as on the 7Net public site (lib/cms.ts). Only these open from the window.
LINKS = {
    "site": SITE,
    "discord": "https://discord.gg/7hills",
    "youtube": "https://www.youtube.com/@7hillsindustries",
    "spotify": "https://open.spotify.com/artist/2Y8asDjzVsVYEUFS1xnyk9",
    "apple": "https://music.apple.com/us/artist/7hills-industries/1843073599",
    "rsi": "https://robertsspaceindustries.com/en/orgs/7HILLS",
}


class JsApi:
    """Methods the page calls through window.pywebview.api."""

    def __init__(self, core: Core, autostart: bool):
        self._core = core
        self._autostart = autostart
        self._window = None   # set once the window exists; needed for the file dialog
        self._path_error: str | None = None
        self._install_error: str | None = None
        self._quit = None      # set by run_window

    def status(self):
        s = self._core.status()
        s["autostarted"] = self._autostart
        s["path_error"] = self._path_error
        s["install"] = {
            "offer": installer.needs_install(self._core.prefs.get("install_declined")),
            "installed": installer.is_installed_copy(),
            "packaged": installer.is_packaged(),
            "target": str(installer.install_dir()),
            "error": self._install_error,
        }
        return s

    def enable_telemetry(self):
        r = self._core.enable_telemetry()
        return {"result": r, "status": self.status()}

    def rescan(self):
        self._core.scan()
        self._core.ensure_stream()
        return self.status()

    def set_channel(self, channel):
        self._core.set_channel(str(channel))
        return self.status()

    def start_link(self):
        return self._core.start_link()

    def open_link_page(self):
        link = self._core.link
        webbrowser.open(link["url"] if link else SITE + "/link")

    def unlink(self):
        self._core.unlink()
        return self.status()

    def set_share(self, patch):
        return self._core.set_share(dict(patch or {}))

    def update_now(self):
        self._core.updates.install()
        return self.status()

    def check_updates(self):
        self._core.updates.check_now()
        return self.status()

    def set_auto_update(self, on):
        self._core.updates.set_auto(bool(on))
        return self.status()

    def set_sound(self, muted=None, volume=None, repeat=None, stopped=None):
        self._core.set_sound(None if muted is None else bool(muted), None if volume is None else float(volume),
                             None if repeat is None else bool(repeat), None if stopped is None else bool(stopped))
        return self.status()

    def browse_game(self, channel):
        """Windows file dialog for StarCitizen.exe; the pick is used for that channel."""
        import webview
        start = ""
        inst = next((i for i in self._core.installs if i.channel == str(channel).upper()), None)
        if inst:
            start = str(inst.exe.parent)
        picked = self._window.create_file_dialog(webview.OPEN_DIALOG, directory=start, allow_multiple=False,
                                                 file_types=("Programs (*.exe)",))
        if picked:
            path = picked[0] if isinstance(picked, (list, tuple)) else picked
            self._path_error = self._core.set_game_path(str(channel), str(path))
        return self.status()

    def reset_game_path(self, channel):
        self._path_error = self._core.set_game_path(str(channel), None)
        return self.status()

    def set_pref(self, key, value):
        if str(key) in DEFAULTS:
            self._core.prefs.set(str(key), bool(value))
            if str(key) == "exact_position":
                self._core.tracker.share_position = bool(value)
        return self.status()

    def open_link(self, key):
        url = LINKS.get(str(key))
        if url:
            webbrowser.open(url)

    def quit(self):
        if self._quit:
            threading.Thread(target=self._quit, daemon=True).start()

    def install_app(self, start_menu=True, desktop=True, remove_old=True):
        err = installer.install(bool(start_menu), bool(desktop), bool(remove_old), self._core.prefs.get("start_with_windows"))
        self._install_error = err
        if err is None:
            self.quit()   # the installed copy is starting; it waits for this one to close
        return self.status()

    def decline_install(self):
        self._core.prefs.set("install_declined", True)
        return self.status()

    def uninstall_app(self):
        installer.uninstall()
        self._core.prefs.set("start_with_windows", False)
        self.quit()

    def open_dashboard(self):
        webbrowser.open(SITE + "/live")


def run_window(updated_from: str | None = None, autostart: bool = False) -> int:
    import webview  # pywebview

    # The music plays without a click on the page; WebView2 needs this to allow it.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
    core = Core()
    # Keep the Windows Run entry in step with the setting and the exe's current path.
    apply_startup(core.prefs.get("start_with_windows"))

    # Served by pywebview's local http server, so the page can load music.mp3 next to it.
    page = str(resource("ui", "index.html"))
    js_api = JsApi(core, autostart)
    window = webview.create_window("7Hills Link", url=page, js_api=js_api, width=980, height=720,
                                   min_size=(760, 560), background_color="#0D0D0D", hidden=autostart)

    js_api._window = window

    from .tray import Tray

    quitting = threading.Event()

    def show_window():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def quit_app():
        quitting.set()
        tray.stop()
        core.stop()
        try:
            window.destroy()
        except Exception:
            os._exit(0)

    def toggle_mute():
        core.set_sound(muted=not core.sound_muted)

    tray = Tray(show_window, lambda: webbrowser.open(SITE + "/live"), quit_app, toggle_mute, lambda: core.sound_muted)
    js_api._quit = quit_app
    instance.listen(show_window)   # a second start shows this window instead of running twice

    def to_tray() -> bool:
        return tray.can_hide and core.prefs.get("tray") and not quitting.is_set()

    def on_minimized(*_):
        if to_tray():
            window.hide()

    def on_closing(*_):
        # With "Minimize to tray" on, the close button hides the window; Quit is in the tray menu.
        if to_tray():
            window.hide()
            return False
        return True

    window.events.minimized += on_minimized
    window.events.closing += on_closing

    def install(new_exe):
        # Hands the swap to a script and exits; the script starts the new version.
        if updater.install(new_exe):
            quitting.set()
            tray.stop()
            core.stop()
            try:
                window.destroy()
            finally:
                os._exit(0)
    core.updates.install_hook = install

    def tray_title_loop():
        while not quitting.is_set():
            try:
                st = core.status()
                state = "game connected" if st.get("game_connected") else "game not running"
                tray.set_title(f"7Hills Link {st.get('version')} · {state}")
            except Exception:
                pass
            quitting.wait(5)

    def started():
        threading.Thread(target=core.run, name="core", daemon=True).start()
        tray.start()
        if autostart and not tray.can_hide:
            show_window()   # no tray to come back from: show the window after all
        threading.Thread(target=tray_title_loop, name="tray-title", daemon=True).start()
        if updated_from:
            threading.Thread(target=updater.cleanup, name="update-cleanup", daemon=True).start()

    webview.start(started, http_server=True)
    tray.stop()
    core.stop()
    return 0
