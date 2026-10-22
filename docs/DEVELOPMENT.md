# 开发与构建

[项目首页](../README.md) · [文档导航](README.md) · [CI 说明](CI.md)

## 环境与入口

Python 使用 **3.12**；HTTP 上传仍依赖该版本提供的 `cgi`。依赖按平台保留在仓库根目录，构建脚本和 CI 直接引用这些文件。

| 平台 | 应用入口 | 依赖 / 构建 |
| --- | --- | --- |
| Mac 原生版 | `native/ShengjianApp.swift` → `src/mac_service.py` | `requirements-macos.txt`、`scripts/build_macos.sh` |
| Windows 安装版 | `desktop/` → Python sidecar | `requirements-windows.txt`、`scripts/build_tauri.ps1` |
| Windows Qt 便携版 | `src/qt_app.py` | 同上，Tauri 构建脚本会一并生成 |
| iOS | `ios/ShengjianIOS.xcodeproj` | 完整 Xcode、iOS SDK；参见 [iOS 文档](../ios/README.md) |
| 公网后台 | `server/relay.py` | `server/requirements.txt`；参见 [部署文档](SERVER-RELAY.md) |

Mac 使用 Xcode Command Line Tools 和官方 cloudflared。Windows 完整构建还需要 Node.js 24、Rust / MSVC，以及官方 Windows amd64 cloudflared；版本与摘要以 [Windows workflow](../.github/workflows/windows-client.yml) 为准。

## 本地构建

从仓库根目录执行 Mac 构建：

```sh
bash scripts/build_macos.sh
```

脚本创建虚拟环境、安装依赖、运行回归、编译 SwiftUI、打包 Python 服务及 cloudflared，生成 `dist/声笺.app`、DMG 和 ZIP。更详细的要求见 [Mac 指南](README-macOS.md#开发与构建)。

Windows 在 PowerShell 中执行：

```powershell
python -m pip install -r requirements-windows.txt
.\scripts\build_tauri.ps1 -PythonExe (Get-Command python).Source
```

先将 workflow 中指定版本的 cloudflared 放入 `tools/cloudflared/cloudflared.exe`，或用 `-Cloudflared` 参数指定路径。NSIS 安装包位于 `desktop/src-tauri/target/release/bundle/nsis/`，Qt 便携版位于 `dist/`。

## 回归测试

安装对应平台依赖后执行：

```sh
python -m pytest -q tests
```

测试配置将数据写入临时目录。CI 使用 `QT_QPA_PLATFORM=offscreen`；不要把真实应用数据目录传给自动化测试。`scripts/smoke_macos.py` 属于需要桌面和授权的人工实机检查，普通 pytest 不会执行它。

iOS 测试与模拟器构建命令见 [iOS 指南](../ios/README.md#构建)。CI 的实际检查步骤见 [CI 说明](CI.md)。

## 配置与运行数据

| 平台 | 默认数据目录 |
| --- | --- |
| Mac | `~/Library/Application Support/DoubaoLanInputBridge/` |
| Windows | `%LOCALAPPDATA%\DoubaoLanInputBridge\` |

`DOUBAO_BRIDGE_DATA_DIR` 可指定隔离数据目录。内部项目名保留 `DoubaoLanInputBridge`，以兼容升级路径。

- `relay.json`：本机独立服务器连接凭据；从后台生成并导入，禁止提交。
- `device.json` / `paired-devices.json`：本机身份和已配对机器信息。
- `access_key.txt`：本机手机访问凭据，二维码或链接同样属于访问凭据。
- `mobile_host.txt` / `DOUBAO_BRIDGE_HOST`：局域网主机覆盖，常规使用优先自动识别。
- `prompt_library.json`：本地提示词模式；格式见 [模式库说明](prompt_library_schema.md)。

翻译功能使用 MyMemory，润色使用 MiniMax；只有调用相应功能时才会向服务发送文本。MiniMax 凭据可在桌面设置中配置，也支持 `MINIMAX_API_KEY` 环境变量；未配置或网络不可用时，普通传输仍可使用。

Windows 更新默认读取 GitHub Releases，并校验下载摘要。内网更新源脚本 `scripts/publish_local_update.ps1` 和旧 Qt 分发脚本 `scripts/make_release.ps1` 供既有流程使用，生成的 `local_update_source/`、`release/` 均为本地产物，不提交到 Git。

## 目录约定

根目录放项目入口、版本、平台依赖与源码目录。当前文档放 `docs/`，历史资料放 `docs/archive/`；生成的 `.app`、EXE、DMG、ZIP、缓存和运行数据由 `.gitignore` 排除。对外安装包进入 GitHub Releases，测试包进入 Actions Artifacts。
