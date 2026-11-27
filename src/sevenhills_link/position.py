"""Where on a planet or moon the player is, from the `r_displayinfo` text on screen.

Next to the place (screen.py), the debug block gives a position inside each zone:

    Zone: OOC_Stanton_2a_Cellin Pos: -102.1047km -72.5157km -228.7069km
    Zone: SolarSystem_926655998358 Pos: -18987729.9791km -2708970.2118km -228.7069km
    ...
    Planet:OOC_Stanton_2a_Cellin  (Load Complete)
    Radius: 260000.000000 ElevationUnderCam: 748.671875 Altitude 1.714687
    XYPos: -116075.242613 -82437.771268 Page: 5 (-Z)

The line of the planet or moon is a position from that body's middle, in a frame that
turns with the body: the same spot on the ground always has the same numbers. From it
this module works out latitude, longitude and height.

From 0.9.0 the "SolarSystem" line is read too: the position in the solar system's own
frame, in km. It is what says where the player is in open space, away from any planet or
moon, so a bookmark or a waypoint can be saved there (7Net works out the nearest quantum
travel point from it). Session and server names are not read here.

Text recognition can misread a digit, and a wrong digit would put the player somewhere
else entirely. So a position counts only when it checks out against the rest of the
same screen:

  - the distance from the body's middle must equal Radius + ElevationUnderCam +
    Altitude from the "Radius:" line (a misread digit breaks this);
  - the side of the body named on the "XYPos:" line, "(-Z)", must be the side the
    position is on (a lost minus sign on the largest number breaks this);
  - screen.py then wants two readings in a row that lie close together (a lost minus
    sign on one of the smaller numbers breaks this, unless it is lost every time).

The course (which way the player is moving, as a compass bearing) is worked out by
screen.py from two positions at least 20 m apart; standing still keeps the last one.

What leaves the PC, and only while "Share exact position" is on: the body's place id,
latitude and longitude to three decimals, the height in metres, the course in whole
degrees and the body's radius in km; and, from 0.9.0, the position in the solar system's
frame as three numbers in km to one decimal (`system_position`). Nothing is written down
on this PC, and 7Net keeps only the latest.
"""

from __future__ import annotations

import math
import re

# A number with its unit, as the block writes it ("-102.1047km", "-2089.02m"). The minus
# sign can come back as another dash; "km" as "krn" or "kn" and "m" as "n"; a zero as "ø"
# or "O"; a space after the decimal point.
_NUM = r"([-−–—~]?)\s?([0-9øØOo]+(?:[.,]\s?[0-9øØOo]+)?)\s?(km|krn|kn|k\s?m|m|n)\b"
RE_ZONE_POS = re.compile(r"Z[o0]ne\s*[^\w\s-]?\s*(\S.*?)\s+P[o0]s\s*[^\w\s-]?\s*(.*)$", re.I)
RE_NUM = re.compile(_NUM, re.I)
_PLAIN = r"([-−–—~]?\s?[0-9øØOo]+(?:[.,][0-9øØOo]+)?)"
# The colon after a word can come back as any mark ("ElevationUnderCam?").
RE_RADIUS = re.compile(r"Radius\s*[^\w\s-]?\s*" + _PLAIN + r".*?Elevati[o0]nUnderCam\s*[^\w\s-]?\s*" + _PLAIN + r".*?Altitude\s*[^\w\s-]?\s*" + _PLAIN, re.I)
RE_PAGE = re.compile(r"Page\s*[:;.]?\s*\S+\s*[(\[{]\s*([-+−–—~])\s*([XYZ])\s*[)\]}]?", re.I)

TOLERANCE = 0.002        # the distance check: 0.2 % of the radius (about 500 m on a moon)
MIN_TOLERANCE_M = 150.0
MAX_ALT_FACTOR = 3.0     # further out than this many radii is not "on" the body


def _digits(s: str) -> str:
    return s.replace("ø", "0").replace("Ø", "0").replace("O", "0").replace("o", "0").replace(",", ".")


def _plain(s: str) -> float | None:
    s = _digits(s.replace(" ", ""))
    neg = s[:1] in "-−–—~"
    try:
        v = float(s.lstrip("-−–—~"))
    except ValueError:
        return None
    return -v if neg else v


def zone_positions(text: str | None) -> list[tuple[str, tuple[float, float, float]]]:
    """Every "Zone: NAME Pos: x y z" line that has three numbers, as (name, metres)."""
    out = []
    for line in (text or "").splitlines():
        m = RE_ZONE_POS.search(line.strip())
        if not m:
            continue
        nums = RE_NUM.findall(m.group(2))
        if len(nums) != 3:
            continue
        xyz = []
        for sign, digits, unit in nums:
            try:
                v = float(_digits(digits.replace(" ", "")))
            except ValueError:
                break
            if unit.lower().replace(" ", "") not in ("m", "n"):
                v *= 1000.0
            xyz.append(-v if sign else v)
        if len(xyz) == 3:
            out.append((m.group(1), (xyz[0], xyz[1], xyz[2])))
    return out


def radius_line(text: str | None) -> tuple[float, float, float] | None:
    """(radius, elevation of the ground, height above the ground) in metres, from the "Radius:" line."""
    for line in (text or "").splitlines():
        m = RE_RADIUS.search(line)
        if m:
            vals = [_plain(g) for g in m.groups()]
            if None not in vals and vals[0] and vals[0] > 1000:
                return vals[0], vals[1], vals[2]   # type: ignore[return-value]
    return None


def page_side(text: str | None) -> tuple[int, int] | None:
    """The side of the body the "XYPos:" line names: (axis 0-2, sign +1 or -1)."""
    for line in (text or "").splitlines():
        m = RE_PAGE.search(line)
        if m:
            return "XYZ".index(m.group(2).upper()), 1 if m.group(1) == "+" else -1
    return None


def lat_lon(x: float, y: float, z: float) -> tuple[float, float, float]:
    """(latitude, longitude in degrees, distance from the middle) of a point in the body's frame."""
    r = math.sqrt(x * x + y * y + z * z)
    return math.degrees(math.asin(max(-1.0, min(1.0, z / r)))), math.degrees(math.atan2(y, x)), r


def body_position(text: str | None, places) -> dict | None:
    """The position the debug block gives, or None when it gives none that checks out.

    {"body": place id of the planet or moon, "lat", "lon" (degrees), "alt" (metres above
    the body's radius), "radius" (metres, for comparing two readings; not sent),
    "checked": which checks it passed}. `places` is location.Places.
    """
    rad = radius_line(text)
    if not rad:
        return None
    radius, elevation, altitude = rad
    for name, (x, y, z) in zone_positions(text):
        pid = places.named(name) or places.hint(name)
        if not pid or places.kind(pid) not in ("planet", "moon"):
            continue
        lat, lon, dist = lat_lon(x, y, z)
        if dist <= 0 or dist > radius * MAX_ALT_FACTOR:
            return None
        if abs(dist - (radius + elevation + altitude)) > max(MIN_TOLERANCE_M, radius * TOLERANCE):
            return None
        checked = ["distance"]
        side = page_side(text)
        if side:
            axis, sign = side
            v = (x, y, z)
            # Only when that axis clearly is the largest: near an edge of a side either may be named.
            others = max(abs(c) for i, c in enumerate(v) if i != axis)
            if abs(v[axis]) > others * 1.05 and (v[axis] > 0) != (sign > 0):
                return None
            if abs(v[axis]) >= others * 0.95:
                checked.append("side")
        return {"body": pid, "lat": round(lat, 3), "lon": round(lon, 3), "alt": round(dist - radius), "radius": radius, "checked": checked,
                "exact": (lat, lon)}     # unrounded, for the course between two readings; not sent
    return None


RE_SYSTEM = re.compile(r"^S[o0]lar\s?System", re.I)
SYSTEM_MAX_KM = 1e9            # further from the star than this is not a position
ROOT_SLACK_M = 1000.0          # the "Root" line repeats the system line: they must agree


def system_position(text: str | None) -> dict | None:
    """Where the player is in the solar system's own frame, from the "SolarSystem" zone line,
    or None when the block has none that checks out: {"x", "y", "z"} in km to one decimal,
    "checked": which checks it passed.

    The block usually repeats the same numbers on a "Root" line. When it is there the two
    must agree, which catches a misread digit; screen.py also wants two readings in a row
    that lie close together.
    """
    system = root = None
    for name, xyz in zone_positions(text):
        if RE_SYSTEM.match(name.strip()):
            system = system or xyz
        elif name.strip().lower() == "root":
            root = root or xyz
    if not system or max(abs(v) for v in system) / 1000.0 > SYSTEM_MAX_KM:
        return None
    checked = []
    if root is not None:
        if max(abs(a - b) for a, b in zip(system, root)) > ROOT_SLACK_M:
            return None
        checked.append("root")
    return {"x": round(system[0] / 1000.0, 1), "y": round(system[1] / 1000.0, 1), "z": round(system[2] / 1000.0, 1), "checked": checked}


def space_apart_km(a: dict, b: dict) -> float:
    """Kilometres between two positions in the solar system's frame."""
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2)


def apart_m(a: dict, b: dict) -> float:
    """Roughly how far apart two positions on the same body are, in metres."""
    radius_m = float(a.get("radius") or b.get("radius") or 300000.0)
    la, lb = math.radians(a["lat"]), math.radians(b["lat"])
    c = math.sin(la) * math.sin(lb) + math.cos(la) * math.cos(lb) * math.cos(math.radians(a["lon"] - b["lon"]))
    ground = math.acos(max(-1.0, min(1.0, c))) * (radius_m + max(0.0, min(a["alt"], b["alt"])))
    return math.hypot(ground, a["alt"] - b["alt"])


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The compass course from one (lat, lon) to another on the same body, 0-360, 0 = towards
    the body's north pole, 90 = east."""
    la, lb, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(lb)
    x = math.cos(la) * math.sin(lb) - math.sin(la) * math.cos(lb) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def ground_m(a: tuple[float, float], b: tuple[float, float], radius_m: float) -> float:
    """Metres along the ground between two (lat, lon) on a body of this radius."""
    la, lb = math.radians(a[0]), math.radians(b[0])
    c = math.sin(la) * math.sin(lb) + math.cos(la) * math.cos(lb) * math.cos(math.radians(a[1] - b[1]))
    return math.acos(max(-1.0, min(1.0, c))) * radius_m
