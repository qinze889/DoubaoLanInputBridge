# 声笺 macOS 版 1.2.0

基于 [qinze889/DoubaoLanInputBridge](https://github.com/qinze889/DoubaoLanInputBridge) 1.0.0 的 macOS 适配。通过 Cloudflare 公网或同一 Wi-Fi 扫码，在手机输入（包括使用手机的豆包语音输入法）后发送，Mac 将内容粘贴到当前输入框。手机无需安装配套 App。

## 安装与使用

当前构建适用于 **Apple Silicon（M1/M2/M3/M4 等），macOS 14.4 或更新版本**。本机已在 macOS 27 / arm64 构建并验证。

1. 打开 `dist/Shengjian-mac-arm64.dmg`，把「声笺」拖入「Applications」。也可以解压 ZIP 后把 `.app` 移入「应用程序」。
2. 双击打开「声笺」。应用会自动启动局域网服务，在菜单栏保留入口。
3. 在「系统设置 → 隐私与安全性 → 辅助功能」中允许「声笺」。界面顶部提供快捷入口，权限生效后提示会消失。首次联网出现系统提示时允许本地网络访问。
4. 默认自动开启 Cloudflare 公网连接，显示「公网已连接」后用手机相机扫码，蜂窝网络也能使用，无需同一 Wi-Fi。关闭「公网连接」开关后改用局域网。微信内置浏览器如果无法选文件，请用 Safari/系统浏览器打开。
5. 在 Mac 中点选目标输入框，再在手机输入并点击「发送」。默认发送后回车，可在手机页面关闭该选项。自动粘贴使用 **⌘V**。
6. 电脑发送给手机时，点击右上角「分享」，输入文字或拖入文件。手机页面「来自电脑」中可复制文字、打开或下载文件。

关闭窗口后应用仍在菜单栏运行；菜单栏选择「退出」，或按 ⌘Q 完全退出并停止服务。再次打开应用会唤起已有窗口。

这是本地构建，使用 ad-hoc 签名，未做 Apple Developer ID 签名或公证。其他 Mac 如显示开发者验证提示，可在「隐私与安全性」中选择「仍要打开」。不需要关闭 Gatekeeper。

## 已适配

- 中文、Emoji、多行文字剪贴板与原生 ⌘V、可选回车。
- 图片、视频、PDF、Word 和普通文件传输。图片同时写入文件 URL 和位图剪贴板类型，兼容 Finder 与常见聊天输入框；具体粘贴效果取决于目标应用。
- 二维码配对、刷新密钥、旧二维码失效、端口冲突自动顺延。
- 电脑向手机分享文字和多个文件，手机端下载。
- 历史归档、搜索、分类、分页，Finder 打开目录。
- 原生 SwiftUI、SF Symbols、分组卡片、系统开关、菜单栏、设置和退出快捷键。
- Cloudflare 一键公网二维码、HTTPS、连接重试、退出清理；公网不开放桌面管理 API。
- 手机页面 iOS 风格与深色模式。
- 识别活动网卡，支持 10.*、172.16–31.*、192.168.*；无局域网时明确提示。
- 请求日志隐藏配对密钥；运行数据与凭据不打入应用安装包。
- 保留原手机页面的翻译和 MiniMax 润色功能。翻译会调用 MyMemory；润色需在「设置 → 智能润色」设置自己的 MiniMax API Key。

## 多机器共享与 iOS 客户端

“机器共享”可以添加多台 Mac，经各自的 Cloudflare 隧道互传文件，支持进度、短暂断线重试、SHA256 校验和撤销配对。详见 [机器共享说明](MACHINE-SHARING.md)。

原生 iOS 客户端与 Xcode 工程在 [ios/](../ios/README.md)，支持扫码、多 Mac 连接、文字、照片、文件与下载分享。交互采用原生 SwiftUI 控件，并为卡片、二维码切换、状态提示与进度加入遵循系统减弱动态效果设置的动效。

## 当前范围

Windows 自动更新和 Windows 防火墙命令不在 Mac 中运行。当前 Mac 版通过重新安装更新，不使用原仓库的 Windows 安装包更新源。公网使用 Cloudflare Quick Tunnel，免登录、无需配置域名，安装包内置 cloudflared。每次重新连接会产生新的临时域名；关闭连接或退出应用后失效。临时隧道没有可用性保证，固定域名和命名隧道尚未在新界面开放。Intel Mac 需在 Intel 机器上重新构建，此处未生成或验证 Intel 安装包。

本工具接收手机浏览器发来的文字，不会直接调用或控制手机上的豆包应用。

## 开发与构建

使用 **Python 3.12**（原项目 multipart 实现依赖 `cgi`）。`uv` 可自动安装该版本；不使用 `uv` 时需自行安装 `python3.12`。

```bash
bash scripts/build_macos.sh
```

脚本创建 `.venv`、安装固定版本依赖、执行回归测试，编译原生 SwiftUI 界面、打包后台服务与 cloudflared，生成 `.app`、DMG 和 ZIP。构建需要 Xcode Command Line Tools、cloudflared；使用者无需安装 Python 或 cloudflared。

从源码构建并运行：

```bash
bash scripts/build_macos.sh
open dist/声笺.app
```

`src/qt_app.py` 与 `scripts/build_qt_macos.sh` 仅保留旧 Qt 界面作为参考。正式运行入口为原生 `.app`。

开发运行时，辅助功能需授权启动 Python 的终端或宿主应用。已打包应用的授权对象是「声笺」。

Mac 专项与 HTTP 集成测试：

```bash
DOUBAO_BRIDGE_DATA_DIR="$(mktemp -d)" QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q tests/test_macos.py tests/test_macos_http.py
```

运行数据位于 `~/Library/Application Support/DoubaoLanInputBridge/`。可通过 `DOUBAO_BRIDGE_DATA_DIR` 指定测试目录，与真实数据分开。配对链接带访问密钥，仅分享给可信设备。

## 来源与目录

- `src/mac_platform.py`：NSPasteboard、Quartz 键盘事件、辅助功能与网卡适配。
- `src/gui_app.py`：沿用原项目 HTTP 服务、手机页面、传输和历史逻辑，增加 Mac 分支。
- `native/ShengjianApp.swift`：原生 SwiftUI 界面，连接、历史、设置、拖放分享、菜单栏。
- `src/mac_service.py`：应用托管后台服务，退出时收回隧道和服务进程。
- `src/mac_tunnel.py`：Cloudflare Quick Tunnel 生命周期及限制路由的公网网关。
- `src/ios_mobile.py`：手机网页 iOS 风格与深色模式。
- `src/qt_app.py`：保留的旧 Qt 界面参考。
- `scripts/build_macos.sh`、`packaging/mac-service.spec`、`packaging/Info-native.plist`：Mac 构建与应用声明。
- `docs/README-UPSTREAM.md`：原项目说明，包含 Windows 历史内容，不作为本 Mac 版运行指南。
- `docs/MAC-VALIDATION.md`：构建验证记录。

上游源码通过公开的 main 分支归档获取，获取日期 2026-10-21。上游提供的品牌、图标和源代码保留原作者归属；快照未附带 LICENSE 文件。本分支提供 macOS 与 iOS 适配。

Cloudflare Quick Tunnel 行为与限制参照[官方说明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。
