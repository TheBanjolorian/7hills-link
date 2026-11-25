# Test sessions

`sessions_2026-11.log` is seven real play sessions on 4.10 LIVE (build 13220821, 21 to 24
November 2026, 12.6 hours in the PU, six logins), cut down with
[`tools/extract_gamelog.py`](../../tools/extract_gamelog.py) to the lines 7Hills Link reads
for the place: joining a server, the location number changes, landing areas by name, the
ship navigation lines, jurisdiction, armistice and quantum notices, and the planet whose
ground is loaded.

Nothing personal is in it: the player's handle is `TestPilot`, party members are
`PartyMember1` … `PartyMember7`, server addresses are zeroed, the ids of ships, party
markers and mission beacons are stand-ins (`900000000001` …), and chat, missions and
everything else is left out. The location numbers are the game's own number for a
place, the same for every player. The times are the real ones.

What happens in it, for reading the tests ([`test_sessions.py`](../test_sessions.py)):

| When (UTC) | What |
|---|---|
| 21 Nov 18:23 – 18:50 | Three logins at Ruin Station (Pyro) |
| 21 Nov 18:56 | Login aboard a ship in open space in Pyro; it arrives at the Stanton Gateway at 19:02 |
| 21 Nov 19:10 | Login at that gateway, through the jump point to Stanton at 19:15, quantum to a party member on Daymar at 19:16 |
| 21 Nov 19:20 – 21:10 | On Daymar: outposts Lamina and Shubin SCD-1. Party members calibrate their own jumps all evening |
| 21 Nov 21:10 – 21:26 | Route plotted to microTech, changed to Crusader, arrival 21:20, six minutes there |
| 21 Nov 21:26 – 01:44 | Back on Daymar until the session ends |
| 23 Nov 17:58 | Login on Daymar. Two mission jumps, mission sites in Crusader's jurisdiction |
| 23 Nov 18:51 – 18:57 | Stanton → Nyx through the gateways `RR_JP_StantonMagnus` and `RR_JP_NyxCastra` (no route plotted on this PC) |
| 23 Nov 19:00 – 23:20 | Nyx: open space, two bases, the Pyro Gateway, a jump to the Glaciem Ring |

To add a session: `python tools/extract_gamelog.py Game.log > tests/data/<name>.log`, and read
the result before committing it.
