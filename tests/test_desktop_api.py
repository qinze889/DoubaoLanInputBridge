import http.client
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui_app


@contextmanager
def running_server(monkeypatch):
    monkeypatch.setattr(gui_app, "current_access_key", lambda fallback="": "test-key")
    monkeypatch.setattr(gui_app, "preferred_lan_host", lambda: "192.168.1.88")
    monkeypatch.setattr(gui_app, "machine_lan_host", lambda: "192.168.1.88")
    monkeypatch.setattr(gui_app, "PUBLIC_URL_FILE", ROOT / "__missing_public_url__.txt")
    monkeypatch.setattr(gui_app, "PUBLIC_PROBE_FILE", ROOT / "__missing_public_probe__.txt")
    monkeypatch.delenv(gui_app.PUBLIC_URL_ENV, raising=False)
    server = gui_app.BridgeServer(("127.0.0.1", 0), gui_app.BridgeRequestHandler, "test-key")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = dict(headers or {})
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    result = json.loads(data.decode("utf-8")) if data else None
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, result, response_headers


def test_desktop_state_requires_key_and_returns_runtime(monkeypatch):
    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "GET", "/desktop/state")
        assert status == 401
        assert payload["error"] == "invalid access key"

        status, payload, _ = request(port, "GET", "/desktop/state?key=test-key")
        assert status == 200
        assert payload["port"] == port
        assert payload["key"] == "test-key"
        assert payload["mobile_url"].startswith(f"http://192.168.1.88:{port}/?key=")


def test_cloud_account_requires_local_authenticated_client(monkeypatch):
    calls = []
    class Account:
        def __init__(self, directory): pass
        def perform(self, action, body=None):
            calls.append(action)
            return {'ok': True, 'authenticated': True}
    monkeypatch.setattr(gui_app.cloud_account, 'CloudAccount', Account)
    with running_server(monkeypatch) as port:
        assert request(port, 'GET', '/desktop/account')[0] == 401
        assert request(port, 'GET', '/desktop/agent')[0] == 401
        assert request(port, 'POST', '/desktop/agent/start', {})[0] == 401
        assert request(port, 'POST', '/desktop/agent/task', {'prompt': 'untrusted'})[0] == 401
        assert request(port, 'POST', '/desktop/account/login', {'username': 'test', 'password': 'secret'})[0] == 401
        assert calls == []
        assert request(port, 'GET', '/desktop/account?key=test-key', headers={'X-Bridge-Public': '1'})[0] == 403
        assert request(port, 'POST', '/desktop/account/qr', {'key': 'test-key'}, headers={'CF-Ray': 'public-request'})[0] == 403
        assert request(port, 'POST', '/desktop/agent/task', {'key': 'test-key', 'prompt': 'untrusted'}, headers={'X-Bridge-Public': '1'})[0] == 403
        assert calls == []
        assert request(port, 'GET', '/desktop/account?key=test-key')[1]['authenticated']
        assert request(port, 'POST', '/desktop/account/qr', {'key': 'test-key'})[1]['authenticated']
        assert calls == ['status', 'qr']


def test_desktop_history_supports_global_filter_and_pagination(monkeypatch):
    records = [
        {"id": f"text-{index}", "type": "text", "text": f"内容 {index}", "chars": 4, "ts": index}
        for index in range(5)
    ]
    monkeypatch.setattr(gui_app, "search_clipboard_history", lambda query, limit, category: records)
    with running_server(monkeypatch) as port:
        path = f"/desktop/history?key=test-key&q={quote('内容')}&category=all&offset=2&limit=2"
        status, payload, _ = request(port, "GET", path)

    assert status == 200
    assert [item["id"] for item in payload["items"]] == ["text-2", "text-3"]
    assert payload["total"] == 5
    assert payload["has_more"] is True
    assert payload["items"][0]["summary"]["kind"] == "文字"


def test_desktop_copy_diagnostics_copies_and_reports_character_count(monkeypatch):
    copied = []
    monkeypatch.setattr(gui_app, "build_diagnostics_report", lambda port, running: "safe diagnostics")
    monkeypatch.setattr(gui_app, "set_clipboard_text", copied.append)
    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "POST", "/desktop/diagnostics/copy", {"key": "test-key"})

    assert status == 200
    assert copied == ["safe diagnostics"]
    assert payload["result"] == {"copied": True, "characters": 16}


def test_desktop_firewall_returns_verified_status(monkeypatch):
    statuses = iter([{"allowed": False}, {"allowed": True}])
    monkeypatch.setattr(gui_app, "firewall_rule_status", lambda port: next(statuses))
    monkeypatch.setattr(gui_app, "launch_firewall_rule_elevation", lambda port: None)
    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "POST", "/desktop/firewall", {"key": "test-key"})

    assert status == 200
    assert payload["result"]["allowed"] is True
    assert payload["result"]["launched"] is True


def test_desktop_publish_combines_text_and_files(monkeypatch, tmp_path):
    document = tmp_path / "sample.txt"
    document.write_text("sample", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        gui_app,
        "publish_text_for_mobile_download",
        lambda text: calls.append(("text", text)) or {"texts": 1},
    )
    monkeypatch.setattr(
        gui_app,
        "publish_files_for_mobile_download",
        lambda paths: calls.append(("files", paths)) or {"files": len(paths)},
    )
    with running_server(monkeypatch) as port:
        status, payload, _ = request(
            port,
            "POST",
            "/desktop/publish",
            {"key": "test-key", "text": "给手机的文字", "paths": [str(document)]},
        )

    assert status == 200
    assert payload["result"]["text"] == {"texts": 1}
    assert payload["result"]["files"] == {"files": 1}
    assert calls == [("text", "给手机的文字"), ("files", [str(document)])]


def test_desktop_cors_only_reflects_allowed_local_origins(monkeypatch):
    with running_server(monkeypatch) as port:
        status, _, headers = request(
            port,
            "OPTIONS",
            "/desktop/state",
            headers={"Origin": "http://tauri.localhost"},
        )
        _, _, blocked_headers = request(
            port,
            "OPTIONS",
            "/desktop/state",
            headers={"Origin": "https://example.com"},
        )

    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == "http://tauri.localhost"
    assert "Access-Control-Allow-Origin" not in blocked_headers


def test_desktop_api_rejects_non_loopback_client(monkeypatch):
    handler = object.__new__(gui_app.BridgeRequestHandler)
    handler.client_address = ("192.168.1.88", 54321)
    responses = []
    monkeypatch.setattr(gui_app, "json_response", lambda _, status, payload: responses.append((status, payload)))

    assert handler.require_desktop_client() is False
    assert responses == [
        (gui_app.HTTPStatus.FORBIDDEN, {"ok": False, "error": "desktop API is local only"})
    ]


def test_desktop_update_prepare_downloads_verified_installer(monkeypatch, tmp_path):
    package = tmp_path / "DoubaoLanInputBridge_0.11.2.exe"
    package.write_bytes(b"installer")
    monkeypatch.setattr(
        gui_app,
        "check_for_update",
        lambda timeout=0: {
            "configured": True,
            "available": True,
            "version": "0.11.2",
            "url": "http://127.0.0.1/update.exe",
            "sha256": "abc123",
        },
    )
    downloads = []
    monkeypatch.setattr(
        gui_app,
        "download_update_package",
        lambda url, version, sha256, timeout=0: downloads.append((url, version, sha256, timeout)) or package,
    )

    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "POST", "/desktop/update/prepare", {"key": "test-key"})

    assert status == 200
    assert payload["version"] == "0.11.2"
    assert payload["package_path"] == str(package.resolve())
    assert downloads == [("http://127.0.0.1/update.exe", "0.11.2", "abc123", 120.0)]


# ---------------------------------------------------------------- 公网隧道路由


def test_desktop_tunnel_returns_config_status_and_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "TUNNEL_CONFIG_FILE", tmp_path / "tunnel.json")
    monkeypatch.setattr(gui_app, "find_cloudflared", lambda configured="": "")
    monkeypatch.setattr(gui_app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: False)
    monkeypatch.setattr(
        gui_app,
        "detect_tunnel_candidates",
        lambda root=None: [
            {
                "name": "shenjian",
                "config_path": "config.yml",
                "tunnel": "c2901f65",
                "hostnames": ["sj.q-ze.top"],
                "public_url": "https://sj.q-ze.top",
            }
        ],
    )

    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "GET", "/desktop/tunnel?key=test-key")

    assert status == 200
    assert payload["config"]["enabled"] is False
    assert payload["status"]["ready"] is False
    assert payload["status"]["managed"] is False
    assert payload["probe_url"] == "http://127.0.0.1:20244/ready"
    assert payload["candidates"][0]["public_url"] == "https://sj.q-ze.top"


def test_desktop_tunnel_requires_key(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "TUNNEL_CONFIG_FILE", tmp_path / "tunnel.json")

    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "GET", "/desktop/tunnel")

    assert status == 401


def test_desktop_tunnel_config_post_persists_and_switches_access_url(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "IS_MACOS", False)  # Legacy named-tunnel configuration.
    tunnel_file = tmp_path / "tunnel.json"
    monkeypatch.setattr(gui_app, "TUNNEL_CONFIG_FILE", tunnel_file)
    monkeypatch.setattr(gui_app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: True)
    monkeypatch.setattr(gui_app, "probe_public_entry", lambda probe_url, timeout=2.0: True)

    with running_server(monkeypatch) as port:
        status, payload, _ = request(
            port,
            "POST",
            "/desktop/tunnel/config",
            {
                "key": "test-key",
                "enabled": True,
                "name": "shenjian",
                "public_url": "https://sj.q-ze.top",
                "metrics_port": 20244,
            },
        )
        assert status == 200
        assert payload["config"]["name"] == "shenjian"
        assert payload["config"]["public_url"] == "https://sj.q-ze.top"
        assert payload["status"]["ready"] is True

        state_status, state, _ = request(port, "GET", "/desktop/state?key=test-key")

    assert state_status == 200
    assert state["mobile_url"] == "https://sj.q-ze.top/?key=test-key"
    assert json.loads(tunnel_file.read_text(encoding="utf-8"))["enabled"] is True


def test_desktop_tunnel_config_keeps_lan_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "TUNNEL_CONFIG_FILE", tmp_path / "tunnel.json")

    with running_server(monkeypatch) as port:
        status, _, _ = request(
            port,
            "POST",
            "/desktop/tunnel/config",
            {"key": "test-key", "enabled": False, "name": "shenjian", "public_url": "https://sj.q-ze.top"},
        )
        assert status == 200
        _, state, _ = request(port, "GET", "/desktop/state?key=test-key")

    assert state["mobile_url"].startswith("http://192.168.1.88:")


def test_desktop_tunnel_stop_reports_external_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "TUNNEL_CONFIG_FILE", tmp_path / "tunnel.json")
    gui_app._reset_tunnel_process_state()

    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "POST", "/desktop/tunnel/stop", {"key": "test-key"})

    assert status == 200
    assert payload["status"]["stop_result"] == {"stopped": False, "reason": "external"}


def test_desktop_tunnel_start_without_cloudflared_reports_error(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "TUNNEL_CONFIG_FILE", tmp_path / "tunnel.json")
    monkeypatch.setattr(gui_app, "IS_WINDOWS", True)
    monkeypatch.setattr(gui_app, "find_cloudflared", lambda configured="": "")

    with running_server(monkeypatch) as port:
        status, payload, _ = request(
            port,
            "POST",
            "/desktop/tunnel/start",
            {"key": "test-key", "name": "shenjian", "public_url": "https://sj.q-ze.top"},
        )

    assert status == 500
    assert "cloudflared" in payload["error"]


def test_desktop_config_reports_github_update_source(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "UPDATE_URL_FILE", tmp_path / "missing_update_url.txt")
    monkeypatch.delenv(gui_app.UPDATE_MANIFEST_ENV, raising=False)

    with running_server(monkeypatch) as port:
        status, payload, _ = request(port, "GET", "/desktop/config?key=test-key")

    assert status == 200
    assert payload["update_source"] == ("manual" if gui_app.IS_MACOS else "github")
    assert payload["update_url"] == "" if gui_app.IS_MACOS else payload["update_url"].startswith("https://github.com/")
    assert payload["tunnel"]["enabled"] is False


def test_desktop_update_refresh_query_bypasses_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_app, "UPDATE_URL_FILE", tmp_path / "missing_update_url.txt")
    monkeypatch.delenv(gui_app.UPDATE_MANIFEST_ENV, raising=False)
    calls = []

    def fake_check(manifest_url=None, timeout=8.0, use_cache=True):
        calls.append(use_cache)
        return {"configured": True, "available": False, "version": gui_app.APP_VERSION, "url": "", "notes": ""}

    monkeypatch.setattr(gui_app, "check_for_update", fake_check)

    with running_server(monkeypatch) as port:
        request(port, "GET", "/desktop/update?key=test-key")
        request(port, "GET", "/desktop/update?key=test-key&refresh=1")

    assert calls == [True, False]
