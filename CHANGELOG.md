# 更新记录

发行包与完整说明以 [GitHub Releases](https://github.com/qinze889/DoubaoLanInputBridge/releases) 为准。`VERSION` 表示当前分支源码版本。

## 1.4.0 — 未发布 / PR #3

[查看改动](https://github.com/qinze889/DoubaoLanInputBridge/pull/3)

- Mac / Windows 增加固定公网、CF 隧道、WebRTC P2P、局域网四种连接方式的统一入口和配置保存。
- 机器共享支持固定域名下的独立设备端点；P2P 使用认证握手和加密数据通道，不自动回退中转。
- Windows CI 增加冻结安装包的 P2P 双向传输与 SHA256 验证。
- 固定公网后台已迁至独立的 32 核、64GB 服务器，保留设备身份。
- 现场验证：Mac / Windows 已安装测试构建并完成双向文件校验；当前两台机器的跨网络 P2P 直连仍超时，使用固定公网。

## 1.3.0 — 2026-10-22

[发行说明与下载](https://github.com/qinze889/DoubaoLanInputBridge/releases/tag/v1.3.0)

- Windows Tauri 安装版和 Qt 便携版提供机器共享，与 Mac 双向传文件。
- 安装包内置 cloudflared，发送使用 1 MiB 分块，兼容旧版接收协议；完成后校验 SHA256。
- 增加固定公网设备后台与主动连接器，按设备身份隔离手机入口。
- Mac 由原生主程序执行粘贴，修复内部服务的辅助功能授权问题。
- GitHub Actions 验证 Windows 安装 / 升级与互传，并从成功构建上传校验后的发行附件。

## macOS 1.2.0 — 2026-10-21

[发行说明与下载](https://github.com/qinze889/DoubaoLanInputBridge/releases/tag/v1.2.0-macos)

- macOS 原生 SwiftUI 应用、菜单栏、Cloudflare 公网二维码与机器共享。
- 提供 iOS SwiftUI 客户端源码与 Xcode 工程。

## 更早记录

- [早期 Windows 说明与逐项更新](docs/archive/README-UPSTREAM.md)
- [整理前的 README 快照](docs/archive/README-before-cleanup.md)
- [历史构建验证与 0.9.x 分发样例](docs/archive/README.md)
