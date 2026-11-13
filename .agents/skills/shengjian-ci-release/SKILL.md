---
name: shengjian-ci-release
description: "当用户明确要求发布声笺（Shengjian / DoubaoLanInputBridge）的新版本、检查 Windows/macOS CI、创建正式 GitHub Release 或让 Windows 客户端一键更新时使用。不是一般性的发布知识问答；不得在用户仅询问方案时触发正式发布。"
---

# 声笺 CI → GitHub Release → Windows 一键更新

## 目标与边界

在用户**明确要求正式发布某个版本**时，通过已连接的 GitHub 工具执行「代码及版本准备 → PR 与测试 → 合并 → main 精确提交 CI → 受控 Issue 触发 Release → 验证公开产物」。所有发布动作以 GitHub 实时返回为证据；不能把 PR 合并、CI 启动或草稿 Release 说成发布成功。

固定项目：qinze889/DoubaoLanInputBridge（公开仓库），默认分支 main，仓库所有者 qinze889。此 Skill 只对声笺执行写入/发布操作。用户指定其他仓库时，先审计其独立发布机制、授权及校验规则，不能照搬发布指令。

触发示例：「发布声笺 v1.4.2」「为声笺跑 CI，全部通过后发布 Release」「把新版本上架，让 Windows 客户端检查更新」。不触发示例：「一键更新是什么」「发布机制能否实现」。

## 前置核实（每次从 GitHub 实时读取，不使用历史对话的状态）

1. 检查连接用户是否有仓库写权限；核对仓库、main HEAD SHA、最新公开 Release 的 tag/版本、目标版本是否存在 Release 或 tag。
2. 查看相关 PR、代码树、变更范围及 CI。严禁引用旧提交的成功 CI 来证明当前提交已验证；cancelled / skipped / in_progress 均不算 success。
3. 阅读发布实现：
   - .github/workflows/windows-client.yml
   - .github/workflows/apple-clients.yml
   - .github/workflows/release-on-request.yml
   - scripts/release_assets.py
   - docs/RELEASE-AUTOMATION.md
4. 确认目标版本大于最新公开版；未完成版本准备时，先做新版本代码，不能只修改 tag 或重命名旧安装包。

## 版本与代码准备

需要改动程序时，在单独分支提交并创建 PR，确认 lint、前端测试、Python 回归和 Windows/macOS 构建结果，再合并。若构建报错，审查日志、修复根因并重跑，禁止跳过门禁。

所有对应的版本字段应保持一致：
- VERSION
- src/gui_app.py 的 APP_VERSION
- desktop/package.json 和 desktop/package-lock.json
- desktop/src-tauri/Cargo.toml 和 Cargo.lock
- desktop/src-tauri/tauri.conf.json
- packaging/Info-native.plist（CFBundleShortVersionString；CFBundleVersion 应单调增加）
- native/ShareExtension/Info.plist（同上）
- native/ShengjianApp.swift 中的展示版本
- README、CHANGELOG 的当前源码与发布记录（不要提前宣称未发布版本已经公开）
- scripts/smoke_desktop_ui.cjs 和其他安装/服务冒烟测试中可能写死的旧版本。优先以 VERSION 为单一事实源，避免硬编码版本误判。

iOS 版本号可能独立维护，勿未经审查把 iOS 的 MARKETING_VERSION 自动改成桌面版本。

## 正式发布门禁

将待发布变更合并进 main 后，**重新**获取 main 的完整 40 位 commit SHA，并确认同一 SHA 存在两次 GitHub Actions push 运行：
- Windows client：所有 jobs 完成且 conclusion=success；应包含 UI、安装覆盖升级、协议/P2P、打包附件。
- Apple clients：所有 jobs 完成且 conclusion=success；应包含 Mac 构建、签名/DMG/ZIP、iOS 和相关传输测试。

在 GitHub 上检查两个 run 的 head_sha = main HEAD、head_branch = main、event = push。附件必须属于这两次 run。若 main 发生新提交，需要重新取得 SHA 和与之匹配的 CI；不能复用旧 run。禁止把成功的 PR 检查替代 main push 检查。

如 hdiutil 遇到偶发 Resource busy，可先对**同一提交**的失败 Mac job 重跑一次；若重复失败，修脚本走新的 PR 和 main CI。其他失败遵循相同原则。

## 触发发行（仅在上述全部成功、且用户确实要求正式发布时）

本仓库的 GitHub 连接器可能没有直接的 workflow_dispatch / create release 接口，使用已经验证的 Issue 触发机制，不要求用户提供 PAT：

1. 确认 .github/workflows/release-on-request.yml 已在 main 上启用。
2. 使用 GitHub create_issue，在 qinze889/DoubaoLanInputBridge 创建**全新** Issue。作者必须是仓库所有者 qinze889：
   - 标题严格为 Release vX.Y.Z，例如 Release v1.4.2
   - 正文严格为单行 commit: <main 最新完整40位 SHA>
3. GitHub Actions 的 issues: opened 事件启动 Release on owner request。
4. 在当前会话跟踪该 Workflow。它校验请求人、版本字段、main HEAD、未发布 tag、两平台精确 SHA 的成功 CI、附件 SHA256，然后先建 Draft、上传附件，最后才公开为 Latest。
5. 在发布失败时严禁宣称成功；查看失败 job/log，必要时检查并清理草稿，但不可覆盖已公开 Release。修复后必须重新审查提交、CI 及发行状态，再用新的 Issue 触发。
6. 发布成功后，检查 release tags API 与 releases/latest：tag 正确、draft=false、prerelease=false、source commit 正确、Windows 安装版资产与 Mac DMG/ZIP 存在、SHA256 摘要/构建元数据存在；关闭作为发布请求的 Issue（completed）。

如工具无法写入 Issue、连接用户不是所有者，或本仓库 workflow 缺失，解释具体阻塞；不得虚构已触发或已发布。

## 客户端更新的正确承诺

Windows **Tauri 安装版**已实现通过 GitHub Releases/latest 检查版本，下载优先匹配 *-setup.exe 的 NSIS 安装包，并在校验后静默原位覆盖安装与自动重启。通常操作：打开声笺 → 设置 → 检查更新 → 立即更新；无需用户手动卸载。

不要把这个过程称为真正的运行时热更新：需要结束旧进程以替换 EXE。至少在 v1.4.1，客户端并没有真实实时百分比下载进度条；Qt 便携版和 macOS 原生版不保证拥有与 Windows Tauri 相同的一键更新路径。GitHub 访问失败、旧安装方式不同或权限问题都可能使客户端更新失败，不能声称已远程验证用户电脑完成升级。

## 发布完成后的验收与报告

只在 Github Release 正式公开、运行成功并核验最新 tag 后报告「已发布」。提供：
- Release 链接和 tag
- main commit SHA
- Windows / Apple CI 各自 run 链接与 success 状态
- 发布 Issue 和 Release on owner request 的运行链接
- Windows 更新方法及平台限制

若 CI 仍在运行，只报告已经完成的事实，明确写「尚未发布」；不能承诺本轮会话结束后后台继续工作，除非实际创建了独立可执行的自动化。

## 可移植性

本目录符合 Agent Skills 格式。Codex 从项目的 .agents/skills/shengjian-ci-release/SKILL.md 自动发现；在其他 ChatGPT 对话中可显式给出本文件的 GitHub 链接并要求读取遵循。若希望在 ChatGPT 的所有合资格会话通过 @ 调用或自动匹配，需要在相应产品的 Skills / Plugins 功能中**安装**该 Skill；仅提交 GitHub 文件不等于安装到 ChatGPT 账号。
