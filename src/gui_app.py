import argparse
import base64
import ctypes
import hashlib
import html
import ipaddress
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import warnings
import webbrowser
from http.client import HTTPConnection
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk, UnidentifiedImageError
except Exception:
    Image = None
    ImageTk = None
    UnidentifiedImageError = OSError


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
QRCODE_TOOL_DIR = Path(__file__).resolve().parents[1] / "tools" / "qrcode"
if QRCODE_TOOL_DIR.exists() and str(QRCODE_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(QRCODE_TOOL_DIR))
LOCAL_UPDATE_SOURCE_DIR = SOURCE_ROOT / "local_update_source"

import qrcode
from qrcode.constants import ERROR_CORRECT_M


APP_NAME = "声笺"
APP_ID = "DoubaoLanInputBridge"
APP_VERSION = "1.0.0"
APP_ICON_RELATIVE_PATH = "assets/app.ico"
DEFAULT_PORT = 8765
PORT_AUTO_INCREMENT_LIMIT = 20
FIXED_LAN_UPDATE_HOST = "192.168.1.63"
FIXED_LAN_UPDATE_PORT = 8765
FIREWALL_RULE_PREFIX = f"{APP_ID} LAN TCP"
MAX_TEXT_LENGTH = 20000
UPDATE_MANIFEST_ENV = "DOUBAO_BRIDGE_UPDATE_URL"
MOBILE_HOST_ENV = "DOUBAO_BRIDGE_HOST"
PUBLIC_URL_ENV = "DOUBAO_BRIDGE_PUBLIC_URL"
PUBLIC_PROBE_ENV = "DOUBAO_BRIDGE_PUBLIC_PROBE"
PUBLIC_ENTRY_PROBE_TTL = 30.0
GITHUB_REPO_DEFAULT = "qinze889/DoubaoLanInputBridge"
GITHUB_RELEASES_LATEST_API = "https://api.github.com/repos/{repo}/releases/latest"
GITHUB_RELEASES_API = "https://api.github.com/repos/{repo}/releases"
UPDATE_CHECK_CACHE_TTL = 1800.0
TUNNEL_DEFAULT_METRICS_PORT = 20244
TUNNEL_READY_TIMEOUT = 25.0
TUNNEL_LOG_TAIL_BYTES = 4000
CLOUDFLARED_CANDIDATE_PATHS = (
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
)
UPDATE_ASSET_SUFFIXES = ("-setup.exe", ".msi")
MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M3"
MINIMAX_TIMEOUT_SECONDS = 45.0
IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    CF_UNICODETEXT = 13
    CF_HDROP = 15
    GMEM_MOVEABLE = 0x0002
    VK_CONTROL = 0x11
    VK_V = 0x56
    VK_RETURN = 0x0D
    KEYEVENTF_KEYUP = 0x0002
    ERROR_CLASS_ALREADY_EXISTS = 1410
    WM_USER = 0x0400
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    IDI_APPLICATION = 32512
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040
    TRAY_ICON_ID = 1
    TRAY_CALLBACK_MESSAGE = WM_USER + 31
    LRESULT = ctypes.c_ssize_t
    HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
    HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)

    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uTimeoutOrVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
        ]

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.keybd_event.argtypes = [
        wintypes.BYTE,
        wintypes.BYTE,
        wintypes.DWORD,
        ctypes.c_size_t,
    ]
    user32.keybd_event.restype = None
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = HICON
    user32.LoadIconW.restype = HICON
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def app_data_dir() -> Path:
    if IS_WINDOWS:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / APP_ID
    return Path.home() / f".{APP_ID}"


DATA_DIR = app_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
KEY_FILE = DATA_DIR / "access_key.txt"
LOG_FILE = DATA_DIR / "service.log"
UPDATE_URL_FILE = DATA_DIR / "update_url.txt"
MOBILE_HOST_FILE = DATA_DIR / "mobile_host.txt"
PUBLIC_URL_FILE = DATA_DIR / "public_url.txt"
PUBLIC_PROBE_FILE = DATA_DIR / "public_probe.txt"
TUNNEL_CONFIG_FILE = DATA_DIR / "tunnel.json"
UPDATE_CHECK_CACHE_FILE = DATA_DIR / "update_check_cache.json"
FIRST_RUN_FILE = DATA_DIR / "first_run_guide_seen.txt"
PROMPT_LIBRARY_FILE = DATA_DIR / "prompt_library.json"
MINIMAX_API_KEY_FILE = DATA_DIR / "minimax_api_key.txt"
UPLOAD_DIR = DATA_DIR / "uploads"
MOBILE_SHARE_DIR = DATA_DIR / "mobile_share"
MOBILE_SHARE_FEED_FILE = DATA_DIR / "mobile_share_feed.json"
HISTORY_FILE = DATA_DIR / "clipboard_history.json"
HISTORY_ARCHIVE_DIR = DATA_DIR / "history_archive"
TEXT_HISTORY_JSONL = HISTORY_ARCHIVE_DIR / "texts.jsonl"
FILE_HISTORY_JSONL = HISTORY_ARCHIVE_DIR / "files.jsonl"
HISTORY_IMAGE_DIR = HISTORY_ARCHIVE_DIR / "images"
HISTORY_VIDEO_DIR = HISTORY_ARCHIVE_DIR / "videos"
HISTORY_DOCUMENT_DIR = HISTORY_ARCHIVE_DIR / "files"
UPDATE_DOWNLOAD_DIR = DATA_DIR / "updates"
UPDATER_SCRIPT_FILE = DATA_DIR / "updater.ps1"
UPDATE_LOG_FILE = DATA_DIR / "update.log"
MAX_UPLOAD_FILES = 8
MAX_MOBILE_SHARE_ITEMS = 100
MAX_HISTORY_ITEMS = 100
HISTORY_WINDOW_LIMIT = 30
HISTORY_RETENTION_DAYS = 7
HISTORY_ARCHIVE_LOCK = threading.Lock()
MOBILE_SHARE_FEED_LOCK = threading.Lock()
_PAPER_BACKGROUND_DATA_URL = ""
STATUS_THEMES = {
    "stopped": {
        "bg": "#f8fafc",
        "fg": "#0f172a",
        "muted": "#475569",
        "accent": "#64748b",
        "border": "#cbd5e1",
    },
    "starting": {
        "bg": "#eff6ff",
        "fg": "#1e3a8a",
        "muted": "#1d4ed8",
        "accent": "#2563eb",
        "border": "#93c5fd",
    },
    "running": {
        "bg": "#ecfdf5",
        "fg": "#064e3b",
        "muted": "#047857",
        "accent": "#059669",
        "border": "#6ee7b7",
    },
    "warning": {
        "bg": "#fffbeb",
        "fg": "#78350f",
        "muted": "#92400e",
        "accent": "#d97706",
        "border": "#fbbf24",
    },
    "error": {
        "bg": "#fef2f2",
        "fg": "#7f1d1d",
        "muted": "#991b1b",
        "accent": "#dc2626",
        "border": "#fca5a5",
    },
}
UI_COLORS = {
    "page": "#f4f7f8",
    "surface": "#ffffff",
    "surface_soft": "#f8fbfb",
    "nav": "#eef5f5",
    "nav_active": "#d8f3f0",
    "text": "#132329",
    "muted": "#60717a",
    "line": "#d9e5e5",
    "primary": "#0f9f96",
    "primary_dark": "#08766f",
    "danger": "#b42318",
    "warning": "#d97706",
}


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative_path


def app_icon_path() -> Path:
    return resource_path(APP_ICON_RELATIVE_PATH)


def paper_background_data_url() -> str:
    global _PAPER_BACKGROUND_DATA_URL
    if _PAPER_BACKGROUND_DATA_URL:
        return _PAPER_BACKGROUND_DATA_URL
    image_path = resource_path("assets/paper000.jpg")
    if not image_path.exists():
        return ""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    _PAPER_BACKGROUND_DATA_URL = f"data:image/jpeg;base64,{encoded}"
    return _PAPER_BACKGROUND_DATA_URL


def now_ms() -> int:
    return int(time.time() * 1000)


def running_executable_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    return str(Path(__file__).resolve())


def local_update_source_candidates() -> list[Path]:
    candidates = [LOCAL_UPDATE_SOURCE_DIR]
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidates.extend(
            [
                exe_path.parent / "local_update_source",
                exe_path.parent.parent / "local_update_source",
            ]
        )
    candidates.extend(
        [DATA_DIR / "local_update_source", Path.cwd() / "local_update_source", PROJECT_ROOT / "local_update_source"]
    )
    unique = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def active_local_update_source_dir() -> Path:
    for path in local_update_source_candidates():
        if (path / "update.json").is_file():
            return path
    return local_update_source_candidates()[0]


def append_service_log(message: str) -> str:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    return line


def win_error(prefix: str) -> RuntimeError:
    return RuntimeError(f"{prefix}: Windows error {ctypes.get_last_error()}")


def read_or_create_access_key() -> str:
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_urlsafe(24)
    write_access_key(key)
    return key


def write_access_key(key: str) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = KEY_FILE.with_name(f".{KEY_FILE.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temp_file.write_text(key, encoding="utf-8")
    os.replace(temp_file, KEY_FILE)


def current_access_key(fallback: str = "") -> str:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    return key or fallback


def write_new_access_key() -> str:
    key = secrets.token_urlsafe(24)
    write_access_key(key)
    return key


def version_parts(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts[:4]) or (0,)


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    candidate_parts = version_parts(candidate)
    current_parts = version_parts(current)
    width = max(len(candidate_parts), len(current_parts))
    candidate_parts = candidate_parts + (0,) * (width - len(candidate_parts))
    current_parts = current_parts + (0,) * (width - len(current_parts))
    return candidate_parts > current_parts


def normalize_update_manifest(manifest: dict, current_version: str = APP_VERSION) -> dict:
    version = str(manifest.get("version", "")).strip()
    url = str(manifest.get("url", "")).strip()
    notes = str(manifest.get("notes", "")).strip()
    sha256 = str(manifest.get("sha256", "")).strip().lower()
    if not version:
        raise ValueError("更新信息缺少 version")
    return {
        "available": is_newer_version(version, current_version),
        "version": version,
        "url": url,
        "notes": notes,
        "sha256": sha256,
    }


# 直连 opener：忽略系统/环境代理。更新检查、更新包下载与公网探测共用。
_local_only_opener = build_opener(ProxyHandler({}))


def _open_direct(request: Request, timeout: float):
    """直连请求，绕过环境代理。

    HTTP_PROXY 指向未启动的本地代理时，走代理会直接 ConnectionRefused，
    把「有新版本」误判成「检查失败」。这里与 probe_public_entry 保持同一策略。
    """
    return _local_only_opener.open(request, timeout=timeout)


def github_repo_from_url(url: str) -> str:
    """把 GitHub 仓库/发行版地址归一成 owner/repo；不是 GitHub 返回空串。"""
    value = (url or "").strip().rstrip("/")
    if not value:
        return ""
    if re.fullmatch(r"[0-9A-Za-z._-]+/[0-9A-Za-z._-]+", value):
        return value
    match = re.search(r"github\.com/(?:repos/)?([0-9A-Za-z._-]+)/([0-9A-Za-z._-]+)", value)
    if not match:
        return ""
    repo = f"{match.group(1)}/{match.group(2)}"
    return repo[:-4] if repo.endswith(".git") else repo


def pick_release_asset(release: dict) -> dict:
    """挑安装包资产：优先 NSIS 的 *-setup.exe，其次 msi。"""
    assets = release.get("assets")
    if not isinstance(assets, list):
        return {}
    ranked: list[tuple[int, dict]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").lower()
        if not name.endswith(UPDATE_ASSET_SUFFIXES):
            continue
        ranked.append((0 if name.endswith("-setup.exe") else 1, asset))
    if not ranked:
        return {}
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def normalize_github_release(release: dict, current_version: str = APP_VERSION) -> dict:
    """把 GitHub releases API 响应转成与本地 update.json 一致的内部结构。"""
    tag = str(release.get("tag_name") or release.get("name") or "").strip()
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    if not version:
        raise ValueError("GitHub 发行版缺少版本号")
    asset = pick_release_asset(release)
    digest = str(asset.get("digest") or "")
    sha256 = digest.split(":", 1)[1].strip().lower() if digest.lower().startswith("sha256:") else ""
    return {
        "available": is_newer_version(version, current_version),
        "version": version,
        "url": str(asset.get("browser_download_url") or ""),
        "notes": str(release.get("body") or "").strip(),
        "sha256": sha256,
        "source": "github",
        "tag": tag,
        "asset_name": str(asset.get("name") or ""),
    }


def default_update_manifest_url() -> str:
    """未显式配置时的更新源：GitHub 发行版。"""
    return f"https://github.com/{GITHUB_REPO_DEFAULT}"


def fetch_update_source(url: str, timeout: float = 8.0) -> dict:
    """读取更新源：GitHub 地址走 releases API，其余按原有 update.json 清单解析。"""
    repo = github_repo_from_url(url)
    if repo:
        request = Request(
            GITHUB_RELEASES_LATEST_API.format(repo=repo),
            headers={
                "User-Agent": f"{APP_ID}/{APP_VERSION}",
                "Accept": "application/vnd.github+json",
            },
        )
        with _open_direct(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8-sig")
        return normalize_github_release(json.loads(payload))
    request = Request(url, headers={"User-Agent": f"{APP_ID}/{APP_VERSION}"})
    with _open_direct(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8-sig")
    result = normalize_update_manifest(json.loads(payload))
    result["source"] = "manifest"
    return result


def read_update_manifest_url() -> str:
    """更新源地址。

    优先级：环境变量 DOUBAO_BRIDGE_UPDATE_URL > data_dir/update_url.txt > GitHub 默认源。
    没有任何显式配置时直接走 GitHub 发行版，装完即可检查更新。
    """
    env_url = os.environ.get(UPDATE_MANIFEST_ENV, "").strip()
    if env_url:
        return env_url.lstrip("\ufeff")
    if UPDATE_URL_FILE.exists():
        file_url = UPDATE_URL_FILE.read_text(encoding="utf-8").strip().lstrip("\ufeff")
        if file_url:
            return file_url
    return default_update_manifest_url()


def write_text_config(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")


def clear_text_config(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


_update_check_cache: dict = {"checked_at": 0.0, "url": "", "result": None}


def reset_update_check_cache() -> None:
    _update_check_cache.update({"checked_at": 0.0, "url": "", "result": None})


def check_for_update(
    manifest_url: str | None = None,
    timeout: float = 8.0,
    use_cache: bool = True,
) -> dict:
    """检查更新。

    结果做 TTL 缓存：前端会自动轮询，而直连 GitHub 未认证额度只有 60 次/小时，
    没有缓存会被自动检查打满。网络异常不抛给调用方，改为带 error 字段返回，
    让界面能区分「确实已是最新版」和「查不到」。
    """
    url = (manifest_url if manifest_url is not None else read_update_manifest_url()).strip()
    if not url:
        return {
            "configured": False,
            "available": False,
            "version": APP_VERSION,
            "url": "",
            "notes": "",
        }
    now = time.monotonic()
    cached = _update_check_cache.get("result")
    if (
        use_cache
        and isinstance(cached, dict)
        and _update_check_cache.get("url") == url
        and (now - float(_update_check_cache.get("checked_at") or 0.0)) < UPDATE_CHECK_CACHE_TTL
    ):
        return dict(cached)

    result = {
        "configured": True,
        "available": False,
        "version": APP_VERSION,
        "url": "",
        "notes": "",
        "manifest_url": url,
    }
    try:
        fetched = fetch_update_source(url, timeout=timeout)
    except Exception as exc:
        result["error"] = str(exc) or exc.__class__.__name__
        return result

    result.update(fetched)
    result["configured"] = True
    result["manifest_url"] = url
    _update_check_cache.update({"checked_at": now, "url": url, "result": dict(result)})
    return result


def safe_update_version_name(version: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", version.strip())
    return safe or "update"


def download_update_package(
    url: str,
    version: str,
    sha256: str = "",
    download_dir: Path = UPDATE_DOWNLOAD_DIR,
    transport=None,
    timeout: float = 120.0,
) -> Path:
    update_url = url.strip()
    if not update_url:
        raise ValueError("更新清单缺少下载地址")
    download_dir.mkdir(parents=True, exist_ok=True)
    request = Request(update_url, headers={"User-Agent": f"{APP_ID}/{APP_VERSION}"})
    opener = transport or _open_direct
    with opener(request, timeout=timeout) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError("下载到的更新包为空")
    digest = hashlib.sha256(payload).hexdigest()
    expected = sha256.strip().lower()
    if expected and digest != expected:
        raise RuntimeError(f"更新包 SHA256 校验失败：期望 {expected}，实际 {digest}")
    package_path = download_dir / f"DoubaoLanInputBridge_{safe_update_version_name(version)}.exe"
    package_path.write_bytes(payload)
    return package_path


def write_update_script(script_path: Path = UPDATER_SCRIPT_FILE) -> Path:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        r'''param(
    [Parameter(Mandatory=$true)][int]$CurrentPid,
    [Parameter(Mandatory=$true)][string]$PackagePath,
    [Parameter(Mandatory=$true)][string]$TargetExe,
    [Parameter(Mandatory=$true)][string]$LogPath
)

$ErrorActionPreference = "Stop"

function Write-UpdateLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "$stamp $Message"
}

try {
    Write-UpdateLog "updater started"
    try {
        Wait-Process -Id $CurrentPid -Timeout 60 -ErrorAction SilentlyContinue
    } catch {
        Write-UpdateLog "wait current process skipped: $($_.Exception.Message)"
    }

    if (!(Test-Path -LiteralPath $PackagePath)) {
        throw "update package not found: $PackagePath"
    }

    $targetDir = Split-Path -Parent $TargetExe
    $backupDir = Join-Path $targetDir "backup"
    if (!(Test-Path -LiteralPath $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir | Out-Null
    }

    $timestamp = Get-Date -Format "yyyyMMddHHmmss"
    $backupPath = Join-Path $backupDir ("DoubaoLanInputBridge_zh2en." + $timestamp + ".bak.exe")
    $movedOld = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            if (Test-Path -LiteralPath $TargetExe) {
                Move-Item -LiteralPath $TargetExe -Destination $backupPath
            }
            $movedOld = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $movedOld) {
        throw "old app is still locked: $TargetExe"
    }

    try {
        Move-Item -LiteralPath $PackagePath -Destination $TargetExe
    } catch {
        if ((Test-Path -LiteralPath $backupPath) -and !(Test-Path -LiteralPath $TargetExe)) {
            Move-Item -LiteralPath $backupPath -Destination $TargetExe
        }
        throw
    }

    Write-UpdateLog "replacement finished"
    Start-Process -FilePath $TargetExe -WorkingDirectory $targetDir
} catch {
    Write-UpdateLog ("updater failed: " + $_.Exception.Message)
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("Auto update failed: " + $_.Exception.Message, "声笺更新")
}
''',
        encoding="utf-8-sig",
    )
    return script_path


def current_app_executable() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("开发模式不能自动更新，请使用打包后的 exe。")
    return Path(sys.executable).resolve()


def launch_update_script(
    script_path: Path,
    package_path: Path,
    target_exe: Path,
    current_pid: int | None = None,
    log_path: Path = UPDATE_LOG_FILE,
    popen_factory=subprocess.Popen,
) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("自动更新目前仅支持 Windows exe")
    args = [
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-CurrentPid",
        str(current_pid or os.getpid()),
        "-PackagePath",
        str(package_path),
        "-TargetExe",
        str(target_exe),
        "-LogPath",
        str(log_path),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    popen_factory(args, close_fds=True, creationflags=creationflags, startupinfo=startupinfo)


def default_prompt_library() -> dict:
    return {
        "version": 1,
        "source_catalogs": [
            {
                "name": "prompts.chat",
                "url": "https://github.com/f/awesome-chatgpt-prompts",
                "raw_csv": "https://raw.githubusercontent.com/f/prompts.chat/main/prompts.csv",
                "license": "CC0-1.0",
                "usage": "可作为角色型提示词种子库导入；本程序默认只内置分类框架和少量本地模板。",
            }
        ],
        "modes": [
            {
                "id": "dialog",
                "label": "对话提示词",
                "role": "资深对话助手",
                "goal": "把用户的想法整理成适合 ChatGPT、豆包、Claude 等对话模型执行的清晰指令。",
                "style_terms": ["明确目标", "补齐上下文", "列出约束", "要求分步骤", "给出输出格式"],
                "output_format": "先给结论，再给步骤；必要时列出假设、风险和下一步。",
            },
            {
                "id": "raw",
                "label": "原始提示词",
                "role": "提示词编辑器",
                "goal": "保持原意不变，只增强表达的清晰度、边界、变量和验收标准。",
                "style_terms": ["保留原意", "消除歧义", "压缩废话", "增加验收标准", "避免过度发挥"],
                "output_format": "输出一段可直接复制使用的提示词。",
            },
            {
                "id": "image",
                "label": "图像提示词",
                "role": "视觉提示词导演",
                "goal": "把想法转成适合图像生成模型的画面描述。",
                "style_terms": ["主体", "场景", "构图", "光线", "材质", "色彩", "镜头"],
                "output_format": "按主体、环境、风格、构图、负面约束组织。",
            },
            {
                "id": "code",
                "label": "代码提示词",
                "role": "高级软件工程师",
                "goal": "把开发需求整理成可执行的工程任务。",
                "style_terms": ["目标", "文件范围", "接口契约", "边界条件", "测试", "验证命令"],
                "output_format": "按目标、实现范围、约束、测试、交付物输出。",
            },
            {
                "id": "writing",
                "label": "写作提示词",
                "role": "中文内容编辑",
                "goal": "把写作需求整理成有受众、语气、结构和质量标准的提示词。",
                "style_terms": ["受众", "语气", "结构", "长度", "例子", "禁用表达"],
                "output_format": "明确标题、段落结构、语气要求和修改标准。",
            },
        ],
    }


def ensure_prompt_library() -> dict:
    if not PROMPT_LIBRARY_FILE.exists():
        PROMPT_LIBRARY_FILE.write_text(
            json.dumps(default_prompt_library(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return read_prompt_library()


def read_prompt_library() -> dict:
    try:
        data = json.loads(PROMPT_LIBRARY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_prompt_library()
    except json.JSONDecodeError as exc:
        raise ValueError(f"提示词库 JSON 格式错误：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("modes"), list):
        raise ValueError("提示词库必须包含 modes 列表")
    return data


def find_prompt_mode(mode_id: str, library: dict) -> dict:
    modes = library.get("modes", [])
    for mode in modes:
        if mode.get("id") == mode_id:
            return mode
    for mode in modes:
        if mode.get("id") == "dialog":
            return mode
    raise ValueError("提示词库缺少可用模式")


def read_minimax_config() -> dict:
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key and MINIMAX_API_KEY_FILE.exists():
        api_key = MINIMAX_API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    return {
        "api_key": api_key,
        "base_url": (
            os.environ.get("MINIMAX_BASE_URL", "").strip()
            or os.environ.get("OPENAI_BASE_URL", "").strip()
            or MINIMAX_DEFAULT_BASE_URL
        ),
        "model": os.environ.get("MINIMAX_MODEL", "").strip() or MINIMAX_DEFAULT_MODEL,
    }


def file_has_text(path: Path) -> bool:
    try:
        return path.exists() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def env_has_text(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def firewall_port_scope(port: int) -> str:
    port = int(port)
    if port < 1 or port > 65535:
        raise ValueError("端口必须在 1 到 65535 之间")
    default_end = min(65535, DEFAULT_PORT + PORT_AUTO_INCREMENT_LIMIT - 1)
    start = DEFAULT_PORT if DEFAULT_PORT <= port <= default_end else port
    end = min(65535, start + PORT_AUTO_INCREMENT_LIMIT - 1)
    return str(start) if start == end else f"{start}-{end}"


def firewall_rule_name(port: int) -> str:
    return f"{FIREWALL_RULE_PREFIX} {firewall_port_scope(port)}"


def powershell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_firewall_rule_script(port: int, exe_path: str | None = None) -> str:
    port_scope = firewall_port_scope(port)
    target_exe = str(Path(exe_path or running_executable_path()).resolve())
    rule_name = firewall_rule_name(port)
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$rulePrefix = {powershell_single_quote(FIREWALL_RULE_PREFIX)}",
            f"$ruleName = {powershell_single_quote(rule_name)}",
            f"$program = {powershell_single_quote(target_exe)}",
            f"$portScope = {powershell_single_quote(port_scope)}",
            "$existing = Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like ($rulePrefix + ' *') }",
            "if ($existing) {",
            "    $existing | Remove-NetFirewallRule",
            "}",
            "New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $portScope -Profile Private,Public -Program $program | Out-Null",
        ]
    )


def launch_firewall_rule_elevation(
    port: int,
    exe_path: str | None = None,
    popen_factory=subprocess.Popen,
) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("防火墙自动放行目前仅支持 Windows")
    script = build_firewall_rule_script(port, exe_path)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    launcher = (
        "Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden "
        f"-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}')"
    )
    args = [
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        launcher,
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    popen_factory(args, close_fds=True, creationflags=creationflags, startupinfo=startupinfo)


def firewall_rule_status(port: int, exe_path: str | None = None, runner=subprocess.run) -> dict:
    if not IS_WINDOWS:
        return {"allowed": False, "reason": "unsupported"}
    rule_name = firewall_rule_name(port)
    port_scope = firewall_port_scope(port)
    target_exe = str(Path(exe_path or running_executable_path()).resolve())
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$ruleName = {powershell_single_quote(rule_name)}",
            f"$portScope = {powershell_single_quote(port_scope)}",
            f"$program = {powershell_single_quote(target_exe)}",
            "$rules = @(Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)",
            "if ($rules.Count -eq 0) { @{ allowed = $false; reason = 'missing' } | ConvertTo-Json -Compress; exit 0 }",
            "$enabled = @($rules | Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Allow' })",
            "$allowed = $false",
            "foreach ($rule in $enabled) {",
            "    $portFilter = $rule | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue",
            "    $appFilter = $rule | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue",
            "    $portMatches = $portFilter -and $portFilter.Protocol -eq 'TCP' -and [string]$portFilter.LocalPort -eq $portScope",
            "    $programMatches = $appFilter -and [string]::Equals([string]$appFilter.Program, $program, [System.StringComparison]::OrdinalIgnoreCase)",
            "    if ($portMatches -and $programMatches) { $allowed = $true; break }",
            "}",
            "@{ allowed = $allowed; reason = $(if ($allowed) { 'allowed' } else { 'mismatch' }) } | ConvertTo-Json -Compress",
        ]
    )
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    result = runner(
        ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        capture_output=True,
        text=True,
        timeout=8,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        return {"allowed": False, "reason": "query_failed"}
    try:
        parsed = json.loads(result.stdout.strip())
    except (TypeError, ValueError):
        return {"allowed": False, "reason": "invalid_response"}
    return {
        "allowed": bool(parsed.get("allowed", False)),
        "reason": str(parsed.get("reason", "unknown")),
    }


def build_diagnostics_report(port: int = DEFAULT_PORT, service_running: bool = False) -> str:
    update_url = read_update_manifest_url()
    minimax_configured = env_has_text("MINIMAX_API_KEY") or env_has_text("OPENAI_API_KEY") or file_has_text(MINIMAX_API_KEY_FILE)
    lines = [
        f"{APP_NAME} diagnostics",
        f"version: {APP_VERSION}",
        f"service_running: {bool_text(service_running)}",
        f"port: {port}",
        f"firewall_rule: {firewall_rule_name(port)}",
        f"lan_hosts: {', '.join(get_mobile_access_hosts())}",
        f"update_url_configured: {bool_text(bool(update_url))}",
        f"update_url_kind: {'lan-http' if '/__updates__/update.json' in update_url else ('custom' if update_url else 'none')}",
        f"minimax_api_key_configured: {bool_text(minimax_configured)}",
        f"minimax_base_url: {read_minimax_config().get('base_url', MINIMAX_DEFAULT_BASE_URL)}",
        f"minimax_model: {read_minimax_config().get('model', MINIMAX_DEFAULT_MODEL)}",
        f"access_key_configured: {bool_text(file_has_text(KEY_FILE))}",
        f"data_dir_exists: {bool_text(DATA_DIR.exists())}",
        f"prompt_library_exists: {bool_text(PROMPT_LIBRARY_FILE.exists())}",
        f"local_update_source: {active_local_update_source_dir()}",
        f"local_update_source_exists: {bool_text((active_local_update_source_dir() / 'update.json').is_file())}",
        f"executable: {running_executable_path()}",
        f"frozen: {bool_text(bool(getattr(sys, 'frozen', False)))}",
    ]
    return "\n".join(lines)


def build_self_check_report(port: int = DEFAULT_PORT, service_running: bool = False) -> str:
    update_url = read_update_manifest_url()
    minimax_configured = env_has_text("MINIMAX_API_KEY") or env_has_text("OPENAI_API_KEY") or file_has_text(MINIMAX_API_KEY_FILE)
    update_dir = active_local_update_source_dir()
    checks = [
        ("版本", True, APP_VERSION),
        ("服务状态", service_running, f"port={port}" if service_running else "服务未启动"),
        ("访问密钥", file_has_text(KEY_FILE), "已配置" if file_has_text(KEY_FILE) else "未生成"),
        ("局域网主机", bool(get_mobile_access_hosts()), ", ".join(get_mobile_access_hosts())),
        ("防火墙放行", True, f"如手机无法访问，请在管理页执行：{firewall_rule_name(port)}"),
        ("更新源配置", bool(update_url), "已配置" if update_url else "未配置"),
        ("本地更新包", (update_dir / "update.json").is_file(), str(update_dir)),
        ("MiniMax 配置", minimax_configured, "已配置" if minimax_configured else "未配置，可暂不影响互传"),
        ("历史目录", DATA_DIR.exists(), str(DATA_DIR)),
        ("历史记录", HISTORY_FILE.exists(), str(HISTORY_FILE)),
        ("单实例入口", True, "Qt 本地通道已启用"),
        ("托盘唤起", True, "托盘单击/双击绑定显示窗口"),
    ]
    lines = [
        f"{APP_NAME} self-check",
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"version: {APP_VERSION}",
        f"executable: {running_executable_path()}",
        "",
        "checks:",
    ]
    for name, ok, detail in checks:
        lines.append(f"- {'PASS' if ok else 'WARN'} {name}: {detail}")
    if update_url:
        try:
            result = check_for_update(timeout=4.0)
            if result.get("available"):
                lines.append(f"- WARN 更新检查: 发现新版本 {result.get('version')}")
            else:
                lines.append(f"- PASS 更新检查: 当前版本可读取更新源")
        except Exception as exc:
            lines.append(f"- WARN 更新检查: {exc}")
    lines.extend(["", "diagnostics:", build_diagnostics_report(port, service_running)])
    return "\n".join(lines)


def minimax_chat_completions_url(base_url: str) -> str:
    normalized = (base_url or MINIMAX_DEFAULT_BASE_URL).strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def resolve_prompt_mode(mode_id: str, library: dict, text: str = "") -> tuple[dict, str]:
    requested = (mode_id or "auto").strip() or "auto"
    if requested != "auto":
        return find_prompt_mode(requested, library), requested

    lowered = text.lower()
    code_markers = (
        "代码",
        "函数",
        "脚本",
        "接口",
        "api",
        "python",
        "javascript",
        "typescript",
        "bug",
        "报错",
        "异常",
        "pytest",
    )
    image_markers = ("画", "图片", "图像", "海报", "插画", "摄影", "镜头", "logo")
    writing_markers = ("文案", "文章", "标题", "邮件", "小红书", "公众号", "脚本", "改写")
    raw_markers = ("原样", "轻度", "不要扩写", "不要润色", "保持")

    if any(marker in lowered for marker in code_markers):
        resolved = "code"
    elif any(marker in lowered for marker in image_markers):
        resolved = "image"
    elif any(marker in lowered for marker in writing_markers):
        resolved = "writing"
    elif any(marker in lowered for marker in raw_markers):
        resolved = "raw"
    else:
        resolved = "dialog"
    return find_prompt_mode(resolved, library), requested


def build_prompt_enrichment_messages(original: str, mode: dict, answer: str = "") -> list[dict]:
    terms = "、".join(str(item) for item in mode.get("style_terms", [])) or "清晰、具体、可执行"
    system = f"""你是{mode.get("role", "提示词专家")}。

你的任务：{mode.get("goal", "把用户需求整理成更清晰、可执行的提示词。")}

润色要求：
1. 先判断原始需求是否真的需要润色：润色只适用于用户在表达一个想法但表达不清楚、边界不明确或缺少执行条件的情况。
2. 如果原始需求只是简单测试、短命令、按钮名、关键词、标题、确认语或已经清楚的短句，不要把它扩写成完整方案；只做轻度整理，必要时保持一句话。
3. 不要把简单测试、短命令、按钮名、关键词扩展成角色设定、完整流程、表格、风险清单或多级文档。
4. 保留原始意图，不虚构用户没有要求的事实；不要过度扩写，不要替用户新增业务场景。
5. 只有在原始需求确实表达不清时，才补齐必要上下文、约束条件、执行步骤和判断标准；信息不足时，用“可选补充”或“需要确认”表达，不要硬造假设。
6. 强化维度：{terms}。
7. 如果原始需求清楚，直接给候选提示词；如果缺少关键方向会导致候选结果明显跑偏，最多只问 1 个最关键的问题。
8. 如果用户已经提供补充回答，必须给候选提示词，不要继续追问。
9. 输出必须是 JSON 对象，不要 Markdown，不要代码块，不要解释润色过程。
10. JSON 字段固定为：
{{
  "action": "candidate 或 question",
  "question": "需要用户补充时的问题；否则为空字符串",
  "candidate": "可直接复制使用的提示词；需要补充时为空字符串",
  "mode": "{mode.get("id", "dialog")}",
  "reason": "一句话说明为什么直接生成或为什么需要补充"
}}
11. 当 action 为 candidate 时，candidate 必须符合这个输出要求：{mode.get("output_format", "输出可直接复制使用的提示词。")}"""
    user = f"""提示词类型：{mode.get("label", mode.get("id", "默认"))}

原始需求：
{original}"""
    answer = answer.strip()
    if answer:
        user += f"""

用户补充回答：
{answer}"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def extract_json_object(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_prompt_enrichment_result(
    model_text: str,
    original: str,
    mode: dict,
    requested_mode: str,
    model_name: str,
) -> dict:
    payload = extract_json_object(model_text)
    if payload:
        action = str(payload.get("action", "")).strip().lower()
        question = str(payload.get("question", "")).strip()
        candidate = str(payload.get("candidate", "")).strip()
        reason = str(payload.get("reason", "")).strip()
    else:
        action = "candidate"
        question = ""
        candidate = model_text.strip()
        reason = ""

    if action == "question" and question:
        text = question
        candidate = ""
    else:
        action = "candidate"
        text = candidate or model_text.strip()
        question = ""
        candidate = text

    return {
        "changed": text != original,
        "provider": "minimax",
        "requested_mode": requested_mode,
        "mode": mode.get("id", requested_mode),
        "label": mode.get("label", requested_mode),
        "model": model_name,
        "action": action,
        "question": question,
        "candidate": candidate,
        "reason": reason,
        "text": text,
    }


def extract_chat_completion_text(payload: dict) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                pieces = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        pieces.append(item["text"])
                    elif isinstance(item, str):
                        pieces.append(item)
                joined = "".join(pieces).strip()
                if joined:
                    return joined
        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    raise RuntimeError("MiniMax 返回结果中没有可用文本")


def call_minimax_chat(
    messages: list[dict],
    api_config: dict | None = None,
    transport=urlopen,
    timeout: float = MINIMAX_TIMEOUT_SECONDS,
) -> str:
    config = api_config or read_minimax_config()
    api_key = str(config.get("api_key", "")).strip()
    if not api_key:
        raise RuntimeError(
            "未配置 MiniMax API Key。请设置环境变量 MINIMAX_API_KEY 或 OPENAI_API_KEY，"
            f"也可以把 Key 单独写入 {MINIMAX_API_KEY_FILE}"
        )
    body = {
        "model": str(config.get("model", "")).strip() or MINIMAX_DEFAULT_MODEL,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "stream": False,
        "temperature": 0.3,
        "max_completion_tokens": 2000,
    }
    request = Request(
        minimax_chat_completions_url(str(config.get("base_url", MINIMAX_DEFAULT_BASE_URL))),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"{APP_ID}/{APP_VERSION}",
        },
        method="POST",
    )
    try:
        with transport(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"MiniMax 调用失败：HTTP {exc.code} {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"MiniMax 调用失败：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("MiniMax 返回了无法解析的 JSON") from exc
    return extract_chat_completion_text(payload)


def enrich_prompt(
    text: str,
    mode_id: str = "auto",
    library: dict | None = None,
    api_config: dict | None = None,
    transport=urlopen,
    answer: str = "",
) -> dict:
    original = text.strip()
    if not original:
        raise ValueError("提示词不能为空")
    library = library or ensure_prompt_library()
    mode, requested_mode = resolve_prompt_mode(mode_id, library, original)
    config = api_config or read_minimax_config()
    model_name = str(config.get("model", "")).strip() or MINIMAX_DEFAULT_MODEL
    model_text = call_minimax_chat(
        build_prompt_enrichment_messages(original, mode, answer),
        api_config=api_config,
        transport=transport,
    )
    return normalize_prompt_enrichment_result(model_text, original, mode, requested_mode, model_name)


def is_allowed_mobile_lan_host(host: str) -> bool:
    return host.startswith("192.168.")


def sorted_lan_ipv4_addresses(addresses: list[str]) -> list[str]:
    unique_192 = []
    for ip in addresses:
        if not ip or not is_allowed_mobile_lan_host(ip):
            continue
        if ip not in unique_192:
            unique_192.append(ip)
    return sorted(unique_192)


def get_lan_ipv4_addresses() -> list[str]:
    addresses = ["127.0.0.1"]
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        if ip not in addresses:
            addresses.append(ip)
    except OSError:
        pass
    return sorted_lan_ipv4_addresses(addresses)


def normalize_mobile_host(host: str) -> str:
    value = host.strip().lstrip("\ufeff")
    if not value:
        return ""
    if "://" in value:
        parsed = urlparse(value)
        value = parsed.hostname or ""
    else:
        value = value.split("/", 1)[0].strip()
        if value.count(":") == 1:
            value = value.rsplit(":", 1)[0].strip()
    return value.strip("[] \t\r\n")


def read_mobile_host_override() -> str:
    env_host = normalize_mobile_host(os.environ.get(MOBILE_HOST_ENV, ""))
    if env_host and is_allowed_mobile_lan_host(env_host):
        return env_host
    if MOBILE_HOST_FILE.exists():
        file_host = normalize_mobile_host(MOBILE_HOST_FILE.read_text(encoding="utf-8"))
        if file_host and is_allowed_mobile_lan_host(file_host):
            return file_host
    return ""


def get_mobile_access_hosts() -> list[str]:
    override = read_mobile_host_override()
    if override:
        return [override]
    hosts = get_lan_ipv4_addresses()
    return hosts if hosts else [FIXED_LAN_UPDATE_HOST]


def read_public_url_override() -> str:
    """公网访问根地址覆盖（例如 https://sj.q-ze.top）。

    配置后二维码与扫码链接直接指向公网入口，手机不必与电脑处于同一 Wi-Fi。
    优先级：环境变量 DOUBAO_BRIDGE_PUBLIC_URL > 隧道配置(启用时) > data_dir/public_url.txt。
    留空或删除文件即回到原有局域网行为。
    """
    env_url = (os.environ.get(PUBLIC_URL_ENV, "") or "").strip().lstrip("\ufeff")
    if env_url:
        return env_url.rstrip("/")
    tunnel = read_tunnel_config()
    if tunnel_config_active(tunnel):
        return str(tunnel["public_url"]).rstrip("/")
    if PUBLIC_URL_FILE.exists():
        try:
            file_url = PUBLIC_URL_FILE.read_text(encoding="utf-8").strip().lstrip("\ufeff")
        except OSError:
            file_url = ""
        if file_url:
            return file_url.rstrip("/")
    return ""


_public_entry_probe_state: dict = {"checked_at": 0.0, "ok": False}


def read_public_probe_override() -> str:
    """可用性探测地址。

    优先级：环境变量 DOUBAO_BRIDGE_PUBLIC_PROBE > 隧道配置(启用时) > data_dir/public_probe.txt。
    两者都为空表示不做探测，只要配了公网入口就直接用（保留最简行为）。
    推荐指向隧道 metrics 的 /ready：本地请求，毫秒级且直接反映隧道连接状态。
    """
    env_probe = (os.environ.get(PUBLIC_PROBE_ENV, "") or "").strip().lstrip("\ufeff")
    if env_probe:
        return env_probe
    tunnel = read_tunnel_config()
    if tunnel_config_active(tunnel):
        return tunnel_probe_url(tunnel)
    if PUBLIC_PROBE_FILE.exists():
        try:
            file_probe = PUBLIC_PROBE_FILE.read_text(encoding="utf-8").strip().lstrip("\ufeff")
        except OSError:
            file_probe = ""
        if file_probe:
            return file_probe
    return ""


def fetch_public_entry_status(probe_url: str, timeout: float = 2.0) -> bool:
    """单次探测，不走缓存。

    状态展示与启动等待必须看到实时结果，否则 TTL 缓存会把「隧道刚断」显示成健康。
    """
    try:
        with _local_only_opener.open(Request(probe_url, method="GET"), timeout=timeout) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except Exception:
        return False


def probe_public_entry(probe_url: str, timeout: float = 2.0) -> bool:
    """探测入口是否可用。

    结果按 PUBLIC_ENTRY_PROBE_TTL 缓存，避免每次生成扫码链接都发请求。
    使用禁用系统代理的 opener —— 本机探针走代理既慢，又可能被 Cloudflare
    按默认 UA 拦成 403，造成"手机其实能用、本机却判定不可用"的误回退。
    任何异常一律视为不可用，调用方据此回退局域网。
    """
    now = time.monotonic()
    checked_at = float(_public_entry_probe_state.get("checked_at") or 0.0)
    if checked_at and (now - checked_at) < PUBLIC_ENTRY_PROBE_TTL:
        return bool(_public_entry_probe_state.get("ok"))

    ok = fetch_public_entry_status(probe_url, timeout=timeout)

    _public_entry_probe_state["checked_at"] = now
    _public_entry_probe_state["ok"] = ok
    return ok


# ----------------------------------------------------------------- Cloudflare 隧道托管
#
# 目标：把「公网入口」从手写 public_url.txt / public_probe.txt + 计划任务 vbs，
# 收敛成 App 内可配置、可启停、可观测的一项能力。
# 取址优先级保持为：环境变量 > 隧道配置(enabled) > public_url.txt，向后兼容。


def tunnel_log_path(name: str = "") -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "-", (name or "").strip()).strip("-")
    return DATA_DIR / (f"cloudflared-{safe}.log" if safe else "cloudflared-tunnel.log")


def default_tunnel_config() -> dict:
    return {
        "enabled": False,
        "name": "",
        "public_url": "",
        "cloudflared_path": "",
        "metrics_port": TUNNEL_DEFAULT_METRICS_PORT,
        "config_path": "",
    }


def normalize_tunnel_config(raw: dict | None) -> dict:
    config = default_tunnel_config()
    if not isinstance(raw, dict):
        return config
    config["enabled"] = bool(raw.get("enabled", False))
    config["name"] = str(raw.get("name", "") or "").strip()
    config["public_url"] = str(raw.get("public_url", "") or "").strip().rstrip("/")
    config["cloudflared_path"] = str(raw.get("cloudflared_path", "") or "").strip()
    config["config_path"] = str(raw.get("config_path", "") or "").strip()
    try:
        port = int(raw.get("metrics_port", TUNNEL_DEFAULT_METRICS_PORT))
    except (TypeError, ValueError):
        port = TUNNEL_DEFAULT_METRICS_PORT
    config["metrics_port"] = port if 1 <= port <= 65535 else TUNNEL_DEFAULT_METRICS_PORT
    return config


def read_tunnel_config(path: Path | None = None) -> dict:
    target = path or TUNNEL_CONFIG_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default_tunnel_config()
    return normalize_tunnel_config(raw)


def write_tunnel_config(config: dict, path: Path | None = None) -> dict:
    target = path or TUNNEL_CONFIG_FILE
    normalized = normalize_tunnel_config(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # 隧道状态变了，缓存里的入口判定立即失效，避免旧结论继续供码
    _public_entry_probe_state["checked_at"] = 0.0
    _public_entry_probe_state["ok"] = False
    return normalized


def tunnel_probe_url(config: dict) -> str:
    port = int(config.get("metrics_port") or TUNNEL_DEFAULT_METRICS_PORT)
    return f"http://127.0.0.1:{port}/ready"


def tunnel_config_active(config: dict | None = None) -> bool:
    cfg = normalize_tunnel_config(config if config is not None else read_tunnel_config())
    return bool(cfg.get("enabled") and cfg.get("public_url"))


def find_cloudflared(configured: str = "") -> str:
    candidate = (configured or "").strip().strip('"')
    if candidate and Path(candidate).is_file():
        return candidate
    for path in CLOUDFLARED_CANDIDATE_PATHS:
        if Path(path).is_file():
            return path
    found = shutil.which("cloudflared")
    return found or ""


def parse_tunnel_config_text(text: str) -> dict:
    """极简解析 cloudflared config.yml 中我们关心的两项：隧道标识与 ingress 主机名。

    刻意不引入 PyYAML：只需处理顶层 `tunnel:` 标量与 `ingress:` 下的 `hostname:`，
    解析不出来就返回空值，由界面手工填写兜底，不给 sidecar 增加打包依赖风险。
    """
    tunnel_id = ""
    hostnames: list[str] = []
    in_ingress = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        is_item = stripped.startswith("- ")
        indent = len(line) - len(line.lstrip())
        if not is_item and indent == 0:
            if stripped.startswith("tunnel:"):
                tunnel_id = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            # 任何新的顶层键都代表 ingress 块结束
            in_ingress = stripped.startswith("ingress:")
            continue
        if not in_ingress:
            continue
        # ingress 条目形如 "- hostname: sj.q-ze.top"，需要先剥掉列表项前缀；
        # 也兼容列表与父键同缩进（顶层连字符）的写法。
        item = stripped[2:].strip() if is_item else stripped
        if item.startswith("hostname:"):
            value = item.split(":", 1)[1].strip().strip('"').strip("'")
            if value and value not in hostnames:
                hostnames.append(value)
    return {"tunnel": tunnel_id, "hostnames": hostnames}


def cloudflared_home() -> Path:
    return Path.home() / ".cloudflared"


def detect_tunnel_candidates(root: Path | None = None) -> list[dict]:
    """扫描 ~/.cloudflared/*/config.yml，供界面一键填充。"""
    base = root or cloudflared_home()
    candidates: list[dict] = []
    try:
        children = sorted(base.iterdir())
    except OSError:
        return candidates
    for child in children:
        if not child.is_dir():
            continue
        config_file = child / "config.yml"
        if not config_file.is_file():
            continue
        try:
            parsed = parse_tunnel_config_text(
                config_file.read_text(encoding="utf-8-sig", errors="replace")
            )
        except OSError:
            continue
        hostnames = list(parsed.get("hostnames") or [])
        candidates.append(
            {
                "name": child.name,
                "config_path": str(config_file),
                "tunnel": str(parsed.get("tunnel") or ""),
                "hostnames": hostnames,
                "public_url": f"https://{hostnames[0]}" if hostnames else "",
            }
        )
    return candidates


_tunnel_process_state: dict = {"process": None, "pid": 0, "name": ""}


def _reset_tunnel_process_state() -> None:
    _tunnel_process_state.update({"process": None, "pid": 0, "name": ""})


def tunnel_owned_pid() -> int:
    """本进程自己拉起的 cloudflared PID；未托管或已退出返回 0。"""
    process = _tunnel_process_state.get("process")
    if process is None:
        return 0
    try:
        if process.poll() is not None:
            _reset_tunnel_process_state()
            return 0
    except Exception:
        _reset_tunnel_process_state()
        return 0
    return int(_tunnel_process_state.get("pid") or 0)


def wait_for_tunnel_ready(
    probe_url: str,
    timeout: float = TUNNEL_READY_TIMEOUT,
    interval: float = 1.0,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if fetch_public_entry_status(probe_url, timeout=1.5):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def tunnel_status(config: dict | None = None, timeout: float = 2.0) -> dict:
    cfg = normalize_tunnel_config(config if config is not None else read_tunnel_config())
    probe_url = tunnel_probe_url(cfg)
    ready = fetch_public_entry_status(probe_url, timeout=timeout)
    owned_pid = tunnel_owned_pid()
    cloudflared = find_cloudflared(cfg.get("cloudflared_path", ""))
    return {
        "enabled": bool(cfg.get("enabled")),
        "name": str(cfg.get("name") or ""),
        "public_url": str(cfg.get("public_url") or ""),
        "config_path": str(cfg.get("config_path") or ""),
        "metrics_port": int(cfg.get("metrics_port") or TUNNEL_DEFAULT_METRICS_PORT),
        "probe_url": probe_url,
        "ready": bool(ready),
        "running": bool(ready or owned_pid),
        "managed": bool(owned_pid),
        "owned_pid": owned_pid,
        "cloudflared_path": cloudflared,
        "cloudflared_available": bool(cloudflared),
        "log_path": str(tunnel_log_path(str(cfg.get("name") or ""))),
    }


def _hidden_process_kwargs() -> dict:
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return {"creationflags": creationflags, "startupinfo": startupinfo}


def build_tunnel_command(config: dict, cloudflared: str) -> list[str]:
    cfg = normalize_tunnel_config(config)
    name = str(cfg.get("name") or "").strip()
    command = [cloudflared, "tunnel"]
    config_path = str(cfg.get("config_path") or "").strip()
    if config_path:
        command += ["--config", config_path]
    command += [
        "--no-autoupdate",
        "--metrics",
        f"127.0.0.1:{int(cfg.get('metrics_port') or TUNNEL_DEFAULT_METRICS_PORT)}",
        "--loglevel",
        "info",
        "--logfile",
        str(tunnel_log_path(name)),
        "run",
        name,
    ]
    return command


def start_tunnel(
    config: dict | None = None,
    popen_factory=subprocess.Popen,
    wait_ready: bool = True,
) -> dict:
    """启动托管隧道。

    已由外部（例如计划任务）拉起且健康时不再重复拉起，避免同一隧道出现
    多个本地连接器；这种情况返回 managed=False，由界面如实标注。
    """
    if not IS_WINDOWS:
        raise RuntimeError("隧道托管目前仅支持 Windows")
    cfg = normalize_tunnel_config(config if config is not None else read_tunnel_config())
    cloudflared = find_cloudflared(cfg.get("cloudflared_path", ""))
    if not cloudflared:
        raise RuntimeError("未找到 cloudflared，请先安装或手动指定 cloudflared.exe 路径")
    name = str(cfg.get("name") or "").strip()
    if not name:
        raise RuntimeError("未指定隧道名称")
    config_path = str(cfg.get("config_path") or "").strip()
    if config_path and not Path(config_path).is_file():
        raise RuntimeError(f"隧道配置不存在：{config_path}")

    probe_url = tunnel_probe_url(cfg)
    if not tunnel_owned_pid() and not fetch_public_entry_status(probe_url, timeout=2.0):
        command = build_tunnel_command(cfg, cloudflared)
        process = popen_factory(
            command,
            close_fds=True,
            cwd=str(DATA_DIR),
            **_hidden_process_kwargs(),
        )
        _tunnel_process_state.update(
            {"process": process, "pid": int(getattr(process, "pid", 0) or 0), "name": name}
        )
        if wait_ready:
            wait_for_tunnel_ready(probe_url)
    return tunnel_status(cfg)


def stop_tunnel(runner=subprocess.run) -> dict:
    """停止托管隧道；只作用于本进程拉起的进程，外部托管的不动。"""
    pid = tunnel_owned_pid()
    if not pid:
        return {"stopped": False, "reason": "external"}
    try:
        runner(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    process = _tunnel_process_state.get("process")
    if process is not None:
        try:
            process.wait(timeout=5)
        except Exception:
            pass
    _reset_tunnel_process_state()
    return {"stopped": True, "reason": "managed"}


def tunnel_log_tail(name: str = "", limit: int = TUNNEL_LOG_TAIL_BYTES) -> str:
    path = tunnel_log_path(name)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max(0, limit)))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def build_access_url(host: str, port: int, access_key: str) -> str:
    """对外扫码地址：公网入口可用时优先公网，不可用时回退局域网。"""
    public_base = read_public_url_override()
    if public_base:
        probe_url = read_public_probe_override()
        if not probe_url or probe_public_entry(probe_url):
            return f"{public_base}/?key={quote(access_key, safe='')}"
    return f"http://{host}:{port}/?key={quote(access_key, safe='')}"


def build_local_access_url(port: int, access_key: str) -> str:
    """本机自用地址：始终走回环，不受公网入口覆盖影响。"""
    return f"http://127.0.0.1:{port}/?key={quote(access_key, safe='')}"


def build_health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def display_qr_target(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "局域网地址"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}"


def build_connection_self_check(port: int, service_running: bool, host: str | None = None) -> str:
    lan_host = host or preferred_lan_host()
    target = f"{lan_host}:{port}"
    health_url = build_health_url(lan_host, port)
    status = "运行中" if service_running else "未启动"
    return "\n".join(
        [
            "声笺连接自检",
            f"服务状态：{status}",
            f"电脑局域网入口：{target}",
            f"手机健康检查：{health_url}",
            "判断方法：",
            "1. 手机先打开健康检查地址。",
            "2. 能看到 ok=true，说明网络通，重新扫码或复制完整扫码链接。",
            f"3. 打不开或超时，说明手机到电脑被拦截：确认同一 Wi-Fi、关闭路由器 AP 隔离，或用管理员权限放行 Windows 防火墙 TCP {firewall_port_scope(port)}。",
            "4. 能打开 health 但页面无权限，说明链接缺少访问 key，请重新扫二维码。",
            "注意：Wi-Fi 自动连接二维码需要明文 Wi-Fi 密码，当前不自动生成。",
        ]
    )


def preferred_lan_host() -> str:
    hosts = get_mobile_access_hosts()
    for host in hosts:
        if is_allowed_mobile_lan_host(host):
            return host
    return FIXED_LAN_UPDATE_HOST


def bridge_probe_hosts() -> list[str]:
    override = read_mobile_host_override()
    detected_hosts = [override] if override else get_lan_ipv4_addresses()
    hosts = ["127.0.0.1", *detected_hosts]
    return list(dict.fromkeys(hosts))


def is_tcp_port_in_use(port: int, hosts: list[str] | None = None, timeout: float = 0.2) -> bool:
    for host in hosts or bridge_probe_hosts():
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def wait_for_bridge_server_identity(
    port: int,
    expected_pid: int,
    hosts: list[str] | None = None,
    timeout: float = 2.0,
) -> tuple[bool, str]:
    targets = hosts or bridge_probe_hosts()
    deadline = time.monotonic() + timeout
    last_error = "服务未响应"
    while time.monotonic() < deadline:
        all_valid = True
        for host in targets:
            connection = HTTPConnection(host, int(port), timeout=0.4)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
                if response.status != HTTPStatus.OK:
                    raise ValueError(f"{host}:{port} 返回 HTTP {response.status}")
                if int(payload.get("pid", 0)) != int(expected_pid):
                    raise ValueError(f"{host}:{port} 属于其他进程 PID {payload.get('pid')}")
                if str(payload.get("version", "")) != APP_VERSION:
                    raise ValueError(f"{host}:{port} 返回其他版本 {payload.get('version')}")
            except Exception as exc:
                all_valid = False
                last_error = str(exc)
                break
            finally:
                connection.close()
        if all_valid:
            return True, ""
        time.sleep(0.08)
    return False, last_error


def write_lan_update_manifest_url(port: int) -> str:
    _ = port
    url = local_update_url_for_host(
        f"{FIXED_LAN_UPDATE_HOST}:{FIXED_LAN_UPDATE_PORT}",
        "update.json",
    )
    UPDATE_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_URL_FILE.write_text(url + "\n", encoding="utf-8")
    return url


def is_lan_update_source_url(url: str) -> bool:
    return "/__updates__/" in (url or "")


def refresh_lan_update_manifest_url(port: int) -> str:
    """启动时刷新局域网更新源端口。

    只在当前更新源本来就是局域网地址时才生效 —— 默认源已改为 GitHub，
    无条件回写会把用户显式选择的 GitHub 源覆盖掉。
    """
    if not is_lan_update_source_url(read_update_manifest_url()):
        return ""
    return write_lan_update_manifest_url(port)


def qr_matrix(text: str) -> list[list[bool]]:
    code = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    code.add_data(text)
    code.make(fit=True)
    return [[bool(value) for value in row] for row in code.get_matrix()]


def qr_photo_image(text: str, scale: int = 6, border: int = 4) -> tk.PhotoImage:
    matrix = qr_matrix(text)
    image_size = len(matrix) * scale
    image = tk.PhotoImage(width=image_size, height=image_size)
    image.put("#ffffff", to=(0, 0, image_size, image_size))
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                left = x * scale
                top = y * scale
                image.put("#111111", to=(left, top, left + scale, top + scale))
    return image


def set_clipboard_text(text: str, retries: int = 10) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Keyboard paste is only available on Windows.")

    data = (text + "\0").encode("utf-16-le")
    last_error = None
    for _ in range(retries):
        if user32.OpenClipboard(None):
            break
        last_error = ctypes.get_last_error()
        time.sleep(0.05)
    else:
        raise RuntimeError(f"OpenClipboard failed: Windows error {last_error}")

    handle = None
    try:
        if not user32.EmptyClipboard():
            raise win_error("EmptyClipboard failed")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise win_error("GlobalAlloc failed")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise win_error("GlobalLock failed")
        try:
            ctypes.memmove(locked, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise win_error("SetClipboardData failed")
        handle = None
    finally:
        user32.CloseClipboard()


def send_ctrl_v() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Keyboard paste is only available on Windows.")
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def send_enter() -> None:
    if not IS_WINDOWS:
        raise RuntimeError("Keyboard paste is only available on Windows.")
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)


def paste_text(
    text: str,
    add_newline: bool = False,
    press_enter: bool = False,
    enter_delay_sec: float = 0.5,
) -> dict:
    payload = text + ("\n" if add_newline else "")
    set_clipboard_text(payload)
    time.sleep(0.08)
    send_ctrl_v()
    enter_pressed = False
    if press_enter:
        time.sleep(max(0.0, min(5.0, float(enter_delay_sec))))
        send_enter()
        enter_pressed = True
    return {"chars": len(payload), "enter_pressed": enter_pressed}


def history_now(now: int | float | None = None) -> int:
    return int(now if now is not None else time.time())


def format_history_timestamp(ts: int | float | str | None) -> str:
    try:
        value = int(float(ts or 0))
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return "时间未知"
    return time.strftime("%Y年%m月%d日 %H:%M", time.localtime(value))


def history_id(prefix: str = "h") -> str:
    return f"{prefix}-{now_ms()}-{secrets.token_hex(4)}"


def read_history_file() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def write_history_file(records: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_history_record(record: dict) -> dict:
    normalized = dict(record)
    normalized.setdefault("id", history_id())
    normalized.setdefault("ts", history_now())
    normalized.setdefault("pinned", False)
    normalized.setdefault("action", "")
    return normalized


def sort_history_records(records: list[dict]) -> list[dict]:
    return sorted(
        records,
        key=lambda item: int(item.get("ts", 0)),
        reverse=True,
    )


def trim_history_records(records: list[dict], now: int | float | None = None) -> list[dict]:
    cutoff = history_now(now) - HISTORY_RETENTION_DAYS * 86400 if now is not None else None
    kept = []
    for item in records:
        normalized = normalize_history_record(item)
        if cutoff is not None and not normalized.get("pinned") and int(normalized.get("ts", 0)) < cutoff:
            continue
        kept.append(normalized)
    pinned = [item for item in kept if item.get("pinned")]
    regular = [item for item in kept if not item.get("pinned")]
    regular = sort_history_records(regular)
    limit = max(0, MAX_HISTORY_ITEMS - len(pinned))
    return sort_history_records(pinned + regular[:limit])


def save_history_records(records: list[dict], now: int | float | None = None) -> list[dict]:
    trimmed = trim_history_records(records, now=now)
    write_history_file(trimmed)
    return trimmed


def list_clipboard_history(limit: int = 50) -> list[dict]:
    records = trim_history_records(read_history_file())
    write_history_file(records)
    return records[: max(0, limit)]


def history_record_search_text(record: dict) -> str:
    preview = history_record_preview(record)
    parts = [
        str(record.get("type", "")),
        str(record.get("action", "")),
        str(record.get("text", "")),
        str(record.get("preview", "")),
        str(preview.get("kind", "")),
        str(preview.get("preview", "")),
        str(preview.get("info", "")),
    ]
    for item in record.get("files") or []:
        if isinstance(item, dict):
            parts.extend([str(item.get("name", "")), str(item.get("path", "")), str(item.get("content_type", ""))])
    return " ".join(parts).lower()


def append_history_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with HISTORY_ARCHIVE_LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()


def active_history_archive_dir() -> Path:
    if HISTORY_FILE.parent.resolve() == DATA_DIR.resolve():
        return HISTORY_ARCHIVE_DIR
    return HISTORY_FILE.parent / "history_archive"


def active_text_history_jsonl() -> Path:
    return active_history_archive_dir() / "texts.jsonl"


def active_file_history_jsonl() -> Path:
    return active_history_archive_dir() / "files.jsonl"


def ensure_history_archive_structure() -> Path:
    root = active_history_archive_dir()
    for name in ("images", "videos", "files"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def read_history_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    with HISTORY_ARCHIVE_LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(normalize_history_record(record))
    return records


def list_global_history() -> list[dict]:
    merged = {}
    for record in [
        *read_history_file(),
        *read_history_jsonl(active_text_history_jsonl()),
        *read_history_jsonl(active_file_history_jsonl()),
    ]:
        normalized = normalize_history_record(record)
        merged[str(normalized.get("id", history_id()))] = normalized
    return sort_history_records(list(merged.values()))


def backfill_history_archive() -> dict[str, int]:
    ensure_history_archive_structure()
    text_path = active_text_history_jsonl()
    file_path = active_file_history_jsonl()
    known_text_ids = {str(item.get("id", "")) for item in read_history_jsonl(text_path)}
    known_file_ids = {str(item.get("id", "")) for item in read_history_jsonl(file_path)}
    added_text = 0
    added_files = 0
    for record in sort_history_records(read_history_file()):
        record_id = str(record.get("id", ""))
        if record.get("type") == "text":
            if record_id and record_id not in known_text_ids:
                append_history_jsonl(text_path, record)
                known_text_ids.add(record_id)
                added_text += 1
        elif record_id and record_id not in known_file_ids:
            append_history_jsonl(file_path, record)
            known_file_ids.add(record_id)
            added_files += 1
    return {"text": added_text, "files": added_files}


def history_record_category(record: dict) -> str:
    if record.get("type") == "text":
        return "text"
    kind = str(history_record_preview(record).get("kind", ""))
    return {
        "图片": "image",
        "视频": "video",
        "媒体": "media",
        "混合": "mixed",
        "文件": "file",
    }.get(kind, "file")


def history_category_matches(record: dict, category: str = "all") -> bool:
    selected = str(category or "all").strip().lower()
    if selected in ("", "all"):
        return True
    actual = history_record_category(record)
    if selected == "file":
        return actual == "file"
    return actual == selected


def search_clipboard_history(
    query: str = "",
    limit: int | None = HISTORY_WINDOW_LIMIT,
    category: str = "all",
) -> list[dict]:
    words = [word.lower() for word in str(query or "").split() if word.strip()]
    records = list_global_history()
    records = [record for record in records if history_category_matches(record, category)]
    if words:
        records = [record for record in records if all(word in history_record_search_text(record) for word in words)]
    if limit is None:
        return records
    return records[: max(0, int(limit))]


def format_file_size(size: int | float | str | None) -> str:
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        value = 0
    units = ("B", "KB", "MB", "GB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "0 B"


def is_image_history_file(file_info: dict) -> bool:
    content_type = str(file_info.get("content_type", "")).lower()
    name = str(file_info.get("name") or file_info.get("path") or "").lower()
    return content_type.startswith("image/") or name.endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif")
    )


def is_video_history_file(file_info: dict) -> bool:
    content_type = str(file_info.get("content_type", "")).lower()
    name = str(file_info.get("name") or file_info.get("path") or "").lower()
    return content_type.startswith("video/") or name.endswith(
        (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wmv", ".3gp", ".3gpp")
    )


def is_gallery_history_file(file_info: dict) -> bool:
    return is_image_history_file(file_info) or is_video_history_file(file_info)


def history_record_preview(record: dict) -> dict:
    if record.get("type") == "text":
        text = " ".join(str(record.get("text") or record.get("preview") or "").split())
        preview = text[:80] + ("..." if len(text) > 80 else "")
        return {
            "kind": "文字",
            "preview": preview or "空文本",
            "info": f"{int(record.get('chars', len(text)) or 0)} 字",
        }
    files = [item for item in (record.get("files") or []) if isinstance(item, dict)]
    image_count = sum(1 for item in files if is_image_history_file(item))
    video_count = sum(1 for item in files if is_video_history_file(item))
    gallery_count = image_count + video_count
    total_size = sum(int(item.get("bytes", 0) or 0) for item in files)
    names = [str(item.get("name") or Path(str(item.get("path", ""))).name) for item in files]
    preview = "、".join(names[:3])
    if len(names) > 3:
        preview += f" 等 {len(names)} 个"
    if image_count and image_count == len(files):
        kind = "图片"
        info = f"{image_count} 张 | {format_file_size(total_size)}"
    elif video_count and video_count == len(files):
        kind = "视频"
        info = f"{video_count} 个 | {format_file_size(total_size)}"
    elif gallery_count and gallery_count == len(files):
        kind = "媒体"
        info = f"{len(files)} 个 | 图片 {image_count} 张 | 视频 {video_count} 个 | {format_file_size(total_size)}"
    elif gallery_count:
        kind = "混合"
        counts = []
        if image_count:
            counts.append(f"图片 {image_count} 张")
        if video_count:
            counts.append(f"视频 {video_count} 个")
        info = f"{len(files)} 个 | {' | '.join(counts)} | {format_file_size(total_size)}"
    else:
        kind = "文件"
        info = f"{len(files)} 个 | {format_file_size(total_size)}"
    return {"kind": kind, "preview": preview or "未命名文件", "info": info}


def first_image_history_path(record: dict) -> Path | None:
    if record.get("type") != "file":
        return None
    for item in record.get("files") or []:
        if not isinstance(item, dict) or not is_image_history_file(item):
            continue
        path = Path(str(item.get("path", "")))
        if path.is_file():
            return path
    return None


def first_gallery_history_path(record: dict) -> Path | None:
    if record.get("type") != "file":
        return None
    for item in record.get("files") or []:
        if not isinstance(item, dict) or not is_gallery_history_file(item):
            continue
        path = Path(str(item.get("path", "")))
        if path.is_file():
            return path
    return None


def cleanup_history(now: int | float | None = None) -> list[dict]:
    return save_history_records(read_history_file(), now=now)


def record_text_history(
    text: str,
    action: str = "send",
    pinned: bool = False,
    now: int | float | None = None,
) -> dict:
    content = str(text or "").strip()
    if not content:
        raise ValueError("历史文本不能为空")
    record = {
        "id": history_id("text"),
        "type": "text",
        "text": content[:MAX_TEXT_LENGTH],
        "preview": content[:120],
        "chars": len(content),
        "action": action,
        "pinned": bool(pinned),
        "ts": history_now(now),
    }
    append_history_jsonl(active_text_history_jsonl(), record)
    save_history_records([record] + read_history_file())
    return record


def record_file_history(
    files: list[dict],
    action: str = "clipboard",
    pinned: bool = False,
    now: int | float | None = None,
) -> dict:
    normalized_files = []
    for item in files:
        path = Path(str(item.get("path", ""))).resolve()
        normalized_files.append(
            {
                "name": str(item.get("name") or path.name),
                "path": str(path),
                "bytes": int(item.get("bytes", 0) or 0),
                "content_type": str(item.get("content_type", "")),
            }
        )
    if not normalized_files:
        raise ValueError("历史文件不能为空")
    record = {
        "id": history_id("file"),
        "type": "file",
        "files": normalized_files,
        "preview": "、".join(item["name"] for item in normalized_files[:3]),
        "file_count": len(normalized_files),
        "action": action,
        "pinned": bool(pinned),
        "ts": history_now(now),
    }
    append_history_jsonl(active_file_history_jsonl(), record)
    save_history_records([record] + read_history_file())
    return record


def delete_history_item(record_id: str) -> bool:
    records = read_history_file()
    kept = [item for item in records if str(item.get("id", "")) != str(record_id)]
    save_history_records(kept)
    return len(kept) != len(records)


def clear_clipboard_history(keep_pinned: bool = False) -> list[dict]:
    records = read_history_file()
    kept = [item for item in records if keep_pinned and item.get("pinned")]
    save_history_records(kept)
    return kept


def set_history_pinned(record_id: str, pinned: bool = True) -> dict:
    records = read_history_file()
    for item in records:
        if str(item.get("id", "")) == str(record_id):
            item["pinned"] = bool(pinned)
            save_history_records(records)
            return item
    raise ValueError("历史记录不存在")


def find_history_record(record_id: str) -> dict:
    for item in list_global_history():
        if str(item.get("id", "")) == str(record_id):
            return item
    raise ValueError("历史记录不存在")


def open_history_file_item(record_id: str, mode: str = "file", file_index: int = 0, opener=None) -> dict:
    record = find_history_record(record_id)
    if record.get("type") != "file":
        raise ValueError("不是文件历史")
    files = record.get("files") or []
    if not files:
        raise ValueError("文件历史为空")
    file_info = files[max(0, min(int(file_index), len(files) - 1))]
    target = Path(str(file_info.get("path", ""))).resolve()
    if not target.is_file():
        raise ValueError("文件不存在")
    open_target = target.parent if mode == "folder" else target
    if opener is None:
        if IS_WINDOWS:
            os.startfile(str(open_target))
        else:
            webbrowser.open(open_target.as_uri())
    else:
        opener(open_target)
    return {"path": str(open_target), "mode": mode}


def sanitize_upload_filename(filename: str) -> str:
    name = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    name = name.strip(". ")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:180] or f"upload-{now_ms()}.bin"


def unique_upload_path(upload_dir: Path, filename: str) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    candidate = upload_dir / sanitize_upload_filename(filename)
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 1000):
        next_candidate = upload_dir / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    return upload_dir / f"{stem}-{now_ms()}{suffix}"


def history_file_category_dir(filename: str, content_type: str, archive_dir: Path = HISTORY_ARCHIVE_DIR) -> Path:
    file_info = {"name": filename, "content_type": content_type}
    if is_image_history_file(file_info):
        return archive_dir / "images"
    if is_video_history_file(file_info):
        return archive_dir / "videos"
    return archive_dir / "files"


def parse_multipart_upload(
    body: bytes,
    content_type: str,
    upload_dir: Path = HISTORY_ARCHIVE_DIR,
    categorize: bool = True,
) -> dict:
    return parse_multipart_upload_stream(BytesIO(body), len(body), content_type, upload_dir, categorize)


def parse_multipart_upload_stream(
    stream,
    content_length: int,
    content_type: str,
    upload_dir: Path = HISTORY_ARCHIVE_DIR,
    categorize: bool = True,
) -> dict:
    if content_length <= 0:
        raise ValueError("empty upload")
    if "multipart/form-data" not in content_type:
        raise ValueError("invalid multipart content type")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import cgi

    form = cgi.FieldStorage(
        fp=stream,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(content_length),
        },
        keep_blank_values=True,
    )
    fields: dict[str, str] = {}
    files: list[dict] = []
    for part in form.list or []:
        name = str(part.name or "")
        filename = part.filename
        if filename:
            if len(files) >= MAX_UPLOAD_FILES:
                raise ValueError(f"一次最多上传 {MAX_UPLOAD_FILES} 个文件")
            part_content_type = str(part.type or mimetypes.guess_type(filename)[0] or "application/octet-stream")
            target_dir = history_file_category_dir(filename, part_content_type, upload_dir) if categorize else upload_dir
            path = unique_upload_path(target_dir, filename)
            with path.open("wb") as output:
                shutil.copyfileobj(part.file, output, length=1024 * 1024)
            bytes_written = path.stat().st_size
            files.append(
                {
                    "name": path.name,
                    "path": str(path.resolve()),
                    "bytes": bytes_written,
                    "content_type": part_content_type,
                }
            )
        else:
            fields[name] = str(part.value or "").strip()
    if not files:
        raise ValueError("没有收到文件")
    return {"key": fields.get("key", ""), "files": files}


def build_file_drop_data(paths: list[Path]) -> bytes:
    file_list = "\0".join(str(Path(path)) for path in paths) + "\0\0"
    # DROPFILES: pFiles=20, pt=(0,0), fNC=0, fWide=1, then UTF-16 file list.
    header = (
        (20).to_bytes(4, "little")
        + (0).to_bytes(4, "little", signed=True)
        + (0).to_bytes(4, "little", signed=True)
        + (0).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
    )
    return header + file_list.encode("utf-16le")


def set_clipboard_files(paths: list[Path]) -> None:
    if not IS_WINDOWS:
        raise RuntimeError("File clipboard is only available on Windows.")
    resolved = [Path(path).resolve() for path in paths]
    data = build_file_drop_data(resolved)
    last_error = 0
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        last_error = ctypes.get_last_error()
        time.sleep(0.05)
    else:
        raise RuntimeError(f"OpenClipboard failed: Windows error {last_error}")

    handle = None
    try:
        if not user32.EmptyClipboard():
            raise win_error("EmptyClipboard failed")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise win_error("GlobalAlloc failed")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise win_error("GlobalLock failed")
        try:
            ctypes.memmove(locked, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_HDROP, handle):
            raise win_error("SetClipboardData failed")
        handle = None
    finally:
        user32.CloseClipboard()


def put_uploaded_files_on_clipboard(files: list[dict]) -> dict:
    paths = [Path(item["path"]) for item in files]
    set_clipboard_files(paths)
    return {"files": len(paths), "names": [path.name for path in paths]}


def paste_uploaded_files(
    files: list[dict],
    press_enter: bool = False,
    enter_delay_sec: float = 0.5,
    set_files=set_clipboard_files,
    paste=send_ctrl_v,
    enter=send_enter,
    sleeper=time.sleep,
) -> dict:
    paths = [Path(item["path"]) for item in files]
    pasted_names = []
    for index, path in enumerate(paths):
        set_files([path])
        sleeper(0.08)
        paste()
        pasted_names.append(path.name)
        if index < len(paths) - 1:
            sleeper(0.35)
    enter_pressed = False
    if press_enter:
        sleeper(max(0.0, min(5.0, float(enter_delay_sec))))
        enter()
        enter_pressed = True
    return {
        "files": len(paths),
        "pastes": len(paths),
        "names": pasted_names,
        "enter_pressed": enter_pressed,
    }


def list_shared_files(share_dir: Path = MOBILE_SHARE_DIR) -> list[dict]:
    if not share_dir.exists():
        return []
    records = []
    for path in share_dir.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        records.append(
            {
                "name": path.name,
                "bytes": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    records.sort(key=lambda item: item["mtime"], reverse=True)
    return records


def mobile_share_feed_path(share_dir: Path = MOBILE_SHARE_DIR, feed_file: Path | None = None) -> Path:
    if feed_file is not None:
        return Path(feed_file)
    if Path(share_dir).resolve() == MOBILE_SHARE_DIR.resolve():
        return MOBILE_SHARE_FEED_FILE
    return Path(share_dir).parent / f"{Path(share_dir).name}_feed.json"


def read_mobile_share_feed(
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> list[dict]:
    path = mobile_share_feed_path(share_dir, feed_file)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def write_mobile_share_feed(
    items: list[dict],
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> list[dict]:
    path = mobile_share_feed_path(share_dir, feed_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = sorted(items, key=lambda item: int(item.get("mtime", 0)), reverse=True)[:MAX_MOBILE_SHARE_ITEMS]
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temp.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return kept


def append_mobile_share_items(
    items: list[dict],
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> list[dict]:
    with MOBILE_SHARE_FEED_LOCK:
        existing = read_mobile_share_feed(share_dir, feed_file)
        incoming_ids = {str(item.get("id", "")) for item in items}
        merged = list(items) + [item for item in existing if str(item.get("id", "")) not in incoming_ids]
        return write_mobile_share_feed(merged, share_dir, feed_file)


def list_shared_items(
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> list[dict]:
    share_dir = Path(share_dir)
    indexed = []
    indexed_names = set()
    for item in read_mobile_share_feed(share_dir, feed_file):
        item_type = str(item.get("type", ""))
        if item_type == "text" and str(item.get("text", "")).strip():
            indexed.append(item)
        elif item_type == "file":
            name = sanitize_upload_filename(str(item.get("name", "")))
            target = share_dir / name
            if name and target.is_file():
                indexed.append({**item, "name": name, "bytes": target.stat().st_size})
                indexed_names.add(name)
    for file_item in list_shared_files(share_dir):
        if file_item["name"] in indexed_names:
            continue
        indexed.append(
            {
                "id": f"legacy-file:{file_item['name']}",
                "type": "file",
                "name": file_item["name"],
                "bytes": file_item["bytes"],
                "mtime": file_item["mtime"],
                "content_type": mimetypes.guess_type(file_item["name"])[0] or "application/octet-stream",
            }
        )
    return sorted(indexed, key=lambda item: int(item.get("mtime", 0)), reverse=True)[:MAX_MOBILE_SHARE_ITEMS]


def resolve_shared_download(filename: str, share_dir: Path = MOBILE_SHARE_DIR) -> Path:
    original = str(filename or "").strip()
    if not original:
        raise ValueError("文件不存在")
    safe_name = sanitize_upload_filename(original)
    if safe_name != original:
        raise ValueError("非法文件名")
    root = share_dir.resolve()
    target = (share_dir / safe_name).resolve()
    if target.parent != root or not target.is_file():
        raise ValueError("文件不存在")
    return target


def share_uploaded_files(
    files: list[dict],
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> dict:
    now = history_now()
    entries = [
        {
            "id": f"web-file:{now}:{index}:{item['name']}",
            "type": "file",
            "name": str(item["name"]),
            "bytes": int(item.get("bytes", 0) or 0),
            "mtime": now,
            "content_type": str(item.get("content_type", "application/octet-stream")),
        }
        for index, item in enumerate(files)
    ]
    append_mobile_share_items(entries, share_dir, feed_file)
    return {"files": len(files), "items": list_shared_items(share_dir, feed_file)}


def publish_text_for_mobile_download(
    text: str,
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> dict:
    content = str(text or "")
    if not content.strip():
        raise ValueError("没有输入要发布的文字")
    if len(content) > MAX_TEXT_LENGTH:
        raise ValueError(f"文字过长，最多 {MAX_TEXT_LENGTH} 字")
    record = record_text_history(content, action="share")
    published = {
        "id": record["id"],
        "type": "text",
        "text": content,
        "chars": len(content),
        "mtime": int(record["ts"]),
    }
    append_mobile_share_items([published], share_dir, feed_file)
    return {"texts": 1, "items": list_shared_items(share_dir, feed_file), "published": [published]}


def publish_files_for_mobile_download(
    paths: list[Path | str],
    share_dir: Path = MOBILE_SHARE_DIR,
    feed_file: Path | None = None,
) -> dict:
    published = []
    for item in paths:
        source = Path(item).resolve()
        if not source.is_file():
            raise ValueError(f"文件不存在：{source}")
        target = unique_upload_path(share_dir, source.name)
        shutil.copy2(source, target)
        published.append(
            {
                "name": target.name,
                "path": str(target.resolve()),
                "bytes": target.stat().st_size,
                "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            }
        )
    if not published:
        raise ValueError("没有选择文件")
    record = record_file_history(published, action="share")
    now = int(record["ts"])
    entries = [
        {
            "id": f"{record['id']}:{index}",
            "type": "file",
            "name": item["name"],
            "bytes": item["bytes"],
            "mtime": now,
            "content_type": item["content_type"],
        }
        for index, item in enumerate(published)
    ]
    append_mobile_share_items(entries, share_dir, feed_file)
    return {"files": len(published), "items": list_shared_items(share_dir, feed_file), "published": published}


def resolve_local_update_file(filename: str, update_dir: Path | None = None) -> Path:
    update_dir = update_dir or active_local_update_source_dir()
    original = str(filename or "").strip()
    if not original:
        raise ValueError("更新文件不存在")
    safe_name = sanitize_upload_filename(original)
    if safe_name != original:
        raise ValueError("非法更新文件名")
    root = update_dir.resolve()
    target = (update_dir / safe_name).resolve()
    if target.parent != root or not target.is_file():
        raise ValueError("更新文件不存在")
    return target


def normalize_update_host_header(host_header: str) -> str:
    host = str(host_header or "").strip() or f"127.0.0.1:{DEFAULT_PORT}"
    host = host.split("/", 1)[0]
    if not re.fullmatch(r"[0-9A-Za-z.\-:\[\]]+(?::\d+)?", host):
        return f"127.0.0.1:{DEFAULT_PORT}"
    return host


def local_update_url_for_host(host_header: str, filename: str) -> str:
    host = normalize_update_host_header(host_header)
    return f"http://{host}/__updates__/{quote(filename, safe='')}"


def local_update_manifest_for_host(host_header: str, update_dir: Path | None = None) -> dict:
    update_dir = update_dir or active_local_update_source_dir()
    manifest_path = resolve_local_update_file("update.json", update_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    package_name = ""
    url_value = str(manifest.get("url", "")).strip()
    if url_value:
        parsed = urlparse(url_value)
        package_name = Path(unquote(parsed.path)).name
    if not package_name:
        packages = sorted(
            (path for path in update_dir.iterdir() if path.is_file() and path.suffix.lower() == ".exe"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if packages:
            package_name = packages[0].name
    if package_name:
        resolve_local_update_file(package_name, update_dir)
        manifest["url"] = local_update_url_for_host(host_header, package_name)
    return manifest


def json_response(handler, status: HTTPStatus, data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def text_response(
    handler,
    status: HTTPStatus,
    body: str,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def can_inline_shared_content(content_type: str) -> bool:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized in {"application/pdf", "text/plain"}:
        return True
    if normalized == "image/svg+xml":
        return False
    return normalized.startswith(("image/", "video/", "audio/"))


def file_response(handler, path: Path, inline: bool = False) -> None:
    data = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    disposition = "inline" if inline and can_inline_shared_content(content_type) else "attachment"
    handler.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(path.name)}")
    handler.end_headers()
    handler.wfile.write(data)


def html_page(access_key: str, server_name: str) -> str:
    safe_key = html.escape(access_key, quote=True)
    paper_bg = html.escape(paper_background_data_url(), quote=True)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>声笺</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #eef3f8;
      --panel: #ffffff;
      --panel-soft: rgba(255, 255, 255, 0.82);
      --text: #172033;
      --muted: #637083;
      --line: rgba(139, 154, 177, 0.28);
      --accent: #0f766e;
      --accent-strong: #0b5d56;
      --secondary: #263445;
      --danger: #b42318;
      --ok: #137333;
      --blue: #2563eb;
      --warm: #f59e0b;
      --shadow: 0 24px 70px rgba(15, 23, 42, 0.14);
      --soft-shadow: 0 10px 28px rgba(15, 23, 42, 0.10);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; color: var(--text); }}
    body {{
      position: relative; overflow-x: hidden;
      padding: max(12px, env(safe-area-inset-top)) 12px max(14px, env(safe-area-inset-bottom));
      background:
        radial-gradient(circle at 14% 4%, rgba(15,118,110,0.18), transparent 30%),
        radial-gradient(circle at 88% 78%, rgba(37,99,235,0.16), transparent 34%),
        linear-gradient(135deg, rgba(226, 239, 255, 0.86), rgba(245, 247, 251, 0.92) 48%, rgba(229, 247, 242, 0.9)),
        #eef3f8;
    }}
    .visual-backdrop {{
      position: fixed; inset: -22px; z-index: -1; pointer-events: none; opacity: 0.76;
      background-image:
        linear-gradient(135deg, rgba(248,250,252,0.82), rgba(240,253,250,0.60)),
        url("{paper_bg}"),
        linear-gradient(rgba(15, 23, 42, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15, 23, 42, 0.045) 1px, transparent 1px);
      background-size: cover, cover, 44px 44px, 44px 44px;
      background-position: center, center, 0 0, 0 0;
      transform: translateZ(0);
      animation: paperDrift 18s ease-in-out infinite alternate;
    }}
    .visual-backdrop::after {{
      content: ""; position: absolute; inset: 0;
      background:
        linear-gradient(120deg, rgba(255,255,255,0.82), transparent 34%, rgba(15,118,110,0.10) 72%, transparent),
        radial-gradient(circle at 50% 30%, rgba(255,255,255,0.34), transparent 36%);
      animation: paperLightSweep 8s ease-in-out infinite alternate;
    }}
    .visual-backdrop::before {{
      content: ""; position: absolute; left: -8%; right: -8%; top: 42%; height: 160px;
      background:
        radial-gradient(ellipse at center, rgba(15,118,110,0.18), transparent 62%),
        repeating-linear-gradient(90deg, transparent 0 18px, rgba(15,118,110,0.12) 18px 20px);
      filter: blur(12px); opacity: 0.46; transform: rotate(-5deg);
      animation: waveformSlide 7s ease-in-out infinite alternate;
    }}
    @keyframes paperDrift {{
      from {{ transform: translate3d(-7px, -5px, 0) scale(1.018); }}
      to {{ transform: translate3d(9px, 7px, 0) scale(1.035); }}
    }}
    @keyframes paperLightSweep {{
      from {{ opacity: .76; transform: translateX(-10px); }}
      to {{ opacity: .94; transform: translateX(12px); }}
    }}
    @keyframes waveformSlide {{
      from {{ transform: translateX(-16px) rotate(-5deg); opacity: .35; }}
      to {{ transform: translateX(18px) rotate(-5deg); opacity: .52; }}
    }}
    @keyframes appShellIn {{
      0% {{ opacity: 0; }}
      100% {{ opacity: 1; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .visual-backdrop, .visual-backdrop::before, .visual-backdrop::after, .app-shell, button, .tool-card {{ animation: none; transition: none; }}
    }}
    .app-shell {{ width: min(820px, 100%); margin: 0 auto; display: grid; gap: 10px; animation: appShellIn .22s ease-out both; }}
    .hero-copy {{ min-width: 0; }}
    .eyebrow {{ margin: 0 0 7px; color: var(--accent); font-size: 12px; font-weight: 800; letter-spacing: 0; }}
    h1 {{ margin: 0; font-size: 30px; line-height: 1.12; font-weight: 820; letter-spacing: 0; }}
    .subtitle {{ max-width: 520px; margin: 9px 0 0; color: var(--muted); font-size: 14px; line-height: 1.6; }}
    section {{ background: var(--panel-soft); border: 1px solid rgba(255,255,255,0.82); border-radius: 24px; box-shadow: var(--shadow); padding: 16px; backdrop-filter: blur(18px); }}
    .tool-card {{ display: grid; gap: 11px; }}
    .input-drawer {{ display: grid; gap: 9px; }}
    .drawer-summary {{
      display: flex; align-items: flex-end; justify-content: space-between; gap: 12px;
    }}
    .editor-head {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }}
    .editor-title {{ display: grid; gap: 3px; }}
    .editor-title strong {{ font-size: 16px; line-height: 1.2; }}
    .editor-title span {{ color: var(--muted); font-size: 13px; line-height: 1.4; }}
    .mode-pill {{ flex: 0 0 auto; border: 1px solid rgba(15,118,110,0.16); border-radius: 999px; padding: 7px 10px; background: rgba(232, 249, 245, 0.88); color: var(--accent-strong); font-size: 12px; font-weight: 760; }}
    textarea {{
      width: 100%; min-height: 148px; resize: none; border: 1px solid rgba(137, 153, 175, 0.30);
      border-radius: 18px; padding: 14px; color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 16px; line-height: 1.68;
      white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; text-align: left;
      -webkit-text-fill-color: var(--text); caret-color: var(--accent-strong);
      -webkit-user-select: text; user-select: text; -webkit-touch-callout: default; touch-action: manipulation;
      outline: none; background: rgba(255,255,255,0.92);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.9);
    }}
    .compact-input {{ min-height: 148px; }}
    textarea:focus {{ border-color: rgba(15,118,110,0.72); box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.13); background: #fff; }}
    .input-drawer.input-expanded .compact-input {{ min-height: 260px; }}
    .quick-actions {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; }}
    .mobile-tool-switches {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .tool-toggle {{
      min-width: 0; min-height: 40px; color: var(--accent-strong); background: rgba(240,253,250,0.88);
      border: 1px solid rgba(15,118,110,0.18); box-shadow: none;
    }}
    .tool-toggle.active {{ color: #fff; background: var(--secondary); border-color: transparent; }}
    .collapsible-panel {{ display: grid; gap: 10px; }}
    .collapsible-panel[hidden] {{ display: none; }}
    .prompt-tools {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
    .file-tools {{
      display: grid; gap: 10px; border: 1px solid rgba(137,153,175,0.20);
      border-radius: 18px; padding: 11px; background: rgba(255,255,255,0.58);
    }}
    .file-tools-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--muted); font-size: 13px; }}
    .file-tools-head strong {{ color: var(--text); font-size: 15px; }}
    .file-row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: stretch; }}
    .file-input-native {{
      position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
      clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
    }}
    .file-dropzone {{
      display: grid; gap: 8px; min-height: 88px; border: 1px dashed rgba(15,118,110,0.38);
      border-radius: 16px; padding: 13px; background: rgba(255,255,255,0.70);
      color: var(--text); cursor: pointer; transition: border-color .16s ease, background .16s ease, transform .16s ease;
    }}
    .file-dropzone:hover, .file-dropzone:focus-visible, .file-dropzone.drag-over {{
      border-color: rgba(15,118,110,0.72); background: rgba(240,253,250,0.78); transform: translateY(-1px);
      outline: none;
    }}
    .file-dropzone-main {{ display: flex; align-items: center; gap: 10px; min-width: 0; }}
    .file-icon {{
      width: 36px; height: 36px; border-radius: 12px; display: inline-flex; align-items: center; justify-content: center;
      background: rgba(15,118,110,0.12); color: var(--accent-strong); font-size: 18px; flex: 0 0 auto;
    }}
    .file-copy {{ display: grid; gap: 3px; min-width: 0; }}
    .file-copy strong {{ font-size: 15px; line-height: 1.2; }}
    .file-copy span, .file-summary {{ color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .file-list {{ display: flex; flex-wrap: wrap; gap: 6px; min-height: 22px; }}
    .file-chip {{
      max-width: 100%; display: inline-flex; align-items: center; border: 1px solid rgba(137,153,175,0.22);
      border-radius: 999px; padding: 4px 9px; background: rgba(255,255,255,0.82);
      color: var(--text); font-size: 12px; line-height: 1.2;
    }}
    .file-chip span {{ min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .file-action-row {{
      display: flex; flex-wrap: wrap; gap: 8px; align-content: flex-start; justify-content: flex-end;
    }}
    .file-action-row button {{
      min-width: 96px; min-height: 38px; padding-left: 13px; padding-right: 13px; font-size: 13px;
    }}
    .mobile-file-actions {{ display: none; grid-template-columns: 1fr 1fr; gap: 9px; }}
    .mobile-file-actions button {{ min-width: 0; min-height: 54px; border-radius: 16px; }}
    .upload-progress {{ display: grid; gap: 7px; padding: 10px 12px; border: 1px solid rgba(15,118,110,0.22); border-radius: 14px; background: rgba(240,253,250,0.86); }}
    .upload-progress[hidden] {{ display: none; }}
    .upload-progress-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 12px; }}
    .upload-progress-head strong {{ color: var(--accent-strong); font-size: 13px; font-variant-numeric: tabular-nums; }}
    .upload-progress-track {{ height: 8px; overflow: hidden; border-radius: 999px; background: rgba(15,118,110,0.13); }}
    .upload-progress-bar {{ display: block; width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #0f766e, #20b79d); transition: width .12s linear; }}
    .shared-files-panel {{
      display: grid; gap: 8px; border-top: 1px solid rgba(137,153,175,0.18); padding-top: 10px;
    }}
    .shared-files-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
    .shared-files-head strong {{ font-size: 14px; color: var(--text); }}
    .shared-files-list {{ display: grid; gap: 8px; }}
    .shared-text-item, .shared-file-link {{
      width: 100%; min-width: 0; min-height: 0; margin: 0; border: 1px solid rgba(137,153,175,0.20);
      border-radius: 14px; padding: 10px 12px; color: var(--text); background: rgba(255,255,255,0.78);
      box-shadow: none; text-align: left; text-decoration: none; transform: none;
    }}
    .shared-text-item {{ display: grid; gap: 7px; justify-items: stretch; }}
    .shared-text-item:hover, .shared-file-link:hover {{
      border-color: rgba(15,118,110,0.45); background: rgba(240,253,250,0.90); box-shadow: none; transform: none;
    }}
    .shared-text-content {{
      display: block; max-height: 8.1em; overflow: hidden;
      white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; text-align: left;
      font-size: 15px; font-weight: 600; line-height: 1.62;
    }}
    .shared-item-meta {{ color: var(--muted); font-size: 12px; font-weight: 500; }}
    .shared-file-link {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; }}
    .shared-file-copy {{ display: grid; gap: 4px; min-width: 0; }}
    .shared-file-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; font-weight: 700; }}
    .shared-file-link em {{ color: var(--muted); font-style: normal; font-size: 12px; white-space: nowrap; }}
    body[data-file-mode="mobile-clipboard"] .file-tools-head span {{ display: none; }}
    body[data-file-mode="mobile-clipboard"] .file-action-row {{ display: none; }}
    body[data-file-mode="mobile-clipboard"] .mobile-file-actions {{ display: grid; }}
    body[data-file-mode="mobile-clipboard"] .file-dropzone {{
      display: none;
    }}
    body[data-file-mode="mobile-clipboard"] .file-copy span {{ display: none; }}
    .prompt-workbench {{
      display: none; gap: 12px; border: 1px solid rgba(37, 99, 235, 0.12); border-radius: 20px;
      padding: 13px; background: rgba(248, 250, 252, 0.82);
    }}
    .prompt-workbench.active {{ display: grid; }}
    .prompt-row {{ display: grid; gap: 6px; }}
    .prompt-row label {{ color: var(--muted); font-size: 13px; font-weight: 700; justify-content: flex-start; }}
    .prompt-question {{ margin: 0; color: var(--text); font-size: 15px; line-height: 1.55; }}
    .prompt-answer, .prompt-candidate {{ min-height: 82px; font-size: 15px; line-height: 1.5; }}
    .prompt-candidate {{ min-height: 120px; background: #fff; }}
    .prompt-actions {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }}
    .prompt-actions button {{ min-width: 104px; min-height: 38px; font-size: 14px; }}
    .action-row {{ display: inline-flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }}
    .send-panel {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; border-top: 1px solid rgba(137,153,175,0.20); padding-top: 2px; }}
    .option-grid {{ display: flex; flex-wrap: wrap; gap: 10px 14px; color: var(--muted); font-size: 14px; }}
    .checks {{ display: contents; }}
    label {{ display: inline-flex; align-items: center; gap: 7px; user-select: none; }}
    input[type="checkbox"] {{ width: 18px; height: 18px; accent-color: var(--accent); }}
    input[type="number"], select {{
      width: 70px; min-height: 36px; border: 1px solid rgba(137,153,175,0.34); border-radius: 12px;
      padding: 6px 9px; color: var(--text); background: rgba(255,255,255,0.88);
      font: 14px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; outline: none;
    }}
    select {{ width: auto; min-width: 136px; }}
    button {{
      display: inline-flex; align-items: center; justify-content: center; gap: 7px;
      min-width: 112px; min-height: 42px; border: 0; border-radius: 14px; padding: 0 17px;
      color: #fff; background: var(--accent); box-shadow: 0 10px 22px rgba(15, 118, 110, 0.20);
      font-size: 15px; font-weight: 800; cursor: pointer; transition: transform .16s ease, box-shadow .16s ease, background .16s ease;
    }}
    button:hover {{ transform: translateY(-1px); box-shadow: 0 14px 28px rgba(15, 118, 110, 0.25); }}
    button.secondary, .ghost-button {{ background: var(--secondary); box-shadow: 0 10px 22px rgba(38, 52, 69, 0.16); }}
    button.secondary:hover, .ghost-button:hover {{ box-shadow: 0 14px 28px rgba(38, 52, 69, 0.20); }}
    .primary-action {{ min-width: 132px; min-height: 48px; background: linear-gradient(135deg, var(--accent), var(--accent-strong)); }}
    button:disabled {{ background: #95a3b4; cursor: not-allowed; }}
    button:disabled:hover {{ transform: none; box-shadow: none; }}
    .message {{ min-height: 22px; color: var(--muted); font-size: 14px; line-height: 1.45; }}
    .message.ok {{ color: var(--ok); }}
    .message.err {{ color: var(--danger); }}
    @media (max-width: 560px) {{
      body {{ padding-left: 10px; padding-right: 10px; }}
      h1 {{ font-size: 26px; }}
      section {{ padding: 12px; border-radius: 20px; }}
      textarea, .compact-input {{ min-height: 128px; font-size: 17px; }}
      .input-drawer.input-expanded .compact-input {{ min-height: 238px; }}
      .drawer-summary {{ flex-direction: column; align-items: stretch; }}
      .drawer-summary .ghost-button {{ align-self: flex-start; flex: 0 0 auto; }}
      .editor-head, .quick-actions, .send-panel, .file-row {{ grid-template-columns: 1fr; }}
      .editor-head {{ align-items: flex-start; }}
      .option-grid, .prompt-tools, .action-row, .prompt-actions {{ width: 100%; }}
      button {{ flex: 1 1 138px; min-height: 46px; }}
    }}
  </style>
</head>
<body>
  <div class="visual-backdrop paper-stage" aria-hidden="true"></div>
  <main class="app-shell">
    <section class="tool-card">
      <div id="inputDrawer" class="input-drawer">
        <div class="drawer-summary editor-head">
          <div class="editor-title">
            <strong>输入内容</strong>
            <span>先写入或语音输入，再选择润色、翻译或发送。</span>
          </div>
          <button id="toggleInputSize" type="button" class="ghost-button">展开输入框</button>
        </div>
        <textarea id="text" class="compact-input" placeholder="点这里，用手机豆包输入法语音转文字，可以先中译英，再发送到电脑当前输入框。"></textarea>
      </div>
      <div class="mobile-tool-switches">
        <button id="toggleAssistTools" type="button" class="tool-toggle">辅助工具</button>
        <button id="toggleFileTools" type="button" class="tool-toggle">文件与下载</button>
      </div>
      <div id="assistTools" class="quick-actions collapsible-panel" hidden>
        <div class="prompt-tools">
          <span class="mode-pill">润色区</span>
          <label>润色类型
            <select id="promptMode">
              <option value="auto" selected>自动识别</option>
              <option value="dialog">对话提示词</option>
              <option value="raw">原始提示词</option>
              <option value="image">图像提示词</option>
              <option value="code">代码提示词</option>
              <option value="writing">写作提示词</option>
            </select>
          </label>
          <button id="enrichPrompt" type="button" class="secondary">润色提示词</button>
        </div>
        <div class="action-row">
          <button id="translate" type="button" class="ghost-button">中译英</button>
        </div>
      </div>
      <div id="promptWorkbench" class="prompt-workbench" aria-live="polite">
        <div id="promptQuestionBlock" class="prompt-row" hidden>
          <label for="promptAnswer">需要补充</label>
          <p id="promptQuestion" class="prompt-question"></p>
          <textarea id="promptAnswer" class="prompt-answer" placeholder="在这里回答模型的问题，主输入框不会被修改。"></textarea>
          <div class="prompt-actions">
            <button id="sendPromptAnswer" type="button" class="secondary">继续润色</button>
          </div>
        </div>
        <div id="promptCandidateBlock" class="prompt-row" hidden>
          <label for="promptCandidate">润色结果</label>
          <textarea id="promptCandidate" class="prompt-candidate" readonly></textarea>
          <div class="prompt-actions">
            <button id="clearPromptWorkbench" type="button" class="secondary">清空结果</button>
            <button id="acceptPromptResult" type="button">采用结果</button>
          </div>
        </div>
      </div>
      <div class="send-panel">
        <div class="option-grid">
          <div class="checks">
            <label><input id="clearAfterSend" type="checkbox" checked>发送后清空</label>
            <label><input id="pressEnter" type="checkbox" checked>发送后回车</label>
          </div>
        </div>
        <div class="action-row">
          <button id="send" type="button" class="primary-action">发送</button>
        </div>
      </div>
      <div id="message" class="message"></div>
      <div id="fileToolsPanel" class="file-tools collapsible-panel" hidden>
        <div class="file-tools-head">
          <strong id="fileToolsTitle">文件剪贴板</strong>
          <span id="fileToolsHint">图片、视频、Word、PDF、小文件</span>
        </div>
        <div class="file-row">
          <input id="fileInput" class="file-input-native" type="file" multiple>
          <input id="imageInput" class="file-input-native" type="file" multiple accept=".jpg,.jpeg,.png,.webp,.gif,.heic,.heif,.mp4,.mov,.m4v,.webm,.mkv,.avi,.wmv,.3gp,.3gpp,image/jpeg,image/png,image/webp,image/gif,image/heic,image/heif,video/mp4,video/quicktime,video/x-m4v,video/webm,video/x-matroska,video/x-msvideo,video/x-ms-wmv,video/3gpp">
          <input id="documentInput" class="file-input-native" type="file" multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.zip,.rar,.7z,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document">
          <div id="fileDropzone" class="file-dropzone" role="button" tabindex="0" aria-label="选择或拖放文件">
            <div class="file-dropzone-main">
              <span class="file-icon" aria-hidden="true">+</span>
              <div class="file-copy">
                <strong id="fileDropzoneTitle">点按选择，或把文件拖到这里</strong>
                <span id="fileDropzoneHint">最多 8 个文件，视频时长不限。</span>
              </div>
            </div>
            <div id="fileSummary" class="file-summary">未选择文件</div>
            <div id="fileList" class="file-list" aria-live="polite"></div>
          </div>
          <div class="mobile-file-actions">
            <button id="chooseImages" type="button" class="ghost-button">选图库媒体</button>
            <button id="chooseDocuments" type="button" class="ghost-button">选文档/文件</button>
          </div>
          <div class="file-action-row">
            <button id="chooseFiles" type="button" class="ghost-button">选择文件</button>
            <button id="clearFiles" type="button" class="ghost-button">清空</button>
            <button id="uploadFiles" type="button" class="ghost-button">放入剪贴板</button>
          </div>
        </div>
        <div id="uploadProgress" class="upload-progress" role="progressbar" aria-label="文件上传进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" hidden>
          <div class="upload-progress-head"><span id="uploadProgressText">准备上传</span><strong id="uploadProgressPercent">0%</strong></div>
          <div class="upload-progress-track"><span id="uploadProgressBar" class="upload-progress-bar"></span></div>
        </div>
        <div id="sharedFilesPanel" class="shared-files-panel" hidden>
          <div class="shared-files-head">
            <strong>来自电脑</strong>
            <button id="refreshSharedFiles" type="button" class="ghost-button">刷新</button>
          </div>
          <div id="sharedFilesList" class="shared-files-list" aria-live="polite"></div>
        </div>
      </div>
    </section>

  </main>

  <script>
    const ACCESS_KEY = "{safe_key}";
    const textEl = document.getElementById("text");
    const inputDrawerEl = document.getElementById("inputDrawer");
    const toggleInputSizeBtn = document.getElementById("toggleInputSize");
    const toggleAssistToolsBtn = document.getElementById("toggleAssistTools");
    const toggleFileToolsBtn = document.getElementById("toggleFileTools");
    const assistToolsEl = document.getElementById("assistTools");
    const fileToolsPanelEl = document.getElementById("fileToolsPanel");
    const translateBtn = document.getElementById("translate");
    const enrichPromptBtn = document.getElementById("enrichPrompt");
    const promptModeEl = document.getElementById("promptMode");
    const promptWorkbenchEl = document.getElementById("promptWorkbench");
    const promptQuestionBlockEl = document.getElementById("promptQuestionBlock");
    const promptQuestionEl = document.getElementById("promptQuestion");
    const promptAnswerEl = document.getElementById("promptAnswer");
    const promptCandidateBlockEl = document.getElementById("promptCandidateBlock");
    const promptCandidateEl = document.getElementById("promptCandidate");
    const sendPromptAnswerBtn = document.getElementById("sendPromptAnswer");
    const clearPromptWorkbenchBtn = document.getElementById("clearPromptWorkbench");
    const acceptPromptResultBtn = document.getElementById("acceptPromptResult");
    const sendBtn = document.getElementById("send");
    const fileInputEl = document.getElementById("fileInput");
    const imageInputEl = document.getElementById("imageInput");
    const documentInputEl = document.getElementById("documentInput");
    const fileDropzoneEl = document.getElementById("fileDropzone");
    const fileToolsTitleEl = document.getElementById("fileToolsTitle");
    const fileToolsHintEl = document.getElementById("fileToolsHint");
    const fileDropzoneTitleEl = document.getElementById("fileDropzoneTitle");
    const fileDropzoneHintEl = document.getElementById("fileDropzoneHint");
    const chooseFilesBtn = document.getElementById("chooseFiles");
    const chooseImagesBtn = document.getElementById("chooseImages");
    const chooseDocumentsBtn = document.getElementById("chooseDocuments");
    const clearFilesBtn = document.getElementById("clearFiles");
    const fileSummaryEl = document.getElementById("fileSummary");
    const fileListEl = document.getElementById("fileList");
    const uploadFilesBtn = document.getElementById("uploadFiles");
    const uploadProgressEl = document.getElementById("uploadProgress");
    const uploadProgressTextEl = document.getElementById("uploadProgressText");
    const uploadProgressPercentEl = document.getElementById("uploadProgressPercent");
    const uploadProgressBarEl = document.getElementById("uploadProgressBar");
    const sharedFilesPanelEl = document.getElementById("sharedFilesPanel");
    const sharedFilesListEl = document.getElementById("sharedFilesList");
    const refreshSharedFilesBtn = document.getElementById("refreshSharedFiles");
    const messageEl = document.getElementById("message");
    const clearAfterSendEl = document.getElementById("clearAfterSend");
    const pressEnterEl = document.getElementById("pressEnter");
    let currentPromptOriginal = "";
    let currentPromptCandidate = "";
    let selectedFiles = [];
    const isCoarsePointer = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    const isLocalHost = ["127.0.0.1", "localhost", "::1"].includes(window.location.hostname);

    function setMessage(text, kind = "") {{
      messageEl.textContent = text;
      messageEl.className = "message" + (kind ? " " + kind : "");
    }}

    function setUploadProgress(percent, loaded = 0, total = 0) {{
      const value = Math.max(0, Math.min(100, Math.round(percent)));
      uploadProgressEl.hidden = false;
      uploadProgressEl.setAttribute("aria-valuenow", String(value));
      uploadProgressBarEl.style.width = `${{value}}%`;
      uploadProgressPercentEl.textContent = `${{value}}%`;
      uploadProgressTextEl.textContent = total > 0
        ? `已上传 ${{formatFileSize(loaded)}} / ${{formatFileSize(total)}}`
        : "正在上传...";
    }}

    function uploadFormWithProgress(url, form) {{
      setUploadProgress(0);
      return new Promise((resolve, reject) => {{
        const xhr = new XMLHttpRequest();
        const separator = url.includes("?") ? "&" : "?";
        xhr.open("POST", `${{url}}${{separator}}key=${{encodeURIComponent(ACCESS_KEY)}}`);
        xhr.responseType = "json";
        xhr.upload.addEventListener("progress", (event) => {{
          if (event.lengthComputable) setUploadProgress((event.loaded / event.total) * 100, event.loaded, event.total);
        }});
        xhr.addEventListener("load", () => {{
          const data = xhr.response || {{}};
          if (xhr.status < 200 || xhr.status >= 300 || !data.ok) {{
            reject(new Error(data.error || `文件上传失败（HTTP ${{xhr.status}}）`));
            return;
          }}
          setUploadProgress(100, 1, 1);
          uploadProgressTextEl.textContent = "上传完成";
          resolve(data);
        }});
        xhr.addEventListener("error", () => reject(new Error("上传连接中断，请检查 Wi-Fi 后重试。")));
        xhr.addEventListener("abort", () => reject(new Error("上传已取消。")));
        xhr.send(form);
      }});
    }}

    function toggleInputSize() {{
      inputDrawerEl.classList.toggle("input-expanded");
      const expanded = inputDrawerEl.classList.contains("input-expanded");
      toggleInputSizeBtn.textContent = expanded ? "收起输入框" : "展开输入框";
      textEl.focus();
    }}

    function setPanelVisible(panel, button, visible) {{
      panel.hidden = !visible;
      button.classList.toggle("active", visible);
      button.setAttribute("aria-expanded", visible ? "true" : "false");
    }}

    function togglePanel(panel, button) {{
      setPanelVisible(panel, button, panel.hidden);
    }}

    async function translateText() {{
      const text = textEl.value.trim();
      if (!text) {{
        setMessage("没有可翻译的文字。", "err");
        textEl.focus();
        return;
      }}
      translateBtn.disabled = true;
      setMessage("翻译中...");
      try {{
        const url = "https://api.mymemory.translated.net/get?q="
          + encodeURIComponent(text)
          + "&langpair=zh-CN|en";
        const res = await fetch(url, {{ cache: "no-store" }});
        const data = await res.json();
        const translated = data && data.responseData && data.responseData.translatedText;
        if (!res.ok || !translated) throw new Error(data.responseDetails || "翻译失败");
        textEl.value = translated;
        setMessage("已转换为英文。", "ok");
      }} catch (err) {{
        setMessage(String(err.message || err), "err");
      }} finally {{
        translateBtn.disabled = false;
        textEl.focus();
      }}
    }}

    function formatFileSize(bytes) {{
      const units = ["B", "KB", "MB", "GB"];
      let size = Number(bytes) || 0;
      let unitIndex = 0;
      while (size >= 1024 && unitIndex < units.length - 1) {{
        size = size / 1024;
        unitIndex += 1;
      }}
      return `${{size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)}} ${{units[unitIndex]}}`;
    }}

    function isMobileClipboardMode() {{
      return isCoarsePointer && !isLocalHost;
    }}

    function isLocalShareMode() {{
      return isLocalHost;
    }}

    function shouldLoadSharedFiles() {{
      return true;
    }}

    function applyFileMode() {{
      if (isMobileClipboardMode()) {{
        document.body.dataset.fileMode = "mobile-clipboard";
        fileToolsTitleEl.textContent = "文件到电脑";
        fileToolsHintEl.textContent = "";
        fileDropzoneTitleEl.textContent = "从图库或文件选择";
        fileDropzoneHintEl.textContent = "支持图片、视频和文档，点击发送后粘贴到电脑。";
        uploadFilesBtn.textContent = "选择后自动上传";
        return;
      }}
      if (isLocalShareMode()) {{
        document.body.dataset.fileMode = "local-share";
        fileToolsTitleEl.textContent = "传到手机";
        fileToolsHintEl.textContent = "电脑文件发布后，手机打开局域网地址可下载。";
        fileDropzoneTitleEl.textContent = "选择电脑文件，发布给手机下载";
        fileDropzoneHintEl.textContent = "最多 8 个文件，视频时长不限。";
        uploadFilesBtn.textContent = "发布给手机下载";
        return;
      }}
      document.body.dataset.fileMode = "desktop-clipboard";
      fileToolsTitleEl.textContent = "文件剪贴板";
      fileToolsHintEl.textContent = "图片、视频、Word、PDF、小文件";
      fileDropzoneTitleEl.textContent = "点按选择，或把文件拖到这里";
      fileDropzoneHintEl.textContent = "最多 8 个文件，视频时长不限。";
      uploadFilesBtn.textContent = "放入剪贴板";
    }}

    function renderSelectedFiles() {{
      fileListEl.innerHTML = "";
      if (!selectedFiles.length) {{
        fileSummaryEl.textContent = "未选择文件";
        clearFilesBtn.disabled = true;
        return;
      }}
      const totalBytes = selectedFiles.reduce((sum, file) => sum + (file.size || 0), 0);
      fileSummaryEl.textContent = `已选择 ${{selectedFiles.length}} 个文件，共 ${{formatFileSize(totalBytes)}}`;
      clearFilesBtn.disabled = false;
      for (const file of selectedFiles.slice(0, 6)) {{
        const chip = document.createElement("div");
        chip.className = "file-chip";
        const label = document.createElement("span");
        label.textContent = `${{file.name}} · ${{formatFileSize(file.size)}}`;
        chip.title = label.textContent;
        chip.appendChild(label);
        fileListEl.appendChild(chip);
      }}
      if (selectedFiles.length > 6) {{
        const chip = document.createElement("div");
        chip.className = "file-chip";
        chip.textContent = `另有 ${{selectedFiles.length - 6}} 个文件`;
        fileListEl.appendChild(chip);
      }}
    }}

    function setSelectedFiles(files) {{
      selectedFiles = Array.from(files || []);
      renderSelectedFiles();
      if (isMobileClipboardMode() && selectedFiles.length) {{
        setPanelVisible(fileToolsPanelEl, toggleFileToolsBtn, true);
        setMessage("文件已加入待发送，点击发送后粘贴到电脑。", "ok");
      }}
    }}

    function clearSelectedFiles() {{
      selectedFiles = [];
      fileInputEl.value = "";
      imageInputEl.value = "";
      documentInputEl.value = "";
      renderSelectedFiles();
    }}

    async function openFilePicker() {{
      if (isMobileClipboardMode()) {{
        imageInputEl.click();
        return;
      }}
      if ("showOpenFilePicker" in window) {{
        try {{
          const handles = await window.showOpenFilePicker({{ multiple: true }});
          const files = await Promise.all(handles.map((handle) => handle.getFile()));
          setSelectedFiles(files);
          return;
        }} catch (err) {{
          if (err && err.name === "AbortError") return;
          setMessage(String(err.message || err), "err");
        }}
      }}
      fileInputEl.click();
    }}

    function currentFileEndpoint() {{
      return isLocalShareMode() ? "/files/share" : "/files/clipboard";
    }}

    async function loadSharedFiles() {{
      if (!shouldLoadSharedFiles()) {{
        sharedFilesPanelEl.hidden = true;
        sharedFilesListEl.textContent = "";
        return;
      }}
      try {{
        const res = await fetch(`/files/shared?key=${{encodeURIComponent(ACCESS_KEY)}}`, {{ cache: "no-store" }});
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "文件列表读取失败");
        renderSharedItems(data.items || data.files || []);
      }} catch (err) {{
        sharedFilesPanelEl.hidden = false;
        sharedFilesListEl.textContent = String(err.message || err);
      }}
    }}

    function formatSharedTime(timestamp) {{
      const date = new Date((Number(timestamp) || 0) * 1000);
      if (!Number.isFinite(date.getTime()) || date.getTime() <= 0) return "";
      return date.toLocaleString([], {{ month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }});
    }}

    async function copySharedText(text) {{
      try {{
        await navigator.clipboard.writeText(text);
      }} catch (_err) {{
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }}
      setMessage("文字已复制。", "ok");
    }}

    function renderSharedItems(items) {{
      sharedFilesListEl.innerHTML = "";
      if (!items.length) {{
        sharedFilesPanelEl.hidden = false;
        sharedFilesListEl.textContent = "电脑发布的文字和文件会显示在这里。";
        return;
      }}
      sharedFilesPanelEl.hidden = false;
      for (const item of items.slice(0, 30)) {{
        if (item.type === "text") {{
          const button = document.createElement("button");
          button.type = "button";
          button.className = "shared-text-item";
          button.setAttribute("aria-label", "复制这条文字");
          const content = document.createElement("span");
          content.className = "shared-text-content";
          content.textContent = item.text || "";
          const meta = document.createElement("small");
          meta.className = "shared-item-meta";
          meta.textContent = `文字 · ${{Number(item.chars) || String(item.text || "").length}} 字 · ${{formatSharedTime(item.mtime)}} · 点击复制`;
          button.appendChild(content);
          button.appendChild(meta);
          button.addEventListener("click", () => copySharedText(String(item.text || "")));
          sharedFilesListEl.appendChild(button);
          continue;
        }}
        const file = item;
        const link = document.createElement("a");
        link.className = "shared-file-link";
        link.href = `/files/download?key=${{encodeURIComponent(ACCESS_KEY)}}&file=${{encodeURIComponent(file.name)}}`;
        link.target = "_blank";
        link.rel = "noopener";
        const copy = document.createElement("span");
        copy.className = "shared-file-copy";
        const name = document.createElement("span");
        name.className = "shared-file-name";
        name.textContent = file.name;
        const meta = document.createElement("small");
        meta.className = "shared-item-meta";
        meta.textContent = `${{file.content_type || "文件"}} · ${{formatSharedTime(file.mtime)}} · 点击打开`;
        copy.appendChild(name);
        copy.appendChild(meta);
        const size = document.createElement("em");
        size.textContent = formatFileSize(file.bytes);
        link.appendChild(copy);
        link.appendChild(size);
        sharedFilesListEl.appendChild(link);
      }}
    }}

    async function uploadFilesToClipboard() {{
      const files = Array.from(selectedFiles || []);
      if (!files.length) {{
        setMessage(isLocalShareMode() ? "请先选择要发布给手机的文件。" : "请先选择要放入剪贴板的文件。", "err");
        return;
      }}
      uploadFilesBtn.disabled = true;
      setMessage(isLocalShareMode() ? "正在发布给手机下载..." : "正在上传到电脑剪贴板...");
      try {{
        const form = new FormData();
        form.append("key", ACCESS_KEY);
        for (const file of files) form.append("files", file, file.name);
        const data = await uploadFormWithProgress(currentFileEndpoint(), form);
        const count = data.result && data.result.files ? data.result.files : files.length;
        if (isLocalShareMode()) {{
          setMessage(`已发布 ${{count}} 个文件，手机可在下载区获取。`, "ok");
          await loadSharedFiles();
        }} else {{
          setMessage(`已将 ${{count}} 个文件放入电脑剪贴板。`, "ok");
        }}
        clearSelectedFiles();
      }} catch (err) {{
        setMessage(String(err.message || err), "err");
      }} finally {{
        uploadFilesBtn.disabled = false;
      }}
    }}

    async function uploadFilesToPaste() {{
      const files = Array.from(selectedFiles || []);
      if (!files.length) {{
        setMessage("请先选择要发送的文件。", "err");
        return;
      }}
      sendBtn.disabled = true;
      setMessage(files.length > 1 ? "正在逐个粘贴文件..." : "正在粘贴文件...");
      try {{
        const form = new FormData();
        form.append("key", ACCESS_KEY);
        for (const file of files) form.append("files", file, file.name);
        const data = await uploadFormWithProgress("/files/paste", form);
        const count = data.result && data.result.files ? data.result.files : files.length;
        setMessage(`已逐个粘贴 ${{count}} 个文件到电脑。`, "ok");
        clearSelectedFiles();
      }} catch (err) {{
        setMessage(String(err.message || err), "err");
      }} finally {{
        sendBtn.disabled = false;
      }}
    }}

    function clearPromptWorkbench() {{
      currentPromptOriginal = "";
      currentPromptCandidate = "";
      promptWorkbenchEl.classList.remove("active");
      promptQuestionBlockEl.hidden = true;
      promptCandidateBlockEl.hidden = true;
      promptQuestionEl.textContent = "";
      promptAnswerEl.value = "";
      promptCandidateEl.value = "";
    }}

    function renderPromptWorkbench(result) {{
      promptWorkbenchEl.classList.add("active");
      promptQuestionBlockEl.hidden = true;
      promptCandidateBlockEl.hidden = true;
      promptQuestionEl.textContent = "";
      promptCandidateEl.value = "";
      currentPromptCandidate = "";

      if (result.action === "question" && result.question) {{
        promptQuestionEl.textContent = result.question;
        promptQuestionBlockEl.hidden = false;
        promptAnswerEl.value = "";
        promptAnswerEl.focus();
        setMessage(`需要补充 1 个信息，再生成「${{result.label}}」。`, "ok");
        return;
      }}

      currentPromptCandidate = result.candidate || result.text || "";
      promptCandidateEl.value = currentPromptCandidate;
      promptCandidateBlockEl.hidden = false;
      acceptPromptResultBtn.disabled = !currentPromptCandidate.trim();
      setMessage(`已生成「${{result.label}}」候选结果，确认后可采用。`, "ok");
    }}

    async function requestPromptEnrichment(answer = "") {{
      const original = currentPromptOriginal || textEl.value.trim();
      if (!original) {{
        setPanelVisible(assistToolsEl, toggleAssistToolsBtn, true);
        setMessage("没有可润色的提示词。", "err");
        textEl.focus();
        return;
      }}
      currentPromptOriginal = original;
      enrichPromptBtn.disabled = true;
      sendPromptAnswerBtn.disabled = true;
      setMessage("正在润色提示词...");
      try {{
        const res = await fetch("/prompt/enrich", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            key: ACCESS_KEY,
            text: original,
            mode: promptModeEl.value,
            answer
          }})
        }});
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "润色失败");
        renderPromptWorkbench(data.result);
      }} catch (err) {{
        setMessage(String(err.message || err), "err");
      }} finally {{
        enrichPromptBtn.disabled = false;
        sendPromptAnswerBtn.disabled = false;
      }}
    }}

    async function enrichPromptText() {{
      currentPromptOriginal = textEl.value.trim();
      currentPromptCandidate = "";
      promptAnswerEl.value = "";
      await requestPromptEnrichment("");
    }}

    async function sendPromptAnswer() {{
      const answer = promptAnswerEl.value.trim();
      if (!answer) {{
        setMessage("请先填写补充回答。", "err");
        promptAnswerEl.focus();
        return;
      }}
      await requestPromptEnrichment(answer);
    }}

    function acceptPromptResult() {{
      if (!currentPromptCandidate.trim()) {{
        setMessage("没有可采用的润色结果。", "err");
        return;
      }}
      textEl.value = currentPromptCandidate;
      setMessage("已采用润色结果。", "ok");
      textEl.focus();
    }}

    async function sendText() {{
      if (selectedFiles.length && !isLocalShareMode()) {{
        await uploadFilesToPaste();
        return;
      }}
      const text = textEl.value;
      if (!text.trim()) {{
        setMessage("没有可发送的文字。", "err");
        textEl.focus();
        return;
      }}
      sendBtn.disabled = true;
      setMessage("发送中...");
      try {{
        const res = await fetch("/send", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            key: ACCESS_KEY,
            text,
            add_newline: false,
            press_enter: pressEnterEl.checked,
            enter_delay_sec: 0.5
          }})
        }});
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "发送失败");
        const suffix = data.result.enter_pressed ? "，并已回车" : "";
        setMessage(`已发送 ${{data.result.chars}} 个字符，电脑已执行粘贴${{suffix}}。`, "ok");
        if (clearAfterSendEl.checked) textEl.value = "";
      }} catch (err) {{
        setMessage(String(err.message || err), "err");
      }} finally {{
        sendBtn.disabled = false;
        textEl.focus();
      }}
    }}

    translateBtn.addEventListener("click", translateText);
    toggleInputSizeBtn.addEventListener("click", toggleInputSize);
    toggleAssistToolsBtn.addEventListener("click", () => togglePanel(assistToolsEl, toggleAssistToolsBtn));
    toggleFileToolsBtn.addEventListener("click", () => togglePanel(fileToolsPanelEl, toggleFileToolsBtn));
    chooseFilesBtn.addEventListener("click", openFilePicker);
    chooseImagesBtn.addEventListener("click", () => imageInputEl.click());
    chooseDocumentsBtn.addEventListener("click", () => documentInputEl.click());
    clearFilesBtn.addEventListener("click", clearSelectedFiles);
    fileInputEl.addEventListener("change", () => {{
      setSelectedFiles(fileInputEl.files);
    }});
    imageInputEl.addEventListener("change", () => {{
      setSelectedFiles(imageInputEl.files);
    }});
    documentInputEl.addEventListener("change", () => {{
      setSelectedFiles(documentInputEl.files);
    }});
    fileDropzoneEl.addEventListener("click", openFilePicker);
    fileDropzoneEl.addEventListener("keydown", (event) => {{
      if (event.key === "Enter" || event.key === " ") {{
        event.preventDefault();
        openFilePicker();
      }}
    }});
    fileDropzoneEl.addEventListener("dragover", (event) => {{
      if (isMobileClipboardMode()) return;
      event.preventDefault();
      fileDropzoneEl.classList.add("drag-over");
    }});
    fileDropzoneEl.addEventListener("dragleave", () => {{
      fileDropzoneEl.classList.remove("drag-over");
    }});
    fileDropzoneEl.addEventListener("drop", (event) => {{
      if (isMobileClipboardMode()) return;
      event.preventDefault();
      fileDropzoneEl.classList.remove("drag-over");
      setSelectedFiles(event.dataTransfer ? event.dataTransfer.files : []);
    }});
    uploadFilesBtn.addEventListener("click", uploadFilesToClipboard);
    refreshSharedFilesBtn.addEventListener("click", loadSharedFiles);
    enrichPromptBtn.addEventListener("click", enrichPromptText);
    sendPromptAnswerBtn.addEventListener("click", sendPromptAnswer);
    clearPromptWorkbenchBtn.addEventListener("click", clearPromptWorkbench);
    acceptPromptResultBtn.addEventListener("click", acceptPromptResult);
    sendBtn.addEventListener("click", sendText);
    textEl.addEventListener("paste", (event) => {{
      if (!event.clipboardData) return;
      const pastedText = event.clipboardData.getData("text/plain");
      if (!pastedText) return;
      event.preventDefault();
      const start = Number.isInteger(textEl.selectionStart) ? textEl.selectionStart : textEl.value.length;
      const end = Number.isInteger(textEl.selectionEnd) ? textEl.selectionEnd : start;
      textEl.setRangeText(pastedText, start, end, "end");
      textEl.dispatchEvent(new Event("input", {{ bubbles: true }}));
      textEl.focus();
    }});
    textEl.addEventListener("keydown", (event) => {{
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {{
        event.preventDefault();
        sendText();
      }}
    }});
    applyFileMode();
    renderSelectedFiles();
    if (shouldLoadSharedFiles()) loadSharedFiles();
    if (shouldLoadSharedFiles()) window.setInterval(loadSharedFiles, 5000);
    textEl.focus();
  </script>
</body>
</html>'''


def invalid_access_key_page() -> str:
    return '''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>二维码已失效</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f7f6; color: #142421; font-family: "Microsoft YaHei UI", sans-serif; }
    main { width: min(86vw, 420px); padding: 28px; background: #fff; border: 1px solid #dce8e6; border-radius: 14px; text-align: center; }
    h1 { margin: 0 0 12px; font-size: 24px; }
    p { margin: 0; color: #61716e; line-height: 1.7; }
  </style>
</head>
<body><main><h1>二维码已失效</h1><p>请回到电脑 APP，打开“扫码连接手机”，点击“刷新二维码”，然后重新扫码。</p></main></body>
</html>'''


class BridgeServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, access_key: str, log_queue=None):
        super().__init__(server_address, handler_class)
        self.access_key = access_key
        self.log_queue = log_queue
        self.state = {"last_paste_ms": None, "last_error": None, "paste_count": 0}
        self.state_lock = threading.Lock()

    def add_log(self, message: str) -> None:
        line = append_service_log(message)
        if self.log_queue is not None:
            self.log_queue.put(line)


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server: BridgeServer

    def end_headers(self) -> None:
        origin = str(self.headers.get("Origin", ""))
        if origin in ("http://tauri.localhost", "https://tauri.localhost") or origin.startswith(
            ("http://localhost:", "http://127.0.0.1:")
        ):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def log_message(self, format, *args) -> None:
        self.server.add_log(format % args)

    def active_access_key(self) -> str:
        key = current_access_key(self.server.access_key)
        if key != self.server.access_key:
            self.server.access_key = key
            self.server.add_log("access key synchronized from local configuration")
        return key

    def is_authorized(self, key: str | None) -> bool:
        return bool(key and secrets.compare_digest(key, self.active_access_key()))

    def is_loopback_client(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def require_desktop_client(self) -> bool:
        if self.is_loopback_client():
            return True
        json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "desktop API is local only"})
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        key = (params.get("key") or [""])[0]
        if parsed.path in ("", "/"):
            if not self.is_authorized(key):
                text_response(self, HTTPStatus.UNAUTHORIZED, invalid_access_key_page(), "text/html; charset=utf-8")
                return
            active_key = self.active_access_key()
            text_response(
                self,
                HTTPStatus.OK,
                html_page(active_key, f"http://{self.headers.get('Host', '127.0.0.1')}/?key={active_key}"),
                "text/html; charset=utf-8",
            )
            return
        if parsed.path.startswith("/__updates__/"):
            filename = unquote(parsed.path.removeprefix("/__updates__/"))
            try:
                update_file = resolve_local_update_file(filename)
                if update_file.name == "update.json":
                    json_response(self, HTTPStatus.OK, local_update_manifest_for_host(self.headers.get("Host", "")))
                else:
                    file_response(self, update_file)
            except Exception as exc:
                text_response(self, HTTPStatus.NOT_FOUND, str(exc))
            return
        if parsed.path == "/files/shared":
            if not self.is_authorized(key):
                json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "invalid access key"})
                return
            items = list_shared_items(MOBILE_SHARE_DIR)
            json_response(self, HTTPStatus.OK, {"ok": True, "items": items, "files": items})
            return
        if parsed.path == "/files/download":
            if not self.is_authorized(key):
                text_response(self, HTTPStatus.UNAUTHORIZED, "invalid access key")
                return
            try:
                filename = (params.get("file") or [""])[0]
                file_response(self, resolve_shared_download(filename, MOBILE_SHARE_DIR), inline=True)
            except Exception as exc:
                text_response(self, HTTPStatus.NOT_FOUND, str(exc))
            return
        if parsed.path == "/health":
            with self.server.state_lock:
                state = dict(self.server.state)
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "name": APP_NAME,
                    "version": APP_VERSION,
                    "pid": os.getpid(),
                    "executable": running_executable_path(),
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "state": state,
                    "time_ms": now_ms(),
                },
            )
            return
        if parsed.path == "/prompt/library":
            if not self.is_authorized(key):
                json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "invalid access key"})
                return
            try:
                library = ensure_prompt_library()
                modes = [
                    {
                        "id": mode.get("id"),
                        "label": mode.get("label"),
                        "goal": mode.get("goal"),
                    }
                    for mode in library.get("modes", [])
                ]
                json_response(self, HTTPStatus.OK, {"ok": True, "modes": modes})
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        if parsed.path.startswith("/desktop/"):
            if not self.require_desktop_client():
                return
            if not self.is_authorized(key):
                json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "invalid access key"})
                return
            try:
                self.handle_desktop_get(parsed.path, params)
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        text_response(self, HTTPStatus.NOT_FOUND, "not found")

    def handle_desktop_get(self, path: str, params: dict) -> None:
        port = int(self.server.server_port)
        active_key = self.active_access_key()
        if path == "/desktop/state":
            host = preferred_lan_host()
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "version": APP_VERSION,
                    "port": port,
                    "key": active_key,
                    "mobile_url": build_access_url(host, port, active_key),
                    "local_url": build_local_access_url(port, active_key),
                    "host": host,
                    "data_dir": str(DATA_DIR),
                },
            )
            return
        if path == "/desktop/history":
            query = str((params.get("q") or [""])[0])
            category = str((params.get("category") or ["all"])[0])
            offset = max(0, int((params.get("offset") or ["0"])[0]))
            limit = max(1, min(100, int((params.get("limit") or ["30"])[0])))
            records = search_clipboard_history(query, None, category)
            items = []
            for record in records[offset : offset + limit]:
                item = dict(record)
                item["summary"] = history_record_preview(record)
                item["category"] = history_record_category(record)
                item["has_thumbnail"] = first_image_history_path(record) is not None
                items.append(item)
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "items": items,
                    "total": len(records),
                    "offset": offset,
                    "has_more": offset + len(items) < len(records),
                },
            )
            return
        if path == "/desktop/history/thumbnail":
            record_id = str((params.get("id") or [""])[0])
            record = find_history_record(record_id)
            image_path = first_image_history_path(record)
            if image_path is None:
                raise ValueError("历史记录没有可预览图片")
            file_response(self, image_path, inline=True)
            return
        if path == "/desktop/update":
            force = str((params.get("refresh") or [""])[0]).strip().lower() not in ("", "0", "false")
            if force:
                reset_update_check_cache()
            json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "result": check_for_update(timeout=5.0, use_cache=not force)},
            )
            return
        if path == "/desktop/tunnel":
            config = read_tunnel_config()
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "config": config,
                    "status": tunnel_status(config),
                    "candidates": detect_tunnel_candidates(),
                    "probe_url": tunnel_probe_url(config),
                    "log_path": str(tunnel_log_path(str(config.get("name") or ""))),
                    "log_tail": tunnel_log_tail(str(config.get("name") or "")),
                },
            )
            return
        if path == "/desktop/config":
            minimax = read_minimax_config()
            tunnel = read_tunnel_config()
            update_url = read_update_manifest_url()
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "update_url": update_url,
                    "update_source": "github" if github_repo_from_url(update_url) else "manifest",
                    "minimax_configured": bool(str(minimax.get("api_key", "")).strip()),
                    "minimax_model": str(minimax.get("model", MINIMAX_DEFAULT_MODEL)),
                    "tunnel": tunnel,
                    "tunnel_status": tunnel_status(tunnel),
                },
            )
            return
        if path == "/desktop/diagnostics":
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "diagnostics": build_diagnostics_report(port, True),
                    "self_check": build_self_check_report(port, True),
                },
            )
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in (
            "/send",
            "/prompt/enrich",
            "/files/clipboard",
            "/files/share",
            "/files/paste",
            "/desktop/key/regenerate",
            "/desktop/publish",
            "/desktop/copy",
            "/desktop/diagnostics/copy",
            "/desktop/open",
            "/desktop/open-folder",
            "/desktop/update/prepare",
            "/desktop/config",
            "/desktop/firewall",
            "/desktop/tunnel/config",
            "/desktop/tunnel/start",
            "/desktop/tunnel/stop",
        ):
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return

        if parsed.path in ("/files/clipboard", "/files/share", "/files/paste"):
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0:
                    json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty upload"})
                    return
                upload_dir = MOBILE_SHARE_DIR if parsed.path == "/files/share" else HISTORY_ARCHIVE_DIR
                upload = parse_multipart_upload_stream(
                    self.rfile,
                    content_length,
                    self.headers.get("Content-Type", ""),
                    upload_dir,
                    categorize=parsed.path != "/files/share",
                )
            except Exception as exc:
                json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return
            if not self.is_authorized(str(upload.get("key", ""))):
                json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "invalid access key"})
                return
            try:
                if parsed.path == "/files/share":
                    result = share_uploaded_files(upload["files"])
                    record_file_history(upload["files"], action="share")
                    log_message = f"shared {result['files']} files for mobile download"
                elif parsed.path == "/files/paste":
                    result = paste_uploaded_files(upload["files"])
                    record_file_history(upload["files"], action="paste")
                    log_message = f"pasted {result['pastes']} uploaded files"
                else:
                    result = put_uploaded_files_on_clipboard(upload["files"])
                    record_file_history(upload["files"], action="clipboard")
                    log_message = f"uploaded {result['files']} files to clipboard"
                with self.server.state_lock:
                    if parsed.path == "/files/paste":
                        self.server.state["last_paste_ms"] = now_ms()
                        self.server.state["paste_count"] += result["pastes"]
                    self.server.state["last_error"] = None
                self.server.add_log(log_message)
                json_response(self, HTTPStatus.OK, {"ok": True, "result": result})
            except Exception as exc:
                with self.server.state_lock:
                    self.server.state["last_error"] = str(exc)
                self.server.add_log(f"file upload failed: {exc}")
                json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"file upload failed: {exc}"},
                )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))
        except Exception:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid json"})
            return

        if not self.is_authorized(str(data.get("key", ""))):
            json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "invalid access key"})
            return

        if parsed.path.startswith("/desktop/"):
            if not self.require_desktop_client():
                return
            try:
                self.handle_desktop_post(parsed.path, data)
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/prompt/enrich":
            text = str(data.get("text", ""))
            if not text.strip():
                json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty text"})
                return
            if len(text) > MAX_TEXT_LENGTH:
                json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": f"text is too long; max {MAX_TEXT_LENGTH}"},
                )
                return
            try:
                result = enrich_prompt(
                    text,
                    str(data.get("mode", "auto")),
                    answer=str(data.get("answer", "")),
                )
                json_response(self, HTTPStatus.OK, {"ok": True, "result": result})
            except Exception as exc:
                json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return

        text = str(data.get("text", ""))
        if not text.strip():
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty text"})
            return
        if len(text) > MAX_TEXT_LENGTH:
            json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": f"text is too long; max {MAX_TEXT_LENGTH}"},
            )
            return

        try:
            result = paste_text(
                text,
                bool(data.get("add_newline", False)),
                bool(data.get("press_enter", False)),
                float(data.get("enter_delay_sec", 0.5)),
            )
            record_text_history(text, action="send")
            with self.server.state_lock:
                self.server.state["last_paste_ms"] = now_ms()
                self.server.state["last_error"] = None
                self.server.state["paste_count"] += 1
            self.server.add_log(f"pasted {result['chars']} chars")
            json_response(self, HTTPStatus.OK, {"ok": True, "result": result})
        except Exception as exc:
            with self.server.state_lock:
                self.server.state["last_error"] = str(exc)
            self.server.add_log(f"paste failed: {exc}")
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"paste failed: {exc}"})

    def handle_desktop_post(self, path: str, data: dict) -> None:
        port = int(self.server.server_port)
        if path == "/desktop/key/regenerate":
            key = write_new_access_key()
            self.server.access_key = key
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "key": key,
                    "mobile_url": build_access_url(preferred_lan_host(), port, key),
                },
            )
            return
        if path == "/desktop/publish":
            text = str(data.get("text", ""))
            paths = [str(item) for item in data.get("paths", []) if str(item).strip()]
            result = {"text": None, "files": None}
            if text.strip():
                result["text"] = publish_text_for_mobile_download(text)
            if paths:
                result["files"] = publish_files_for_mobile_download(paths)
            if result["text"] is None and result["files"] is None:
                raise ValueError("没有可发布的文字或文件")
            json_response(self, HTTPStatus.OK, {"ok": True, "result": result})
            return
        if path == "/desktop/copy":
            text = str(data.get("text", ""))
            if not text:
                raise ValueError("没有可复制的文字")
            set_clipboard_text(text)
            json_response(self, HTTPStatus.OK, {"ok": True})
            return
        if path == "/desktop/diagnostics/copy":
            diagnostics = build_diagnostics_report(port, True)
            set_clipboard_text(diagnostics)
            json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "result": {"copied": True, "characters": len(diagnostics)}},
            )
            return
        if path == "/desktop/open":
            result = open_history_file_item(
                str(data.get("id", "")),
                str(data.get("mode", "file")),
                int(data.get("file_index", 0)),
            )
            json_response(self, HTTPStatus.OK, {"ok": True, "result": result})
            return
        if path == "/desktop/open-folder":
            target = str(data.get("target", "history"))
            folder = MOBILE_SHARE_DIR if target == "shared" else ensure_history_archive_structure()
            os.startfile(str(folder))
            json_response(self, HTTPStatus.OK, {"ok": True, "path": str(folder)})
            return
        if path == "/desktop/update/prepare":
            update = check_for_update(timeout=10.0)
            if not update.get("configured"):
                raise ValueError("未配置更新源")
            if not update.get("available"):
                raise ValueError("当前已是最新版")
            package = download_update_package(
                str(update.get("url", "")),
                str(update.get("version", "")),
                str(update.get("sha256", "")),
                timeout=120.0,
            )
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "version": str(update.get("version", "")),
                    "package_path": str(package.resolve()),
                },
            )
            return
        if path == "/desktop/tunnel/config":
            merged = dict(read_tunnel_config())
            for field in ("enabled", "name", "public_url", "cloudflared_path", "config_path", "metrics_port"):
                if field in data:
                    merged[field] = data[field]
            saved = write_tunnel_config(merged)
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "config": saved,
                    "status": tunnel_status(saved),
                    "probe_url": tunnel_probe_url(saved),
                },
            )
            return
        if path in ("/desktop/tunnel/start", "/desktop/tunnel/stop"):
            config = dict(read_tunnel_config())
            if "name" in data:
                config["name"] = data["name"]
            if "public_url" in data:
                config["public_url"] = data["public_url"]
            if "cloudflared_path" in data:
                config["cloudflared_path"] = data["cloudflared_path"]
            if "config_path" in data:
                config["config_path"] = data["config_path"]
            if "metrics_port" in data:
                config["metrics_port"] = data["metrics_port"]
            starting = path.endswith("/start")
            config["enabled"] = bool(data.get("enabled", True)) if starting else bool(config.get("enabled"))
            config = write_tunnel_config(config)
            if starting:
                status = start_tunnel(config)
            else:
                stop_result = stop_tunnel()
                status = tunnel_status(config)
                status["stop_result"] = stop_result
            json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "config": read_tunnel_config(), "status": status},
            )
            return
        if path == "/desktop/config":
            if "update_url" in data:
                value = str(data.get("update_url", "")).strip()
                if value:
                    write_text_config(UPDATE_URL_FILE, value)
                else:
                    clear_text_config(UPDATE_URL_FILE)
                reset_update_check_cache()
            if "minimax_api_key" in data:
                value = str(data.get("minimax_api_key", "")).strip()
                if value:
                    write_text_config(MINIMAX_API_KEY_FILE, value)
                elif bool(data.get("clear_minimax_api_key", False)):
                    clear_text_config(MINIMAX_API_KEY_FILE)
            json_response(self, HTTPStatus.OK, {"ok": True})
            return
        if path == "/desktop/firewall":
            status = firewall_rule_status(port)
            launched = False
            if not status.get("allowed"):
                launch_firewall_rule_elevation(port)
                launched = True
                status = firewall_rule_status(port)
            json_response(
                self,
                HTTPStatus.OK,
                {"ok": True, "result": {**status, "launched": launched, "rule": firewall_rule_name(port)}},
            )
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})


class WindowsTrayIcon:
    def __init__(self, gui: "BridgeGui"):
        self.gui = gui
        self.root = gui.root
        self.hwnd = None
        self.hicon = None
        self.installed = False
        self._wndproc = None
        self._menu = None
        self.actions = queue.Queue()
        self._class_name = f"{APP_ID}TrayWindow"

    def install(self) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            self._create_message_window()
            self.hicon = self._load_icon()
            if not self.hicon:
                raise win_error("加载托盘图标失败")
            data = self._notify_data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
                raise win_error("注册系统托盘图标失败")
            self._menu = self._build_menu()
            self.installed = True
            return True
        except Exception as exc:
            self.gui.log(f"tray icon disabled: {exc}")
            self.remove()
            return False

    def _load_icon(self):
        icon_path = app_icon_path()
        if icon_path.exists():
            icon = user32.LoadImageW(
                None,
                str(icon_path),
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if icon:
                return icon
        return user32.LoadIconW(
            None,
            ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR),
        )

    def _create_message_window(self) -> None:
        self._wndproc = WNDPROC(self._handle_message)
        hinstance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = hinstance
        window_class.lpszClassName = self._class_name
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom and ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
            raise win_error("注册托盘消息窗口失败")
        self.hwnd = user32.CreateWindowExW(
            0,
            self._class_name,
            self._class_name,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not self.hwnd:
            raise win_error("创建托盘消息窗口失败")

    def _build_menu(self) -> tk.Menu:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="显示主窗口", command=self.gui.show_window)
        menu.add_command(label="复制扫码链接", command=self.gui.copy_mobile_url)
        menu.add_command(label="打开本机页面", command=self.gui.open_local_url)
        menu.add_separator()
        menu.add_command(label="检查更新", command=self.gui.check_update_from_tray)
        menu.add_separator()
        menu.add_command(label="退出程序", command=self.gui.quit_app)
        return menu

    def _notify_data(self, flags: int) -> "NOTIFYICONDATAW":
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = TRAY_ICON_ID
        data.uFlags = flags
        data.uCallbackMessage = TRAY_CALLBACK_MESSAGE
        data.hIcon = self.hicon
        data.szTip = f"{APP_NAME} v{APP_VERSION}"[:127]
        return data

    def _handle_message(self, hwnd, msg, wparam, lparam):
        if msg == TRAY_CALLBACK_MESSAGE:
            event = int(lparam)
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.actions.put("show")
            elif event == WM_RBUTTONUP:
                self.actions.put("menu")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def drain_actions(self) -> None:
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self.gui.show_window()
            elif action == "menu":
                self.show_menu()

    def show_menu(self) -> None:
        if not self._menu:
            return
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return
        user32.SetForegroundWindow(self.hwnd)
        try:
            self._menu.tk_popup(point.x, point.y)
        finally:
            self._menu.grab_release()

    def remove(self) -> None:
        if IS_WINDOWS and self.hwnd and self.installed:
            data = self._notify_data(0)
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        self.installed = False
        if IS_WINDOWS and self.hwnd:
            user32.DestroyWindow(self.hwnd)
        self.hwnd = None


class BridgeGui:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1040x720")
        self.root.minsize(940, 640)
        self.log_queue = queue.Queue()
        self.server = None
        self.server_thread = None
        self.access_key = read_or_create_access_key()
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.status_var = tk.StringVar(value="未启动")
        self.status_badge_var = tk.StringVar(value="待启动")
        self.status_title_var = tk.StringVar(value="服务未启动")
        self.status_detail_var = tk.StringVar(value="点击“启动”后，手机即可扫码发送文字、图片、视频和文件到这台电脑。")
        self.status_port_var = tk.StringVar(value=f"端口 {DEFAULT_PORT}")
        self.key_var = tk.StringVar(value=self.access_key)
        self.qr_hint_var = tk.StringVar(value="启动后生成二维码")
        self.link_value_var = tk.StringVar(value="等待服务启动")
        self.key_status_var = tk.StringVar(value=self.mask_access_key(self.access_key))
        self.update_status_var = tk.StringVar(value=f"当前版本 v{APP_VERSION}")
        self.activity_visible = False
        self.main_preview_refresh_after_id = None
        self.apply_window_icon()
        self._build_ui()
        self.log(f"app started version={APP_VERSION} executable={running_executable_path()}")
        self.tray_icon = WindowsTrayIcon(self)
        self.tray_available = self.tray_icon.install()
        if self.tray_available:
            self.log("tray icon registered")
        else:
            self.log("tray icon unavailable")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.after(100, self.start_server)
        self.root.after(700, self.maybe_show_first_run_guide)
        self.root.after(1500, lambda: self.check_update(silent=True))
        self.root.after(200, self.drain_logs)
        self.root.after(100, self.drain_tray_actions)
        self.schedule_main_preview_refresh()

    def apply_window_icon(self) -> None:
        icon_path = app_icon_path()
        if not icon_path.exists():
            return
        try:
            self.root.iconbitmap(default=str(icon_path))
        except tk.TclError as exc:
            self.log(f"window icon skipped: {exc}")

    @staticmethod
    def mask_access_key(access_key: str) -> str:
        if len(access_key) <= 10:
            return "已配置"
        return f"{access_key[:4]} •••• •••• {access_key[-4:]}"

    def maybe_show_first_run_guide(self) -> None:
        if FIRST_RUN_FILE.exists():
            return
        try:
            FIRST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
            FIRST_RUN_FILE.write_text(f"seen {APP_VERSION}\n", encoding="utf-8")
        except OSError:
            pass
        messagebox.showinfo(
            APP_NAME,
            "对外分发版已就绪。\n\n"
            "1. 点击“启动服务”，手机扫码即可互传文字、图片、视频和文件。\n"
            "2. 如需提示词润色，点击“配置”写入 MiniMax API Key。\n"
            "3. 遇到问题时，点击“复制诊断信息”发给维护者。\n\n"
            "本机访问密钥、API Key、日志和上传文件只保存在当前电脑。",
        )

    def _configure_styles(self) -> None:
        self.root.configure(bg=UI_COLORS["page"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Bridge.TEntry", fieldbackground="#ffffff", padding=6)

    def _panel(self, parent: tk.Misc, bg: str | None = None, border: str | None = None) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=bg or UI_COLORS["surface"],
            highlightbackground=border or UI_COLORS["line"],
            highlightthickness=1,
        )

    def _action_button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        primary: bool = False,
        danger: bool = False,
    ) -> tk.Button:
        bg = UI_COLORS["surface"]
        fg = UI_COLORS["text"]
        border = UI_COLORS["line"]
        active_bg = "#eef5f5"
        if primary:
            bg = UI_COLORS["primary"]
            fg = "#ffffff"
            border = UI_COLORS["primary"]
            active_bg = UI_COLORS["primary_dark"]
        elif danger:
            fg = UI_COLORS["danger"]
            active_bg = "#fff1f0"
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightbackground=border,
            highlightthickness=1,
            padx=14,
            pady=8,
            cursor="hand2",
            font=("", 10, "bold"),
        )

    def _build_ui(self) -> None:
        self._configure_styles()
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.shell_frame = tk.Frame(self.root, bg=UI_COLORS["page"])
        self.shell_frame.grid(row=0, column=0, sticky="nsew")
        self.shell_frame.columnconfigure(0, minsize=208)
        self.shell_frame.columnconfigure(1, weight=1)
        self.shell_frame.columnconfigure(2, minsize=330)
        self.shell_frame.rowconfigure(0, weight=1)

        self.sidebar_frame = tk.Frame(self.shell_frame, bg=UI_COLORS["nav"])
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.columnconfigure(0, weight=1)
        self.sidebar_frame.rowconfigure(7, weight=1)

        tk.Label(self.sidebar_frame, text=APP_NAME, bg=UI_COLORS["nav"], fg=UI_COLORS["text"], font=("", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=22, pady=(26, 2)
        )
        tk.Label(self.sidebar_frame, text=f"v{APP_VERSION}", bg=UI_COLORS["nav"], fg=UI_COLORS["muted"], font=("", 10)).grid(
            row=1, column=0, sticky="w", padx=22, pady=(0, 18)
        )
        self.guide_frame = tk.Frame(self.sidebar_frame, bg=UI_COLORS["nav_active"], highlightbackground="#bfe8e5", highlightthickness=1)
        self.guide_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 14))
        self.guide_frame.columnconfigure(0, weight=1)
        tk.Label(self.guide_frame, text="连接步骤", bg=UI_COLORS["nav_active"], fg=UI_COLORS["primary_dark"], font=("", 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(14, 8)
        )
        for row, text in enumerate(("1. 启动服务", "2. 手机扫码", "3. 发送内容"), start=1):
            tk.Label(self.guide_frame, text=text, bg=UI_COLORS["nav_active"], fg=UI_COLORS["text"], font=("", 10)).grid(
                row=row, column=0, sticky="w", padx=14, pady=(0, 7)
            )
        tk.Label(
            self.guide_frame,
            text="端口占用会自动顺延，无需手动配置。",
            bg=UI_COLORS["nav_active"],
            fg=UI_COLORS["muted"],
            font=("", 9),
            wraplength=150,
            justify="left",
        ).grid(row=4, column=0, sticky="ew", padx=14, pady=(4, 14))
        tk.Label(self.sidebar_frame, text="当前状态", bg=UI_COLORS["nav"], fg=UI_COLORS["muted"], font=("", 9)).grid(
            row=8, column=0, sticky="w", padx=22, pady=(0, 4)
        )
        tk.Label(
            self.sidebar_frame,
            textvariable=self.status_title_var,
            bg=UI_COLORS["nav"],
            fg=UI_COLORS["primary_dark"],
            font=("", 10, "bold"),
        ).grid(row=9, column=0, sticky="w", padx=22, pady=(0, 6))
        tk.Label(self.sidebar_frame, text="局域网扫码模式", bg=UI_COLORS["nav"], fg=UI_COLORS["muted"], font=("", 10)).grid(
            row=10, column=0, sticky="w", padx=22, pady=(0, 22)
        )

        self.scan_panel = tk.Frame(
            self.shell_frame,
            bg=UI_COLORS["surface"],
            highlightbackground=UI_COLORS["line"],
            highlightthickness=1,
        )
        self.scan_panel.grid(row=0, column=1, sticky="nsew", padx=16, pady=(16, 10))
        self.scan_panel.columnconfigure(0, weight=1)
        self.scan_panel.rowconfigure(1, weight=1)

        preview_header = tk.Frame(self.scan_panel, bg=UI_COLORS["surface"])
        preview_header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 12))
        preview_header.columnconfigure(0, weight=1)
        tk.Label(
            preview_header,
            text="最近内容预览",
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["text"],
            font=("", 22, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            preview_header,
            text="最近 30 条文字、图片、视频和文件记录。每 5 秒自动刷新，图片会显示缩略图。",
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["muted"],
            font=("", 10),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        preview_actions = tk.Frame(preview_header, bg=UI_COLORS["surface"])
        preview_actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self._action_button(preview_actions, "扫码连接手机", self.show_qr_window, primary=True).grid(row=0, column=0, padx=(0, 8))
        self._action_button(preview_actions, "立即刷新", self.refresh_main_preview).grid(row=0, column=1)

        preview_frame = tk.Frame(self.scan_panel, bg=UI_COLORS["surface"])
        preview_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 18))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.main_preview_images = []
        self.main_preview_canvas = tk.Canvas(preview_frame, bg=UI_COLORS["surface"], highlightthickness=0, height=420)
        self.main_preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.main_preview_list = tk.Frame(self.main_preview_canvas, bg=UI_COLORS["surface"])
        self.main_preview_canvas_window = self.main_preview_canvas.create_window(
            (0, 0),
            window=self.main_preview_list,
            anchor="nw",
        )
        main_preview_scroll_y = ttk.Scrollbar(preview_frame, orient="vertical", command=self.main_preview_canvas.yview)
        main_preview_scroll_y.grid(row=0, column=1, sticky="ns")
        self.main_preview_canvas.configure(yscrollcommand=main_preview_scroll_y.set)
        self.main_preview_list.bind(
            "<Configure>",
            lambda _event: self.main_preview_canvas.configure(scrollregion=self.main_preview_canvas.bbox("all")),
        )
        self.main_preview_canvas.bind(
            "<Configure>",
            lambda event: self.main_preview_canvas.itemconfigure(self.main_preview_canvas_window, width=event.width),
        )
        self.main_preview_canvas.bind("<Enter>", self.bind_main_preview_mousewheel)
        self.main_preview_canvas.bind("<Leave>", self.unbind_main_preview_mousewheel)

        self.service_panel = tk.Frame(
            self.shell_frame,
            bg=UI_COLORS["surface"],
            highlightbackground=UI_COLORS["line"],
            highlightthickness=1,
        )
        self.service_panel.grid(row=0, column=2, sticky="nsew", padx=(0, 16), pady=(16, 10))
        self.service_panel.columnconfigure(0, weight=1)

        tk.Label(self.service_panel, text="服务控制", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], font=("", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(20, 10)
        )
        self.status_card = tk.Frame(self.service_panel, bg="#f8fafc", highlightbackground="#cbd5e1", highlightthickness=1)
        self.status_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))
        self.status_card.columnconfigure(1, weight=1)
        self.status_badge_label = tk.Label(
            self.status_card,
            textvariable=self.status_badge_var,
            bg="#64748b",
            fg="#ffffff",
            font=("", 11, "bold"),
            padx=12,
            pady=6,
        )
        self.status_badge_label.grid(row=0, column=0, sticky="nw", padx=12, pady=12)
        self.status_title_label = tk.Label(
            self.status_card,
            textvariable=self.status_title_var,
            bg="#f8fafc",
            fg="#0f172a",
            font=("", 20, "bold"),
            anchor="w",
        )
        self.status_title_label.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 2))
        self.status_detail_label = tk.Label(
            self.status_card,
            textvariable=self.status_detail_var,
            bg="#f8fafc",
            fg="#475569",
            font=("", 10),
            anchor="w",
            justify="left",
            wraplength=230,
        )
        self.status_detail_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8))
        control_frame = tk.Frame(self.service_panel, bg=UI_COLORS["surface"])
        control_frame.grid(row=2, column=0, sticky="ew", padx=18)
        control_frame.columnconfigure(0, weight=1)
        self.service_toggle_button = self._action_button(control_frame, "启动服务", self.start_server, primary=True)
        self.service_toggle_button.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        update_frame = self._panel(self.service_panel, bg=UI_COLORS["surface_soft"])
        update_frame.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 16))
        update_frame.columnconfigure(0, weight=1)
        tk.Label(update_frame, text="更新状态", bg=UI_COLORS["surface_soft"], fg=UI_COLORS["text"], font=("", 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 2)
        )
        tk.Label(update_frame, textvariable=self.update_status_var, bg=UI_COLORS["surface_soft"], fg=UI_COLORS["muted"], font=("", 10)).grid(
            row=1, column=0, sticky="w", padx=12, pady=(0, 10)
        )
        self.update_button = self._action_button(update_frame, "检查更新", self.check_update)
        self.update_button.grid(row=0, column=1, rowspan=2, padx=12, pady=12)

        key_frame = self._panel(self.service_panel, bg=UI_COLORS["surface_soft"])
        key_frame.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 16))
        key_frame.columnconfigure(0, weight=1)
        tk.Label(key_frame, text="访问密钥", bg=UI_COLORS["surface_soft"], fg=UI_COLORS["text"], font=("", 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 2)
        )
        tk.Label(key_frame, textvariable=self.key_status_var, bg=UI_COLORS["surface_soft"], fg=UI_COLORS["muted"], font=("", 10)).grid(
            row=1, column=0, sticky="w", padx=12, pady=(0, 10)
        )
        key_actions = tk.Frame(key_frame, bg=UI_COLORS["surface_soft"])
        key_actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        key_actions.columnconfigure((0, 1), weight=1)
        self._action_button(key_actions, "复制 Key", self.copy_key).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._action_button(key_actions, "重新生成 Key", self.regenerate_key).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        tk.Label(self.service_panel, text="快速操作", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], font=("", 12, "bold")).grid(
            row=5, column=0, sticky="w", padx=18, pady=(0, 8)
        )
        quick_actions = tk.Frame(self.service_panel, bg=UI_COLORS["surface"])
        quick_actions.grid(row=6, column=0, sticky="ew", padx=18)
        quick_actions.columnconfigure(0, weight=1)
        self._action_button(quick_actions, "打开本机数据目录", self.open_prompt_library_dir).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._action_button(quick_actions, "配置", self.show_config_dialog).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._action_button(quick_actions, "复制诊断信息", self.copy_diagnostics).grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._action_button(quick_actions, "查看历史", self.show_history_window).grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self._action_button(quick_actions, "放行防火墙", self.allow_firewall).grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self._action_button(quick_actions, "复制连接信息", self.copy_mobile_url).grid(row=5, column=0, sticky="ew")
        self.activity_toggle_button = self._action_button(quick_actions, "查看最近活动", self.toggle_activity_frame)
        self.activity_toggle_button.grid(row=6, column=0, sticky="ew", pady=(8, 0))

        self.set_status(
            "stopped",
            "服务未启动",
            "点击“启动服务”后，手机即可扫码发送文字、图片、视频和文件到这台电脑。",
            "待启动",
        )
        self.sync_service_buttons()

        self.activity_frame = tk.Frame(
            self.shell_frame,
            bg=UI_COLORS["surface"],
            highlightbackground=UI_COLORS["line"],
            highlightthickness=1,
        )
        self.activity_frame.grid(row=1, column=1, columnspan=2, sticky="nsew", padx=(16, 16), pady=(0, 16))
        self.activity_frame.columnconfigure(0, weight=1)
        self.activity_frame.rowconfigure(1, weight=1)
        tk.Label(self.activity_frame, text="最近活动", bg=UI_COLORS["surface"], fg=UI_COLORS["text"], font=("", 13, "bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 4)
        )
        tk.Label(
            self.activity_frame,
            text="日志仅保存在本机应用数据目录",
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["muted"],
            font=("", 9),
        ).grid(row=0, column=1, sticky="e", padx=18, pady=(14, 4))
        self.activity_text = tk.Text(
            self.activity_frame,
            height=6,
            wrap="word",
            relief="flat",
            bg="#fbfdfd",
            fg=UI_COLORS["text"],
            insertbackground=UI_COLORS["primary"],
            padx=12,
            pady=10,
            font=("", 9),
        )
        self.activity_text.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=18, pady=(0, 16))
        self.log_text = self.activity_text
        self.activity_frame.grid_remove()
        self.refresh_main_preview()

    def toggle_activity_frame(self) -> None:
        if self.activity_visible:
            self.activity_frame.grid_remove()
            self.activity_toggle_button.configure(text="查看最近活动")
            self.activity_visible = False
            return
        self.activity_frame.grid()
        self.activity_toggle_button.configure(text="收起最近活动")
        self.activity_visible = True

    def refresh_main_preview(self) -> None:
        if not getattr(self, "main_preview_list", None):
            return
        for child in self.main_preview_list.winfo_children():
            child.destroy()
        self.main_preview_images = []
        records = list_clipboard_history(HISTORY_WINDOW_LIMIT)
        if not records:
            empty_row = tk.Frame(self.main_preview_list, bg="#fbfdfd", highlightbackground=UI_COLORS["line"], highlightthickness=1)
            empty_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            empty_row.columnconfigure(0, weight=1)
            tk.Label(
                empty_row,
                text="还没有历史记录",
                bg="#fbfdfd",
                fg=UI_COLORS["muted"],
                font=("", 11, "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=14, pady=18)
            return
        self.main_preview_list.columnconfigure(0, weight=1)
        for index, record in enumerate(records):
            ts = format_history_timestamp(record.get("ts"))
            preview_data = history_record_preview(record)
            thumbnail = self.history_thumbnail_for_record(record, "main_preview_images")
            self.add_main_preview_row(index, str(record.get("id", "")), ts, preview_data, thumbnail)

    def schedule_main_preview_refresh(self) -> None:
        if self.main_preview_refresh_after_id:
            self.root.after_cancel(self.main_preview_refresh_after_id)
        self.main_preview_refresh_after_id = self.root.after(5000, self.auto_refresh_main_preview)

    def auto_refresh_main_preview(self) -> None:
        self.main_preview_refresh_after_id = None
        self.refresh_main_preview()
        self.schedule_main_preview_refresh()

    def add_main_preview_row(self, row: int, record_id: str, ts: str, preview_data: dict, thumbnail) -> None:
        normal_bg = "#fbfdfd"
        hover_bg = "#f0fbf8"
        item = tk.Frame(self.main_preview_list, bg=normal_bg, highlightbackground=UI_COLORS["line"], highlightthickness=1)
        item.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        item.columnconfigure(1, weight=1)

        thumb_box = tk.Frame(item, bg="#eef5f5", width=76, height=54)
        thumb_box.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=10, pady=9)
        thumb_box.grid_propagate(False)
        if thumbnail is not None:
            tk.Label(thumb_box, image=thumbnail, bg="#eef5f5").place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(
                thumb_box,
                text=str(preview_data.get("kind", ""))[:2],
                bg="#eef5f5",
                fg=UI_COLORS["primary_dark"],
                font=("", 11, "bold"),
            ).place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            item,
            text=str(preview_data.get("preview", "")),
            bg=normal_bg,
            fg=UI_COLORS["text"],
            font=("", 10, "bold"),
            anchor="w",
            justify="left",
            wraplength=330,
            cursor="hand2",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(10, 2))
        tk.Label(
            item,
            text=f"{ts}  |  {preview_data.get('info', '')}  |  单击使用，双击打开位置",
            bg=normal_bg,
            fg=UI_COLORS["muted"],
            font=("", 9),
            anchor="w",
            cursor="hand2",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 10))
        tk.Label(
            item,
            text=str(preview_data.get("kind", "")),
            bg=normal_bg,
            fg=UI_COLORS["primary_dark"],
            font=("", 9, "bold"),
            anchor="e",
            cursor="hand2",
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 12))
        self.bind_main_preview_row(item, record_id, normal_bg, hover_bg)

    def bind_main_preview_row(self, widget: tk.Widget, record_id: str, normal_bg: str, hover_bg: str) -> None:
        widgets = [widget] + list(widget.winfo_children())
        for child in widget.winfo_children():
            widgets.extend(child.winfo_children())
        for target in widgets:
            target.configure(cursor="hand2")
            target.bind("<Button-1>", lambda _event, rid=record_id: self.activate_main_preview_record(rid))
            target.bind("<Double-1>", lambda _event, rid=record_id: self.open_main_preview_record_folder(rid))
            target.bind("<MouseWheel>", self.on_main_preview_mousewheel)
            target.bind("<Button-4>", self.on_main_preview_mousewheel)
            target.bind("<Button-5>", self.on_main_preview_mousewheel)
            target.bind("<Enter>", lambda _event, frame=widget: self.set_main_preview_row_bg(frame, hover_bg))
            target.bind("<Leave>", lambda _event, frame=widget: self.set_main_preview_row_bg(frame, normal_bg))

    def set_main_preview_row_bg(self, widget: tk.Widget, bg: str) -> None:
        widget.configure(bg=bg)
        for child in widget.winfo_children():
            if isinstance(child, tk.Frame) and child.cget("bg") == "#eef5f5":
                continue
            try:
                child.configure(bg=bg)
            except tk.TclError:
                pass

    def activate_main_preview_record(self, record_id: str) -> str:
        try:
            record = find_history_record(record_id)
            if record.get("type") == "text":
                self.root.clipboard_clear()
                self.root.clipboard_append(str(record.get("text", "")))
                self.log("main preview text copied")
                return "text-copied"
            open_history_file_item(record_id, mode="file")
            self.log("main preview file opened")
            return "file-opened"
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return "error"

    def open_main_preview_record_folder(self, record_id: str) -> str:
        try:
            record = find_history_record(record_id)
            if record.get("type") != "file":
                return "ignored"
            open_history_file_item(record_id, mode="folder")
            self.log("main preview folder opened")
            return "folder-opened"
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return "error"

    def bind_main_preview_mousewheel(self, _event=None) -> None:
        self.root.bind_all("<MouseWheel>", self.on_main_preview_mousewheel)
        self.root.bind_all("<Button-4>", self.on_main_preview_mousewheel)
        self.root.bind_all("<Button-5>", self.on_main_preview_mousewheel)

    def unbind_main_preview_mousewheel(self, _event=None) -> None:
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def on_main_preview_mousewheel(self, event) -> str:
        if not getattr(self, "main_preview_canvas", None):
            return "break"
        if getattr(event, "num", None) == 4:
            delta = -3
        elif getattr(event, "num", None) == 5:
            delta = 3
        else:
            delta = -1 * int(getattr(event, "delta", 0) / 120)
        if delta:
            self.main_preview_canvas.yview_scroll(delta, "units")
        return "break"

    def history_selection_id(self) -> str:
        if not getattr(self, "history_tree", None):
            return ""
        selected = self.history_tree.selection()
        return selected[0] if selected else ""

    def show_history_window(self) -> None:
        if getattr(self, "history_window", None) and self.history_window.winfo_exists():
            self.history_window.lift()
            self.refresh_history_window()
            return
        self.history_window = tk.Toplevel(self.root)
        self.history_window.title("历史剪贴板")
        self.history_window.geometry("940x520")
        self.history_window.minsize(820, 420)
        self.history_window.configure(bg=UI_COLORS["page"])
        self.history_window.columnconfigure(0, weight=1)
        self.history_window.rowconfigure(1, weight=1)
        self.history_preview_images = []

        header = tk.Frame(self.history_window, bg=UI_COLORS["page"])
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="历史剪贴板", bg=UI_COLORS["page"], fg=UI_COLORS["text"], font=("", 15, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        action_bar = tk.Frame(header, bg=UI_COLORS["page"])
        action_bar.grid(row=0, column=1, sticky="e")
        self._action_button(action_bar, "刷新", self.refresh_history_window).grid(row=0, column=0, padx=(0, 6))
        self._action_button(action_bar, "清空", self.clear_history_from_window, danger=True).grid(row=0, column=1)

        tree_frame = tk.Frame(self.history_window, bg=UI_COLORS["page"])
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=14)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ("kind", "time", "preview", "info", "action")
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=HISTORY_WINDOW_LIMIT,
            style="History.Treeview",
        )
        ttk.Style(self.history_window).configure("History.Treeview", rowheight=58)
        self.history_tree.heading("#0", text="预览图")
        self.history_tree.heading("kind", text="类型")
        self.history_tree.heading("time", text="时间")
        self.history_tree.heading("preview", text="内容预览")
        self.history_tree.heading("info", text="信息")
        self.history_tree.heading("action", text="来源")
        self.history_tree.column("#0", width=96, minwidth=88, anchor="center", stretch=False)
        self.history_tree.column("kind", width=72, anchor="center", stretch=False)
        self.history_tree.column("time", width=150, anchor="w", stretch=False)
        self.history_tree.column("preview", width=380, anchor="w")
        self.history_tree.column("info", width=140, anchor="w", stretch=False)
        self.history_tree.column("action", width=90, anchor="center", stretch=False)
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        history_scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.history_tree.yview)
        history_scroll_y.grid(row=0, column=1, sticky="ns")
        history_scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.history_tree.xview)
        history_scroll_x.grid(row=1, column=0, sticky="ew")
        self.history_tree.configure(yscrollcommand=history_scroll_y.set, xscrollcommand=history_scroll_x.set)
        self.history_tree.bind("<Double-1>", lambda _event: self.open_selected_history_file())

        footer = tk.Frame(self.history_window, bg=UI_COLORS["page"])
        footer.grid(row=2, column=0, sticky="ew", padx=14, pady=14)
        footer.columnconfigure(0, weight=1)
        self._action_button(footer, "复制文本", self.copy_selected_history_text).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._action_button(footer, "固定/取消固定", self.toggle_selected_history_pin).grid(row=0, column=1, padx=(0, 6))
        self._action_button(footer, "删除", self.delete_selected_history_item, danger=True).grid(row=0, column=2, padx=(0, 6))
        self._action_button(footer, "打开文件", self.open_selected_history_file, primary=True).grid(row=0, column=3, padx=(0, 6))
        self._action_button(footer, "打开所在文件夹", self.open_selected_history_folder).grid(row=0, column=4)
        self.refresh_history_window()

    def refresh_history_window(self) -> None:
        if not getattr(self, "history_tree", None):
            return
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self.history_preview_images = []
        for record in list_clipboard_history(HISTORY_WINDOW_LIMIT):
            ts = format_history_timestamp(record.get("ts"))
            preview_data = history_record_preview(record)
            kind = preview_data["kind"]
            if record.get("pinned"):
                kind = "★ " + kind
            thumbnail = self.history_thumbnail_for_record(record)
            tree_text = preview_data["kind"] if thumbnail is None else ""
            self.history_tree.insert(
                "",
                "end",
                iid=str(record.get("id", "")),
                text=tree_text,
                image=thumbnail,
                values=(kind, ts, preview_data["preview"], preview_data["info"], str(record.get("action", ""))),
            )

    def history_thumbnail_for_record(self, record: dict, image_store_name: str = "history_preview_images"):
        if Image is None or ImageTk is None:
            return None
        path = first_image_history_path(record)
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                image.thumbnail((72, 48))
                preview = ImageTk.PhotoImage(image.copy())
        except (OSError, UnidentifiedImageError):
            return None
        image_store = getattr(self, image_store_name, None)
        if image_store is None:
            image_store = []
            setattr(self, image_store_name, image_store)
        image_store.append(preview)
        return preview

    def selected_history_record(self) -> dict:
        record_id = self.history_selection_id()
        if not record_id:
            raise ValueError("请先选择一条历史记录")
        return find_history_record(record_id)

    def copy_selected_history_text(self) -> None:
        try:
            record = self.selected_history_record()
            if record.get("type") != "text":
                raise ValueError("选中的不是文本历史")
            self.root.clipboard_clear()
            self.root.clipboard_append(str(record.get("text", "")))
            self.log("history text copied to clipboard")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def toggle_selected_history_pin(self) -> None:
        try:
            record = self.selected_history_record()
            set_history_pinned(str(record.get("id", "")), not bool(record.get("pinned")))
            self.refresh_history_window()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def delete_selected_history_item(self) -> None:
        try:
            record = self.selected_history_record()
            delete_history_item(str(record.get("id", "")))
            self.refresh_history_window()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def clear_history_from_window(self) -> None:
        if not messagebox.askyesno(APP_NAME, "确定清空历史剪贴板吗？固定项也会清空。"):
            return
        clear_clipboard_history()
        self.refresh_history_window()

    def open_selected_history_file(self) -> None:
        try:
            record_id = self.history_selection_id()
            open_history_file_item(record_id, mode="file")
            self.log("history file opened")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def open_selected_history_folder(self) -> None:
        try:
            record_id = self.history_selection_id()
            open_history_file_item(record_id, mode="folder")
            self.log("history file folder opened")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def set_status(self, theme_name: str, title: str, detail: str, badge: str) -> None:
        theme = STATUS_THEMES.get(theme_name, STATUS_THEMES["stopped"])
        self.status_var.set(title)
        self.status_badge_var.set(badge)
        self.status_title_var.set(title)
        self.status_detail_var.set(detail)
        self.status_port_var.set(f"端口 {self.current_port()}")
        if not hasattr(self, "status_card"):
            return
        self.status_card.configure(bg=theme["bg"], highlightbackground=theme["border"])
        self.status_badge_label.configure(bg=theme["accent"], fg="#ffffff")
        for label in (self.status_title_label, self.status_detail_label):
            label.configure(bg=theme["bg"])
        self.status_title_label.configure(fg=theme["fg"])
        self.status_detail_label.configure(fg=theme["muted"])

    def sync_service_buttons(self) -> None:
        if not hasattr(self, "service_toggle_button"):
            return
        if self.server:
            self.service_toggle_button.configure(
                text="停止服务",
                command=self.stop_server,
                state="normal",
                bg=UI_COLORS["danger"],
                fg="#ffffff",
                activebackground="#8a1f17",
                activeforeground="#ffffff",
                highlightbackground=UI_COLORS["danger"],
            )
        else:
            self.service_toggle_button.configure(
                text="启动服务",
                command=self.start_server,
                state="normal",
                bg=UI_COLORS["primary"],
                fg="#ffffff",
                activebackground=UI_COLORS["primary_dark"],
                activeforeground="#ffffff",
                highlightbackground=UI_COLORS["primary"],
            )

    def run(self) -> None:
        self.root.mainloop()

    def log(self, message: str) -> None:
        self.log_queue.put(append_service_log(message))

    def drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
        self.root.after(200, self.drain_logs)

    def drain_tray_actions(self) -> None:
        if getattr(self, "tray_icon", None):
            self.tray_icon.drain_actions()
        self.root.after(100, self.drain_tray_actions)

    def start_server(self) -> None:
        if self.server:
            self.update_qr()
            self.set_status(
                "running",
                "服务运行中",
                "手机扫码后即可发送文字、图片、视频和文件。",
                "可用",
            )
            self.sync_service_buttons()
            return
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            self.set_status("error", "端口无效", "端口必须是数字，例如 8765。", "需要处理")
            messagebox.showerror(APP_NAME, "端口必须是数字")
            return
        self.set_status("starting", "正在启动服务", "正在准备局域网扫码入口。", "启动中")
        self.sync_service_buttons()
        self.access_key = read_or_create_access_key()
        self.key_var.set(self.access_key)
        last_error = None
        selected_port = None
        for candidate_port in range(port, port + PORT_AUTO_INCREMENT_LIMIT):
            try:
                self.server = BridgeServer(("0.0.0.0", candidate_port), BridgeRequestHandler, self.access_key, self.log_queue)
            except OSError as exc:
                last_error = exc
                self.log(f"port {candidate_port} unavailable: {exc}")
                continue
            selected_port = candidate_port
            break
        if self.server is None or selected_port is None:
            detail = f"从 {port} 开始连续尝试 {PORT_AUTO_INCREMENT_LIMIT} 个端口仍无法启动：{last_error}"
            self.set_status("error", "启动失败", detail, "失败")
            self.sync_service_buttons()
            messagebox.showerror(APP_NAME, detail)
            return
        if selected_port != port:
            self.port_var.set(str(selected_port))
            self.log(f"port {port} busy; auto switched to {selected_port}")
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.set_status(
            "running",
            "服务运行中",
            "手机扫码后即可发送文字、图片、视频和文件。",
            "可用",
        )
        self.sync_service_buttons()
        self.log(f"server started on port {selected_port}")
        try:
            update_url = refresh_lan_update_manifest_url(selected_port)
            self.log(f"lan update source configured: {update_url}")
        except Exception as exc:
            self.log(f"lan update source configure skipped: {exc}")
        self.update_qr()

    def stop_server(self) -> None:
        if not self.server:
            self.set_status("stopped", "服务未启动", "点击“启动”重新开启手机互传。", "已停止")
            self.sync_service_buttons()
            return
        server = self.server
        self.server = None
        threading.Thread(target=lambda: self._shutdown_server(server), daemon=True).start()
        self.set_status("warning", "正在停止服务", "正在关闭局域网访问入口，手机端将暂时无法发送。", "停止中")
        self.sync_service_buttons()

    def _shutdown_server(self, server: BridgeServer) -> None:
        server.shutdown()
        server.server_close()
        self.log("server stopped")
        self.root.after(
            0,
            lambda: (
                self.set_status("stopped", "服务已停止", "点击“启动”重新开启手机互传。", "已停止"),
                self.sync_service_buttons(),
            ),
        )

    def current_port(self) -> int:
        try:
            return int(self.port_var.get().strip())
        except ValueError:
            return DEFAULT_PORT

    def make_urls(self) -> list[str]:
        key = self.access_key
        return [build_access_url(host, self.current_port(), key) for host in get_mobile_access_hosts()]

    def mobile_url(self) -> str:
        urls = self.make_urls()
        for url in urls:
            if "://127.0.0.1:" not in url and "://localhost:" not in url:
                return url
        return urls[0]

    def show_qr_window(self) -> None:
        if getattr(self, "qr_window", None) and self.qr_window.winfo_exists():
            self.qr_window.lift()
            self.update_qr()
            return
        self.qr_window = tk.Toplevel(self.root)
        self.qr_window.title("扫码连接手机")
        self.qr_window.geometry("500x680")
        self.qr_window.minsize(460, 640)
        self.qr_window.configure(bg=UI_COLORS["surface"])
        self.qr_window.columnconfigure(0, weight=1)

        tk.Label(
            self.qr_window,
            text="扫码连接手机",
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["text"],
            font=("", 20, "bold"),
        ).grid(row=0, column=0, pady=(24, 6))
        tk.Label(
            self.qr_window,
            text="手机和电脑在同一 Wi-Fi 下，扫码即可发送文字、图片、视频和文件。访问密钥已隐藏。",
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["muted"],
            font=("", 10),
            wraplength=360,
            justify="center",
        ).grid(row=1, column=0, pady=(0, 14))
        qr_holder = tk.Frame(self.qr_window, bg="#ffffff", highlightbackground="#e2eded", highlightthickness=1)
        qr_holder.grid(row=2, column=0, sticky="n", padx=30, pady=(0, 14))
        self.qr_popup_label = tk.Label(qr_holder, bg="#ffffff")
        self.qr_popup_label.grid(row=0, column=0, padx=16, pady=16)

        self.qr_popup_link_var = tk.StringVar(value="")
        tk.Label(
            self.qr_window,
            textvariable=self.qr_popup_link_var,
            bg=UI_COLORS["surface"],
            fg=UI_COLORS["primary_dark"],
            font=("", 9, "bold"),
            wraplength=380,
            justify="center",
        ).grid(row=3, column=0, padx=20, pady=(0, 12))
        self.qr_popup_check_var = tk.StringVar(value="")
        tk.Label(
            self.qr_window,
            textvariable=self.qr_popup_check_var,
            bg="#f8fbfb",
            fg=UI_COLORS["muted"],
            font=("", 9),
            wraplength=410,
            justify="left",
            padx=12,
            pady=10,
        ).grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 12))

        qr_actions = tk.Frame(self.qr_window, bg=UI_COLORS["surface"])
        qr_actions.grid(row=5, column=0, pady=(0, 20))
        self._action_button(qr_actions, "复制扫码链接", self.copy_mobile_url, primary=True).grid(row=0, column=0, padx=6)
        self._action_button(qr_actions, "复制自检信息", self.copy_connection_self_check).grid(row=0, column=1, padx=6)
        self._action_button(qr_actions, "打开本机页面", self.open_local_url).grid(row=0, column=2, padx=6)
        self.update_qr()

    def update_qr(self) -> None:
        url = self.mobile_url()
        if getattr(self, "qr_popup_label", None) and self.qr_popup_label.winfo_exists():
            self.qr_image = qr_photo_image(url, scale=8)
            self.qr_popup_label.configure(image=self.qr_image)
            if getattr(self, "qr_popup_link_var", None):
                self.qr_popup_link_var.set(f"局域网扫码链接已生成 · {display_qr_target(url)}")
            if getattr(self, "qr_popup_check_var", None):
                qr_host = urlparse(url).hostname or preferred_lan_host()
                self.qr_popup_check_var.set(
                    f"连接自检：手机先打开 {build_health_url(qr_host, self.current_port())}\n"
                    "能看到 ok=true 说明网络通；打不开通常是不同 Wi-Fi、路由器 AP 隔离或 Windows 防火墙拦截。"
                )
        if read_mobile_host_override():
            self.qr_hint_var.set("手机连接可访问此电脑的网络后扫码。")
        else:
            self.qr_hint_var.set("手机连接同一 Wi-Fi 后扫码。")

    def copy_mobile_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.mobile_url())
        self.log("mobile url copied to clipboard")

    def copy_connection_self_check(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(build_connection_self_check(self.current_port(), bool(self.server), preferred_lan_host()))
        self.log("connection self-check copied to clipboard")

    def show_config_dialog(self) -> None:
        minimax_key = simpledialog.askstring(
            APP_NAME,
            "MiniMax API Key：\n留空表示不修改；输入 clear 表示清除本机保存的 Key。",
            parent=self.root,
            show="*",
        )
        if minimax_key is not None:
            value = minimax_key.strip()
            if value.lower() == "clear":
                clear_text_config(MINIMAX_API_KEY_FILE)
                self.log("minimax api key cleared")
            elif value:
                write_text_config(MINIMAX_API_KEY_FILE, value)
                self.log("minimax api key configured")

        update_url = simpledialog.askstring(
            APP_NAME,
            "更新源 URL：\n留空表示不修改；输入 clear 表示清除。\n局域网源会在服务启动后自动写入。",
            parent=self.root,
            initialvalue=read_update_manifest_url(),
        )
        if update_url is not None:
            value = update_url.strip()
            if value.lower() == "clear":
                clear_text_config(UPDATE_URL_FILE)
                self.log("update url cleared")
            elif value:
                write_text_config(UPDATE_URL_FILE, value)
                self.log("update url configured")

        mobile_host = simpledialog.askstring(
            APP_NAME,
            "手机访问主机覆盖：\n通常不用填。留空表示不修改；输入 clear 表示恢复自动识别。",
            parent=self.root,
            initialvalue=read_mobile_host_override(),
        )
        if mobile_host is not None:
            value = normalize_mobile_host(mobile_host)
            if mobile_host.strip().lower() == "clear":
                clear_text_config(MOBILE_HOST_FILE)
                self.log("mobile host override cleared")
            elif value:
                write_text_config(MOBILE_HOST_FILE, value)
                self.log(f"mobile host override configured: {value}")
        self.update_qr()
        messagebox.showinfo(APP_NAME, "配置已保存。本机密钥和 API Key 不会写入 release 分发包。")

    def copy_diagnostics(self) -> None:
        report = build_diagnostics_report(self.current_port(), bool(self.server))
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        self.log("diagnostics copied to clipboard")
        messagebox.showinfo(APP_NAME, "诊断信息已复制，内容已脱敏，不包含访问 Key 或 API Key。")

    def allow_firewall(self) -> None:
        port = self.current_port()
        rule_name = firewall_rule_name(port)
        ok = messagebox.askyesno(
            APP_NAME,
            f"将创建或更新 Windows 防火墙持久入站规则：\n\n{rule_name}\n\n"
            f"放行端口：TCP {port}\n"
            "作用范围：Private, Public\n\n"
            "系统会弹出管理员权限确认窗口。",
        )
        if not ok:
            return
        try:
            launch_firewall_rule_elevation(port)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.log(f"firewall elevation requested: {rule_name}")
        messagebox.showinfo(APP_NAME, "已请求管理员放行。确认 UAC 后，规则会持久保存在 Windows 防火墙里。")

    def copy_key(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.access_key)
        self.log("access key copied to clipboard")

    def regenerate_key(self) -> None:
        if self.server:
            messagebox.showinfo(APP_NAME, "请先停止服务，再重新生成 Key。")
            return
        self.access_key = write_new_access_key()
        self.key_var.set(self.access_key)
        self.key_status_var.set(self.mask_access_key(self.access_key))
        self.update_qr()
        self.log("access key regenerated")

    def open_local_url(self) -> None:
        webbrowser.open(self.make_urls()[0])

    def show_window(self) -> None:
        self.root.deiconify()
        try:
            self.root.state("normal")
        except tk.TclError:
            pass
        self.root.lift()
        self.root.focus_force()

    def hide_to_tray(self) -> None:
        if not self.tray_available:
            self.root.iconify()
            self.log("tray unavailable; window minimized instead of exiting")
            return
        self.root.iconify()
        self.log("window minimized; tray icon remains available")

    def open_prompt_library_dir(self) -> None:
        try:
            ensure_prompt_library()
            if IS_WINDOWS:
                os.startfile(str(DATA_DIR))
            else:
                webbrowser.open(DATA_DIR.as_uri())
            self.log(f"prompt library opened: {PROMPT_LIBRARY_FILE}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"打开词库目录失败：{exc}")

    def check_update(self, silent: bool = False) -> None:
        if not silent:
            self.set_status("starting", "正在检查更新", "服务仍可继续使用，正在读取更新清单。", "检查中")
            if hasattr(self, "update_status_var"):
                self.update_status_var.set("正在检查更新")
            self.update_button.configure(state="disabled")
        threading.Thread(target=lambda: self._check_update_worker(silent), daemon=True).start()

    def check_update_from_tray(self) -> None:
        self.show_window()
        self.check_update(silent=False)

    def _check_update_worker(self, silent: bool) -> None:
        try:
            result = check_for_update()
        except Exception as exc:
            result = {"error": str(exc), "configured": True, "available": False}
        self.root.after(0, lambda: self._show_update_result(result, silent))

    def _show_update_result(self, result: dict, silent: bool) -> None:
        if not silent:
            self.update_button.configure(state="normal")
        if result.get("available"):
            version = result.get("version", "")
            notes = result.get("notes", "")
            url = result.get("url", "")
            lines = [f"检测到新版本：{version}"]
            if notes:
                lines.append("")
                lines.append(notes)
            if url:
                lines.append("")
                lines.append("是否下载并安装？软件会自动关闭，并在更新后重新打开。")
                if messagebox.askyesno(APP_NAME, "\n".join(lines)):
                    self.install_update(result)
            else:
                messagebox.showinfo(APP_NAME, "\n".join(lines))
            self.log(f"update available: {version}")
            if hasattr(self, "update_status_var"):
                self.update_status_var.set(f"检测到新版本 {version}")
            self.set_status("warning", f"检测到新版本 {version}", "建议完成手头输入后再安装更新。", "可更新")
            return
        if result.get("error"):
            self.log(f"update check failed: {result['error']}")
            if not silent:
                if hasattr(self, "update_status_var"):
                    self.update_status_var.set("更新检查失败")
                self.set_status("error", "更新检查失败", str(result["error"]), "失败")
                messagebox.showerror(APP_NAME, f"更新检查失败：{result['error']}")
            return
        if not result.get("configured"):
            self.log("update check skipped: no manifest url configured")
            if not silent:
                if hasattr(self, "update_status_var"):
                    self.update_status_var.set("未配置更新源")
                self.set_status("warning", "未配置更新源", "当前仍可正常使用，只是不能自动检测新版本。", "未配置")
                messagebox.showinfo(
                    APP_NAME,
                    f"未配置更新源。\n\n可设置环境变量 {UPDATE_MANIFEST_ENV}，或在 {UPDATE_URL_FILE} 写入更新清单地址。",
                )
            return
        self.log("already on latest version")
        if hasattr(self, "update_status_var"):
            self.update_status_var.set(f"已是最新版 v{APP_VERSION}")
        if not silent:
            if self.server:
                self.set_status(
                    "running",
                    "服务运行中",
                    f"端口 {self.current_port()} 正在监听。当前已是最新版本 {APP_VERSION}。",
                    "可用",
                )
            else:
                self.set_status("stopped", "服务未启动", f"当前已是最新版本 {APP_VERSION}。", "待启动")
            messagebox.showinfo(APP_NAME, f"已是最新版本：{APP_VERSION}")

    def install_update(self, result: dict) -> None:
        try:
            target_exe = current_app_executable()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.set_status("starting", "正在下载更新", "下载完成后会自动启动更新脚本并重启软件。", "下载中")
        self.update_button.configure(state="disabled")
        threading.Thread(
            target=lambda: self._install_update_worker(result, target_exe),
            daemon=True,
        ).start()

    def _install_update_worker(self, result: dict, target_exe: Path) -> None:
        try:
            package = download_update_package(
                str(result.get("url", "")),
                str(result.get("version", "")),
                str(result.get("sha256", "")),
            )
            script = write_update_script()
            launch_update_script(script, package, target_exe)
        except Exception as exc:
            self.root.after(0, lambda: self._show_update_install_error(str(exc)))
            return
        self.root.after(0, lambda: self._close_for_update(str(result.get("version", ""))))

    def _show_update_install_error(self, error: str) -> None:
        self.update_button.configure(state="normal")
        self.set_status("error", "自动更新失败", error, "失败")
        self.log(f"update install failed: {error}")
        messagebox.showerror(APP_NAME, f"自动更新失败：{error}")

    def _close_for_update(self, version: str) -> None:
        self.set_status("starting", "正在安装更新", f"正在切换到版本 {version}，软件会自动重启。", "安装中")
        self.log(f"update installer started: {version}")
        messagebox.showinfo(APP_NAME, "更新程序已启动。当前软件会关闭，更新完成后会自动重新打开。")
        self.quit_app()

    def quit_app(self) -> None:
        self.log("app quit requested")
        if getattr(self, "main_preview_refresh_after_id", None):
            self.root.after_cancel(self.main_preview_refresh_after_id)
            self.main_preview_refresh_after_id = None
        if getattr(self, "tray_icon", None):
            self.tray_icon.remove()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self.root.destroy()


def run_server_only(port: int) -> None:
    access_key = read_or_create_access_key()
    refresh_lan_update_manifest_url(port)
    server = BridgeServer(("0.0.0.0", port), BridgeRequestHandler, access_key)
    print(f"{APP_NAME} listening on {port}")
    for url in [build_access_url(host, port, access_key) for host in get_mobile_access_hosts()]:
        print(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--server-only", action="store_true")
    args = parser.parse_args()
    if args.server_only:
        run_server_only(args.port)
        return
    if not IS_WINDOWS:
        messagebox.showerror(APP_NAME, "当前程序仅支持 Windows 粘贴控制。")
        return
    BridgeGui().run()


if __name__ == "__main__":
    raise SystemExit(main())




