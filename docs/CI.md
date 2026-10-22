# CI 与 GitHub Actions

[项目首页](../README.md) · [文档导航](README.md) · [打开 Actions](https://github.com/qinze889/DoubaoLanInputBridge/actions)

CI 的实现位于仓库隐藏目录 [`.github/workflows/`](../.github/workflows/)，由 GitHub 托管 runner 执行。设备后台服务器只提供运行服务，CI 构建不在该服务器上执行。

## Workflow 与触发条件

| Workflow | 配置 | 何时运行 | Runner |
| --- | --- | --- | --- |
| Windows client | [windows-client.yml](../.github/workflows/windows-client.yml) | PR、推送 `main`、手动运行 | `windows-2025` |
| Apple clients | [apple-clients.yml](../.github/workflows/apple-clients.yml) | PR、推送 `main` | `macos-15` |
| Publish verified Windows assets | [release-assets.yml](../.github/workflows/release-assets.yml) | 手动运行，指定草稿 tag 和成功的 Windows run ID | `ubuntu-latest` |

普通 PR 测试使用只读仓库权限；上传草稿 Release 附件的 workflow 单独申请 `contents: write`。Windows 与 Apple workflow 会取消同一 workflow / 分支仍在运行的旧执行。

## Windows 检查什么

1. 准备 Python 3.12、Node.js 24、Rust / MSVC 和构建缓存。
2. 安装 `requirements-windows.txt`，执行 `python -m pytest -q tests`。
3. 从 Cloudflare 官方发行版下载 cloudflared，先验证固定的 SHA256。
4. 调用 [`scripts/build_tauri.ps1`](../scripts/build_tauri.ps1)，构建 Python sidecar、Tauri NSIS 安装版、Qt 便携版。
5. 调用 [`smoke_windows_installer.py`](../scripts/smoke_windows_installer.py)：在临时目录真实安装、覆盖升级，检查旧服务退出、安装后的二进制与预期一致。
6. 调用 [`smoke_packaged_peers.py`](../scripts/smoke_packaged_peers.py)：运行两个打包后的服务，配对并双向传文件，验证 SHA256。
7. 将安装包、便携版、安装说明、许可证和摘要上传为 `Shengjian-windows-x64` artifact，保留 30 天。

1.4.0 / [PR #3](https://github.com/qinze889/DoubaoLanInputBridge/pull/3) 另外加入 `scripts/smoke_packaged_rtc.py`，验证冻结后的 WebRTC 组件与 P2P 双向多分块文件传输；合并后成为主分支检查的一部分。

## Mac 与 iOS 检查什么

- Mac：安装 `requirements-macos.txt`，运行回归测试，再用 `swiftc` 编译原生 SwiftUI 应用。
- iOS：运行 `swift test --package-path ios`，再用 Xcode 为 iOS Simulator 构建 `ShengjianIOS`，CI 不执行开发者签名。

Apple workflow 当前不自动导出或上传 DMG，也不发布签名 IPA。Mac DMG / ZIP 通过 [`scripts/build_macos.sh`](../scripts/build_macos.sh) 构建；iOS 真机安装需要自己的开发团队和签名。

## 查看结果与下载测试包

打开 [Actions](https://github.com/qinze889/DoubaoLanInputBridge/actions)，选择一次执行：

- 点击 `windows`、`macos`、`ios` job，展开 step 查看日志。
- Windows 成功执行后，在页面底部 **Artifacts** 下载 `Shengjian-windows-x64`（GitHub 可能要求登录）。
- 长期给用户使用的安装包从 [Releases](https://github.com/qinze889/DoubaoLanInputBridge/releases/latest) 下载；artifact 是本次提交的测试构建。

命令行也可查看：

```sh
gh run list --repo qinze889/DoubaoLanInputBridge
gh run view RUN_ID --repo qinze889/DoubaoLanInputBridge --log
gh run download RUN_ID --repo qinze889/DoubaoLanInputBridge \
  --name Shengjian-windows-x64 --dir dist/windows-ci
```

## 发行附件如何上传

`release-assets.yml` 接收两个参数：已有草稿 Release 的 tag、成功的 Windows workflow run ID。它检查 run 已成功结束，逐项比较构建相关源码与发行标签，下载 artifact 并逐文件校验 SHA256，然后上传版本化安装包、说明、许可和 `Windows-build.json`。

标签需要先在远端存在，Release 需要保持草稿状态。该 workflow **只上传已验证的 Windows 附件**，不会自动创建 Release、构建 Mac 包或将草稿公开发布。最终发布时还需核对 Mac 安装包、源码包、版本与说明。

## 自动化验证的边界

CI 可以验证打包、安装升级和隔离测试环境中的协议；Mac 辅助功能、具体手机浏览器、摄像头、真实目标输入框、跨 NAT 的 P2P 连通性仍需要实机检查。CI 通过不代表所有网络都能建立 P2P，也不代表完成了 Apple 公证或 iOS 真机签名。
