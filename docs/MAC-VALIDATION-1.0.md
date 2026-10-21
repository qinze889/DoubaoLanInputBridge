# macOS 构建验证记录

日期：2026-10-21（Asia/Shanghai）

- 运行环境：macOS 27.0，Apple Silicon / arm64，Python 3.12.14。
- 产物：`dist/声笺.app`、`dist/Shengjian-mac-arm64.dmg`、`dist/Shengjian-mac-arm64.zip`。
- 最低系统版本：macOS 14.4。已通过 `vtool -show-build` 检查 QtCore / QtGui 的实际部署目标，Info.plist 与此一致；仅在本机 macOS 27 完成运行测试。
- 回归测试：217 passed。保留的 Windows 更新/防火墙测试使用明确的 Windows 模式及进程替身；Mac 分支另有专项测试。
- 原生实测：在专用 Qt 文本输入窗口中，经 HTTP `/send` 调用 NSPasteboard 与 Quartz ⌘V，中文、Emoji、多行文字准确写入。测试只对自身前台窗口发送按键，结束后恢复原系统剪贴板。
- 图片实测：原生剪贴板包含 `public.file-url` 与 TIFF 位图。
- HTTP 集成：错误密钥拒绝、手机页面、文本粘贴、回车、历史、multipart 文件上传、电脑发布、手机 feed 与文件下载、上传前鉴权、请求日志密钥脱敏。
- 桌面界面：主窗口、权限条、扫码弹窗、管理页、服务启停均已验证；界面截图在 `docs/screenshots/`。
- 独立应用启动：通过 LaunchServices 打开最终 `.app`，辅助功能权限提示正确显示。用户需自行在系统设置授权打包后的「声笺」。开发 Python 的既有权限不会被假定为应用已有权限。
- 实机端口冲突：8765 已有其他服务，应用自动选用 8766；`/health` 返回对应打包应用 PID、`version=1.0.0`、`frozen=true`、`ok=true`。未中断原有服务。
- 签名：PyInstaller ad-hoc 签名，`codesign --verify --deep --strict` 通过。未做 Developer ID 签名、公证。
- 未验证：真实手机跨 Wi-Fi 联调、Intel CPU、各第三方聊天应用的具体文件粘贴行为、外部 AI 服务调用、Cloudflare 隧道。提供的是本地 Mac 构建，不包含 Windows 自动更新。

上游来源：[qinze889/DoubaoLanInputBridge](https://github.com/qinze889/DoubaoLanInputBridge)，公开 main 分支归档，获取日期 2026-10-21。

上游归档 SHA256：`8dec60a9fd2329da45450bd82205503b0b6d5e51c60e44c8d92f4791b0a485df`。
