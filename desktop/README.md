# 声笺 Windows 桌面端

[项目首页](../README.md) · [开发与构建](../docs/DEVELOPMENT.md) · [CI 说明](../docs/CI.md)

桌面壳使用 Tauri 2、React 和 TypeScript，Python Sidecar 继续提供局域网手机页面、剪贴板与历史数据服务。

开发：`npm run tauri dev`

完整构建：`..\scripts\build_tauri.ps1`

“机器共享”支持 Mac / Windows 一次性邀请配对、公网或局域网双向文件传输、进度和 SHA256 校验。Mac 1.2.0 的共享协议兼容本版。

Windows 构建需要 Python 3.12、Node.js 24、Rust/MSVC 和官方 cloudflared.exe。安装 `requirements-windows.txt`；将 Cloudflare 官方 2026.10.2 的 Windows amd64 二进制放入 `tools/cloudflared/cloudflared.exe`，或通过 `-Cloudflared` 指定。构建脚本同时生成 Tauri NSIS 安装版与 Qt 便携版，二者都内置隧道程序。仓库 Windows Actions 会验证下载摘要、运行测试、构建并上传安装包附件。
