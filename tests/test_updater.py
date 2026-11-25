"""Updater: version checks, release parsing and checksum verification (no network)."""

import hashlib
import json

import pytest

from sevenhills_link import updater


def test_versions():
    assert updater.is_newer("v0.4.0", "0.3.0")
    assert updater.is_newer("0.10.0", "0.9.9")
    assert not updater.is_newer("v0.3.0", "0.3.0")
    assert not updater.is_newer("v0.2.9", "0.3.0")


def _release(tag, digest=None, sha_file=False):
    assets = [{"name": "7HillsLink.exe", "browser_download_url": "https://github.com/x/7HillsLink.exe", "size": 3}]
    if digest:
        assets[0]["digest"] = "sha256:" + digest
    if sha_file:
        assets.append({"name": "7HillsLink.exe.sha256", "browser_download_url": "https://github.com/x/7HillsLink.exe.sha256"})
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def test_check_and_download(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    blob = b"exe"
    good = hashlib.sha256(blob).hexdigest()
    pages = {updater.API: _release("v99.0.0", sha_file=True), "https://github.com/x/7HillsLink.exe": blob,
             "https://github.com/x/7HillsLink.exe.sha256": (good + "  7HillsLink.exe").encode()}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=15: pages[url])
    info = updater.check()
    assert info["version"] == "99.0.0" and info["sha256"] is None and info["sha256_url"]
    path = updater.download(info)
    assert path.read_bytes() == blob and path.name == "7HillsLink-99.0.0.exe"

    # Same version as this build: nothing to do.
    pages[updater.API] = _release("v" + updater.__version__, digest=good)
    assert updater.check() is None


def test_bad_checksum_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pages = {updater.API: _release("v99.0.0", digest="0" * 64), "https://github.com/x/7HillsLink.exe": b"evil"}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=15: pages[url])
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(updater.check())
    assert not list((tmp_path / "7HillsLink" / "update").glob("*.exe"))


def test_no_checksum_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pages = {updater.API: _release("v99.0.0")}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=15: pages[url])
    with pytest.raises(updater.UpdateError, match="no checksum"):
        updater.download(updater.check())


def test_only_github_hosts():
    with pytest.raises(updater.UpdateError):
        updater._get("https://evil.example/7HillsLink.exe")
    with pytest.raises(updater.UpdateError):
        updater._get("http://github.com/x")


def test_source_build_never_installs():
    assert updater.can_install() is False
    with pytest.raises(updater.UpdateError):
        updater.install(updater.update_dir() / "x.exe")


def _fake_install(tmp_path, monkeypatch, new_starts: bool):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    target = tmp_path / "app" / "7HillsLink.exe"
    target.parent.mkdir()
    target.write_bytes(b"old")
    new = tmp_path / "7HillsLink-9.9.9.exe"
    new.write_bytes(b"new")
    started = []

    class P:
        def kill(self):
            started.append("killed")

    def fake_start(exe, *args):
        started.append((exe.read_bytes(), args))
        if new_starts and args[:1] == ("--updated",):
            updater.mark_ready()
        return P()
    monkeypatch.setattr(updater.sys, "executable", str(new))
    monkeypatch.setattr(updater, "_start", fake_start)
    monkeypatch.setattr(updater, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(updater.time, "sleep", lambda s: None)
    rc = updater.install_to(target, [1, 2], "0.4.3")
    log = (updater.update_dir() / "update.log").read_text()
    return rc, target, started, log


def test_install_to_swaps_and_starts_new(tmp_path, monkeypatch):
    rc, target, started, log = _fake_install(tmp_path, monkeypatch, new_starts=True)
    assert rc == 0 and target.read_bytes() == b"new"
    assert target.with_name("7HillsLink.old.exe").read_bytes() == b"old"
    assert started == [(b"new", ("--updated", "0.4.3"))]
    assert "kept the old version as 7HillsLink.old.exe" in log and log.strip().endswith("updated")


def test_install_to_rolls_back(tmp_path, monkeypatch):
    rc, target, started, log = _fake_install(tmp_path, monkeypatch, new_starts=False)
    assert rc == 2 and target.read_bytes() == b"old"
    assert started[-1] == (b"old", ())
    assert "restoring the old one" in log


def test_rate_limited_api_falls_back_to_the_release_page(monkeypatch):
    import urllib.error
    from sevenhills_link import updater

    def refuse(url, timeout=15.0):
        raise urllib.error.HTTPError(url, 403, "rate limit exceeded", None, None)

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def geturl(self):
            return "https://github.com/TheBanjolorian/7hills-link/releases/tag/v99.0.0"

    monkeypatch.setattr(updater, "_get", refuse)
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=15: Resp())
    info = updater.check()
    assert info["version"] == "99.0.0"
    assert info["url"].endswith("/releases/download/v99.0.0/7HillsLink.exe")
    assert info["sha256_url"].endswith("7HillsLink.exe.sha256") and info["sha256"] is None
