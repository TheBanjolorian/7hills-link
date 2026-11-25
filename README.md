# 7Hills Link

Desktop client for [7Hills Industries](https://www.7hills.space). It reads Star Citizen's own local game telemetry and sends it to 7Net, so you can see your ship and vitals on your phone or a second screen at **7hills.space/live**, and choose what Org Command sees: nothing, only that you are online (default), or your full status.

**Download:** [7HillsLink.exe](https://github.com/TheBanjolorian/7hills-link/releases/latest/download/7HillsLink.exe) (Windows 10/11). The exe is not code-signed yet, so Windows SmartScreen asks once: *More info → Run anyway*.

**Linux:** runs natively from source with the game in Wine/Proton (LUG helper, Lutris, Steam). Tested on LIVE with KDE Plasma on Wayland. See [Linux (Wine / Proton)](#linux-wine--proton).

## What it does

1. **Finds Star Citizen** (running game, RSI Launcher files, common install folders) — LIVE, PTU and the other channels. If it misses one, pick `StarCitizen.exe` for that channel under Settings → Game.
2. **Switches on the game's telemetry** when you press *Switch on*: adds three lines to `StarCitizen\<channel>\user.cfg` and sets `GRPC_CLIENT_SERVER_ENABLED=true` for your Windows user. Nothing else in the file changes. Restart the game afterwards.
   ```
   grpc.client.server.enabled = 1
   grpc.client.server.port = 50051
   server.game.telemetry.enabled = 1
   ```
3. **Reads the API definitions from your installed `StarCitizen.exe`**, so it keeps working after patches.
4. **Links this PC to your 7Net account**: shows a code, opens 7hills.space/link, you press *Connect this PC*. The key is stored in Windows Credential Manager. Only approve a code that this app shows on the PC in front of you. *Unlink this PC* (Settings → Account) makes 7Net stop accepting the key before the app forgets it; you can also unlink any PC on 7hills.space under **Profile → PCs**. You can have 5 PCs linked (linking a sixth unlinks the one unused longest), a PC not used for 90 days is unlinked on its own, and linking the same installation again replaces its old key. When a PC is unlinked the app says why and asks you to link it again.
5. **Streams** from the game's local server (`127.0.0.1`, the `user.cfg` port or 2942, never exposed to the network) and sends the state to 7Net as soon as it changes (at most four times a second).
7. **Installs itself** on first start to `%LOCALAPPDATA%\Programs\7HillsLink` (no admin rights) with Start menu and desktop shortcuts, and runs **one copy at a time**: starting it again shows the window of the one that runs. Quit with the power button in the window or from the tray. Its log is `%LOCALAPPDATA%\7HillsLink\link.log` (native crashes in `crash.log`).
6. **Runs in the tray**: minimizing or closing hides the window behind a gold 7 in the notification area; quit from its menu. It starts with Windows (hidden, no music) unless you switch that off under Settings.
8. **Works out where you are** (from v0.5.0) by reading `Game.log` in the channel folder (`StarCitizen\<channel>\Game.log`), only reading, never writing. It picks one place from [`data/places.json`](src/sevenhills_link/data/places.json): the landing area you stand in (city, station, rest stop, gateway), else the planet, moon or belt you are at, else a planet company's jurisdiction, else the system. Only that place id, how sure it is, armistice yes/no, the shard and the game's own location number go to 7Net, never log lines. Your position goes with it only if you turn on **Share exact position** (point 11). From v0.6.0 the place is joined with the telemetry: one more word says what you are doing there (`landed`, `flying`, `space`, `on_foot` or `eva`, see [`situation.py`](src/sevenhills_link/situation.py)), so /live reads "Flying at Cellin, 940 m above the ground". The place list is built from the game files by 7Net's `scripts/live-map/build-places.py`.
9. **What it reads in `Game.log`** (v0.7.2, see the top of [`location.py`](src/sevenhills_link/location.py)):
   - **The game's own location number** (`<Update Inventory Location> … Location [a] -> [b]`), written at login and every time you cross into another place. A number is the same place on every shard, so [`data/location_ids.json`](src/sevenhills_link/data/location_ids.json) lists the ones seen so far, and every pair your own log gives is remembered in `%LOCALAPPDATA%\7HillsLink\locations.json`: a number with a landing area's name, or with a route's start location. That file stays on your PC.
   - **The landing area by its own name** (`RR_P6_LEO` is Ruin Station, `RR_JP_PyroStanton` the Stanton Gateway in Pyro). A landing area that is not on the place list still gives the moon, belt or system in its name (`Outpost_OLP_Stanton2b_Lamina` is on Daymar). From v0.7.3 the place list holds 212 outposts, shelters and security posts in Stanton: one is named when the words of its landing name fit exactly one of them (`Stanton2b_ShubinMining_SCD1` is Shubin Mining Facility SCD-1), and the screen's location line names them as the game shows them.
   - **Where the ship you plot a route on is** (`Projected Start Location is Daymar`), the planet or moon whose ground is loaded (every ten minutes), and jurisdiction and armistice notices.
   - **The route you plotted**: the target you picked on the ship you fly, until that ship arrives. Sent as the route's two ends, as place ids. The log has no line for the jump itself, so the client never says "in quantum": 7Net takes that from the ship's telemetry. The "Quantum Travel Calibration …" notices are not used (they go to the whole party wherever each member is), and other ships arriving nearby are ignored.
   - One short line about the newest of these ("Landed at Ruin Station", "Plotted a route to Crusader"). Never another player's name.
10. **The place from the screen** (from v0.7.0, Windows; reworked in v0.7.2): with `r_displayinfo 3` typed in the game console, the game prints debug text in the top-right corner. While you share **Full** and the game window is in front, the client looks at a 760 × 420 px box in that corner every two seconds (every ten once the debug text has not been there for a while), reads the text with Windows' own OCR on your PC and takes the place from it: the landing area on the "Current player location" line when the place list has it, else the planet, moon or belt among the "Zone" lines (counted once two readings agree). Only the debug block counts, so a mission text in that corner is never read as where you are, and the screen never replaces a station the log knows with the moon it sits on. No picture is kept or sent. The window says whether the screen is being read, and **Settings → Game → Test screen reading** shows what the last look found. `7HillsLink.exe --screen-test picture.png` reads a saved screenshot of the game window the same way (without a picture: the main screen as it is now) and writes what it found to `screen-test.json` in `%LOCALAPPDATA%\7HillsLink`: the place, the lines that bear on it with their numbers taken out, and how each way of reading went (which box, enlarged how many times, prepared how, how long it took). No position, session or server name is written down. The build runs this on a drawn copy of a real screen ([`tools/make_debug_screenshot.py`](tools/make_debug_screenshot.py)) at 2560 × 1440 and 1920 × 1080, so every release has read the debug text with Windows' own OCR; how it reads (see the top of [`screen.py`](src/sevenhills_link/screen.py)) was settled from those runs.
11. **Your exact position** (from v0.8.0, Windows, **off unless you turn it on**: Settings → Game → *Share exact position*). The same debug text has a line for the planet or moon you are at, `Zone: OOC_Stanton_2a_Cellin Pos: x y z`: where you are, counted from that body's middle. With the setting on, the client works out latitude, longitude and height from it on your PC ([`position.py`](src/sevenhills_link/position.py)) and sends those three numbers and the body with your place, so the 7Net map can show a dot where you stand or fly and not only which place you are at. A reading counts only when it checks out against the rest of the screen (the distance from the middle must equal the `Radius` line's radius plus height, the side of the body must match the `XYPos` line) and lies close to the reading before it, so a misread digit is thrown away instead of sent. The numbers on the screen themselves, and the solar-system, session and server lines, are never sent or written down. 7Net keeps only your latest position, shows it to the same people who see your place (your party; Org Command while you share Full), and draws it for two minutes. Without the debug text on screen, or in open space, there is no position and the map shows your place as before. *Test screen reading* shows the position the last look gave whether or not you share it.

Who sees your place: you on /live, Org Command (manager and up) when you share **Full**, and the members of a party or event squad you are in while it shares its map, unless you hide your place there. The place reaches 7Net in every sharing mode; *Off* and *Online only* decide what Org Command sees, and a party you join sees what its lead chose whatever is set here.

## Linux (Wine / Proton)

The client runs natively on Linux from source (see *Run from source*; use `export PYTHONPATH=src`). The game's telemetry server listens on the host's loopback through Wine, so the native client can reach it. Tested on CachyOS (KDE Plasma, Wayland) with a LUG helper prefix on 4.x LIVE.

- **Finding the game:** it looks inside the usual prefixes (`$WINEPREFIX`, `~/Games/star-citizen` from the LUG helper, other `~/Games/*` Lutris prefixes, Steam/Proton `compatdata/*/pfx`, `~/.wine`), reads the RSI Launcher's files inside them, and maps the running `StarCitizen.exe` back to its folder. If it misses yours, point it there:
  ```
  python -m sevenhills_link --game-dir ~/Games/star-citizen
  # or
  export SEVENHILLS_SC_DIR=~/Games/star-citizen
  ```
  Either takes the Wine prefix, the `StarCitizen` folder, a channel folder (`.../StarCitizen/PTU`) or `StarCitizen.exe` itself. `--game-dir` can be repeated; separate several folders in the variable with `:`.
- **`user.cfg`:** *Switch on* writes the three lines as on Windows. No admin prompt is needed, the prefix is yours.
- **Port:** 4.x LIVE ignores `grpc.client.server.port` and always serves on `2942`; the client tries the `user.cfg` port first and then 2942, and stays on whichever answers. To force one: `--port 2942` or `SEVENHILLS_SC_PORT=2942`.
- **`GRPC_CLIENT_SERVER_ENABLED`:** must be in the game's launch environment; the client cannot set it for you. Add `export GRPC_CLIENT_SERVER_ENABLED=true` to your launch script, or set it under Lutris → Configure → System options → Environment variables, or use Steam launch options `GRPC_CLIENT_SERVER_ENABLED=true %command%`. The client checks the running game's environment and shows a hint until it sees the variable there.
- **One copy, tray and autostart:** as on Windows it runs one copy at a time (a lock file; a second start shows the running window). *Start when you log in* writes `~/.config/autostart/7hills-link.desktop`. The tray icon needs PyGObject (in `requirements.txt`; first install your distro's `gobject-introspection`, `cairo` and `libayatana-appindicator` packages) and an AppIndicator/StatusNotifier host (most desktops; GNOME needs the AppIndicator extension). Without PyGObject pystray falls back to X11, where the icon can't be clicked under KDE Wayland, so the window is then never hidden to the tray. Updates are not installed automatically when running from source; `git pull` instead.
- Check what the game listens on with `ss -ltnp | grep -E '2942|50051'` while in game. Report problems in [issue #1](https://github.com/TheBanjolorian/7hills-link/issues/1).

## What the game's telemetry offers

See **[docs/TELEMETRY.md](docs/TELEMETRY.md)** for everything we have found: how to switch it on, every field you can read, the actions you can send to the game, and how the API definitions are read from the exe. Useful if you want to build your own tool (button boxes, Joystick Gremlin, dashboards).

## Updates

From v0.4.0 the client checks this repository's latest release at start and every 6 hours, downloads a newer `7HillsLink.exe` and checks its SHA-256 against the release. It installs by itself when the game is not running (you can switch that off under Settings and press *Restart now* instead). The client starts the downloaded exe as the installer and closes; the new exe copies itself over the old one (kept as `7HillsLink.old.exe`), starts, and puts the old one back if it does not start within 20 seconds. The steps are logged in `%LOCALAPPDATA%\7HillsLink\update\update.log`. v0.4.0 to v0.4.3 may not update themselves; install v0.4.4 or later by hand once. Keep the exe in a folder you can write to, such as Downloads or Desktop.

## What it does not do

- It does not read game memory, inject anything, or touch Easy Anti-Cheat. It only uses the telemetry server the game itself provides.
- It does not send commands to the game (yet).
- Live data on 7Net is deleted after 24 hours. Org Command sees what you choose: *Off*, *Online only* (default: your name and "in game") or *Full* (ship, seat, status, health and vitals, and where you are). The aUEC balance is removed before anything is uploaded (from v0.6.1).

## Run from source

```
pip install -r requirements.txt        # Linux: also "pywebview[qt]"
set PYTHONPATH=src                     # Linux/macOS: export PYTHONPATH=src
python -m sevenhills_link            # window
python -m sevenhills_link --headless
```

Tests: `PYTHONPATH=src python -m pytest -q tests`. Builds: GitHub Actions builds `7HillsLink.exe` on every push; every push to `main` publishes the release for the version in `src/sevenhills_link/__init__.py`.
