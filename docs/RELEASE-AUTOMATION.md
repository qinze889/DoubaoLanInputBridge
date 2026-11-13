# ChatGPT 触发 CI 验证后发布 Release

本仓库提供 `.github/workflows/release-on-request.yml`，用于让已授权的 GitHub 账号通过创建 Issue 触发完整发行流程。无需在聊天中共享 PAT、服务器 SSH 凭据，且无需人工运行 workflow_dispatch。

## 发布前置条件

1. 版本号已经在 main 上统一升级（VERSION、Python 桥接服务、Windows Tauri/React/Cargo、Mac Info.plist）。
2. main 最新提交的 Windows client、Apple clients GitHub Actions **push** 任务均全部成功；不能用 PR 上旧提交的成功结果。
3. 需要正常生成 `Shengjian-windows-x64` 和 `Shengjian-macos-arm64` artifacts，且与提交完全一致。
4. 目标 tag 尚不存在，且版本高于 GitHub Latest Release。

## 发布指令

通过仓库所有者 `qinze889` 账号创建一个 Issue：

- 标题精确使用 `Release v1.4.1`（按实际版本变更）。
- 正文只有一行，格式为 `commit: <main 当前完整40位 SHA>`。

如果通过已经连接的 GitHub 插件发起，ChatGPT 可以自行查询目标提交、创建该 Issue，而 Issue 事件会启动发行 Workflow。不要编辑旧 Issue 重试；失败时检查原因，并以**尚未存在 Release/tag** 为前提新建 Issue。

## CI/CD 门禁

工作流首先验证请求来自仓库所有者、Issue 中版本与 main 文件一致、预期 SHA 就是 main 最新提交，并确认目标版本未被发布。随后查询两个平台完全相同提交的成功 push CI，下载产物，复用 `scripts/release_assets.py` 检查所有校验和及构建元数据。全部通过后，才建立 **Draft Release** 并上传产物；上传成功后才公开为 Latest。

任一步失败都不会公开不完整 Release。若创建草稿之后失败，应人工检查并清理该草稿，再重新请求；不会覆盖现有正式 Release。

## Windows 客户端更新

现有 Windows Tauri 安装版检测 GitHub 最新正式 Release，优先选择 `*-setup.exe`。用户在声笺内点击检查更新/下载更新，客户端下载并校验，然后以静默覆盖安装与自动重启完成原位升级，无需手动卸载。v1.4.0 **暂不具备实时下载进度条**。

Mac 当前 CI 提供 DMG/ZIP，但原生 Mac 版暂未实现与 Windows 等价的客户端一键更新。

## 权限与安全

工作流采用最小的 `contents: write`、`actions: read` 和 `issues: write`，使用自动生成的临时 GITHUB_TOKEN，不保存额外长效令牌。只有仓库所有者请求能进入发布任务。推荐保护 main，禁止未通过 CI 的提交进入主分支。

这条工作流验证 **已成功完成的 main CI**，不会在发布 Issue 时从头重新构建；CI 在代码合并至 main 后自动运行。
## 发行附件政策

从下一版本开始，正式 GitHub Release 只上传 **两个文件**：`Shengjian-<版本>-windows-x64-setup.exe` 与 `Shengjian-<版本>-mac-arm64.dmg`。Qt 便携版不再构建或发布；Mac ZIP、SHA256、许可证、构建报告和安装说明只保留在 CI artifacts。GitHub 自动提供的 Source code (zip / tar.gz) 链接由平台生成，不属于额外上传的安装包。
