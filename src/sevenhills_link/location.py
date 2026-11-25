"""Where is the player? Read from the game's Game.log, turned into one place.

The game writes Game.log next to its exe (for example ...\\StarCitizen\\LIVE\\Game.log).
These lines say where you are:

  <Join PU> ... shard[...]                      the shard you joined (a new session)
  <Update Inventory Location> ... Landing [a] -> [b]. Location [c] -> [d]
                                                the game's own number for the place you
                                                are in, written at login and every time
                                                you cross into another one; b is the
                                                landing area you stand in, or 0
  <RequestLocationInventory> ... Location[RR_P6_LEO]
                                                that landing area by its own name
  <Calculate Route> ... Projected Start Location is Daymar for route to ...
                                                where the ship you plot a route on is
  planet cells: 152 ... name: OOC_Stanton_2b_Daymar
                                                every ten minutes: the planet or moon
                                                whose ground is loaded around you
  Added notification "Entered X Jurisdiction"   a planet company's space, or none
  Added notification "Entering/Leaving Armistice Zone"
  <Planet CPU Maps Loaded> Planet '...'         a planet or moon being loaded (not in
  ATC '..._Port_Lawful-Orison'                  every build): alone it means you are
                                                close to it; a port's ATC waking up

The location number is the backbone. A number is the same place on every shard, so
data/location_ids.json lists the ones seen so far, and every pair the log itself
gives (a number with a landing area's name, or with a route's start location) is
remembered in locations.json in the client's data folder. A number nobody has named
yet keeps the planet or system you came from: you only reach another planet through
the system's open space, which has a number of its own.

From these the tracker keeps one place, from most to least precise: the landing
area you stand in (city, station, rest stop, gateway), the planet, moon or belt you
are at, a planet company's jurisdiction, the system.

Travel: Game.log says which target you plotted on a ship and when that ship
arrived, both with the ship's id. It has no line for the jump itself, so what is
sent is the route ("plotted a route to Crusader on the ship I fly"), never "in
quantum now": 7Net takes that from the ship's telemetry. The "Quantum Travel
Calibration ..." notices are not used: they go to the whole party wherever each
member is, and the arrival lines of other ships nearby are ignored.

Only the place id from places.json is sent to 7Net, with how sure it is, the shard,
the game's location number, the jurisdiction's name, the route's two ends as place
ids and one short line about the newest event. Never log lines, never another
player's name. The exact position on a planet or moon (position.py, read from the
screen) goes with it only when the member turned on "Share exact position".
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter as _count
from datetime import datetime, timezone
from pathlib import Path

from .log import log
from .paths import data_dir, resource

BURST_S = 3.0           # planets loaded this close together are streaming, not where you are
PORT_HINT_S = 600.0     # an ATC hint counts for this long when you then land or enter armistice
ROUTE_FORGET_S = 900.0  # a plotted route with no arrival is forgotten after this long
POS_STALE_S = 15.0      # an exact position read from the screen counts for this long

RE_TS = re.compile(r"^<(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z>")
RE_JOIN = re.compile(r"<Join PU>.*?shard\[([^\]]+)\]")
RE_PLANET = re.compile(r"<Planet CPU Maps Loaded> Planet '([^']+)'")
RE_NOTICE = re.compile(r'<SHUDEvent_OnNotification> Added notification "([^"]*)')
RE_ATC = re.compile(r"<ATC_Reset_VehiclesBeingStoredCleared> ATC '([^']+)'")
RE_INV = re.compile(r"<Update Inventory Location>.*?Landing \[(\d+)\] -> \[(\d+)\]\. Location \[(\d+)\] -> \[(\d+)\]")
RE_JURIS = re.compile(r"^Entered (.+?) Jurisdiction", re.I)
RE_LOCINV = re.compile(r"<RequestLocationInventory> Player\[[^\]]*\] requested inventory for Location\[([^\]]+)\]")
# A ship's navigation: "| NOT AUTH | AEGS_Idris_M_900000000001[900000000001]|CSCItemNavigation::CalculateRoute|text".
RE_NAV = re.compile(r"\|\s*([A-Za-z0-9_]+)\[\d+\]\|CSCItemNavigation::(\w+)\|(.*)$")
RE_NAV_SELECT = re.compile(r"selected point (\S+) as their destination")
RE_NAV_START = re.compile(r"Projected Start Location is (.+?) for route to destination (\S+)")
RE_CELLS = re.compile(r"planet cells:\s*(\d+)\s.*?name:\s*(\S+)")
# Gateway stations and jump-point quantum targets: RR_JP_PyroStanton, rs_ext_pyro-stan_jp1.
RE_RR_JP = re.compile(r"^RR_JP_([A-Z][a-z]+)([A-Z][a-z]+)")
RE_EXT_JP = re.compile(r"^rs_ext_([a-z]+)-([a-z]+)_jp", re.I)
SYSTEMS = ("stanton", "pyro", "nyx", "castra", "magnus", "terra")

# Jurisdiction notice → the planet whose company it is.
JURISDICTION = {
    "hurston dynamics": "Hurston",
    "crusader industries": "Crusader",
    "arccorp": "ArcCorp",
    "microtech": "microTech",
}
# Jurisdictions that only exist in one system (seen in real sessions). "UEE" and
# "Ungoverned" exist in several, so they say nothing about the system.
JURISDICTION_SYSTEM = {
    "rough & ready": "pyro",
    "people's alliance": "nyx",
}

# One spot you stand in or at, as opposed to a planet, a moon, a belt or a whole system.
SPOT_KINDS = frozenset({"city", "station", "jump", "landingzone", "outpost", "settlement", "facility", "shelter",
                        "landmark", "bunker", "cave", "wreck", "derelict"})
AREA_KINDS = frozenset({"system", "planet", "moon", "belt", "cloud", "cluster"})


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
        # The list also holds spots the game files place but do not name (hundreds of "Cave",
        # `unnamed` on the place). They are for 7Net's map only: nothing here can tell one
        # from another, so they are never reported.
        places = [p for p in places if not p.get("unnamed")]
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
        # A name several places share ("Derelict Outpost") names none of them. (Places with
        # match keys of their own, such as the two Pyro Gateways, are told apart by those.)
        shared = {n for n, c in _count(_norm(p["name"]) for p in places if not p.get("match")).items() if c > 1}
        self.by_name: dict[str, str] = {}
        for p in places:
            for k in [p["name"], *p.get("match", [])]:
                if _norm(k) in shared and k == p["name"]:
                    continue
                self.by_name.setdefault(_norm(k), p["id"])
        # A belt by the first word of its name ("Keeger" in AsteroidClusterBase_Nyx_Social_Keeger_004).
        words: dict[str, list[str]] = {}
        for p in places:
            if p["kind"] in ("belt", "cloud", "cluster"):
                w = _norm(p["name"].split()[0]) if p["name"].split() else ""
                if len(w) >= 5:
                    words.setdefault(w, []).append(p["id"])
        self.words = {w: ids[0] for w, ids in words.items() if len(ids) == 1}
        self.systems = {_norm(p["name"]): p["id"] for p in places if p["kind"] == "system"}

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

    def hint(self, name: str) -> str | None:
        """The moon, planet, belt or system a longer game name sits in.

        Outpost_OLP_Stanton2b_Lamina → Daymar, AsteroidClusterBase_Nyx_Social_Keeger_004 →
        Keeger Belt, Nyx_TSG_QVExtractionStation_038 → Nyx, "OOC Stanton 2c Yela" (the
        screen, underscores lost) → Yela. The deepest place wins.
        """
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", name or "") if t]
        best: str | None = None
        for t in tokens + [a + b for a, b in zip(tokens, tokens[1:])]:
            n = _norm(t)
            pid = self.bodies.get(n) or self.words.get(n) or self.systems.get(n)
            if not pid and len(n) >= 4:
                q = self.by_name.get(n)
                if q and self.by_id[q]["kind"] in AREA_KINDS:
                    pid = q
            if pid and (best is None or pid.count("/") > best.count("/")):
                best = pid
        return best

    def outpost(self, name: str) -> str | None:
        """An outpost from its landing-area name: Stanton2b_ShubinMining_SCD1 → Shubin Mining
        Facility SCD-1 on Daymar. The moon or planet comes from the name (hint); the outpost
        is the one place on it whose name holds every other word of the landing name. None
        unless exactly one fits and the words are telling enough (8 letters together)."""
        body = self.hint(name)
        if not body or self.kind(body) not in ("planet", "moon"):
            return None
        tokens = []
        for t in re.split(r"[^A-Za-z0-9]+", name or ""):
            n = _norm(t)
            if not n or n in ("outpost", "olp", "paf") or self.bodies.get(n) or self.systems.get(n):
                continue
            # "ShubinMining" is two words run together.
            tokens += [_norm(w) for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", t)] if re.search(r"[a-z][A-Z]", t) else [n]
        tokens = [t for t in tokens if t]
        if sum(len(t) for t in tokens) < 8 or not any(len(t) >= 4 for t in tokens):
            return None
        fits = [p["id"] for p in self.by_id.values()
                if p.get("parent") == body and self.is_spot(p["id"]) and all(t in _norm(p["name"]) for t in tokens)]
        return fits[0] if len(fits) == 1 else None

    def kind(self, pid: str | None) -> str | None:
        p = self.by_id.get(pid) if pid else None
        return p["kind"] if p else None

    def is_spot(self, pid: str | None) -> bool:
        """A landing area (city, station, rest stop, gateway, outpost ...), not a planet, moon, belt or system."""
        p = self.by_id.get(pid) if pid else None
        return bool(p and (p["kind"] in SPOT_KINDS or (p["kind"] == "lpoint" and p.get("station"))))

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


class LocationTable:
    """The game's location numbers and the place each one is.

    `seed` ships with the client (data/location_ids.json). `learnt` is what this PC's
    own Game.log has shown, kept in locations.json in the data folder: a landing
    area's number with its name (certain, and it wins over the seed), or the number
    you were in when a route's start location named a planet, moon or a system's
    open space (used only for numbers nothing else names).

    An entry is {"place": id} plus "near": true for the space around a station and
    "name" for a landing area that is not on the place list (its place is then the
    moon, belt or system it sits in).
    """

    MAX_LEARNT = 3000

    def __init__(self, seed: dict | None = None, learnt: dict | None = None, path: Path | None = None) -> None:
        self.seed: dict[str, dict] = dict(seed or {})
        self.learnt: dict[str, dict] = dict(learnt or {})
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> "LocationTable":
        """The shipped numbers plus what this PC has learnt (path: locations.json in the data folder)."""
        try:
            seed = json.loads(resource("data", "location_ids.json").read_text(encoding="utf-8")).get("ids") or {}
        except (OSError, ValueError, AttributeError):
            seed = {}
        path = path or (data_dir() / "locations.json")
        try:
            learnt = json.loads(Path(path).read_text(encoding="utf-8")).get("ids") or {}
        except (OSError, ValueError, AttributeError):
            learnt = {}
        ok = {str(k): v for k, v in learnt.items() if isinstance(v, dict) and isinstance(v.get("place"), str)}
        return cls({str(k): v for k, v in seed.items() if isinstance(v, dict)}, ok, Path(path))

    def keep_known(self, places: Places) -> None:
        """Drop entries whose place is not on the place list (an older or newer list)."""
        self.seed = {k: v for k, v in self.seed.items() if v.get("place") in places.by_id}
        self.learnt = {k: v for k, v in self.learnt.items() if v.get("place") in places.by_id}

    def get(self, number: str | None) -> dict | None:
        if not number:
            return None
        mine = self.learnt.get(number)
        if mine and (mine.get("by") == "landing" or mine.get("over")):
            return mine
        return self.seed.get(number) or mine

    def learn(self, number: str | None, place: str, *, name: str | None = None, by: str = "landing", force: bool = False) -> bool:
        """Remember number → place. Returns True when it was new.

        `force`: the log named a place for this number that cannot be the one listed (a
        different planet, another system), so the game has changed the number: what the log
        says now replaces the shipped entry on this PC.
        """
        if not number or number == "0" or not place:
            return False
        old = self.learnt.get(number)
        if by != "landing" and not force and (number in self.seed or (old and old.get("by") == "landing")):
            return False        # a route's start location never replaces something better
        entry: dict = {"place": place, "by": by}
        if name:
            entry["name"] = name[:60]
        if force and by != "landing":
            entry["over"] = True
        if old == entry:
            return False
        self.learnt.pop(number, None)
        self.learnt[number] = entry
        while len(self.learnt) > self.MAX_LEARNT:
            self.learnt.pop(next(iter(self.learnt)))
        self._save()
        return True

    def _save(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "ids": self.learnt}, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


class Tracker:
    """Keeps the best guess of where the player is, fed one Game.log line at a time."""

    def __init__(self, places: Places, table: LocationTable | None = None) -> None:
        self.places = places
        self.table = table if table is not None else LocationTable()
        self.table.keep_known(places)
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.shard: str | None = None
        self.system: str | None = None
        self.jur_area: str | None = None      # planet id from the last planet company's jurisdiction notice
        self.body: str | None = None          # the place you are at or next to without standing in its landing area
        self.port: str | None = None          # the landing area you stand in: city, station, rest stop, gateway
        self.armistice = False
        self.landing: str | None = None       # the game's landing-area number while inside one
        self.landing_name: str | None = None  # ... and its own name, once the log gave it
        self.raw_id: str | None = None        # the game's location number
        # What the last location number was: 'system' (open space), 'body', 'spot' (a station
        # or the space around it), 'site' (a number nobody has named, reached from open space).
        self._level: str | None = None
        self._hops = 0                        # location numbers in a row that nobody has named
        self._body_by: str | None = None      # which signal set `body`: number, learnt, name, route, cells, load, arrival, left
        self._port_hint: tuple[float, str] | None = None
        self._landing_ports: dict[str, str] = {}   # landing-area number -> port, from an ATC hint this session
        self._pending: tuple[float, str, float] | None = None   # (log time, body, wall time)
        self._burst_until = 0.0
        self._cells: tuple[int, str] | None = None   # most cells in the physics block being read: (cells, body id)
        self.jurisdiction: str | None = None  # "UEE", "Ungoverned", "Crusader Industries" ...
        # The route plotted on the ship the player flies: {"ship", "target", "from", "to", "to_label", "since", "wall"}.
        self.route: dict | None = None
        self.event: tuple[float, str] | None = None   # (log time, short text): the newest thing that happened
        self.screen: dict | None = None       # set by screen.py: {"place_id", "at"} while the screen shows a known place
        # The exact position on a planet or moon, read from the screen (position.py):
        # {"body", "lat", "lon", "alt", "at"}. Sent only while share_position is on, which
        # core.py sets from the member's own "Share exact position" setting (off by default).
        self.screen_pos: dict | None = None
        self.share_position = False
        self._last_ts = 0.0

    # ------------------------------------------------------------ feeding

    def feed(self, line: str) -> None:
        ts = _ts(line)
        if ts is None:
            return
        line = line.rstrip("\r\n")
        with self._lock:
            self._settle(ts)
            self._last_ts = ts
            if self.route and ts - self.route["since"] > ROUTE_FORGET_S:
                self.route = None
            if "<Join PU>" in line:
                m = RE_JOIN.search(line)
                if m:
                    self.reset()
                    self.shard = m.group(1)[:64]
                    self._event(ts, "Joined a server")
                return
            if "<Update Inventory Location>" in line:
                m = RE_INV.search(line)
                if m:
                    self._moved(ts, m.group(2), m.group(4))
                return
            if "<RequestLocationInventory>" in line:
                m = RE_LOCINV.search(line)
                if m:
                    self._landed_at(ts, m.group(1))
                return
            if "CSCItemNavigation::" in line:
                m = RE_NAV.search(line)
                if m:
                    self._nav(ts, *m.groups())
                return
            if "<SHUDEvent_OnNotification>" in line:
                m = RE_NOTICE.search(line)
                if m:
                    self._notice(ts, m.group(1))
                return
            if "planet cells:" in line:
                m = RE_CELLS.search(line)
                if m and int(m.group(1)) > 0:
                    pid = self.places.body(m.group(2))
                    if pid and (not self._cells or int(m.group(1)) > self._cells[0]):
                        self._cells = (int(m.group(1)), pid)
                return
            if "PHYSICS INSTANCE STATS" in line:
                if "BEGIN" in line:
                    self._cells = None
                elif "END" in line:
                    self._ground(self._cells[1] if self._cells else None)
                    self._cells = None
                return
            if "<Planet CPU Maps Loaded>" in line:
                m = RE_PLANET.search(line)
                pid = self.places.body(m.group(1)) if m else None
                if pid:
                    self._planet(ts, pid)
                return
            if "<ATC_Reset_VehiclesBeingStoredCleared>" in line:
                m = RE_ATC.search(line)
                pid = self.places.port(m.group(1)) if m else None
                if pid:
                    self._port_hint = (ts, pid)
                    if self.landing:
                        self._landing_ports.setdefault(self.landing, pid)
                    # A hint only: it never replaces a port the number or the landing area's name gave.
                    if (self.armistice or self.landing) and not self.port:
                        self._set_port(pid)

    def tick(self) -> None:
        """Settle a lone planet load, and forget an old route, once nothing came for a while (wall clock)."""
        with self._lock:
            if self._pending and time.time() - self._pending[2] >= BURST_S:
                self._set_body(self._pending[1], "load")
            if self.route and time.time() - self.route["wall"] > ROUTE_FORGET_S:
                self.route = None

    # ------------------------------------------------------------ the location number

    def _moved(self, ts: float, landing_to: str, loc_to: str) -> None:
        """<Update Inventory Location>: a new location number, inside a landing area or not."""
        number = loc_to if loc_to != "0" else None
        self.raw_id = number
        was_port, was_level = self.port, self._level
        landed = landing_to != "0"
        if landed:
            self.landing = landing_to
        else:
            if self.landing:
                left = self.places.name_of(self.port) if self.port else (_plain(self.landing_name) if self.landing_name else None)
                if left:
                    self._event(ts, "Left " + left)
            self.landing, self.landing_name = None, None
        entry = self.table.get(number)
        if entry:
            self._hops = 0
            pid = entry["place"]
            if landed and not entry.get("near") and self.places.is_spot(pid):
                self._set_port(pid)          # the landing area by its number; its name line follows
                self._level = "spot"
            else:
                # A pair learnt from a route's start location is a good guess, not a certainty.
                self._at(pid, sure=entry.get("by") != "route")
                if landed and self._level == "system":
                    self._level = "spot"     # a landing area that is not on the list, in open space
        elif landed:
            # A landing area whose number nobody has named: the port whose ATC woke up shortly
            # before, or the one this number belonged to earlier. Its own name follows.
            self._hops = 0
            pid = self._landing_ports.get(landing_to) or self._fresh_hint(ts)
            if pid:
                self._landing_ports[landing_to] = pid
                self._set_port(pid)
                self._level = "spot"
        else:
            # A number nobody has named, outside any landing area. One step from a known place
            # keeps it: the space just outside the station you left, or a spot on the moon you
            # are on. A second unnamed number in a row means you have moved on (you leave a
            # moon through open space, and that may be a number nobody has named yet).
            self._hops += 1
            if not self.armistice:
                self.port = None
            if was_level == "system" or self._hops >= 2:
                if self._body_by != "cells":
                    self.body, self._body_by = None, None
                self._level = "site"
            elif was_port and not self.armistice and not self.places.within(was_port, self.body):
                # Just outside the station you left (a city keeps its planet instead).
                self.body, self._body_by = was_port, "left"
        # Some trips end without an arrival line (a jump to a party member does). With a known
        # target the route ends when its number is reached; without one it ends when open space
        # gives way to any place, which can be half a minute early when the jump crosses a
        # planet's space on its way.
        r = self.route
        if r and ts - r["since"] >= 20:
            if r["to"]:
                if self.places.within(self.port or self.body, r["to"]):
                    self._event(ts, "Arrived at " + (self.places.name_of(r["to"]) or "the target"))
                    self.route = None
            elif was_level == "system" and self._level != "system":
                self.route = None

    def _at(self, pid: str, sure: bool = True) -> None:
        """The location number names this place, and you are not inside a landing area the list knows."""
        self.port = None
        if self.places.kind(pid) == "system":
            self.system = pid
            self.body, self._body_by = None, None
            self._level = "system"
        else:
            self.system = self.places.system_of(pid)
            self.body, self._body_by = pid, "number" if sure else "learnt"
            self._level = "spot" if self.places.is_spot(pid) else "body"

    def _landed_at(self, ts: float, name: str) -> None:
        """<RequestLocationInventory>: the landing area's own name. It follows the number when you
        arrive, and comes again each time you open the inventory there."""
        again = self.landing_name == name
        self.landing_name = name
        self._hops = 0
        pid = self.places.named(name)
        if not (pid and self.places.is_spot(pid)):
            pid = self.places.outpost(name) or pid
        if pid and self.places.is_spot(pid):
            self._set_port(pid)
            self._level = "spot"
            if self.landing:
                self._landing_ports[self.landing] = pid
                self.table.learn(self.landing, pid, by="landing")
            label = self.places.name_of(pid) or _plain(name)
        else:
            # A landing area that is not on the place list: the moon, belt or system in its name.
            area = pid or self.places.hint(name)
            label = _plain(name)
            if area:
                self.port = None
                if self.places.kind(area) == "system":
                    if self.system != area:
                        self.system = area
                        self.body, self._body_by = None, None
                    self._level = "spot"
                else:
                    self.system = self.places.system_of(area)
                    self.body, self._body_by = area, "name"
                    self._level = "body"
                if self.landing:
                    self.table.learn(self.landing, area, name=label, by="landing")
        self.route = None
        if not again:
            # "Arrived", not "landed": the game writes this line on entering the landing area's
            # zone, also from a ship still in the air.
            self._event(ts, "Arrived at " + label)

    # ------------------------------------------------------------ the ship's navigation

    def _nav(self, ts: float, ship: str, what: str, text: str) -> None:
        if what == "OnPlayerSelectedQuantumTarget":
            m = RE_NAV_SELECT.search(text)
            if m:
                self._plotted(ts, ship, m.group(1))
        elif what == "CalculateRoute":
            m = RE_NAV_START.search(text)
            if m:
                self._route_start(ship, m.group(1).strip(), m.group(2))
        elif what == "OnQuantumDriveArrived":
            r = self.route
            if r and r["ship"] == ship:      # other ships arriving nearby write the same line
                to = r["to"]
                self._event(ts, "Arrived" + (" at " + (self.places.name_of(to) or "the target") if to else ""))
                # Next to the planet, moon or belt it flew to, unless the location number says where.
                if to and self.places.kind(to) in AREA_KINDS - {"system"} and (self._level == "system" or not self._named_number()):
                    self._set_body(to, "arrival")
                self.route = None

    def _plotted(self, ts: float, ship: str, target: str) -> None:
        """The player picked a quantum target on this ship's starmap."""
        r = self.route
        if r and r["ship"] == ship and r["target"] == target:
            return            # the game repeats the selection
        to = self.places.named(target) or self.places.hint(target)
        label = None if to else ("a party member" if target.startswith("PartyMemberMarker") else
                                 "a mission marker" if target.startswith("MISSION_") else None)
        self.route = {"ship": ship, "target": target, "from": self.port or self.body or self.system, "to": to,
                      "to_label": label, "since": ts, "wall": time.time()}
        self._event(ts, "Plotted a route to " + (self.places.name_of(to) or label or "a point in space"))

    def _route_start(self, ship: str, start: str, target: str) -> None:
        """"Projected Start Location is Daymar": where the ship the player plots on is right now."""
        pid = self.places.named(start)
        if not pid:
            return
        kind = self.places.kind(pid)
        # What the location number already says about where this is (not while standing in a
        # landing area: its number belongs to the landing area, not to the body around it).
        entry = None if self.landing else self.table.get(self.raw_id)
        known = entry["place"] if entry else None
        clash = bool(known) and not (self.places.within(known, pid) or self.places.within(pid, known))
        if kind == "system":
            if _norm(start).endswith("system"):
                # "Stanton System": the system's open space, which has a location number of its own.
                if not self.landing and (not known or clash):
                    self._at(pid)
                    self._hops = 0
                    self.table.learn(self.raw_id, pid, by="route", force=clash)
            elif self.system != pid:
                # "Nyx": somewhere in that system the starmap has no name for.
                self.port = None
                self.system = pid
                self.body, self._body_by = None, None
        elif self.places.is_spot(pid):
            if self.landing:
                self._set_port(pid)
            elif not self.port:
                self.system = self.places.system_of(pid)
                self.body, self._body_by = pid, "route"
        elif not (known and not clash and self.places.within(known, pid)):
            # A planet, a moon or a belt, and the number does not already say that or more.
            self.system = self.places.system_of(pid)
            if not self.places.within(self.port, pid):
                self.port = None
            if not (self.body and self.body != pid and self.places.within(self.body, pid)):
                self.body, self._body_by = pid, "route"
            if not self.landing:
                self._level = "body"
                self._hops = 0
                if not known or clash:
                    self.table.learn(self.raw_id, pid, by="route", force=clash)
        r = self.route
        if r and r["ship"] == ship and r["target"] == target:
            r["from"] = self.port or self.body or pid

    # ------------------------------------------------------------ other signals

    def _settle(self, ts: float) -> None:
        if self._pending and ts - self._pending[0] >= BURST_S:
            self._set_body(self._pending[1], "load")

    def _named_number(self) -> bool:
        """Does the location number you are in have a place? Then it outranks the softer signals."""
        return self.table.get(self.raw_id) is not None

    def _set_body(self, pid: str, by: str) -> None:
        self._pending = None
        # A location number with a place is better than a planet seen loading (you can see
        # the next moon load from where you are).
        if by == "load" and self._named_number():
            return
        self.body, self._body_by = pid, by
        self.system = self.places.system_of(pid)

    def _planet(self, ts: float, pid: str) -> None:
        # Only a lone load says where you are; the batches at join load planets
        # of every system, so they set neither the body nor the system.
        if ts < self._burst_until:
            self._burst_until = ts + BURST_S
            return
        if self._pending and ts - self._pending[0] < BURST_S:
            self._pending = None
            self._burst_until = ts + BURST_S
            return
        self._pending = (ts, pid, time.time())

    def _ground(self, pid: str | None) -> None:
        """The physics block every ten minutes: the planet or moon whose ground is loaded, or none."""
        if pid:
            if self.body and self._body_by == "number":
                return        # the location number already says where
            if self.port and not self.landing and not self.places.within(self.port, pid):
                self.port = None
            if not (self.body and self.places.within(self.body, pid)):
                self.body, self._body_by = pid, "cells"
            self.system = self.places.system_of(pid)
        elif self._body_by == "cells":
            self.body, self._body_by = None, None

    def _notice(self, ts: float, text: str) -> None:
        text = text.strip()
        m = RE_JURIS.match(text)
        if m:
            who = m.group(1).strip()
            self.jurisdiction = who[:40]
            self._event(ts, "Entered " + self.jurisdiction + " jurisdiction")
            planet = self.places.planets_by_name.get(_norm(JURISDICTION.get(who.lower(), "")))
            if planet:
                self.jur_area = planet
                self.system = self.places.system_of(planet)
                if self.body and not self.places.within(self.body, planet) and not self._named_number():
                    self.body, self._body_by = None, None
            else:
                # UEE, Ungoverned or a gang's space: no planet company's area any more.
                self.jur_area = None
                home = JURISDICTION_SYSTEM.get(who.lower())
                if home and self.system != home:
                    self.system = home
                    self.port = None
                    self.body, self._body_by = None, None
                    self._level = None
            return
        low = text.lower()
        if low.startswith("entering armistice zone"):
            self.armistice = True
            self._event(ts, "Entered armistice zone")
            pid = (self._landing_ports.get(self.landing) if self.landing else None) or self._fresh_hint(ts)
            if pid and not self.port:
                self._set_port(pid)
        elif low.startswith("leaving armistice zone"):
            self.armistice = False
            self._event(ts, "Left armistice zone")
            # Still inside the landing area (flying around the city): keep the port.
            if not self.landing:
                self.port = None

    def _event(self, ts: float, text: str) -> None:
        self.event = (ts, text[:80])

    def _fresh_hint(self, ts: float) -> str | None:
        if self._port_hint and ts - self._port_hint[0] <= PORT_HINT_S:
            return self._port_hint[1]
        return None

    def _set_port(self, pid: str) -> None:
        self.port = pid
        self.system = self.places.system_of(pid)

    # ------------------------------------------------------------ reading

    def _confidence(self, pid: str) -> str:
        if self.places.is_spot(pid):
            return "exact"
        return "system" if self.places.kind(pid) == "system" else "near"

    def snapshot(self) -> dict | None:
        """What goes to 7Net: the best place and how sure it is, or None."""
        with self._lock:
            if self.port:
                pid, conf, src = self.port, "exact", "port"
            elif self.body:
                pid, conf, src = self.body, "near", "planet"
            elif self.jur_area:
                pid, conf, src = self.jur_area, "area", "jurisdiction"
            elif self.system:
                pid, conf, src = self.system, "system", "system"
            else:
                pid, conf, src = None, None, None
            # The screen (screen.py) decides unless Game.log already has a spot inside the
            # place the screen names: the debug text often shows only the moon's zone while
            # the log knows the station on it.
            scr = self.screen.get("place_id") if self.screen else None
            if scr and scr in self.places.by_id and not (pid and pid != scr and self.places.within(pid, scr)):
                pid, conf, src = scr, self._confidence(scr), "screen"
            if not pid:
                return None
            r = self.route
            transit = None
            if r:
                transit = {"from": r["from"], "to": r["to"], "to_label": r["to_label"], "state": "route",
                           "since": _iso(r["since"])}
            out = {"place_id": pid, "confidence": conf, "source": src, "armistice": self.armistice,
                   "shard": self.shard, "raw_id": self.raw_id,
                   "jurisdiction": self.jurisdiction, "transit": transit,
                   "event": {"text": self.event[1], "at": _iso(self.event[0])} if self.event else None}
            # The exact position: only when the member shares it, it is fresh, and it is on the
            # body the place is on. Absent otherwise, which clears it on 7Net.
            sp = self.screen_pos
            if (self.share_position and sp and time.time() - sp["at"] <= POS_STALE_S
                    and (pid == sp["body"] or self.places.within(pid, sp["body"]))):
                out["pos"] = {"body": sp["body"], "lat": sp["lat"], "lon": sp["lon"], "alt": sp["alt"]}
            return out

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
        self._logged: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="gamelog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _feed(self, line: str) -> None:
        """One line to the tracker. A line it cannot handle must never end this thread:
        the place would then freeze until the client is restarted."""
        try:
            self.tracker.feed(line)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if msg != self._logged:      # once per kind of error, not once per line
                self._logged = msg
                log.warning("Game.log line not understood (%s)", msg, exc_info=True)

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
                        self._feed(raw.decode("utf-8", errors="replace"))
                    self.error = None
                except OSError as e:
                    self.error = str(e)[:200]
            try:
                self.tracker.tick()
            except Exception:  # noqa: BLE001
                log.warning("place tracker tick failed", exc_info=True)
            self._stop.wait(self.poll)
