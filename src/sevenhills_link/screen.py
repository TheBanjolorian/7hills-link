"""Exact place from the game screen: the text `r_displayinfo` writes in the top-right corner.

With `r_displayinfo 2` (or higher) in the game console, Star Citizen prints a block of
debug text in the top-right corner, among it the zone you are in. This module looks at
that corner of the game window about once a second, reads the text with Windows' own
OCR (Windows.Media.Ocr, on this PC, no network) and turns the zone into a place from
data/places.json. A place counts once two readings in a row agree.

What leaves the PC: only that place id, through the same location upload as the
Game.log place (location.py). No picture is kept or sent; the text is dropped after
the place is looked up.

It runs only on Windows, only while the game window is in front, and only when the
member shares Full (core.py decides). Anything missing (no Windows OCR, no game, no
debug text) just leaves the Game.log place in charge.
"""

from __future__ import annotations

import asyncio
import re
import sys
import threading
import time

from .log import log

POLL_S = 1.0
STALE_S = 10.0           # a screen place older than this no longer counts
CORNER = (0.55, 0.0, 1.0, 0.40)   # left, top, right, bottom of the window, as fractions

# Lines r_displayinfo writes that name where you are. The value is the rest of the line.
RE_ZONE = re.compile(r"(?:^|\b)(?:zone|location|current player location|container)\s*[:=]\s*(.+)$", re.I)
# Seen in every r_displayinfo block: tells "the debug text is on" from "nothing there".
RE_MARK = re.compile(r"\b(?:zone|fps|frame|shard|server|build|location)\b", re.I)

IS_WINDOWS = sys.platform == "win32"


class ScreenReader:
    """A thread that keeps tracker.screen set to the place the screen shows, or None."""

    def __init__(self, tracker, places) -> None:
        self.tracker = tracker
        self.places = places
        self.enabled = False            # core.py: on while sharing Full
        # unavailable | off | idle | no_text | reading
        #   unavailable: not Windows or no OCR on this PC; off: not sharing Full;
        #   idle: the game is not in front; no_text: in front but no debug text; reading: text found
        self.status = "unavailable" if not IS_WINDOWS else "off"
        self.place_id: str | None = None
        self._last: str | None = None
        self._at = 0.0
        self._engine = None
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
        if not on:
            self._clear()
            if self.status != "unavailable":
                self.status = "off"

    # ------------------------------------------------------------ work

    def _clear(self) -> None:
        self.place_id = None
        self._last = None
        with self.tracker._lock:
            self.tracker.screen = None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            self._engine = _ocr_engine()
        except Exception as e:  # no OCR language pack, old Windows, missing winrt
            log.info("screen reading unavailable: %s", e)
            self.status = "unavailable"
            return
        while not self._stop.is_set():
            self._stop.wait(POLL_S)
            if not self.enabled:
                continue
            try:
                self._once(loop)
            except Exception as e:  # never let a bad frame stop the thread
                log.debug("screen read failed: %s", e)
            if self.place_id and time.time() - self._at > STALE_S:
                self._clear()

    def _once(self, loop) -> None:
        rect = _game_rect()
        if not rect:
            self.status = "idle"
            self._clear()
            return
        l, t, r, b = rect
        w, h = r - l, b - t
        box = (l + int(w * CORNER[0]), t + int(h * CORNER[1]), l + int(w * CORNER[2]), t + int(h * CORNER[3]))
        pixels, bw, bh = _grab(box)
        text = loop.run_until_complete(_recognize(self._engine, pixels, bw, bh))
        pid = self.place_from_text(text)
        if not RE_MARK.search(text or ""):
            self.status = "no_text"
            self._clear()
            return
        self.status = "reading"
        if pid and pid == self._last:
            self.place_id, self._at = pid, time.time()
            with self.tracker._lock:
                self.tracker.screen = {"place_id": pid, "at": self._at}
        self._last = pid

    def place_from_text(self, text: str | None) -> str | None:
        """The most precise place named on a zone/location line, else in any line."""
        if not text:
            return None
        best: str | None = None
        for line in text.splitlines():
            m = RE_ZONE.search(line.strip())
            if not m:
                continue
            for token in re.split(r"[\s,;|()]+", m.group(1)):
                pid = self.places.named(token) if len(token) >= 4 else None
                if pid and (not best or pid.count("/") > best.count("/")):
                    best = pid
        return best


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


async def _recognize(engine, pixels: bytes, w: int, h: int) -> str:
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap  # type: ignore
    from winrt.windows.security.cryptography import CryptographicBuffer  # type: ignore

    buf = CryptographicBuffer.create_from_byte_array(pixels)
    bmp = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h)
    result = await engine.recognize_async(bmp)
    return "\n".join(line.text for line in result.lines)
