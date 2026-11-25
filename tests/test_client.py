from pathlib import Path

from google.protobuf import descriptor_pb2

from sevenhills_link import gamecfg, protoset
from sevenhills_link.core import _summary


def test_patch_keeps_other_lines_and_replaces_wrong_values(tmp_path: Path):
    cfg = tmp_path / "user.cfg"
    cfg.write_text("r_DisplayInfo = 0\n-- comment\nserver.game.telemetry.enabled = 0\n")
    assert set(gamecfg.missing(cfg)) == {"grpc.client.server.enabled", "grpc.client.server.port", "server.game.telemetry.enabled"}
    assert gamecfg.apply(cfg) is True
    text = cfg.read_text()
    assert "r_DisplayInfo = 0" in text and "-- comment" in text
    assert "server.game.telemetry.enabled = 1" in text and "server.game.telemetry.enabled = 0" not in text
    assert gamecfg.missing(cfg) == {}
    assert gamecfg.apply(cfg) is False


def test_player_port_is_kept(tmp_path: Path):
    cfg = tmp_path / "user.cfg"
    cfg.write_text("grpc.client.server.port = 50999\n")
    assert "grpc.client.server.port" not in gamecfg.missing(cfg)
    assert gamecfg.port_of(cfg) == 50999


def _fake_exe(tmp_path: Path) -> Path:
    types = descriptor_pb2.FileDescriptorProto(name="sc/game/telemetry/v1/types.proto", package="sc.game.telemetry.v1", syntax="proto3")
    types.message_type.add(name="VehicleFrame")
    api = descriptor_pb2.FileDescriptorProto(name="sc/game/telemetry/v1/api.proto", package="sc.game.telemetry.v1", syntax="proto3", dependency=["sc/game/telemetry/v1/types.proto"])
    api.message_type.add(name="TelemetryStreamRequest")
    r = api.message_type.add(name="TelemetryStreamResponse")
    r.field.add(name="vehicle", number=3, type=11, label=1, type_name=".sc.game.telemetry.v1.VehicleFrame")
    s = api.service.add(name="GameTelemetryService")
    s.method.add(name="TelemetryStream", input_type=".sc.game.telemetry.v1.TelemetryStreamRequest", output_type=".sc.game.telemetry.v1.TelemetryStreamResponse", server_streaming=True)
    exe = tmp_path / "StarCitizen.exe"
    # api first in the file, so the extractor has to order dependencies itself
    exe.write_bytes(b"\x00junk" * 500 + api.SerializeToString() + b"\xff\xfe" * 100 + types.SerializeToString() + b"\xff\xff\xff tail")
    return exe


def test_protoset_extracts_and_orders(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    exe = _fake_exe(tmp_path)
    fds = protoset.load(exe)
    assert [f.name for f in fds.file] == ["sc/game/telemetry/v1/types.proto", "sc/game/telemetry/v1/api.proto"]
    assert protoset.has_service(fds)
    assert any(p.name.startswith("protoset-") for p in (tmp_path / "7HillsLink").iterdir())


def test_summary():
    frame = {"actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_SEATED", "seat_name": "X"}},
             "vehicle": {"state": {"class_name": "AEGS_Idris_M", "flight": {"state": {"gear": "VEHICLE_COMPONENT_DEPLOYMENT_STATE_RETRACTED"}},
                                   "master_mode": {"mode": "VEHICLE_MASTER_MODE_SCM"}, "power": {"powerplants": True, "engines": True}}}}
    s = _summary(frame)
    assert s["ship"] == "AEGS Idris M" and s["gear"] == "retracted" and s["mode"] == "SCM" and s["power_on"]


def test_uploads_on_change_at_most_4_per_second(tmp_path, monkeypatch):
    import threading, time
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import core as core_mod

    class FakeStream:
        connected = True
        def __init__(self):
            self.lock = threading.Lock(); self.frame = {"n": 0}; self.at = time.time(); self.events = []
        def pending(self, since):
            with self.lock: return self.at > since, bool(self.events)
        def peek(self):
            with self.lock: return dict(self.frame)
        def take(self):
            with self.lock:
                ev, self.events = self.events, []
                return dict(self.frame), self.at, ev
        def stop(self): pass

    sent = []
    monkeypatch.setattr(core_mod.api, "ingest", lambda token, frame, events: sent.append((time.time(), frame, events)))
    c = core_mod.Core()
    monkeypatch.setattr(c, "scan", lambda: None)
    monkeypatch.setattr(c, "ensure_stream", lambda: None)
    monkeypatch.setattr(c, "refresh_settings", lambda force=False: None)
    c.token = "7hl_test"
    s = FakeStream(); c.stream = s
    t = threading.Thread(target=c.run, daemon=True); t.start()
    # 2 s: the frame changes 20 times a second for 1 s, then stays the same.
    end = time.time() + 1.0
    while time.time() < end:
        with s.lock: s.frame = {"n": s.frame["n"] + 1}; s.at = time.time()
        time.sleep(0.05)
    with s.lock: s.events.append("GAME_EVENT_TYPE_ACTOR_ENTER_SEAT"); s.at = time.time()
    time.sleep(1.0)
    c.stop()
    changing = [x for x in sent if x[0] < end + 0.01]
    assert 3 <= len(changing) <= 5, len(changing)                 # ~4 a second, not 20
    assert any("GAME_EVENT_TYPE_ACTOR_ENTER_SEAT" in e for _, _, e in sent)
    assert len(sent) <= len(changing) + 1                         # unchanged frame is not resent
    gaps = [b[0] - a[0] for a, b in zip(sent, sent[1:])]
    assert min(gaps) >= 0.24


def test_sound_and_prefs_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    from sevenhills_link import core as core_mod
    c = core_mod.Core()
    assert c.status()["sound"] == {"muted": False, "volume": 0.1, "repeat": False, "stopped": False}
    c.set_sound(stopped=True)
    assert c.status()["prefs"] == {"start_with_windows": True, "tray": True, "play_on_start": True, "install_declined": False,
                                  "share_position": False}     # the exact position is off until the member turns it on
    c.prefs.set("play_on_start", False)
    c.prefs.set("start_with_windows", False)          # no registry outside the packaged exe
    c.set_sound(muted=True, volume=1.7)
    c2 = core_mod.Core()
    assert c2.sound_muted and c2.sound_volume == 1.0 and c2.sound_stopped
    assert c2.prefs.as_dict() == {"start_with_windows": False, "tray": True, "play_on_start": False, "install_declined": False,
                                  "share_position": False}


def test_chosen_game_path_wins(tmp_path, monkeypatch):
    from sevenhills_link import detect
    def mk(root, ch):
        exe = tmp_path / root / ch / "Bin64" / "StarCitizen.exe"
        exe.parent.mkdir(parents=True); exe.write_bytes(b"x"); return exe
    auto = detect.Install("PTU", mk("a", "PTU").parent.parent)
    picked = mk("b", "PTU")
    live = detect.Install("LIVE", mk("a", "LIVE").parent.parent)
    out = detect.apply_choices([auto, live], {"PTU": str(picked)})
    assert [i.channel for i in out] == ["LIVE", "PTU"]
    assert out[1].source == "chosen" and out[1].exe == picked
    assert detect.install_from_exe(tmp_path / "nope.exe") is None
    assert detect.apply_choices([auto], {"PTU": str(tmp_path / "gone.exe")})[0].source == "auto"


def test_install_is_windows_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import install
    assert install.needs_install(False) is False          # not the packaged Windows exe
    assert install.install(True, True, True, True) == "Installing works only in the packaged 7HillsLink.exe"
    assert install.install_dir() == tmp_path / "Programs" / "7HillsLink"


def test_log_writes_uncaught_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import sys
    from sevenhills_link import log as logmod
    logmod.log.handlers.clear()
    old = sys.excepthook
    try:
        logmod.setup()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        for h in logmod.log.handlers:
            h.flush()
        assert "boom" in (tmp_path / "7HillsLink" / "link.log").read_text()
    finally:
        sys.excepthook = old
        for h in list(logmod.log.handlers):
            h.close(); logmod.log.removeHandler(h)


def test_linux_single_instance_and_show_request(tmp_path, monkeypatch):
    import subprocess, sys, textwrap, time
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import instance
    assert instance.acquire() is True
    # A second process cannot take the lock while this one holds it, and can ask for the window.
    code = textwrap.dedent("""
        import sys
        from sevenhills_link import instance
        print(instance.acquire(), instance.signal_running())
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"LOCALAPPDATA": str(tmp_path), "PYTHONPATH": "src"}).stdout.split()
    assert out == ["False", "True"]
    shown = []
    instance.listen(lambda: shown.append(1))
    instance.signal_running()
    for _ in range(20):
        if shown:
            break
        time.sleep(0.1)
    assert shown


def test_linux_autostart_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sevenhills_link import prefs
    assert prefs.can_autostart() is True
    assert prefs.apply_startup(True) is True
    entry = (tmp_path / "autostart" / "7hills-link.desktop").read_text()
    assert "-m sevenhills_link --autostart" in entry and "PYTHONPATH=" in entry
    assert prefs.apply_startup(False) is True
    assert not (tmp_path / "autostart" / "7hills-link.desktop").exists()


def test_install_id_is_made_once_and_kept(tmp_path, monkeypatch):
    import uuid
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import api
    first = api.install_id()
    assert str(uuid.UUID(first)) == first
    assert api.install_id() == first
    (tmp_path / "7HillsLink" / "install.id").write_text("not a uuid")
    again = api.install_id()
    assert again != first and api.install_id() == again


def test_link_start_sends_the_install_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import api
    seen = {}
    monkeypatch.setattr(api, "_call", lambda method, path, body=None, token=None, timeout=10: seen.update(path=path, body=body) or {})
    api.start_link()
    assert seen["path"] == "/api/telemetry/link/start"
    assert seen["body"]["install_id"] == api.install_id()


def _core_with_key(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    from sevenhills_link import core as core_mod
    calls = []
    monkeypatch.setattr(core_mod.api, "clear_token", lambda: calls.append("forget"))
    c = core_mod.Core()
    c.token, c.linked = "7hl_test", True
    return core_mod, c, calls


def test_unlink_tells_7net_before_forgetting_the_key(tmp_path, monkeypatch):
    core_mod, c, calls = _core_with_key(tmp_path, monkeypatch)
    monkeypatch.setattr(core_mod.api, "unlink_device", lambda token: calls.append("unlink " + token) or {"ok": True})
    c.unlink()
    assert calls == ["unlink 7hl_test", "forget"]
    assert c.token is None and not c.linked and c.link_error is None


def test_unlink_without_7net_still_forgets_and_says_so(tmp_path, monkeypatch):
    core_mod, c, calls = _core_with_key(tmp_path, monkeypatch)
    def down(token):
        raise core_mod.api.ApiError(0, "timed out")
    monkeypatch.setattr(core_mod.api, "unlink_device", down)
    c.unlink()
    assert calls == ["forget"] and c.token is None
    assert c.link_error == core_mod.UNLINK_UNCONFIRMED


def test_unlink_of_a_key_7net_already_refuses_is_quiet(tmp_path, monkeypatch):
    core_mod, c, calls = _core_with_key(tmp_path, monkeypatch)
    def refused(token):
        raise core_mod.api.ApiError(401, "Unauthorized", "unauthorized")
    monkeypatch.setattr(core_mod.api, "unlink_device", refused)
    c.unlink()
    assert calls == ["forget"] and c.link_error is None


def test_refused_key_says_why(tmp_path, monkeypatch):
    core_mod, c, calls = _core_with_key(tmp_path, monkeypatch)
    E = core_mod.api.ApiError
    def refuse(code, reason=None):
        def f(token):
            raise E(401, "refused", code, reason)
        return f
    cases = [
        (("expired",), "90 days"),
        (("unlinked", "admin"), "An admin unlinked"),
        (("unlinked", "limit"), "you can have 5"),
        (("unlinked", "user"), "This PC was unlinked on 7Net"),
        (("unauthorized",), "This PC was unlinked on 7Net"),
    ]
    for args, text in cases:
        c.token, c.linked = "7hl_test", True
        monkeypatch.setattr(core_mod.api, "get_settings", refuse(*args))
        c.refresh_settings(force=True)
        assert c.token is None and not c.linked
        assert text in c.link_error, (args, c.link_error)


def test_api_error_carries_code_and_reason(monkeypatch):
    import io, urllib.error
    from sevenhills_link import api
    body = b'{"error": "This PC was unlinked from 7Net. Link it again.", "code": "unlinked", "reason": "admin"}'
    def boom(req, timeout=10):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body))
    monkeypatch.setattr(api.urllib.request, "urlopen", boom)
    try:
        api.get_settings("7hl_test")
    except api.ApiError as e:
        assert (e.status, e.code, e.reason) == (401, "unlinked", "admin")
    else:
        raise AssertionError("expected ApiError")


def test_a_web_page_instead_of_json_is_a_network_error(monkeypatch):
    from sevenhills_link import api
    class Page:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html><body>Sign in to the hotel wifi</body></html>"
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda req, timeout=10: Page())
    try:
        api._call("GET", "/api/telemetry/device/settings", token="7hl_test")
        assert False, "should raise"
    except api.ApiError as e:
        assert e.status == 0 and "web page" in e.message


def test_a_json_list_is_not_an_answer(monkeypatch):
    from sevenhills_link import api
    class Odd:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"[1, 2]"
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda req, timeout=10: Odd())
    try:
        api._call("GET", "/x")
        assert False, "should raise"
    except api.ApiError as e:
        assert e.status == 0


def test_a_401_that_is_not_from_7net_keeps_the_key(tmp_path, monkeypatch):
    core_mod, c, calls = _core_with_key(tmp_path, monkeypatch)
    def proxy(token):
        raise core_mod.api.ApiError(401, "Unauthorized")
    monkeypatch.setattr(core_mod.api, "get_settings", proxy)
    c.refresh_settings(force=True)
    assert c.token == "7hl_test" and calls == []
    def seven_net(token):
        raise core_mod.api.ApiError(401, "Unauthorized", "unauthorized")
    monkeypatch.setattr(core_mod.api, "get_settings", seven_net)
    c.refresh_settings(force=True)
    assert c.token is None and calls == ["forget"]
