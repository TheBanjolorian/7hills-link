"""Landing area by name, the route plotted on your own ship, jurisdiction and the newest event.

Lines are shaped like real 4.10 LIVE sessions (build 13220821, Nov 2026), with the
player's handle and the party members' handles replaced.
"""

from sevenhills_link.location import Places, Tracker

PLACES = Places.load()
SHIP = "AEGS_Idris_M_900000000001[900000000001]"
OTHER = "RSI_Galaxy_900000000003[900000000003]"


def L(t: str, rest: str) -> str:
    return f"<2026-11-21T{t}Z> {rest}"


def nav(t: str, tag: str, ship: str, call: str, text: str) -> str:
    return L(t, f"[Notice] <{tag}> [ItemNavigation][CL][38248] | NOT AUTH | {ship}|CSCItemNavigation::{call}|{text} [Team_CGP4][QuantumTravel]")


def note(t: str, text: str) -> str:
    return L(t, f'[Notice] <SHUDEvent_OnNotification> Added notification "{text}: " [4] to queue. New queue size: 1 [Team_CoreGameplayFeatures][Missions][Comms]')


JOIN = L("18:56:05.455", "[Notice] <Join PU> address[0.0.0.0] port[64366] shard[pub_euw1b_13165946_320] locationId[-281470681677823] [GIM][Matchmaking]")
RUIN_NO = L("18:56:30.040", "[Notice] <Update Inventory Location> Player [TestPilot] is changing location. Landing [0] -> [2026442305]. Location [0] -> [2026442305]. Pending [0] [Inventory]")
RUIN = L("18:56:30.046", "[Notice] <RequestLocationInventory> Player[TestPilot] requested inventory for Location[RR_P6_LEO] [Team_CoreGameplayFeatures][Inventory]")
SELECT = nav("18:57:51.414", "Player Selected Quantum Target - Local", SHIP, "OnPlayerSelectedQuantumTarget", "Player has selected point rs_ext_pyro-stan_jp1 as their destination, routing locally")
START = nav("18:57:51.414", "Calculate Route", SHIP, "CalculateRoute", "Projected Start Location is Ruin Station for route to destination rs_ext_pyro-stan_jp1")
CAL_PARTY = note("18:58:00.000", "Quantum Travel Calibration Started By PartyMemberOne")
CAL_PARTY_DONE = note("18:58:06.000", "Quantum Travel Calibration Complete By PartyMemberOne")
ARRIVED_OTHER = nav("18:58:19.000", "Quantum Drive Arrived - Arrived at Final Destination", OTHER, "OnQuantumDriveArrived", "Quantum Drive has arrived at final destination")
UEE = note("19:02:50.009", "Entered UEE Jurisdiction")
ARRIVED = nav("19:02:51.906", "Quantum Drive Arrived - Arrived at Final Destination", SHIP, "OnQuantumDriveArrived", "Quantum Drive has arrived at final destination")
GATE_NO = L("19:02:53.669", "[Notice] <Update Inventory Location> Player [TestPilot] is changing location. Landing [0] -> [639835600]. Location [3273347588] -> [639835600]. Pending [0] [Inventory]")
GATE = L("19:02:53.672", "[Notice] <RequestLocationInventory> Player[TestPilot] requested inventory for Location[RR_JP_PyroStanton] [Inventory]")
OUTPOST_NO = L("22:12:04.470", "[Notice] <Update Inventory Location> Player [TestPilot] is changing location. Landing [438795353] -> [3554465802]. Location [2610496815] -> [3554465802]. Pending [0] [Inventory]")
OUTPOST = L("22:12:04.473", "[Notice] <RequestLocationInventory> Player[TestPilot] requested inventory for Location[Outpost_PAF_Stanton2b_Attritus_2] [Team_CoreGameplayFeatures][Inventory]")


def run(lines):
    t = Tracker(PLACES)
    for line in lines:
        t.feed(line)
    return t


def test_landing_area_name_puts_you_at_the_station_without_an_atc_hint():
    snap = run([JOIN, RUIN_NO, RUIN]).snapshot()
    assert snap["place_id"] == "pyro/terminus/ruin-station"
    assert snap["confidence"] == "exact" and snap["source"] == "port"
    assert snap["event"]["text"] == "Arrived at Ruin Station"


def test_opening_the_inventory_again_is_not_a_new_landing():
    t = run([JOIN, RUIN_NO, RUIN])
    first = t.event
    t.feed(RUIN.replace("18:56:30.046", "18:59:12.000"))
    assert t.event == first


def test_gateway_station_names_map_to_the_jump_point_of_that_system():
    assert PLACES.named("RR_JP_PyroStanton") == "pyro/jump-stanton"
    assert PLACES.named("RR_JP_StantonPyro") == "stanton/jump-pyro"
    assert PLACES.named("RR_JP_NyxCastra") == "nyx/jump-castra"
    assert PLACES.named("rs_ext_pyro-stan_jp1") == "pyro/jump-stanton"
    assert PLACES.named("rs_ext_nyx-pyro_jp1") == "nyx/jump-pyro"
    assert PLACES.named("Stanton System") == "stanton"
    assert PLACES.named("Daymar") == "stanton/crusader/daymar"
    assert PLACES.named("OOC_Stanton_4_Microtech") == "stanton/microtech"


def test_a_target_plotted_on_your_own_ship_is_a_route():
    t = run([JOIN, RUIN_NO, RUIN, START, SELECT])
    snap = t.snapshot()
    assert snap["transit"] == {"from": "pyro/terminus/ruin-station", "to": "pyro/jump-stanton", "to_label": None,
                               "state": "route", "since": "2026-11-21T18:57:51Z"}
    assert snap["event"]["text"] == "Plotted a route to Stanton Gateway"
    assert snap["place_id"] == "pyro/terminus/ruin-station"      # plotting does not move you


def test_party_calibration_notices_say_nothing_about_you():
    # The notice goes to the whole party wherever each member is: no route, no event, no handle.
    t = run([JOIN, RUIN_NO, RUIN])
    before = t.snapshot()
    for line in (CAL_PARTY, CAL_PARTY_DONE):
        t.feed(line)
    assert t.snapshot() == before
    assert "PartyMemberOne" not in str(t.snapshot())


def test_another_ships_arrival_does_not_end_your_route():
    t = run([JOIN, RUIN_NO, RUIN, START, SELECT, CAL_PARTY, ARRIVED_OTHER])
    assert t.snapshot()["transit"]["to"] == "pyro/jump-stanton"
    assert t.snapshot()["event"]["text"] == "Plotted a route to Stanton Gateway"


def test_your_ships_arrival_ends_the_route():
    t = run([JOIN, RUIN_NO, RUIN, START, SELECT, UEE, ARRIVED])
    snap = t.snapshot()
    assert snap["transit"] is None
    assert snap["event"]["text"] == "Arrived at Stanton Gateway"
    for line in (GATE_NO, GATE):
        t.feed(line)
    snap = t.snapshot()
    assert snap["place_id"] == "pyro/jump-stanton" and snap["confidence"] == "exact"
    assert snap["jurisdiction"] == "UEE"
    assert snap["event"]["text"] == "Arrived at Stanton Gateway"


def test_a_route_without_an_arrival_is_forgotten_after_a_quarter_of_an_hour():
    t = run([JOIN, RUIN_NO, RUIN, START, SELECT])
    t.feed(L("19:12:50.000", "[Notice] <Population Manager Stats> NPCs 0/1000"))
    assert t.snapshot()["transit"] is not None
    t.feed(L("19:12:52.000", "[Notice] <Population Manager Stats> NPCs 0/1000"))
    assert t.snapshot()["transit"] is None


def test_target_kinds_that_are_not_places_get_a_label():
    party = nav("19:16:10.204", "Player Selected Quantum Target - Local", SHIP, "OnPlayerSelectedQuantumTarget", "Player has selected point PartyMemberMarker_900000000002 as their destination, routing locally")
    mission = nav("19:17:10.204", "Player Selected Quantum Target - Local", SHIP, "OnPlayerSelectedQuantumTarget", "Player has selected point MISSION_QT_Quantum_Beacon_900000000004 as their destination, routing locally")
    ring = nav("19:18:10.204", "Player Selected Quantum Target - Local", SHIP, "OnPlayerSelectedQuantumTarget", "Player has selected point glaciemring_TransitPoint_Charlie as their destination, routing locally")
    t = run([JOIN, RUIN_NO, RUIN, party])
    assert t.snapshot()["transit"]["to"] is None and t.snapshot()["transit"]["to_label"] == "a party member"
    t.feed(mission)
    assert t.snapshot()["transit"]["to_label"] == "a mission marker"
    t.feed(ring)
    assert t.snapshot()["transit"]["to"] == "nyx/glaciem-ring" and t.snapshot()["transit"]["to_label"] is None


def test_unknown_landing_area_gives_the_moon_in_its_name_and_a_readable_event():
    t = run([JOIN, OUTPOST_NO, OUTPOST])
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader/daymar" and snap["confidence"] == "near"
    assert snap["event"]["text"] == "Arrived at Outpost PAF Stanton2b Attritus 2"


def test_names_inside_longer_game_names():
    assert PLACES.hint("Stanton2b_ShubinMining_SCD1") == "stanton/crusader/daymar"
    assert PLACES.hint("Outpost_OLP_Stanton2b_Lamina") == "stanton/crusader/daymar"
    assert PLACES.hint("Nyx_TSG_QVExtractionStation_038") == "nyx"
    assert PLACES.hint("AsteroidClusterBase_Nyx_Social_Keeger_004") == "nyx/keeger-belt"
    assert PLACES.hint("OOC Stanton 2c Yela") == "stanton/crusader/yela"       # the screen loses the underscores
    assert PLACES.hint("ObjectContainer-000") is None
    assert PLACES.hint("SolarSystem_926344131032") is None
    assert PLACES.hint("") is None


def test_the_screen_decides_unless_the_log_has_a_spot_inside_what_the_screen_names():
    t = run([JOIN, RUIN_NO, RUIN])
    # The debug text often shows only the planet's zone: the station from the log stays.
    t.screen = {"place_id": "pyro/terminus"}
    snap = t.snapshot()
    assert snap["place_id"] == "pyro/terminus/ruin-station" and snap["source"] == "port" and snap["confidence"] == "exact"
    # The same spot on the screen: confirmed.
    t.screen = {"place_id": "pyro/terminus/ruin-station"}
    snap = t.snapshot()
    assert snap["source"] == "screen" and snap["confidence"] == "exact"
    # Somewhere else entirely: the screen is what the game shows right now.
    t.screen = {"place_id": "stanton/crusader/yela"}
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader/yela" and snap["source"] == "screen" and snap["confidence"] == "near"


def test_the_screen_alone_gives_a_place_when_the_log_has_none():
    t = run([JOIN])
    assert t.snapshot() is None
    t.screen = {"place_id": "stanton/crusader/daymar"}
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader/daymar" and snap["confidence"] == "near" and snap["source"] == "screen"
    t.screen = {"place_id": "not/on/the/list"}
    assert t.snapshot() is None


def test_the_list_of_0_8_1_names_the_new_places_and_never_an_unnamed_or_shared_one():
    from sevenhills_link.location import Places
    p = Places.load()
    assert p.named("Grim HEX") == "stanton/crusader/yela/grim-hex" and p.named("GrimHEX") == "stanton/crusader/yela/grim-hex"
    assert p.named("Scarper's Turn") == "pyro/terminus/scarpers-turn"
    assert p.named("Cave") is None and p.named("Bunker") is None          # unnamed spots are 7Net's only
    assert p.named("Derelict Outpost") is None                            # thirteen places share the name
    assert not any(pid.rsplit("/", 1)[-1].startswith("u-") for pid in p.by_id)
    assert p.named("Ruin Station") == "pyro/terminus/ruin-station"
