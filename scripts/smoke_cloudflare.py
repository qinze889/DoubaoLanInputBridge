"""Exercise a real Quick Tunnel through the actual service and public HTTPS.

Release jobs must pass --service from the final installed/mounted package and
--cloudflared from that package (an extracted copy is OK for a one-file EXE).
Without --service this runs the real source BridgeServer, and labels the result
as a source check. No cloudflared output or network response is simulated.

Only synthetic files in a temporary app-data directory are exposed. Successful
uploads use /files/share; clipboard/paste upload endpoints receive only requests
that must fail authentication without side effects. A pass describes this runner
and network; it does not certify the user's phone/network.
"""

import argparse
import hashlib
import http.client
import json
import os
import queue
import re
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (HTTPRedirectHandler, HTTPSHandler, Request, build_opener,
                            getproxies, proxy_bypass)


ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
LOG_TAIL_BYTES = 128 * 1024
FILE_BYTES = 1024 * 1024 + 37
DIAGNOSTIC_LIMIT_SECONDS = 12
DIAGNOSTIC_INTERVAL_SECONDS = 20


class CheckFailed(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_tail(path, limit=LOG_TAIL_BYTES):
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            text = stream.read(limit).decode('utf-8', errors='replace')
        return ('[earlier log lines omitted]\n' if size > limit else '') + text
    except OSError:
        return '[log unavailable]\n'


class Budget:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds

    def timeout(self, maximum=10):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CheckFailed('overall E2E deadline exceeded')
        return min(maximum, remaining)

    def pause(self, seconds=.3):
        time.sleep(self.timeout(seconds))


class Evidence:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.secrets = []
        self.stage = 'preflight'
        self.started = time.monotonic()
        self.result = {
            'ok': False,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'platform': sys.platform,
            'python': sys.version.split()[0],
            'source_sha': os.environ.get('GITHUB_SHA', ''),
            'tls_verification': True,
            'public_client_location': 'same host/network as the tested service',
            'scope': 'real public HTTPS, real packaged/source BridgeServer, synthetic data only',
            'user_phone_or_user_network_tested': False,
            'stages': [],
            'diagnostics': [],
        }

    def redact(self, value):
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if not isinstance(value, str):
            return value
        for secret in self.secrets:
            if secret:
                value = value.replace(secret, '[redacted]').replace(quote(secret, safe=''), '[redacted]')
        value = re.sub(r'(?i)([?&](?:key|token|secret|access_token)=)[^&\s\"\']+', r'\1[redacted]', value)
        value = re.sub(r'(?i)(\b(?:Bearer|Basic)\s+)[^\s,\"\']+', r'\1[redacted]', value)
        value = re.sub(
            r'(?i)([\"\']?(?:key|access_key|tunnel_secret|tunnelsecret|token|secret|authorization|password)[\"\']?\s*[:=]\s*)'
            r'(?:\"[^\"]*\"|\'[^\']*\'|[^,\s}\]]+)',
            r'\1[redacted]', value,
        )
        return re.sub(r'https://[a-z0-9-]+\.trycloudflare\.com(?:/[^\s\"\']*)?',
                      'https://[redacted].trycloudflare.com', value, flags=re.I)

    def begin(self, stage):
        self.stage = stage
        print(f'[Cloudflare E2E] {stage}', flush=True)

    def passed(self, **details):
        self.result['stages'].append({'stage': self.stage, 'ok': True,
                                      'elapsed_s': round(time.monotonic() - self.started, 3), **details})

    def failed(self, error):
        self.result['ok'] = False
        self.result.setdefault('failed_stage', self.stage)
        message = f'{type(error).__name__}: {error}'
        self.result['stages'].append({'stage': self.stage, 'ok': False,
                                      'error': self.redact(message)})
        print(f'[Cloudflare E2E] FAILED at {self.stage}: {self.redact(message)}', flush=True)

    def save(self, data_dir, stdout_log):
        logs = {
            'cloudflare.log': read_tail(data_dir / 'cloudflare.log'),
            'service.log': '=== service stdout/stderr ===\n' + read_tail(stdout_log)
                           + '\n=== application log ===\n' + read_tail(data_dir / 'service.log'),
        }
        for name, content in logs.items():
            (self.folder / name).write_text(self.redact(content), encoding='utf-8')
        self.result['elapsed_s'] = round(time.monotonic() - self.started, 3)
        self.result['finished_at'] = datetime.now(timezone.utc).isoformat()
        (self.folder / 'result.json').write_text(
            json.dumps(self.redact(self.result), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if not self.result['ok']:
            for name, content in logs.items():
                print(f'--- sanitized {name} tail ---', flush=True)
                print(self.redact('\n'.join(content.splitlines()[-60:])), flush=True)


def response_bytes(response):
    body = response.read(MAX_RESPONSE_BYTES + 1)
    require(len(body) <= MAX_RESPONSE_BYTES, 'HTTP response exceeds the test size limit')
    return response.status, dict(response.headers.items()), body


def decode_json(status, body, expected=200):
    require(status == expected, f'API returned HTTP {status}; expected {expected}')
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise CheckFailed('API did not return valid JSON') from None
    require(isinstance(value, dict) and value.get('ok') is True, 'API did not confirm success')
    return value


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None  # Never forward a pairing key to another host.


def candidate_hostname(value):
    """Accept only a bare Quick Tunnel hostname, never a URL or resolver option."""
    if not isinstance(value, str) or len(value) > 80:
        return ''
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', value):
        return ''
    return value if len(value.split('.', 1)[0]) <= 63 else ''


def diagnostic_error(error):
    """Network exception text can contain private proxy hosts and credentials."""
    reason = error.reason if isinstance(error, URLError) else error
    result = {'error_type': type(error).__name__, 'reason_type': type(reason).__name__}
    if isinstance(reason, socket.gaierror):
        result['category'] = 'dns'
    elif isinstance(reason, ssl.SSLCertVerificationError):
        result['category'] = 'tls_certificate'
    elif isinstance(reason, ssl.SSLError):
        result['category'] = 'tls'
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        result['category'] = 'timeout'
    elif isinstance(error, HTTPError):
        result['category'] = 'http'
        result['http_status'] = error.code
    else:
        result['category'] = 'connection' if isinstance(reason, OSError) else 'other'
    if isinstance(getattr(reason, 'errno', None), int):
        result['errno'] = reason.errno
    if isinstance(getattr(reason, 'verify_code', None), int):
        result['verify_code'] = reason.verify_code
    return result


def diagnostic_resolve(host, family):
    addresses = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
    unique = {(entry[0], entry[4][0]) for entry in addresses}
    return {'status': 'resolved', 'address_count': len(unique),
            'ipv4_count': sum(item[0] == socket.AF_INET for item in unique),
            'ipv6_count': sum(item[0] == socket.AF_INET6 for item in unique)}


def diagnostic_proxy_presence(host):
    proxies = getproxies()
    https_configured = bool(proxies.get('https'))
    return {'any_configured': any(bool(value) for key, value in proxies.items() if key != 'no'),
            'https_configured': https_configured,
            'candidate_bypassed_by_configuration': bool(proxy_bypass(host)) if https_configured else False}


def diagnostic_https(host, timeout):
    # Match PublicClient's default proxy route and verified TLS. A successful
    # diagnostic response cannot mark the service ready or pass the business E2E.
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request('https://' + host + '/health?probe=' + secrets.token_hex(8), headers={
        'Cache-Control': 'no-store', 'User-Agent': 'Shengjian-Cloudflare-Diagnostics'})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(4097)
            result = {'status': 'response', 'http_status': response.status,
                      'tls_verification': True, 'redirects_followed': False}
            if len(body) <= 4096:
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError):
                    payload = None
                result['json_object'] = isinstance(payload, dict)
                if isinstance(payload, dict):
                    result['health_ok'] = payload.get('ok') is True
                    result['service_name_matches'] = payload.get('name') == 'Shengjian'
                    result['probe_identity_present'] = bool(payload.get('probe_id'))
            else:
                result['response_exceeds_diagnostic_limit'] = True
            return result
    except HTTPError as error:
        error.close()
        return {'status': 'response', 'http_status': error.code,
                'tls_verification': True, 'redirects_followed': False}


def summarize_dig(output, returncode):
    """Keep DNS status and TTLs, never names, addresses, servers, or raw output."""
    result = {'status': 'completed', 'available': True, 'returncode': returncode,
              'rcode': 'unavailable', 'answer_types': {}, 'authority_types': {}}
    header = re.search(r'\bstatus:\s*([A-Z0-9]+)', output)
    if header:
        known = {'NOERROR', 'FORMERR', 'SERVFAIL', 'NXDOMAIN', 'NOTIMP', 'REFUSED',
                 'YXDOMAIN', 'YXRRSET', 'NXRRSET', 'NOTAUTH', 'NOTZONE', 'BADVERS'}
        result['rcode'] = header.group(1) if header.group(1) in known else 'other'
    section = None
    negative_ttls = []
    answer_ttls = []
    soa = []
    for line in output.splitlines():
        if line.startswith(';; ANSWER SECTION:'):
            section = 'answer_types'
        elif line.startswith(';; AUTHORITY SECTION:'):
            section = 'authority_types'
        elif line.startswith(';;'):
            if 'SECTION:' in line:
                section = None
        elif line.strip() and section:
            fields = line.split()
            if len(fields) < 5 or not fields[1].isdigit() or fields[2] != 'IN':
                continue
            record_type = fields[3]
            if record_type not in {'A', 'AAAA', 'CNAME', 'SOA', 'NS', 'TXT', 'HTTPS', 'SVCB'}:
                record_type = 'other'
            result[section][record_type] = result[section].get(record_type, 0) + 1
            if section == 'answer_types':
                answer_ttls.append(int(fields[1]))
            if record_type == 'SOA' and len(fields) >= 11 and fields[-1].isdigit():
                ttl, minimum = int(fields[1]), int(fields[-1])
                negative_ttls.append(min(ttl, minimum))
                soa.append({'record_ttl_s': ttl, 'minimum_ttl_s': minimum,
                            'effective_negative_ttl_s': min(ttl, minimum)})
    result['answer_ttl_s'] = sorted(set(answer_ttls))[:64]
    if soa:
        result['soa'] = soa[:8]
    if negative_ttls:
        result['negative_ttl_s'] = min(negative_ttls)
    return result


def diagnostic_dig(host, record_type, timeout):
    executable = shutil.which('dig')
    if not executable:
        return {'status': 'unavailable', 'available': False}
    if timeout < 1:
        return {'status': 'skipped', 'available': True, 'reason': 'worker_deadline_near'}
    # No @server: use the runner's configured resolver. dig and the macOS system
    # resolver are distinct paths, so record both instead of substituting one.
    command = [executable, '+time=2', '+tries=1', '+noall', '+comments', '+answer',
               '+authority', host, record_type]
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding='utf-8', errors='replace', timeout=timeout,
                                   check=False)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'available': True}
    return summarize_dig(completed.stdout, completed.returncode)


def diagnostic_doh(host, timeout):
    # Read-only public-record comparison, never a resolver for application
    # traffic. Returned addresses are discarded and cannot influence readiness.
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request('https://cloudflare-dns.com/dns-query?' + urlencode({'name': host, 'type': 'A'}),
                      headers={'Accept': 'application/dns-json', 'Cache-Control': 'no-store',
                               'User-Agent': 'Shengjian-Cloudflare-Diagnostics'})
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(16385)
            result = {'status': 'response', 'http_status': response.status,
                      'tls_verification': True, 'redirects_followed': False}
            if len(body) > 16384:
                return {**result, 'response_exceeds_diagnostic_limit': True}
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return {**result, 'json_object': False}
            rcode = payload.get('Status')
            result['rcode_number'] = rcode if isinstance(rcode, int) and 0 <= rcode <= 65535 else None
            result['rcode'] = {0: 'NOERROR', 1: 'FORMERR', 2: 'SERVFAIL', 3: 'NXDOMAIN',
                               4: 'NOTIMP', 5: 'REFUSED'}.get(result['rcode_number'], 'other')
            answers = payload.get('Answer', [])
            answers = [item for item in answers if isinstance(item, dict)] if isinstance(answers, list) else []
            result['answer_count'] = len(answers)
            result['answer_types'] = {}
            ttls = []
            for item in answers:
                kind = {1: 'A', 5: 'CNAME', 28: 'AAAA'}.get(item.get('type'), 'other')
                result['answer_types'][kind] = result['answer_types'].get(kind, 0) + 1
                ttl = item.get('TTL')
                if isinstance(ttl, int) and 0 <= ttl <= 2**32 - 1:
                    ttls.append(ttl)
            result['answer_ttl_s'] = sorted(set(ttls))[:64]
            authority = payload.get('Authority', [])
            soa = []
            for item in authority[:64] if isinstance(authority, list) else []:
                if not isinstance(item, dict) or item.get('type') != 6:
                    continue
                ttl, data = item.get('TTL'), item.get('data')
                fields = data.split() if isinstance(data, str) else []
                if isinstance(ttl, int) and 0 <= ttl <= 2**32 - 1 and fields and fields[-1].isdigit():
                    minimum = int(fields[-1])
                    soa.append({'record_ttl_s': ttl, 'minimum_ttl_s': minimum,
                                'effective_negative_ttl_s': min(ttl, minimum)})
            if soa:
                result['soa'] = soa[:8]
            return result
    except HTTPError as error:
        error.close()
        return {'status': 'response', 'http_status': error.code,
                'tls_verification': True, 'redirects_followed': False}


def diagnostic_worker(host, timeout):
    """Run in a disposable process: getaddrinfo has no reliable socket timeout."""
    require(candidate_hostname(host), 'invalid diagnostic hostname')
    timeout = max(.05, min(float(timeout), 11))
    started = time.monotonic()
    deadline = started + timeout
    results = queue.Queue()
    jobs = {
        'getaddrinfo_unspecified': lambda: diagnostic_resolve(host, socket.AF_UNSPEC),
        'getaddrinfo_ipv4': lambda: diagnostic_resolve(host, socket.AF_INET),
        'getaddrinfo_ipv6': lambda: diagnostic_resolve(host, socket.AF_INET6),
        'default_proxy': lambda: diagnostic_proxy_presence(host),
        'default_https': lambda: diagnostic_https(host, min(6, timeout)),
        # Leave time for subprocess.run to kill and reap dig before this
        # disposable Python process exits, including a nearly exhausted budget.
        'dig_a': lambda: diagnostic_dig(host, 'A', min(4, deadline - time.monotonic() - .5)),
        'dig_aaaa': lambda: diagnostic_dig(host, 'AAAA', min(4, deadline - time.monotonic() - .5)),
        'cloudflare_doh_a': lambda: diagnostic_doh(host, min(4, timeout)),
    }

    def collect(name, check):
        before = time.monotonic()
        try:
            result = check()
        except Exception as error:
            result = {'status': 'error', **diagnostic_error(error)}
        result['elapsed_s'] = round(time.monotonic() - before, 3)
        results.put((name, result))

    for name, check in jobs.items():
        threading.Thread(target=collect, args=(name, check), daemon=True).start()
    checks = {}
    while len(checks) < len(jobs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            name, result = results.get(timeout=remaining)
        except queue.Empty:
            break
        checks[name] = result
    for name in jobs.keys() - checks.keys():
        checks[name] = {'status': 'timeout'}
    return checks


def stop_diagnostic_process(process, deadline):
    if process.poll() is None:
        if os.name == 'nt':
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=max(.1, min(1, deadline - time.monotonic())), check=False)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        process.communicate(timeout=max(.1, min(.5, deadline - time.monotonic())))
    except subprocess.TimeoutExpired:
        process.kill()


def collect_diagnostics(host, budget):
    remaining = budget.deadline - time.monotonic()
    if remaining < 3:
        return {'status': 'skipped', 'reason': 'overall_deadline_near'}
    allowance = min(DIAGNOSTIC_LIMIT_SECONDS, remaining)
    deadline = time.monotonic() + allowance
    # Reserve two seconds inside the existing E2E budget for killing/reaping a
    # hung resolver process. The hostname goes through stdin, never argv/logs.
    execution_timeout = allowance - 2
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--diagnostics-worker'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', errors='replace', start_new_session=os.name != 'nt',
        creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0)
    try:
        payload = json.dumps({'host': host, 'timeout': max(.05, execution_timeout - 1)})
        stdout, _ = process.communicate(payload, timeout=max(.1, deadline - time.monotonic() - 2))
        if process.returncode != 0:
            return {'status': 'worker_error', 'returncode': process.returncode}
        checks = json.loads(stdout)
        require(isinstance(checks, dict), 'diagnostic worker returned invalid JSON')
        return {'status': 'completed', 'checks': checks}
    except subprocess.TimeoutExpired:
        return {'status': 'worker_timeout'}
    except (ValueError, CheckFailed):
        return {'status': 'worker_output_invalid'}
    finally:
        stop_diagnostic_process(process, deadline)


def diagnostic_message(value, evidence):
    value = evidence.redact(str(value))[:1000]
    value = re.sub(r'(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"\']+', '[address redacted]', value)
    value = re.sub(r'(?i)(?<![\w])(?:[a-z0-9_-]+\.)+[a-z0-9_-]+', '[host redacted]', value)
    return re.sub(r'(?i)(?<![\w])(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]*(?:%[\w]+)?',
                  '[address redacted]', value)


class PublicDiagnostics:
    def __init__(self, evidence, budget):
        self.evidence, self.budget = evidence, budget
        self.last_started = None
        self.count = 0

    def observe(self, state):
        host = candidate_hostname(state.get('candidate_host'))
        if host and host not in self.evidence.secrets:
            self.evidence.secrets.append(host)
        now = time.monotonic()
        if (not host or not state.get('managed') or state.get('stage') != 'verifying'
                or not state.get('last_error') or self.count >= 2
                or (self.last_started is not None and now - self.last_started < DIAGNOSTIC_INTERVAL_SECONDS)):
            return
        self.last_started, self.count = now, self.count + 1
        entry = {
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'candidate_host_sha256': hashlib.sha256(host.encode('ascii')).hexdigest(),
            'frozen_service': {name: diagnostic_message(state.get(name, ''), self.evidence)
                               for name in ('phase', 'stage', 'error_code', 'last_error')},
            'managed_at_capture': bool(state.get('managed')),
            'ready_at_capture': bool(state.get('ready')),
            'url_assignments': state.get('url_assignments'),
            'tls_verification': True,
            'diagnostics_do_not_set_ready': True,
        }
        print(f'[Cloudflare E2E] capturing bounded DNS/HTTPS diagnostics ({self.count}/2)', flush=True)
        try:
            entry.update(collect_diagnostics(host, self.budget))
        except Exception as error:
            entry.update(status='collection_error', error_type=type(error).__name__)
        entry['elapsed_s'] = round(time.monotonic() - now, 3)
        self.evidence.result['diagnostics'].append(self.evidence.redact(entry))


class PublicClient:
    def __init__(self, base, budget):
        parts = urlsplit(base)
        require(parts.scheme == 'https' and not parts.username and not parts.password
                and parts.port in (None, 443)
                and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', parts.hostname or '')
                and parts.path in ('', '/') and not parts.query and not parts.fragment,
                'service did not return a valid public Quick Tunnel HTTPS origin')
        self.base, self.budget = base.rstrip('/'), budget
        # The default ProxyHandler respects the runner's network configuration.
        # Certificate and hostname verification remain enabled.
        self.opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))

    def request(self, path, params=None, body=None, content_type=None):
        url = self.base + path
        if params:
            url += '?' + urlencode(params)
        headers = {'Cache-Control': 'no-store', 'User-Agent': 'Shengjian-Cloudflare-E2E'}
        if content_type:
            headers['Content-Type'] = content_type
        request = Request(url, data=body, headers=headers, method='POST' if body is not None else 'GET')
        try:
            with self.opener.open(request, timeout=self.budget.timeout(12)) as response:
                return response_bytes(response)
        except HTTPError as response:
            try:
                return response_bytes(response)
            finally:
                response.close()


class Service:
    def __init__(self, args, folder, evidence, budget):
        self.args, self.folder, self.evidence, self.budget = args, Path(folder), evidence, budget
        self.folder.mkdir(parents=True, exist_ok=True)
        self.key = secrets.token_urlsafe(32)
        evidence.secrets.append(self.key)
        key_file = self.folder / 'access_key.txt'
        key_file.write_text(self.key, encoding='utf-8')
        key_file.chmod(0o600)
        self.stdout_log = self.folder.parent / 'backend-stdout.log'
        self.stdout_stream = None
        self.process = None
        self.port = None
        self.tunnel_requested = False
        self.kind = args.service_kind
        if self.kind == 'auto':
            self.kind = 'mac' if args.service and sys.platform == 'darwin' else 'gui'
        require(args.service is not None or self.kind == 'gui', 'source service uses --service-kind gui')

    def start(self):
        command = [str(self.args.service)] if self.args.service else [sys.executable, str(ROOT / 'src/gui_app.py')]
        if self.kind == 'gui':
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                self.port = listener.getsockname()[1]
            command += ['--server-only', '--port', str(self.port)]
        env = {**os.environ, 'DOUBAO_BRIDGE_DATA_DIR': str(self.folder), 'QT_QPA_PLATFORM': 'offscreen'}
        for name in ('DOUBAO_BRIDGE_PUBLIC_URL', 'DOUBAO_BRIDGE_PUBLIC_PROBE'):
            env.pop(name, None)
        isolated_ca = bool(self.args.service and sys.platform in ('darwin', 'win32'))
        if isolated_ca:
            # Prove that the frozen Python probe does not borrow the builder's
            # OpenSSL CA paths. The outer HTTPS test client keeps normal trust.
            empty_ca = self.folder.parent / 'empty-default-ca'
            empty_ca.mkdir(exist_ok=True)
            missing_ca = self.folder.parent / 'missing-default-ca.pem'
            require(not missing_ca.exists() and not any(empty_ca.iterdir()),
                    'default CA isolation paths are not empty')
            env['SSL_CERT_FILE'] = str(missing_ca)
            env['SSL_CERT_DIR'] = str(empty_ca)
            # cloudflared 2026.10.2 uses Go 1.27, which otherwise also honors
            # SSL_CERT_* on Windows/macOS. Keep its native platform trust while
            # isolating Python; no TLS verification is disabled for either.
            debug = [item for item in env.get('GODEBUG', '').split(',')
                     if item and item.split('=', 1)[0].strip() != 'x509sslcertoverrideplatform']
            env['GODEBUG'] = ','.join([*debug, 'x509sslcertoverrideplatform=0'])
        self.evidence.result['service_tls'] = {
            'default_openssl_ca_paths_isolated': isolated_ca,
            'go_platform_trust_preserved': isolated_ca,
            'tls_verification': True,
        }
        if not self.args.service:
            # Source mode has no packaged resource; require the supplied binary.
            env['PATH'] = str(self.args.cloudflared.parent) + os.pathsep + env.get('PATH', '')
        self.stdout_stream = self.stdout_log.open('wb')
        self.process = subprocess.Popen(command, env=env, cwd=str(self.folder),
            stdout=self.stdout_stream, stderr=subprocess.STDOUT,
            start_new_session=os.name != 'nt',
            creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0)
        startup_deadline = min(time.monotonic() + 45, self.budget.deadline)
        last_error = 'service has not announced its port'
        while time.monotonic() < startup_deadline:
            require(self.process.poll() is None, 'service exited during startup')
            if self.port is None:
                for line in read_tail(self.stdout_log).splitlines():
                    try:
                        announcement = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(announcement, dict) and isinstance(announcement.get('port'), int):
                        require(0 < announcement['port'] < 65536, 'service announced an invalid port')
                        self.port = announcement['port']
                        break
            if self.port:
                try:
                    status, _, body = self.local('/health')
                    health = decode_json(status, body)
                    state = self.control('/desktop/state')
                    require(Path(state.get('data_dir', '')).resolve() == self.folder.resolve(),
                            'responding service is not using the isolated test data directory')
                    require(state.get('key') == self.key, 'responding service does not own the test pairing key')
                    expected = self.args.service or ROOT / 'src/gui_app.py'
                    require(Path(health.get('executable', '')).resolve() == expected.resolve(),
                            'responding service executable differs from the requested service')
                    require(bool(health.get('frozen')) == bool(self.args.service),
                            '--service must be an actual frozen application backend')
                    require(health.get('version') == expected_version(), 'service version differs from this checkout')
                    self.evidence.result['service'] = {
                        'kind': self.kind, 'frozen': bool(health.get('frozen')),
                        'version': health.get('version'),
                        'sha256': sha256_file(self.args.service) if self.args.service else '',
                    }
                    return
                except (OSError, http.client.HTTPException, ValueError) as error:
                    last_error = type(error).__name__
            self.budget.pause()
        raise CheckFailed(f'local service startup deadline exceeded ({last_error})')

    def local(self, path, data=None, timeout=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port,
            timeout=timeout if timeout is not None else self.budget.timeout(5))
        try:
            if data is None:
                connection.request('GET', path + '?' + urlencode({'key': self.key}))
            else:
                connection.request('POST', path, json.dumps({**data, 'key': self.key}).encode(),
                                   {'Content-Type': 'application/json'})
            return response_bytes(connection.getresponse())
        finally:
            connection.close()

    def control(self, path, data=None, timeout=None):
        status, _, body = self.local(path, data, timeout)
        return decode_json(status, body)

    def close(self):
        errors = []
        if self.process is not None:
            if self.tunnel_requested and self.process.poll() is None:
                try:
                    state = self.control('/desktop/connections', {'mode': 'cloudflare', 'enabled': False}, timeout=8)
                    require(not state.get('enabled') and not state.get('cloudflare', {}).get('managed'),
                            'service did not confirm its tunnel was stopped')
                except Exception as error:
                    errors.append('tunnel shutdown: ' + type(error).__name__)
            try:
                if os.name == 'nt':
                    if self.process.poll() is None:
                        subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
                else:
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                self.process.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired) as error:
                errors.append('service shutdown: ' + type(error).__name__)
                try:
                    if os.name == 'nt':
                        self.process.kill()
                    else:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    errors.append('forced service shutdown failed')
        if self.stdout_stream is not None:
            self.stdout_stream.close()
        return errors


def expected_version():
    version_file = ROOT / 'VERSION'
    if version_file.is_file():
        return version_file.read_text(encoding='utf-8').strip()
    match = re.search(r'^APP_VERSION\s*=\s*[\"\']([^\"\']+)',
                      (ROOT / 'src/gui_app.py').read_text(encoding='utf-8'), re.M)
    require(match is not None, 'cannot determine expected app version')
    return match.group(1)


def check_running_binary(state, args, expected_hash, evidence):
    path = state.get('binary_path')
    require(path, 'packaged TunnelManager does not report binary_path; rebuild the service')
    running = Path(path).resolve()
    require(running.is_file(), 'reported running cloudflared file is missing')
    actual_hash = sha256_file(running)
    require(actual_hash == expected_hash, 'running cloudflared differs from the package reference SHA256')
    if args.service:
        same_file = running == args.cloudflared
        # Windows PyInstaller --onefile extracts its bundled binary into _MEI*.
        extracted = os.name == 'nt' and any(part.startswith('_MEI') for part in running.parts[:-1])
        require(same_file or extracted, 'packaged service resolved an external cloudflared binary')
    evidence.result['cloudflared']['running_sha256'] = actual_hash
    evidence.result['cloudflared']['running_matches_package'] = True


def start_tunnel(service, args, evidence, reference_hash):
    service.tunnel_requested = True
    snapshot = service.control('/desktop/connections', {'mode': 'cloudflare', 'enabled': True})
    last_transition = None
    binary_checked = False
    transitions = evidence.result.setdefault('tunnel_transitions', [])
    diagnostics = PublicDiagnostics(evidence, service.budget)
    while True:
        require(service.process.poll() is None, 'service exited while creating the tunnel')
        require(snapshot.get('mode') == 'cloudflare' and snapshot.get('enabled'),
                'service did not select Cloudflare mode')
        state = snapshot.get('cloudflare')
        require(isinstance(state, dict), 'service is missing Cloudflare diagnostics; rebuild the package')
        diagnostics.observe(state)
        transition = {name: state.get(name, '') for name in ('phase', 'stage', 'error_code', 'error')}
        if transition != last_transition:
            transitions.append(evidence.redact(transition))
            print('[Cloudflare E2E] tunnel ' + evidence.redact(json.dumps(transition, ensure_ascii=False)), flush=True)
            last_transition = transition
        if state.get('managed') and not binary_checked:
            check_running_binary(state, args, reference_hash, evidence)
            binary_checked = True
        require(state.get('phase') != 'error', f"tunnel failed: {state.get('error') or state.get('error_code') or 'unknown error'}")
        if snapshot.get('ready') and state.get('ready'):
            require(binary_checked, 'ready tunnel has no verified owned cloudflared process')
            return state['public_url']
        service.budget.pause(.4)
        snapshot = service.control('/desktop/connections')


def wait_for_public_origin(client, evidence):
    deadline = min(time.monotonic() + 30, client.budget.deadline)
    last_error = 'public request not attempted'
    while time.monotonic() < deadline:
        try:
            status, _, _ = client.request('/')
            if status == 401:
                return
            require(status != 200, 'public phone page accepted a request without a pairing key')
            last_error = f'HTTP {status}'
        except (OSError, URLError, http.client.HTTPException) as error:
            last_error = evidence.redact(f'{type(error).__name__}: {error}')
        client.budget.pause(.7)
    raise CheckFailed(f'public HTTPS could not reach the authenticated origin ({last_error})')


def multipart_upload(key, filename, payload, extra_keys=()):
    boundary = 'shengjian-e2e-' + secrets.token_hex(16)
    fields = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="key"\r\n\r\n{value}\r\n'
                     for value in (key, *extra_keys))
    body = (fields + f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            + 'Content-Type: application/octet-stream\r\n\r\n').encode()
    return body + payload + f'\r\n--{boundary}--\r\n'.encode(), 'multipart/form-data; boundary=' + boundary


def exercise_rejected_uploads(client, service, evidence, wrong_key):
    evidence.begin('public upload authentication before side effects')
    status, _, body = service.local('/health')
    before = decode_json(status, body).get('state', {}).get('paste_count')
    require(before == 0, 'isolated service already has a paste side effect')
    outcomes = []
    for endpoint in ('/files/share', '/files/clipboard', '/files/paste'):
        # Probe query/body disagreement and duplicate valid keys on the harmless
        # sharing endpoint. Keep every clipboard/paste body key invalid even if
        # an older backend incorrectly ignores the public query-key boundary.
        query_body_key = service.key if endpoint == '/files/share' else wrong_key
        cases = (
            ('missing query key', None, query_body_key, ()),
            ('incorrect query key', {'key': wrong_key}, query_body_key, ()),
            ('incorrect multipart key', {'key': service.key}, wrong_key, ()),
            ('duplicate multipart keys', {'key': service.key}, query_body_key, (query_body_key,)),
        )
        for label, params, body_key, extra_keys in cases:
            filename = 'rejected-cloudflare-e2e-' + secrets.token_hex(12) + '.bin'
            # Small bodies can be sent before a pre-parse 401 closes the socket.
            multipart, content_type = multipart_upload(body_key, filename, secrets.token_bytes(64), extra_keys)
            status, _, _ = client.request(endpoint, params, multipart, content_type)
            require(status == 401, f'{endpoint}: {label} should return 401; got {status}')
            require(not any(service.folder.rglob(filename)),
                    f'{endpoint}: {label} returned 401 but wrote a business file')
            health_status, _, health_body = service.local('/health')
            after = decode_json(health_status, health_body).get('state', {}).get('paste_count')
            require(after == before, f'{endpoint}: {label} changed paste_count')
            outcomes.append({'endpoint': endpoint, 'case': label, 'status': status,
                             'business_file_created': False})
    evidence.passed(cases=outcomes, paste_count=before)


def exercise_public_app(client, service, evidence):
    evidence.begin('public phone authentication')
    wrong_key = secrets.token_urlsafe(24)
    evidence.secrets.append(wrong_key)
    for params in (None, {'key': wrong_key}):
        status, _, body = client.request('/', params)
        require(status == 401, f'phone page should reject absent/incorrect keys with 401; got {status}')
        require(service.key.encode() not in body, 'unauthenticated response exposed the pairing key')
    status, headers, body = client.request('/', {'key': service.key})
    require(status == 200, f'authenticated phone page returned HTTP {status}')
    require('text/html' in next((v for k, v in headers.items() if k.lower() == 'content-type'), ''),
            'authenticated phone response is not HTML')
    require(service.key.encode() in body and b'/files/share' in body,
            'phone response is not the current real application page')
    status, _, _ = client.request('/files/shared')
    require(status == 401, 'shared file listing accepted an unauthenticated request')
    evidence.passed(absent_key_status=401, incorrect_key_status=401, valid_key_status=200)

    exercise_rejected_uploads(client, service, evidence, wrong_key)

    evidence.begin('public file upload to isolated origin')
    filename = 'cloudflare-e2e-' + secrets.token_hex(12) + '.bin'
    payload = secrets.token_bytes(FILE_BYTES)
    expected_hash = hashlib.sha256(payload).hexdigest()
    multipart, content_type = multipart_upload(service.key, filename, payload)
    status, _, body = client.request('/files/share', {'key': service.key}, multipart, content_type)
    result = decode_json(status, body)
    require(result.get('result', {}).get('files') == 1, 'origin did not confirm one shared file')
    stored = service.folder / 'mobile_share' / filename
    require(stored.is_file() and stored.stat().st_size == len(payload), 'public upload did not reach the isolated origin')
    require(sha256_file(stored) == expected_hash, 'origin file SHA256 differs from the uploaded bytes')
    evidence.passed(bytes=len(payload), sha256=expected_hash, origin_file_verified=True)

    evidence.begin('public file listing and download SHA256')
    status, _, body = client.request('/files/shared', {'key': service.key})
    listing = decode_json(status, body)
    require(any(item.get('name') == filename and item.get('bytes') == len(payload)
                for item in listing.get('files', [])), 'uploaded file absent from the public file listing')
    status, _, _ = client.request('/files/download', {'file': filename})
    require(status == 401, 'download accepted an unauthenticated request')
    status, _, downloaded = client.request('/files/download', {'key': service.key, 'file': filename})
    require(status == 200, f'public file download returned HTTP {status}')
    require(len(downloaded) == len(payload) and hashlib.sha256(downloaded).hexdigest() == expected_hash,
            'publicly downloaded bytes/SHA256 differ from the random upload')
    evidence.passed(bytes=len(downloaded), sha256=expected_hash, unauthenticated_status=401)

    evidence.begin('public management boundary and final origin state')
    status, _, _ = client.request('/desktop/state', {'key': service.key})
    require(status == 403, f'public management endpoint should reject a valid pairing key with 403; got {status}')
    status, _, body = service.local('/health')
    health = decode_json(status, body)
    require(health.get('state', {}).get('paste_count') == 0, 'test unexpectedly performed desktop paste')
    require(service.control('/desktop/connections').get('ready'), 'tunnel disconnected before completion')
    evidence.passed(management_status=403, paste_count=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloudflared', type=Path, required=True, help='exact packaged cloudflared, or copy extracted from the final package')
    parser.add_argument('--service', type=Path, help='frozen backend from the final installed/mounted package; omit only for source testing')
    parser.add_argument('--service-kind', choices=('auto', 'gui', 'mac'), default='auto')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cloudflare-e2e-evidence')
    parser.add_argument('--timeout', type=float, default=180, help='total verification budget in seconds, excluding bounded cleanup')
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error('--timeout must be between 1 and 600 seconds')
    args.cloudflared = args.cloudflared.expanduser().resolve()
    args.service = args.service.expanduser().resolve() if args.service else None
    evidence, budget = Evidence(args.output), Budget(args.timeout)
    evidence.result['release_package_test'] = bool(args.service)
    service = None
    with tempfile.TemporaryDirectory(prefix='shengjian-cloudflare-e2e-') as temporary:
        data_dir = Path(temporary) / 'data'
        stdout_log = Path(temporary) / 'backend-stdout.log'
        try:
            evidence.begin('package preflight')
            require(args.cloudflared.is_file() and os.access(args.cloudflared, os.X_OK), 'packaged cloudflared is missing or not executable')
            require(args.service is None or args.service.is_file(), 'packaged service is missing')
            version = subprocess.run([str(args.cloudflared), '--version'], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                timeout=budget.timeout(10), check=False)
            require(version.returncode == 0 and 'cloudflared' in version.stdout.lower(), 'packaged cloudflared --version failed')
            reference_hash = sha256_file(args.cloudflared)
            evidence.result['cloudflared'] = {'version': version.stdout.strip()[:300], 'reference_sha256': reference_hash}
            evidence.passed()

            evidence.begin('isolated real service startup')
            service = Service(args, data_dir, evidence, budget)
            service.start()
            evidence.passed()

            evidence.begin('service-owned Cloudflare tunnel and binary verification')
            public_url = start_tunnel(service, args, evidence, reference_hash)
            evidence.passed()

            evidence.begin('real public HTTPS reaches origin')
            client = PublicClient(public_url, budget)
            wait_for_public_origin(client, evidence)
            evidence.passed(unauthenticated_origin_status=401)
            exercise_public_app(client, service, evidence)
            evidence.result['ok'] = True
        except (Exception, KeyboardInterrupt) as error:
            evidence.failed(error)
        finally:
            if service is not None:
                errors = service.close()
                evidence.result['cleanup'] = {'ok': not errors, 'errors': errors}
                if errors:
                    evidence.begin('cleanup')
                    evidence.failed(CheckFailed('; '.join(errors)))
            evidence.save(data_dir, stdout_log)
    if evidence.result['ok']:
        print('[Cloudflare E2E] PASS: real public HTTPS authentication, file upload/download SHA256, '
              'origin storage and public management isolation verified; credentials withheld.', flush=True)
        return 0
    return 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--diagnostics-worker']:
        request = json.loads(sys.stdin.read(4096))
        print(json.dumps(diagnostic_worker(request.get('host'), request.get('timeout', 10))), flush=True)
    else:
        raise SystemExit(main())
