import os
import queue
import sys
import threading
import time
import webbrowser
import ctypes
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
SRC_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
for tool_dir in ("pyside6", "qrcode"):
    path = TOOLS_ROOT / tool_dir
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QFileDialog,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTextEdit,
    QInputDialog,
    QMenu,
    QVBoxLayout,
    QWidget,
)

import gui_app as bridge


APP_NAME = bridge.APP_NAME
APP_VERSION = bridge.APP_VERSION
SINGLE_INSTANCE_NAME = f"{bridge.APP_ID}.qt.main.{APP_VERSION}"
PREVIEW_AUTO_REFRESH_MS = 5000
PREVIEW_TITLE_LIMIT = 96

if os.name == "nt":
    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _SW_RESTORE = 9
    _USER32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _USER32.ShowWindow.restype = ctypes.c_int
    _USER32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    _USER32.SetForegroundWindow.restype = ctypes.c_int
    _USER32.BringWindowToTop.argtypes = [ctypes.c_void_p]
    _USER32.BringWindowToTop.restype = ctypes.c_int


class SingleInstanceGuard:
    def __init__(self, name: str):
        self.name = name
        self.server = QLocalServer()
        self.activate_callback = None
        self.is_secondary = self._notify_existing_instance()
        if self.is_secondary:
            return
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.is_secondary = self._notify_existing_instance()
            return
        self.server.newConnection.connect(self._handle_new_connection)

    def _notify_existing_instance(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(180):
            socket.abort()
            return False
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(180)
        socket.disconnectFromServer()
        return True

    def _handle_new_connection(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readAll()
            socket.disconnectFromServer()
            socket.deleteLater()
        if self.activate_callback:
            QTimer.singleShot(0, self.activate_callback)

    def set_activate_callback(self, callback) -> None:
        self.activate_callback = callback

    def close(self) -> None:
        if self.server.isListening():
            self.server.close()
            QLocalServer.removeServer(self.name)


def app_icon() -> QIcon:
    path = bridge.app_icon_path()
    return QIcon(str(path)) if path.exists() else QIcon()


def qr_pixmap(text: str, scale: int = 8) -> QPixmap:
    matrix = bridge.qr_matrix(text)
    size = len(matrix) * scale
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.fillRect(0, 0, size, size, QColor("#ffffff"))
    painter.setBrush(QColor("#111111"))
    painter.setPen(Qt.PenStyle.NoPen)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                painter.drawRect(x * scale, y * scale, scale, scale)
    painter.end()
    return QPixmap.fromImage(image)


def image_thumbnail(record: dict, size: QSize = QSize(76, 54)) -> QPixmap | None:
    path = bridge.first_image_history_path(record)
    if path is None:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def compact_preview_text(value: object, limit: int = PREVIEW_TITLE_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def display_qr_target(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "局域网地址"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}"


def default_file_picker_dir() -> str:
    documents = Path.home() / "Documents"
    if documents.exists():
        return str(documents)
    return str(Path.home())


class PreviewCard(QFrame):
    def __init__(self, parent, record: dict, on_select, on_activate, on_open_folder):
        super().__init__(parent)
        self.record = record
        self.on_select = on_select
        self.on_activate = on_activate
        self.on_open_folder = on_open_folder
        self.setObjectName("previewCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(82)
        self.setProperty("selected", False)

        preview = bridge.history_record_preview(record)
        kind_value = str(preview.get("kind", ""))
        kind_style_map = {
            "文字": "text",
            "图片": "image",
            "视频": "video",
            "媒体": "media",
            "混合": "mixed",
        }
        kind_style = kind_style_map.get(kind_value, "file")
        self.setProperty("kind", kind_style)
        ts = bridge.format_history_timestamp(record.get("ts"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(12)

        thumb = QLabel()
        thumb.setObjectName("previewThumb")
        thumb.setProperty("kind", kind_style)
        thumb.setFixedSize(76, 54)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = image_thumbnail(record)
        if pixmap:
            thumb.setPixmap(pixmap)
        else:
            thumb.setText(kind_value[:2])
        layout.addWidget(thumb)

        text_box = QVBoxLayout()
        full_preview = str(preview.get("preview", ""))
        title = QLabel(compact_preview_text(full_preview))
        title.setObjectName("previewTitle")
        title.setWordWrap(True)
        title.setToolTip(full_preview)
        title.setMaximumHeight(44)
        meta = QLabel(f"{ts}  ·  {preview.get('info', '')}")
        meta.setObjectName("previewMeta")
        meta.setWordWrap(False)
        text_box.addWidget(title)
        text_box.addWidget(meta)
        layout.addLayout(text_box, 1)

        kind = QLabel(kind_value)
        kind.setObjectName("previewKind")
        kind.setProperty("kind", kind_style)
        layout.addWidget(kind)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        primary = QPushButton("复制" if record.get("type") == "text" else "打开")
        primary.setObjectName("miniButton")
        primary.clicked.connect(lambda: self.on_activate(self.record))
        actions.addWidget(primary)
        if record.get("type") == "file":
            folder = QPushButton("文件夹")
            folder.setObjectName("miniButton")
            folder.clicked.connect(lambda: self.on_open_folder(self.record))
            actions.addWidget(folder)
        layout.addLayout(actions)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_select(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_activate(self.record)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.record.get("type") == "text":
            copy_action = menu.addAction("复制文字")
            copy_action.triggered.connect(lambda: self.on_activate(self.record))
        else:
            open_action = menu.addAction("打开文件")
            open_action.triggered.connect(lambda: self.on_activate(self.record))
            folder_action = menu.addAction("打开所在文件夹")
            folder_action.triggered.connect(lambda: self.on_open_folder(self.record))
        menu.exec(event.globalPos())


class QrDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("扫码连接手机")
        self.setMinimumSize(520, 720)
        self.setWindowIcon(app_icon())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        title = QLabel("扫码连接手机")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("手机和电脑在同一 Wi-Fi 下，扫码即可发送文字、图片、视频和文件。访问密钥已隐藏。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr = QLabel()
        self.qr.setObjectName("qrBox")
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.link = QLabel()
        self.link.setObjectName("qrLink")
        self.link.setWordWrap(True)
        self.link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check_box = QFrame()
        check_box.setObjectName("selfCheckBox")
        check_layout = QVBoxLayout(check_box)
        check_layout.setContentsMargins(12, 10, 12, 10)
        check_layout.setSpacing(5)
        check_title = QLabel("连接自检")
        check_title.setObjectName("boxTitle")
        self.health = QLabel()
        self.health.setObjectName("muted")
        self.health.setWordWrap(True)
        check_hint = QLabel("能看到 ok=true 说明网络通；打不开通常是不同 Wi-Fi、路由器 AP 隔离或 Windows 防火墙拦截。Wi-Fi 自动连接二维码需要明文 Wi-Fi 密码，当前不自动生成。")
        check_hint.setObjectName("muted")
        check_hint.setWordWrap(True)
        check_layout.addWidget(check_title)
        check_layout.addWidget(self.health)
        check_layout.addWidget(check_hint)
        actions = QHBoxLayout()
        refresh_btn = QPushButton("刷新二维码")
        refresh_btn.setObjectName("primaryButton")
        refresh_btn.clicked.connect(self.refresh_access_key)
        copy_btn = QPushButton("复制扫码链接")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.parent_window.mobile_url()))
        check_btn = QPushButton("复制自检信息")
        check_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.parent_window.connection_self_check()))
        local_btn = QPushButton("打开本机页面")
        local_btn.clicked.connect(lambda: webbrowser.open(parent.local_url()))
        actions.addWidget(refresh_btn)
        actions.addWidget(copy_btn)
        actions.addWidget(check_btn)
        actions.addWidget(local_btn)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.qr, 1)
        layout.addWidget(self.link)
        layout.addWidget(check_box)
        layout.addLayout(actions)
        self.refresh_qr()

    def refresh_qr(self) -> None:
        url = self.parent_window.mobile_url()
        self.qr.setPixmap(qr_pixmap(url, 9))
        self.link.setText(f"v{APP_VERSION} · 局域网扫码链接已生成 · {display_qr_target(url)}")
        self.health.setText(f"手机先测：{self.parent_window.health_url()}")

    def refresh_access_key(self) -> None:
        self.parent_window.regenerate_access_key()
        self.refresh_qr()
        QMessageBox.information(self, APP_NAME, "二维码已刷新。旧二维码和旧链接会立即失效，请用手机重新扫码。")


class ManageDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("管理")
        self.setMinimumSize(460, 460)
        self.setWindowIcon(app_icon())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("管理")
        title.setObjectName("dialogTitle")
        hint = QLabel("常用维护入口。低频诊断和敏感操作已收起。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

        version_line = QLabel(f"当前版本 v{APP_VERSION}  ·  Key {bridge.BridgeGui.mask_access_key(parent.access_key)}")
        version_line.setObjectName("muted")
        layout.addWidget(version_line)

        quick = QFrame()
        quick.setObjectName("manageCompactGroup")
        quick_grid = QGridLayout(quick)
        quick_grid.setContentsMargins(10, 10, 10, 10)
        quick_grid.setSpacing(8)
        actions = [
            ("检查更新", "读取本地更新源", lambda: parent.check_update(False), False),
            ("配置", "MiniMax / 更新源", parent.show_config, False),
            ("共享目录", "电脑发给手机下载", parent.open_mobile_share_folder, False),
            ("完整历史", "查看运行数据", parent.open_history_folder, False),
        ]
        for index, (title_text, body, callback, primary) in enumerate(actions):
            quick_grid.addWidget(
                self._action_tile(title_text, body, callback, primary=primary),
                index // 2,
                index % 2,
            )
        layout.addWidget(quick)

        firewall = self._action_tile(
            "放行防火墙",
            "手机同 Wi-Fi 仍连不上时使用",
            parent.allow_firewall,
            primary=True,
        )
        firewall.setObjectName("manageFirewallTile")
        layout.addWidget(firewall)

        self.more_button = QPushButton("更多工具")
        self.more_button.setObjectName("secondaryButton")
        self.more_button.setCheckable(True)
        self.more_button.clicked.connect(self.toggle_more_tools)
        layout.addWidget(self.more_button)

        self.advanced_frame = QFrame()
        self.advanced_frame.setObjectName("manageCompactGroup")
        advanced = QGridLayout(self.advanced_frame)
        advanced.setContentsMargins(10, 10, 10, 10)
        advanced.setSpacing(8)
        advanced_actions = [
            ("复制 Key", "当前访问密钥", parent.copy_key),
            ("运行自检", "复制脱敏自检报告", parent.copy_self_check),
            ("复制诊断", "复制脱敏诊断信息", parent.copy_diagnostics),
            ("运行日志", "查看本次运行日志", parent.show_logs),
            ("复制连接", "可信设备间使用", parent.copy_mobile_url),
        ]
        for index, (title_text, body, callback) in enumerate(advanced_actions):
            advanced.addWidget(self._action_tile(title_text, body, callback), index // 2, index % 2)
        self.advanced_frame.hide()
        layout.addWidget(self.advanced_frame)
        layout.addStretch(1)

    def _action_tile(self, title: str, body: str, callback, primary: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName("manageActionTile")
        tile = QVBoxLayout(frame)
        tile.setContentsMargins(12, 10, 12, 10)
        tile.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("boxTitle")
        body_label = QLabel(body)
        body_label.setObjectName("muted")
        body_label.setWordWrap(True)
        button = QPushButton(title)
        button.setObjectName("primaryButton" if primary else "miniButton")
        button.clicked.connect(callback)
        tile.addWidget(title_label)
        tile.addWidget(body_label)
        tile.addWidget(button)
        return frame

    def toggle_more_tools(self) -> None:
        expanded = self.more_button.isChecked()
        self.advanced_frame.setVisible(expanded)
        self.more_button.setText("收起工具" if expanded else "更多工具")


class LogDialog(QDialog):
    def __init__(self, parent, lines: list[str]):
        super().__init__(parent)
        self.setWindowTitle("运行日志")
        self.setMinimumSize(620, 420)
        self.setWindowIcon(app_icon())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel("运行日志")
        title.setObjectName("dialogTitle")
        hint = QLabel("仅显示本次窗口运行期间的最近日志。完整日志保存在本机应用数据目录。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        text = QTextEdit()
        text.setObjectName("logBox")
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines[-200:]) if lines else "暂无运行日志")
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(text, 1)


class BridgeQtWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1060, 720)
        self.setMinimumSize(960, 640)

        self.access_key = bridge.read_or_create_access_key()
        self.log_queue = queue.Queue()
        self.server = None
        self.port = bridge.DEFAULT_PORT
        self.selected_preview_card = None
        self.service_state = "stopped"
        self.log_lines = []

        self._build_ui()
        self._build_tray()
        self.apply_status("stopped", "待启动", "服务未启动", "点击启动后，手机即可扫码发送文字、图片、视频和文件。")
        self.update_service_controls("stopped")

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.drain_logs)
        self.log_timer.start(200)
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.refresh_preview)
        self.preview_timer.start(PREVIEW_AUTO_REFRESH_MS)
        QTimer.singleShot(120, self.start_server)
        QTimer.singleShot(1500, lambda: self.check_update(silent=True))

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(210)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(22, 26, 16, 22)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("muted")
        guide = QLabel("连接摘要\n\n服务会自动启动。\n端口占用自动顺延。\n手机扫码后即可发送。")
        guide.setObjectName("guideBox")
        self.side_status = QLabel("服务未启动")
        self.side_status.setObjectName("sideStatus")
        side.addWidget(title)
        side.addWidget(version)
        side.addSpacing(18)
        side.addWidget(guide)
        side.addStretch(1)
        side.addWidget(QLabel("当前状态"))
        side.addWidget(self.side_status)
        shell.addWidget(self.sidebar)

        center = QFrame()
        center.setObjectName("panel")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(24, 24, 24, 24)
        header = QHBoxLayout()
        header_text = QVBoxLayout()
        h1 = QLabel("最近内容预览")
        h1.setObjectName("pageTitle")
        sub = QLabel("最近 10 条文字、图片、视频和文件。双击文字复制，双击文件打开。")
        sub.setObjectName("muted")
        self.refresh_status = QLabel("自动刷新中 · 每 5 秒 · 上次刷新：等待首次刷新")
        self.refresh_status.setObjectName("refreshStatus")
        header_text.addWidget(h1)
        header_text.addWidget(sub)
        header_text.addWidget(self.refresh_status)
        refresh_btn = QPushButton("立即刷新")
        refresh_btn.clicked.connect(self.refresh_preview)
        header.addLayout(header_text, 1)
        header.addWidget(refresh_btn)
        center_layout.addLayout(header)

        search_row = QHBoxLayout()
        search_badge = QLabel("搜索")
        search_badge.setObjectName("searchBadge")
        self.history_search = QLineEdit()
        self.history_search.setObjectName("historySearch")
        self.history_search.setPlaceholderText("搜索历史：输入文字、文件名或类型")
        self.history_search.textChanged.connect(self.refresh_preview)
        clear_search_btn = QPushButton("清除搜索")
        clear_search_btn.setObjectName("miniButton")
        clear_search_btn.clicked.connect(self.history_search.clear)
        search_row.addWidget(search_badge)
        search_row.addWidget(self.history_search, 1)
        search_row.addWidget(clear_search_btn)
        center_layout.addLayout(search_row)

        self.preview_area = QScrollArea()
        self.preview_area.setWidgetResizable(True)
        self.preview_area.setObjectName("previewArea")
        self.preview_body = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_body)
        self.preview_layout.setContentsMargins(0, 12, 0, 0)
        self.preview_layout.setSpacing(8)
        self.preview_layout.addStretch(1)
        self.preview_area.setWidget(self.preview_body)
        center_layout.addWidget(self.preview_area, 1)
        shell.addWidget(center, 1)

        right = QFrame()
        right.setObjectName("panel")
        right.setFixedWidth(330)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 20, 18, 18)
        right_layout.setSpacing(12)
        status_title = QLabel("连接手机")
        status_title.setObjectName("sectionTitle")
        self.status_card = QLabel()
        self.status_card.setObjectName("statusCard")
        self.status_card.setWordWrap(True)
        scan_side_btn = QPushButton("扫码连接手机")
        scan_side_btn.setObjectName("primaryButton")
        scan_side_btn.clicked.connect(self.show_qr)
        publish_btn = QPushButton("发布给手机")
        publish_btn.setObjectName("primaryButton")
        publish_btn.clicked.connect(self.show_publish_menu)
        self.service_button = QPushButton("启动服务")
        self.service_button.setObjectName("secondaryButton")
        self.service_button.clicked.connect(self.toggle_server)
        manage_btn = QPushButton("管理")
        manage_btn.setObjectName("secondaryButton")
        manage_btn.clicked.connect(self.show_manage)
        for widget in (status_title, self.status_card, scan_side_btn, publish_btn, self.service_button, manage_btn):
            right_layout.addWidget(widget)
        right_layout.addStretch(1)
        shell.addWidget(right)

        self.setStyleSheet(STYLE)
        self.refresh_preview()

    def _row(self, title: str, body: str, button_text: str, callback) -> QFrame:
        frame = QFrame()
        frame.setObjectName("softBox")
        layout = QGridLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        title_label = QLabel(title)
        title_label.setObjectName("boxTitle")
        body_label = QLabel(body)
        body_label.setObjectName("muted")
        button = QPushButton(button_text)
        button.clicked.connect(callback)
        layout.addWidget(title_label, 0, 0)
        layout.addWidget(body_label, 1, 0)
        layout.addWidget(button, 0, 1, 2, 1)
        return frame

    def _button_row(self, title: str, button_text: str, callback) -> QFrame:
        return self._row(title, "", button_text, callback)

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show_normal)
        copy_action = QAction("复制扫码链接", self)
        copy_action.triggered.connect(self.copy_mobile_url)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def on_tray_activated(self, reason) -> None:
        self.log(f"tray activated: {reason}")
        if reason == QSystemTrayIcon.ActivationReason.Context:
            return
        self.show_normal()

    def mobile_url(self) -> str:
        self.sync_access_key()
        return bridge.build_access_url(bridge.preferred_lan_host(), self.port, self.access_key)

    def health_url(self) -> str:
        return bridge.build_health_url(bridge.preferred_lan_host(), self.port)

    def connection_self_check(self) -> str:
        return bridge.build_connection_self_check(self.port, bool(self.server), bridge.preferred_lan_host())

    def local_url(self) -> str:
        self.sync_access_key()
        return bridge.build_access_url("127.0.0.1", self.port, self.access_key)

    def log(self, message: str) -> None:
        self.log_queue.put(message)

    def drain_logs(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_lines.append(f"{time.strftime('%H:%M:%S')}  {message}")
            self.log_lines = self.log_lines[-200:]

    def apply_status(self, theme: str, badge: str, title: str, detail: str) -> None:
        self.status_card.setText(f"{title}\n{detail}")
        self.status_card.setProperty("state", theme)
        self.status_card.style().unpolish(self.status_card)
        self.status_card.style().polish(self.status_card)
        self.side_status.setText(title)

    def update_service_controls(self, state: str) -> None:
        self.service_state = state
        config = {
            "running": ("停止服务", "dangerGhostButton", True),
            "stopping": ("正在停止...", "secondaryButton", False),
            "stopped": ("启动服务", "secondaryButton", True),
            "starting": ("正在启动...", "secondaryButton", False),
            "error": ("启动服务", "secondaryButton", True),
        }.get(state, ("启动服务", "secondaryButton", True))
        text, object_name, enabled = config
        self.service_button.setText(text)
        self.service_button.setObjectName(object_name)
        self.service_button.setEnabled(enabled)
        self.service_button.style().unpolish(self.service_button)
        self.service_button.style().polish(self.service_button)
        self.service_button.update()

    def confirm_stop_server(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText("停止服务后，手机将暂时无法发送或下载文件。")
        dialog.setInformativeText("确定要停止局域网互传服务吗？")
        stop_button = dialog.addButton("停止服务", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() is stop_button

    def toggle_server(self) -> None:
        if self.service_state == "stopping":
            return
        if self.server:
            if not self.confirm_stop_server():
                return
            self.stop_server()
            return
        self.start_server()

    def start_server(self) -> None:
        if self.server or self.service_state == "stopping":
            return
        self.update_service_controls("starting")
        self.apply_status("stopped", "启动中", "正在启动服务", "正在准备局域网扫码入口。")
        selected = self.port
        last_error = ""
        for candidate in range(selected, selected + bridge.PORT_AUTO_INCREMENT_LIMIT + 1):
            if bridge.is_tcp_port_in_use(candidate):
                last_error = f"端口 {candidate} 已被其他服务占用"
                self.log(f"port {candidate} already in use; trying next port")
                continue
            candidate_server = None
            try:
                candidate_server = bridge.BridgeServer(
                    ("0.0.0.0", candidate),
                    bridge.BridgeRequestHandler,
                    self.access_key,
                    self.log_queue,
                )
            except OSError as exc:
                last_error = str(exc)
                continue
            threading.Thread(target=candidate_server.serve_forever, daemon=True).start()
            verified, detail = bridge.wait_for_bridge_server_identity(candidate, os.getpid())
            if not verified:
                last_error = f"端口 {candidate} 启动自检失败：{detail}"
                self.log(last_error)
                candidate_server.shutdown()
                candidate_server.server_close()
                continue
            self.server = candidate_server
            self.port = candidate
            break
        if not self.server:
            self.update_service_controls("error")
            self.apply_status("error", "失败", "服务启动失败", last_error)
            QMessageBox.critical(self, APP_NAME, last_error)
            return
        bridge.write_lan_update_manifest_url(self.port)
        self.update_service_controls("running")
        self.apply_status("running", "可用", "服务运行中", "手机扫码后即可发送文字、图片、视频和文件。")
        self.log(f"server started port={self.port}")

    def stop_server(self) -> None:
        if not self.server:
            self.update_service_controls("stopped")
            self.apply_status("stopped", "已停止", "服务已停止", "点击启动重新开启手机互传。")
            return
        server = self.server
        self.server = None
        self.update_service_controls("stopping")
        self.apply_status("stopped", "停止中", "正在停止服务", "正在关闭局域网互传入口。")
        QApplication.processEvents()
        try:
            server.shutdown()
            server.server_close()
        except Exception as exc:
            self.update_service_controls("error")
            self.apply_status("error", "失败", "服务停止失败", str(exc))
            self.log(f"server stop failed: {exc}")
            return
        self.log("server stopped")
        self.update_service_controls("stopped")
        self.apply_status("stopped", "已停止", "服务已停止", "点击启动重新开启手机互传。")

    def refresh_preview(self) -> None:
        selected_id = str(self.selected_preview_card.record.get("id", "")) if self.selected_preview_card else ""
        self.selected_preview_card = None
        while self.preview_layout.count() > 1:
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        records = bridge.search_clipboard_history(query, bridge.HISTORY_WINDOW_LIMIT)
        if hasattr(self, "refresh_status"):
            self.refresh_status.setText(f"自动刷新中 · 每 5 秒 · 上次刷新：{time.strftime('%Y年%m月%d日 %H:%M:%S')}")
        if not records:
            empty = QLabel("没有匹配的历史记录" if query else "还没有历史记录")
            empty.setObjectName("emptyPreview")
            self.preview_layout.insertWidget(0, empty)
            return
        for record in records:
            card = PreviewCard(self.preview_body, record, self.select_preview_card, self.activate_record, self.open_record_folder)
            if selected_id and str(record.get("id", "")) == selected_id:
                card.setProperty("selected", True)
                card.style().unpolish(card)
                card.style().polish(card)
                self.selected_preview_card = card
            self.preview_layout.insertWidget(self.preview_layout.count() - 1, card)

    def select_preview_card(self, card: PreviewCard) -> None:
        if self.selected_preview_card and self.selected_preview_card is not card:
            self.selected_preview_card.setProperty("selected", False)
            self.selected_preview_card.style().unpolish(self.selected_preview_card)
            self.selected_preview_card.style().polish(self.selected_preview_card)
        self.selected_preview_card = card
        card.setProperty("selected", True)
        card.style().unpolish(card)
        card.style().polish(card)

    def activate_record(self, record: dict) -> None:
        try:
            if record.get("type") == "text":
                QApplication.clipboard().setText(str(record.get("text", "")))
                self.log("preview text copied")
            else:
                bridge.open_history_file_item(str(record.get("id", "")), mode="file")
                self.log("preview file opened")
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def open_record_folder(self, record: dict) -> None:
        if record.get("type") != "file":
            return
        try:
            bridge.open_history_file_item(str(record.get("id", "")), mode="folder")
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def show_qr(self) -> None:
        QrDialog(self).exec()

    def copy_mobile_url(self) -> None:
        QApplication.clipboard().setText(self.mobile_url())
        self.log("mobile url copied")

    def copy_key(self) -> None:
        self.sync_access_key()
        QApplication.clipboard().setText(self.access_key)
        self.log("access key copied")

    def sync_access_key(self) -> str:
        latest_key = bridge.current_access_key(self.access_key)
        if latest_key != self.access_key:
            self.access_key = latest_key
            if self.server:
                self.server.access_key = latest_key
            self.log("access key synchronized")
        return self.access_key

    def regenerate_access_key(self) -> str:
        self.access_key = bridge.write_new_access_key()
        if self.server:
            self.server.access_key = self.access_key
        self.log("access key regenerated")
        return self.access_key

    def show_manage(self) -> None:
        ManageDialog(self).exec()

    def show_logs(self) -> None:
        LogDialog(self, self.log_lines).exec()

    def copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(bridge.build_diagnostics_report(self.port, bool(self.server)))
        QMessageBox.information(self, APP_NAME, "诊断信息已复制，内容已脱敏。")

    def copy_self_check(self) -> None:
        report = bridge.build_self_check_report(self.port, bool(self.server))
        QApplication.clipboard().setText(report)
        QMessageBox.information(self, APP_NAME, "自检报告已复制，内容已脱敏。")

    def allow_firewall(self) -> None:
        rule_name = bridge.firewall_rule_name(self.port)
        message = (
            f"将创建或更新 Windows 防火墙持久入站规则：\n\n{rule_name}\n\n"
            f"放行端口：TCP {self.port}\n"
            "作用范围：Private, Public\n\n"
            "系统会弹出管理员权限确认窗口。"
        )
        if QMessageBox.question(self, APP_NAME, message) != QMessageBox.StandardButton.Yes:
            return
        try:
            bridge.launch_firewall_rule_elevation(self.port)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))
            return
        QMessageBox.information(self, APP_NAME, "已请求管理员放行。确认 UAC 后，规则会持久保存在 Windows 防火墙里。")

    def show_config(self) -> None:
        key, ok = QInputDialog.getText(self, APP_NAME, "MiniMax API Key：留空不修改，输入 clear 清除。", QLineEdit.EchoMode.Password)
        if ok:
            value = key.strip()
            if value.lower() == "clear":
                bridge.clear_text_config(bridge.MINIMAX_API_KEY_FILE)
            elif value:
                bridge.write_text_config(bridge.MINIMAX_API_KEY_FILE, value)
        url, ok = QInputDialog.getText(self, APP_NAME, "更新源 URL：留空不修改，输入 clear 清除。", text=bridge.read_update_manifest_url())
        if ok:
            value = url.strip()
            if value.lower() == "clear":
                bridge.clear_text_config(bridge.UPDATE_URL_FILE)
            elif value:
                bridge.write_text_config(bridge.UPDATE_URL_FILE, value)

    def check_update(self, silent: bool = False) -> None:
        result = bridge.check_for_update()
        if result.get("error"):
            if not silent:
                QMessageBox.critical(self, APP_NAME, f"更新检查失败：{result['error']}")
            return
        if not result.get("update_available"):
            if not silent:
                QMessageBox.information(self, APP_NAME, f"已是最新版本：{APP_VERSION}")
            return
        if QMessageBox.question(self, APP_NAME, f"检测到新版本 {result.get('version')}，是否更新？") == QMessageBox.StandardButton.Yes:
            try:
                bridge.begin_update_install(result)
            except Exception as exc:
                QMessageBox.critical(self, APP_NAME, str(exc))

    def open_history_folder(self) -> None:
        bridge.DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(bridge.DATA_DIR))

    def open_mobile_share_folder(self) -> None:
        bridge.MOBILE_SHARE_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(bridge.MOBILE_SHARE_DIR))

    def show_publish_menu(self) -> None:
        menu = QMenu(self)
        text_action = menu.addAction("发布文字")
        file_action = menu.addAction("发布文件")
        button = self.sender()
        pos = button.mapToGlobal(button.rect().bottomLeft()) if isinstance(button, QPushButton) else self.mapToGlobal(self.rect().center())
        action = menu.exec(pos)
        if action is text_action:
            self.publish_text_for_mobile()
        elif action is file_action:
            self.publish_files_for_mobile()

    def publish_text_for_mobile(self) -> None:
        default_text = QApplication.clipboard().text()
        text, ok = QInputDialog.getMultiLineText(self, APP_NAME, "输入要发布给手机的文字：", default_text)
        if not ok:
            return
        try:
            result = bridge.publish_text_for_mobile_download(text)
            self.refresh_preview()
            self.log("published text for mobile download")
            name = result["published"][0]["name"]
            QMessageBox.information(
                self,
                APP_NAME,
                f"已发布文字：{name}\n\n手机打开扫码页面后，在底部“文件缓冲区”点击“刷新”，即可下载。",
            )
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def publish_files_for_mobile(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要发布给手机下载的文件", default_file_picker_dir())
        if not paths:
            return
        try:
            result = bridge.publish_files_for_mobile_download([Path(path) for path in paths])
            self.refresh_preview()
            self.log(f"published {result['files']} files for mobile download")
            QMessageBox.information(
                self,
                APP_NAME,
                f"已发布 {result['files']} 个文件。\n\n手机打开扫码页面后，在底部“文件缓冲区”点击“刷新”，即可下载。",
            )
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def show_normal(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self, 0)
        if os.name == "nt":
            hwnd = int(self.winId())
            _USER32.ShowWindow(hwnd, _SW_RESTORE)
            _USER32.SetForegroundWindow(hwnd)
            _USER32.BringWindowToTop(hwnd)
        self.log("main window activation requested")

    def closeEvent(self, event) -> None:
        if self.tray and self.tray.isVisible():
            self.hide()
            event.ignore()
            return
        self.stop_server()
        super().closeEvent(event)


STYLE = """
QMainWindow, QWidget { background: #f4f7f6; color: #142421; font-family: "Microsoft YaHei UI"; }
#sidebar { background: #e9f2f1; border-right: 1px solid #d7e4e2; }
#panel { background: #ffffff; border: 1px solid #dde7e5; }
#appTitle { font-size: 18px; font-weight: 700; }
#pageTitle { font-size: 30px; font-weight: 800; color: #10231f; }
#sectionTitle { font-size: 18px; font-weight: 800; }
#muted, .QLabel#muted { color: #61716e; }
#guideBox { background: #e2f6f2; border: 1px solid #b8e3dd; border-radius: 10px; padding: 14px; color: #123f39; }
#sideStatus { color: #00796b; font-weight: 800; }
#statusCard { background: #edfff8; border: 1px solid #72dcbf; border-radius: 12px; padding: 14px; font-size: 18px; font-weight: 800; color: #006553; }
#statusCard[state="stopped"] { background: #f8fafc; border-color: #cbd5e1; color: #334155; }
#statusCard[state="error"] { background: #fff1f0; border-color: #fca5a5; color: #b91c1c; }
#softBox { background: #f8fbfb; border: 1px solid #dce8e6; border-radius: 12px; }
#boxTitle { font-weight: 800; color: #162623; }
#refreshStatus { color: #0f766e; font-weight: 700; }
#searchBadge { background: #e7fbf6; border: 1px solid #9edfd4; border-radius: 10px; padding: 8px 12px; color: #04756a; font-weight: 900; }
#manageGroup { background: #fbfdfd; border: 1px solid #dce8e6; border-radius: 12px; }
#manageGroupTitle { color: #10231f; font-weight: 900; font-size: 15px; }
#manageCompactGroup { background: #fbfdfd; border: 1px solid #dce8e6; border-radius: 14px; }
#manageActionTile { background: #ffffff; border: 1px solid #dce8e6; border-radius: 12px; }
#manageActionTile:hover { background: #f4fbfa; border-color: #9edfd4; }
#manageFirewallTile { background: #e7fbf6; border: 1px solid #7ad9cb; border-radius: 14px; }
QPushButton { border: 1px solid #d8e3e1; border-radius: 10px; background: #ffffff; padding: 8px 12px; font-weight: 700; }
QPushButton:hover { background: #f0fbf8; }
#primaryButton { background: #0ea58f; color: white; border-color: #0ea58f; }
#primaryButton:hover { background: #087c70; }
#secondaryButton { background: #ffffff; color: #18423d; border-color: #cddbd9; }
#dangerButton { background: #bd2a21; color: white; border-color: #bd2a21; }
#dangerGhostButton { background: #fff7f7; color: #a11d17; border-color: #f0b7b3; padding: 6px 10px; font-size: 12px; }
#dangerGhostButton:hover { background: #ffe8e7; }
#miniButton { padding: 5px 8px; border-radius: 8px; font-size: 12px; }
#historySearch { background: #ffffff; border: 2px solid #9edfd4; border-radius: 10px; padding: 9px 12px; font-weight: 700; }
#previewArea { border: none; background: #ffffff; }
#previewCard { background: #fbfdfd; border: 1px solid #dce8e6; border-radius: 14px; }
#previewCard[kind="text"] { border-left: 5px solid #0ea58f; }
#previewCard[kind="file"] { border-left: 5px solid #2563eb; }
#previewCard[kind="image"] { border-left: 5px solid #7c3aed; }
#previewCard[kind="video"] { border-left: 5px solid #dc2626; }
#previewCard[kind="media"] { border-left: 5px solid #0891b2; }
#previewCard[kind="mixed"] { border-left: 5px solid #d97706; }
#previewCard:hover { background: #f0fbf8; border-color: #9edfd4; }
#previewCard[selected="true"] { background: #e7fbf6; border: 2px solid #0ea58f; }
#previewThumb { background: #eef5f5; border: 1px solid #dbe8e6; border-radius: 10px; color: #00796b; font-weight: 900; }
#previewThumb[kind="text"] { background: #e7fbf6; border-color: #9edfd4; color: #04756a; }
#previewThumb[kind="file"] { background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; }
#previewThumb[kind="image"] { background: #f5f3ff; border-color: #ddd6fe; color: #6d28d9; }
#previewThumb[kind="video"] { background: #fef2f2; border-color: #fecaca; color: #b91c1c; }
#previewThumb[kind="media"] { background: #ecfeff; border-color: #a5f3fc; color: #0e7490; }
#previewThumb[kind="mixed"] { background: #fff7ed; border-color: #fed7aa; color: #c2410c; }
#previewTitle { font-weight: 800; color: #10231f; }
#previewMeta { color: #61716e; font-size: 12px; }
#previewKind { border-radius: 999px; padding: 4px 8px; font-weight: 900; font-size: 12px; }
#previewKind[kind="text"] { background: #e7fbf6; color: #04756a; }
#previewKind[kind="file"] { background: #eff6ff; color: #1d4ed8; }
#previewKind[kind="image"] { background: #f5f3ff; color: #6d28d9; }
#previewKind[kind="video"] { background: #fef2f2; color: #b91c1c; }
#previewKind[kind="media"] { background: #ecfeff; color: #0e7490; }
#previewKind[kind="mixed"] { background: #fff7ed; color: #c2410c; }
#emptyPreview { background: #fbfdfd; border: 1px solid #dce8e6; border-radius: 14px; padding: 24px; color: #61716e; }
#logBox { background: #fbfdfd; border: 1px solid #dce8e6; border-radius: 10px; }
#dialogTitle { font-size: 24px; font-weight: 800; }
#qrBox { background: white; border: 1px solid #d8e3e1; border-radius: 14px; padding: 16px; }
#qrLink { color: #00796b; font-weight: 800; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 6px 2px 6px 2px; }
QScrollBar::handle:vertical { background: #b8cbc8; border-radius: 5px; min-height: 34px; }
QScrollBar::handle:vertical:hover { background: #7fa6a0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 6px 2px 6px; }
QScrollBar::handle:horizontal { background: #b8cbc8; border-radius: 5px; min-width: 34px; }
QScrollBar::handle:horizontal:hover { background: #7fa6a0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""


def main() -> int:
    if os.name != "nt":
        print("当前程序仅支持 Windows 粘贴控制。")
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    single_instance = SingleInstanceGuard(SINGLE_INSTANCE_NAME)
    if single_instance.is_secondary:
        return 0
    app.aboutToQuit.connect(single_instance.close)
    window = BridgeQtWindow()
    single_instance.set_activate_callback(window.show_normal)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
