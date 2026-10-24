# 更新记录

发行包与完整说明以 [GitHub Releases](https://github.com/qinze889/DoubaoLanInputBridge/releases) 为准。`VERSION` 表示当前分支源码版本。

## Web 2.0 预览版 — 2026-10-24

- 新回答首段文字淡入主阅读区并放大，主动翻阅解除聚焦，支持减少动态效果。

- 内置简明回复提示词：默认短句直答、少用术语，明确要求详细内容时完整展开。

- 手机网页重新分为对话、创作、记录、工作、我的；固定输入器、历史抽屉和按需设置，适配桌面与明暗主题。
- 支持历史续聊、会话草稿、新对话、归档与恢复；刷新只读取记录，不重复执行或播报。
- 纯聊天与电脑工作分开，工作保留后台进度、待确认和取消回执。
- 创作区区分生成和参考编辑，记录区区分时间线、回顾和记忆；危险操作确认，记忆编辑保留。
- 账号、登录与旧传输保持兼容，桌面安装版本不变。详见 [使用说明](docs/MOBILE-UI.md)。

## 未发布

- Mac 新增系统分享扩展：截屏或预览中选择“分享 → 声笺”，图片会带入发送窗口，可选择手机或已配对电脑。
- 修复首页底部两张卡片没有点击动作，分别打开文字分享和文件分享。
- 分享窗口显示图片预览，保留未发送草稿；临时附件会先保存为本机私有副本，避免截图窗口关闭后文件失效。
- Mac CI 同时构建并校验内嵌分享扩展，增加文件副本生命周期、重复文件名、权限和输入校验测试。

## 1.4.0 — 2026-10-22

[发行说明与下载](https://github.com/qinze889/DoubaoLanInputBridge/releases/tag/v1.4.0) · [查看改动](https://github.com/qinze889/DoubaoLanInputBridge/pull/3)

- Mac / Windows 增加固定公网、CF 隧道、WebRTC P2P、局域网四种连接方式的统一入口和配置保存。
- 机器共享支持固定域名下的独立设备端点；P2P 使用认证握手和加密数据通道，不自动回退中转。
- Windows CI 增加冻结安装包的 P2P 双向传输与 SHA256 验证。
- Mac CI 构建原生 DMG / ZIP，挂载校验签名、版本与架构，验证包内服务的双向 P2P 文件摘要。
- 发行流程核对 Mac / Windows CI 与标签为同一提交，验证完整摘要清单，自动生成源码 ZIP / tar.gz 后上传草稿 Release。
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
