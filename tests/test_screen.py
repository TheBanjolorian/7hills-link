"""screen.py: the text part (what OCR returned → a place). Capture and OCR need Windows."""

from sevenhills_link.location import Places, Tracker
from sevenhills_link.screen import ScreenReader

PLACES = Places.load()


def reader():
    return ScreenReader(Tracker(PLACES), PLACES)


def test_zone_line_names_the_station():
    text = "FPS 58.3\nShard pub_euw1b_13165946_320\nZone: RR_P6_LEO_Interior\nPos 12.1 4.0 -3.2"
    assert reader().place_from_text(text) == "pyro/terminus/ruin-station"


def test_most_precise_place_wins():
    text = "Location: OOC_Stanton_2_Crusader\nZone: OOC_Stanton_2b_Daymar"
    assert reader().place_from_text(text) == "stanton/crusader/daymar"


def test_nothing_known_gives_nothing():
    assert reader().place_from_text("Zone: SomewhereUnknown_123") is None
    assert reader().place_from_text("") is None
    assert reader().place_from_text(None) is None


def test_off_until_full_and_clears_on_off():
    r = reader()
    assert r.status in ("off", "unavailable")
    r.tracker.screen = {"place_id": "pyro/terminus"}
    r.set_enabled(False)
    assert r.tracker.screen is None
