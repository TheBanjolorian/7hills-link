"""tools/extract_gamelog.py: what is kept of a Game.log, and that no name survives."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extract_gamelog", ROOT / "tools" / "extract_gamelog.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

RAW = [
    "<2026-11-21T18:55:00.560Z> [Notice] <Legacy login response> [CIG-net] User Login Success - Handle[RealHandle] - Time[1] [Team_GameServices][Login]",
    "<2026-11-21T18:56:05.455Z> [Notice] <Join PU> address[203.0.113.7] port[64366] shard[pub_euw1b_13165946_320] locationId[-281470681677823] [GIM][Matchmaking]",
    "<2026-11-21T18:56:26.000Z> [Notice] <Update Inventory Location> Player [RealHandle] is changing location. Landing [0] -> [2026442305]. Location [0] -> [2026442305]. Pending [0] [Inventory]",
    "<2026-11-21T18:56:27.000Z> [Notice] <RequestLocationInventory> Player[RealHandle] requested inventory for Location[RR_P6_LEO] [Inventory]",
    '<2026-11-21T18:56:28.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "Entered Ungoverned Jurisdiction: " [1] to queue. New queue size: 1, MissionId: [0000], ObjectiveId: [] [Comms]',
    '<2026-11-21T18:56:29.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "Quantum Travel Calibration Started By SomeFriend: " [2] to queue. New queue size: 1 [Comms]',
    '<2026-11-21T18:56:30.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "Quantum Travel Calibration Complete By RealHandle: " [3] to queue. New queue size: 1 [Comms]',
    '<2026-11-21T18:56:31.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "AnotherFriend has started to QT to your current location.: " [4] to queue. New queue size: 1 [Comms]',
    '<2026-11-21T18:56:32.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "New Objective: Neutralize SomeoneElse: " [5] to queue. New queue size: 1 [Comms]',
    "<2026-11-21T18:56:33.000Z> [Notice] <Player Selected Quantum Target - Local> [ItemNavigation][CL][1] | NOT AUTH | AEGS_Idris_M_123456789012[123456789012]|CSCItemNavigation::OnPlayerSelectedQuantumTarget|Player has selected point OOC_Stanton_2_Crusader as their destination, routing locally [Team_CGP4][QuantumTravel]",
    "<2026-11-21T18:56:34.000Z> [Notice] <Calculate Route> [ItemNavigation][CL][1] | NOT AUTH | AEGS_Idris_M_123456789012[123456789012]|CSCItemNavigation::CalculateRoute|Successfully calculated route to OOC_Stanton_2_Crusader fuel estimate 1.0 [Team_CGP4][QuantumTravel]",
    "<2026-11-21T18:56:35.000Z> [Notice] <Calculate Route> [ItemNavigation][CL][1] | NOT AUTH | AEGS_Idris_M_123456789012[123456789012]|CSCItemNavigation::CalculateRoute|Projected Start Location is Ruin Station for route to destination OOC_Stanton_2_Crusader [Team_CGP4][QuantumTravel]",
    "<2026-11-21T18:56:36.000Z> [GLOBAL] SomeoneElse: a chat line with location: Lorville in it",
    "<2026-11-21T18:56:37.000Z> PHYSICS INSTANCE STATS BEGIN 1",
    "<2026-11-21T18:56:37.000Z>   planet cells:    0 [    0] meshes:    0 [    0] name: OOC_Stanton_3a_Lyria",
    "<2026-11-21T18:56:37.000Z>   planet cells:  594 [16384] meshes:   89 [ 2048] name: OOC_Stanton_2b_Daymar",
    "<2026-11-21T18:56:37.000Z> PHYSICS INSTANCE STATS END",
    "a line without a time stamp from RealHandle",
]


def test_only_place_lines_survive_and_no_name_does():
    out = list(tool.extract(RAW))
    text = "\n".join(out)
    for secret in ("RealHandle", "SomeFriend", "AnotherFriend", "SomeoneElse", "203.0.113.7", "chat line", "Legacy login"):
        assert secret not in text, secret
    assert len(out) == 12
    assert "address[0.0.0.0] port[0] shard[pub_euw1b_13165946_320]" in out[0]
    assert "Player [TestPilot]" in out[1] and "Location [0] -> [2026442305]" in out[1]
    assert "Player[TestPilot]" in out[2] and "Location[RR_P6_LEO]" in out[2]
    assert '"Entered Ungoverned Jurisdiction: "' in out[3]
    assert '"Quantum Travel Calibration Started By PartyMember1: "' in out[4]
    assert '"Quantum Travel Calibration Complete By TestPilot: "' in out[5]
    assert '"PartyMember2 has started to QT to your current location.: "' in out[6]
    assert "selected point OOC_Stanton_2_Crusader" in out[7]
    assert "Projected Start Location is Ruin Station" in out[8]     # the fuel line before it is dropped
    # The ship's id is a stand-in, the same one on both lines; the place number above is kept.
    assert "123456789012" not in text
    assert "AEGS_Idris_M_900000000001[900000000001]|" in out[7] and "AEGS_Idris_M_900000000001[900000000001]|" in out[8]
    assert out[9].endswith("PHYSICS INSTANCE STATS BEGIN 1") and "OOC_Stanton_2b_Daymar" in out[10] and out[11].endswith("STATS END")


def test_ids_of_ships_markers_and_beacons_become_stand_ins():
    def nav(ship, text):
        return (f"<2026-11-21T19:00:00.000Z> [Notice] <Player Selected Quantum Target - Local> [ItemNavigation][CL][1] | NOT AUTH | "
                f"{ship}|CSCItemNavigation::OnPlayerSelectedQuantumTarget|Player has selected point {text} as their destination, routing locally")
    out = list(tool.extract([
        nav("AEGS_Idris_M_111111111111[111111111111]", "PartyMemberMarker_222222222222"),
        nav("AEGS_Idris_M_111111111111[111111111111]", "MISSION_QT_Quantum_Beacon_333333333333"),
        nav("RSI_Galaxy_444444444444[444444444444]", "PartyMemberMarker_222222222222"),
    ]))
    assert "AEGS_Idris_M_900000000001[900000000001]|" in out[0] and "PartyMemberMarker_900000000002 " in out[0]
    assert "AEGS_Idris_M_900000000001[900000000001]|" in out[1] and "MISSION_QT_Quantum_Beacon_900000000003 " in out[1]
    assert "RSI_Galaxy_900000000004[900000000004]|" in out[2] and "PartyMemberMarker_900000000002 " in out[2]
    assert not any(n in "\n".join(out) for n in ("111111111111", "222222222222", "333333333333", "444444444444"))


def test_the_shipped_sessions_hold_no_real_ship_or_marker_id():
    import re
    text = (ROOT / "tests" / "data" / "sessions_2026-11.log").read_text(encoding="utf-8")
    ids = set(re.findall(r"\d{9,}", "\n".join(line for line in text.splitlines() if "CSCItemNavigation::" in line)))
    assert ids and all(re.fullmatch(r"9000000000\d\d", n) for n in ids), sorted(ids)
    assert "address[0.0.0.0] port[0]" in text and not re.search(r"address\[(?!0\.0\.0\.0\])", text)
    assert set(re.findall(r"Player ?\[([^\]]*)\]", text)) == {"TestPilot"}


def test_the_tracker_reads_what_the_tool_writes():
    from sevenhills_link.location import Places, Tracker
    t = Tracker(Places.load())
    for line in tool.extract(RAW):
        t.feed(line)
    snap = t.snapshot()
    assert snap["place_id"] == "pyro/terminus/ruin-station"        # the landing name; the ground block does not overrule a landing area
    assert snap["transit"]["to"] == "stanton/crusader" and snap["jurisdiction"] == "Ungoverned"
