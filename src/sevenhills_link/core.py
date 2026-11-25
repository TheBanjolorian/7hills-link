"""The client's brain: finds the game, links the PC, streams and uploads.

Independent of the window, so it can be tested and run headless.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections import deque
import webbrowser

from . import __version__, api, detect, gamecfg, location, protoset, screen, situation, updater
from .paths import data_dir
from .prefs import Prefs, can_autostart
from .stream import GameStream

MIN_GAP = 0.25          # at most 4 uploads a second; sent as soon as something changes
TICK = 0.05             # how often the loop looks for news
HEARTBEAT = 15.0        # upload at least this often while connected, even if nothing new
SETTINGS_EVERY = 30.0   # refresh sharing settings from 7Net
UPDATE_EVERY = 6 * 3600 # look for a new release
LOC_REFRESH = 60.0      # resend the place now and then even when it did not change

UNLINK_UNCONFIRMED = ("7Net did not confirm the unlink, so this PC is only unlinked here. "
                      "Unlink it on 7hills.space too: Profile \u2192 PCs.")


def refused_key(e: "api.ApiError") -> bool:
    """True when 7Net itself says the key is no longer valid. 7Net always sends a code
    with that; a bare 401 comes from something in between (a proxy, a sign-in page) and
    must not make the app forget a key that still works."""
    return e.status == 401 and bool(e.code)


def lost_key_message(e: "api.ApiError | None") -> str:
    """Why 7Net refused this PC's key, for the window."""
    code = getattr(e, "code", None)
    reason = getattr(e, "reason", None)
    if code == "expired":
        return "This PC was not used for 90 days, so its link expired. Link it again."
    if code == "unlinked" and reason == "admin":
        return "An admin unlinked this PC from 7Net. Link it again if you should have access."
    if code == "unlinked" and reason == "limit":
        return "This PC was unlinked because another PC was linked and you can have 5. Link it again."
    return "This PC was unlinked on 7Net. Link it again."


def _summary(frame: dict | None) -> dict:
    """What the window shows under "Right now"."""
    if not frame:
        return {}
    actor = frame.get("actor") or {}
    st = actor.get("state") or {}
    vs = (frame.get("vehicle") or {}).get("state") or {}
    loco = str(st.get("locomotion", "")).replace("ACTOR_LOCOMOTION_STATE_", "").lower()
    out = {"locomotion": loco, "seat": st.get("seat_name") or None}
    if vs.get("class_name"):
        fl = vs.get("flight") or {}
        out.update({
            "ship": str(vs.get("class_name")).replace("_", " "),
            "gear": str((fl.get("state") or {}).get("gear", "")).replace("VEHICLE_COMPONENT_DEPLOYMENT_STATE_", "").lower(),
            "mode": str((vs.get("master_mode") or {}).get("mode", "")).replace("VEHICLE_MASTER_MODE_", ""),
            "power_on": all((vs.get("power") or {}).get(k, True) for k in ("powerplants", "engines")),
        })
    return out


def without_uec(frame: dict | None) -> dict | None:
    """The frame as it is uploaded: the aUEC balance never leaves the PC."""
    st = ((frame or {}).get("actor") or {}).get("state")
    if not isinstance(st, dict) or "uec_balance" not in st:
        return frame
    actor = dict(frame["actor"])
    actor["state"] = {k: v for k, v in st.items() if k != "uec_balance"}
    return {**frame, "actor": actor}


def _smooth(prev: float | None, value: float, k: float = 0.2) -> float:
    return value if prev is None else prev + k * (value - prev)


def _r3(v: float | None) -> float | None:
    return None if v is None else round(v, 3)


class Updates:
    """Looks for new releases, downloads them, and installs when allowed."""

    def __init__(self, core: "Core") -> None:
        self.core = core
        self.path = data_dir() / "update.json"
        try:
            self.auto = bool(json.loads(self.path.read_text(encoding="utf-8")).get("auto_install", True))
        except (OSError, ValueError):
            self.auto = True
        self.state = "idle"        # idle | checking | up_to_date | downloading | ready | installing | error
        self.latest: str | None = None
        self.file = None
        self.error: str | None = None
        self.checked_at = 0.0
        self.install_hook = None   # set by the window: (Path) -> None, exits the app on success

    def set_auto(self, on: bool) -> None:
        self.auto = bool(on)
        try:
            self.path.write_text(json.dumps({"auto_install": self.auto}), encoding="utf-8")
        except OSError:
            pass

    def check_now(self) -> None:
        self.checked_at = time.time()
        self.state, self.error = "checking", None
        try:
            info = updater.check()
            if not info:
                self.state = "up_to_date"
                return
            self.latest = info["version"]
            self.state = "downloading"
            self.file = updater.download(info)
            self.state = "ready"
        except Exception as e:
            self.state, self.error = "error", str(e)[:200]

    def tick(self) -> None:
        if not updater.can_install():
            self.state = "source"   # running from source: nothing to update
            return
        if time.time() - self.checked_at >= UPDATE_EVERY or (self.state == "error" and time.time() - self.checked_at >= 3600):
            threading.Thread(target=self.check_now, name="update-check", daemon=True).start()
            self.checked_at = time.time()
        # Install by itself only between play sessions.
        playing = bool(self.core.stream and self.core.stream.connected)
        if self.state == "ready" and self.auto and not playing and self.core.link is None and updater.can_install():
            self.install()

    def install(self) -> None:
        if self.state != "ready" or not self.file or not self.install_hook:
            return
        self.state = "installing"
        try:
            self.install_hook(self.file)
        except Exception as e:
            self.state, self.error = "error", str(e)[:200]

    def status(self) -> dict:
        return {"state": self.state, "latest": self.latest, "error": self.error, "auto": self.auto,
                "can_install": updater.can_install()}


class Core:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.installs: list[detect.Install] = []
        self.channel: str | None = None
        self.cfg_state: dict[str, dict] = {}
        self.env_ok: bool | None = False
        self.needs_restart = False
        self.stream: GameStream | None = None
        self.stream_exe: str | None = None
        self.proto_error: str | None = None
        self.token = api.load_token()
        self.linked = bool(self.token)
        self.link: dict | None = None
        self.updates = Updates(self)
        self.prefs = Prefs()
        # StarCitizen.exe per channel, picked by the player with Browse; wins over what scan finds.
        self.game_path_file = data_dir() / "game.json"
        try:
            gp = json.loads(self.game_path_file.read_text(encoding="utf-8")).get("paths") or {}
        except (OSError, ValueError, AttributeError):
            gp = {}
        self.game_paths: dict[str, str] = {str(k): str(v) for k, v in gp.items()} if isinstance(gp, dict) else {}
        # Music: mute and volume, remembered across restarts. The window plays it.
        self.sound_path = data_dir() / "sound.json"
        try:
            snd = json.loads(self.sound_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            snd = {}
        self.sound_muted = bool(snd.get("muted", False))
        v = snd.get("volume", 0.1)
        self.sound_volume = min(1.0, max(0.0, float(v))) if isinstance(v, (int, float)) else 0.1
        self.sound_repeat = bool(snd.get("repeat", False))
        self.sound_stopped = bool(snd.get("stopped", False))   # Stop pressed: no music on start until Play
        self.link_error: str | None = None
        self.member: dict | None = None
        self.settings: dict | None = None
        self.last_upload: float = 0
        self.upload_error: str | None = None
        self.uploads = 0
        self._last_settings = 0.0
        self._stop = threading.Event()
        self._traffic: deque = deque(maxlen=120)   # (time, bytes out, bytes in), one per tick second
        self.delay_wait = None    # s from the game's frame to the start of its upload (smoothed)
        self.delay_upload = None  # s the upload to 7Net took (smoothed)
        # Where the player is, from Game.log next to the game's exe (see location.py).
        self.tracker = location.Tracker(location.Places.load())
        self.gamelog: location.GameLogFollower | None = None
        # The exact place from the r_displayinfo text on screen, while sharing Full (see screen.py).
        self.screen = screen.ScreenReader(self.tracker, self.tracker.places)
        self.screen.start()
        # What the player is doing there, from the telemetry (see situation.py).
        self.steady = situation.Steady()

    # ---------------------------------------------------------------- setup

    def scan(self) -> None:
        installs = detect.apply_choices(detect.find_installs(detect.user_roots()), self.game_paths)
        running = detect.running_channel()
        with self.lock:
            self.installs = installs
            names = [i.channel for i in installs]
            if running and running in names:
                self.channel = running
            elif self.channel not in names:
                self.channel = "LIVE" if "LIVE" in names else (names[0] if names else None)
            self.cfg_state = {i.channel: {"missing": gamecfg.missing(i.user_cfg), "path": str(i.user_cfg)} for i in installs}
            self.env_ok = gamecfg.env_enabled()

    def set_game_path(self, channel: str, exe: str | None) -> str | None:
        """Pick (or with None, forget) StarCitizen.exe for a channel. Returns an error text or None."""
        channel = str(channel).upper()
        if exe:
            inst = detect.install_from_exe(exe)
            if inst is None:
                return "Pick StarCitizen.exe inside a Bin64 folder"
            if inst.channel != channel:
                return f"That exe is in the {inst.channel} folder, not {channel}"
            self.game_paths[channel] = str(inst.exe)
        else:
            self.game_paths.pop(channel, None)
        try:
            self.game_path_file.write_text(json.dumps({"paths": self.game_paths}), encoding="utf-8")
        except OSError:
            pass
        self.scan()
        with self.lock:
            if exe:
                self.channel = channel
            self._restart_stream()
        return None

    def current(self) -> detect.Install | None:
        return next((i for i in self.installs if i.channel == self.channel), None)

    def set_channel(self, channel: str) -> None:
        with self.lock:
            if any(i.channel == channel for i in self.installs):
                self.channel = channel
                self._restart_stream()

    def enable_telemetry(self) -> dict:
        """Write user.cfg for every install found, and the user environment variable."""
        result = {"changed": [], "needs_admin": [], "errors": [], "env_howto": None}
        for inst in self.installs:
            try:
                if gamecfg.apply(inst.user_cfg):
                    result["changed"].append(inst.channel)
            except gamecfg.NeedsAdmin:
                if gamecfg.apply_elevated(inst.user_cfg):
                    result["needs_admin"].append(inst.channel)
                else:
                    result["errors"].append(inst.channel + ": no permission")
            except Exception as e:
                result["errors"].append(f"{inst.channel}: {e}")
        if gamecfg.env_manual():
            if gamecfg.env_enabled() is not True:
                result["env_howto"] = gamecfg.ENV_HOWTO
        else:
            try:
                if not gamecfg.env_enabled():
                    gamecfg.enable_env()
            except Exception as e:
                result["errors"].append(f"environment: {e}")
        if result["changed"] or result["needs_admin"]:
            self.needs_restart = True
        time.sleep(1.5 if result["needs_admin"] else 0)
        self.scan()
        return result

    # ---------------------------------------------------------------- stream

    def _restart_gamelog(self, inst: detect.Install | None) -> None:
        path = inst.folder / "Game.log" if inst else None
        if self.gamelog and path and self.gamelog.path == path:
            return
        if self.gamelog:
            self.gamelog.stop()
            self.gamelog = None
        self.tracker.reset()
        if path:
            self.gamelog = location.GameLogFollower(path, self.tracker)
            self.gamelog.start()

    def _restart_stream(self) -> None:
        inst = self.current()
        self._restart_gamelog(inst)
        if self.stream:
            self.stream.stop()
            self.stream = None
        self.stream_exe = None
        if not inst:
            return
        try:
            fds = protoset.load(inst.exe)
            self.proto_error = None
        except Exception as e:
            self.proto_error = str(e)[:200]
            return
        self.stream = GameStream(fds, gamecfg.ports_for(inst.user_cfg))
        self.stream.start()
        self.stream_exe = str(inst.exe)

    def ensure_stream(self) -> None:
        inst = self.current()
        if inst and (self.stream is None or self.stream_exe != str(inst.exe)):
            self._restart_stream()

    # ---------------------------------------------------------------- linking

    def start_link(self) -> dict:
        try:
            self.link = api.start_link()
            self.link_error = None
            webbrowser.open(self.link["url"])
            threading.Thread(target=self._poll_link, name="link-poll", daemon=True).start()
        except api.ApiError as e:
            self.link_error = e.message
        return self.status()

    def _poll_link(self) -> None:
        link = self.link
        deadline = time.time() + (link or {}).get("expires_in", 600)
        while link and time.time() < deadline and not self._stop.is_set():
            try:
                r = api.poll_link(link["code"], link["poll_secret"])
                if r.get("status") == "linked" and r.get("token"):
                    api.save_token(r["token"])
                    with self.lock:
                        self.token, self.linked, self.link = r["token"], True, None
                    self.refresh_settings(force=True)
                    return
            except api.ApiError as e:
                if e.status in (404, 410):
                    self.link_error, self.link = "The code expired. Start again.", None
                    return
            time.sleep(2)
        if self.link is link:
            self.link, self.link_error = None, "The code expired. Start again."

    def unlink(self) -> None:
        """The member pressed Unlink: 7Net stops accepting the key first, then it is forgotten here."""
        token = self.token
        error = None
        if token:
            try:
                api.unlink_device(token)
            except api.ApiError as e:
                # 401: 7Net already refuses this key, so there is nothing left to unlink there.
                if e.status != 401:
                    error = UNLINK_UNCONFIRMED
        self._forget_key()
        self.link_error = error

    def _forget_key(self) -> None:
        api.clear_token()
        with self.lock:
            self.token, self.linked, self.member, self.settings = None, False, None, None

    def _lost_key(self, e: api.ApiError | None = None) -> None:
        """7Net refused the key: forget it and say why."""
        self._forget_key()
        self.link_error = lost_key_message(e)

    # ---------------------------------------------------------------- sharing

    def refresh_settings(self, force: bool = False) -> None:
        if not self.token:
            self.screen.set_enabled(False)
            return
        if not force and time.time() - self._last_settings < SETTINGS_EVERY:
            return
        self._last_settings = time.time()
        try:
            r = api.get_settings(self.token)
            self.member, self.settings = r.get("member"), r.get("settings")
        except api.ApiError as e:
            if refused_key(e):
                self._lost_key(e)
        self._screen_by_share()

    def _screen_by_share(self) -> None:
        # The screen is read only while the member shares Full with Org Command.
        st = self.settings or {}
        mode = st.get("share_mode") or ("full" if st.get("share_org") else "online")
        self.screen.set_enabled(bool(self.token) and mode == "full")

    def set_share(self, patch: dict) -> dict:
        if self.token:
            try:
                body = {k: bool(v) for k, v in patch.items() if k == "share_org"}
                if patch.get("share_mode") in ("off", "online", "full"):
                    body["share_mode"] = patch["share_mode"]
                r = api.patch_settings(self.token, body)
                self.member, self.settings = r.get("member"), r.get("settings")
                self._screen_by_share()
            except api.ApiError as e:
                if refused_key(e):
                    self._lost_key(e)
        return self.status()

    # ---------------------------------------------------------------- upload loop

    def run(self) -> None:
        self.scan()
        self.ensure_stream()
        self.refresh_settings(force=True)
        last_sent_frame_at = 0.0
        last_sent_json = ""
        last_loc_json = ""
        last_loc_sent = 0.0
        last_try = 0.0
        backoff_until = 0.0
        last_scan = time.time()
        while not self._stop.is_set():
            self._stop.wait(TICK)
            now = time.time()
            if now - last_scan > 20:
                self.scan()
                self.ensure_stream()
                last_scan = time.time()
            self.refresh_settings()
            self.updates.tick()
            if not (self.token and self.stream) or now < backoff_until or now - last_try < MIN_GAP:
                continue
            new_frame, has_events = self.stream.pending(last_sent_frame_at)
            heartbeat = self.stream.connected and now - self.last_upload >= HEARTBEAT
            # The place from Game.log: sent when it changed (or cleared), and once a minute.
            loc = self.tracker.snapshot()
            state = self.steady.feed(situation.state_of(self._peek_frame()), now) if self.stream.connected else None
            if loc:
                loc["state"] = state
            loc_json = json.dumps(loc, sort_keys=True) if loc else ""
            loc_due = self.stream.connected and (loc_json != last_loc_json or (bool(loc) and now - last_loc_sent >= LOC_REFRESH))
            if not (new_frame or has_events or heartbeat or loc_due):
                continue
            frame, at, events = self.stream.take()
            frame = without_uec(frame)
            # The game sends ~17 frames a second; upload only when the content changed.
            frame_json = json.dumps(frame, sort_keys=True, default=str) if frame is not None else ""
            if frame_json == last_sent_json and not events and not heartbeat and not loc_due:
                last_sent_frame_at = at
                continue
            last_try = now
            t0 = time.time()
            try:
                if loc_due:
                    api.ingest(self.token, frame, events, location=loc)
                    last_loc_json, last_loc_sent = loc_json, time.time()
                else:
                    api.ingest(self.token, frame, events)
                t1 = time.time()
                self.delay_wait = _smooth(self.delay_wait, max(0.0, t0 - at)) if at else self.delay_wait
                self.delay_upload = _smooth(self.delay_upload, t1 - t0)
                self.last_upload, self.upload_error = time.time(), None
                self.uploads += 1
                last_sent_frame_at, last_sent_json = at, frame_json
            except api.ApiError as e:
                self.upload_error = e.message
                if refused_key(e):
                    self._lost_key(e)
                elif e.status in (429, 503):
                    backoff_until = time.time() + 2.0
                elif e.status in (401, 403):
                    # Not a member right now, or a 401 that did not come from 7Net: keep the key, try again in a minute.
                    backoff_until = time.time() + 60.0

    # ---------------------------------------------------------------- sound

    def set_sound(self, muted: bool | None = None, volume: float | None = None, repeat: bool | None = None,
                  stopped: bool | None = None) -> dict:
        if stopped is not None:
            self.sound_stopped = bool(stopped)
        if muted is not None:
            self.sound_muted = bool(muted)
        if repeat is not None:
            self.sound_repeat = bool(repeat)
        if isinstance(volume, (int, float)):
            self.sound_volume = min(1.0, max(0.0, float(volume)))
        try:
            self.sound_path.write_text(json.dumps({"muted": self.sound_muted, "volume": round(self.sound_volume, 2), "repeat": self.sound_repeat, "stopped": self.sound_stopped}), encoding="utf-8")
        except OSError:
            pass
        return self.status()

    def traffic_rate(self) -> dict:
        """KB/s to and from 7Net over the last ~10 s."""
        now = time.time()
        if not self._traffic or now - self._traffic[-1][0] >= 1:
            self._traffic.append((now, api.traffic["out"], api.traffic["in"]))
        old = next((t for t in self._traffic if now - t[0] <= 10), self._traffic[0])
        span = max(1.0, now - old[0])
        return {"up": round((api.traffic["out"] - old[1]) / span / 1024, 1),
                "down": round((api.traffic["in"] - old[2]) / span / 1024, 1)}

    def stop(self) -> None:
        self._stop.set()
        if self.stream:
            self.stream.stop()
        if self.gamelog:
            self.gamelog.stop()
        self.screen.stop()

    # ---------------------------------------------------------------- status for the window

    def _peek_frame(self) -> dict | None:
        """The latest telemetry frame, without draining the game events."""
        return self.stream.peek() if self.stream else None

    def _situation(self, frame: dict | None) -> str | None:
        """Place (Game.log) + state (telemetry) as one line for the window."""
        snap = self.tracker.snapshot()
        if not snap:
            return None
        place = self.tracker.places.by_id.get(snap["place_id"]) or {}
        name = place.get("name")
        if name and place.get("station"):
            name = f"{name} · {place['station']}"
        return situation.describe(self.steady.state, snap["confidence"], name, situation.altitude_of(frame))

    def status(self) -> dict:
        with self.lock:
            inst = self.current()
            cfg = self.cfg_state.get(self.channel or "", {})
            frame = self._peek_frame()
            return {
                "version": __version__,
                "update": self.updates.status(),
                "sound": {"muted": self.sound_muted, "volume": self.sound_volume, "repeat": self.sound_repeat, "stopped": self.sound_stopped},
                "channels_known": detect.CHANNELS,
                "prefs": self.prefs.as_dict(),
                "traffic": self.traffic_rate(),
                "delay": {"wait": _r3(self.delay_wait), "upload": _r3(self.delay_upload)},
                "can_autostart": can_autostart(),
                "platform": sys.platform,
                "update_checked_ago": round(time.time() - self.updates.checked_at) if self.updates.checked_at else None,
                "installs": [i.as_dict() for i in self.installs],
                "channel": self.channel,
                "game_found": inst is not None,
                "cfg_ok": inst is not None and not cfg.get("missing"),
                "cfg_missing": list((cfg.get("missing") or {}).keys()),
                "env_ok": self.env_ok,            # None: not Windows and the game is not running to check
                "env_manual": gamecfg.env_manual(),
                "env_howto": gamecfg.ENV_HOWTO if gamecfg.env_manual() else None,
                "platform": "windows" if detect.IS_WINDOWS else sys.platform,
                "needs_restart": self.needs_restart,
                "proto_error": self.proto_error,
                "game_connected": bool(self.stream and self.stream.connected),
                "fps": round(self.stream.fps, 1) if self.stream else 0,
                "port": self.stream.port if self.stream else gamecfg.DEFAULT_PORT,
                "stream_error": self.stream.error if self.stream else None,
                "linked": self.linked,
                "link": {"code": self.link["code"], "url": self.link["url"]} if self.link else None,
                "link_error": self.link_error,
                "member": self.member,
                "settings": self.settings,
                "last_upload_ago": round(time.time() - self.last_upload, 1) if self.last_upload else None,
                "upload_error": self.upload_error,
                "now": _summary(frame),
                "where": self.tracker.describe(),
                "screen": self.screen.status,
                "situation": self._situation(frame),
                "gamelog_error": self.gamelog.error if self.gamelog else None,
            }
