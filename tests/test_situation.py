"""Telemetry frame → what the player is doing, and the line shown with the place."""

from sevenhills_link.situation import Steady, altitude_of, describe, state_of

FLT_MAX = 3.4028234663852886e38


def frame(loco: str, ship: bool = False, landed: bool = False, altitude: float | None = FLT_MAX) -> dict:
    f: dict = {"actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_" + loco}}}
    if ship:
        f["vehicle"] = {"state": {"class_name": "AEGS_Sabre_Firebird",
                                  "flight": {"state": {"is_landed": landed}, "instruments": {"altitude": altitude}}}}
    return f


def test_seated_in_a_ship():
    assert state_of(frame("SEATED", ship=True, landed=True, altitude=0.4)) == "landed"
    assert state_of(frame("SEATED", ship=True, altitude=940.2)) == "flying"
    assert state_of(frame("SEATED", ship=True, altitude=FLT_MAX)) == "space"
    assert state_of(frame("SEATED", ship=True, altitude=None)) == "space"


def test_on_foot_and_eva():
    assert state_of(frame("ON_FOOT")) == "on_foot"
    assert state_of(frame("EVA")) == "eva"


def test_nothing_useful():
    assert state_of(None) is None
    assert state_of({}) is None
    assert state_of(frame("UNSPECIFIED")) is None
    # Seated but the game sent no ship: not flying, not on foot.
    assert state_of(frame("SEATED")) is None


def test_altitude_only_near_a_body():
    assert altitude_of(frame("SEATED", ship=True, altitude=940.2)) == 940.2
    assert altitude_of(frame("SEATED", ship=True, altitude=FLT_MAX)) is None
    assert altitude_of(frame("ON_FOOT")) is None
    assert altitude_of(frame("SEATED", ship=True, altitude=float("nan"))) is None


def test_a_new_state_has_to_hold():
    s = Steady(hold=2.0)
    assert s.feed("landed", 0.0) == "landed"          # the first one counts at once
    assert s.feed("flying", 1.0) == "landed"          # the game flaps while a ship settles
    assert s.feed("landed", 1.5) == "landed"
    assert s.feed("flying", 2.0) == "landed"
    assert s.feed("flying", 3.9) == "landed"
    assert s.feed("flying", 4.0) == "flying"          # held for 2 s
    assert s.feed(None, 5.0) == "flying"              # a frame that says nothing does not clear it at once
    assert s.feed(None, 7.0) is None
    s.reset()
    assert s.state is None


def test_the_balance_never_leaves_the_pc():
    from sevenhills_link.core import without_uec
    f = {"actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_ON_FOOT", "uec_balance": 123456}, "vitals": {"heart_rate": 60}}}
    out = without_uec(f)
    assert "uec_balance" not in out["actor"]["state"]
    assert out["actor"]["state"]["locomotion"] == "ACTOR_LOCOMOTION_STATE_ON_FOOT" and out["actor"]["vitals"] == {"heart_rate": 60}
    assert f["actor"]["state"]["uec_balance"] == 123456      # the game's frame is left as it was
    assert without_uec(None) is None and without_uec({"vehicle": {}}) == {"vehicle": {}}


def test_one_line_with_the_place():
    assert describe("landed", "near", "Cellin") == "Landed at Cellin"
    assert describe("flying", "near", "Cellin", 940.2) == "Flying at Cellin, 940 m above the ground"
    assert describe("flying", "near", "Cellin", 12400) == "Flying at Cellin, 12.4 km above the ground"
    assert describe("space", "near", "Cellin") == "In space near Cellin"
    assert describe("space", "area", "Crusader") == "In space in the Crusader area"
    assert describe("on_foot", "exact", "Orison") == "On foot at Orison"
    assert describe("on_foot", "near", "Cellin") == "On foot on or near Cellin"
    assert describe("eva", "near", "Cellin") == "On EVA near Cellin"
    assert describe(None, "near", "Cellin") is None
    assert describe("landed", "near", None) is None
