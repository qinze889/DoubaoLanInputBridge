"""Quick Tunnel regressions without GUI imports or external network access."""

import http.client
import io
import json
import socket
import ssl
import threading
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler

import pytest

import mac_tunnel


@contextmanager
def running_server(server):
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def fetch(server, path="/health"):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=2
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class HealthOrigin(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append(self.path)
        self.send_response(self.server.health_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.server.health_body)))
        self.end_headers()
        self.wfile.write(self.server.health_body)


@pytest.fixture
def services():
    """Keep every listener alive until its public gateway has been stopped."""
    with ExitStack() as stack:
        def origin(payload=None, status=200):
            server = ThreadingHTTPServer(("127.0.0.1", 0), HealthOrigin)
            server.health_status = status
            server.health_body = (
                payload if isinstance(payload, bytes)
                else json.dumps({"ok": True} if payload is None else payload).encode()
            )
            server.requests = []
            return stack.enter_context(running_server(server))

        def gateway(origin_port):
            return stack.enter_context(
                running_server(mac_tunnel.PublicGateway(origin_port))
            )

        yield origin, gateway


def test_public_health_checks_origin_and_returns_only_probe_identity(services):
    make_origin, make_gateway = services
    origin = make_origin({
        "ok": True,
        "name": "private origin name",
        "pid": 424242,
        "data_dir": "/private/user/bridge-data",
        "access_key": "never-return-this-key",
    })
    gateway = make_gateway(origin.server_port)

    status, headers, raw_body = fetch(gateway)
    body = json.loads(raw_body)

    assert status == 200
    assert origin.requests == ["/health"]
    assert body["ok"] is True
    assert body["probe_id"] == gateway.probe_id
    assert isinstance(body["probe_id"], str) and body["probe_id"]
    assert set(body) <= {"ok", "name", "probe_id"}
    if "name" in body:
        assert body["name"] == "Shengjian"
    assert "no-store" in headers.get("Cache-Control", "").lower()
    assert b"never-return-this-key" not in raw_body
    assert b"/private/user/bridge-data" not in raw_body


def test_probe_identity_is_stable_per_gateway_and_distinct_after_restart(services):
    make_origin, make_gateway = services
    origin = make_origin()
    first = make_gateway(origin.server_port)
    replacement = make_gateway(origin.server_port)

    first_id = json.loads(fetch(first)[2])["probe_id"]
    repeated_id = json.loads(fetch(first)[2])["probe_id"]
    replacement_id = json.loads(fetch(replacement)[2])["probe_id"]

    assert first_id == repeated_id == first.probe_id
    assert replacement_id == replacement.probe_id
    assert first_id != replacement_id
    assert origin.requests == ["/health", "/health", "/health"]


def test_public_health_rejects_unreachable_origin(services):
    _, make_gateway = services
    # Reserve the port without listening so no other test can acquire it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        gateway = make_gateway(unavailable.getsockname()[1])
        status, _, _ = fetch(gateway)

    assert status == 502


@pytest.mark.parametrize(("status", "payload"), [
    (503, {"ok": True}),
    (200, {"ok": False}),
    (200, {}),
    (200, []),
    (200, {"ok": "true"}),
    (200, b"not JSON"),
])
def test_public_health_rejects_unhealthy_or_invalid_origin(services, status, payload):
    make_origin, make_gateway = services
    origin = make_origin(payload, status)
    gateway = make_gateway(origin.server_port)

    response_status, _, _ = fetch(gateway)

    assert response_status == 502
    assert origin.requests == ["/health"]


@pytest.mark.parametrize("path", [
    "/desktop/state?key=synthetic-test-key",
    "/desktop/connections",
    "/desktop/tunnel",
    "/__updates__/update.json",
])
def test_public_probe_does_not_open_management_routes(services, path):
    make_origin, make_gateway = services
    origin = make_origin()
    gateway = make_gateway(origin.server_port)

    status, _, _ = fetch(gateway, path)

    assert status == 403
    assert origin.requests == []


class FakeProcess:
    pid = 12345

    def __init__(self):
        self.stdout = io.StringIO()
        self.returncode = None
        self.calls = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.calls.append("terminate")
        self.returncode = 0

    def wait(self, timeout=None):
        self.calls.append("wait")
        self.returncode = 0
        return 0

    def kill(self):
        self.calls.append("kill")
        self.returncode = -9


class FakeGateway:
    server_port = 34567
    probe_id = "active-test-gateway"

    def __init__(self, origin_port):
        self.origin_port = origin_port
        self.closed = False

    def serve_forever(self):
        pass

    def shutdown(self):
        pass

    def server_close(self):
        self.closed = True


@pytest.fixture
def active_manager(tmp_path, monkeypatch):
    """An owned live process with no worker threads or real connector."""
    monkeypatch.setattr(mac_tunnel, "find_binary", lambda configured="": "/test/cloudflared")
    manager = mac_tunnel.TunnelManager(tmp_path)
    manager.process = FakeProcess()
    manager.gateway = FakeGateway(8767)
    manager.generation = 7
    manager.phase = "starting"
    manager.stage = "allocating"
    try:
        yield manager
    finally:
        manager.stop()


PUBLIC_URL = "https://active-test.trycloudflare.com"


def allocate(manager):
    manager._handle_line(PUBLIC_URL, manager.generation)


def register(manager, index=0):
    manager._handle_line(
        f"INF Registered tunnel connection connIndex={index} protocol=http2",
        manager.generation,
    )


def verify(manager):
    manager._apply_probe(manager.generation, manager.probe_epoch, True, "")


def test_registration_waits_for_public_identity_verification(active_manager):
    manager = active_manager
    allocate(manager)
    assert manager.status()["stage"] == "connecting"
    register(manager)

    waiting = manager.status()
    assert waiting["stage"] == "verifying"
    assert waiting["ready"] is False
    assert waiting["public_url"] == ""

    verify(manager)

    ready = manager.status()
    assert ready["ready"] is True
    assert ready["stage"] == "ready"
    assert ready["public_url"] == PUBLIC_URL
    assert ready["verified_at"]


def test_all_edge_connections_must_be_lost_before_revoking_ready(active_manager):
    manager = active_manager
    allocate(manager)
    register(manager, 0)
    register(manager, 1)
    verify(manager)
    assert len(manager.connections) == 2

    manager._handle_line("ERR Connection terminated connIndex=0", manager.generation)
    assert manager.status()["ready"] is True
    assert len(manager.connections) == 1

    manager._handle_line("ERR Connection terminated connIndex=1", manager.generation)

    disconnected = manager.status()
    assert not manager.connections
    assert disconnected["ready"] is False
    assert disconnected["public_url"] == ""
    assert disconnected["stage"] == "reconnecting"


def test_later_public_probe_failure_revokes_ready_even_while_process_lives(active_manager):
    manager = active_manager
    allocate(manager)
    register(manager)
    verify(manager)
    assert manager.status()["ready"] is True

    manager._apply_probe(
        manager.generation, manager.probe_epoch, False, "public probe timed out"
    )

    disconnected = manager.status()
    assert manager.process.poll() is None
    assert disconnected["ready"] is False
    assert disconnected["public_url"] == ""
    assert "timed out" in disconnected["last_error"]

    verify(manager)
    assert manager.status()["ready"] is True


def test_probe_started_before_disconnect_cannot_mark_reconnected_tunnel_ready(active_manager):
    manager = active_manager
    allocate(manager)
    register(manager)
    stale_epoch = manager.probe_epoch
    manager._handle_line("ERR Connection terminated connIndex=0", manager.generation)
    register(manager)
    assert manager.probe_epoch != stale_epoch

    manager._apply_probe(manager.generation, stale_epoch, True, "")
    assert manager.status()["ready"] is False

    verify(manager)
    assert manager.status()["ready"] is True


def test_old_generation_logs_and_probe_results_cannot_change_current_attempt(active_manager):
    manager = active_manager
    allocate(manager)
    register(manager)
    previous_generation = manager.generation - 1
    before = manager.status()

    manager._handle_line("https://stale-test.trycloudflare.com", previous_generation)
    manager._handle_line("ERR Connection terminated connIndex=0", previous_generation)
    manager._handle_line("ERR stale generation error", previous_generation)
    manager._apply_probe(previous_generation, manager.probe_epoch, True, "")

    after = manager.status()
    assert manager.url == PUBLIC_URL
    assert len(manager.connections) == 1
    for key in ("phase", "stage", "ready", "public_url", "last_error", "log_tail"):
        assert after[key] == before[key]


def test_probe_cannot_restore_ready_after_user_stops_tunnel(active_manager):
    manager = active_manager
    allocate(manager)
    register(manager)
    generation, epoch = manager.generation, manager.probe_epoch
    manager.stop()

    manager._apply_probe(generation, epoch, True, "")

    stopped = manager.status()
    assert stopped["phase"] == "off"
    assert stopped["stage"] == "off"
    assert stopped["ready"] is False
    assert stopped["public_url"] == ""


def test_continuous_verifier_rechecks_success_detects_loss_and_recovers(active_manager, monkeypatch):
    manager = active_manager
    clock = [100.0]
    monkeypatch.setattr(mac_tunnel.time, "monotonic", lambda: clock[0])
    manager.attempt_started = clock[0]
    manager.deadline_at = clock[0] + mac_tunnel.STARTUP_TIMEOUT
    allocate(manager)
    register(manager)
    results = [(True, ""), (False, "public route unavailable"), (True, "")]
    probe_times = []
    readiness = []

    def probe(url, gateway):
        assert url == PUBLIC_URL
        assert gateway is manager.gateway
        probe_times.append(clock[0])
        return results[len(probe_times) - 1]

    class ControlledCancel:
        stopped = False
        waits = 0

        def is_set(self):
            return self.stopped

        def wait(self, delay):
            self.waits += 1
            assert self.waits <= 20, "verifier failed to schedule the next bounded probe"
            if len(readiness) < len(probe_times):
                readiness.append(manager.status()["ready"])
            clock[0] += delay
            self.stopped = len(probe_times) == len(results)
            return self.stopped

    monkeypatch.setattr(manager, "_probe_public", probe)
    manager._verify(manager.generation, ControlledCancel())

    assert readiness == [True, False, True]
    assert probe_times[1] - probe_times[0] >= mac_tunnel.PROBE_INTERVAL
    assert probe_times[2] - probe_times[1] >= mac_tunnel.RETRY_INTERVAL


def test_successful_probe_after_startup_deadline_cannot_make_tunnel_ready(active_manager, monkeypatch):
    manager = active_manager
    clock = [100.0]
    monkeypatch.setattr(mac_tunnel.time, "monotonic", lambda: clock[0])
    manager.attempt_started = clock[0]
    manager.deadline_at = clock[0] + mac_tunnel.STARTUP_TIMEOUT
    allocate(manager)
    register(manager)
    process, gateway = manager.process, manager.gateway

    def late_success(url, probed_gateway):
        clock[0] = manager.deadline_at + 1
        return True, ""

    monkeypatch.setattr(manager, "_probe_public", late_success)
    manager._verify(manager.generation, manager.cancel)

    failed = manager.status()
    assert failed["phase"] == "error"
    assert failed["stage"] == "verifying"
    assert failed["ready"] is False
    assert failed["public_url"] == ""
    assert failed["verified_at"] == 0
    assert "terminate" in process.calls
    assert gateway.closed


def test_old_monitor_preserves_current_attempt_state_and_log(active_manager):
    manager = active_manager
    allocate(manager)
    current_process = manager.process
    current_log = "current generation diagnostics\n"
    manager.log_file.write_text(current_log, encoding="utf-8")
    old_process = FakeProcess()
    old_process.stdout = io.StringIO(
        "https://old-generation.trycloudflare.com\n"
        "INF Registered tunnel connection connIndex=0\n"
    )

    manager._monitor(old_process, manager.generation - 1)

    assert manager.process is current_process
    assert manager.url == PUBLIC_URL
    assert manager.status()["phase"] == "starting"
    assert manager.log_file.read_text(encoding="utf-8") == current_log
    assert "terminate" not in current_process.calls


def test_failure_stops_owned_process_and_preserves_failed_stage_and_reason(active_manager):
    manager = active_manager
    process, gateway = manager.process, manager.gateway
    allocate(manager)
    manager._handle_line(
        'ERR Unable to establish connection with Cloudflare edge error="dial tcp: i/o timeout" connIndex=0',
        manager.generation,
    )

    manager._fail(manager.generation, "Connection startup deadline exceeded")

    failed = manager.status()
    assert failed["phase"] == "error"
    assert failed["stage"] == "connecting"
    assert failed["ready"] is False
    assert "i/o timeout" in failed["last_error"]
    assert "i/o timeout" in failed["log_tail"]
    assert failed["error"]
    assert "terminate" in process.calls
    assert gateway.closed


def test_start_uses_explicit_empty_config_and_records_elapsed_time(tmp_path, monkeypatch):
    commands = []
    process = FakeProcess()
    clock = [100.0]
    binary = str(tmp_path / "cloudflared")

    class DeferredThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def join(self, timeout=None):
            pass

    def popen(command, **kwargs):
        commands.append(command)
        return process

    monkeypatch.setattr(mac_tunnel, "find_binary", lambda configured="": binary)
    monkeypatch.setattr(mac_tunnel, "PublicGateway", FakeGateway)
    monkeypatch.setattr(mac_tunnel.subprocess, "Popen", popen)
    monkeypatch.setattr(mac_tunnel.threading, "Thread", DeferredThread)
    monkeypatch.setattr(mac_tunnel.time, "monotonic", lambda: clock[0])
    manager = mac_tunnel.TunnelManager(tmp_path)

    try:
        manager.start(8767)
        clock[0] += 4.5
        command = commands[0]
        config_path = Path(command[command.index("--config") + 1])
        status = manager.status()

        assert json.loads(config_path.read_text()) == {}
        assert command[command.index("--protocol") + 1] == "http2"
        assert command[command.index("--url") + 1] == "http://127.0.0.1:34567"
        assert status["stage"] == "allocating"
        assert status["protocol"] == "http2"
        assert status["binary_path"] == str(Path(binary).resolve())
        assert 4 <= status["elapsed_seconds"] <= 5
        assert status["ready"] is False
    finally:
        manager.stop()


@pytest.mark.parametrize("text", [
    "GET https://active-test.trycloudflare.com/?key=pairing-secret&mode=quick",
    "request token=pairing-secret&mode=quick",
    '{"key":"pairing-secret","message":"i/o timeout"}',
    "Authorization: Bearer pairing-secret",
])
def test_log_redaction_hides_credentials_without_discarding_diagnostics(text):
    redacted = mac_tunnel.redact_log(text)
    assert "pairing-secret" not in redacted
    assert redacted
    if "i/o timeout" in text:
        assert "i/o timeout" in redacted


def test_runtime_diagnostics_redact_pairing_keys(active_manager):
    manager = active_manager
    manager._handle_line(
        'ERR Serve tunnel error url="https://active-test.trycloudflare.com/?key=pairing-secret" error="i/o timeout" connIndex=0',
        manager.generation,
    )

    status = manager.status()
    assert isinstance(status["log_tail"], str)
    assert "pairing-secret" not in status["log_tail"]
    assert "pairing-secret" not in status["last_error"]
    assert "i/o timeout" in status["log_tail"]
    assert "i/o timeout" in status["last_error"]


class ProbeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def getcode(self):
        return self.status

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.mark.parametrize(("status", "payload", "expected"), [
    (200, {"ok": True, "probe_id": "this-probe"}, True),
    (200, {"ok": True, "probe_id": "previous-probe"}, False),
    (200, {"ok": False, "probe_id": "this-probe"}, False),
    (200, {"ok": "true", "probe_id": "this-probe"}, False),
    (200, {"ok": True}, False),
    (200, [], False),
    (200, b"not JSON", False),
    (503, {"ok": True, "probe_id": "this-probe"}, False),
])
def test_public_probe_requires_success_and_current_gateway_identity(
    tmp_path, monkeypatch, status, payload, expected
):
    requests = []
    handlers_seen = []

    class Opener:
        def open(self, request, timeout=None):
            requests.append((getattr(request, "full_url", request), timeout))
            return ProbeResponse(status, payload)

    def opener_factory(*handlers):
        handlers_seen.extend(handlers)
        return Opener()

    monkeypatch.setattr(mac_tunnel, "build_opener", opener_factory)
    manager = mac_tunnel.TunnelManager(tmp_path)
    ok, reason = manager._probe_public(PUBLIC_URL, SimpleNamespace(probe_id="this-probe"))

    assert ok is expected
    if not expected:
        assert reason
    parsed = urlsplit(requests[0][0])
    assert parsed.scheme == "https"
    assert parsed.hostname == "active-test.trycloudflare.com"
    assert parsed.path == "/health"
    assert 0 < requests[0][1] <= mac_tunnel.PROBE_TIMEOUT
    assert any(isinstance(handler, ProxyHandler) and handler.proxies == {} for handler in handlers_seen)
    assert any(isinstance(handler, mac_tunnel.NoRedirect) for handler in handlers_seen)
    for handler in handlers_seen:
        if isinstance(handler, HTTPSHandler):
            context = handler._context
            assert context is None or (
                context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            )


def test_public_probe_reports_tls_failure_without_insecure_retry(tmp_path, monkeypatch):
    attempts = []

    class Opener:
        def open(self, request, timeout=None):
            attempts.append(request)
            raise ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(mac_tunnel, "build_opener", lambda *handlers: Opener())
    manager = mac_tunnel.TunnelManager(tmp_path)

    ok, reason = manager._probe_public(PUBLIC_URL, SimpleNamespace(probe_id="this-probe"))

    assert ok is False
    assert reason
    assert len(attempts) == 1


@pytest.mark.parametrize("status", [302, 503])
def test_public_probe_reports_http_errors_and_closes_response(tmp_path, monkeypatch, status):
    response_body = io.BytesIO(b"upstream error")

    class Opener:
        def open(self, request, timeout=None):
            raise HTTPError(PUBLIC_URL + "/health", status, "test failure", {}, response_body)

    monkeypatch.setattr(mac_tunnel, "build_opener", lambda *handlers: Opener())
    manager = mac_tunnel.TunnelManager(tmp_path)

    ok, reason = manager._probe_public(PUBLIC_URL, SimpleNamespace(probe_id="this-probe"))

    assert ok is False
    assert str(status) in reason
    assert response_body.closed


def test_probe_redirect_handler_does_not_visit_redirect_destination(services):
    make_origin, _ = services
    destination = make_origin()

    class RedirectOrigin(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/health")
            self.send_header("Content-Length", "0")
            self.end_headers()

    opener = mac_tunnel.build_opener(ProxyHandler({}), mac_tunnel.NoRedirect())
    redirector = ThreadingHTTPServer(("127.0.0.1", 0), RedirectOrigin)
    with running_server(redirector):
        with pytest.raises(HTTPError) as failure:
            opener.open(f"http://127.0.0.1:{redirector.server_port}/health", timeout=2)
        assert failure.value.code == 302
        failure.value.close()

    assert destination.requests == []
