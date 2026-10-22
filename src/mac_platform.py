"""Native macOS clipboard, keyboard and network integration.

All pasteboard operations finish synchronously, including on HTTP worker threads.
No AppleScript, shell interpolation or Automation permission is needed.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
from pathlib import Path

import objc
from AppKit import NSPasteboard, NSPasteboardTypeString, NSPasteboardTypeTIFF, NSImage
from Foundation import NSURL
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from Quartz import (
    CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
    kCGEventFlagMaskCommand, kCGHIDEventTap,
)

PASTE_LOCK = threading.RLock()
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


def native_input(request):
    path = os.environ.get('SHENGJIAN_NATIVE_INPUT_SOCKET', '')
    if not path:
        return None
    request = {**request, 'token': os.environ.get('SHENGJIAN_NATIVE_INPUT_TOKEN', '')}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(path)
            connection.sendall(json.dumps(request).encode() + b'\n')
            response = bytearray()
            while b'\n' not in response and len(response) < 8192:
                part = connection.recv(1024)
                if not part:
                    break
                response.extend(part)
            result = json.loads(response)
            if not result.get('ok'):
                raise RuntimeError(result.get('error', '本机输入服务拒绝了请求'))
            return result
    except (OSError, ValueError) as exc:
        raise RuntimeError('声笺原生输入服务未响应，请退出后重新打开应用。') from exc


def accessibility_enabled() -> bool:
    if os.environ.get('SHENGJIAN_NATIVE_INPUT_SOCKET'):
        try:
            return bool(native_input({'operation':'permission'}).get('allowed'))
        except RuntimeError:
            return False
    return bool(AXIsProcessTrusted())


def request_accessibility() -> None:
    if os.environ.get('SHENGJIAN_NATIVE_INPUT_SOCKET'):
        native_input({'operation':'request-permission'})
    else:
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    open_settings("accessibility")


def require_accessibility() -> None:
    if not accessibility_enabled():
        raise RuntimeError("请在 Mac 系统设置 → 隐私与安全性 → 辅助功能中允许“声笺”，再重新发送。开发运行时请允许启动 Python 的终端应用。")


def set_clipboard_text(text: str) -> None:
    with PASTE_LOCK, objc.autorelease_pool():
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        if not board.setString_forType_(text, NSPasteboardTypeString):
            raise RuntimeError("无法写入 Mac 剪贴板")


def set_clipboard_files(paths: list[Path]) -> None:
    resolved = [Path(path).expanduser().resolve(strict=True) for path in paths]
    if not resolved or any(not path.is_file() for path in resolved):
        raise ValueError("请选择存在的普通文件")
    with PASTE_LOCK, objc.autorelease_pool():
        board = NSPasteboard.generalPasteboard()
        urls = [NSURL.fileURLWithPath_(str(path)) for path in resolved]
        board.clearContents()
        if not board.writeObjects_(urls):
            raise RuntimeError("无法把文件写入 Mac 剪贴板")
        # Browsers/chat editors often accept bitmap data rather than file URLs.
        # Keep the file URL for Finder and also provide an image representation.
        if len(resolved) == 1 and resolved[0].suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".tif", ".tiff", ".bmp"}:
            image = NSImage.alloc().initWithContentsOfFile_(str(resolved[0]))
            if image is not None:
                bitmap = image.TIFFRepresentation()
                if bitmap is not None:
                    board.setData_forType_(bitmap, NSPasteboardTypeTIFF)


def _key_press(keycode: int, flags: int = 0) -> None:
    require_accessibility()
    if os.environ.get('SHENGJIAN_NATIVE_INPUT_SOCKET'):
        operation = 'paste' if keycode == 9 and flags == kCGEventFlagMaskCommand else 'enter' if keycode == 36 and flags == 0 else ''
        if not operation:
            raise RuntimeError('不支持的输入操作')
        native_input({'operation': operation})
        return
    down = CGEventCreateKeyboardEvent(None, keycode, True)
    up = CGEventCreateKeyboardEvent(None, keycode, False)
    if down is None or up is None:
        raise RuntimeError("无法创建 Mac 键盘事件")
    CGEventSetFlags(down, flags)
    CGEventSetFlags(up, flags)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


def send_command_v() -> None:
    _key_press(9, kCGEventFlagMaskCommand)


def send_enter() -> None:
    _key_press(36)


def open_path(path: Path) -> None:
    subprocess.run(["/usr/bin/open", str(Path(path).resolve())], check=True, timeout=10)


def open_settings(section: str) -> None:
    urls = {
        "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "network": "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork",
        "firewall": "x-apple.systempreferences:com.apple.preference.security?Firewall",
    }
    subprocess.run(["/usr/bin/open", urls[section]], check=True, timeout=10)


def is_lan_ipv4(host: str) -> bool:
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return False
    return any(address in network for network in PRIVATE_NETWORKS)


def lan_ipv4_addresses() -> list[str]:
    """Read active physical interfaces, avoiding VPN/VM pseudo LAN addresses."""
    try:
        result = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, check=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for block in re.split(r"(?m)(?=^[a-z][a-z0-9]*:)", result.stdout):
        if not re.match(r"(?:en\d+|bridge\d+):", block):
            continue
        if "status: inactive" in block:
            continue
        found.extend(ip for ip in re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)", block) if is_lan_ipv4(ip))
    return list(dict.fromkeys(found))
