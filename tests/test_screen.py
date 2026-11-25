"""screen.py: the text part (what OCR returned → a place) and the enlarging. Capture and OCR need Windows.

The debug block below is what `r_displayinfo` showed on a real 4.10 screen at GrimHEX
(2560×1440), with the numbers replaced. The two "as read" versions are what an OCR
engine made of that screenshot at its own size and enlarged twice.
"""

import pytest

from sevenhills_link.location import Places, Tracker
from sevenhills_link.screen import ScreenReader, _enlarge, read_debug_text

PLACES = Places.load()

BLOCK = """CamDir:    4    0 -112 FOV: 84 Focal: 0.10 FStop: 64.0
Zone: ObjectContainer-000 Pos: 1.00m -2.00m -3.00m
Zone: OOC_Stanton_2c_Yela Pos: -500.0000km 300.0000km -2000.00m
Zone: SolarSystem_926344131032 Pos: -19000000.0000km -2600000.0000km -2000.00m
Zone: Root Pos: -19000000.0000km -2600000.0000km -2000.00m
FPS 53.2 [51..54], - 18.8ms [18.5ms]
Server FPS 30.0 [29.1..30.7] - 33.3ms [32.5..34.3], Hitches: 0
Current player location : GrimHEX (LZ : GrimHEX)
Planet:OOC_Stanton_2c_Yela (working) (Load Complete)
CamPos Planet Zone: -500000.000000 300000.000000 -2000.000000"""

# The same block as an OCR engine read it at 1:1 (letters confused, underscores lost, a
# compass number of the HUD caught at the start of a line) and enlarged twice.
AS_READ_SMALL = """Zone: ObjectContainer-000 Pos: 1.00m -2.00n_-3.00n
Zone: 00C Stanton 2c Yela Pos: -500.0000kn 300.0000kn -2000.00n
1 60 Zone: Solarsystem 926344131032 Pos: -19000000.0000kn -2600000.0000km -2000.00n
Zone: Root Pos: -19000000.0000km - 2600000. 0000km”*2000.00n
Current player location : GrinHEX (LZ : GrimHEX)
CamPos Planet Zone: -500000. 000000 300000.000000 -2000.000000"""
AS_READ_LARGE = """Zone: ObjectContainer-000 Pos: 1.00m -2.00m -3.00m
60 Zone: OOC Stanton 2c Yela Pos: -500.0000km 300.0000km -2000.00m
| Zone: SolarSystem 926344131032 Pos: -19000000.0000km -2600000.0000km -2000.00m
Zone: Root Pos: -19000000.0000km -2600000,0000km -2000.00m
Current player location : GrimHEX (LZ : GrimHEX)
CamPos Planet Zone: -500000.000000 300000.000000 -2000.000000"""


def reader():
    return ScreenReader(Tracker(PLACES), PLACES)


def block(*lines: str) -> str:
    """A debug block around the given lines (two zone lines make it one)."""
    return "\n".join(["Zone: ObjectContainer-000 Pos: 1.00m 2.00m 3.00m", *lines, "Zone: Root Pos: 1.0km 2.0km 3.0km"])


def test_the_real_block_gives_the_moon_because_grimhex_is_not_on_the_list():
    seen = read_debug_text(BLOCK)
    assert seen["block"] is True
    assert seen["zones"] == ["ObjectContainer-000", "OOC_Stanton_2c_Yela", "SolarSystem_926344131032", "Root"]
    assert seen["location"] == "GrimHEX" and seen["lz"] == "GrimHEX"
    assert reader().place_from_text(BLOCK) == "stanton/crusader/yela"


def test_what_ocr_makes_of_it_still_gives_the_moon():
    assert reader().place_from_text(AS_READ_LARGE) == "stanton/crusader/yela"
    assert reader().place_from_text(AS_READ_SMALL) == "stanton/crusader/yela"
    assert len(read_debug_text(AS_READ_SMALL)["zones"]) == 4       # "CamPos Planet Zone:" is not a zone line


def test_only_the_debug_block_counts():
    r = reader()
    # A mission text or a notice in the top-right corner, with no debug text on screen.
    for text in ("New Objective: Go to location: Lorville",
                 "Deliver the package\nLocation: Area18 Riker Memorial Spaceport",
                 "Entering Armistice Zone - Combat Prohibited",
                 "Current player location : Lorville (LZ : Lorville)",          # a lone line is not the block
                 "Zone: OOC_Stanton_2b_Daymar Pos: 1.0km 2.0km 3.0km",          # one zone line is not the block
                 "FPS 58.3\nShard pub_euw1b_13165946_320\nServer FPS 30.0"):
        assert r.place_from_text(text) is None, text
        r.look(text)
        assert r.status == "no_text"


def test_the_location_line_names_the_landing_area_also_with_two_words():
    r = reader()
    assert r.place_from_text(block("Zone: pyro6 Pos: 1.0km 2.0km 3.0km", "Current player location : Ruin Station (LZ : Ruin Station)")) == "pyro/terminus/ruin-station"
    assert r.place_from_text(block("Zone: OOC_Stanton_4_Microtech Pos: 1.0km 2.0km 3.0km", "Current player location : New Babbage (LZ : New Babbage)")) == "stanton/microtech/new-babbage"
    assert r.place_from_text(block("Zone: OOC_Stanton_1_Hurston Pos: 1.0km 2.0km 3.0km", "Current player location : Lorville (LZ : Lorville)")) == "stanton/hurston/lorville"
    # The landing zone's own name when the first one is misread.
    assert r.place_from_text(block("Zone: OOC_Stanton_1_Hurston Pos: 1.0km 2.0km 3.0km", "Current player location : Lorvi11e (LZ : Lorville)")) == "stanton/hurston/lorville"


def test_a_landing_area_that_contradicts_the_zones_is_not_believed():
    # Zones say Yela; a misread location line that happens to match a city on Hurston loses.
    text = block("Zone: OOC_Stanton_2c_Yela Pos: 1.0km 2.0km 3.0km", "Current player location : Lorville (LZ : Lorville)")
    assert reader().place_from_text(text) == "stanton/crusader/yela"


def test_open_space_names_no_place():
    text = "Zone: SolarSystem_926344131032 Pos: 1.0km 2.0km 3.0km\nZone: Root Pos: 1.0km 2.0km 3.0km"
    assert read_debug_text(text)["block"] is True
    assert reader().place_from_text(text) is None
    assert reader().place_from_text("") is None
    assert reader().place_from_text(None) is None


def test_a_place_counts_after_two_readings_that_agree():
    r = reader()
    daymar = block("Zone: OOC_Stanton_2b_Daymar Pos: 1.0km 2.0km 3.0km")
    r.look(daymar)
    assert r.status == "reading" and r.tracker.screen is None
    r.look(daymar)
    assert r.tracker.screen["place_id"] == "stanton/crusader/daymar"
    # One odd reading does not move you ...
    r.look(BLOCK)
    assert r.tracker.screen["place_id"] == "stanton/crusader/daymar"
    # ... a second one does.
    r.look(BLOCK)
    assert r.tracker.screen["place_id"] == "stanton/crusader/yela"


def test_the_old_place_goes_when_the_block_stops_naming_one():
    r = reader()
    daymar = block("Zone: OOC_Stanton_2b_Daymar Pos: 1.0km 2.0km 3.0km")
    r.look(daymar)
    r.look(daymar)
    space = "Zone: SolarSystem_926344131032 Pos: 1.0km 2.0km 3.0km\nZone: Root Pos: 1.0km 2.0km 3.0km"
    r.look(space)
    assert r.tracker.screen is not None          # once could be a bad reading
    r.look(space)
    assert r.tracker.screen is None and r.status == "reading"
    # And at once when the debug text is switched off.
    r.look(daymar)
    r.look(daymar)
    r.look("no debug text here")
    assert r.tracker.screen is None and r.status == "no_text"


def test_the_last_look_is_kept_for_the_window_without_positions():
    r = reader()
    r.look(BLOCK, size=(2304, 1152), scale=2)
    rep = r.report()
    assert rep["status"] == "reading"
    last = rep["last"]
    assert last["block"] is True and last["size"] == [2304, 1152] and last["scale"] == 2
    assert last["zones"][1] == "OOC_Stanton_2c_Yela" and last["location"] == "GrimHEX"
    assert last["place"] == "stanton/crusader/yela" and last["place_name"] == "Yela"
    assert isinstance(last["ago"], int) and "at" not in last
    assert "km" not in str(last) and "500.0000" not in str(last)      # zone names only, never where in the zone


def test_a_failed_look_is_shown_and_logged_once(caplog):
    r = reader()
    r.set_enabled(True)
    with caplog.at_level("WARNING", logger="7hillslink"):
        r._fail("capturing the screen", OSError("screen locked"))
        r._fail("capturing the screen", OSError("screen locked"))
    assert r.status == "error" and "screen locked" in r.error
    assert r.report()["last"]["error"] == r.error
    assert len([x for x in caplog.records if "screen reading failed" in x.getMessage()]) == 1


def test_off_until_full_and_clears_on_off():
    r = reader()
    assert r.status in ("off", "unavailable")
    r.tracker.screen = {"place_id": "pyro/terminus"}
    r.set_enabled(False)
    assert r.tracker.screen is None


def test_enlarging_keeps_the_picture_and_the_byte_order():
    pytest.importorskip("PIL")
    # 2×1 pixels, BGRA: a blue one and a red one.
    pixels = bytes([255, 0, 0, 0, 0, 0, 255, 0])
    out, w, h, scale = _enlarge(pixels, 2, 1, 10000)
    assert (w, h, scale) == (4, 2, 2) and len(out) == 4 * 2 * 4
    assert out[0] > 200 and out[2] < 60            # left edge still blue (B first)
    assert out[(w - 1) * 4 + 2] > 200 and out[(w - 1) * 4] < 60    # right edge still red
    # Too large for the OCR: left as it is.
    assert _enlarge(pixels, 2, 1, 3) == (pixels, 2, 1, 1)


# ---------------------------------------------------------------- 7HillsLink.exe --screen-test

def _screen_test(monkeypatch, tmp_path, picture, text=BLOCK, engine=True):
    """check_screenshot with the two Windows calls replaced; returns (exit code, the JSON it wrote)."""
    import json
    from sevenhills_link import screen

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    seen = {}

    class Engine:
        max_image_dimension = 10000

    def engine_or_not():
        if not engine:
            raise RuntimeError("no OCR language installed")
        return Engine()

    async def recognize(_engine, pixels, w, h):
        seen["bytes"], seen["size"] = len(pixels), (w, h)
        return text

    monkeypatch.setattr(screen, "_ocr_engine", engine_or_not)
    monkeypatch.setattr(screen, "_language_of", lambda e: "en-US")
    monkeypatch.setattr(screen, "_recognize", recognize)
    code = screen.check_screenshot(picture)
    out = json.loads((tmp_path / "7HillsLink" / "screen-test.json").read_text(encoding="utf-8"))
    return code, out, seen


def _picture(tmp_path, size=(2000, 1000)):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "shot.png"
    Image.new("RGB", size, (10, 10, 10)).save(path)
    return str(path)


def test_screen_test_reads_a_saved_screenshot_the_way_the_client_reads_the_screen(monkeypatch, tmp_path, capsys):
    code, out, seen = _screen_test(monkeypatch, tmp_path, _picture(tmp_path))
    assert code == 0 and out["ok"] is True and out["language"] == "en-US"
    # The top-right corner (45 % × 40 % of the picture), enlarged twice, four bytes a pixel.
    assert seen["size"] == (1800, 800) and seen["bytes"] == 1800 * 800 * 4
    assert out["size"] == [1800, 800] and out["scale"] == 2
    assert out["block"] is True and out["place"] == "stanton/crusader/yela" and out["place_name"] == "Yela"
    assert out["confidence"] == "near"                  # a moon, not the station: never "exact"
    assert '"place": "stanton/crusader/yela"' in capsys.readouterr().out


def test_screen_test_writes_down_no_position(monkeypatch, tmp_path):
    _, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path))
    assert any("OOC_Stanton_2c_Yela" in line for line in out["read"])      # the words are kept
    assert "500.0000" not in str(out) and "19000000" not in str(out) and "2000.00" not in str(out)


def test_screen_test_says_when_the_debug_text_is_not_there(monkeypatch, tmp_path):
    code, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path), text="Lorville\nlocation: Area18")
    assert code == 0 and out["ok"] is True and out["block"] is False and out["place"] is None and out["confidence"] is None


def test_screen_test_exit_codes(monkeypatch, tmp_path):
    code, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path), engine=False)
    assert code == 3 and out["ok"] is False and "no OCR language installed" in out["error"]
    code, out, _ = _screen_test(monkeypatch, tmp_path, str(tmp_path / "missing.png"))
    assert code == 2 and "could not open the picture" in out["error"]


def test_the_drawn_test_screenshot_has_the_block_in_the_corner_the_client_reads(tmp_path):
    """tools/make_debug_screenshot.py is what the build reads with Windows OCR: the block must
    lie inside the corner screen.py looks at, at every size it is drawn in."""
    pytest.importorskip("PIL")
    import importlib.util
    from pathlib import Path
    from sevenhills_link.screen import CORNER

    spec = importlib.util.spec_from_file_location("make_debug_screenshot", Path(__file__).parent.parent / "tools" / "make_debug_screenshot.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert read_debug_text("\n".join(text for text, _ in tool.BLOCK))["block"] is True
    for size in ((2560, 1440), (1920, 1080)):
        img = tool.draw(*size)
        w, h = img.size
        text_colours = set(tool.COLOURS.values())
        xs, ys = [], []
        px = img.load()
        for y in range(0, h):
            for x in range(0, w):
                if px[x, y] in text_colours:
                    xs.append(x)
                    ys.append(y)
        assert xs, "no text was drawn"
        assert min(xs) >= w * CORNER[0] and max(ys) <= h * CORNER[3], (size, min(xs), max(ys))
