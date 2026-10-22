# macOS 1.2.0 与 iOS 源码验证记录

日期：2026-10-21（Asia/Shanghai）。上游基线 `78e84c671a94a437df2a3058af18967a7185d5f2`。

- 平台：macOS 27 / arm64，Python 3.12.14；Mac 最低部署版本 14.4。
- 构建：`bash scripts/build_macos.sh` 成功，生成 SwiftUI 原生应用、打包后台服务、内置 cloudflared、DMG 和 ZIP。应用版本 1.2.0；`codesign --verify --deep --strict` 通过。当前使用 ad-hoc 签名，未做 Developer ID 公证。
- Python 回归：**241 passed**。新增多机器测试覆盖三台独立服务及公网路由网关、四个方向传输、分块、接收进程重启后的续传、文件名路径清理、SHA256 不匹配拒绝发布、一次性/过期邀请、HMAC 篡改与重放、撤销配对、端点更新。测试使用隔离临时目录。
- 实际公网：`scripts/smoke_public_sharing.py` 在同一 Mac 上启动三套隔离的最终打包服务及三条真实 Cloudflare Quick Tunnel；三个公网健康检查成功、三个桌面管理入口均为 403；A→B、B→A、A→C、C→A 四个方向的合成文件传输完成且 SHA256 一致。测试退出已关闭全部服务与隧道，凭据未输出或纳入源码。
- macOS 交互：卡片悬浮、二维码淡入缩放、导航切换、进度更新与提示弹簧动效，遵循减弱动态效果。正式控件来自 SwiftUI / AppKit 与 SF Symbols；旧 Qt 入口保留为参考。
- iOS：完整 Xcode 工程文件和 Info.plist 经 `plutil -lint` 通过，App 源码经 Swift parser 通过。Foundation 客户端编译且 **6 项行为自检通过**：二维码解析、不安全地址拒绝、局域网地址、文字 POST、共享内容解码、配对失效处理。
- 当前本机未安装完整 Xcode/iOS SDK，因此尚未执行 iOS SDK 类型检查、模拟器构建或真机验证；XCTest 与 iOS 模拟器构建已加入 GitHub Actions，不能将 CI 配置等同于运行成功。
- 未验证：实际 iPhone 相机/照片选择/权限及蜂窝网络联调、Intel 安装包、第三方应用具体粘贴效果、长时间大文件稳定性。
- 公网桌面管理 API 由路由白名单阻断。源码和安装包不含真实配对凭据、隧道账户、SSH 身份或个人运行数据。

Quick Tunnel 域名不持久：重新连接会变化；双方同时变化时需要重新配对。详见 [多机器共享](../../MACHINE-SHARING.md)。

此前原生应用公网/生命周期/手机传输验证见 [1.1 记录](MAC-VALIDATION-1.1.md)，最初 Qt 适配验证见 [1.0 记录](MAC-VALIDATION-1.0.md)。
