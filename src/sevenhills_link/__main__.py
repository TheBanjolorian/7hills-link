"""Entry point: `7HillsLink.exe`, or `python -m sevenhills_link`.

  --write-cfg <path>   (used by the client itself, elevated) add the telemetry lines to user.cfg
  --headless           run without a window, log status to the console
  --game-dir <path>    a Star Citizen folder to look in (repeatable): the StarCitizen folder,
                       a channel folder, StarCitizen.exe or a whole Wine prefix. Same as
                       SEVENHILLS_SC_DIR (separate several with the OS path separator).
  --port <n>           use only this telemetry port (default: the user.cfg port, then 2942).
                       Same as SEVENHILLS_SC_PORT.
  --updated <version>  (used by the updater) started by the previous version after an update
  --autostart          (used by the Windows Run entry) start hidden in the tray, no music
  --install-to <exe> --wait <pids> --from-version <v>   (used by the updater) put this exe in place of <exe>
  --installed          (used by the installer) first start of the installed copy
  --remove-old <exe>   (used by the installer) delete the copy it was installed from
  --screen-test [picture]   read the debug text in a saved screenshot of the game window (or,
                       without a picture, in the top-right corner of the main screen right now),
                       the way the running client reads the screen, and print what it found as
                       JSON (also written to screen-test.json in the data folder). Exit code 0
                       read, 3 no Windows text recognition on this PC. Nothing is sent anywhere.
  --version
"""

from __future__ import annotations

import sys
from pathlib import Path


def _take_game_dirs(argv: list[str]) -> list[str]:
    """Remove --game-dir <path> / --game-dir=<path> from argv and return the paths."""
    dirs: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--game-dir" and i + 1 < len(argv):
            dirs.append(argv[i + 1])
            del argv[i:i + 2]
        elif a.startswith("--game-dir="):
            dirs.append(a.split("=", 1)[1])
            del argv[i]
        else:
            i += 1
    return dirs


def _take_port(argv: list[str]) -> str | None:
    """Remove --port <n> / --port=<n> from argv and return n."""
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        if a.startswith("--port="):
            del argv[i]
            return a.split("=", 1)[1]
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import __version__

    game_dirs = _take_game_dirs(argv)
    if game_dirs:
        import os
        from .detect import ENV_DIR
        old = [p for p in os.environ.get(ENV_DIR, "").split(os.pathsep) if p]
        os.environ[ENV_DIR] = os.pathsep.join(game_dirs + old)

    port = _take_port(argv)
    if port:
        import os
        from .gamecfg import PORT_ENV
        os.environ[PORT_ENV] = port

    if "--version" in argv:
        print(__version__)
        return 0

    if "--screen-test" in argv:
        from . import screen
        i = argv.index("--screen-test")
        picture = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
        return screen.check_screenshot(picture)

    if "--install-to" in argv:
        from . import updater

        def arg(flag, default=""):
            i = argv.index(flag) if flag in argv else -1
            return argv[i + 1] if 0 <= i < len(argv) - 1 else default
        pids = [int(p) for p in arg("--wait").split(",") if p.strip().isdigit()]
        return updater.install_to(Path(arg("--install-to")), pids, arg("--from-version", "?"))

    if "--write-cfg" in argv:
        from . import gamecfg
        i = argv.index("--write-cfg")
        path = Path(argv[i + 1]) if i + 1 < len(argv) else None
        if not path or path.name.lower() != "user.cfg":
            return 2
        gamecfg.apply(path)
        return 0

    if "--headless" in argv:
        import json
        import threading
        import time
        from .core import Core
        core = Core()
        threading.Thread(target=core.run, daemon=True).start()
        try:
            while True:
                time.sleep(5)
                print(json.dumps(core.status()), flush=True)
        except KeyboardInterrupt:
            core.stop()
        return 0

    updated_from = None
    if "--updated" in argv:
        i = argv.index("--updated")
        updated_from = argv[i + 1] if i + 1 < len(argv) else "?"
        from . import updater
        updater.mark_ready()   # the swap script waits for this before it removes the backup

    from . import instance
    from .log import log, setup
    setup()
    # One 7Hills Link at a time. After an install or update the old one may still be closing.
    waiting = "--installed" in argv or updated_from is not None
    if not instance.acquire(wait=15.0 if waiting else 0.0):
        if "--autostart" not in argv:
            instance.signal_running()   # show the window of the one that runs
        log.info("already running; %s", "stayed hidden" if "--autostart" in argv else "showed its window")
        return 0
    log.info("start %s %s", __version__, " ".join(argv))
    if "--remove-old" in argv:
        from .install import remove_old_copy
        i = argv.index("--remove-old")
        if i + 1 < len(argv):
            remove_old_copy(argv[i + 1])

    from .app import run_window
    return run_window(updated_from, autostart="--autostart" in argv)


if __name__ == "__main__":
    sys.exit(main())
