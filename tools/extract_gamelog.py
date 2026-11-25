#!/usr/bin/env python3
"""Cut a Game.log down to the lines 7Hills Link reads for the place, with names replaced.

    python tools/extract_gamelog.py Game.log [more.log ...] > session.log

For test data (tests/data/) and for sending a session to someone who is looking into
why a place came out wrong: the result holds no chat, no mission text, no account
or server addresses, and no handles.

Kept: joining a server (shard only), the location number changes, landing areas by
name, the ship navigation lines (target picked, route start, arrival), jurisdiction,
armistice and quantum notices, and the physics block's planet lines that have ground
loaded. Your own handle becomes TestPilot; every other name in a notice becomes
PartyMember1, PartyMember2 ... in order of appearance. The ids of ships, party
markers and mission beacons in the navigation lines become stand-ins (900000000001,
900000000002 ...), the same stand-in for the same id. Location numbers are the game's
own number for a place, the same for everyone, so they stay.
"""

from __future__ import annotations

import re
import sys

KEEP_NOTICE = re.compile(r'Added notification "((?:Entered|Exited) .*?Jurisdiction|(?:Entering|Leaving) Armistice Zone[^"]*'
                         r'|Quantum Travel Calibration (?:Started|Complete) By [^":]*'
                         r'|[^":]* has started to QT to your current location\.?)[:\s]*"')
NAV = re.compile(r"CSCItemNavigation::(OnPlayerSelectedQuantumTarget|OnQuantumDriveArrived|CalculateRoute)\|")
TS = re.compile(r"^<\d{4}-\d\d-\d\dT[\d:.]+Z>")
ENTITY_ID = re.compile(r"\d{9,}")        # in a navigation line: a ship, a party member's marker, a mission beacon


class Names:
    def __init__(self) -> None:
        self.me: str | None = None
        self.others: dict[str, str] = {}
        self.ids: dict[str, str] = {}

    def entity(self, number: str) -> str:
        """The stand-in for a ship's, marker's or beacon's id: the same one every time."""
        return self.ids.setdefault(number, str(900000000001 + len(self.ids)))

    def other(self, name: str) -> str:
        name = name.strip()
        if not name:
            return name
        if self.me and name.lower() == self.me.lower():
            return "TestPilot"
        return self.others.setdefault(name, f"PartyMember{len(self.others) + 1}")


def extract(lines, names: Names | None = None):
    """Yield the kept lines of one log, anonymised."""
    names = names or Names()
    for line in lines:
        line = line.rstrip("\r\n")
        if not TS.match(line):
            continue
        m = re.search(r"<Legacy login response>.*?Handle\[([^\]]+)\]", line)
        if m:
            names.me = m.group(1)
            continue
        if "<Join PU>" in line:
            yield re.sub(r"address\[[^\]]*\] port\[[^\]]*\]", "address[0.0.0.0] port[0]", line)
        elif "<Update Inventory Location>" in line:
            yield re.sub(r"Player \[[^\]]*\]", "Player [TestPilot]", line)
        elif "<RequestLocationInventory>" in line:
            yield re.sub(r"Player\[[^\]]*\]", "Player[TestPilot]", line)
        elif NAV.search(line):
            if "CalculateRoute|" in line and "Projected Start Location" not in line:
                continue
            yield ENTITY_ID.sub(lambda m: names.entity(m.group(0)), line)
        elif "<SHUDEvent_OnNotification> Added notification" in line:
            m = KEEP_NOTICE.search(line)
            if not m:
                continue
            text = m.group(1)
            who = re.match(r"Quantum Travel Calibration (Started|Complete) By (.*)$", text)
            if who:
                text = f"Quantum Travel Calibration {who.group(1)} By {names.other(who.group(2))}"
            who = re.match(r"(.*) has started to QT to your current location", text)
            if who:
                text = f"{names.other(who.group(1))} has started to QT to your current location."
            stamp = TS.match(line).group(0)
            yield f'{stamp} [Notice] <SHUDEvent_OnNotification> Added notification "{text}: " [0] to queue. New queue size: 1 [Team_CoreGameplayFeatures][Missions][Comms]'
        elif "PHYSICS INSTANCE STATS" in line:
            yield line
        elif "planet cells:" in line and re.search(r"planet cells:\s*[1-9]", line):
            yield line


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    names = Names()
    for path in argv:
        with open(path, encoding="utf-8", errors="replace") as f:
            for out in extract(f, names):
                print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
