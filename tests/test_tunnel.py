"""公网隧道托管：配置读写、配置解析、候选探测、启停语义与取址联动。"""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "gui_app.py"


def load_app():
    spec = importlib.util.spec_from_file_location("gui_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.IS_MACOS = False  # Retained Windows named-tunnel tests.
    return module


class FakeProcess:
    """最小可用的 Popen 替身。"""

    def __init__(self, pid=4321):
        self.pid = pid
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        self._alive = False
        return 0


def isolated_tunnel_env(app, monkeypatch, tmp_path, **config):
    """把隧道配置与两个公网配置文件的落点都指向临时目录。"""
    app._reset_tunnel_process_state()
    tunnel_file = tmp_path / "tunnel.json"
    monkeypatch.setattr(app, "TUNNEL_CONFIG_FILE", tunnel_file)
    monkeypatch.setattr(app, "PUBLIC_URL_FILE", tmp_path / "missing_public_url.txt")
    monkeypatch.setattr(app, "PUBLIC_PROBE_FILE", tmp_path / "missing_public_probe.txt")
    monkeypatch.delenv(app.PUBLIC_URL_ENV, raising=False)
    monkeypatch.delenv(app.PUBLIC_PROBE_ENV, raising=False)
    if config:
        app.write_tunnel_config(config, tunnel_file)
    return tunnel_file


# ------------------------------------------------------------------ 配置读写


def test_tunnel_config_defaults_when_file_missing(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "TUNNEL_CONFIG_FILE", tmp_path / "nope.json")

    config = app.read_tunnel_config()

    assert config["enabled"] is False
    assert config["name"] == ""
    assert config["public_url"] == ""
    assert config["metrics_port"] == app.TUNNEL_DEFAULT_METRICS_PORT


def test_tunnel_config_defaults_when_file_corrupt(tmp_path, monkeypatch):
    app = load_app()
    broken = tmp_path / "tunnel.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(app, "TUNNEL_CONFIG_FILE", broken)

    assert app.read_tunnel_config()["enabled"] is False


def test_tunnel_config_roundtrip_normalizes_fields(tmp_path, monkeypatch):
    app = load_app()
    target = tmp_path / "tunnel.json"
    monkeypatch.setattr(app, "TUNNEL_CONFIG_FILE", target)

    saved = app.write_tunnel_config(
        {
            "enabled": True,
            "name": "  shenjian  ",
            "public_url": "https://sj.q-ze.top/",
            "metrics_port": "20244",
        },
        target,
    )

    assert saved["name"] == "shenjian"
    assert saved["public_url"] == "https://sj.q-ze.top"
    assert saved["metrics_port"] == 20244
    assert app.read_tunnel_config(target) == saved


def test_tunnel_config_rejects_out_of_range_metrics_port(tmp_path, monkeypatch):
    app = load_app()
    target = tmp_path / "tunnel.json"

    saved = app.write_tunnel_config({"metrics_port": 99999}, target)

    assert saved["metrics_port"] == app.TUNNEL_DEFAULT_METRICS_PORT


def test_write_tunnel_config_invalidates_probe_cache(tmp_path, monkeypatch):
    """改了隧道状态，旧的入口判定必须立刻失效，否则二维码会继续用过期结论。"""
    app = load_app()
    target = tmp_path / "tunnel.json"
    monkeypatch.setattr(app, "TUNNEL_CONFIG_FILE", target)
    monkeypatch.setattr(app, "_public_entry_probe_state", {"checked_at": 123.0, "ok": True})

    app.write_tunnel_config({"enabled": True, "public_url": "https://sj.q-ze.top"}, target)

    assert app._public_entry_probe_state["checked_at"] == 0.0


# ------------------------------------------------------------------ 取址联动


def test_public_url_comes_from_tunnel_config_when_enabled(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(
        app,
        monkeypatch,
        tmp_path,
        enabled=True,
        name="shenjian",
        public_url="https://sj.q-ze.top",
    )

    assert app.read_public_url_override() == "https://sj.q-ze.top"
    assert app.read_public_probe_override() == "http://127.0.0.1:20244/ready"


def test_public_url_ignored_when_tunnel_disabled(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(
        app,
        monkeypatch,
        tmp_path,
        enabled=False,
        name="shenjian",
        public_url="https://sj.q-ze.top",
    )

    assert app.read_public_url_override() == ""
    assert app.build_access_url("192.168.1.171", 8765, "k") == "http://192.168.1.171:8765/?key=k"


def test_public_url_env_beats_tunnel_config(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(
        app,
        monkeypatch,
        tmp_path,
        enabled=True,
        name="shenjian",
        public_url="https://sj.q-ze.top",
    )
    monkeypatch.setenv(app.PUBLIC_URL_ENV, "https://from-env.example/")

    assert app.read_public_url_override() == "https://from-env.example"


def test_access_url_falls_back_to_lan_when_tunnel_unreachable(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(
        app,
        monkeypatch,
        tmp_path,
        enabled=True,
        name="shenjian",
        public_url="https://sj.q-ze.top",
    )
    monkeypatch.setattr(app, "probe_public_entry", lambda probe_url, timeout=2.0: False)

    assert app.build_access_url("192.168.1.171", 8765, "k") == "http://192.168.1.171:8765/?key=k"


# ------------------------------------------------------------------ 配置解析


def test_parse_tunnel_config_reads_uuid_and_ingress_hostname():
    app = load_app()

    parsed = app.parse_tunnel_config_text(
        "tunnel: c2901f65-7abf-4768-a34b-f2bd6f8e1705\n"
        "credentials-file: C:\\Users\\0\\.cloudflared\\c2901f65.json\n"
        "protocol: http2\n"
        "\n"
        "ingress:\n"
        "  - hostname: sj.q-ze.top\n"
        "    service: http://127.0.0.1:8765\n"
        "  - service: http_status:404\n"
    )

    assert parsed["tunnel"] == "c2901f65-7abf-4768-a34b-f2bd6f8e1705"
    assert parsed["hostnames"] == ["sj.q-ze.top"]


def test_parse_tunnel_config_accepts_named_tunnel_and_flat_list_indent():
    app = load_app()

    parsed = app.parse_tunnel_config_text(
        "tunnel: my-named-tunnel\n"
        "ingress:\n"
        "- hostname: a.example.com\n"
        "  service: http://127.0.0.1:8765\n"
    )

    assert parsed["tunnel"] == "my-named-tunnel"
    assert parsed["hostnames"] == ["a.example.com"]


def test_parse_tunnel_config_stops_at_next_top_level_key():
    app = load_app()

    parsed = app.parse_tunnel_config_text(
        "tunnel: abc\n"
        "ingress:\n"
        "  - hostname: kept.example.com\n"
        "originRequest:\n"
        "  - hostname: ignored.example.com\n"
    )

    assert parsed["hostnames"] == ["kept.example.com"]


def test_parse_tunnel_config_tolerates_garbage():
    app = load_app()

    parsed = app.parse_tunnel_config_text("garbage: [unclosed\n\x00binary\xff\n")

    assert parsed == {"tunnel": "", "hostnames": []}


def test_detect_tunnel_candidates_scans_cloudflared_home(tmp_path):
    app = load_app()
    root = tmp_path / ".cloudflared"
    (root / "shenjian").mkdir(parents=True)
    (root / "shenjian" / "config.yml").write_text(
        "tunnel: c2901f65\n"
        "ingress:\n"
        "  - hostname: sj.q-ze.top\n"
        "    service: http://127.0.0.1:8765\n",
        encoding="utf-8",
    )
    (root / "no-config").mkdir()
    (root / "voice-gate").mkdir()
    (root / "voice-gate" / "config.yml").write_text(
        "tunnel: f89292f3\ningress:\n  - hostname: vg.q-ze.top\n",
        encoding="utf-8",
    )

    candidates = app.detect_tunnel_candidates(root)

    assert [item["name"] for item in candidates] == ["shenjian", "voice-gate"]
    assert candidates[0]["public_url"] == "https://sj.q-ze.top"
    assert candidates[1]["hostnames"] == ["vg.q-ze.top"]


def test_detect_tunnel_candidates_returns_empty_for_missing_root(tmp_path):
    app = load_app()

    assert app.detect_tunnel_candidates(tmp_path / "nope") == []


# ------------------------------------------------------------------ 进程生命周期


def test_build_tunnel_command_matches_supervised_launch(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "DATA_DIR", tmp_path)

    command = app.build_tunnel_command(
        {
            "name": "shenjian",
            "metrics_port": 20244,
            "config_path": "C:\\cf\\config.yml",
        },
        "cloudflared.exe",
    )

    assert command[0] == "cloudflared.exe"
    assert command[1] == "tunnel"
    assert "--no-autoupdate" in command
    assert "--config" in command and "C:\\cf\\config.yml" in command
    assert "127.0.0.1:20244" in command
    assert command[-2:] == ["run", "shenjian"]
    assert command[command.index("--logfile") + 1] == str(app.tunnel_log_path("shenjian"))


def test_start_tunnel_requires_cloudflared(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "")

    try:
        app.start_tunnel()
    except RuntimeError as exc:
        assert "cloudflared" in str(exc)
    else:
        raise AssertionError("缺少 cloudflared 时应报错")


def test_start_tunnel_requires_name(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")

    try:
        app.start_tunnel()
    except RuntimeError as exc:
        assert "隧道名称" in str(exc)
    else:
        raise AssertionError("缺少隧道名称时应报错")


def test_start_tunnel_rejects_missing_config_path(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(
        app,
        monkeypatch,
        tmp_path,
        enabled=True,
        name="shenjian",
        config_path=str(tmp_path / "absent.yml"),
    )
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")

    try:
        app.start_tunnel()
    except RuntimeError as exc:
        assert "隧道配置不存在" in str(exc)
    else:
        raise AssertionError("配置路径不存在时应报错")


def test_start_tunnel_spawns_and_records_own_pid(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")
    monkeypatch.setattr(app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: False)
    monkeypatch.setattr(app, "wait_for_tunnel_ready", lambda probe_url, timeout=None: True)

    spawned = []

    def fake_popen(command, **kwargs):
        spawned.append((command, kwargs))
        return FakeProcess(pid=7788)

    status = app.start_tunnel(popen_factory=fake_popen)

    assert len(spawned) == 1
    assert spawned[0][0][-2:] == ["run", "shenjian"]
    assert status["managed"] is True
    assert status["owned_pid"] == 7788
    assert app.tunnel_owned_pid() == 7788


def test_start_tunnel_does_not_double_spawn_when_external_tunnel_healthy(tmp_path, monkeypatch):
    """外部（例如计划任务）已拉起且健康时，不应再拉一个连接器。"""
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")
    monkeypatch.setattr(app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: True)

    def unexpected_popen(*args, **kwargs):
        raise AssertionError("隧道已健康时不应重复拉起")

    status = app.start_tunnel(popen_factory=unexpected_popen)

    assert status["ready"] is True
    assert status["managed"] is False
    assert app.tunnel_owned_pid() == 0


def test_start_tunnel_is_idempotent_when_already_managed(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")
    monkeypatch.setattr(app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: False)
    monkeypatch.setattr(app, "wait_for_tunnel_ready", lambda probe_url, timeout=None: True)

    calls = []

    def fake_popen(command, **kwargs):
        calls.append(command)
        return FakeProcess(pid=1001)

    app.start_tunnel(popen_factory=fake_popen)
    app.start_tunnel(popen_factory=fake_popen)

    assert len(calls) == 1


def test_stop_tunnel_refuses_to_kill_external_process(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")

    def unexpected_run(*args, **kwargs):
        raise AssertionError("外部托管的隧道不应被 taskkill")

    result = app.stop_tunnel(runner=unexpected_run)

    assert result == {"stopped": False, "reason": "external"}


def test_stop_tunnel_kills_only_owned_process(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")
    monkeypatch.setattr(app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: False)
    monkeypatch.setattr(app, "wait_for_tunnel_ready", lambda probe_url, timeout=None: True)

    process = FakeProcess(pid=2468)
    app.start_tunnel(popen_factory=lambda command, **kwargs: process)

    killed = []

    class FakeResult:
        returncode = 0

    killed.append(None)
    result = app.stop_tunnel(runner=lambda command, **kwargs: killed.__setitem__(0, command) or FakeResult())

    assert killed[0] == ["taskkill", "/PID", "2468", "/T", "/F"]
    assert result == {"stopped": True, "reason": "managed"}
    assert app.tunnel_owned_pid() == 0


def test_tunnel_owned_pid_clears_when_process_exited(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(app, monkeypatch, tmp_path, enabled=True, name="shenjian")
    monkeypatch.setattr(app, "IS_WINDOWS", True)
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": "cloudflared.exe")
    monkeypatch.setattr(app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: False)
    monkeypatch.setattr(app, "wait_for_tunnel_ready", lambda probe_url, timeout=None: True)

    process = FakeProcess(pid=555)
    app.start_tunnel(popen_factory=lambda command, **kwargs: process)
    process._alive = False

    assert app.tunnel_owned_pid() == 0
    assert app.tunnel_status()["managed"] is False


def test_tunnel_status_reports_probe_and_availability(tmp_path, monkeypatch):
    app = load_app()
    isolated_tunnel_env(
        app,
        monkeypatch,
        tmp_path,
        enabled=True,
        name="shenjian",
        public_url="https://sj.q-ze.top",
    )
    monkeypatch.setattr(app, "find_cloudflared", lambda configured="": r"C:\cf\cloudflared.exe")
    monkeypatch.setattr(app, "fetch_public_entry_status", lambda probe_url, timeout=2.0: True)

    status = app.tunnel_status()

    assert status["enabled"] is True
    assert status["ready"] is True
    assert status["running"] is True
    assert status["managed"] is False
    assert status["probe_url"] == "http://127.0.0.1:20244/ready"
    assert status["cloudflared_available"] is True


def test_tunnel_log_tail_reads_only_the_tail(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "DATA_DIR", tmp_path)
    log = app.tunnel_log_path("shenjian")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("x" * 5000 + "TAIL-MARKER", encoding="utf-8")

    tail = app.tunnel_log_tail("shenjian", limit=32)

    assert "TAIL-MARKER" in tail
    assert len(tail.encode("utf-8")) <= 32


def test_tunnel_log_tail_missing_file_is_empty(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "DATA_DIR", tmp_path)

    assert app.tunnel_log_tail("nope") == ""
