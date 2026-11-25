"""Updates 7Hills Link from the GitHub releases of this repository.

1. check(): asks api.github.com for the latest release; newer than this build?
2. download(): fetches 7HillsLink.exe to %LOCALAPPDATA%\\7HillsLink\\update\\ and checks
   its SHA-256 against the release (the asset digest GitHub reports, or the
   7HillsLink.exe.sha256 file the build uploads). A file that does not match is deleted.
3. install(): only in the packaged exe. Starts the downloaded exe with
   --install-to and exits; that process (install_to) waits for this one to
   close, copies itself over the old exe (kept as 7HillsLink.old.exe), starts it
   with --updated and waits for its "ready" marker; if none appears within 20 s
   it puts the old exe back. Steps go to update\\update.log.
4. cleanup(): the new process removes 7HillsLink.old.exe at startup.

Downloads come only from github.com / objects.githubusercontent.com over HTTPS.
Once releases are code-signed, install() will also require the 7Hills AB signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .paths import data_dir

REPO = "TheBanjolorian/7hills-link"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "7HillsLink.exe"
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


class UpdateError(Exception):
    pass


def parse_version(v: str) -> tuple[int, ...]:
    v = (v or "").strip().lstrip("vV").split("-")[0]
    out = []
    for part in v.split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _get(url: str, timeout: float = 15.0) -> bytes:
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or not (host == "api.github.com" or host in ALLOWED_HOSTS):
        raise UpdateError(f"Refusing to download from {host or url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"7HillsLink/{__version__}", "Accept": "application/octet-stream, application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        final = urllib.parse.urlparse(r.geturl()).hostname or ""
        if final != "api.github.com" and final not in ALLOWED_HOSTS:
            raise UpdateError(f"Redirected to {final}")
        return r.read()


def check() -> dict | None:
    """{version, url, sha256 or None, sha256_url or None, notes} for a newer release, else None."""
    data = json.loads(_get(API))
    tag = data.get("tag_name") or ""
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    assets = {a.get("name"): a for a in data.get("assets") or []}
    exe = assets.get(ASSET)
    if not exe:
        return None
    digest = exe.get("digest") or ""
    sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
    side = assets.get(ASSET + ".sha256")
    return {"version": tag.lstrip("vV"), "url": exe.get("browser_download_url"), "sha256": sha,
            "sha256_url": side.get("browser_download_url") if side else None, "size": exe.get("size")}


def update_dir() -> Path:
    d = data_dir() / "update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(info: dict) -> Path:
    want = info.get("sha256")
    if not want and info.get("sha256_url"):
        want = _get(info["sha256_url"]).decode("ascii", "replace").split()[0].strip().lower()
    if not want or len(want) != 64:
        raise UpdateError("The release has no checksum; not installing it")
    blob = _get(info["url"], timeout=120)
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise UpdateError("Downloaded file does not match the release checksum")
    path = update_dir() / f"7HillsLink-{info['version']}.exe"
    tmp = path.with_suffix(".part")
    tmp.write_bytes(blob)
    os.replace(tmp, path)
    for old in update_dir().glob("7HillsLink-*.exe"):
        if old != path:
            try:
                old.unlink()
            except OSError:
                pass
    return path


def can_install() -> bool:
    """Only the packaged exe replaces itself; running from source never does."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def _ready_marker() -> Path:
    return update_dir() / "ready"


def mark_ready() -> None:
    """Called by a freshly updated process once it is up."""
    try:
        _ready_marker().write_text(str(os.getpid()))
    except OSError:
        pass


def _log(msg: str) -> None:
    try:
        with open(update_dir() / "update.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _copy_retry(src: Path, dst: Path, tries: int = 40) -> bool:
    import shutil
    for _ in range(tries):
        try:
            shutil.copyfile(src, dst)
            return True
        except OSError:
            time.sleep(0.5)
    return False


def _start(exe: Path, *args: str):
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen([str(exe), *args], close_fds=True, creationflags=flags, cwd=str(exe.parent))


def install_to(target: Path, wait_pids: list[int], from_version: str) -> int:
    """Run by the NEW exe (from the update folder): put itself in place of the old one.

    Waits for the old 7Hills Link to exit, keeps it as 7HillsLink.old.exe, copies
    this exe over it, starts it with --updated and waits for its "ready" marker.
    If none comes within 20 s, the old exe is put back and started.
    """
    me = Path(sys.executable).resolve()
    target = Path(target)
    backup = target.with_name(target.stem + ".old.exe")
    _log(f"installing {__version__} over {from_version} at {target}")
    deadline = time.time() + 30
    while time.time() < deadline and any(_pid_alive(p) for p in wait_pids):
        time.sleep(0.25)
    time.sleep(0.5)
    if not _copy_retry(target, backup, tries=10):
        _log("could not keep a backup; leaving the old version in place")
        _start(target)
        return 1
    # Logged, because the new version removes the backup again soon after it starts (cleanup()).
    _log(f"kept {backup.name}")
    if not _copy_retry(me, target):
        _log("could not replace the exe; starting the old one")
        _start(target)
        return 1
    try:
        _ready_marker().unlink()
    except OSError:
        pass
    proc = _start(target, "--updated", from_version)
    for _ in range(40):
        if _ready_marker().exists():
            _log("updated")
            return 0
        time.sleep(0.5)
    _log("new version did not start; restoring the old one")
    try:
        proc.kill()
    except OSError:
        pass
    time.sleep(0.8)
    _copy_retry(backup, target)
    _start(target)
    return 2


def install(new_exe: Path) -> bool:
    """Start the downloaded exe as the installer and let this app exit.

    A running exe (and PyInstaller's open archive) cannot be replaced, so the
    new exe does the swap once this one has closed (see install_to). No script
    engine is involved. Returns True: the caller should exit now.
    """
    if not can_install():
        raise UpdateError("Updates install only in the packaged 7HillsLink.exe")
    current = Path(sys.executable).resolve()
    if not os.access(current.parent, os.W_OK):
        raise UpdateError(f"Cannot write to {current.parent}. Move 7HillsLink.exe to a folder of yours, e.g. Downloads.")
    pids = [os.getpid()]
    try:
        pids.append(os.getppid())   # PyInstaller's launcher process
    except Exception:
        pass
    _log(f"{__version__}: handing over to {Path(new_exe).name}")
    try:
        _start(Path(new_exe), "--install-to", str(current), "--wait", ",".join(map(str, pids)), "--from-version", __version__)
    except OSError as e:
        _log(f"could not start the installer: {e}")
        raise UpdateError(f"Could not start the installer: {e}") from e
    return True


def cleanup() -> None:
    """Remove the previous exe after an update (retry a few times while it exits)."""
    if not can_install():
        return
    old = Path(sys.executable).resolve().with_name(Path(sys.executable).stem + ".old.exe")
    for _ in range(20):
        if not old.exists():
            return
        try:
            old.unlink()
            return
        except OSError:
            time.sleep(0.5)
