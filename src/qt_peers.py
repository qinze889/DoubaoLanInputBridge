"""Machine sharing for the retained Qt desktop entry point."""
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)
import gui_app as bridge


class MachineShareDialog(QDialog):
    completed = Signal(str, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.host_window = parent
        self.invitation = ''
        self.expires = 0
        self.busy = False
        self.jobs_text = ''
        self.setWindowTitle('机器共享 · Mac 与 Windows')
        self.resize(700, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel('机器共享'); title.setStyleSheet('font-size: 24px; font-weight: 700')
        layout.addWidget(title)
        hint = QLabel('Mac 与 Windows 配对后可以双向传文件。跨网络时请在两端开启公网连接。')
        hint.setWordWrap(True); layout.addWidget(hint)
        network = QHBoxLayout()
        self.network = QLabel(); self.network.setTextFormat(Qt.TextFormat.PlainText)
        self.public = QPushButton('开启公网连接')
        self.public.clicked.connect(self.toggle_public)
        network.addWidget(self.network, 1); network.addWidget(self.public); layout.addLayout(network)
        self.error = QLabel(); self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True); self.error.setStyleSheet('color: #a32e35')
        layout.addWidget(self.error)
        invitation_row = QHBoxLayout()
        self.create = QPushButton('生成一次性邀请'); self.create.clicked.connect(self.create_invitation)
        self.copy = QPushButton('复制邀请'); self.copy.setEnabled(False); self.copy.clicked.connect(self.copy_invitation)
        self.expiry = QLabel('邀请 5 分钟内有效，仅使用一次。')
        invitation_row.addWidget(self.create); invitation_row.addWidget(self.copy); invitation_row.addWidget(self.expiry, 1)
        layout.addLayout(invitation_row)
        join_row = QHBoxLayout()
        self.link = QLineEdit(); self.link.setPlaceholderText('粘贴另一台电脑的 shengjian://pair?… 邀请')
        self.join = QPushButton('配对'); self.join.clicked.connect(self.join_machine)
        join_row.addWidget(self.link, 1); join_row.addWidget(self.join); layout.addLayout(join_row)
        layout.addWidget(QLabel('已配对的电脑'))
        self.peers = QListWidget(); layout.addWidget(self.peers, 1)
        actions = QHBoxLayout()
        self.send = QPushButton('发送文件'); self.send.clicked.connect(self.send_files)
        self.remove = QPushButton('解除配对'); self.remove.clicked.connect(self.remove_peer)
        received = QPushButton('接收文件夹'); received.clicked.connect(self.open_received)
        actions.addWidget(self.send); actions.addWidget(self.remove); actions.addStretch(); actions.addWidget(received)
        layout.addLayout(actions)
        layout.addWidget(QLabel('传输任务 · 完成后校验 SHA256'))
        self.jobs = QListWidget(); layout.addWidget(self.jobs, 1)
        self.completed.connect(self.did_complete)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(2000)
        self.refresh()

    def service(self):
        if self.host_window.server is None:
            raise ValueError('请先启动本机服务。')
        return self.host_window.server

    def run(self, action, function):
        if self.busy:
            return
        self.busy = True; self.error.clear(); self.refresh()
        def worker():
            try:
                result = (True, function())
            except Exception as error:
                result = (False, str(error))
            try:
                self.completed.emit(action, result)
            except RuntimeError:
                pass  # Dialog was closed while the request was in progress.
        threading.Thread(target=worker, daemon=True).start()

    def did_complete(self, action, result):
        self.busy = False
        ok, value = result
        if not ok:
            self.error.setText(value)
        elif action == 'invite':
            self.invitation = value['invitation']; self.expires = time.time() + value['expires_in']
            self.copy_invitation()
        elif action == 'join':
            self.link.clear()
        self.refresh()

    def toggle_public(self):
        server = self.service()
        if server.quick_tunnel.status()['phase'] in ('starting', 'ready'):
            self.run('network', server.quick_tunnel.stop)
        else:
            configured = bridge.find_cloudflared(bridge.read_tunnel_config().get('cloudflared_path', ''))
            self.run('network', lambda: server.quick_tunnel.start(server.server_port, configured))

    def create_invitation(self):
        self.run('invite', self.service().peer_manager.invite)

    def copy_invitation(self):
        if self.invitation and time.time() < self.expires:
            QApplication.clipboard().setText(self.invitation)

    def join_machine(self):
        value = self.link.text().strip()
        if value:
            self.run('join', lambda: self.service().peer_manager.join(value))

    def selected_id(self):
        item = self.peers.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def send_files(self):
        ident = self.selected_id()
        if not ident:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, '发送文件到另一台电脑')
        if paths:
            self.run('send', lambda: self.service().peer_manager.send(ident, paths))

    def remove_peer(self):
        ident = self.selected_id()
        if ident:
            self.run('remove', lambda: self.service().peer_manager.remove(ident))

    def open_received(self):
        folder = Path(bridge.DATA_DIR) / 'received'; folder.mkdir(parents=True, exist_ok=True)
        bridge.open_local_path(folder)

    def refresh(self):
        try:
            server = self.service(); snapshot = server.peer_manager.snapshot(); tunnel = server.quick_tunnel.status()
            endpoint = server.peer_manager.endpoint_provider()
            label = '公网已连接' if tunnel['ready'] else '正在连接 Cloudflare…' if tunnel['phase'] == 'starting' else '已配置公网地址' if endpoint.startswith('https:') else '请开启公网连接，或连接局域网' if '127.0.0.1' in endpoint else '局域网连接 · 需同一网络'
            self.network.setText(label)
            self.public.setText('关闭公网连接' if tunnel['phase'] in ('starting', 'ready') else '开启公网连接')
            self.public.setEnabled(not self.busy)
            self.create.setEnabled(not self.busy and tunnel['phase'] != 'starting' and '127.0.0.1' not in endpoint)
            self.join.setEnabled(not self.busy)
            self.copy.setEnabled(bool(self.invitation and time.time() < self.expires))
            if self.invitation:
                self.expiry.setText(f'邀请剩余 {max(0, int(self.expires-time.time()))} 秒' if time.time() < self.expires else '邀请已过期，请重新生成。')
            ident = self.selected_id(); self.peers.clear()
            for peer in snapshot['peers']:
                item = QListWidgetItem(f'{peer["name"]}  ·  已配对'); item.setData(Qt.ItemDataRole.UserRole, peer['id'])
                self.peers.addItem(item)
                if peer['id'] == ident: self.peers.setCurrentItem(item)
            if self.peers.currentRow() < 0 and self.peers.count(): self.peers.setCurrentRow(0)
            self.send.setEnabled(not self.busy and bool(snapshot['peers']))
            self.remove.setEnabled(not self.busy and bool(snapshot['peers']))
            lines = []
            for job in snapshot['jobs']:
                status = '校验成功' if job['status']=='complete' else job['error'] if job['status']=='error' else f'{int(job["sent"]*100/max(1, job["total"]))}%'
                direction = '发送到' if job['direction']=='send' else '接收自'
                lines.append(f'{job["name"]} · {direction} {job["peer_name"]} · {status}')
            text = '\n'.join(lines)
            if text != self.jobs_text:
                self.jobs_text = text; self.jobs.clear(); self.jobs.addItems(lines)
            if tunnel.get('error') and not self.error.text(): self.error.setText(tunnel['error'])
        except Exception:
            self.error.setText('服务尚未就绪，请重新打开机器共享。')

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
