import importlib.util
import hashlib
import json
import os
import socket
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "gui_app.py"
QT_APP_PATH = ROOT / "src" / "qt_app.py"


def load_app():
    spec = importlib.util.spec_from_file_location("gui_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This retained upstream suite covers the Windows update/firewall policy.
    # macOS behavior is covered separately in test_macos.py.
    module.IS_MACOS = False
    module.IS_WINDOWS = True
    return module


def test_is_newer_version_handles_semver_and_suffixes():
    app = load_app()

    assert app.is_newer_version("0.1.1", "0.1.0-zh2en")
    assert app.is_newer_version("0.2.0", "0.1.9")
    assert not app.is_newer_version("0.1.0", "0.1.0-zh2en")
    assert not app.is_newer_version("0.0.9", "0.1.0")


def test_normalize_update_manifest_reports_available_update():
    app = load_app()

    update = app.normalize_update_manifest(
        {
            "version": "0.1.1",
            "url": "https://example.com/DoubaoLanInputBridge_zh2en.exe",
            "notes": "界面优化和更新检测",
        },
        current_version="0.1.0-zh2en",
    )

    assert update["available"] is True
    assert update["version"] == "0.1.1"
    assert update["url"] == "https://example.com/DoubaoLanInputBridge_zh2en.exe"
    assert "界面优化" in update["notes"]


def test_normalize_update_manifest_reports_current_when_not_newer():
    app = load_app()

    update = app.normalize_update_manifest(
        {"version": "0.1.0", "url": "https://example.com/app.exe"},
        current_version="0.1.0-zh2en",
    )

    assert update["available"] is False
    assert update["version"] == "0.1.0"


def test_read_update_manifest_url_strips_utf8_bom(tmp_path, monkeypatch):
    app = load_app()
    update_file = tmp_path / "update_url.txt"
    update_file.write_text("\ufefffile:///C:/updates/update.json\r\n", encoding="utf-8")
    monkeypatch.setattr(app, "UPDATE_URL_FILE", update_file)
    monkeypatch.delenv(app.UPDATE_MANIFEST_ENV, raising=False)

    assert app.read_update_manifest_url() == "file:///C:/updates/update.json"


def test_check_for_update_accepts_bom_prefixed_manifest(monkeypatch):
    app = load_app()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'\xef\xbb\xbf{"version":"9.9.9","url":"file:///C:/app.exe"}'

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "file:///C:/updates/update.json")
    monkeypatch.setattr(app, "_open_direct", fake_urlopen)

    result = app.check_for_update()

    assert result["configured"] is True
    assert result["available"] is True
    assert result["version"] == "9.9.9"


def test_normalize_update_manifest_keeps_download_checksum():
    app = load_app()

    update = app.normalize_update_manifest(
        {
            "version": "0.2.0",
            "url": "https://example.com/app.exe",
            "sha256": " ABCDEF ",
        },
        current_version="0.1.0",
    )

    assert update["sha256"] == "abcdef"


def test_download_update_package_writes_file_and_verifies_sha256(tmp_path):
    app = load_app()
    payload = b"new exe bytes"
    expected_hash = hashlib.sha256(payload).hexdigest()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return payload

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse()

    package = app.download_update_package(
        "https://example.com/DoubaoLanInputBridge_zh2en.exe",
        "0.2.0",
        expected_hash,
        download_dir=tmp_path,
        transport=fake_urlopen,
    )

    assert package.read_bytes() == payload
    assert package.name == "DoubaoLanInputBridge_0.2.0.exe"
    assert captured["url"] == "https://example.com/DoubaoLanInputBridge_zh2en.exe"


def test_write_update_script_backs_up_replaces_and_restarts(tmp_path):
    app = load_app()

    script = app.write_update_script(tmp_path / "updater.ps1")
    content = script.read_text(encoding="utf-8")

    assert "Wait-Process -Id $CurrentPid" in content
    assert "Move-Item -LiteralPath $TargetExe -Destination $backupPath" in content
    assert "Move-Item -LiteralPath $PackagePath -Destination $TargetExe" in content
    assert "Start-Process -FilePath $TargetExe" in content
    assert "Remove-Item" not in content


def test_launch_update_script_hides_powershell_window(tmp_path):
    app = load_app()
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    app.launch_update_script(
        tmp_path / "updater.ps1",
        tmp_path / "package.exe",
        tmp_path / "target.exe",
        current_pid=1234,
        popen_factory=fake_popen,
    )

    assert captured["args"][:4] == ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden"]
    assert "-ExecutionPolicy" in captured["args"]
    assert captured["kwargs"]["creationflags"] == getattr(app.subprocess, "CREATE_NO_WINDOW", 0)
    if hasattr(app.subprocess, "STARTUPINFO"):
        assert captured["kwargs"]["startupinfo"] is not None
        assert captured["kwargs"]["startupinfo"].wShowWindow == 0


def test_firewall_rule_script_creates_persistent_private_public_rule(tmp_path):
    app = load_app()
    exe = tmp_path / "bridge-service.exe"

    script = app.build_firewall_rule_script(8766, str(exe))

    assert "DoubaoLanInputBridge LAN TCP 8765-8784" in script
    assert "-Direction Inbound" in script
    assert "-Action Allow" in script
    assert "-Protocol TCP" in script
    assert "-LocalPort $portScope" in script
    assert "$portScope = '8765-8784'" in script
    assert "-Profile Private,Public" in script
    assert str(exe) in script
    assert "-like ($rulePrefix + ' *')" in script
    assert "Remove-NetFirewallRule" in script
    assert "Set-NetFirewallRule -DisplayName $ruleName -Program" not in script


def test_firewall_status_requires_current_program_and_auto_port_range(tmp_path):
    app = load_app()
    exe = tmp_path / "bridge-service.exe"
    captured = {}

    class Result:
        returncode = 0
        stdout = '{"allowed":true,"reason":"allowed"}'

    def fake_runner(args, **kwargs):
        captured["script"] = args[-1]
        return Result()

    status = app.firewall_rule_status(8766, str(exe), runner=fake_runner)

    assert status == {"allowed": True, "reason": "allowed"}
    assert "DoubaoLanInputBridge LAN TCP 8765-8784" in captured["script"]
    assert "$portScope = '8765-8784'" in captured["script"]
    assert "Get-NetFirewallApplicationFilter" in captured["script"]
    assert str(exe) in captured["script"]


def test_launch_firewall_rule_elevation_uses_uac_and_hidden_launcher(tmp_path):
    app = load_app()
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    app.launch_firewall_rule_elevation(8765, str(tmp_path / "app.exe"), popen_factory=fake_popen)

    assert captured["args"][:4] == ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden"]
    assert "-Command" in captured["args"]
    assert "Start-Process -FilePath powershell.exe -Verb RunAs" in captured["args"][-1]
    assert "-EncodedCommand" in captured["args"][-1]
    assert captured["kwargs"]["creationflags"] == getattr(app.subprocess, "CREATE_NO_WINDOW", 0)
    if hasattr(app.subprocess, "STARTUPINFO"):
        assert captured["kwargs"]["startupinfo"] is not None


def test_gui_confirmed_update_starts_one_click_install(monkeypatch):
    app = load_app()
    gui = app.BridgeGui.__new__(app.BridgeGui)
    messages = []
    installs = []
    statuses = []
    button_states = []

    class FakeVar:
        def set(self, value):
            statuses.append(value)

    class FakeButton:
        def configure(self, **kwargs):
            button_states.append(kwargs)

    gui.status_var = FakeVar()
    gui.update_button = FakeButton()
    gui.log = lambda message: None
    gui.set_status = lambda *args: statuses.append(args[1])
    gui.install_update = lambda result: installs.append(result)
    monkeypatch.setattr(
        app.messagebox,
        "askyesno",
        lambda title, message: messages.append(message) or True,
    )

    result = {
        "available": True,
        "version": "0.5.0",
        "url": "https://example.com/DoubaoLanInputBridge_zh2en.exe",
        "notes": "自动更新",
    }
    gui._show_update_result(result, silent=False)

    assert installs == [result]
    assert "是否下载并安装" in messages[0]
    assert {"state": "normal"} in button_states
    assert statuses[-1] == "检测到新版本 0.5.0"


def test_qr_matrix_generates_for_mobile_access_url():
    app = load_app()

    matrix = app.qr_matrix("http://lan-host.local:8765/?key=access-key")

    assert len(matrix) >= 29
    assert all(len(row) == len(matrix) for row in matrix)
    assert matrix[0][0] is False
    assert matrix[4][4] is True
    assert any(any(row) for row in matrix)


def test_request_handler_synchronizes_rotated_access_key_from_disk(tmp_path, monkeypatch):
    app = load_app()
    key_file = tmp_path / "access_key.txt"
    key_file.write_text("new-key", encoding="utf-8")
    monkeypatch.setattr(app, "KEY_FILE", key_file)

    class FakeServer:
        access_key = "old-key"

        def add_log(self, message):
            self.message = message

    fake_handler = type(
        "FakeHandler",
        (),
        {
            "server": FakeServer(),
            "active_access_key": app.BridgeRequestHandler.active_access_key,
        },
    )()

    assert app.BridgeRequestHandler.active_access_key(fake_handler) == "new-key"
    assert fake_handler.server.access_key == "new-key"
    assert app.BridgeRequestHandler.is_authorized(fake_handler, "new-key") is True
    assert app.BridgeRequestHandler.is_authorized(fake_handler, "old-key") is False


def test_mobile_access_hosts_default_to_detected_lan_addresses(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.MOBILE_HOST_ENV, raising=False)
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", tmp_path / "missing_mobile_host.txt")
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", tmp_path / "missing_public_url.txt")
    monkeypatch.delenv(app.PUBLIC_URL_ENV, raising=False)
    monkeypatch.setattr(app, "get_lan_ipv4_addresses", lambda: ["192.168.1.63"])

    assert app.get_mobile_access_hosts() == ["192.168.1.63"]
    assert app.build_access_url("192.168.1.63", 8765, "access key") == "http://192.168.1.63:8765/?key=access%20key"


def test_public_url_override_switches_access_url_to_public_entry(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.PUBLIC_URL_ENV, raising=False)
    monkeypatch.delenv(app.PUBLIC_PROBE_ENV, raising=False)
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", tmp_path / "missing_mobile_host.txt")
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", tmp_path / "missing_public_url.txt")
    monkeypatch.setattr(app, "PUBLIC_PROBE_FILE", tmp_path / "missing_public_probe.txt")
    monkeypatch.setattr(app, "probe_public_entry", lambda probe_url, timeout=2.0: True)

    assert app.read_public_url_override() == ""
    assert app.build_access_url("192.168.1.63", 8765, "access key") == "http://192.168.1.63:8765/?key=access%20key"

    public_file = tmp_path / "public_url.txt"
    public_file.write_text("https://sj.q-ze.top/\n", encoding="utf-8")
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", public_file)

    assert app.read_public_url_override() == "https://sj.q-ze.top"
    assert app.build_access_url("192.168.1.63", 8765, "access key") == "https://sj.q-ze.top/?key=access%20key"


def test_public_url_falls_back_to_lan_when_entry_unreachable(tmp_path, monkeypatch):
    """隧道不通时扫码链接应回退局域网，避免给出打不开的公网地址。"""
    app = load_app()
    monkeypatch.delenv(app.PUBLIC_URL_ENV, raising=False)
    monkeypatch.delenv(app.PUBLIC_PROBE_ENV, raising=False)
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", tmp_path / "missing_mobile_host.txt")
    public_file = tmp_path / "public_url.txt"
    public_file.write_text("https://sj.q-ze.top", encoding="utf-8")
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", public_file)
    probe_file = tmp_path / "public_probe.txt"
    probe_file.write_text("http://127.0.0.1:20244/ready", encoding="utf-8")
    monkeypatch.setattr(app, "PUBLIC_PROBE_FILE", probe_file)
    monkeypatch.setattr(app, "probe_public_entry", lambda probe_url, timeout=2.0: False)

    assert app.build_access_url("192.168.1.63", 8765, "access key") == "http://192.168.1.63:8765/?key=access%20key"


def test_access_url_uses_public_when_probe_not_configured(tmp_path, monkeypatch):
    """未配置探测地址时，只要配了公网入口就直接使用，不做探测。"""
    app = load_app()
    monkeypatch.delenv(app.PUBLIC_URL_ENV, raising=False)
    monkeypatch.delenv(app.PUBLIC_PROBE_ENV, raising=False)
    public_file = tmp_path / "public_url.txt"
    public_file.write_text("https://sj.q-ze.top", encoding="utf-8")
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", public_file)
    monkeypatch.setattr(app, "PUBLIC_PROBE_FILE", tmp_path / "missing_public_probe.txt")

    def unexpected_probe(*args, **kwargs):
        raise AssertionError("未配置探测地址时不应发起探测")

    monkeypatch.setattr(app, "probe_public_entry", unexpected_probe)

    assert app.build_access_url("192.168.1.63", 8765, "access key") == "https://sj.q-ze.top/?key=access%20key"


def test_probe_public_entry_caches_result(monkeypatch):
    """探测结果按 TTL 缓存，避免每次生成链接都发网络请求。"""
    app = load_app()
    calls = []
    probe_url = "http://127.0.0.1:20244/ready"

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeOpener:
        def open(self, request, timeout=None):
            calls.append(request.full_url)
            return FakeResponse()

    monkeypatch.setattr(app, "_local_only_opener", FakeOpener())
    monkeypatch.setattr(app, "_public_entry_probe_state", {"checked_at": 0.0, "ok": False})

    assert app.probe_public_entry(probe_url) is True
    assert app.probe_public_entry(probe_url) is True
    assert len(calls) == 1
    assert calls[0] == probe_url


def test_public_url_env_takes_priority_over_file(tmp_path, monkeypatch):
    app = load_app()
    public_file = tmp_path / "public_url.txt"
    public_file.write_text("https://from-file.example", encoding="utf-8")
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", public_file)
    monkeypatch.setenv(app.PUBLIC_URL_ENV, "https://from-env.example/")

    assert app.read_public_url_override() == "https://from-env.example"


def test_busy_port_detection_checks_specific_loopback_listener():
    app = load_app()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        port = listener.getsockname()[1]
        assert app.is_tcp_port_in_use(port, hosts=["127.0.0.1"]) is True
    finally:
        listener.close()


def test_server_identity_probe_validates_current_pid_and_version(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "KEY_FILE", tmp_path / "access_key.txt")
    app.write_access_key("probe-key")
    server = app.BridgeServer(("127.0.0.1", 0), app.BridgeRequestHandler, "probe-key")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        assert app.wait_for_bridge_server_identity(port, os.getpid(), hosts=["127.0.0.1"])[0] is True
        verified, detail = app.wait_for_bridge_server_identity(
            port,
            os.getpid() + 1,
            hosts=["127.0.0.1"],
            timeout=0.2,
        )
        assert verified is False
        assert "其他进程" in detail
    finally:
        server.shutdown()
        server.server_close()


def test_mobile_access_host_can_be_overridden_by_environment(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", tmp_path / "mobile_host.txt")
    monkeypatch.setenv(app.MOBILE_HOST_ENV, "http://192.168.1.99:8765/?key=old")

    assert app.read_mobile_host_override() == "192.168.1.99"
    assert app.get_mobile_access_hosts() == ["192.168.1.99"]


def test_mobile_access_host_can_be_overridden_by_local_file(tmp_path, monkeypatch):
    app = load_app()
    host_file = tmp_path / "mobile_host.txt"
    host_file.write_text("\ufeff192.168.1.88:8765\n", encoding="utf-8")
    monkeypatch.delenv(app.MOBILE_HOST_ENV, raising=False)
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", host_file)

    assert app.read_mobile_host_override() == "192.168.1.88"
    assert app.get_mobile_access_hosts() == ["192.168.1.88"]


def test_lan_update_manifest_url_uses_non_loopback_host(tmp_path, monkeypatch):
    app = load_app()
    update_file = tmp_path / "update_url.txt"
    monkeypatch.setattr(app, "UPDATE_URL_FILE", update_file)
    monkeypatch.setattr(app, "get_mobile_access_hosts", lambda: ["192.168.1.88"])

    url = app.write_lan_update_manifest_url(8769)

    assert url == "http://192.168.1.63:8765/__updates__/update.json"
    assert update_file.read_text(encoding="utf-8").strip() == url


def test_mobile_access_hosts_allow_only_192_168_ranges():
    app = load_app()

    hosts = app.sorted_lan_ipv4_addresses([
        "127.0.0.1",
        "198.18.0.1",
        "169.254.3.4",
        "10.2.3.4",
        "192.168.1.63",
        "172.20.112.1",
    ])

    assert hosts == ["192.168.1.63"]


def test_mobile_access_host_rejects_non_192_168_overrides(tmp_path, monkeypatch):
    app = load_app()
    host_file = tmp_path / "mobile_host.txt"
    host_file.write_text("10.9.8.7\n", encoding="utf-8")
    monkeypatch.setenv(app.MOBILE_HOST_ENV, "http://198.18.0.1:8765/?key=old")
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", host_file)

    assert app.read_mobile_host_override() == ""


def test_mobile_access_hosts_fallback_to_fixed_192_when_no_allowed_lan(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.MOBILE_HOST_ENV, raising=False)
    monkeypatch.setattr(app, "MOBILE_HOST_FILE", tmp_path / "missing_mobile_host.txt")
    monkeypatch.setattr(app, "get_lan_ipv4_addresses", lambda: [])

    assert app.get_mobile_access_hosts() == ["192.168.1.63"]


def test_preferred_lan_host_ignores_non_192_ranges(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "get_mobile_access_hosts", lambda: ["127.0.0.1", "198.18.0.1", "10.2.3.4", "192.168.1.63"])

    assert app.preferred_lan_host() == "192.168.1.63"


def test_update_source_download_resolves_only_local_update_files(tmp_path, monkeypatch):
    app = load_app()
    update_dir = tmp_path / "local_update_source"
    update_dir.mkdir()
    manifest = update_dir / "update.json"
    manifest.write_text('{"version":"9.9.9"}', encoding="utf-8")
    package = update_dir / "DoubaoLanInputBridge_zh2en-9.9.9.exe"
    package.write_bytes(b"exe")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(app, "LOCAL_UPDATE_SOURCE_DIR", update_dir)

    assert app.resolve_local_update_file("update.json") == manifest.resolve()
    assert app.resolve_local_update_file("DoubaoLanInputBridge_zh2en-9.9.9.exe") == package.resolve()

    for bad_name in ("../secret.txt", "missing.exe", "nested/file.exe", ""):
        try:
            app.resolve_local_update_file(bad_name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad_name!r} should not resolve outside local update source")


def test_active_local_update_source_falls_back_to_frozen_exe_parent(tmp_path, monkeypatch):
    app = load_app()
    repo_root = tmp_path / "repo"
    dist_dir = repo_root / "dist"
    frozen_dir = tmp_path / "_MEI123"
    update_dir = repo_root / "local_update_source"
    dist_dir.mkdir(parents=True)
    frozen_dir.mkdir()
    update_dir.mkdir()
    (update_dir / "update.json").write_text('{"version":"9.9.9"}', encoding="utf-8")
    monkeypatch.setattr(app, "LOCAL_UPDATE_SOURCE_DIR", frozen_dir / "local_update_source")
    monkeypatch.setattr(app, "PROJECT_ROOT", frozen_dir)
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.sys, "executable", str(dist_dir / "DoubaoLanInputBridge_zh2en.exe"))

    assert app.active_local_update_source_dir() == update_dir.resolve()
    assert app.resolve_local_update_file("update.json") == (update_dir / "update.json").resolve()


def test_local_update_manifest_rewrites_package_url_to_request_host(tmp_path, monkeypatch):
    app = load_app()
    update_dir = tmp_path / "local_update_source"
    update_dir.mkdir()
    package = update_dir / "DoubaoLanInputBridge_zh2en-9.9.9.exe"
    package.write_bytes(b"exe")
    (update_dir / "update.json").write_text(
        '{"version":"9.9.9","url":"file:///C:/old/DoubaoLanInputBridge_zh2en-9.9.9.exe"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "LOCAL_UPDATE_SOURCE_DIR", update_dir)

    manifest = app.local_update_manifest_for_host("192.168.1.63:8769")

    assert manifest["version"] == "9.9.9"
    assert manifest["url"] == "http://192.168.1.63:8769/__updates__/DoubaoLanInputBridge_zh2en-9.9.9.exe"


def test_local_update_url_sanitizes_host_header():
    app = load_app()

    assert app.local_update_url_for_host("192.168.1.63:8769", "update.json") == "http://192.168.1.63:8769/__updates__/update.json"
    assert app.local_update_url_for_host("bad host\r\nx: y", "update.json") == "http://127.0.0.1:8765/__updates__/update.json"


def test_bridge_handler_exposes_local_update_route():
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'parsed.path.startswith("/__updates__/")' in source
    assert "resolve_local_update_file" in source
    assert "local_update_manifest_for_host" in source


def test_gui_uses_qr_panel_instead_of_access_address_textbox():
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'text="访问地址"' not in source
    assert "self.urls_text" not in source
    assert "copy_urls" not in source
    assert 'text="扫码连接手机"' in source
    assert "show_qr_window" in source
    assert "self.qr_popup_label" in source
    assert "最近内容预览" in source
    assert "self.main_preview_canvas" in source
    assert "self.main_preview_list" in source
    assert "add_main_preview_row" in source
    assert "bind_main_preview_row" in source
    assert "activate_main_preview_record" in source
    assert "open_main_preview_record_folder" in source
    assert "bind_main_preview_mousewheel" in source
    assert "on_main_preview_mousewheel" in source
    assert '"<MouseWheel>"' in source
    assert '"<Double-1>"' in source
    assert "copy_mobile_url" in source
    assert "qrcode.QRCode" in source


def test_gui_has_prominent_service_status_card():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "self.status_card = tk.Frame" in source
    assert "self.status_badge_var" in source
    assert "self.status_title_var" in source
    assert "self.status_detail_var" in source
    assert "font=(\"\", 20, \"bold\")" in source
    assert "服务运行中" in source
    assert "手机扫码后即可发送文字、图片、视频和文件" in source
    assert "sync_service_buttons" in source
    assert "self.service_toggle_button" in source
    assert "text=\"停止服务\"" in source
    assert "text=\"启动服务\"" in source


def test_gui_uses_scan_workbench_desktop_layout():
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'self.root.geometry("1040x720")' in source
    assert "self.sidebar_frame = tk.Frame" in source
    assert "self.guide_frame = tk.Frame" in source
    assert "self.scan_panel = tk.Frame" in source
    assert "self.service_panel = tk.Frame" in source
    assert "self.activity_frame = tk.Frame" in source
    assert "扫码连接手机" in source
    assert "连接步骤" in source
    assert "端口占用会自动顺延" in source
    assert "qr_photo_image(url, scale=8)" in source
    assert "服务控制" in source
    assert "快速操作" in source
    assert "最近活动" in source
    assert "状态总览" not in source
    assert "def _nav_button" not in source
    assert "def _metric" not in source
    assert "当前局域网地址" not in source
    assert "metric_frame" not in source
    assert "self.mobile_host_var" not in source
    assert "self.mobile_port_var" not in source


def test_gui_hides_activity_log_and_private_paths_by_default():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "self.activity_visible = False" in source
    assert "self.activity_toggle_button" in source
    assert "toggle_activity_frame" in source
    assert "self.activity_frame.grid_remove()" in source
    assert "查看最近活动" in source
    assert "收起最近活动" in source
    assert "完整日志保存在" not in source
    assert "text=f\"完整日志" not in source


def test_gui_start_server_auto_increments_busy_port(monkeypatch):
    app = load_app()
    gui = app.BridgeGui.__new__(app.BridgeGui)
    attempts = []
    statuses = []
    logs = []

    class FakeVar:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = str(value)

    class FakeServer:
        def __init__(self, address, handler, access_key, log_queue):
            attempts.append(address[1])
            if address[1] == 8765:
                raise OSError("busy")
            self.address = address
            self.server_port = address[1]
            self.instance_id = 'fixture-instance'

        def serve_forever(self):
            return None

    class FakeThread:
        def __init__(self, target, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            return None

    gui.server = None
    gui.server_thread = None
    gui.port_var = FakeVar("8765")
    gui.key_var = FakeVar()
    gui.access_key = "old-key"
    gui.log_queue = []
    gui.set_status = lambda theme, title, detail, badge: statuses.append((theme, title, detail, badge))
    gui.sync_service_buttons = lambda: None
    gui.update_qr = lambda: None
    gui.log = lambda message: logs.append(message)

    monkeypatch.setattr(app, "BridgeServer", FakeServer)
    monkeypatch.setattr(app.threading, "Thread", FakeThread)
    monkeypatch.setattr(app, "is_tcp_port_in_use", lambda port: False)
    monkeypatch.setattr(app, "wait_for_bridge_server_identity", lambda *args, **kwargs: (True, ''))
    monkeypatch.setattr(app, "read_or_create_access_key", lambda: "new-key")
    monkeypatch.setattr(app.messagebox, "showerror", lambda *args, **kwargs: None)

    app.BridgeGui.start_server(gui)

    assert attempts == [8765, 8766]
    assert gui.server is not None
    assert gui.port_var.get() == "8766"
    assert gui.access_key == "new-key"
    assert any("auto switched to 8766" in message for message in logs)


def test_gui_registers_windows_tray_icon_and_hides_on_close():
    source = APP_PATH.read_text(encoding="utf-8")

    assert '"assets/app.ico"' in source
    assert "class WindowsTrayIcon" in source
    assert "app_icon_path()" in source
    assert "LoadImageW" in source
    assert "self.root.iconbitmap" in source
    assert "Shell_NotifyIconW(NIM_ADD" in source
    assert "self.actions = queue.Queue()" in source
    assert 'self.actions.put("show")' in source
    assert "def drain_tray_actions" in source
    assert 'menu.add_command(label="显示主窗口"' in source
    assert 'menu.add_command(label="复制扫码链接"' in source
    assert 'menu.add_command(label="检查更新", command=self.gui.check_update_from_tray)' in source
    assert 'self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)' in source
    assert "def hide_to_tray" in source
    assert "self.root.iconify()" in source
    assert "window minimized; tray icon remains available" in source
    assert "window minimized instead of exiting" in source
    assert "def quit_app" in source
    assert "_close_for_update" in source
    assert "self.quit_app()" in source
    assert "def check_update_from_tray" in source


def test_health_response_exposes_version_and_executable_for_tray_debugging():
    source = APP_PATH.read_text(encoding="utf-8")

    assert '"version": APP_VERSION' in source
    assert '"pid": os.getpid()' in source
    assert '"executable": running_executable_path()' in source
    assert '"frozen": bool(getattr(sys, "frozen", False))' in source
    assert "app started version=" in source
    assert "window minimized; tray icon remains available" in source
    assert "app quit requested" in source


def test_diagnostics_report_redacts_secrets_and_includes_distribution_context(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "UPDATE_URL_FILE", tmp_path / "update_url.txt")
    monkeypatch.setattr(app, "MINIMAX_API_KEY_FILE", tmp_path / "minimax_api_key.txt")
    monkeypatch.setattr(app, "KEY_FILE", tmp_path / "access_key.txt")
    monkeypatch.setattr(app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app, "get_mobile_access_hosts", lambda: ["192.168.1.63"])
    monkeypatch.setenv(app.UPDATE_MANIFEST_ENV, "http://192.168.1.63:8765/__updates__/update.json")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-sensitive-value")
    app.MINIMAX_API_KEY_FILE.write_text("sk-file-secret", encoding="utf-8")
    app.KEY_FILE.write_text("access-secret", encoding="utf-8")

    report = app.build_diagnostics_report(port=8769, service_running=True)

    assert app.APP_VERSION in report
    assert "service_running: true" in report
    assert "port: 8769" in report
    assert "lan_hosts: 192.168.1.63" in report
    assert "update_url_configured: true" in report
    assert "minimax_api_key_configured: true" in report
    assert "access_key_configured: true" in report
    assert "sk-sensitive-value" not in report
    assert "sk-file-secret" not in report
    assert "access-secret" not in report


def test_self_check_report_redacts_secrets_and_covers_release_health(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "UPDATE_URL_FILE", tmp_path / "update_url.txt")
    monkeypatch.setattr(app, "MINIMAX_API_KEY_FILE", tmp_path / "minimax_api_key.txt")
    monkeypatch.setattr(app, "KEY_FILE", tmp_path / "access_key.txt")
    monkeypatch.setattr(app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "data" / "clipboard_history.json")
    monkeypatch.setattr(app, "get_mobile_access_hosts", lambda: ["192.168.1.63"])
    app.DATA_DIR.mkdir(parents=True)
    app.KEY_FILE.write_text("access-secret", encoding="utf-8")
    app.MINIMAX_API_KEY_FILE.write_text("sk-file-secret", encoding="utf-8")

    report = app.build_self_check_report(port=8765, service_running=True)

    assert "self-check" in report
    assert "PASS 版本" in report
    assert "PASS 服务状态" in report
    assert "PASS 访问密钥" in report
    assert "PASS 单实例入口" in report
    assert "PASS 托盘唤起" in report
    assert "diagnostics:" in report
    assert "sk-file-secret" not in report
    assert "access-secret" not in report


def test_gui_exposes_distribution_config_first_run_and_diagnostics_controls():
    source = APP_PATH.read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert f'APP_VERSION = "{version}"' in source
    assert "FIRST_RUN_FILE" in source
    assert "maybe_show_first_run_guide" in source
    assert "show_config_dialog" in source
    assert "copy_diagnostics" in source
    assert "配置" in source
    assert "复制诊断信息" in source
    assert "对外分发版" in source


def test_gui_exposes_clipboard_history_window_and_open_actions():
    source = APP_PATH.read_text(encoding="utf-8")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert f'APP_VERSION = "{version}"' in source
    assert "show_history_window" in source
    assert "refresh_history_window" in source
    assert "HISTORY_WINDOW_LIMIT = 30" in source
    assert 'columns = ("kind", "time", "preview", "info", "action")' in source
    assert 'show="tree headings"' in source
    assert 'heading("#0", text="预览图")' in source
    assert 'column("#0", width=96' in source
    assert 'heading("preview", text="内容预览")' in source
    assert 'heading("info", text="信息")' in source
    assert 'orient="vertical"' in source
    assert 'orient="horizontal"' in source
    assert "history_record_preview(record)" in source
    assert "format_history_timestamp(record.get(\"ts\"))" in source
    assert "history_thumbnail_for_record" in source
    assert "first_image_history_path(record)" in source
    assert "list_clipboard_history(HISTORY_WINDOW_LIMIT)" in source
    assert "open_selected_history_file" in source
    assert "open_selected_history_folder" in source
    assert "查看历史" in source
    assert "打开文件" in source
    assert "打开所在文件夹" in source


def test_qt_app_replaces_tk_main_ui_with_modern_preview_cards():
    source = QT_APP_PATH.read_text(encoding="utf-8")

    assert "from PySide6.QtWidgets import" in source
    assert "from PySide6.QtNetwork import QLocalServer, QLocalSocket" in source
    assert "class SingleInstanceGuard" in source
    assert "SINGLE_INSTANCE_NAME" in source
    assert 'SINGLE_INSTANCE_NAME = f"{bridge.APP_ID}.qt.main.{APP_VERSION}"' in source
    assert "single_instance.is_secondary" in source
    assert "set_activate_callback(window.show_normal)" in source
    assert "self.tray.activated.connect(self.on_tray_activated)" in source
    assert "ActivationReason.Context" in source
    assert "tray activated" in source
    assert "showNormal()" in source
    assert "QApplication.alert(self, 0)" in source
    assert "ShowWindow" in source
    assert "SetForegroundWindow" in source
    assert "BringWindowToTop" in source
    assert "main window activation requested" in source
    assert "运行自检" in source
    assert "copy_self_check" in source
    assert "build_self_check_report" in source
    assert "allow_firewall" in source
    assert "launch_firewall_rule_elevation" in source
    assert "class BridgeQtWindow(QMainWindow)" in source
    assert "class PreviewCard(QFrame)" in source
    assert "QScrollArea" in source
    assert "mousePressEvent" in source
    assert "mouseDoubleClickEvent" in source
    assert "contextMenuEvent" in source
    assert "select_preview_card" in source
    assert "QScrollBar:vertical" in source
    assert 'selected="true"' in source
    assert "QSystemTrayIcon" in source
    assert "class QrDialog(QDialog)" in source
    assert "刷新二维码" in source
    assert "def refresh_access_key" in source
    assert "self.parent_window.regenerate_access_key()" in source
    assert "旧二维码和旧链接会立即失效" in source
    assert "QApplication.clipboard().setText" in source
    assert "bridge.create_verified_bridge_service" in source
    assert "def regenerate_access_key" in source
    assert "bridge.write_new_access_key()" in source
    assert "self.server.access_key = self.access_key" in source
    assert "def sync_access_key" in source
    assert "bridge.current_access_key(self.access_key)" in source
    assert "history_search" in source
    assert "全局搜索历史：文字、文件名、路径或类型" in source
    assert "search_clipboard_history" in source
    assert "PREVIEW_PAGE_SIZE = bridge.HISTORY_WINDOW_LIMIT" in source
    assert "records_with_more = bridge.search_clipboard_history(query, self.preview_limit + 1, category)" in source
    assert "全局历史 · 已加载 {len(records)} 条" in source
    assert "PREVIEW_AUTO_REFRESH_MS = 5000" in source
    assert "self.preview_timer.timeout.connect(self.refresh_preview)" in source
    assert "self.preview_timer.start(PREVIEW_AUTO_REFRESH_MS)" in source
    assert "自动刷新中 · 每 5 秒 · 上次刷新：" in source
    assert "bridge.format_history_timestamp(record.get(\"ts\"))" in source
    assert "每 5 秒" in source
    assert "连接摘要" not in source
    assert 'topbar.setObjectName("topbar")' in source
    assert 'center.setObjectName("workspace")' in source
    assert "self.sidebar" not in source
    assert 'QLabel("史记")' in source
    assert "最近 50 条文字、图片、视频和文件" not in source
    assert "QComboBox" in source
    assert "history_category" in source
    assert 'self.history_category.addItem(label, value)' in source
    assert "bridge.search_clipboard_history(query, self.preview_limit + 1, category)" in source
    assert "打开所选内容目录" in source
    assert "open_selected_record_folder" in source
    assert "打开归档目录" in source
    assert "open_history_archive_folder" in source
    assert "继续加载 {PREVIEW_PAGE_SIZE} 条" in source
    assert "def reset_preview" in source
    assert "def load_more_history" in source
    assert 'QPushButton("刷新")' in source
    assert "miniButton" in source
    assert "文件夹" in source
    assert 'self.setProperty("kind", kind_style)' in source
    assert 'thumb.setProperty("kind", kind_style)' in source
    assert 'kind.setProperty("kind", kind_style)' not in source
    assert '#previewCard[kind="text"]' in source
    assert '#previewCard[kind="file"]' in source
    assert '#previewThumb[kind="image"]' in source
    assert '#previewCard[kind="video"]' in source
    assert '#previewThumb[kind="media"]' in source
    assert '#previewKind' not in source
    assert "self.history_search.setClearButtonEnabled(True)" in source
    assert "QFileDialog" in source
    assert "发布给手机" in source
    assert "show_publish_dialog" in source
    assert "show_publish_menu" not in source
    assert "class PublishToMobileDialog(QDialog)" in source
    assert "class PublishFileDropZone(QFrame)" in source
    assert "self.setAcceptDrops(True)" in source
    assert "filesDropped = Signal(list)" in source
    assert 'QPushButton("选择文件")' in source
    assert 'QPushButton("清空文件")' in source
    assert 'QPushButton("发布到手机")' in source
    assert "文字会显示为可复制的对话条目" in source
    assert "两者可以同时发布" in source
    assert "publish_text_for_mobile_download" in source
    assert "default_file_picker_dir()" in source
    assert "点击文字即可复制，点击文件即可打开" in source
    assert "publish_files_for_mobile_download" in source
    assert "共享目录" in source
    assert "class ManageDialog(QDialog)" in source
    assert "常用维护入口。低频诊断和敏感操作已收起。" in source
    assert "manageCompactGroup" in source
    assert "manageActionTile" in source
    assert "更多工具" in source
    assert "toggle_more_tools" in source
    assert "运行日志" in source
    assert "class LogDialog(QDialog)" in source
    assert "放行防火墙" in source
    assert "手机同 Wi-Fi 仍连不上时使用" in source
    assert "bridge.launch_firewall_rule_elevation" in source
    assert "display_qr_target(url)" in source
    assert "build_health_url" in source
    assert "build_connection_self_check" in source
    assert "访问密钥已隐藏" in source
    assert "连接自检" in source
    assert "手机先测" in source
    assert "复制自检信息" in source
    assert "bridge.build_access_url(bridge.preferred_lan_host(), self.port, self.access_key)" in source
    assert 'self.link.setText(f"v{APP_VERSION}' in source
    assert 'def local_url(self) -> str:' in source
    assert "bridge.build_health_url(bridge.preferred_lan_host(), self.port)" in source
    assert "bridge.build_connection_self_check(self.port, bool(self.server), bridge.preferred_lan_host())" in source
    assert "bridge.build_access_url(bridge.FIXED_LAN_UPDATE_HOST, self.port, self.access_key)" not in source
    assert "Wi-Fi 自动连接二维码需要明文 Wi-Fi 密码" in source
    assert "QLabel(url)" not in source
    assert "right_layout.addWidget(self.log_text)" not in source
    assert "dangerGhostButton" in source
    assert "def update_service_controls" in source
    assert "def confirm_stop_server" in source
    assert "停止服务后，手机将暂时无法发送或下载文件。" in source
    assert "确定要停止局域网互传服务吗？" in source
    assert 'dialog.addButton("停止服务"' in source
    assert 'dialog.addButton("取消"' in source
    assert "停止服务后，手机将暂时无法发送或下载文件。确定停止吗？" not in source
    assert "正在停止服务" in source
    assert "QApplication.processEvents()" in source
    assert "server.shutdown()" in source
    assert "server.server_close()" in source
    assert "show_manage" in source
    assert "ManageDialog(self).exec()" in source
    assert "管理" in source
    assert "当前版本 v{APP_VERSION}" in source
    assert "访问密钥" in source
    assert "完整历史" in source
    assert "复制连接" in source


# ---------------------------------------------------------------- GitHub 更新源


def test_github_repo_from_url_accepts_common_forms():
    app = load_app()

    expected = "qinze889/DoubaoLanInputBridge"
    assert app.github_repo_from_url("https://github.com/qinze889/DoubaoLanInputBridge") == expected
    assert app.github_repo_from_url("https://github.com/qinze889/DoubaoLanInputBridge/") == expected
    assert app.github_repo_from_url("https://github.com/qinze889/DoubaoLanInputBridge/releases") == expected
    assert app.github_repo_from_url("https://github.com/qinze889/DoubaoLanInputBridge.git") == expected
    assert app.github_repo_from_url("https://api.github.com/repos/qinze889/DoubaoLanInputBridge/releases/latest") == expected
    assert app.github_repo_from_url("qinze889/DoubaoLanInputBridge") == expected


def test_github_repo_from_url_rejects_non_github_sources():
    app = load_app()

    assert app.github_repo_from_url("http://192.168.1.63:8765/__updates__/update.json") == ""
    assert app.github_repo_from_url("file:///C:/updates/update.json") == ""
    assert app.github_repo_from_url("") == ""


def test_pick_release_asset_prefers_nsis_setup_over_msi_and_archives():
    app = load_app()

    asset = app.pick_release_asset(
        {
            "assets": [
                {"name": "source.zip", "browser_download_url": "https://x/s.zip"},
                {"name": "pkg.msi", "browser_download_url": "https://x/o.msi"},
                {"name": "声笺_0.12.2_x64-setup.exe", "browser_download_url": "https://x/setup.exe"},
            ]
        }
    )

    assert asset["name"] == "声笺_0.12.2_x64-setup.exe"


def test_pick_release_asset_falls_back_to_msi():
    app = load_app()

    asset = app.pick_release_asset(
        {"assets": [{"name": "pkg.msi", "browser_download_url": "https://x/o.msi"}]}
    )

    assert asset["name"] == "pkg.msi"


def test_pick_release_asset_returns_empty_without_installer():
    app = load_app()

    assert app.pick_release_asset({"assets": [{"name": "src.zip"}]}) == {}
    assert app.pick_release_asset({}) == {}
    assert app.pick_release_asset({"assets": "not-a-list"}) == {}


def test_normalize_github_release_maps_tag_asset_digest_and_notes():
    app = load_app()

    result = app.normalize_github_release(
        {
            "tag_name": "v0.13.0",
            "body": "  本次更新：集成隧道  ",
            "assets": [
                {
                    "name": "shenjian-0.13.0-setup.exe",
                    "browser_download_url": "https://github.com/x/y/releases/download/v0.13.0/shenjian-0.13.0-setup.exe",
                    "digest": "sha256:ABCDEF",
                }
            ],
        },
        current_version="0.12.2",
    )

    assert result["available"] is True
    assert result["version"] == "0.13.0"
    assert result["sha256"] == "abcdef"
    assert result["source"] == "github"
    assert result["tag"] == "v0.13.0"
    assert result["notes"] == "本次更新：集成隧道"
    assert result["url"].endswith("shenjian-0.13.0-setup.exe")


def test_normalize_github_release_without_digest_leaves_checksum_empty():
    app = load_app()

    result = app.normalize_github_release(
        {"tag_name": "0.13.0", "assets": [{"name": "a-setup.exe", "browser_download_url": "https://x/a.exe"}]},
        current_version="0.12.2",
    )

    assert result["available"] is True
    assert result["sha256"] == ""


def test_normalize_github_release_requires_version():
    app = load_app()

    try:
        app.normalize_github_release({"assets": []})
    except ValueError as exc:
        assert "版本号" in str(exc)
    else:
        raise AssertionError("缺少 tag 时应报错")


def test_read_update_manifest_url_defaults_to_github(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.UPDATE_MANIFEST_ENV, raising=False)
    monkeypatch.setattr(app, "UPDATE_URL_FILE", tmp_path / "missing_update_url.txt")

    assert app.read_update_manifest_url() == f"https://github.com/{app.GITHUB_REPO_DEFAULT}"


def test_read_update_manifest_url_prefers_configured_file(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.UPDATE_MANIFEST_ENV, raising=False)
    target = tmp_path / "update_url.txt"
    target.write_text("http://192.168.1.63:8765/__updates__/update.json\n", encoding="utf-8")
    monkeypatch.setattr(app, "UPDATE_URL_FILE", target)

    assert app.read_update_manifest_url() == "http://192.168.1.63:8765/__updates__/update.json"


def test_check_for_update_queries_github_releases_api(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "https://github.com/qinze889/DoubaoLanInputBridge")
    seen = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(
                {
                    "tag_name": "v9.9.9",
                    "body": "notes",
                    "assets": [
                        {
                            "name": "shenjian-9.9.9-setup.exe",
                            "browser_download_url": "https://x/setup.exe",
                            "digest": "sha256:abc",
                        }
                    ],
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(app, "_open_direct", fake_urlopen)

    result = app.check_for_update()

    assert seen == ["https://api.github.com/repos/qinze889/DoubaoLanInputBridge/releases/latest"]
    assert result["configured"] is True
    assert result["available"] is True
    assert result["version"] == "9.9.9"
    assert result["sha256"] == "abc"
    assert result["source"] == "github"


def test_check_for_update_degrades_to_error_instead_of_raising(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "https://github.com/qinze889/DoubaoLanInputBridge")

    def failing_urlopen(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(app, "_open_direct", failing_urlopen)

    result = app.check_for_update()

    assert result["configured"] is True
    assert result["available"] is False
    assert "connection refused" in result["error"]


def test_check_for_update_caches_within_ttl(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "https://github.com/qinze889/DoubaoLanInputBridge")
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"tag_name": "v0.12.2", "assets": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(app, "_open_direct", fake_urlopen)

    app.check_for_update()
    app.check_for_update()

    assert len(calls) == 1

    app.check_for_update(use_cache=False)

    assert len(calls) == 2


def test_check_for_update_does_not_cache_failures(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "https://github.com/qinze889/DoubaoLanInputBridge")
    calls = []

    def failing_urlopen(request, timeout):
        calls.append(1)
        raise OSError("temporary failure")

    monkeypatch.setattr(app, "_open_direct", failing_urlopen)

    assert app.check_for_update().get("error")
    assert app.check_for_update().get("error")

    assert len(calls) == 2


def test_reset_update_check_cache_forces_refetch(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "https://github.com/qinze889/DoubaoLanInputBridge")
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"tag_name": "v0.12.2", "assets": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(1)
        return FakeResponse()

    monkeypatch.setattr(app, "_open_direct", fake_urlopen)

    app.check_for_update()
    app.reset_update_check_cache()
    app.check_for_update()

    assert len(calls) == 2


def test_refresh_lan_update_manifest_url_never_clobbers_github_source(tmp_path, monkeypatch):
    """默认源已是 GitHub，启动时的回写不能把用户选的源覆盖成局域网地址。"""
    app = load_app()
    monkeypatch.delenv(app.UPDATE_MANIFEST_ENV, raising=False)
    target = tmp_path / "update_url.txt"
    target.write_text("https://github.com/qinze889/DoubaoLanInputBridge\n", encoding="utf-8")
    monkeypatch.setattr(app, "UPDATE_URL_FILE", target)

    assert app.refresh_lan_update_manifest_url(8790) == ""
    assert target.read_text(encoding="utf-8").strip() == "https://github.com/qinze889/DoubaoLanInputBridge"


def test_refresh_lan_update_manifest_url_never_writes_default_source(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.UPDATE_MANIFEST_ENV, raising=False)
    target = tmp_path / "update_url.txt"
    monkeypatch.setattr(app, "UPDATE_URL_FILE", target)

    assert app.refresh_lan_update_manifest_url(8790) == ""
    assert not target.exists()


def test_refresh_lan_update_manifest_url_refreshes_existing_lan_source(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.delenv(app.UPDATE_MANIFEST_ENV, raising=False)
    target = tmp_path / "update_url.txt"
    target.write_text("http://192.168.1.63:8765/__updates__/update.json\n", encoding="utf-8")
    monkeypatch.setattr(app, "UPDATE_URL_FILE", target)

    url = app.refresh_lan_update_manifest_url(8790)

    assert url == "http://192.168.1.63:8765/__updates__/update.json"
    assert target.read_text(encoding="utf-8").strip() == url


# ---------------------------------------------------------------- 直连（绕开失效代理）


def test_direct_opener_registers_no_proxy_route(monkeypatch):
    """环境里存在失效代理时，更新链路必须能直连。

    ProxyHandler 按 proxies 映射动态注册 "<scheme>_open"；空映射等于不注册任何
    代理路由，请求不会被送去 HTTP_PROXY。因此这里断言「没有代理路由」即可。
    """
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:10808")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10808")
    app = load_app()

    handler_names = [type(h).__name__ for h in app._local_only_opener.handlers]
    assert "ProxyHandler" not in handler_names
    assert "proxy" not in getattr(app._local_only_opener, "handle_open", {})


def test_check_for_update_uses_direct_opener(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "read_update_manifest_url", lambda: "https://github.com/qinze889/DoubaoLanInputBridge")
    used = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"tag_name": "v9.9.9", "assets": []}).encode("utf-8")

    def fake_open_direct(request, timeout):
        used.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(app, "_open_direct", fake_open_direct)

    result = app.check_for_update()

    assert used == ["https://api.github.com/repos/qinze889/DoubaoLanInputBridge/releases/latest"]
    assert result["available"] is True


def test_download_update_package_defaults_to_direct_opener(tmp_path, monkeypatch):
    app = load_app()
    used = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"installer-bytes"

    def fake_open_direct(request, timeout):
        used.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(app, "_open_direct", fake_open_direct)

    package = app.download_update_package("https://example.com/setup.exe", "9.9.9", "", download_dir=tmp_path)

    assert used == ["https://example.com/setup.exe"]
    assert package.read_bytes() == b"installer-bytes"
