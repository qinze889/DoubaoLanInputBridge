"""Opt-in live native test. Only sends keys when this test window is frontmost.

Run with .venv/bin/python scripts/smoke_macos.py. Never import into pytest.
Uses a temporary data directory and restores the previous system clipboard.
"""
import os
import sys
import tempfile
import threading
import http.client
import json
from pathlib import Path

scratch = tempfile.TemporaryDirectory(prefix='shengjian-smoke-')
os.environ['DOUBAO_BRIDGE_DATA_DIR'] = scratch.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QTextEdit
from AppKit import NSPasteboard, NSPasteboardItem, NSWorkspace, NSRunningApplication, NSApplicationActivateIgnoringOtherApps
from Foundation import NSData
from PIL import Image
import gui_app as bridge
import mac_platform as mac

app = QApplication([])
app.setApplicationName('声笺自检')
window = QTextEdit()
window.setWindowTitle('声笺 Mac 原生粘贴自检')
window.setPlaceholderText('此窗口用于本次自检；不会向其他应用输入内容。')
window.resize(600, 280)
board = NSPasteboard.generalPasteboard()
snapshot = []
for item in board.pasteboardItems() or []:
    snapshot.append({kind: bytes(item.dataForType_(kind)) for kind in item.types() if item.dataForType_(kind) is not None})
service = bridge.BridgeServer(('127.0.0.1', 0), bridge.BridgeRequestHandler, 'live-test-key')
threading.Thread(target=service.serve_forever, daemon=True).start()
result = {'ok': False}
text = '声笺 macOS 原生粘贴验证 😀\n第二行'


def restore():
    service.shutdown()
    service.server_close()
    board.clearContents()
    items = []
    for values in snapshot:
        item = NSPasteboardItem.alloc().init()
        for kind, data in values.items():
            item.setData_forType_(NSData.dataWithBytes_length_(data, len(data)), kind)
        items.append(item)
    if items:
        board.writeObjects_(items)
    scratch.cleanup()


def prepare_request():
    app.inputMethod().reset()
    window.clear()
    threading.Thread(target=send_request, daemon=True).start()


def send_request():
    try:
        with mac.objc.autorelease_pool():
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is None or front.processIdentifier() != os.getpid():
                raise RuntimeError('自检窗口未处于前台，已取消键盘测试')
        connection = http.client.HTTPConnection('127.0.0.1', service.server_port, timeout=4)
        connection.request('POST', '/send', json.dumps({'key': 'live-test-key', 'text': text, 'press_enter': False}), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        result['http'] = response.status
        result['response'] = json.loads(response.read())
        connection.close()
    except Exception as exc:
        result['error'] = str(exc)


def begin():
    try:
        mac.require_accessibility()
        image_path = Path(scratch.name) / '图片 test.png'
        Image.new('RGB', (4, 4), 'green').save(image_path)
        mac.set_clipboard_files([image_path])
        assert mac.NSPasteboardTypeTIFF in board.types()
        assert 'public.file-url' in board.types()
        result['image_clipboard'] = True
        window.raise_()
        window.activateWindow()
        window.setFocus()
        NSRunningApplication.currentApplication().activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        QTimer.singleShot(500, prepare_request)
        QTimer.singleShot(2000, finish)
    except Exception as exc:
        result['error'] = str(exc)
        finish()


def finish():
    result['text_pasted'] = window.toPlainText() == text
    if not result['text_pasted']:
        result['active'] = window.isActiveWindow()
        result['focus'] = window.hasFocus()
    result['ok'] = result.get('http') == 200 and result['text_pasted'] and result.get('image_clipboard', False)
    # Output statuses only; pairing key, received text and response are not logged.
    print(json.dumps({k: v for k, v in result.items() if k != 'response'}, ensure_ascii=False))
    restore()
    app.exit(0 if result['ok'] else 1)

window.show()
QTimer.singleShot(300, begin)
raise SystemExit(app.exec())
