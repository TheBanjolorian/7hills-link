"""The game's location numbers (location.LocationTable) and the rules around them.

Numbers and names are the real ones from 4.10 LIVE sessions (data/location_ids.json);
4100000001 and up are made up and stand for "a number nobody has named".
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from sevenhills_link.location import GameLogFollower, LocationTable, Places, Tracker

PLACES = Places.load()
DAYMAR, CRUSADER, STANTON, NYX = "2610496815", "2493660041", "1902223495", "2627827560"
RUIN, PYRO_GATE, PYRO_GATE_SPACE = "2026442305", "1547955914", "694522860"
SEED = {DAYMAR: {"place": "stanton/crusader/daymar"}, CRUSADER: {"place": "stanton/crusader"}, STANTON: {"place": "stanton"},
        NYX: {"place": "nyx"}, RUIN: {"place": "pyro/terminus/ruin-station"}, PYRO_GATE: {"place": "stanton/jump-pyro"},
        PYRO_GATE_SPACE: {"place": "stanton/jump-pyro", "near": True}}
SHIP = "AEGS_Idris_M_900000000001[900000000001]"
_clock = [0]


def L(rest: str) -> str:
    _clock[0] += 5
    s = _clock[0]
    return f"<2026-11-21T{12 + s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}.000Z> {rest}"


def join() -> str:
    return L("[Notice] <Join PU> address[0.0.0.0] port[0] shard[pub_euw1b_13165946_320] locationId[-281470681677823] [GIM]")


def move(to: str, landing: str = "0", frm: str = "0") -> str:
    return L(f"[Notice] <Update Inventory Location> Player [TestPilot] is changing location. Landing [0] -> [{landing}]. Location [{frm}] -> [{to}]. Pending [0] [Inventory]")


def landed(name: str) -> str:
    return L(f"[Notice] <RequestLocationInventory> Player[TestPilot] requested inventory for Location[{name}] [Inventory]")


def note(text: str) -> str:
    return L(f'[Notice] <SHUDEvent_OnNotification> Added notification "{text}: " [0] to queue. New queue size: 1 [Comms]')


def route_start(start: str, target: str = "OOC_Stanton_4_Microtech") -> str:
    return L(f"[Notice] <Calculate Route> [ItemNavigation][CL][1] | NOT AUTH | {SHIP}|CSCItemNavigation::CalculateRoute|Projected Start Location is {start} for route to destination {target} [Team_CGP4][QuantumTravel]")


def ground(*bodies: tuple[str, int]) -> list[str]:
    return [L("PHYSICS INSTANCE STATS BEGIN 1"), *[L(f"  planet cells: {n:4d} [16384] meshes:   47 [ 2048] name: {name}") for name, n in bodies],
            L("PHYSICS INSTANCE STATS END")]


def run(lines, table: LocationTable | None = None) -> Tracker:
    t = Tracker(PLACES, table if table is not None else LocationTable(dict(SEED), {}))
    for line in lines:
        t.feed(line)
    return t


def place(t: Tracker):
    s = t.snapshot()
    return (s["place_id"], s["confidence"]) if s else None


# ------------------------------------------------------------ the table

def test_a_landing_areas_own_name_beats_the_shipped_entry_and_a_route_start_does_not():
    table = LocationTable({"1": {"place": "stanton"}}, {})
    assert table.learn("1", "stanton/crusader", by="route") is False
    assert table.get("1") == {"place": "stanton"}
    assert table.learn("1", "pyro/terminus/ruin-station", by="landing") is True
    assert table.get("1")["place"] == "pyro/terminus/ruin-station"
    assert table.learn("1", "stanton/crusader", by="route") is False          # nor a landing name learnt earlier
    assert table.learn("0", "stanton", by="landing") is False and table.learn(None, "stanton") is False


def test_a_route_start_that_cannot_be_the_listed_place_replaces_it_on_this_pc():
    # The game changed what a number means: the log says Daymar where the list says Pyro.
    table = LocationTable({"7": {"place": "pyro"}}, {})
    t = run([join(), move("7"), route_start("Daymar")], table)
    assert place(t) == ("stanton/crusader/daymar", "near")
    assert table.get("7")["place"] == "stanton/crusader/daymar" and table.get("7")["over"] is True
    # Something the list already says, or says more precisely, changes nothing.
    table = LocationTable(dict(SEED), {})
    run([join(), move(DAYMAR), route_start("Daymar"), move(STANTON), route_start("Stanton System")], table)
    assert table.learnt == {}


def test_what_was_learnt_is_kept_in_a_file_and_bad_entries_are_dropped(tmp_path: Path):
    path = tmp_path / "locations.json"
    table = LocationTable({}, {}, path)
    table.learn("11", "pyro/terminus/ruin-station", by="landing")
    table.learn("12", "stanton/crusader/daymar", name="Outpost OLP Stanton2b Lamina", by="landing")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["ids"]["12"] == {"place": "stanton/crusader/daymar", "by": "landing", "name": "Outpost OLP Stanton2b Lamina"}
    path.write_text(json.dumps({"version": 1, "ids": {**saved["ids"], "13": {"place": "not/a/place"}, "14": "nonsense"}}), encoding="utf-8")
    again = LocationTable.load(path)
    assert "14" not in again.learnt
    Tracker(PLACES, again)                      # the tracker drops places that are not on its list
    assert set(again.learnt) == {"11", "12"}
    assert again.get("2610496815")["place"] == "stanton/crusader/daymar"       # and the shipped numbers are there
    assert LocationTable.load(tmp_path / "missing.json").learnt == {}


def test_the_learnt_file_does_not_grow_without_end(tmp_path: Path):
    table = LocationTable({}, {})
    table.MAX_LEARNT = 5
    for i in range(1, 9):
        table.learn(str(i), "stanton", by="landing")
    assert list(table.learnt) == ["4", "5", "6", "7", "8"]


# ------------------------------------------------------------ numbers nobody has named

def test_one_unnamed_number_keeps_the_moon_and_a_second_one_means_you_moved_on():
    t = run([join(), move(DAYMAR)])
    assert place(t) == ("stanton/crusader/daymar", "near")
    t.feed(move("4100000001", frm=DAYMAR))         # a spot on the moon
    assert place(t) == ("stanton/crusader/daymar", "near")
    t.feed(move(DAYMAR, frm="4100000001"))
    t.feed(move("4100000002", frm=DAYMAR))         # open space in a system whose number nobody named ...
    t.feed(move("4100000003", frm="4100000002"))   # ... and then somewhere else
    assert place(t) == ("stanton", "system")


def test_from_open_space_into_an_unnamed_number_is_somewhere_in_the_system():
    t = run([join(), move(CRUSADER), move(STANTON, frm=CRUSADER)])
    assert place(t) == ("stanton", "system")
    t.feed(move("4100000001", frm=STANTON))
    assert place(t) == ("stanton", "system")
    t.feed(move(STANTON, frm="4100000001"))
    t.feed(move(DAYMAR, frm=STANTON))
    assert place(t) == ("stanton/crusader/daymar", "near")


def test_leaving_a_station_into_an_unnamed_number_is_still_next_to_it_for_one_step():
    t = run([join(), move(RUIN, landing=RUIN), landed("RR_P6_LEO")])
    assert place(t) == ("pyro/terminus/ruin-station", "exact")
    t.feed(move("4100000001", frm=RUIN))
    assert place(t) == ("pyro/terminus/ruin-station", "near")
    assert t.event[1] == "Left Ruin Station"
    t.feed(move("4100000002", frm="4100000001"))
    assert place(t) == ("pyro", "system")


def test_the_space_around_a_gateway_is_near_it_not_in_it():
    t = run([join(), move(STANTON), move(PYRO_GATE_SPACE, frm=STANTON)])
    assert place(t) == ("stanton/jump-pyro", "near")
    t.feed(move(PYRO_GATE, landing=PYRO_GATE, frm=PYRO_GATE_SPACE))
    assert place(t) == ("stanton/jump-pyro", "exact")           # by the number alone, before the name line


def test_a_landing_area_that_is_not_on_the_list_is_remembered_with_its_name():
    table = LocationTable(dict(SEED), {})
    t = run([join(), move(DAYMAR), move("4019052551", landing="4019052551", frm=DAYMAR), landed("Outpost_OLP_Stanton2b_Lamina")], table)
    assert place(t) == ("stanton/crusader/daymar", "near")
    assert table.get("4019052551") == {"place": "stanton/crusader/daymar", "by": "landing", "name": "Outpost OLP Stanton2b Lamina"}
    t.feed(move(DAYMAR, frm="4019052551"))
    assert t.event[1] == "Left Outpost OLP Stanton2b Lamina"
    # A base in open space: the belt in its name, and next login the number alone is enough.
    t = run([join(), move(NYX), move("2263490509", landing="2263490509", frm=NYX), landed("AsteroidClusterBase_Nyx_Social_Keeger_004")], table)
    assert place(t) == ("nyx/keeger-belt", "near")
    t = run([join(), move("2263490509", landing="2263490509")], table)
    assert place(t) == ("nyx/keeger-belt", "near")


# ------------------------------------------------------------ other signals

def test_jurisdictions():
    # A gang's or an alliance's space names its system when nothing else has.
    assert place(run([join(), move("4100000001"), note("Entered Rough & Ready Jurisdiction")], LocationTable())) == ("pyro", "system")
    assert place(run([join(), move("4100000001"), note("Entered People's Alliance Jurisdiction")], LocationTable())) == ("nyx", "system")
    # UEE space is also around the gateways in Pyro and Nyx: it says nothing about the system.
    assert run([join(), move("4100000001"), note("Entered UEE Jurisdiction")], LocationTable()).snapshot() is None
    assert run([join(), move("4100000001"), note("Entered Ungoverned Jurisdiction")], LocationTable()).snapshot() is None
    # Leaving a planet company's space ends its area.
    t = run([join(), move("4100000001"), note("Entered Crusader Industries Jurisdiction")], LocationTable())
    assert place(t) == ("stanton/crusader", "area") and t.snapshot()["jurisdiction"] == "Crusader Industries"
    t.feed(note("Entered Ungoverned Jurisdiction"))
    assert place(t) == ("stanton", "system") and t.snapshot()["jurisdiction"] == "Ungoverned"
    # A place the number names is not thrown away by a notice from the planet next door.
    t = run([join(), move(DAYMAR), note("Entered Hurston Dynamics Jurisdiction")])
    assert place(t) == ("stanton/crusader/daymar", "near")


def test_a_routes_start_location_is_a_place_and_teaches_the_number():
    table = LocationTable({}, {})
    t = run([join(), move("4100000001"), route_start("Daymar")], table)
    assert place(t) == ("stanton/crusader/daymar", "near")
    assert table.get("4100000001") == {"place": "stanton/crusader/daymar", "by": "route"}
    t.feed(move("4100000002", frm="4100000001"))
    t.feed(route_start("Stanton System"))
    assert place(t) == ("stanton", "system")
    assert table.get("4100000002") == {"place": "stanton", "by": "route"}
    # "Nyx" without "System" is a site the starmap has no name for: the system, and nothing learnt.
    t.feed(move("4100000003", frm="4100000002"))
    t.feed(route_start("Nyx"))
    assert place(t) == ("nyx", "system") and table.get("4100000003") is None
    # Standing in a landing area, the number belongs to the landing area: not taught to mean the moon.
    table = LocationTable({}, {})
    run([join(), move("4100000009", landing="4100000009"), landed("Stanton2b_ShubinMining_SCD1"), route_start("Daymar")], table)
    assert table.get("4100000009")["by"] == "landing"


def test_the_ground_that_is_loaded_names_the_moon_until_it_is_gone():
    t = run([join(), move("4100000001"), *ground(("OOC_Stanton_2b_Daymar", 594), ("OOC_Stanton_2_Crusader", 0))], LocationTable())
    assert place(t) == ("stanton/crusader/daymar", "near")
    for line in ground():                              # ten minutes later no planet has ground loaded
        t.feed(line)
    assert place(t) == ("stanton", "system")
    # A number that names the place is not overruled by it.
    t = run([join(), move(CRUSADER), *ground(("OOC_Stanton_2b_Daymar", 12))])
    assert place(t) == ("stanton/crusader", "near")


def test_a_new_login_starts_over_but_keeps_what_was_learnt():
    table = LocationTable({}, {})
    t = run([join(), move("4100000001", landing="4100000001"), landed("RR_P6_LEO")], table)
    t.feed(join())
    assert t.snapshot() is None
    t.feed(move("4100000001", landing="4100000001"))
    assert place(t) == ("pyro/terminus/ruin-station", "exact")


# ------------------------------------------------------------ the reader thread

def test_a_line_the_tracker_chokes_on_does_not_stop_the_reader(tmp_path: Path, caplog):
    log = tmp_path / "Game.log"
    log.write_text("\n".join([join(), move(RUIN, landing=RUIN), "<2026-11-21T12:59:00.000Z> BOOM", "<2026-11-21T12:59:01.000Z> BOOM",
                              landed("RR_P6_LEO")]) + "\n", encoding="utf-8")
    t = Tracker(PLACES, LocationTable(dict(SEED), {}))
    real = t.feed

    def feed(line: str) -> None:
        if "BOOM" in line:
            raise KeyError("not understood")
        real(line)

    t.feed = feed  # type: ignore[method-assign]
    f = GameLogFollower(log, t, poll=0.01)
    with caplog.at_level("WARNING", logger="7hillslink"):
        th = threading.Thread(target=f._run, daemon=True)
        th.start()
        for _ in range(300):
            if t.event and t.event[1] == "Landed at Ruin Station":
                break
            time.sleep(0.01)
        f.stop()
        th.join(timeout=2)
    assert t.event[1] == "Landed at Ruin Station"            # the line after the bad ones was read
    assert len([r for r in caplog.records if "not understood" in r.getMessage()]) == 1     # logged once, not per line
