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


# What Windows' own OCR made of the first drawn test picture in the build (a face with a
# slashed zero, enlarged twice): zeros as "ø", "Yela" as "YeIa", and three zone lines broken
# in two, one of them with "Zone:" left on a line of its own.
AS_READ_WINDOWS = """Zone:
CamDir:
4
Ø -112 FOV: 84 Focal: ø.lø FStop: 64.Ø
Zone: ObjectContainer-øøø Pos: I.ØØm -2.ØØm -3.00m
Zone: OOC_Stanton_2c_YeIa Pos. -
• søø.øøøøkm 3øø.øøøøkm -2ØØØ.ØØm
SolarSystem_926344131Ø32 Pos: -19øøøøøø.øøøøkm -26øøøøø.øøøøkm -2ØØØ.ØØm
Zone: Root Pos. -
• 19øøøøøø.øøøøkm -26øøøøø.øøøøkm -2ØØØ.ØØm
Graphics Renderer : Vulkan (FSR AA)
Current player location : GrimHEX (LZ : GrimHEX)
Planet:OOC_Stanton_2c_Ye1a (working) (Load Complete)
Cam os Planet Zone.
• -søøøøø.øøøøøø 3øøøøø.øøøøøø -2øøø.øøøøøø"""


def test_what_windows_ocr_made_of_it_gives_the_moon_too():
    seen = read_debug_text(AS_READ_WINDOWS)
    # The line that lost its "Zone:" still counts; the lone "Zone:" and "Planet Zone." do not.
    assert seen["zones"] == ["ObjectContainer-øøø", "OOC_Stanton_2c_YeIa", "SolarSystem_926344131Ø32", "Root"]
    assert seen["location"] == "GrimHEX"
    assert reader().place_from_text(AS_READ_WINDOWS) == "stanton/crusader/yela"       # by "Stanton 2c", whatever became of the name


def test_a_zone_line_broken_in_two_still_counts_once():
    assert read_debug_text("Zone: OOC_Stanton_2b_Daymar\nPos: 1.0km 2.0km 3.0km\nZone:\nRoot Pos: 1.0km 2.0km 3.0km")["zones"] == ["OOC_Stanton_2b_Daymar", "Root"]
    # Not zone lines: a word before "Pos" that is no zone name, and "Zone:" followed by numbers.
    assert read_debug_text("Camera Pos: 1 2 3\nZone: 12.5 13.5\nSomething Zone: here and there")["zones"] == []


def test_the_bracket_before_lz_may_be_misread():
    for line in ("Current player location : Lorville  (LZ : Lorville)", "Current player location : Lorville [LZ : Lorville)",
                 "Current player location : Lorville {LZ ; Lorville}", "Current player l0cation: Lorville (LZ: Lorville"):
        seen = read_debug_text(block(line))
        assert (seen["location"], seen["lz"]) == ("Lorville", "Lorville"), line


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
    assert _enlarge(pixels, 2, 1, 3, scale=2, prep="none") == (pixels, 2, 1, 1)
    # Three times does not fit but twice does.
    assert _enlarge(pixels, 2, 1, 5, scale=3, prep="none")[1:] == (4, 2, 2)


def test_the_corner_that_is_read_is_never_smaller_than_the_block():
    from sevenhills_link.screen import _corner_box
    assert _corner_box(0, 0, 2560, 1440) == (1408, 0, 2560, 576)            # 45 % × 40 % of the window
    assert _corner_box(100, 50, 2020, 1130) == (1156, 50, 2020, 482)        # a 1920 × 1080 window that is not at 0, 0
    assert _corner_box(0, 0, 1280, 720) == (560, 0, 1280, 380)              # small window: the text is as large, so 720 × 380
    assert _corner_box(0, 0, 600, 300) == (0, 0, 600, 300)                  # never outside the window


def test_soft_makes_bright_text_white_on_black_whatever_its_colour():
    pytest.importorskip("PIL")
    # BGRX: yellow text, orange text, a dim blue wall, a dark wall, white text, a mid-grey edge.
    px = lambda r, g, b: bytes([b, g, r, 0])
    pixels = px(232, 214, 96) + px(236, 150, 60) + px(20, 40, 85) + px(12, 12, 12) + px(235, 235, 235) + px(140, 140, 140)
    out, w, h, scale = _enlarge(pixels, 6, 1, 10000, scale=1, prep="soft")
    assert (w, h, scale) == (6, 1, 1)
    grey = [out[i * 4] for i in range(6)]
    assert all(out[i * 4] == out[i * 4 + 1] == out[i * 4 + 2] for i in range(6))      # no colour left
    assert grey[0] == grey[1] == grey[4] == 255 and grey[2] == grey[3] == 0 and 100 < grey[5] < 160
    inv, *_ = _enlarge(pixels, 6, 1, 10000, scale=1, prep="soft_inv")
    assert [inv[i * 4] for i in range(6)] == [255 - v for v in grey]
    # Enlarged too: the size follows, and the text end is still the bright one.
    big, w, h, scale = _enlarge(pixels, 6, 1, 10000, scale=3, prep="soft")
    assert (w, h, scale) == (18, 3, 3) and big[0] == 255 and big[10 * 4] == 0


# ---------------------------------------------------------------- 7HillsLink.exe --screen-test

def _screen_test(monkeypatch, tmp_path, picture, text=BLOCK, engine=True):
    """check_screenshot with the two Windows calls replaced; returns (exit code, the JSON it wrote, the reads)."""
    import json
    from sevenhills_link import screen

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    seen = []

    class Engine:
        max_image_dimension = 10000

    def engine_or_not():
        if not engine:
            raise RuntimeError("no OCR language installed")
        return Engine()

    async def recognize(_engine, pixels, w, h):
        seen.append({"bytes": len(pixels), "size": (w, h)})
        return text(len(seen)) if callable(text) else text

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
    from sevenhills_link import screen
    code, out, seen = _screen_test(monkeypatch, tmp_path, _picture(tmp_path))
    assert code == 0 and out["ok"] is True and out["language"] == "en-US"
    # First the client's own way: the top-right corner (45 % × 40 % of the picture), enlarged, four bytes a pixel.
    k = screen.SCALE
    assert seen[0]["size"] == (900 * k, 400 * k) and seen[0]["bytes"] == 900 * k * 400 * k * 4
    assert out["size"] == [900 * k, 400 * k] and out["scale"] == k and out["prepared"] == screen.PREP and isinstance(out["ms"], int)
    assert out["block"] is True and out["place"] == "stanton/crusader/yela" and out["place_name"] == "Yela"
    assert out["confidence"] == "near"                  # a moon, not the station: never "exact"
    assert '"place": "stanton/crusader/yela"' in capsys.readouterr().out
    # Then every other way to prepare the corner, each read once and judged the same way.
    assert [(t["scale"], t["prepared"]) for t in out["tried"]] == screen.VARIANTS and len(seen) == 1 + len(screen.VARIANTS)
    assert {s["size"] for s in seen[1:]} == {(900, 400), (1800, 800), (2700, 1200)}
    assert all(t["place"] == "stanton/crusader/yela" and t["location"] == "GrimHEX" and len(t["zones"]) == 4 for t in out["tried"])


def test_screen_test_shows_which_way_reads_best(monkeypatch, tmp_path):
    from sevenhills_link import screen
    # The OCR finds the block only in the last three reads (enlarged three times).
    n = 1 + len(screen.VARIANTS)
    code, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path), text=lambda i: BLOCK if i > n - 3 else "Zcne: nothing readable")
    assert code == 0 and out["block"] is False and out["place"] is None
    assert [t["place"] for t in out["tried"]] == [None] * 6 + ["stanton/crusader/yela"] * 3


def test_screen_test_skips_the_sizes_the_ocr_does_not_take(monkeypatch, tmp_path):
    from sevenhills_link import screen
    code, out, seen = _screen_test(monkeypatch, tmp_path, _picture(tmp_path, size=(8000, 5000)))     # corner 3600 × 2000
    assert code == 0 and {t["scale"] for t in out["tried"]} == {1, 2}
    assert max(s["size"][0] for s in seen) == 7200


def test_screen_test_writes_down_no_position_session_or_server(monkeypatch, tmp_path):
    full = BLOCK + "\nSession: 12345678-abcd-ef01-2345-6789abcdef01\nShardId: pub_euw1b_13165946_020\nServer: pub-euw1b-sc-alpha-4100-game-128, restarts 0"
    _, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path), text=full)
    assert any("OOC_Stanton_2c_Yela" in line for line in out["read"])      # the words are kept
    assert any("GrimHEX" in line for line in out["read"])
    text = str(out)
    assert "500.0000" not in text and "19000000" not in text and "2000.00" not in text and "500000" not in text
    assert "12345678" not in text and "pub_euw1b" not in text and "sc-alpha" not in text
    assert out["other_lines"] >= 5                      # counted, not kept


def test_numbers_are_taken_out_also_when_the_ocr_garbled_them():
    from sevenhills_link.screen import _no_numbers, _place_lines
    assert _no_numbers("Zone: OOC_Stanton_2c_Yela Pos: -568.6817km 383.6074km -2089.02m") == "Zone: OOC_Stanton_2c_Yela Pos: # # #"
    assert _no_numbers("Zone: OOC Stanton 2c YeIa Pos. -") == "Zone: OOC Stanton 2c YeIa Pos. -"
    assert _no_numbers("SolarSystem_926344131Ø32 Pos: -19øøøøøø.øøøøkm -26øøøøø.øøøøkm -2ØØØ.ØØm") == "SolarSystem_#Ø32 Pos: # # #"
    assert _no_numbers("Zone: ObjectContainer-øøø Pos: I.ØØm -2.ØØm -3.00m") == "Zone: ObjectContainer-øøø Pos: # # #"
    assert _no_numbers("CamPos Planet Zone: -568681.742251 383607 - 2089. 024816") == "CamPos Planet Zone: # # - # #"
    kept, others = _place_lines(AS_READ_WINDOWS)
    assert others == 7 and not any("km" in line for line in kept)      # the broken-off halves with the positions are not kept
    assert "Current player location : GrimHEX (LZ : GrimHEX)" in kept


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
