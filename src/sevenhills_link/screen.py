"""The place from the game screen: the debug text `r_displayinfo` writes in the top-right corner.

With `r_displayinfo 3` in the game console, Star Citizen prints a block of debug
text in the top-right corner. Among it, as on a real 4.10 screen:

    Zone: ObjectContainer-000 Pos: 23.05m -42.14m -47.02m
    Zone: OOC_Stanton_2c_Yela Pos: -568.6817km 383.6074km -2089.02m
    Zone: SolarSystem_926344131032 Pos: -19023600.8518km ...
    Zone: Root Pos: ...
    Current player location : GrimHEX (LZ : GrimHEX)

This module looks at that corner of the game window every two seconds, reads the
text with Windows' own OCR (Windows.Media.Ocr, on this PC, no network) and turns it
into a place from data/places.json: the landing area on the location line when the
place list has it, else the planet, moon or belt among the zones. A place counts
once two readings in a row agree.

Only the debug block counts. A place is taken from the screen only when at least
two "Zone: ... Pos" lines are there, so a mission text or a notice that happens to
say "location: Lorville" in that corner is never read as where you are.

What leaves the PC: only the place id, through the same upload as the Game.log
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

from .log import log

POLL_S = 2.0
STALE_S = 15.0           # a screen place older than this no longer counts
CORNER = (0.55, 0.0, 1.0, 0.40)   # left, top, right, bottom of the window, as fractions
SCALE = 2                # the debug text is about 9 px high at 1440p: enlarged before it is read

# A zone line of the debug block. The OCR often loses the underscores and reads ":" as ";".
RE_ZONE = re.compile(r"\bZ[o0]ne\s*[:;.]?\s*(\S.*?)\s+P[o0]s\b", re.I)
# "Current player location : GrimHEX (LZ : GrimHEX)"
RE_PLAYER_AT = re.compile(r"player\s+l[o0]cati[o0]n\s*[:;.]?\s*(.*?)\s*(?:\(\s*LZ\s*[:;.]?\s*(.*?)\s*\)?)?\s*$", re.I)
MIN_ZONE_LINES = 2       # fewer: not the debug block

IS_WINDOWS = sys.platform == "win32"


def read_debug_text(text: str | None) -> dict:
    """What the debug block says: {"block": is it there, "zones": [...], "location", "lz"}.

    `location` and `lz` are the two names on the "Current player location : X (LZ : Y)"
    line; both are None when the block is not there.
    """
    zones: list[str] = []
    location: str | None = None
    lz: str | None = None
    for line in (text or "").splitlines():
        line = line.strip()
        m = RE_ZONE.search(line)
        if m:
            zones.append(m.group(1).strip()[:60])
            continue
        m = RE_PLAYER_AT.search(line)
        if m:
            location = (m.group(1) or "").strip()[:60] or None
            lz = (m.group(2) or "").strip()[:60] or None
    block = len(zones) >= MIN_ZONE_LINES
    return {"block": block, "zones": zones, "location": location if block else None, "lz": lz if block else None}


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
        self._last: str | None = None
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
        with self.tracker._lock:
            self.tracker.screen = None

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
            if not self.enabled:
                continue
            self._once(loop)
            if self.place_id and time.time() - self._at > STALE_S:
                self._clear()

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
        l, t, r, b = rect
        w, h = r - l, b - t
        box = (l + int(w * CORNER[0]), t + int(h * CORNER[1]), l + int(w * CORNER[2]), t + int(h * CORNER[3]))
        try:
            pixels, bw, bh = _grab(box)
        except Exception as e:  # noqa: BLE001
            return self._fail("capturing the screen", e)
        try:
            pixels, bw, bh, scale = _enlarge(pixels, bw, bh, _max_side(self._engine))
            text = loop.run_until_complete(_recognize(self._engine, pixels, bw, bh))
        except Exception as e:  # noqa: BLE001
            return self._fail("reading the text", e)
        self.error = None
        self.look(text, size=(bw, bh), scale=scale)

    def look(self, text: str | None, size: tuple[int, int] | None = None, scale: int = 1) -> str | None:
        """One reading of the corner: update the status, the last look and, after two that
        agree, the place. Returns the place this reading names (also used by the tests)."""
        seen = read_debug_text(text)
        pid = self.place_of(seen) if seen["block"] else None
        self.last = {"at": time.time(), "size": list(size) if size else None, "scale": scale,
                     "lines": len([x for x in (text or "").splitlines() if x.strip()]),
                     "block": seen["block"], "zones": seen["zones"][:6], "location": seen["location"] or seen["lz"],
                     "place": pid, "error": None}
        if not seen["block"]:
            self.status = "no_text"
            self._clear()
            return None
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


def _enlarge(pixels: bytes, w: int, h: int, max_side: int) -> tuple[bytes, int, int, int]:
    """The capture enlarged SCALE times (BGRA in, BGRA out), or as it is when Pillow is
    missing or the result would be larger than the OCR takes."""
    if SCALE <= 1 or w * SCALE > max_side or h * SCALE > max_side:
        return pixels, w, h, 1
    try:
        from PIL import Image  # type: ignore
    except Exception:  # noqa: BLE001
        return pixels, w, h, 1
    # Read as three colours plus an unused byte, never as RGBA: a capture's fourth byte is
    # often 0, and Pillow would weigh every pixel by that "alpha" and return a black picture.
    img = Image.frombuffer("RGB", (w, h), pixels, "raw", "BGRX", 0, 1)
    big = img.resize((w * SCALE, h * SCALE), getattr(Image, "Resampling", Image).BICUBIC)
    return big.tobytes("raw", "BGRX"), w * SCALE, h * SCALE, SCALE


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


async def _recognize(engine, pixels: bytes, w: int, h: int) -> str:
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap  # type: ignore
    from winrt.windows.security.cryptography import CryptographicBuffer  # type: ignore

    buf = CryptographicBuffer.create_from_byte_array(pixels)
    # A screen capture has no alpha: its fourth byte is unused and often 0, which must not
    # be read as "fully transparent".
    bmp = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.IGNORE)
    result = await engine.recognize_async(bmp)
    return "\n".join(line.text for line in result.lines)


# ---------------------------------------------------------------- 7HillsLink.exe --screen-test [screenshot]

RE_NUMBER = re.compile(r"-?\d+(?:\s?[.,]\s?\d+)+(?:\s*k?m\b)?|-?\d{4,}")


def _no_numbers(line: str) -> str:
    """A read line with its decimals and long numbers replaced by "#": the words are what a
    test needs, and the numbers in the debug block are positions."""
    return RE_NUMBER.sub("#", line)[:120]

def check_screenshot(path: str | None) -> int:
    """Read the debug text exactly as the running client reads the screen (same corner, same
    enlarging, same Windows OCR call, on a worker thread), and say what it found.

    With a picture: a saved screenshot of the game window. For checking text recognition on a
    PC without the game, and for testing the built exe. Without one: the top-right corner of
    the main screen as it is right now, whatever is in front (for a look with the game up,
    apart from the sharing setting and the "game window in front" rule).

    Prints one JSON object and writes the same to screen-test.json in the data folder (a
    windowed exe has no console to print to unless its output is piped). It holds the lines
    that were read with their numbers taken out, so no position is written down, and it
    goes nowhere.
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
        if path:
            try:
                from PIL import Image  # type: ignore
                img = Image.open(path).convert("RGB")
            except Exception as e:  # noqa: BLE001
                out["error"] = f"could not open the picture: {type(e).__name__}: {e}"
                code = 2
                return
            w, h = img.size
            crop = img.crop((int(w * CORNER[0]), int(h * CORNER[1]), int(w * CORNER[2]), int(h * CORNER[3])))
            pixels, bw, bh = crop.tobytes("raw", "BGRX"), crop.width, crop.height    # what a screen capture hands over
        else:
            try:
                import mss  # type: ignore
                with mss.mss() as sct:
                    mon = sct.monitors[1]
                l, t, w, h = mon["left"], mon["top"], mon["width"], mon["height"]
                pixels, bw, bh = _grab((l + int(w * CORNER[0]), t + int(h * CORNER[1]), l + int(w * CORNER[2]), t + int(h * CORNER[3])))
            except Exception as e:  # noqa: BLE001
                out["error"] = f"capturing the screen failed: {type(e).__name__}: {e}"
                return
            out["captured"] = [bw, bh]
        try:
            engine = _ocr_engine()
        except Exception as e:  # noqa: BLE001
            out["error"] = f"Windows text recognition is not available: {type(e).__name__}: {e}"
            code = 3
            return
        out["language"] = _language_of(engine)
        try:
            pixels, bw, bh, scale = _enlarge(pixels, bw, bh, _max_side(engine))
            text = asyncio.new_event_loop().run_until_complete(_recognize(engine, pixels, bw, bh))
        except Exception as e:  # noqa: BLE001
            out["error"] = f"reading the text failed: {type(e).__name__}: {e}"
            return
        places = Places.load()
        reader = ScreenReader(Tracker(places), places)
        reader.look(text, size=(bw, bh), scale=scale)
        reader.look(text, size=(bw, bh), scale=scale)       # a place counts after two readings that agree
        last = reader.report()["last"] or {}
        snap = reader.tracker.snapshot()
        out.update({"ok": True, "size": last.get("size"), "scale": last.get("scale"), "lines": last.get("lines"),
                    "block": last.get("block"), "zones": last.get("zones"), "location": last.get("location"),
                    "place": last.get("place"), "place_name": last.get("place_name"),
                    "confidence": snap["confidence"] if snap else None,
                    "read": [_no_numbers(x) for x in text.splitlines() if x.strip()][:40]})
        code = 0

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
