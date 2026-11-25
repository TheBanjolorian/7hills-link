"""Where is the player? Read from the game's Game.log, turned into one place.

The game writes Game.log next to its exe (for example ...\\StarCitizen\\LIVE\\Game.log).
A few of its lines say where you are, roughly:

  <Join PU> ... shard[...]                      the shard you joined (a new session)
  <Planet CPU Maps Loaded> Planet '...'         a planet or moon being loaded; alone it
                                                means you are close to it, in a batch it
                                                is just streaming
  Added notification "Entered X Jurisdiction"   inside a planet company's space (UEE: none)
  Added notification "Entering/Leaving Armistice Zone"
  ATC '..._Port_Lawful-Orison'                  a port's air traffic control woke up
  <Update Inventory Location> ... Landing [a] -> [b]   arrived at / left a landing area

From these the tracker keeps one best guess, from most to least precise:
a port (city or station), a planet or moon, a planet's jurisdiction, the system.
Only the place id from places.json is sent to 7Net, with how sure it is, the
shard and the game's own location number. Never coordinates, never log lines.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .paths import resource

BURST_S = 3.0           # planets loaded this close together are streaming, not where you are
PORT_HINT_S = 600.0     # an ATC hint counts for this long when you then land or enter armistice

RE_TS = re.compile(r"^<(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z>")
RE_JOIN = re.compile(r"<Join PU>.*?shard\[([^\]]+)\]")
RE_PLANET = re.compile(r"<Planet CPU Maps Loaded> Planet '([^']+)'")
RE_NOTICE = re.compile(r'<SHUDEvent_OnNotification> Added notification "([^"]*)')
RE_ATC = re.compile(r"<ATC_Reset_VehiclesBeingStoredCleared> ATC '([^']+)'")
RE_INV = re.compile(r"<Update Inventory Location>.*?Landing \[(\d+)\] -> \[(\d+)\]\. Location \[(\d+)\] -> \[(\d+)\]")
RE_JURIS = re.compile(r"^Entered (.+?) Jurisdiction", re.I)
# v0.7: the landing area by name, quantum travel, and who you are (for "calibration started by you").
RE_LOCINV = re.compile(r"<RequestLocationInventory> Player\[[^\]]*\] requested inventory for Location\[([^\]]+)\]")
RE_HANDLE = re.compile(r"<Legacy login response>.*?Handle\[([^\]]+)\]")
RE_QT_SELECT = re.compile(r"<Player Selected Quantum Target - Local>.*?selected point (\S+) as their destination")
RE_QT_START = re.compile(r"<Calculate Route>.*?Projected Start Location is (.+?) for route to destination (\S+)")
RE_QT_ARRIVED = re.compile(r"<Quantum Drive Arrived - Arrived at Final Destination>")
RE_QT_CAL = re.compile(r"^Quantum Travel Calibration (Started|Complete) By (.*?):?\s*$", re.I)
# Gateway stations and jump-point quantum targets: RR_JP_PyroStanton, rs_ext_pyro-stan_jp1.
RE_RR_JP = re.compile(r"^RR_JP_([A-Z][a-z]+)([A-Z][a-z]+)")
RE_EXT_JP = re.compile(r"^rs_ext_([a-z]+)-([a-z]+)_jp", re.I)
SYSTEMS = ("stanton", "pyro", "nyx", "castra", "magnus", "terra")
QT_FORGET_S = 900.0     # a quantum trip with no arrival line is forgotten after this long

# Jurisdiction notice text -> planet name in places.json. "UEE" is Stanton space
# outside the planet companies (Lagrange points, the space between planets).
JURISDICTION = {
    "hurston dynamics": "Hurston",
    "crusader industries": "Crusader",
    "arccorp": "ArcCorp",
    "microtech": "microTech",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(name: str) -> str:
    """A game name for a landing area we have no place for: Outpost_OLP_Stanton2b_Lamina → Outpost OLP Stanton2b Lamina."""
    return re.sub(r"[_]+", " ", name).strip()[:60]


def _ts(line: str) -> float | None:
    m = RE_TS.match(line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1) + "+00:00").timestamp()
    except ValueError:
        return None


class Places:
    """The place list (data/places.json, the same file 7Net uses)."""

    def __init__(self, places: list[dict]) -> None:
        self.by_id = {p["id"]: p for p in places}
        # Planets and moons match the name the game uses for them exactly
        # (OOC_Stanton_2a_Cellin, pyro5a, Nyx1, ...).
        self.bodies: dict[str, str] = {}
        # Ports match as part of a longer name (ATC_DataManager_Port_Lawful-Orison):
        # cities, stations and rest stops, longest first, at least 5 letters.
        ports: list[tuple[str, str]] = []
        named_ports: list[tuple[str, str]] = []
        for p in places:
            keys = [_norm(k) for k in p.get("match", [])]
            if p["kind"] in ("planet", "moon"):
                for k in keys:
                    self.bodies.setdefault(k, p["id"])
            if p["kind"] in ("city", "station") or (p["kind"] == "lpoint" and p.get("station")):
                for k in keys:
                    if len(k) >= 5:
                        ports.append((k, p["id"]))
                    if len(k) >= 4:
                        named_ports.append((k, p["id"]))
        self.ports = sorted(ports, key=lambda kv: -len(kv[0]))
        # Landing-area names are short and exact (RR_P6_LEO): the 4-letter keys count there.
        self.named_ports = sorted(named_ports, key=lambda kv: -len(kv[0]))
        self.planets_by_name = {_norm(p["name"]): p["id"] for p in places if p["kind"] == "planet"}
        # Any place by its name or a match key ("Daymar", "Ruin Station", "Nyx System").
        self.by_name: dict[str, str] = {}
        for p in places:
            for k in [p["name"], *p.get("match", [])]:
                self.by_name.setdefault(_norm(k), p["id"])

    @classmethod
    def load(cls, path: Path | None = None) -> "Places":
        path = path or resource("data", "places.json")
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["places"])

    def body(self, game_name: str) -> str | None:
        return self.bodies.get(_norm(game_name))

    def port(self, text: str) -> str | None:
        t = _norm(text)
        return next((pid for k, pid in self.ports if k in t), None)

    def gateway(self, text: str) -> str | None:
        """RR_JP_PyroStanton (the station in Pyro towards Stanton) or rs_ext_pyro-stan_jp1 → pyro/jump-stanton."""
        m = RE_RR_JP.match(text) or RE_EXT_JP.match(text)
        if not m:
            return None
        a, b = (s.lower() for s in m.groups())
        here = next((s for s in SYSTEMS if s.startswith(a)), None)
        there = next((s for s in SYSTEMS if s.startswith(b)), None)
        pid = f"{here}/jump-{there}" if here and there else None
        return pid if pid in self.by_id else None

    def named(self, text: str) -> str | None:
        """A place from a name the game writes: a gateway, a port inside a longer name, a planet or moon, any place name."""
        text = text.strip()
        if not text:
            return None
        n = _norm(text)
        if n.endswith("system") and n[:-6] in self.by_id:
            return n[:-6]
        port = next((pid for k, pid in self.named_ports if k in n), None)
        return self.gateway(text) or port or self.bodies.get(n) or self.by_name.get(n)

    def name_of(self, pid: str | None) -> str | None:
        p = self.by_id.get(pid) if pid else None
        return p["name"] if p else None

    def system_of(self, pid: str | None) -> str | None:
        return pid.split("/", 1)[0] if pid else None

    def within(self, pid: str | None, area: str | None) -> bool:
        return bool(pid and area and (pid == area or pid.startswith(area + "/")))

    def path_names(self, pid: str | None) -> list[str]:
        out = []
        while pid:
            p = self.by_id.get(pid)
            if not p:
                break
            out.insert(0, p["name"])
            pid = p.get("parent")
        return out


class Tracker:
    """Keeps the best guess of where the player is, fed one Game.log line at a time."""

    def __init__(self, places: Places) -> None:
        self.places = places
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.shard: str | None = None
        self.system: str | None = None
        self.jur_area: str | None = None      # planet id from the last jurisdiction notice
        self.body: str | None = None          # planet or moon loaded on its own
        self.port: str | None = None          # city or station
        self.armistice = False
        self.landing: str | None = None       # the game's landing-area number while inside one
        self.raw_id: str | None = None
        self._port_hint: tuple[float, str] | None = None
        self._landing_ports: dict[str, str] = {}   # landing-area number -> port, learnt this session
        self._pending: tuple[float, str, float] | None = None   # (log time, body, wall time)
        self._burst_until = 0.0
        # v0.7
        self.handle: str | None = getattr(self, "handle", None)   # kept across sessions of one game run
        self.jurisdiction: str | None = None  # "UEE", "Ungoverned", "Crusader Industries" ...
        self.qt: dict | None = None           # {"from", "to", "target", "state", "since"}; state plotted | spool | travel
        self.event: tuple[float, str] | None = None   # (log time, short text): the newest thing that happened
        self.screen: dict | None = None       # set by screen.py: {"place_id", "at"} while the screen shows a known place
        self._last_ts = 0.0

    # ------------------------------------------------------------ feeding

    def feed(self, line: str) -> None:
        ts = _ts(line)
        if ts is None:
            return
        with self._lock:
            self._settle(ts)
            self._last_ts = ts
            if self.qt and ts - self.qt["since"] > QT_FORGET_S:
                self.qt = None
            m = RE_JOIN.search(line)
            if m:
                self.reset()
                self.shard = m.group(1)[:64]
                self._event(ts, "Joined a server")
                return
            m = RE_HANDLE.search(line)
            if m:
                self.handle = m.group(1)
                return
            m = RE_LOCINV.search(line)
            if m:
                self._landed_at(ts, m.group(1))
                return
            m = RE_QT_SELECT.search(line)
            if m:
                self._qt_target(ts, m.group(1))
                return
            m = RE_QT_START.search(line)
            if m:
                if self.qt and self.qt["target"] == m.group(2):
                    self.qt["from"] = self.places.named(m.group(1)) or self.qt["from"]
                return
            if RE_QT_ARRIVED.search(line):
                if self.qt:
                    to = self.qt["to"]
                    self._event(ts, "Arrived" + (" at " + self.places.name_of(to) if to else ""))
                    if to and self.places.by_id.get(to, {}).get("kind") in ("planet", "moon"):
                        self._set_body(to)
                self.qt = None
                return
            m = RE_PLANET.search(line)
            if m:
                pid = self.places.body(m.group(1))
                if pid:
                    self._planet(ts, pid)
                return
            m = RE_NOTICE.search(line)
            if m:
                self._notice(ts, m.group(1))
                return
            m = RE_ATC.search(line)
            if m:
                pid = self.places.port(m.group(1))
                if pid:
                    self._port_hint = (ts, pid)
                    if self.landing:
                        self._landing_ports.setdefault(self.landing, pid)
                    if self.armistice or self.landing:
                        self._set_port(pid)
                return
            m = RE_INV.search(line)
            if m:
                _, landing_to, _, loc_to = m.groups()
                self.raw_id = loc_to if loc_to != "0" else None
                if landing_to != "0":
                    # Arrived in a landing area (a city or station): the port whose ATC
                    # woke up shortly before, or the one this number belonged to earlier.
                    self.landing = landing_to
                    pid = self._landing_ports.get(landing_to) or self._fresh_hint(ts)
                    if pid:
                        self._landing_ports[landing_to] = pid
                        self._set_port(pid)
                else:
                    if self.landing and self.port:
                        self._event(ts, "Left " + (self.places.name_of(self.port) or "the landing area"))
                    self.landing = None
                    if not self.armistice:
                        self.port = None

    def tick(self) -> None:
        """Settle a lone planet load once nothing else came for a while (wall clock)."""
        with self._lock:
            if self._pending and time.time() - self._pending[2] >= BURST_S:
                self._set_body(self._pending[1])

    def _settle(self, ts: float) -> None:
        if self._pending and ts - self._pending[0] >= BURST_S:
            self._set_body(self._pending[1])

    def _set_body(self, pid: str) -> None:
        # Only a lone load says where you are; the batches at join load planets
        # of every system, so they set neither the body nor the system.
        self.body = pid
        self.system = self.places.system_of(pid)
        self._pending = None

    def _planet(self, ts: float, pid: str) -> None:
        if ts < self._burst_until:
            self._burst_until = ts + BURST_S
            return
        if self._pending and ts - self._pending[0] < BURST_S:
            self._pending = None
            self._burst_until = ts + BURST_S
            return
        self._pending = (ts, pid, time.time())

    def _notice(self, ts: float, text: str) -> None:
        m = RE_QT_CAL.match(text.strip())
        if m:
            # Shown to everybody aboard the ship whose pilot spools, so a passenger travels too
            # (real sessions: the target and arrival lines reach passengers as well).
            if not self.qt:
                self.qt = {"from": self.port or self.body or self.jur_area, "to": None, "to_label": None,
                           "target": None, "state": "plotted", "since": ts}
            self.qt["state"] = "spool" if m.group(1).lower() == "started" else "travel"
            self.qt["since"] = ts
            who = m.group(2).strip()
            by = "" if not who or (self.handle and who.lower() == self.handle.lower()) else " (pilot " + who[:32] + ")"
            to = self.places.name_of(self.qt["to"]) or self.qt["to_label"]
            self._event(ts, ("Quantum calibrating" if self.qt["state"] == "spool" else "Quantum travel")
                        + (" to " + to if to else "") + by)
            return
        m = RE_JURIS.match(text.strip())
        if m:
            who = m.group(1).strip()
            self.jurisdiction = who[:40]
            self._event(ts, "Entered " + self.jurisdiction + " jurisdiction")
            if who.upper() == "UEE":
                self.jur_area = None
                self.system = self.system or "stanton"
            else:
                pid = self.places.planets_by_name.get(_norm(JURISDICTION.get(who.lower(), who)))
                if pid:
                    self.jur_area = pid
                    self.system = self.places.system_of(pid)
                    if self.body and not self.places.within(self.body, pid):
                        self.body = None
            return
        low = text.lower()
        if low.startswith("entering armistice zone"):
            self.armistice = True
            self._event(ts, "Entered armistice zone")
            pid = (self._landing_ports.get(self.landing) if self.landing else None) or self._fresh_hint(ts)
            if pid:
                self._set_port(pid)
        elif low.startswith("leaving armistice zone"):
            self.armistice = False
            self._event(ts, "Left armistice zone")
            # Still inside the landing area (flying around the city): keep the port.
            if not self.landing:
                self.port = None

    def _event(self, ts: float, text: str) -> None:
        self.event = (ts, text[:80])

    def _landed_at(self, ts: float, name: str) -> None:
        """RequestLocationInventory: the landing area's own name, sent right after Update Inventory Location."""
        pid = self.places.named(name)
        if pid:
            if self.landing:
                self._landing_ports[self.landing] = pid
            self._set_port(pid)
        self.qt = None
        self._event(ts, "Landed at " + (self.places.name_of(pid) if pid else _plain(name)))

    def _qt_target(self, ts: float, target: str) -> None:
        if self.qt and self.qt["target"] == target and self.qt["state"] != "plotted":
            return            # the game repeats the selection while spooling
        to = self.places.named(target)
        label = None if to else ("a party member" if target.startswith("PartyMemberMarker") else
                                 "a mission marker" if target.startswith("MISSION_") else None)
        frm = self.port or self.body or self.jur_area
        self.qt = {"from": frm, "to": to, "to_label": label, "target": target, "state": "plotted", "since": ts}

    def _fresh_hint(self, ts: float) -> str | None:
        if self._port_hint and ts - self._port_hint[0] <= PORT_HINT_S:
            return self._port_hint[1]
        return None

    def _set_port(self, pid: str) -> None:
        self.port = pid
        self.system = self.places.system_of(pid)

    # ------------------------------------------------------------ reading

    def snapshot(self) -> dict | None:
        """What goes to 7Net: the best place and how sure it is, or None."""
        with self._lock:
            scr = self.screen
            if scr and scr.get("place_id"):
                pid, conf, src = scr["place_id"], "exact", "screen"
            elif self.port:
                pid, conf, src = self.port, "exact", "port"
            elif self.body:
                pid, conf, src = self.body, "near", "planet"
            elif self.jur_area:
                pid, conf, src = self.jur_area, "area", "jurisdiction"
            elif self.system:
                pid, conf, src = self.system, "system", "system"
            else:
                return None
            qt = self.qt
            transit = None
            if qt and qt["state"] in ("spool", "travel"):
                transit = {"from": qt["from"], "to": qt["to"], "to_label": qt["to_label"], "state": qt["state"],
                           "since": _iso(qt["since"])}
            return {"place_id": pid, "confidence": conf, "source": src, "armistice": self.armistice,
                    "shard": self.shard, "raw_id": self.raw_id,
                    "jurisdiction": self.jurisdiction, "transit": transit,
                    "event": {"text": self.event[1], "at": _iso(self.event[0])} if self.event else None}

    def describe(self) -> str | None:
        snap = self.snapshot()
        if not snap:
            return None
        return " › ".join(self.places.path_names(snap["place_id"]))


class GameLogFollower:
    """Reads Game.log from the start, then follows it; starts over when the game makes a new one."""

    def __init__(self, path: Path, tracker: Tracker, poll: float = 1.0) -> None:
        self.path = Path(path)
        self.tracker = tracker
        self.poll = poll
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="gamelog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        pos = 0
        ident = None
        buf = b""
        while not self._stop.is_set():
            try:
                st = self.path.stat()
            except OSError:
                self.error = "no Game.log yet"
                self._stop.wait(self.poll * 5)
                continue
            now_ident = getattr(st, "st_birthtime", None) or st.st_ctime
            if ident is None or now_ident != ident or st.st_size < pos:
                # A new game start writes a new Game.log.
                if ident is not None:
                    self.tracker.reset()
                ident, pos, buf = now_ident, 0, b""
            if st.st_size > pos:
                try:
                    with open(self.path, "rb") as f:
                        f.seek(pos)
                        data = f.read(8 * 1024 * 1024)
                    pos += len(data)
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        self.tracker.feed(raw.decode("utf-8", errors="replace"))
                    self.error = None
                except OSError as e:
                    self.error = str(e)[:200]
            self.tracker.tick()
            self._stop.wait(self.poll)
