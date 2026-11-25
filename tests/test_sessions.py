"""Whole play sessions through the tracker: tests/data/sessions_2026-11.log (see tests/data/README.md).

These are the measures 0.7.1 failed on real sessions: no place for minutes after a login,
a planet shown hours after leaving it, 28 % of the time marked as quantum travel from
party notices, and 1 of 8 own trips found.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sevenhills_link.location import LocationTable, Places, Tracker, _ts

PLACES = Places.load()
LOG = Path(__file__).parent / "data" / "sessions_2026-11.log"
LINES = LOG.read_text(encoding="utf-8").splitlines()
SEED = json.loads(Path(__file__).resolve().parents[1].joinpath("src/sevenhills_link/data/location_ids.json").read_text(encoding="utf-8"))["ids"]


def at(day: int, clock: str) -> float:
    return datetime.fromisoformat(f"2026-11-{day:02d}T{clock}+00:00").timestamp()


def replay(table: LocationTable):
    """Feed every line; yield (time, line, tracker, snapshot after the line)."""
    t = Tracker(PLACES, table)
    for line in LINES:
        ts = _ts(line)
        t.feed(line)
        yield ts, line, t, t.snapshot()


def shipped() -> LocationTable:
    return LocationTable(dict(SEED), {})


def test_the_shipped_numbers_are_all_on_the_place_list():
    assert len(SEED) >= 15
    for number, entry in SEED.items():
        assert number.isdigit() and entry["place"] in PLACES.by_id, number


def test_a_place_within_a_minute_of_every_login():
    waits = []
    joined = None
    for ts, line, _t, snap in replay(shipped()):
        if "<Join PU>" in line:
            joined = ts
        elif joined is not None and snap:
            waits.append(ts - joined)
            joined = None
    assert len(waits) == 6
    assert max(waits) <= 60, waits          # 0.7.1: 6 min 45 s and 9 min 25 s on two of the six


def test_login_aboard_a_ship_in_pyro_and_login_on_daymar():
    seen = {}
    for ts, _line, _t, snap in replay(shipped()):
        if snap and at(21, "18:56:05") < ts < at(21, "18:57:00"):
            seen.setdefault("pyro", snap["place_id"])
        if snap and at(23, "17:58:54") < ts < at(23, "18:00:00"):
            seen.setdefault("daymar", (snap["place_id"], snap["confidence"]))
    assert seen == {"pyro": "pyro", "daymar": ("stanton/crusader/daymar", "near")}


def test_on_daymar_all_evening_not_at_the_planet_left_hours_before():
    crusader = []
    for ts, _line, _t, snap in replay(shipped()):
        if at(21, "21:27:00") <= ts <= at(22, "01:44:00"):
            assert snap["place_id"] == "stanton/crusader/daymar", datetime.fromtimestamp(ts, tz=timezone.utc)
        if at(21, "21:20:30") <= ts <= at(21, "21:26:40"):
            crusader.append(snap["place_id"])
    assert crusader and set(crusader) == {"stanton/crusader"}


def test_through_the_gateways_from_stanton_to_nyx():
    places = []
    for ts, _line, _t, snap in replay(shipped()):
        if snap and at(23, "18:51:00") <= ts <= at(23, "19:00:00") and (not places or places[-1] != snap["place_id"]):
            places.append(snap["place_id"])
    assert places == ["stanton/jump-magnus", "nyx/jump-castra", "nyx"]


def test_party_quantum_notices_never_mark_you_as_travelling():
    notices = 0
    for _ts_, line, t, snap in replay(shipped()):
        if "Quantum Travel Calibration" in line or "has started to QT" in line:
            notices += 1
            # Whatever a party member does, your route is only what you plotted yourself.
            assert (snap["transit"] is None) == (t.route is None)
            assert "PartyMember" not in json.dumps(snap)
    assert notices > 50


def test_your_own_plotted_routes_are_found_and_nothing_else():
    routes = []
    current = None
    for ts, _line, _t, snap in replay(shipped()):
        r = snap["transit"] if snap else None
        key = (r["to"], r["to_label"]) if r else None
        if key != current:
            if r:
                assert r["state"] == "route"
                routes.append((r["from"], r["to"] or r["to_label"]))
            current = key
    assert routes == [
        ("pyro/terminus/ruin-station", "pyro/jump-stanton"),     # 21 Nov 18:49, the game was closed before the jump
        ("stanton", "a party member"),                           # 19:16, ends on reaching Daymar (no arrival line)
        ("stanton/crusader/daymar", "stanton/microtech"),        # 21:10
        ("stanton", "stanton/crusader"),                         # 21:14, changed in open space; arrives 21:20
        ("stanton/crusader/daymar", "a mission marker"),         # 23 Nov 18:07
        ("stanton", "a mission marker"),                         # 18:12
        ("nyx", "nyx/glaciem-ring"),                             # 22:08
        ("nyx/glaciem-ring", "nyx/jump-pyro"),                   # 22:13
        ("nyx", "nyx/keeger-belt"),                              # 22:16, lands at a base in the belt
        ("nyx", "a party member"),                               # 22:36, never flown: forgotten after 15 minutes
    ]


def test_a_route_ends_when_your_ship_arrives_not_when_another_ship_does():
    # 21 Nov 21:14:49 route to Crusader; the Idris arrives 21:20:28. A Galaxy arrives nearby
    # at 22:30:30 while no route is plotted: nothing happens.
    events = {}
    for ts, line, t, snap in replay(shipped()):
        if at(21, "21:14:50") <= ts <= at(21, "21:20:20"):
            assert snap["transit"]["to"] == "stanton/crusader"
        if ts == _ts("<2026-11-21T21:20:28.228Z>"):
            events["own"] = (snap["transit"], t.event[1])
        if "RSI_Galaxy_900000000003" in line:
            events["other"] = (snap["transit"], t.event[1])
    assert events["own"] == (None, "Arrived at Crusader")
    assert events["other"][0] is None and not events["other"][1].startswith("Arrived")


def share_of_time(table: LocationTable) -> dict[str, float]:
    """Seconds in the PU by what was reported: nothing, system, area, body, spot."""
    out = {"nothing": 0.0, "system": 0.0, "area": 0.0, "body": 0.0, "spot": 0.0}
    prev_ts = prev = None
    for ts, line, _t, snap in replay(table):
        if prev_ts is not None and prev is not None and 0 < ts - prev_ts < 3600:
            out[prev] += ts - prev_ts
        if "<Join PU>" in line:
            prev = "nothing"
        elif prev is not None:
            if not snap:
                prev = "nothing"
            elif snap["confidence"] == "exact":
                prev = "spot"
            else:
                prev = {"system": "system", "area": "area", "near": "body"}[snap["confidence"]]
        prev_ts = ts
    return out


def test_most_of_the_time_is_a_planet_moon_or_landing_area():
    s = share_of_time(shipped())
    total = sum(s.values())
    assert s["nothing"] / total < 0.01                       # 0.7.1: 2.5 %
    assert s["system"] / total < 0.35                        # 0.7.1: 46 %, now mostly open space and unnamed sites in Nyx
    assert (s["body"] + s["spot"]) / total > 0.60            # 0.7.1: 46 %, and the planet was hours out of date


def test_a_first_run_without_the_shipped_numbers_learns_from_the_log(tmp_path: Path):
    path = tmp_path / "locations.json"
    first = LocationTable({}, {}, path)
    for _ in replay(first):
        pass
    learnt = json.loads(path.read_text(encoding="utf-8"))["ids"]
    assert learnt["2026442305"] == {"place": "pyro/terminus/ruin-station", "by": "landing"}
    assert learnt["2610496815"] == {"place": "stanton/crusader/daymar", "by": "route"}       # "Projected Start Location is Daymar"
    assert learnt["1902223495"] == {"place": "stanton", "by": "route"}                       # "... is Stanton System"
    assert learnt["4019052551"]["place"] == "stanton/crusader/daymar" and learnt["4019052551"]["name"] == "Outpost OLP Stanton2b Lamina"
    # A mission site whose route start only says "Stanton" is not written down as a place.
    assert "1685977803" not in learnt
    # The second time the same PC knows Daymar from the first line after the login there.
    again = LocationTable({}, json.loads(path.read_text(encoding="utf-8"))["ids"], path)
    joined = False
    for ts, line, _t, snap in replay(again):
        if "<Join PU>" in line and ts > at(23, "17:58:00"):
            joined = True
        elif joined:
            assert "<Update Inventory Location>" in line and ts - at(23, "17:58:54") < 30
            assert snap["place_id"] == "stanton/crusader/daymar"
            break
    else:
        pytest.fail("no line after the login on Daymar")


def test_nothing_about_other_players_or_positions_is_sent():
    for _ts_, _line, _t, snap in replay(shipped()):
        if not snap:
            continue
        text = json.dumps(snap)
        assert "PartyMember" not in text and "TestPilot" not in text
        assert set(snap) == {"place_id", "confidence", "source", "armistice", "shard", "raw_id", "jurisdiction", "transit", "event"}
        assert snap["place_id"] in PLACES.by_id
        if snap["transit"]:
            assert set(snap["transit"]) == {"from", "to", "to_label", "state", "since"}
            assert snap["transit"]["to_label"] in (None, "a party member", "a mission marker")
        if snap["event"]:
            assert len(snap["event"]["text"]) <= 80 and not re.search(r"\d+\.\d+\s*k?m\b", snap["event"]["text"])
