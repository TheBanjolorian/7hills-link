"""v0.7: landing area by name, quantum travel, jurisdiction and the newest event.

Lines are copied from real 4.10 LIVE sessions (build 13220821, Nov 2026).
"""

from sevenhills_link.location import Places, Tracker

PLACES = Places.load()


def L(t: str, rest: str) -> str:
    return f"<2026-11-21T{t}Z> {rest}"


LOGIN = L("18:55:00.560", "[Notice] <Legacy login response> [CIG-net] User Login Success - Handle[TheBanjolorian] - Time[179212726] [Team_GameServices][Login]")
JOIN = L("18:56:05.455", "[Notice] <Join PU> address[34.62.232.110] port[64366] shard[pub_euw1b_13165946_320] locationId[-281470681677823] [GIM][Matchmaking]")
LAND_NO = L("18:56:30.040", "[Notice] <Update Inventory Location> Player [TheBanjolorian] is changing location. Landing [0] -> [3184339241]. Location [0] -> [3184339241]. Pending [0] [Inventory]")
LAND_RUIN = L("18:56:30.046", "[Notice] <RequestLocationInventory> Player[TheBanjolorian] requested inventory for Location[RR_P6_LEO] [Team_CoreGameplayFeatures][Inventory]")
SELECT = L("18:57:51.414", "[Notice] <Player Selected Quantum Target - Local> [ItemNavigation][CL][37688] | NOT AUTH | AEGS_Idris_M_944224401504[944224401504]|CSCItemNavigation::OnPlayerSelectedQuantumTarget|Player has selected point rs_ext_pyro-stan_jp1 as their destination, routing locally [Team_CGP4][QuantumTravel]")
START = L("18:57:51.414", "[Notice] <Calculate Route> [ItemNavigation][CL][37688] | NOT AUTH | AEGS_Idris_M_944224401504[944224401504]|CSCItemNavigation::CalculateRoute|Projected Start Location is Ruin Station for route to destination rs_ext_pyro-stan_jp1 [Team_CGP4][QuantumTravel]")
CAL_ME = L("18:58:00.000", '[Notice] <SHUDEvent_OnNotification> Added notification "Quantum Travel Calibration Started By TheBanjolorian: " [4] to queue. New queue size: 1 [Team_CoreGameplayFeatures][Missions][Comms]')
CAL_DONE = L("18:58:06.000", '[Notice] <SHUDEvent_OnNotification> Added notification "Quantum Travel Calibration Complete By TheBanjolorian: " [5] to queue. New queue size: 1 [Team_CoreGameplayFeatures][Missions][Comms]')
CAL_OTHER = L("18:58:00.000", '[Notice] <SHUDEvent_OnNotification> Added notification "Quantum Travel Calibration Started By Echoo3: " [4] to queue. New queue size: 1 [Team_CoreGameplayFeatures][Missions][Comms]')
ARRIVED = L("19:02:51.906", "[Notice] <Quantum Drive Arrived - Arrived at Final Destination> [ItemNavigation][CL][29076] | NOT AUTH | AEGS_Idris_M_944224401504[944224401504]|CSCItemNavigation::OnQuantumDriveArrived|Quantum Drive has arrived at final destination [Team_CGP4][QuantumTravel]")
UEE = L("19:02:50.009", '[Notice] <SHUDEvent_OnNotification> Added notification "Entered UEE Jurisdiction: " [3] to queue. New queue size: 2 [Team_CoreGameplayFeatures][Missions][Comms]')
GATE_NO = L("19:02:53.669", "[Notice] <Update Inventory Location> Player [TheBanjolorian] is changing location. Landing [0] -> [639835600]. Location [3273347588] -> [639835600]. Pending [0] [Inventory]")
GATE = L("19:02:53.672", "[Notice] <RequestLocationInventory> Player[TheBanjolorian] requested inventory for Location[RR_JP_PyroStanton] [Inventory]")
QT_MIC = L("21:10:07.589", "[Notice] <Player Selected Quantum Target - Local> [ItemNavigation][CL][38248] | NOT AUTH | AEGS_Idris_M_944224401504[944224401504]|CSCItemNavigation::OnPlayerSelectedQuantumTarget|Player has selected point OOC_Stanton_4_Microtech as their destination, routing locally [Team_CGP4][QuantumTravel]")
QT_MIC_START = L("21:10:07.589", "[Notice] <Calculate Route> [ItemNavigation][CL][38248] | NOT AUTH | AEGS_Idris_M_944224401504[944224401504]|CSCItemNavigation::CalculateRoute|Projected Start Location is Daymar for route to destination OOC_Stanton_4_Microtech [Team_CGP4][QuantumTravel]")
OUTPOST = L("22:12:04.473", "[Notice] <RequestLocationInventory> Player[TheBanjolorian] requested inventory for Location[Outpost_PAF_Stanton2b_Attritus_2] [Team_CoreGameplayFeatures][Inventory]")


def run(lines):
    t = Tracker(PLACES)
    for line in lines:
        t.feed(line)
    return t


def test_landing_area_name_puts_you_at_the_station_without_an_atc_hint():
    snap = run([LOGIN, JOIN, LAND_NO, LAND_RUIN]).snapshot()
    assert snap["place_id"] == "pyro/terminus/ruin-station"
    assert snap["confidence"] == "exact" and snap["source"] == "port"
    assert snap["event"]["text"] == "Landed at Ruin Station"


def test_gateway_station_names_map_to_the_jump_point_of_that_system():
    assert PLACES.named("RR_JP_PyroStanton") == "pyro/jump-stanton"
    assert PLACES.named("RR_JP_StantonPyro") == "stanton/jump-pyro"
    assert PLACES.named("RR_JP_NyxCastra") == "nyx/jump-castra"
    assert PLACES.named("rs_ext_pyro-stan_jp1") == "pyro/jump-stanton"
    assert PLACES.named("rs_ext_nyx-pyro_jp1") == "nyx/jump-pyro"
    assert PLACES.named("Stanton System") == "stanton"
    assert PLACES.named("Daymar") == "stanton/crusader/daymar"
    assert PLACES.named("OOC_Stanton_4_Microtech") == "stanton/microtech"


def test_selecting_a_target_alone_is_not_travel():
    snap = run([LOGIN, JOIN, LAND_NO, LAND_RUIN, SELECT, START]).snapshot()
    assert snap["transit"] is None


def test_own_calibration_starts_the_trip_and_arrival_ends_it():
    t = run([LOGIN, JOIN, LAND_NO, LAND_RUIN, SELECT, START, CAL_ME])
    tr = t.snapshot()["transit"]
    assert tr == {"from": "pyro/terminus/ruin-station", "to": "pyro/jump-stanton", "to_label": None,
                  "state": "spool", "since": "2026-11-21T18:58:00Z"}
    assert t.snapshot()["event"]["text"] == "Quantum calibrating to Stanton Gateway"
    t.feed(CAL_DONE)
    assert t.snapshot()["transit"]["state"] == "travel"
    for line in (UEE, ARRIVED, GATE_NO, GATE):
        t.feed(line)
    snap = t.snapshot()
    assert snap["transit"] is None
    assert snap["place_id"] == "pyro/jump-stanton"
    assert snap["jurisdiction"] == "UEE"
    assert snap["event"]["text"] == "Landed at Stanton Gateway"


def test_the_pilots_calibration_moves_the_passengers_too():
    t = run([LOGIN, JOIN, LAND_NO, LAND_RUIN, SELECT, START, CAL_OTHER])
    assert t.snapshot()["transit"]["state"] == "spool"
    assert t.snapshot()["event"]["text"] == "Quantum calibrating to Stanton Gateway (pilot Echoo3)"


def test_calibration_without_a_target_line_is_travel_to_somewhere():
    t = run([LOGIN, JOIN, LAND_NO, LAND_RUIN, CAL_OTHER])
    tr = t.snapshot()["transit"]
    assert tr["state"] == "spool" and tr["to"] is None and tr["from"] == "pyro/terminus/ruin-station"


def test_start_location_from_the_route_line():
    t = run([LOGIN, JOIN, LAND_NO, LAND_RUIN, QT_MIC, QT_MIC_START,
             L("21:10:09.000", '[Notice] <SHUDEvent_OnNotification> Added notification "Quantum Travel Calibration Started By TheBanjolorian: " [4] to queue.')])
    tr = t.snapshot()["transit"]
    assert tr["from"] == "stanton/crusader/daymar" and tr["to"] == "stanton/microtech"


def test_unknown_landing_area_keeps_a_readable_event():
    t = run([LOGIN, JOIN, OUTPOST])
    assert t.snapshot() is None or t.snapshot()["place_id"] != ""
    assert t.event[1] == "Landed at Outpost PAF Stanton2b Attritus 2"


def test_screen_place_wins_over_the_log():
    t = run([LOGIN, JOIN, LAND_NO, LAND_RUIN])
    t.screen = {"place_id": "pyro/terminus"}
    snap = t.snapshot()
    assert snap["place_id"] == "pyro/terminus" and snap["source"] == "screen"
