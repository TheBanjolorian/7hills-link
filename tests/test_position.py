"""position.py: the debug text → latitude, longitude and height, and the checks that guard it.

The blocks are the lines a real 4.10 screen showed on and over Cellin and over Crusader
on 2026-11-25 (only the lines position.py reads; no session or server names).
"""

import time

import pytest

from sevenhills_link import position
from sevenhills_link.location import Places, Tracker
from sevenhills_link.screen import ScreenReader

PLACES = Places.load()

ON_FOOT = """Zone: OOC_Stanton_2a_Cellin Pos: -102.1047km -72.5157km -228.7069km
Zone: SolarSystem_926655998358 Pos: -18987729.9791km -2708970.2118km -228.7069km
Zone: Root Pos: -18987729.9791km -2708970.2118km -228.7069km
Current player location : Stanton2a
Planet:OOC_Stanton_2a_Cellin  (Load Complete)
Radius: 260000.000000 ElevationUnderCam: 748.671875 Altitude 1.714687
XYPos: -116075.242613 -82437.771268 Page: 5 (-Z)"""

IN_SHIP = """Zone: AEGS_Idris_M_900000000001 Pos: -1.90m -11.21m 21.05m
Zone: OOC_Stanton_2a_Cellin Pos: -209.1607km 353.0190km 85.5262km
Zone: SolarSystem_926655998358 Pos: -18987406.9417km -2708653.7363km 85.5262km
Zone: Root Pos: -18987406.9417km -2708653.7363km 85.5262km
Current player location : Stanton2a
Planet:OOC_Stanton_2a_Cellin (working) (Load Complete)
Radius: 260000.000000 ElevationUnderCam: 783.593750 Altitude 158364.758253
XYPos: -154047.798684 62990.391739 Page: 2 (+Y)"""

OVER_CRUSADER = """Zone: OOC_Stanton_2_Crusader Pos: -2135.36m 2703.84m 10684.4272km
Zone: SolarSystem_926655998358 Pos: -18962172.5763km -2664960.3854km 10684.4272km
Planet:OOC_Stanton_2_Crusader  (Load Complete)
Radius: 7450010.000000 ElevationUnderCam: 5.500000 Altitude 3234412.241793
XYPos: -1488.935917 1885.324695 Page: 4 (+Z)"""

OPEN_SPACE = """Zone: AEGS_Idris_M_900000000001 Pos: -1.91m -11.22m 21.06m
Zone: jumppoint_nyx_castra Pos: 9035.69m 55.2258km -5200.68m
Zone: SolarSystem_926655998363 Pos: -13499926.6148km -23382659.9120km -5200.68m
Current player location : RR_JP_NyxCastra  (LZ : RR_JP_NyxCastra)
No Current Planet"""


def test_on_foot_on_cellin():
    p = position.body_position(ON_FOOT, PLACES)
    assert p["body"] == "stanton/crusader/cellin"
    assert p["lat"] == pytest.approx(-61.296, abs=0.002) and p["lon"] == pytest.approx(-144.617, abs=0.002)
    assert 700 < p["alt"] < 800
    assert p["checked"] == ["distance", "side"]


def test_in_a_ship_the_body_is_the_second_zone_and_the_height_is_the_orbit():
    p = position.body_position(IN_SHIP, PLACES)
    assert p["body"] == "stanton/crusader/cellin"
    assert p["lat"] == pytest.approx(11.77, abs=0.01) and p["lon"] == pytest.approx(120.65, abs=0.01)
    assert p["alt"] == pytest.approx(159148, abs=5)


def test_mixed_units_over_a_planet():
    p = position.body_position(OVER_CRUSADER, PLACES)
    assert p["body"] == "stanton/crusader" and p["lat"] > 89.9 and p["alt"] == pytest.approx(3234418, abs=10)


def test_open_space_gives_no_position():
    assert position.body_position(OPEN_SPACE, PLACES) is None
    assert position.body_position("", PLACES) is None
    assert position.body_position(None, PLACES) is None


def test_no_radius_line_no_position():
    assert position.body_position("\n".join(x for x in ON_FOOT.splitlines() if not x.startswith("Radius")), PLACES) is None


@pytest.mark.parametrize("wrong", [
    ON_FOOT.replace("-102.1047km", "-162.1047km"),     # a digit misread
    ON_FOOT.replace("-102.1047km", "-1021047km"),      # the decimal point lost
    ON_FOOT.replace("-72.5157km -228.7069km\nZone: Solar", "-72.5157km 228.7069km\nZone: Solar"),   # the minus sign of the largest number lost
    ON_FOOT.replace("260000.000000", "280000.000000"),  # the radius misread
    ON_FOOT.replace("-102.1047km -72.5157km", "-102.1047km"),   # a number missing
])
def test_a_misread_number_is_thrown_away(wrong):
    assert position.body_position(wrong, PLACES) is None


def test_reads_what_text_recognition_makes_of_it():
    as_read = ON_FOOT.replace("OOC_Stanton_2a_Cellin Pos", "OOC Stanton 2a Cellin Pos").replace("-102.1047km", "−102.1047krn").replace("-72.5157km -228", "-72. 5157kn -228") \
        .replace("260000.000000", "26øøøø.øøøøøø").replace("Radius:", "Radius;").replace("ElevationUnderCam:", "ElevationUnderCam?")
    p = position.body_position(as_read, PLACES)
    assert p and p["body"] == "stanton/crusader/cellin" and p["lat"] == pytest.approx(-61.296, abs=0.002)


def test_two_positions_apart():
    a = position.body_position(ON_FOOT, PLACES)
    b = position.body_position(ON_FOOT.replace("-102.1047km -72.5157km -228.7069km\nZone: Solar", "-102.0441km -72.4713km -228.7454km\nZone: Solar")
                               .replace("748.671875 Altitude 1.714687", "746.281250 Altitude 1.759458"), PLACES)
    assert b and 60 < position.apart_m(a, b) < 150


def reader(share: bool):
    t = Tracker(PLACES)
    t.share_position = share
    return ScreenReader(t, PLACES), t


def test_a_position_counts_after_two_readings_and_is_sent_only_when_shared():
    r, t = reader(True)
    r.look(ON_FOOT)
    assert t.screen_pos is None                      # one reading is not enough
    r.look(ON_FOOT)
    assert t.screen_pos["body"] == "stanton/crusader/cellin"
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader/cellin"
    assert snap["pos"] == {"body": "stanton/crusader/cellin", "lat": pytest.approx(-61.296, abs=0.002), "lon": pytest.approx(-144.617, abs=0.002), "alt": pytest.approx(750, abs=3),
                           "hdg": None, "r": 260}
    assert set(snap["pos"]) == {"body", "lat", "lon", "alt", "hdg", "r"}     # nothing else leaves the PC
    assert r.last["position"]["checked"] == ["distance", "side"]

    r2, t2 = reader(False)
    r2.look(ON_FOOT); r2.look(ON_FOOT)
    assert t2.screen_pos is not None                 # read, for "Test screen reading"
    assert "pos" not in t2.snapshot()                # but not sent: the setting is off


def test_a_jump_between_two_readings_does_not_count():
    r, t = reader(True)
    r.look(ON_FOOT)
    # The minus sign of a smaller number lost: the distance check cannot see it, the jump can.
    r.look(ON_FOOT.replace("-72.5157km -228.7069km\nZone: Solar", "72.5157km -228.7069km\nZone: Solar"))
    assert t.screen_pos is None
    r.look(ON_FOOT)
    assert t.screen_pos is None                      # the reading before it was the wrong one
    r.look(ON_FOOT)
    assert t.screen_pos is not None


def test_an_old_position_is_not_sent_and_one_on_another_body_neither():
    r, t = reader(True)
    r.look(ON_FOOT); r.look(ON_FOOT)
    t.screen_pos["at"] = time.time() - 60
    assert "pos" not in t.snapshot()
    t.screen_pos["at"] = time.time()
    t.screen = {"place_id": "stanton/crusader/daymar", "at": time.time()}
    assert "pos" not in t.snapshot()


def test_no_debug_block_clears_the_position():
    r, t = reader(True)
    r.look(ON_FOOT); r.look(ON_FOOT)
    r.look("FPS 60")
    assert t.screen_pos is None and "pos" not in (t.snapshot() or {})


def test_the_course_is_the_way_the_member_moves():
    assert position.bearing((0, 0), (1, 0)) == pytest.approx(0)          # towards the north pole
    assert position.bearing((0, 0), (0, 1)) == pytest.approx(90)         # east
    assert position.bearing((10, 20), (9, 20)) == pytest.approx(180)
    assert position.bearing((0, 0), (0, -1)) == pytest.approx(270)
    assert position.ground_m((0, 0), (0, 1), 260000) == pytest.approx(4537.9, abs=1)


def at(lat: float, lon: float) -> str:
    """ON_FOOT with the member moved to this latitude and longitude, at the same height."""
    import math
    r = 260.7503860                     # km from Cellin's middle, as in ON_FOOT
    la, lo = math.radians(lat), math.radians(lon)
    x, y, z = r * math.cos(la) * math.cos(lo), r * math.cos(la) * math.sin(lo), r * math.sin(la)
    return ON_FOOT.replace("-102.1047km -72.5157km -228.7069km\nZone: Solar", f"{x:.4f}km {y:.4f}km {z:.4f}km\nZone: Solar")


def test_a_course_comes_after_twenty_metres_and_stays_while_standing_still():
    r, t = reader(True)
    r.look(at(-61.2958, -144.6173)); r.look(at(-61.2958, -144.6173))
    assert t.snapshot()["pos"]["hdg"] is None and t.snapshot()["pos"]["r"] == 260      # no course yet; the radius in km
    r.look(at(-61.2948, -144.6173))                     # 5 m north: not enough
    assert t.snapshot()["pos"]["hdg"] is None
    r.look(at(-61.2858, -144.6173))                     # 45 m north of where it started
    hdg = t.snapshot()["pos"]["hdg"]
    assert hdg is not None and (hdg <= 3 or hdg >= 357), hdg
    r.look(at(-61.2858, -144.6173))                     # standing still: the course stays
    assert t.snapshot()["pos"]["hdg"] == hdg
    r.look(at(-61.2858, -144.5973))                     # 43 m east
    assert 85 <= t.snapshot()["pos"]["hdg"] <= 95


def test_a_landing_name_with_the_games_own_word_for_the_kind_of_place():
    assert PLACES.outpost("Stanton2a_IndyMiner_TramMyers") == "stanton/crusader/cellin/tram-myers-mining"
    assert PLACES.outpost("Stanton2a_IndyFarmer_GalleteFamily") == "stanton/crusader/cellin/gallete-family-farms"
    assert PLACES.outpost("Stanton2a_Hickes") == "stanton/crusader/cellin/hickes-research-outpost"
    assert PLACES.outpost("Stanton2b_ShubinMining_SCD1") == "stanton/crusader/daymar/shubin-mining-facility-scd-1"
    assert PLACES.outpost("Stanton2a_IndyMiner_Nowhere") is None          # nothing telling left
    assert PLACES.outpost("Stanton2a_Security") is None                   # eight security posts: not one


def test_the_position_on_terminus_from_a_misread_zone_name():
    from sevenhills_link.location import Places
    text = "\n".join(["Zone: pyr06 Pos: -199.4489km 199.1949km -50.5566km",
                      "Zone: SolarSystem 926675998371 Pos: -48118219.6840km 48503407.6580km -50.5566km",
                      "Zone: Root Pos: -48118219.6840km 48503407.6580km -50.5566km",
                      "Radius: 285000.000000 ElevationUnderCam: 1379.906250 Altitude 1.739387",
                      "XYPos: 284636.953127 -72242.190123 Page: 1 (-X)"])
    pos = position.body_position(text, Places.load())
    assert pos and pos["body"] == "pyro/terminus" and pos["checked"] == ["distance", "side"]
    assert abs(pos["lat"] + 10.168) < 0.01 and abs(pos["lon"] - 135.037) < 0.01 and abs(pos["alt"] - 1382) <= 1
