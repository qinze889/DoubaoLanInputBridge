"""Desktop account boundary. Never return the stored bearer to the UI or QR."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import platform
import threading
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = 'https://test.xjiaoai.com/shengjian/api/v2'
_lock = threading.RLock()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CredentialVault:
    def __init__(self, directory):
        self.path = Path(directory)/'cloud-session.bin'
        self.account = hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest().encode()

    def mac(self, value=None, delete=False):
        lib = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        find = lib.SecKeychainFindGenericPassword
        find.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.POINTER(C.c_uint32), C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
        service = b'com.shengjian.cloud-account'
        size, data, item = C.c_uint32(), C.c_void_p(), C.c_void_p()
        status = find(None, len(service), service, len(self.account), self.account, C.byref(size), C.byref(data), C.byref(item))
        if status not in (0, -25300):
            raise RuntimeError('无法访问系统钥匙串，请解锁后重试。')
        try:
            if value is None and not delete:
                return C.string_at(data, size.value).decode() if status == 0 else ''
            if status == 0:
                if delete:
                    lib.SecKeychainItemDelete.argtypes = [C.c_void_p]
                    status = lib.SecKeychainItemDelete(item)
                else:
                    lib.SecKeychainItemModifyAttributesAndData.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_char_p]
                    raw = value.encode()
                    status = lib.SecKeychainItemModifyAttributesAndData(item, None, len(raw), raw)
            elif not delete:
                lib.SecKeychainAddGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.c_void_p]
                raw = value.encode()
                status = lib.SecKeychainAddGenericPassword(None, len(service), service, len(self.account), self.account, len(raw), raw, None)
            else:
                status = 0
            if status:
                raise RuntimeError('无法保存系统登录凭据。')
            return ''
        finally:
            if data.value:
                lib.SecKeychainItemFreeContent.argtypes = [C.c_void_p, C.c_void_p]
                lib.SecKeychainItemFreeContent(None, data)
            if item.value:
                cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
                cf.CFRelease.argtypes = [C.c_void_p]
                cf.CFRelease(item)

    @staticmethod
    def dpapi(raw, decrypt=False):
        class Blob(C.Structure):
            _fields_ = [('size', C.c_uint32), ('data', C.c_void_p)]
        buffer = C.create_string_buffer(raw)
        source, output = Blob(len(raw), C.cast(buffer, C.c_void_p)), Blob()
        crypt = C.windll.crypt32
        fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        fn.argtypes = [C.POINTER(Blob), C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint32, C.POINTER(Blob)]
        if not fn(C.byref(source), None, None, None, None, 1, C.byref(output)):
            raise RuntimeError('无法访问 Windows 登录凭据。')
        try:
            return C.string_at(output.data, output.size)
        finally:
            C.windll.kernel32.LocalFree.argtypes = [C.c_void_p]
            C.windll.kernel32.LocalFree(output.data)

    def read(self):
        if platform.system() == 'Darwin':
            return self.mac()
        if platform.system() == 'Windows':
            return self.dpapi(self.path.read_bytes(), decrypt=True).decode() if self.path.exists() else ''
        raise RuntimeError('此平台尚未配置安全凭据存储。')

    def write(self, value):
        if platform.system() == 'Darwin':
            self.mac(value)
        elif platform.system() == 'Windows':
            raw = self.dpapi(value.encode())
            temp = self.path.with_suffix('.tmp')
            with open(temp, 'wb') as output:
                os.chmod(temp, 0o600)
                output.write(raw)
            os.replace(temp, self.path)
        else:
            raise RuntimeError('此平台尚未配置安全凭据存储。')

    def clear(self):
        if platform.system() == 'Darwin':
            self.mac(delete=True)
        else:
            self.path.unlink(missing_ok=True)


class CloudAccount:
    def __init__(self, directory, vault=None):
        self.vault = vault or CredentialVault(directory)

    def request(self, path, body=None, token=''):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer '+token
        request = Request(BASE+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 401:
                raise PermissionError('登录已失效，请重新登录。') from None
            raise RuntimeError({403: '邀请码无效或无权限。', 409: '账号已存在或设备数量已满。', 422: '请检查用户名和密码（至少 12 位）。', 429: '操作频繁，请稍后重试。'}.get(exc.code, '云端服务暂时不可用。')) from None
        except OSError:
            raise RuntimeError('无法连接声笺云端，请检查网络。') from None

    def perform(self, action, body=None):
        with _lock:
            if action in ('login', 'register'):
                values = {k: str((body or {}).get(k, '')) for k in ('username', 'password')}
                if action == 'register':
                    values['invite'] = str((body or {}).get('invite', ''))
                data = self.request('/auth/'+action, values)
                try:
                    self.vault.write(data['token'])
                except Exception:
                    self.request('/auth/logout', {}, data['token'])
                    raise
                return {'ok': True, 'authenticated': True}
            token = self.vault.read()
            if action == 'logout':
                # Keep the local credential if the server cannot revoke it.
                if token:
                    try:
                        self.request('/auth/logout', {}, token)
                    except PermissionError:
                        pass
                self.vault.clear()
                return {'ok': True, 'authenticated': False}
            if not token:
                return {'ok': True, 'authenticated': False}
            try:
                if action == 'qr':
                    data = self.request('/auth/qr', {}, token)
                    return {'ok': True, 'authenticated': True, 'url': BASE+'/console#login='+data['ticket'], 'expires_at': data['expires_at']}
                if action == 'status':
                    data = self.request('/me', token=token)
                    return {'ok': True, 'authenticated': True, 'user_id': data['user_id']}
                raise ValueError('不支持的账号操作。')
            except PermissionError:
                self.vault.clear()
                return {'ok': True, 'authenticated': False}
