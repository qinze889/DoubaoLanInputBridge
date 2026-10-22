# macOS 1.1.0 原生版验证记录

日期：2026-10-21（Asia/Shanghai）

- 平台：macOS 27.0 / arm64，部署目标 macOS 14.4。
- 正式桌面入口：`native/ShengjianApp.swift` 编译的 SwiftUI 原生应用。Qt 界面仅保留为旧实现参考。
- 后台入口：应用内置 `bridge-service`（Python 3.12.14 / PyInstaller），以及内置 `cloudflared 2026.10.2`。使用者不需要自行安装运行时或 cloudflared。
- 自动测试：**230 passed**，涵盖原有传输逻辑、权限、剪贴板、HTTP、Cloudflare 公网网关和服务端口冲突等。
- 原生界面：连接页、传输历史、设置、原生开关、SF Symbols、拖放分享弹窗。预览使用合成二维码，截图在 `docs/screenshots/native-connect.png`，不含真实配对密钥。
- 手机页面：iOS 风格、大字号输入、开关式选项、圆角分组、深色模式；原发送、翻译、润色、文件和下载流程保留。
- Cloudflare 源码实测：创建 Quick Tunnel，公网 HTTPS 健康检查成功、带配对密钥的手机页面成功、公网共享内容读取成功、`/desktop/state` 被 403 拦截。测试内容与凭据位于一次性临时目录，测试结束关闭隧道。
- **最终打包应用实测**：LaunchServices 启动原生应用；应用自动启动打包的后台服务和打包的 cloudflared。后台版本 `1.1.0`、`frozen=true`，在本机使用 8766 端口；Cloudflare `phase=ready`，公网健康检查和手机页面均成功，桌面管理接口返回 403。真实配对链接和二维码未写入验证日志或本文件。
- 端口自检：避开已由其他应用监听的回环/局域网端口；启动后验证 PID 和版本，解决 macOS 通配地址与回环地址同时绑定时请求路由至其他应用的问题。
- 进程通信：原生 UI 使用 `availableData` 消费后台启动信息，不等待固定长度数据，后台就绪后正常刷新界面并启动公网连接。
- 生命周期：停止仅作用于本应用拥有的 cloudflared 子进程，退出/父进程消失会清理后台和公网网关。公网入口使用单独的路由白名单，永不转发 `/desktop/*` 或更新路由；健康响应不泄漏本机 PID、用户名或路径。
- 安装包：ad-hoc 签名，`codesign --verify --deep --strict` 通过；DMG 和 ZIP 已生成。未做 Developer ID 签名、公证。
- 自动粘贴：延用 1.0.0 已实测的 NSPasteboard / Quartz 原生实现；打包应用的辅助功能权限仍需用户在系统设置开启。
- 未验证：实际手机相机/蜂窝网络设备联调、Intel CPU、各第三方应用具体文件粘贴效果。公网 HTTPS 链路在本机真实访问 Cloudflare 域名完成验证。

当前公网模式为 Cloudflare Quick Tunnel：无需登录或域名，重新连接会分配新的临时域名，关闭隧道后失效；没有持久可用性保证。参见 [Cloudflare 官方说明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。固定域名的命名隧道尚未在新界面提供。

1.0.0 验证留档见 `MAC-VALIDATION-1.0.md`。
