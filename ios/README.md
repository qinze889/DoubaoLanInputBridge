# 声笺 iOS 原生客户端

[项目首页](../README.md) · [开发与构建](../docs/DEVELOPMENT.md) · [CI 说明](../docs/CI.md)

iOS 17+、SwiftUI。原生 `TabView`、`NavigationStack`、`Form`、`TextEditor`、`PhotosPicker`、系统文件选择器与分享面板；成功触感反馈、弹簧提示动效遵循“减弱动态效果”设置。通过 Mac 连接二维码配对，可发送文字（可选回车）、照片、视频和文件，也可下载 Mac 分享的内容。多个 Mac 连接分别保存于本机 Keychain，使用 `WhenUnlockedThisDeviceOnly`。

## 构建

用完整 Xcode 打开 `ShengjianIOS.xcodeproj`，选择共享 scheme `ShengjianIOS`。在 Signing & Capabilities 选择你自己的开发团队与可用 Bundle ID，选择 iPhone / iPad 或模拟器运行。源码不包含签名证书或开发团队。

```sh
swift test --package-path ios
xcodebuild -project ios/ShengjianIOS.xcodeproj -scheme ShengjianIOS \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath ios/DerivedData CODE_SIGNING_ALLOWED=NO build
```

只有 Command Line Tools 的 Mac 可运行 Foundation 客户端自检：

```sh
swift run --package-path ios ClientChecks
```

## 使用

1. 在 Mac 开启声笺，等待 Cloudflare 公网连接就绪，或使用同一局域网。
2. iPhone 中选择“连接一台 Mac”，扫描 Mac 的手机连接二维码，也可粘贴配对链接。相机拒绝权限后仍可粘贴链接。
3. 连接验证成功后输入文字发送，或从照片和文件选择器上传；“来自 Mac”页下拉刷新下载内容。
4. “设备”页切换 Mac。Mac 的 Quick Tunnel 域名变化后需重新扫码；旧连接可滑动删除。

手机连接二维码与 `shengjian://pair` 机器共享邀请用途不同；后者用于 Mac / Windows 电脑之间配对。HTTP 仅接受本机或 RFC1918 局域网地址，公网需要 HTTPS。跳转限制为原始协议、主机与端口。

原生客户端支持根路径带 `?key=` 的局域网 / CF 链接，以及 HTTPS 固定中转 `/shengjian/d/.../#...` 链接。固定中转通过 POST 登录并使用会话 Cookie，不把连接码放进转发 URL；上传每次最多 15 MiB。P2P 仍使用手机浏览器。

“对话”页在 App 内打开 v2 账号、任务与实时语音。登录 Cookie 持久保留 30 天，退出或云端撤销后失效；浏览器与 App 的 Cookie 各自独立。扫描电脑账号区的语音二维码可兑换一次性登录，自动切换到对话页；文件传输二维码仍走原有配对。App 内网页仅允许声笺 HTTPS 域名，首次实时对话由系统询问麦克风权限。此入口复用网页音频引擎，仍需完整 Xcode 构建和真机验证。

仓库 CI 执行 Swift 单元测试和完整 Xcode 模拟器构建，结果见 [Apple clients](https://github.com/qinze889/DoubaoLanInputBridge/actions/workflows/apple-clients.yml)。相机、权限、照片/文件选择和设备互传仍需真机联调。
