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


def test_the_real_block_gives_grim_hex_now_that_it_is_on_the_list():
    seen = read_debug_text(BLOCK)
    assert seen["block"] is True
    assert seen["zones"] == ["ObjectContainer-000", "OOC_Stanton_2c_Yela", "SolarSystem_926344131032", "Root"]
    assert seen["location"] == "GrimHEX" and seen["lz"] == "GrimHEX"
    assert reader().place_from_text(BLOCK) == "stanton/crusader/yela/grim-hex"


def test_what_ocr_makes_of_it_still_gives_the_station():
    assert reader().place_from_text(AS_READ_LARGE) == "stanton/crusader/yela/grim-hex"
    assert reader().place_from_text(AS_READ_SMALL) == "stanton/crusader/yela/grim-hex"
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


def test_what_windows_ocr_made_of_it_gives_the_station_too():
    seen = read_debug_text(AS_READ_WINDOWS)
    # The line that lost its "Zone:" still counts; the lone "Zone:" and "Planet Zone." do not.
    assert seen["zones"] == ["ObjectContainer-øøø", "OOC_Stanton_2c_YeIa", "SolarSystem_926344131Ø32", "Root"]
    assert seen["location"] == "GrimHEX"
    assert reader().place_from_text(AS_READ_WINDOWS) == "stanton/crusader/yela/grim-hex"       # Yela by "Stanton 2c", whatever became of its name; the station by the location line


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
    assert r.tracker.screen["place_id"] == "stanton/crusader/yela/grim-hex"


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
    assert last["place"] == "stanton/crusader/yela/grim-hex" and last["place_name"] == "Grim HEX"
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


def test_the_box_that_is_read_and_the_wider_corner():
    from sevenhills_link.screen import _box
    # The box: 760 × 420 px in the top-right corner, whatever the size of the window.
    assert _box(0, 0, 2560, 1440) == (1800, 0, 2560, 420)
    assert _box(100, 50, 2020, 1130) == (1260, 50, 2020, 470)               # a 1920 × 1080 window that is not at 0, 0
    assert _box(0, 0, 3840, 2160) == (3080, 0, 3840, 420)
    assert _box(0, 0, 600, 300) == (0, 0, 600, 300)                         # never outside the window
    # The wider corner: 45 % × 40 % of the window, and never less than the box.
    assert _box(0, 0, 2560, 1440, "corner") == (1408, 0, 2560, 576)
    assert _box(100, 50, 2020, 1130, "corner") == (1156, 50, 2020, 482)
    assert _box(0, 0, 1280, 720, "corner") == (520, 0, 1280, 420)
    assert _box(0, 0, 600, 300, "corner") == (0, 0, 600, 300)


def test_lines_are_put_together_from_where_the_words_stand():
    from sevenhills_link.screen import _lines_from_words
    W = 21.6                                                   # a letter of the debug text enlarged three times
    def word(col, row, text, dy=0.0, h=30.0):
        return (col * W, row * 39.0 + dy, len(text) * W, h, text)
    words = [
        # One line of the screen that the OCR handed over as three lines, the last one first.
        word(37, 1, "-19000000.0000km"), word(0, 1, "Zone:", dy=2.0), word(6, 1, "SolarSystem_926344131032", dy=-1.5), word(31, 1, "Pos:"),
        # A word it cut in two: no room for a space between the halves.
        word(0, 2, "Current"), word(8, 2, "pl"), word(10, 2, "ayer"), word(15, 2, "location"), word(24, 2, ":"), word(26, 2, "GrimHEX"),
        # Two spaces between words are one.
        word(35, 2, "(LZ"), word(39, 2, ":"), word(41, 2, "GrimHEX)"),
        word(0, 0, "Zone:"), word(6, 0, "OOC_Stanton_2c_Yela"), word(26, 0, "Pos:"),
        # A lit sign behind the text, three times as tall, on the same height as line 1.
        (300.0, 20.0, 400.0, 95.0, "CARGO"),
        (0.0, 0.0, 10.0, 30.0, "  "),
    ]
    assert _lines_from_words(words) == [
        "Zone: OOC_Stanton_2c_Yela Pos:",
        "Zone: SolarSystem_926344131032 Pos: -19000000.0000km",
        "Current player location : GrimHEX (LZ : GrimHEX)",
        "CARGO",
    ]
    assert _lines_from_words([]) == []
    seen = read_debug_text("\n".join(_lines_from_words(words)))
    assert seen["zones"] == ["OOC_Stanton_2c_Yela", "SolarSystem_926344131032"] and seen["location"] == "GrimHEX"


def test_a_look_that_names_no_place_moves_on_to_the_next_way():
    from sevenhills_link.screen import WAYS
    r = reader()
    assert r.way == 0
    open_space = "Zone: SolarSystem_926344131032 Pos: 1.0km 2.0km 3.0km\nZone: Root Pos: 1.0km 2.0km 3.0km"
    r.look(open_space)                      # the block, but no place: perhaps another way reads the names
    assert r.way == 1 and r.status == "reading"
    r.look("nothing")                       # no block at all
    assert r.way == 2 and r.status == "no_text"
    r.look(BLOCK)                           # this way names the place: stay with it
    r.look(BLOCK)
    assert r.way == 2 and r.place_id == "stanton/crusader/yela/grim-hex"
    for _ in range(len(WAYS)):
        r.look("nothing")
    assert r.way == 2                       # once round, back at the same way


def test_it_looks_less_often_when_the_debug_text_is_not_there():
    from sevenhills_link.screen import IDLE_POLL_S, WAYS
    r = reader()
    r._looked = 1000.0
    for _ in range(len(WAYS) * 2 - 1):
        r.look("no debug text")
    assert r.resting(now=1001.0) is False                     # every way has not had its two looks yet
    r.look("no debug text")
    assert r.resting(now=1001.0) is True and r.resting(now=1000.0 + IDLE_POLL_S) is False
    r.look(BLOCK)                                             # the block is there: back to every two seconds
    assert r.misses == 0 and r.resting(now=1001.0) is False
    for _ in range(len(WAYS) * 2):
        r.look("no debug text")
    r.set_enabled(False)                                      # sharing switched off and on starts afresh
    assert r.misses == 0


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
    # The reader's own ways first, in their order: the box (760 × 420 px) and the wider corner (45 % × 40 %).
    sizes = {"box": (760, 420), "corner": (900, 420)}
    assert [s["size"] for s in seen[:len(screen.WAYS)]] == [(sizes[b][0] * k, sizes[b][1] * k) for b, k, _ in screen.WAYS]
    assert seen[0]["bytes"] == seen[0]["size"][0] * seen[0]["size"][1] * 4            # four bytes a pixel
    # The answer is the first way that names a place: here the very first.
    box, k, prep = screen.WAYS[0]
    assert (out["box"], out["scale"], out["prepared"]) == (box, k, prep) and out["size"] == [760 * k, 420 * k] and isinstance(out["ms"], int)
    assert out["block"] is True and out["place"] == "stanton/crusader/yela/grim-hex" and out["place_name"] == "Grim HEX"
    assert out["confidence"] == "exact"                 # the station on the location line, now that it is on the place list
    assert '"place": "stanton/crusader/yela/grim-hex"' in capsys.readouterr().out
    # Then every other way of reading: both boxes, twice and three times, each preparation; none twice.
    ways = [(t["box"], t["scale"], t["prepared"]) for t in out["tried"]]
    assert ways[:len(screen.WAYS)] == screen.WAYS and len(ways) == len(set(ways)) == 12 == len(seen)
    assert all(t["place"] == "stanton/crusader/yela/grim-hex" and t["location"] == "GrimHEX" and len(t["zones"]) == 4 for t in out["tried"])
    assert not any("text" in t for t in out["tried"])               # what was read is not kept here


def test_screen_test_answers_with_the_first_way_that_names_a_place(monkeypatch, tmp_path):
    from sevenhills_link import screen
    # The first two ways find no block; the third (the wider corner) reads it.
    code, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path), text=lambda i: BLOCK if i >= 3 else "Zcne: nothing readable")
    assert code == 0 and (out["box"], out["scale"], out["prepared"]) == screen.WAYS[2]
    assert out["block"] is True and out["place"] == "stanton/crusader/yela/grim-hex"
    assert [t["place"] for t in out["tried"]][:3] == [None, None, "stanton/crusader/yela/grim-hex"]
    # No way reads it: the answer says so, with the first way's numbers.
    code, out, _ = _screen_test(monkeypatch, tmp_path, _picture(tmp_path), text="Zcne: nothing readable")
    assert code == 0 and out["block"] is False and out["place"] is None and out["confidence"] is None
    assert (out["box"], out["scale"], out["prepared"]) == screen.WAYS[0]


def test_screen_test_skips_the_sizes_the_ocr_does_not_take(monkeypatch, tmp_path):
    code, out, seen = _screen_test(monkeypatch, tmp_path, _picture(tmp_path, size=(8000, 5000)))     # corner 3600 × 2000
    assert code == 0 and max(s["size"][0] for s in seen) == 7200
    assert not any(t["box"] == "corner" and t["scale"] == 3 for t in out["tried"])                 # 10 800 px wide: more than the OCR takes
    assert any(t["box"] == "box" and t["scale"] == 3 for t in out["tried"])


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
    assert read_debug_text("\n".join(text for text, _ in tool.block()))["block"] is True
    assert read_debug_text("\n".join(text for text, _ in tool.block("pyro")))["zones"][1] == "pyro6"
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


# ---------------------------------------------------------------- names the reader gets wrong

def test_pyro_as_windows_ocr_read_it_on_26_nov_is_terminus():
    # Costas's screen on Terminus: every way of reading gave "pyr06" for the zone "pyro6".
    seen = read_debug_text(block("Zone: pyr06 Pos: -199.4489km 199.1949km -50.5566km",
                                 "Zone: SolarSystem 926675998371 Pos: -48118219.6840km 48503407.6580km -50.5566km",
                                 "Zone: Root Pos •. -48118219.6840km 48503407.6580km -50.5566km",
                                 "Current player locatzon pyr06",
                                 "Planet:pyr06 ( Load Complete)"))
    assert seen["block"] and "pyr06" in seen["zones"]
    assert reader().place_of(seen) == "pyro/terminus"


def test_a_misread_name_counts_only_when_one_body_fits():
    assert PLACES.named("pyr06") == PLACES.named("Pyr06") == PLACES.named("pyro6") == "pyro/terminus"
    assert PLACES.hint("0OC Stanton 2a Ce11in") == "stanton/crusader/cellin"
    assert PLACES.named("Root") is None and PLACES.hint("SolarSystem 926675998371") is None
    # A name read right is never bent into another body.
    for key, pid in PLACES.bodies.items():
        assert PLACES.named(key) in (pid, PLACES.named(key)) and PLACES.body(key) == pid
    # Two bodies whose names a misreading makes the same name neither.
    two = Places([{"id": "a/x", "kind": "moon", "name": "X", "match": ["abc10"]}, {"id": "a/y", "kind": "moon", "name": "Y", "match": ["abclo"]}])
    assert two.misread_body("abc1o") is None and two.named("abc10") == "a/x"
