"""The place from the game screen: the debug text `r_displayinfo` writes in the top-right corner.

With `r_displayinfo 3` in the game console, Star Citizen prints a block of debug
text in the top-right corner. Among it, as on a real 4.10 screen:

    Zone: ObjectContainer-000 Pos: 23.05m -42.14m -47.02m
    Zone: OOC_Stanton_2c_Yela Pos: -568.6817km 383.6074km -2089.02m
    Zone: SolarSystem_926344131032 Pos: -19023600.8518km ...
    Zone: Root Pos: ...
    Current player location : GrimHEX  (LZ : GrimHEX)

This module looks at that corner of the game window every two seconds, reads the
text with Windows' own OCR (Windows.Media.Ocr, on this PC, no network) and turns it
into a place from data/places.json: the landing area on the location line when the
place list has it, else the planet, moon or belt among the zones. A place counts
once two readings in a row agree.

Only the debug block counts. A place is taken from the screen only when at least
two "Zone: ... Pos" lines are there, so a mission text or a notice that happens to
say "location: Lorville" in that corner is never read as where you are.

How it is read was settled by trying it: the build reads a drawn copy of a real
screen with Windows' OCR (tools/make_debug_screenshot.py, build.yml). What that
showed, and what is done about it:

  - The text is 12 px high and the OCR wants more: the box is enlarged three times.
  - The OCR cuts lines and words apart where the picture behind them changes
    ("Zone:" on one line and the rest on the next, "pl ayer"). So the lines are put
    together here, from where each word stands (_lines_from_words).
  - Which preparation reads best depends on the picture behind the text, so there
    are several WAYS and the reader moves on to the next one whenever a look names
    no place, and stays with the one that does.

The same text also gives the exact position on a planet or moon (position.py). It is
read with the place, shown under "Test screen reading", and sent only when the member
turned on "Share exact position" (off by default).

What leaves the PC: the place id (and, with that setting on, latitude, longitude and
height), through the same upload as the Game.log
place (location.py), which also decides between the two: the screen never
replaces a station the log knows with the moon it sits on. No picture is kept or
sent; the zone names of the last look stay in memory for "Test screen reading"
under Settings and nowhere else.

It runs only on Windows, only while the game window is in front, and only when the
member shares Full (core.py decides). Anything missing (no Windows OCR, no game, no
debug text) just leaves the Game.log place in charge, and the window says which.
"""

from __future__ import annotations

import asyncio
import re
import sys
import threading
import time

from . import position
from .location import ship_zone
from .log import log

POLL_S = 2.0
IDLE_POLL_S = 10.0       # how often it looks once the debug text has not been there for a while
STALE_S = 15.0           # a screen place older than this no longer counts
# The exact position (position.py): two readings in a row must lie this close together,
# as far as a ship near the ground can have moved in between plus some slack.
POS_SPEED_MS = 3000.0
POS_SLACK_M = 300.0
COURSE_MIN_M = 20.0      # the course is taken between two positions at least this far apart
BOX = (760, 420)         # px in the window's top-right corner: the block is about 640 × 330 px on a real screen
CORNER = (0.55, 0.0, 1.0, 0.40)   # the wider corner, as fractions of the window, should a screen draw the text larger
# The ways a look can be made, in the order they are tried: which part of the window,
# enlarged how many times, prepared how (see _enlarge). The first is the reader's own;
# it moves on to the next whenever a look names no place and stays with one that does.
WAYS = [("box", 3, "soft_inv"), ("box", 3, "none"), ("corner", 2, "soft_inv"), ("corner", 2, "none")]

# A zone line of the debug block. The OCR often loses the underscores and reads ":" as ";".
RE_ZONE = re.compile(r"\bZ[o0]ne\s*[:;.]?\s*(\S.*?)\s+P[o0]s\b", re.I)
# A zone line that still came out in two halves ("Zone:" / "SolarSystem_926344131032 Pos: ..."):
# the half that carries the name counts.
_ZONE_NAME = r"((?=[\w-]*[_-])[A-Za-z][\w-]*|Root)"      # a name with "_" or "-" in it, as every zone but Root has
RE_ZONE_NO_HEAD = re.compile(r"^\W*" + _ZONE_NAME + r"\s+P[o0]s\b", re.I)
RE_ZONE_NO_TAIL = re.compile(r"\bZ[o0]ne\s*[:;.]\s*" + _ZONE_NAME + r"\W*$", re.I)
# "Current player location : GrimHEX  (LZ : GrimHEX)"; the bracket is read as "[" or "{" at times.
RE_PLAYER_AT = re.compile(r"\bl[o0]cati[o0]n\s*[:;.]?\s*(.*?)\s*(?:[(\[{]\s*LZ\s*[:;.]?\s*(.*?)\s*[)\]}]?)?\s*$", re.I)
MIN_ZONE_LINES = 2       # fewer: not the debug block

IS_WINDOWS = sys.platform == "win32"


def read_debug_text(text: str | None) -> dict:
    """What the debug block says: {"block": is it there, "zones": [...], "location", "lz"}.

    `location` and `lz` are the two names on the "Current player location : X (LZ : Y)"
    line; both are None when the block is not there.
    """
    zones: list[str] = []
    ships: list[str] = []
    location: str | None = None
    lz: str | None = None
    for line in (text or "").splitlines():
        line = line.strip()
        # A ship's name standing as one word anywhere: the reader at times puts it on a line
        # of its own, away from its "Zone:" and "Pos:".
        for word in line.split():
            found = ship_zone(word)
            if found and found[0] not in ships:
                ships.append(found[0])
        m = RE_ZONE.search(line) or RE_ZONE_NO_HEAD.search(line) or RE_ZONE_NO_TAIL.search(line)
        if m:
            zones.append(m.group(1).strip()[:60])
            continue
        m = RE_PLAYER_AT.search(line)
        if m and location is None:
            location = (m.group(1) or "").strip()[:60] or None
            lz = (m.group(2) or "").strip()[:60] or None
    block = len(zones) >= MIN_ZONE_LINES
    return {"block": block, "zones": zones, "ships": ships if block else [], "location": location if block else None, "lz": lz if block else None}


class ScreenReader:
    """A thread that keeps tracker.screen set to the place the screen shows, or None."""

    def __init__(self, tracker, places) -> None:
        self.tracker = tracker
        self.places = places
        self.enabled = False            # core.py: on while sharing Full
        # unavailable | off | idle | no_text | reading | error
        #   unavailable: not Windows or no OCR on this PC; off: not sharing Full;
        #   idle: the game is not in front; no_text: in front but no debug block;
        #   reading: the debug block is there; error: the last look failed
        self.status = "unavailable" if not IS_WINDOWS else "off"
        self.place_id: str | None = None
        self.language: str | None = None    # the OCR language in use
        self.error: str | None = None       # why it is unavailable, or what the last look failed on
        self.last: dict | None = None       # the last look, for "Test screen reading"
        self.way = 0                        # which of WAYS the next look uses
        self.misses = 0                     # looks in a row that found no debug block
        self._looked = 0.0
        self._pos_prev: tuple[dict, float] | None = None   # the last position read, and when
        self._course_from: tuple[str, tuple[float, float]] | None = None   # (body, where the course is measured from)
        self._course: int | None = None                    # the last course, whole degrees
        self.position: dict | None = None                  # the last position that counted, for "Test screen reading"
        self._last: str | None = None
        self._ship_last: str | None = None                 # the ship the look before this one named
        self.ship: str | None = None                       # the ship two looks agreed on, for "Test screen reading"
        self._at = 0.0
        self._engine = None
        self._logged: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ control

    def start(self) -> None:
        if not IS_WINDOWS or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="screen", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        if on and self.status == "off":
            self.status = "idle"
        if not on:
            self._clear()
            self.misses = 0
            if self.status != "unavailable":
                self.status = "off"

    def report(self) -> dict:
        """For the window (Settings → Game → Test screen reading). Stays on this PC."""
        last = dict(self.last) if self.last else None
        if last:
            last["ago"] = round(max(0.0, time.time() - last.pop("at")))
            pid = last.get("place")
            last["place_name"] = self.places.name_of(pid) if pid else None
        return {"status": self.status, "language": self.language, "error": self.error, "last": last}

    # ------------------------------------------------------------ work

    def _clear(self) -> None:
        self.place_id = None
        self._last = None
        self._pos_prev = None
        self._course_from = None
        self._course = None
        self.position = None
        self._ship_last = None
        self.ship = None
        with self.tracker._lock:
            self.tracker.screen = None
            self.tracker.screen_pos = None
            self.tracker.screen_ship = None

    def _look_position(self, text: str | None, now: float) -> dict | None:
        """The exact position this reading gives (position.py). It counts, and is handed to the
        tracker, once it lies close to the reading before it; the tracker sends it only when
        the member has turned on "Share exact position"."""
        pos = position.body_position(text, self.places)
        prev, self._pos_prev = self._pos_prev, ((pos, now) if pos else None)
        if not pos:
            if self.position and now - self.position["at"] > STALE_S:
                self.position = None
                with self.tracker._lock:
                    self.tracker.screen_pos = None
            return None
        if prev and prev[0]["body"] == pos["body"] and position.apart_m(prev[0], pos) <= POS_SLACK_M + POS_SPEED_MS * max(0.0, now - prev[1]):
            # The course: from the spot it was last measured from to here, once that is far
            # enough to say anything. Standing still keeps the last course.
            here = pos["exact"]
            if not self._course_from or self._course_from[0] != pos["body"]:
                self._course_from, self._course = (pos["body"], here), None
            elif position.ground_m(self._course_from[1], here, pos["radius"] + max(0, pos["alt"])) >= COURSE_MIN_M:
                self._course = round(position.bearing(self._course_from[1], here)) % 360
                self._course_from = (pos["body"], here)
            self.position = {"body": pos["body"], "lat": pos["lat"], "lon": pos["lon"], "alt": pos["alt"], "hdg": self._course,
                             "r": round(pos["radius"] / 1000), "at": now}
            with self.tracker._lock:
                self.tracker.screen_pos = dict(self.position)
        return pos

    def _look_ship(self, seen: dict, now: float) -> str | None:
        """The ship whose zone this reading shows (the innermost zone that is one), handed to
        the tracker once two readings in a row name the same ship."""
        found = next((z for z in (ship_zone(zone) for zone in seen["zones"]) if z), None)
        if not found and len(seen.get("ships") or []) == 1:
            found = ship_zone(seen["ships"][0])      # its name alone on a line: the only ship named in the block
        name = found[0] if found else None
        if name and name == self._ship_last:
            self.ship = name
            with self.tracker._lock:
                self.tracker.screen_ship = {"name": name, "number": found[1], "at": now}
        elif not name and not self._ship_last:
            self.ship = None
            with self.tracker._lock:
                self.tracker.screen_ship = None
        self._ship_last = name
        return name

    def _fail(self, what: str, e: BaseException) -> None:
        """A look that did not work: say so in the window and once in link.log."""
        self.error = f"{what}: {type(e).__name__}: {e}"[:200]
        self.status = "error"
        self.last = {"at": time.time(), "error": self.error}
        if self.error != self._logged:       # once per kind of failure, not every two seconds
            self._logged = self.error
            log.warning("screen reading failed (%s)", self.error)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            self._engine = _ocr_engine()
            self.language = _language_of(self._engine)
            log.info("screen reading ready (Windows OCR, %s)", self.language or "language unknown")
        except Exception as e:  # no OCR language pack, old Windows, missing winrt
            self.error = f"{type(e).__name__}: {e}"[:200]
            log.info("screen reading unavailable: %s", self.error)
            self.status = "unavailable"
            return
        while not self._stop.is_set():
            self._stop.wait(POLL_S)
            if not self.enabled or self.resting():
                continue
            self._once(loop)
            if self.place_id and time.time() - self._at > STALE_S:
                self._clear()

    def resting(self, now: float | None = None) -> bool:
        """Most members never switch the debug text on. Once every way has looked twice and
        found no block, a look is made every IDLE_POLL_S instead of every POLL_S, until the
        block is there."""
        return self.misses >= len(WAYS) * 2 and (time.time() if now is None else now) - self._looked < IDLE_POLL_S

    def _once(self, loop) -> None:
        try:
            rect = _game_rect()
        except Exception as e:  # noqa: BLE001
            return self._fail("finding the game window", e)
        if not rect:
            # Game in the background (or this window in front): keep what the last look
            # found, so the window can say it; the place itself expires after STALE_S.
            if self.status not in ("reading", "no_text", "error"):
                self.status = "idle"
            return
        self._looked = time.time()
        which, scale, prep = WAYS[self.way % len(WAYS)]
        try:
            pixels, bw, bh = _grab(_box(*rect, which))
        except Exception as e:  # noqa: BLE001
            return self._fail("capturing the screen", e)
        try:
            began = time.perf_counter()
            pixels, bw, bh, scale = _enlarge(pixels, bw, bh, _max_side(self._engine), scale, prep)
            text = loop.run_until_complete(_recognize(self._engine, pixels, bw, bh))
            ms = round((time.perf_counter() - began) * 1000)
        except Exception as e:  # noqa: BLE001
            return self._fail("reading the text", e)
        self.error = None
        self.look(text, size=(bw, bh), scale=scale, ms=ms, prep=prep)

    def look(self, text: str | None, size: tuple[int, int] | None = None, scale: int = 1, ms: int | None = None,
             prep: str | None = None) -> str | None:
        """One reading of the corner: update the status, the last look and, after two that
        agree, the place. A look that names no place moves the reader on to the next of
        WAYS. Returns the place this reading names (also used by the tests)."""
        seen = read_debug_text(text)
        pid = self.place_of(seen) if seen["block"] else None
        pos = self._look_position(text, time.time()) if seen["block"] else None
        ship = self._look_ship(seen, time.time()) if seen["block"] else None
        self.last = {"at": time.time(), "ship": ship, "position": {**{k: pos[k] for k in ("body", "lat", "lon", "alt", "checked")}, "hdg": self._course} if pos else None, "size": list(size) if size else None, "scale": scale, "prepared": prep, "ms": ms,
                     "lines": len([x for x in (text or "").splitlines() if x.strip()]),
                     "block": seen["block"], "zones": seen["zones"][:6], "location": seen["location"] or seen["lz"],
                     "place": pid, "error": None}
        if not pid:
            self.way = (self.way + 1) % len(WAYS)
        if not seen["block"]:
            self.misses += 1
            self.status = "no_text"
            self._clear()
            return None
        self.misses = 0
        self.status = "reading"
        if pid == self._last:
            if pid:
                self.place_id, self._at = pid, time.time()
                with self.tracker._lock:
                    self.tracker.screen = {"place_id": pid, "at": self._at}
            elif self.place_id:
                self._clear()      # twice in a row the block names no place we know: the old one is over
        self._last = pid
        return pid

    def place_of(self, seen: dict) -> str | None:
        """The place a debug block names: the landing area on the location line when the place
        list has it and it lies where the zones say, else the deepest planet, moon, belt or
        station among the zones."""
        area: str | None = None
        for zone in seen["zones"]:
            pid = self.places.named(zone) or self.places.hint(zone)
            if pid and (area is None or pid.count("/") > area.count("/")):
                area = pid
        # The location line: the name before "(LZ : ...)", else the landing zone's own name.
        spot = None
        for name in (seen.get("location"), seen.get("lz")):
            pid = self.places.named(name) if name else None
            if not pid:
                continue
            if self.places.is_spot(pid):
                spot = pid
                break
            # The line can also name the moon or the system: one more zone.
            if area is None or (pid.count("/") > area.count("/") and self.places.within(pid, area)):
                area = pid
        if spot and (area is None or self.places.within(spot, area) or self.places.kind(area) == "system"):
            return spot
        return area

    def place_from_text(self, text: str | None) -> str | None:
        """What OCR returned → a place, or None. Only inside the debug block."""
        seen = read_debug_text(text)
        return self.place_of(seen) if seen["block"] else None


def _box(l: int, t: int, r: int, b: int, which: str = "box") -> tuple[int, int, int, int]:
    """The part of a window or picture that is read, in its top-right corner.

    "box": BOX pixels, where the block is on a real screen whatever the window's size
    (the game draws the debug text at one size in pixels). "corner": CORNER of the
    window and never less than BOX, for a screen that draws it larger.
    """
    w, h = r - l, b - t
    bw, bh = BOX
    if which == "corner":
        bw, bh = max(bw, w - int(w * CORNER[0])), max(bh, int(h * CORNER[3]))
    bw, bh = min(w, bw), min(h, bh)
    return r - bw, t, r, t + bh


def _lines_from_words(words: list[tuple[float, float, float, float, str]]) -> list[str]:
    """Text lines from the words the OCR found, each given as (x, y, width, height, text).

    The OCR groups words into lines itself, and gets it wrong on this text: where the
    picture behind the block changes it ends a line in the middle ("Zone:" on one line,
    "SolarSystem_... Pos: ..." on the next) or a word ("pl" "ayer"). The debug text is
    one face at one size on straight lines, so where the words stand says it better:
    words at the same height are one line, read from the left, and two words with no
    room for a space between them are one word. A word much taller than the rest is
    something else on the screen and gets a line of its own.
    """
    words = [w for w in words if str(w[4]).strip()]
    if not words:
        return []
    heights = sorted(w[3] for w in words)
    tall = heights[len(heights) // 2] or 1.0
    rows: list[list] = []                                   # [the line's middle, its words]
    apart: list[str] = []
    for w in sorted(words, key=lambda w: w[1] + w[3] / 2):
        if w[3] > tall * 1.8:
            apart.append(str(w[4]))
            continue
        mid = w[1] + w[3] / 2
        if rows and abs(mid - rows[-1][0]) <= tall * 0.5:
            rows[-1][1].append(w)
            rows[-1][0] += (mid - rows[-1][0]) / len(rows[-1][1])
        else:
            rows.append([mid, [w]])
    out: list[str] = []
    for _, row in rows:
        row.sort(key=lambda w: w[0])
        widths = sorted(w[2] / max(len(str(w[4])), 1) for w in row)
        letter = widths[len(widths) // 2] or 1.0
        text = str(row[0][4])
        for a, b in zip(row, row[1:]):
            text += ("" if b[0] - (a[0] + a[2]) < letter * 0.4 else " ") + str(b[4])
        out.append(text)
    return out + apart


# ---------------------------------------------------------------- Windows bits

def _game_rect() -> tuple[int, int, int, int] | None:
    """Screen rectangle of the game's client area, only while the game window is in front."""
    import psutil  # type: ignore
    import win32gui  # type: ignore
    import win32process  # type: ignore

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or win32gui.IsIconic(hwnd):
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        if psutil.Process(pid).name().lower() != "starcitizen.exe":
            return None
    except Exception:
        return None
    l, t, r, b = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (l, t))
    if r - l < 200 or b - t < 200:
        return None
    return x, y, x + (r - l), y + (b - t)


def _grab(box: tuple[int, int, int, int]) -> tuple[bytes, int, int]:
    import mss  # type: ignore

    l, t, r, b = box
    with mss.mss() as sct:
        shot = sct.grab({"left": l, "top": t, "width": r - l, "height": b - t})
        return bytes(shot.bgra), shot.width, shot.height


SOFT_FROM, SOFT_TO = 90, 190    # "soft": darker than the first is black, brighter than the second white


def _enlarge(pixels: bytes, w: int, h: int, max_side: int, scale: int = 2, prep: str = "none") -> tuple[bytes, int, int, int]:
    """The capture made ready for the OCR (BGRA in, BGRA out): enlarged `scale` times and
    prepared as `prep` says. Returned as it is when Pillow is missing, and never larger
    than the OCR takes.

    prep "none": only enlarged. "soft": the brightest of the three colours of each pixel,
    with everything dark made black and everything bright white, so the white, yellow and
    orange debug text stands on a flat black background instead of on the game's picture.
    "soft_inv": the same, black text on white.
    """
    while scale > 1 and (w * scale > max_side or h * scale > max_side):
        scale -= 1
    if scale <= 1 and prep == "none":
        return pixels, w, h, 1
    try:
        from PIL import Image, ImageChops  # type: ignore
    except Exception:  # noqa: BLE001
        return pixels, w, h, 1
    bicubic = getattr(Image, "Resampling", Image).BICUBIC
    # Read as three colours plus an unused byte, never as RGBA: a capture's fourth byte is
    # often 0, and Pillow would weigh every pixel by that "alpha" and return a black picture.
    img = Image.frombuffer("RGB", (w, h), pixels, "raw", "BGRX", 0, 1)
    if prep == "none":
        big = img.resize((w * scale, h * scale), bicubic)
    else:
        r, g, b = img.split()
        light = ImageChops.lighter(ImageChops.lighter(r, g), b)
        if scale > 1:
            light = light.resize((w * scale, h * scale), bicubic)
        span = SOFT_TO - SOFT_FROM
        light = light.point([0 if v <= SOFT_FROM else 255 if v >= SOFT_TO else round((v - SOFT_FROM) * 255 / span) for v in range(256)])
        if prep == "soft_inv":
            light = ImageChops.invert(light)
        big = Image.merge("RGB", (light, light, light))
    return big.tobytes("raw", "BGRX"), w * scale, h * scale, scale


def _ocr_engine():
    from winrt.windows.globalization import Language  # type: ignore
    from winrt.windows.media.ocr import OcrEngine  # type: ignore

    engine = None
    try:
        engine = OcrEngine.try_create_from_language(Language("en-US"))
    except Exception:
        engine = None
    engine = engine or OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("no OCR language installed")
    return engine


def _language_of(engine) -> str | None:
    try:
        return str(engine.recognizer_language.language_tag)
    except Exception:  # noqa: BLE001
        return None


def _max_side(engine) -> int:
    """The largest image side the OCR takes (10 000 px on current Windows)."""
    try:
        return int(type(engine).max_image_dimension)
    except Exception:  # noqa: BLE001
        return 4000


LINES_FROM = {"how": None, "why": None}     # how the last read got its lines: "words", or "engine" and why


async def _recognize(engine, pixels: bytes, w: int, h: int) -> str:
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap  # type: ignore
    from winrt.windows.security.cryptography import CryptographicBuffer  # type: ignore

    buf = CryptographicBuffer.create_from_byte_array(pixels)
    # A screen capture has no alpha: its fourth byte is unused and often 0, which must not
    # be read as "fully transparent".
    bmp = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.IGNORE)
    result = await engine.recognize_async(bmp)
    try:
        words = []
        for line in result.lines:
            for word in line.words:
                box = word.bounding_rect
                words.append((float(box.x), float(box.y), float(box.width), float(box.height), str(word.text)))
        LINES_FROM.update(how="words", why=None)
        return "\n".join(_lines_from_words(words))
    except Exception as e:  # noqa: BLE001  (the words could not be had: the OCR's own lines will do)
        LINES_FROM.update(how="engine", why=f"{type(e).__name__}: {e}"[:160])
        return "\n".join(line.text for line in result.lines)


# ---------------------------------------------------------------- 7HillsLink.exe --screen-test [screenshot]

RE_PLACE_LINE = re.compile(r"z[o0]ne|\bp[o0]s\b|player|l[o0]cati[o0]n|\bLZ\b|planet|container|system", re.I)
RE_DIGITS = re.compile(r"[0-9øØ]")       # Windows reads a slashed zero as "ø"


def _no_numbers(line: str) -> str:
    """A read line without its numbers: every word that holds a decimal point or is made of
    digits becomes "#", and long runs of digits inside a name too. The words are what a
    test needs; the numbers in the debug block are positions."""
    out = []
    for word in line.split():
        if (RE_DIGITS.search(word) and re.search(r"[.,]", word)) or re.fullmatch(r"\W*[0-9øØ]{3,}[A-Za-z]{0,2}\W*", word):
            out.append("#")
        else:
            out.append(re.sub(r"\d{4,}", "#", word))
    return " ".join(out)[:120]


def _place_lines(text: str, places=None) -> tuple[list[str], int]:
    """(the read lines that bear on the place, numbers taken out; how many other lines).
    A line bears on the place when it has one of the block's own words for it or names a
    place on the list. The other lines of the debug block (session, shard, server, times)
    are nobody's business and are only counted."""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    kept = [_no_numbers(x) for x in lines if RE_PLACE_LINE.search(x) or (places is not None and places.hint(x)) or any(ship_zone(w) for w in x.split())]
    return kept[:30], len(lines) - len(kept)


def check_screenshot(path: str | None) -> int:
    """Read the debug text exactly as the running client reads the screen (same boxes, same
    preparation, same Windows OCR call, on a worker thread), and say what it found.

    With a picture: a saved screenshot of the game window. For checking text recognition on a
    PC without the game, and for testing the built exe. Without one: the main screen as it is
    right now, whatever is in front (for a look with the game up, apart from the sharing
    setting and the "game window in front" rule).

    The answer is what the client would settle on: the first of WAYS that names a place.
    `tried` lists how every way of reading went (both boxes, enlarged two and three times,
    each preparation) and how long it took, so the ways can be chosen from real screens.

    Prints one JSON object and writes the same to screen-test.json in the data folder (a
    windowed exe has no console to print to unless its output is piped). Of what was read
    it holds only the lines that bear on the place, with their numbers taken out, and the
    position worked out from them (body, latitude, longitude, height): no session or
    server name is written down. It goes nowhere.
    Exit code: 0 the text was read (whatever it said), 2 bad file, 3 Windows text recognition
    is not available here, 1 it failed.
    """
    import json

    from .location import Places, Tracker
    from .paths import data_dir

    out: dict = {"ok": False, "source": path or "the main screen"}
    code = 1

    def work() -> None:
        nonlocal code
        try:
            from PIL import Image  # type: ignore
            if path:
                img = Image.open(path).convert("RGB")
            else:
                import mss  # type: ignore
                with mss.mss() as sct:
                    shot = sct.grab(sct.monitors[1])
                    img = Image.frombytes("RGB", shot.size, bytes(shot.bgra), "raw", "BGRX")
                out["captured"] = list(img.size)
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{'could not open the picture' if path else 'capturing the screen failed'}: {type(e).__name__}: {e}"
            code = 2 if path else 1
            return
        try:
            engine = _ocr_engine()
        except Exception as e:  # noqa: BLE001
            out["error"] = f"Windows text recognition is not available: {type(e).__name__}: {e}"
            code = 3
            return
        out["language"] = _language_of(engine)
        loop = asyncio.new_event_loop()
        limit = _max_side(engine)
        places = Places.load()
        reader = ScreenReader(Tracker(places), places)

        def read(which: str, scale: int, prep: str) -> dict:
            crop = img.crop(_box(0, 0, *img.size, which))
            began = time.perf_counter()
            px, w2, h2, used = _enlarge(crop.tobytes("raw", "BGRX"), crop.width, crop.height, limit, scale, prep)   # what a screen capture hands over
            text = loop.run_until_complete(_recognize(engine, px, w2, h2))
            ms = round((time.perf_counter() - began) * 1000)
            seen = read_debug_text(text)
            pos = position.body_position(text, places) if seen["block"] else None
            return {"box": which, "scale": used, "prepared": prep, "ms": ms, "size": [w2, h2],
                    "position": {k: pos[k] for k in ("body", "lat", "lon", "alt", "checked")} if pos else None,
                    "lines": len([x for x in text.splitlines() if x.strip()]), "block": seen["block"], "zones": seen["zones"][:6],
                    "location": seen["location"] or seen["lz"], "place": reader.place_of(seen) if seen["block"] else None, "text": text}

        try:
            looks = [read(*way) for way in WAYS]
        except Exception as e:  # noqa: BLE001
            out["error"] = f"reading the text failed: {type(e).__name__}: {e}"
            return
        out["lines_from"] = (LINES_FROM["how"] or "?") + (f" ({LINES_FROM['why']})" if LINES_FROM["why"] else "")
        # What the client settles on: the first way that names a place, else the first that finds the block.
        best = next((x for x in looks if x["place"]), None) or next((x for x in looks if x["block"]), looks[0])
        reader.look(best["text"], size=tuple(best["size"]), scale=best["scale"], ms=best["ms"], prep=best["prepared"])
        reader.look(best["text"], size=tuple(best["size"]), scale=best["scale"], ms=best["ms"], prep=best["prepared"])   # a place counts after two readings that agree
        snap = reader.tracker.snapshot()
        kept, others = _place_lines(best["text"], places)
        # The exact position: what this way of reading gave, and how many of the ways gave one.
        out["position"] = best["position"]
        out["position_ways"] = sum(1 for x in looks if x["position"])
        out["ship"] = reader.ship          # the ship whose zone the text shows, when you are inside one
        import os
        if os.environ.get("SEVENHILLS_SCREEN_DEBUG") == "1":   # the build only: every line of a drawn picture
            out["debug_lines"] = [x for x in best["text"].splitlines() if x.strip()][:12]
        out.update({"ok": True, **{k: best[k] for k in ("box", "scale", "prepared", "ms", "size", "lines", "block", "zones", "location", "place")},
                    "place_name": places.name_of(best["place"]) if best["place"] else None,
                    "confidence": snap["confidence"] if snap else None, "read": kept, "other_lines": others})
        code = 0
        # Every way of reading, for choosing among them: the reader's own first, then the rest.
        tried = [{k: v for k, v in x.items() if k not in ("text", "size", "block")} for x in looks]
        for which in ("box", "corner"):
            for scale in (2, 3):
                for prep in ("none", "soft", "soft_inv"):
                    if (which, scale, prep) in WAYS:
                        continue
                    try:
                        x = read(which, scale, prep)
                    except Exception as e:  # noqa: BLE001
                        tried.append({"box": which, "scale": scale, "prepared": prep, "error": f"{type(e).__name__}: {e}"[:120]})
                        continue
                    if x["scale"] == scale:        # else: too large for the OCR at this size
                        tried.append({k: v for k, v in x.items() if k not in ("text", "size", "block")})
        out["tried"] = tried

    t = threading.Thread(target=work, name="screen-test")
    t.start()
    t.join()
    text = json.dumps(out, indent=1)
    try:
        (data_dir() / "screen-test.json").write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        print(text, flush=True)
    except Exception:  # noqa: BLE001  (no console and no pipe)
        pass
    return code
