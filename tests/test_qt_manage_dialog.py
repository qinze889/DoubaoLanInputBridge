import os
import subprocess
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TOOLS_ROOT = ROOT / "tools"
if not (TOOLS_ROOT / "pyside6" / "PySide6").is_dir():
    git_common = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
    )
    TOOLS_ROOT = git_common.parent / "tools"
for tool_name in ("pyside6", "qrcode"):
    tool_path = TOOLS_ROOT / tool_name
    if tool_path.is_dir() and str(tool_path) not in sys.path:
        sys.path.insert(0, str(tool_path))

import qt_app


class ManageParentStub(qt_app.QWidget):
    def __init__(self):
        super().__init__()
        self.access_key = "test-access-key"
        self.update_owner = None
        self.update_button = None

    def check_update(self, silent=False, dialog_parent=None, source_button=None):
        self.update_owner = dialog_parent
        self.update_button = source_button

    def show_config(self):
        pass

    def open_mobile_share_folder(self):
        pass

    def open_history_folder(self):
        pass

    def allow_firewall(self):
        pass

    def copy_key(self):
        pass

    def copy_self_check(self):
        pass

    def copy_diagnostics(self):
        pass

    def show_logs(self):
        pass

    def copy_mobile_url(self):
        pass


def qt_application():
    return qt_app.QApplication.instance() or qt_app.QApplication([])


def test_manage_update_button_passes_manage_dialog_as_message_owner():
    app = qt_application()
    parent = ManageParentStub()
    dialog = qt_app.ManageDialog(parent)
    update_button = next(button for button in dialog.findChildren(qt_app.QPushButton) if button.text() == "检查更新")

    update_button.click()
    app.processEvents()

    assert parent.update_owner is dialog
    assert parent.update_button is update_button
    dialog.close()
    parent.close()


class UpdateResultStub:
    def __init__(self, owner):
        self._update_check_silent = False
        self._update_check_owner = owner
        self._update_check_button = None
        self.update_check_in_progress = True
        self.logs = []

    def _set_update_check_button(self, checking):
        pass

    def log(self, message):
        self.logs.append(message)


def test_check_update_uses_invoking_dialog_for_result_message(monkeypatch):
    app = qt_application()
    parent = ManageParentStub()
    owner = qt_app.QDialog(parent)
    owner.show()
    app.processEvents()
    captured = {}
    monkeypatch.setattr(
        qt_app.QMessageBox,
        "information",
        lambda message_parent, title, message: captured.update(
            parent=message_parent,
            title=title,
            message=message,
        ),
    )

    window = UpdateResultStub(owner)
    qt_app.BridgeQtWindow._show_update_result(
        window,
        {"configured": True, "available": False, "version": qt_app.APP_VERSION},
    )
    app.processEvents()

    assert captured["parent"] is owner
    assert captured["message"] == f"已是最新版本：{qt_app.APP_VERSION}"
    owner.close()
    parent.close()


def test_update_worker_turns_network_exception_into_visible_result(monkeypatch):
    captured = {}

    class SignalStub:
        def emit(self, result):
            captured.update(result)

    class WorkerStub:
        updateCheckFinished = SignalStub()

    monkeypatch.setattr(qt_app.bridge, "check_for_update", lambda timeout: (_ for _ in ()).throw(OSError("connection refused")))
    monkeypatch.setattr(qt_app.bridge, "read_update_manifest_url", lambda: "http://192.168.1.63:8766/update.json")

    qt_app.BridgeQtWindow._check_update_worker(WorkerStub())

    assert captured["error"] == "connection refused"
    assert captured["configured"] is True
    assert captured["available"] is False


def test_qt_update_flow_uses_manifest_available_field():
    source = (ROOT / "src" / "qt_app.py").read_text(encoding="utf-8")

    assert 'result.get("available")' in source
    assert 'result.get("update_available")' not in source
    assert 'button.setText("检查中..." if checking else "检查更新")' in source
    assert "if self.update_check_in_progress:" in source
    assert "bridge.write_lan_update_manifest_url(self.port)" in source
