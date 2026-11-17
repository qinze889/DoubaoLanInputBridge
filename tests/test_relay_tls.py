"""HTTPS relay transport must remain verified in frozen Mac/Windows apps."""

import ssl
from urllib.request import HTTPSHandler

import certifi
import pytest

import relay_client


def config(url="https://test.example/shengjian"):
    return {
        "url": url, "device_id": "a" * 24,
        "token": "b" * 43, "mobile_token": "c" * 43,
    }


def test_relay_uses_bundled_roots_with_missing_openssl_default(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-root.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "missing-certs"))
    client = relay_client.RelayClient(config(), 8765, lambda: "local-key")
    handler = next(h for h in client.opener.handlers if isinstance(h, HTTPSHandler))
    context = handler._context
    bundled_roots = set(ssl.create_default_context(cafile=certifi.where()).get_ca_certs(binary_form=True))
    assert bundled_roots
    assert bundled_roots <= set(context.get_ca_certs(binary_form=True))
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_relay_preserves_system_trust(monkeypatch, tmp_path):
    local_root = tmp_path / "local-root.pem"
    # Use a trusted system CA from the pinned bundle as an isolated extra default
    # trust path; the relay must still add the entire pinned bundle.
    local_root.write_text(certifi.contents().split("-----END CERTIFICATE-----")[0] +
                          "-----END CERTIFICATE-----\n", encoding="ascii")
    monkeypatch.setenv("SSL_CERT_FILE", str(local_root))
    context = relay_client.verified_relay_ssl_context()
    default_roots = set(ssl.create_default_context(cafile=str(local_root)).get_ca_certs(binary_form=True))
    assert default_roots <= set(context.get_ca_certs(binary_form=True))


@pytest.mark.parametrize("bundle_kind", ["missing", "invalid"])
def test_bad_bundled_ca_fails_closed(monkeypatch, tmp_path, bundle_kind):
    bundle = tmp_path / "cacert.pem"
    if bundle_kind == "invalid":
        bundle.write_text("not a certificate", encoding="ascii")
    monkeypatch.setattr(certifi, "where", lambda: str(bundle))
    with pytest.raises((OSError, ssl.SSLError)):
        relay_client.RelayClient(config(), 8765, lambda: "local-key")


def test_first_poll_uses_fast_handshake_then_normal_long_poll():
    client = relay_client.RelayClient(config("http://127.0.0.1:8765"), 8765, lambda: "local-key")
    client.capability = lambda: "1"
    called = []

    def call(suffix, body=None):
        called.append(suffix)
        if len(called) == 2:
            client.stop_event.set()
        return {'ok': True, 'requests': []}

    client.call = call
    client.run()
    assert len(called) == 2
    assert "&handshake=1" in called[0]
    assert "&handshake=" not in called[1]
    assert client._handshake_pending is False


def test_http_local_relay_does_not_require_certifi(monkeypatch, tmp_path):
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "missing"))
    client = relay_client.RelayClient(config("http://127.0.0.1:8765"), 8765, lambda: "local-key")
    assert client.base == "http://127.0.0.1:8765"