# CI 与 GitHub Actions

[项目首页](../README.md) · [文档导航](README.md) · [打开 Actions](https://github.com/qinze889/DoubaoLanInputBridge/actions)

CI 的实现位于仓库隐藏目录 [`.github/workflows/`](../.github/workflows/)，由 GitHub 托管 runner 执行。设备后台服务器只提供运行服务，CI 构建不在该服务器上执行。

## Workflow 与触发条件

| Workflow | 配置 | 何时运行 | Runner |
| --- | --- | --- | --- |
| Windows client | [windows-client.yml](../.github/workflows/windows-client.yml) | PR、推送 `main`、手动运行 | `windows-2025` |
| Apple clients | [apple-clients.yml](../.github/workflows/apple-clients.yml) | PR、推送 `main`、手动运行 | `macos-15`（arm64） |
| Publish verified release assets | [release-assets.yml](../.github/workflows/release-assets.yml) | 手动运行，指定草稿 tag、成功的 Windows / Apple run ID | `ubuntu-latest` |

普通 PR 测试使用只读仓库权限；上传草稿 Release 附件的 workflow 单独申请 `contents: write`。Windows 与 Apple workflow 会取消同一 workflow / 分支仍在运行的旧执行；同一标签的发行附件任务串行执行。

## Windows 检查什么

1. 准备 Python 3.12、Node.js 24、Rust / MSVC 和构建缓存。
2. 安装 `requirements-windows.txt`，执行 `python -m pytest -q tests`。
3. 从 Cloudflare 官方发行版下载 cloudflared，先验证固定的 SHA256。
4. 调用 [`scripts/build_tauri.ps1`](../scripts/build_tauri.ps1)，构建 Python sidecar、Tauri NSIS 安装版、Qt 便携版。
5. 调用 [`smoke_windows_installer.py`](../scripts/smoke_windows_installer.py)：在临时目录真实安装、覆盖升级，检查旧服务退出、安装后的二进制与预期一致。
6. 调用 [`smoke_packaged_peers.py`](../scripts/smoke_packaged_peers.py)：运行两个打包后的服务，配对并双向传文件，验证 SHA256。
7. 将安装包、便携版、安装说明、许可证、构建提交 / run ID 元数据和摘要上传为 `Shengjian-windows-x64` artifact，保留 30 天。

1.4.0 还调用 `scripts/smoke_packaged_rtc.py`，验证冻结后的 WebRTC 组件与 P2P 双向多分块文件传输。

## Mac 与 iOS 检查什么

1. Mac 在 arm64 runner 准备 Python 3.12，下载固定版本和 SHA256 的官方 cloudflared。
2. 编译并执行 `tests/native/ShareImportChecks.swift`，检查临时文件保留、Unicode / 重名、私有权限与无效输入。调用 [`build_macos.sh`](../scripts/build_macos.sh)：回归测试、SwiftUI 编译、PyInstaller 服务打包，生成包含 cloudflared 的应用、内嵌系统分享扩展、DMG 与 ZIP。
3. 调用 [`verify_macos_package.py`](../scripts/verify_macos_package.py)：解压 ZIP、只读挂载 DMG，检查两包中应用及分享扩展的签名完整性、版本、arm64 架构、扩展沙盒和安装布局，检查无私有运行凭据。
4. 从挂载的 DMG 运行两个冻结服务，验证真实 WebRTC 双向多分块传输及 SHA256，确认文件内容没有经信令服务器转发。
5. 上传 DMG、ZIP、安装说明、许可证、`Mac-build.json` 和摘要清单为 `Shengjian-macos-arm64` artifact，保留 30 天。
6. iOS 独立 job 运行 `swift test --package-path ios`，再用 Xcode 为 iOS Simulator 构建 `ShengjianIOS`。

Mac 包使用 ad-hoc 签名，CI 验证签名完整性，不包含 Developer ID 公证。iOS CI 不发布 IPA；真机安装需要自己的开发团队和签名。CI 不启动用户的已安装应用，也不请求辅助功能权限。

## 查看结果与下载测试包

打开 [Actions](https://github.com/qinze889/DoubaoLanInputBridge/actions)，选择一次执行：

- 点击 `windows`、`macos`、`ios` job，展开 step 查看日志。
- 成功执行后，在页面底部 **Artifacts** 下载 `Shengjian-windows-x64` 或 `Shengjian-macos-arm64`（GitHub 可能要求登录）。
- 长期给用户使用的安装包从 [Releases](https://github.com/qinze889/DoubaoLanInputBridge/releases/latest) 下载；artifact 是本次提交的测试构建。

命令行也可查看：

```sh
gh run list --repo qinze889/DoubaoLanInputBridge
gh run view RUN_ID --repo qinze889/DoubaoLanInputBridge --log
gh run download RUN_ID --repo qinze889/DoubaoLanInputBridge \
  --name Shengjian-windows-x64 --dir dist/windows-ci
```

## 发行附件如何上传

`release-assets.yml` 接收三个参数：已有草稿 Release 的 tag、成功的 Windows workflow run ID、成功的 Apple workflow run ID。两个构建必须成功，且 `head_sha`、附件中记录的构建提交与标签所指向的提交完全一致；旧提交或只有部分 job 成功的构建均会被拒绝。

[`release_assets.py`](../scripts/release_assets.py) 验证每个附件均列入 SHA256 清单、没有额外文件、版本和 run ID 一致，再生成版本化 Mac DMG / ZIP、Windows 安装版 / Qt 便携版、源码 ZIP / tar.gz、构建元数据和统一 `SHA256SUMS.txt`。源码只从标签提交的 Git 跟踪文件导出，不包含本地配置或运行目录。

发布顺序：PR 检查通过 → 合并 → 等待合并提交的 Windows / Apple CI 全部通过 → 在该提交创建标签与草稿 Release → 指定两个 run ID 运行发行 workflow → 核对全部附件后公开 Release。

```sh
gh workflow run release-assets.yml --ref main \
  -f tag=v1.4.0 -f windows_run_id=WINDOWS_RUN_ID -f apple_run_id=APPLE_RUN_ID
```

上传前再次确认 Release 保持草稿。workflow 不自动公开发布草稿，避免附件尚未核对便向用户推送新版。

## 自动化验证的边界

CI 可以验证打包、安装升级和隔离测试环境中的协议；Mac 辅助功能、具体手机浏览器、摄像头、真实目标输入框、跨 NAT 的 P2P 连通性仍需要实机检查。CI 通过不代表所有网络都能建立 P2P，也不代表完成了 Apple 公证或 iOS 真机签名。
