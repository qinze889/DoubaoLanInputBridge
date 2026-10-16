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
