"""Portable verified TLS without relying on a build runner's OpenSSL CA paths."""

import importlib.util
import os
import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

import certifi
import pytest

import mac_tunnel


# Public, test-only root certificate. Its private key was discarded; this is
# never added to the application bundle or used by the live public E2E check.
LOCAL_TEST_CA = """-----BEGIN CERTIFICATE-----
MIIBwTCCAWegAwIBAgIUMFyTt6o/RrY43pkHFJRRT7jaysUwCgYIKoZIzj0EAwIw
LTErMCkGA1UEAwwiU2hlbmdqaWFuIGxvY2FsIHJlZ3Jlc3Npb24gQ0Egb25seTAg
Fw0yNjExMTMxMzM1MjVaGA8yMTI2MTAyMDEzMzUyNVowLTErMCkGA1UEAwwiU2hl
bmdqaWFuIGxvY2FsIHJlZ3Jlc3Npb24gQ0Egb25seTBZMBMGByqGSM49AgEGCCqG
SM49AwEHA0IABHK1hhvT6ung4tk41g8p6m4/kkm16SqFKZgoVYH1pIoRS0NcE9xw
M+xDvGVAhrmO276Jd7upnjt5pDpaINtqNIGjYzBhMB0GA1UdDgQWBBRy51uc0T70
qohv0MN8XJqLgIDl/jAfBgNVHSMEGDAWgBRy51uc0T70qohv0MN8XJqLgIDl/jAP
BgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBBjAKBggqhkjOPQQDAgNIADBF
AiEA+JrB7+gOVreUg+y2+76C1g13alr0BUYGKZvEYEm9jr8CIFOsNIpnpdPMvTKd
8GuhKJBxgyAIPSPxeJDbtFgUKEsR
-----END CERTIFICATE-----
"""


def default_ca_paths(monkeypatch, tmp_path, content=None):
    cafile = tmp_path / 'default-ca.pem'
    capath = tmp_path / 'default-ca-directory'
    capath.mkdir()
    if content is not None:
        cafile.write_text(content, encoding='ascii')
    monkeypatch.setenv('SSL_CERT_FILE', str(cafile))
    monkeypatch.setenv('SSL_CERT_DIR', str(capath))


def bundled_roots():
    context = ssl.create_default_context(cafile=certifi.where())
    roots = set(context.get_ca_certs(binary_form=True))
    assert roots, 'the pinned certifi bundle must contain usable CA certificates'
    return roots


def test_probe_has_verified_tls_when_default_openssl_ca_paths_are_missing(monkeypatch, tmp_path):
    default_ca_paths(monkeypatch, tmp_path)
    default_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))
    assert ssl.get_default_verify_paths().cafile is None
    # CPython can retain built-in certificate policy entries even with empty
    # paths. Windows also loads its native store; only require missing public
    # roots on OpenSSL platforms, rather than assuming the store is empty.
    if sys.platform != 'win32':
        assert bundled_roots() - default_roots

    context = mac_tunnel.public_probe_ssl_context()

    assert bundled_roots() <= set(context.get_ca_certs(binary_form=True))
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_probe_keeps_existing_default_trust_and_adds_bundled_roots(monkeypatch, tmp_path):
    default_ca_paths(monkeypatch, tmp_path, LOCAL_TEST_CA)
    existing_root = ssl.PEM_cert_to_DER_cert(LOCAL_TEST_CA)
    assert existing_root in ssl.create_default_context().get_ca_certs(binary_form=True)

    context = mac_tunnel.public_probe_ssl_context()
    roots = set(context.get_ca_certs(binary_form=True))

    assert existing_root in roots
    assert bundled_roots() <= roots
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.parametrize('bundle_state', ['missing', 'invalid'])
def test_missing_or_invalid_bundled_ca_fails_closed_before_network(monkeypatch, tmp_path, bundle_state):
    bundle = tmp_path / 'cacert.pem'
    if bundle_state == 'invalid':
        bundle.write_text('this is not a CA certificate', encoding='ascii')
    monkeypatch.setattr(certifi, 'where', lambda: str(bundle))

    def forbidden_opener(*args, **kwargs):
        pytest.fail('a broken bundled CA must not fall back to an unverified/network request')

    monkeypatch.setattr(mac_tunnel, 'build_opener', forbidden_opener)
    manager = mac_tunnel.TunnelManager(tmp_path)
    ok, reason = manager._probe_public(
        'https://ca-test.trycloudflare.com', SimpleNamespace(probe_id='local-test'))

    assert ok is False
    assert reason


@pytest.fixture
def smoke_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/smoke_cloudflare.py'
    spec = importlib.util.spec_from_file_location('smoke_cloudflare_ca_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_service_environment(monkeypatch, tmp_path, smoke, packaged, platform):
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setenv('SSL_CERT_FILE', 'outer-client-ca.pem')
    monkeypatch.setenv('SSL_CERT_DIR', 'outer-client-ca-directory')
    original_debug = 'netdns=go,x509sslcertoverrideplatform=1,http2client=0'
    monkeypatch.setenv('GODEBUG', original_debug)
    args = SimpleNamespace(service=tmp_path / 'bridge-service' if packaged else None,
                           cloudflared=tmp_path / 'cloudflared',
                           service_kind='mac' if platform == 'darwin' and packaged else 'gui')
    evidence = smoke.Evidence(tmp_path / 'evidence')
    service = smoke.Service(args, tmp_path / 'data', evidence, smoke.Budget(30))
    captured = {}

    class LaunchCaptured(Exception):
        pass

    def capture(command, **kwargs):
        captured.update(kwargs['env'])
        raise LaunchCaptured

    monkeypatch.setattr(smoke.subprocess, 'Popen', capture)
    try:
        with pytest.raises(LaunchCaptured):
            service.start()
    finally:
        service.close()
    assert os.environ['SSL_CERT_FILE'] == 'outer-client-ca.pem'
    assert os.environ['SSL_CERT_DIR'] == 'outer-client-ca-directory'
    assert os.environ['GODEBUG'] == original_debug
    return captured, evidence.result


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_packaged_smoke_isolates_python_ca_without_breaking_go_platform_trust(
        monkeypatch, tmp_path, smoke_module, platform):
    env, result = capture_service_environment(monkeypatch, tmp_path, smoke_module, True, platform)

    assert not Path(env['SSL_CERT_FILE']).exists()
    assert Path(env['SSL_CERT_DIR']).is_dir()
    assert list(Path(env['SSL_CERT_DIR']).iterdir()) == []
    assert env['GODEBUG'] == 'netdns=go,http2client=0,x509sslcertoverrideplatform=0'
    assert result['service_tls'] == {
        'default_openssl_ca_paths_isolated': True,
        'go_platform_trust_preserved': True,
        'tls_verification': True,
    }


@pytest.mark.parametrize(('packaged', 'platform'), [(False, 'linux'), (False, 'darwin'), (True, 'linux')])
def test_other_smoke_modes_preserve_the_callers_certificate_environment(
        monkeypatch, tmp_path, smoke_module, packaged, platform):
    env, result = capture_service_environment(monkeypatch, tmp_path, smoke_module, packaged, platform)

    assert env['SSL_CERT_FILE'] == 'outer-client-ca.pem'
    assert env['SSL_CERT_DIR'] == 'outer-client-ca-directory'
    assert env['GODEBUG'] == 'netdns=go,x509sslcertoverrideplatform=1,http2client=0'
    assert result['service_tls']['default_openssl_ca_paths_isolated'] is False
