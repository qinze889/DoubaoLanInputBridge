# 声笺

把手机上的文字、照片和文件送到电脑，也能在 Mac 与 Windows 之间互传文件。手机用浏览器扫码即可使用，无需安装配套 App。

[下载安装](https://github.com/qinze889/DoubaoLanInputBridge/releases/latest) · [使用文档](docs/README.md) · [开发与构建](docs/DEVELOPMENT.md) · [CI / Actions](https://github.com/qinze889/DoubaoLanInputBridge/actions) · [更新记录](CHANGELOG.md)

[![Windows CI](https://github.com/qinze889/DoubaoLanInputBridge/actions/workflows/windows-client.yml/badge.svg?branch=main)](https://github.com/qinze889/DoubaoLanInputBridge/actions/workflows/windows-client.yml)
[![Apple CI](https://github.com/qinze889/DoubaoLanInputBridge/actions/workflows/apple-clients.yml/badge.svg?branch=main)](https://github.com/qinze889/DoubaoLanInputBridge/actions/workflows/apple-clients.yml)

账号扫码页新增[生活记录](docs/LIFE-RECORDS.md)：文字、照片、对话时间线，WorkBuddy 看图，每晚整理为有来源的记忆，并同步到本机 Agent。

## 下载与版本

| 平台 | 推荐入口 | 说明 |
| --- | --- | --- |
| Mac | [Release 中的 DMG / ZIP](https://github.com/qinze889/DoubaoLanInputBridge/releases/latest) | Apple Silicon，macOS 14.4+；原生 SwiftUI 界面 |
| Windows | [Release 中的 `windows-x64-setup.exe`](https://github.com/qinze889/DoubaoLanInputBridge/releases/latest) | Tauri 安装版；Qt 便携版按需二选一 |
| iPhone / iPad | 手机浏览器扫码，或查看 [iOS 源码](ios/README.md) | 原生客户端需要自行用 Xcode 签名构建 |

当前版本为 **1.4.0**，Mac / Windows 提供四种连接方式的统一入口。安装包与源码包见 [1.4.0 发行页](https://github.com/qinze889/DoubaoLanInputBridge/releases/tag/v1.4.0)；正式发行状态以 Releases 为准，Actions 附件用于测试。

## 开始使用

1. 在电脑安装并打开声笺。Mac 首次使用需要允许本地网络和辅助功能权限。
2. 打开“连接手机”，等待入口就绪，用手机相机扫描二维码。同一 Wi-Fi 可走局域网；跨网络可使用 Cloudflare 或已配置的固定公网入口。
3. 在电脑上点选目标输入框，在手机页面输入文字或选择文件后发送。Mac 使用 ⌘V，Windows 使用 Ctrl+V。
4. 电脑发给手机：使用“分享 / 发布给手机”。电脑之间传文件：进入“机器共享”，生成一次性邀请，在另一台机器粘贴配对。

详细说明：[Mac 安装与授权](docs/README-macOS.md) · [Windows 安装](docs/INSTALL-Windows.txt) · [机器共享](docs/MACHINE-SHARING.md) · [固定公网后台](docs/SERVER-RELAY.md)

本分支原生 iOS 源码支持局域网 / CF 的 `?key=` 链接及 HTTPS 固定中转登录；P2P 使用手机浏览器。

v2 测试入口已接入账号、设备授权、豆包登录态语音及电脑任务，详见 [部署、验证与当前边界](docs/CORE_V2.md)。网页流式语音支持边说边识别、边生成边播报和打断；原生手机语音与屏幕互控仍在后续阶段，正式发行状态以 Releases 为准。

新版桌面测试 App 的侧栏新增 **电脑 Agent**：登录账号后启用 **DeepSeek Harness**，可查看引擎、模型、连接和任务状态，也可直接输入任务。原生 Mac / Tauri 构建内置固定版本 Harness 与 Node。手机刷新对话页，点击“电脑 Agent”并开启实时对话，可直接派任务、说“汇报进度”“取消当前任务”“查看电脑状态”，或继续补充上一项任务；完成后会语音汇报。默认任务目录为 `Documents/声笺任务`。

本分支新增独立后台浏览器、最多三个子代理、父子消息、自有技能、本地记忆及定时任务。网页任务使用独立无界面 Chrome / Edge，不接用户当前浏览器；原生 Mac 后台控件为默认关闭的实验能力。使用与边界见 [本地电脑助理](docs/LOCAL-ASSISTANT.md)，豆包/GPT 的 REA MCP 证据、能力清单及接入取舍见 [调查索引](docs/research/README.md)。MCP 第三方连接器尚未配置，完整虚拟桌面与跨独立任务会话邮箱尚未接入。

## 连接方式

| 方式 | 适用场景 | 当前状态 |
| --- | --- | --- |
| 局域网 | 同一 Wi-Fi / 内网 | 已支持 |
| Cloudflare 隧道 | 跨网络，使用临时 HTTPS 域名 | 已支持，桌面安装包内置 cloudflared |
| 固定公网 | 自托管服务器、固定域名、每台机器独立连接码 | 已支持，需导入本机设备配置 |
| P2P 直连 | 服务器只参与握手，内容走 WebRTC 数据通道 | 1.4.0；取决于 NAT 和 UDP 网络条件 |

1.4.0 为四种方式提供统一选择入口。当前 Mac / Windows 实机之间的 P2P 握手成功、直连超时，默认使用已验证的固定公网；P2P 不会自动回退为服务器中转。

## 仓库导航

| 目录 / 文件 | 用途 |
| --- | --- |
| [`src/`](src/) | Python 服务、手机网页、平台适配与机器共享协议 |
| [`native/`](native/) | macOS 原生 SwiftUI 应用 |
| [`desktop/`](desktop/) | Windows Tauri / React 桌面界面 |
| [`ios/`](ios/) | iOS SwiftUI 客户端和 Xcode 工程 |
| [`server/`](server/) | 自托管中转后台、手机页面、Nginx / systemd 配置 |
| [`scripts/`](scripts/) · [`packaging/`](packaging/) | 构建、打包、安装与传输验证脚本 |
| [`tests/`](tests/) | 自动化回归与协议测试 |
| [`.github/workflows/`](.github/workflows/) | GitHub Actions：测试、构建、验证和发行附件上传 |
| [`docs/`](docs/) · [`assets/`](assets/) | 文档、历史归档、图标与界面素材 |
| [`VERSION`](VERSION) · `requirements-*.txt` | 当前分支版本及各平台 Python 依赖 |

构建产物写入本地 `dist/` / `build/`，分发文件发布到 GitHub Releases。旧版 0.9.x 分发样例和早期文档已移到 [历史归档](docs/archive/README.md)。

## CI 在哪里

CI 在 **GitHub Actions 的托管 runner** 上运行，结果见 [Actions 页面](https://github.com/qinze889/DoubaoLanInputBridge/actions)。47 服务器运行的是设备后台。

- [Windows workflow](.github/workflows/windows-client.yml)：回归测试、构建安装版和便携版、实际安装 / 升级、双向文件 SHA256 校验，并上传构建附件。
- [Apple workflow](.github/workflows/apple-clients.yml)：Mac 回归、原生应用和 DMG / ZIP 构建、安装包完整性与冻结 P2P 验证；iOS 单元测试与模拟器构建。
- [发行附件 workflow](.github/workflows/release-assets.yml)：手动核对成功的 Mac / Windows 构建与发行标签为同一提交，校验摘要，生成源码包并上传到草稿 Release。

触发条件、附件下载和发布流程见 [CI 说明](docs/CI.md)。

## 数据与权限

每台电脑的访问凭据、配对信息和历史记录保存在本机数据目录。不要将 `relay.json`、访问密钥、API Key 或运行数据提交到仓库或放入安装包。Mac 的自动粘贴需要辅助功能授权及目标输入框焦点。

翻译 / 润色功能会在使用时调用相应第三方服务，配置与数据位置见 [开发文档](docs/DEVELOPMENT.md#配置与运行数据)。
