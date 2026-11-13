"""Bounded, private CI diagnostics; these tests never contact external DNS/HTTPS."""

import hashlib
import importlib.util
import io
import json
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'smoke_cloudflare.py'
spec = importlib.util.spec_from_file_location('cloudflare_smoke_diagnostics', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
HOST = 'synthetic-diagnostics-test.trycloudflare.com'


@pytest.mark.parametrize('value', [
    None, '', 'https://' + HOST, HOST + ':443', HOST + '?key=private',
    '-flag.trycloudflare.com', 'other.example', 'a' * 64 + '.trycloudflare.com',
])
def test_candidate_is_a_bare_bounded_hostname(value):
    assert smoke.candidate_hostname(value) == ''
    assert smoke.candidate_hostname(HOST) == HOST


def test_dig_negative_cache_keeps_only_status_and_numeric_soa():
    output = ''';; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 123
;; AUTHORITY SECTION:
trycloudflare.com. 37 IN SOA private-ns.corp.invalid. admin.corp.invalid. 12345 10000 2400 604800 1800
;; SERVER: 10.20.30.40#53(10.20.30.40)
'''
    result = smoke.summarize_dig(output, 0)
    assert result['rcode'] == 'NXDOMAIN'
    assert result['authority_types'] == {'SOA': 1}
    assert result['negative_ttl_s'] == 37
    assert result['soa'] == [{'record_ttl_s': 37, 'minimum_ttl_s': 1800,
                              'effective_negative_ttl_s': 37}]
    serialized = json.dumps(result)
    assert 'corp.invalid' not in serialized
    assert '10.20.30.40' not in serialized
    assert 'trycloudflare.com' not in serialized


def test_dig_answers_expose_counts_and_ttls_without_names_or_addresses():
    output = ''';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 123
;; ANSWER SECTION:
private.corp.invalid. 60 IN CNAME internal.corp.invalid.
internal.corp.invalid. 25 IN A 10.20.30.40
internal.corp.invalid. 25 IN AAAA fd12:3456::7
'''
    result = smoke.summarize_dig(output, 0)
    assert result['answer_types'] == {'CNAME': 1, 'A': 1, 'AAAA': 1}
    assert result['answer_ttl_s'] == [25, 60]
    assert 'negative_ttl_s' not in result
    assert not any(value in json.dumps(result) for value in ('corp.invalid', '10.20.30.40', 'fd12:3456'))


def test_dig_unavailable_is_explicit_and_default_resolver_is_preserved(monkeypatch):
    monkeypatch.setattr(smoke.shutil, 'which', lambda name: None)
    assert smoke.diagnostic_dig(HOST, 'A', 4) == {'status': 'unavailable', 'available': False}
    monkeypatch.setattr(smoke.shutil, 'which', lambda name: '/test/dig')
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=';; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 1', returncode=0)

    monkeypatch.setattr(smoke.subprocess, 'run', run)
    assert smoke.diagnostic_dig(HOST, 'A', .2)['status'] == 'skipped'
    assert not calls
    assert smoke.diagnostic_dig(HOST, 'AAAA', 3)['rcode'] == 'SERVFAIL'
    command, options = calls[0]
    assert command[-2:] == [HOST, 'AAAA']
    assert not any(item.startswith('@') for item in command)
    assert options['timeout'] == 3


def test_getaddrinfo_results_and_errors_omit_private_addresses(monkeypatch):
    monkeypatch.setattr(smoke.socket, 'getaddrinfo', lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.20.30.40', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.20.30.40', 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('fd12:3456::7', 443, 0, 0)),
    ])
    result = smoke.diagnostic_resolve(HOST, socket.AF_UNSPEC)
    assert result == {'status': 'resolved', 'address_count': 2, 'ipv4_count': 1, 'ipv6_count': 1}
    error = smoke.diagnostic_error(URLError(socket.gaierror(socket.EAI_NONAME, 'private.proxy.invalid: secret')))
    assert error['category'] == 'dns'
    assert error['errno'] == socket.EAI_NONAME
    assert 'private' not in json.dumps(error)


class Response(io.BytesIO):
    status = 200


@pytest.mark.parametrize('kind', ['health', 'doh'])
def test_https_uses_verified_tls_default_proxy_and_no_redirects(monkeypatch, kind):
    import urllib.request

    proxy = 'http://private-user:private-password@private.proxy.invalid:8080'
    monkeypatch.setattr(urllib.request, 'getproxies', lambda: {'https': proxy})
    real_build_opener = smoke.build_opener
    seen = []
    if kind == 'health':
        body = {'ok': True, 'name': 'Shengjian', 'probe_id': 'private-nonce',
                'private_server_address': '10.20.30.40'}
    else:
        body = {'Status': 0, 'Answer': [
            {'name': HOST, 'type': 1, 'TTL': 123, 'data': '10.20.30.40'},
            {'name': HOST, 'type': 5, 'TTL': 60, 'data': 'private.corp.invalid'}]}

    def build(*handlers):
        opener = real_build_opener(*handlers)
        assert any(isinstance(handler, ProxyHandler) and handler.proxies == {'https': proxy}
                   for handler in opener.handlers)
        tls = next(handler for handler in opener.handlers if isinstance(handler, HTTPSHandler))
        assert tls._context.check_hostname
        assert tls._context.verify_mode == ssl.CERT_REQUIRED
        redirect = next(handler for handler in opener.handlers if isinstance(handler, smoke.NoRedirects))
        assert redirect.redirect_request(None, None, 302, '', {}, 'https://private.corp.invalid') is None

        def open_request(request, timeout):
            seen.append((request, timeout))
            return Response(json.dumps(body).encode())

        opener.open = open_request
        return opener

    monkeypatch.setattr(smoke, 'build_opener', build)
    result = smoke.diagnostic_https(HOST, 4) if kind == 'health' else smoke.diagnostic_doh(HOST, 4)
    assert result['http_status'] == 200
    assert result['tls_verification'] is True
    assert result['redirects_followed'] is False
    assert seen[0][1] == 4
    assert not any(value in json.dumps(result) for value in
                   (HOST, 'private-', '10.20.30.40', 'private.corp.invalid'))
    if kind == 'doh':
        assert seen[0][0].full_url.startswith('https://cloudflare-dns.com/dns-query?')
        assert result['rcode'] == 'NOERROR'
        assert result['answer_types'] == {'A': 1, 'CNAME': 1}
        assert result['answer_ttl_s'] == [60, 123]
    else:
        assert result['health_ok'] is True


def test_proxy_evidence_contains_only_booleans(monkeypatch):
    monkeypatch.setattr(smoke, 'getproxies', lambda: {'https': 'http://user:secret@private.invalid:8080',
                                                    'no': 'private.corp.invalid'})
    monkeypatch.setattr(smoke, 'proxy_bypass', lambda host: False)
    result = smoke.diagnostic_proxy_presence(HOST)
    assert result == {'any_configured': True, 'https_configured': True,
                      'candidate_bypassed_by_configuration': False}
    assert all(isinstance(item, bool) for item in result.values())


def test_doh_negative_answer_keeps_numeric_soa_without_authority_identity(monkeypatch):
    body = {'Status': 3, 'Authority': [{
        'name': 'private.corp.invalid', 'type': 6, 'TTL': 27,
        'data': 'private-ns.corp.invalid admin.corp.invalid 12345 10000 2400 604800 1800'}]}
    monkeypatch.setattr(smoke, 'build_opener', lambda *args: SimpleNamespace(
        open=lambda *args, **kwargs: Response(json.dumps(body).encode())))
    result = smoke.diagnostic_doh(HOST, 4)
    assert result['rcode'] == 'NXDOMAIN'
    assert result['answer_count'] == 0
    assert result['soa'] == [{'record_ttl_s': 27, 'minimum_ttl_s': 1800,
                              'effective_negative_ttl_s': 27}]
    assert 'corp.invalid' not in json.dumps(result)


@pytest.mark.parametrize('kind', ['health', 'doh'])
def test_http_redirect_is_recorded_without_following_or_disclosing_location(monkeypatch, kind):
    response = io.BytesIO(b'private response')

    def open_request(*args, **kwargs):
        raise HTTPError('https://' + HOST, 302, 'Moved', {'Location': 'https://private.invalid'}, response)

    monkeypatch.setattr(smoke, 'build_opener', lambda *args: SimpleNamespace(open=open_request))
    result = smoke.diagnostic_https(HOST, 4) if kind == 'health' else smoke.diagnostic_doh(HOST, 4)
    assert result['http_status'] == 302
    assert result['redirects_followed'] is False
    assert response.closed
    assert 'private' not in json.dumps(result)


def test_first_active_error_is_captured_twice_at_most_and_persisted_redacted(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(smoke.time, 'monotonic', lambda: clock[0])
    evidence = smoke.Evidence(tmp_path / 'evidence')
    budget = SimpleNamespace(deadline=300)
    calls = []
    monkeypatch.setattr(smoke, 'collect_diagnostics', lambda host, budget: calls.append(host) or
                        {'status': 'completed', 'checks': {'default_https': {'http_status': 200}}})
    diagnostics = smoke.PublicDiagnostics(evidence, budget)
    state = {'managed': True, 'phase': 'starting', 'stage': 'verifying', 'candidate_host': HOST,
             'last_error': f'DNS failed for {HOST}; 10.20.30.40; fd12:3456::7; '
                           'http://user:secret@private.proxy.invalid:8080',
             'ready': False, 'url_assignments': 1}
    for change in ({'managed': False}, {'stage': 'connecting'}, {'last_error': ''}, {'candidate_host': ''}):
        diagnostics.observe({**state, **change})
    assert calls == []
    diagnostics.observe(state)
    clock[0] = 119.99
    diagnostics.observe(state)
    assert len(calls) == 1
    clock[0] = 120
    diagnostics.observe(state)
    clock[0] = 160
    diagnostics.observe(state)
    assert calls == [HOST, HOST]
    assert HOST in evidence.secrets
    entry = evidence.result['diagnostics'][0]
    assert entry['candidate_host_sha256'] == hashlib.sha256(HOST.encode()).hexdigest()
    assert entry['managed_at_capture'] is True
    assert entry['ready_at_capture'] is False
    assert state['ready'] is False
    assert entry['diagnostics_do_not_set_ready'] is True
    evidence.result['ok'] = True
    evidence.save(tmp_path / 'data', tmp_path / 'stdout.log')
    saved = (evidence.folder / 'result.json').read_text()
    assert not any(value in saved for value in (HOST, '10.20.30.40', 'fd12:3456', 'private.proxy', 'user:secret'))


def test_successful_diagnostic_does_not_override_failed_tunnel(tmp_path, monkeypatch):
    evidence = smoke.Evidence(tmp_path / 'evidence')
    states = iter([
        {'mode': 'cloudflare', 'enabled': True, 'ready': False, 'cloudflare': {
            'phase': 'starting', 'stage': 'verifying', 'managed': True, 'ready': False,
            'candidate_host': HOST, 'last_error': 'DNS failed'}},
        {'mode': 'cloudflare', 'enabled': True, 'ready': False, 'cloudflare': {
            'phase': 'error', 'stage': 'verifying', 'managed': False, 'ready': False,
            'candidate_host': HOST, 'last_error': 'DNS failed', 'error': 'DNS failed'}},
    ])
    budget = SimpleNamespace(deadline=time.monotonic() + 180, pause=lambda seconds: None)
    service = SimpleNamespace(control=lambda *args: next(states), process=SimpleNamespace(poll=lambda: None),
                              budget=budget, tunnel_requested=False)
    monkeypatch.setattr(smoke, 'check_running_binary', lambda *args: None)
    monkeypatch.setattr(smoke, 'collect_diagnostics', lambda *args: {
        'status': 'completed', 'checks': {'default_https': {'http_status': 200, 'health_ok': True}}})
    with pytest.raises(smoke.CheckFailed, match='tunnel failed: DNS failed'):
        smoke.start_tunnel(service, SimpleNamespace(), evidence, 'unused')
    assert evidence.result['ok'] is False
    assert len(evidence.result['diagnostics']) == 1


def test_uninterruptible_resolver_stays_in_disposable_child():
    # A real subprocess with blocked resolver threads must still return partial
    # results and exit. Every network function is replaced inside that process.
    program = '''import json, runpy, threading
ns = runpy.run_path(%r, run_name='diagnostic_test')
worker = ns['diagnostic_worker']
def blocked(*args):
    threading.Event().wait(60)
worker.__globals__['diagnostic_resolve'] = blocked
worker.__globals__['diagnostic_proxy_presence'] = lambda *args: {'any_configured': False}
worker.__globals__['diagnostic_https'] = lambda *args: {'status': 'response', 'http_status': 200}
worker.__globals__['diagnostic_dig'] = lambda *args: {'status': 'unavailable', 'available': False}
worker.__globals__['diagnostic_doh'] = lambda *args: {'status': 'response', 'rcode': 'NOERROR'}
print(json.dumps(worker(%r, .15)))
''' % (str(SCRIPT), HOST)
    started = time.monotonic()
    completed = subprocess.run([sys.executable, '-c', program], text=True, capture_output=True,
                               timeout=3, check=True)
    assert time.monotonic() - started < 3
    result = json.loads(completed.stdout)
    assert result['getaddrinfo_unspecified']['status'] == 'timeout'
    assert result['getaddrinfo_ipv4']['status'] == 'timeout'
    assert result['default_https']['http_status'] == 200


def test_parent_kills_hung_worker_within_existing_budget(monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def start(command, **kwargs):
        if '--diagnostics-worker' in command:
            command = [sys.executable, '-c', 'import time; time.sleep(30)']
        child = real_popen(command, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(smoke.subprocess, 'Popen', start)
    monkeypatch.setattr(smoke, 'DIAGNOSTIC_LIMIT_SECONDS', 2.2)
    budget = smoke.Budget(5)
    original_deadline = budget.deadline
    started = time.monotonic()
    result = smoke.collect_diagnostics(HOST, budget)
    assert result['status'] == 'worker_timeout'
    assert time.monotonic() - started < 3
    assert children[0].poll() is not None
    assert budget.deadline == original_deadline


def test_near_deadline_skips_diagnostics_without_extending_budget(monkeypatch):
    monkeypatch.setattr(smoke.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('must not launch a worker'))
    budget = smoke.Budget(1)
    original_deadline = budget.deadline
    assert smoke.collect_diagnostics(HOST, budget) == {'status': 'skipped', 'reason': 'overall_deadline_near'}
    assert budget.deadline == original_deadline
