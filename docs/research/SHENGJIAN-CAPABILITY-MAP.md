# 声笺能力、Harness 复用与 GitLab 定位

> 本文主体是实施前基线核查。后续本轮已接入有界子代理状态、自有技能目录和独立后台浏览器，并完成真实双子代理并行、send_message、skill 加载、网页操作、本地记忆重启保留及一次性日报调度验收。最终状态以 [调查索引](README.md) 和 [运行说明](../LOCAL-ASSISTANT.md) 为准。用户已明确指定“研究报告进 rev”；GitLab SSH 已验证并同步 origin/main，只归档研究材料，不将声笺源码推入 rev。

核查日期：2026-10-23。声笺源码基线 `5a36757`，分支 `feat/shengjian-core-v2`；本轮功能仍在工作区更新。本文是源码、配置及只读远端检查结果，不把静态安装或配置启用当成真模型验收。豆包/GPT 安装包的 REA 证据由独立报告记录；本文没有为源码仓库分析伪造 REA Evidence ID。

## 已有能力与缺口

| 能力 | 已观察到的实现 | 还需完成的产品接线或验收 |
| --- | --- | --- |
| 手机语音转电脑任务 | `server/core_v2/assistant.py` 接收最终识别文字、幂等 request ID、设备 ID，并创建持久任务；电脑主动建立 WebSocket 领取 | 持续真机测试语音任务、网络切换和任务反馈 |
| 状态、追问、取消与单次审批 | 同一 assistant turn 支持状态、取消、允许/拒绝；Journal 保存任务身份和事件；结果未知不重放 | 原生手机体验、异常中断和审批 UI 的长期验收 |
| 多个电脑任务 | `Connector.active` 接收多个任务；`execution_slot = asyncio.Semaphore(1)` 串行执行电脑任务 | 这不是并行工作区。若放开，应先按工作区、文件及桌面设备锁隔离，不能直接去掉信号量 |
| 子代理并行 | 下述 DSH 官方 subagent 模块已安装，默认 headless profile 有配置启用证据 | 尚未在声笺真模型任务中证明并行子代理、父子通知、取消和用量归属；声笺也没有子代理树 UI |
| 会话衔接 | `conversation_task_id` 将上轮任务和结果作为下一任务参考；任务 ID/事件可持久补读 | 当前 `HarnessEngine.run` 每次运行 headless，没有传 `--session-id`；不能称为跨任务恢复同一模型 Session |
| 同轮代理消息 | DSH 默认 subagent-control 提供消息控制；team 模块另有同队通信 | 声笺尚无跨独立任务的受控邮箱；子代理消息不能当作用户授权来源 |
| 技能 | DSH 默认 skill、skill-filesystem、tool-skill 已配置挂载 | 缺声笺技能目录、启停、版本/来源/许可证展示及能力授权；不能把复制第三方 prompt 当作技能集成 |
| 连接器 / MCP | DSH mcp-resources 默认挂载；mcp-client 包已安装 | base/headless 中未观察到 mcp-client 默认挂载，也未发现声笺连接器配置 UI。不能称为“已连接第三方服务” |
| 本地记忆与定时任务 | 本轮 `PersonalStore` 新增独立本机 SQLite WAL；显式记忆、按设备隔离、领取执行槽、错过不补跑；App 调度器提交任务 | 工作区实现与安装包、真机验收分开记录；不是云端全天候定时执行服务 |
| 后台网页执行 | 本轮独立 headless Chrome / Edge 会话和工具桥正在接入 | 不占用用户浏览器的设计不能泛化为任意原生桌面 App 的虚拟桌面；需实测焦点、表单、终止和清理 |
| 桌面 App 控件 | 本轮原生 AX 工具、快照 ID、过期和操作后重新观察 | 系统授权及应用自身的后台控件支持仍是前提；Windows UI Automation / 完整视觉 computer use 未完成 |

## 优先直接复用的 DSH 官方模块

安装目录为 `tools/dsh/node_modules/@deepseek-ai/`，版本 `0.2.1-rc.2`。主 Harness 与 subagent 包中的 LICENSE 均为 MIT；打包复用应继续保留许可证。

| 用途 | 可复用模块 | 本轮核查结果 |
| --- | --- | --- |
| 基础子代理 | `dsh-subagent`、`dsh-subagent-spawn-in-process`、`dsh-subagent-fork-in-process`、`dsh-tool-subagent` | base profile 挂载 spawn/fork provider；分别注册 `subagent`、`subagent_fork` |
| 父子控制与消息 | `dsh-tool-subagent-control`、其 `list-agents` 入口 | base 默认挂载；tool-subagent 源码明确先返回子代理 ID，完成后通知；支持可继续 provider 时由 `send_message` 引导交互 |
| 团队协作 | `dsh-experimental-agent-team`、`dsh-experimental-tool-agent-team`、`dsh-experimental-agent-team-profile` | 已安装但非当前默认 profile；实验 profile 显式禁用普通 subagent 工具后加入团队工具，默认上限 8 成员、256 共享任务；需专门验证，不能无测试整体套用 |
| 团队共享任务 | 同上 tool-agent-team | 源码提供 `spawn_teammate`、`send_message`、`list_agents`、`wait_agent` 及带 revision 的共享任务领取；发送成功不等于对方处理完成 |
| 技能 | `dsh-skill`、`dsh-skill-filesystem`、`dsh-tool-skill` | base 默认挂载，可围绕声笺任务、报告、文件处理编写自有 SKILL.md |
| MCP | `dsh-mcp-client`、`dsh-mcp-resources` | 前者已安装但未在默认 base/headless 中挂载；后者已挂载。连接服务应按账号、设备及工具能力授权 |
| 会话持久化 | `dsh-session-persistence-jsonl`、`dsh-session-query-sqlite` | base 挂载。查询配置为 `path: ':memory:'`、`openAt: never`，全文检索默认关闭；挂载不等于全文搜索已可用 |
| 进程作业 / 调度 | `dsh-jobs-local`、`dsh-tool-jobs`、`dsh-schedule`、`dsh-tool-schedule` | 已安装；声笺 headless 子进程每任务结束，不应依赖该子进程承载长期 App 调度器 |

### 实际 headless profile 的配置证据

开发版数据根目录中 `agent/state/harness/home/profiles/headless/package.json` 的 `dsh.profile.bundles` 为 `@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-headless`。该 profile 用户 patch 只有空列表，没有 home 级全局 patch。

`dsh-base/cordis.patch.yml` 的第 359–395 行挂载 subagent 与 spawn/fork、控制及委派工具；第 308–315 行挂载技能工具；第 492–493 行挂载 mcp-resources。`dsh-headless/cordis.patch.yml` 没有禁用这些模块。声笺 `server/desktop_agent/harness.py` 的 overlay 主要替换模型路由并插入审批与本机工具，也没有禁用它们。上述证据证明配置层已接入，尚不证明实际模型选用、并发数或 UI 展示已经验收。

建议先让现有 `subagent` / `subagent_fork` / `send_message` 在单个声笺父任务内完成两个互不冲突的只读子任务，记录开始/结束和用量，再扩展 UI；随后再评估实验 team 模块。文件写入、AX 控件、一个浏览器页面等共享可变资源必须保留各自锁，避免并行任务互相踩状态。

## 已定位的 GitLab rev 资产

真实 Git 工作副本：`/Users/tqq/Desktop/lianqi`，HEAD `67552af`，分支 `main`。现有 origin：

`ssh://git@nas-biaoxun:10125/xjiaoai-group/rev.git`

其中有一份不属于本轮的未跟踪微信验收报告，应保留，不纳入本任务提交。另一个 `/Users/tqq/Desktop/wx-公众号/rev` 是已有逆向材料目录，但不是 Git 仓库，不能作为 GitLab 同步入口。

| rev 模块 | 适合借鉴的部分 | 复用边界 |
| --- | --- | --- |
| `doubao/gateway-audio/` | ASR/TTS 协议、串行执行、错误归一、FFmpeg 与关闭处理；声笺已调用部署网关 | 该 overlay 依赖现有 manager 的账号池、加密、鉴权和日志，不是独立程序；不得复制 Cookie/账号库或整套覆盖层 |
| `ai-gateway/model-routing/`、`routing-failover/` | 调度阶段、路由错误、有界重试、隔离 release 和匿名验收回执 | 模型路由 retry 与电脑命令重放语义不同；不能把模型 failover 套用为电脑操作自动重试 |
| `ntfy/` | 完成/失败通知、一题一链的决策回执、pending 不等于同意 | 旧部署地址、主题和账户配置不是声笺默认配置；通知与对外发送需要相应用户授权 |
| `workbuddy/` | Harness 能力拆分、子代理描述、工具/技能入口的研究材料 | 第三方提取的 prompt/资产不等于可自由分发的开源模块，先核查来源与许可；优先实现行为合同 |
| `codex-desktop/` | 普通 Chat 与 Codex Responses 分离、客户端合同和服务端未知的区分方式 | 静态合同不证明服务端 Agent 编排实现，也不应混同 GPT、ChatGPT 与 Codex 的全部能力 |

## GitLab 同步状态与阻塞

1. 声笺当前唯一远端为 `origin = ssh://git@github-mac/qinze889/DoubaoLanInputBridge.git`；没有 `gitlab` remote。不能宣称本轮声笺代码已同步到 GitLab。
2. `~/.ssh/config` 已有 `nas-biaoxun`：HostName `nas.xjiaoai.com`、Port `10125`、User `git`、IdentityFile `~/.ssh/id_ed25519_biaoxun`、IdentitiesOnly yes。只读核对私钥权限为 `600`，没有输出或复制内容。
3. 对已配置 alias 仅做一次 `ssh -T -o BatchMode=yes -o ConnectTimeout=10 nas-biaoxun`，返回 GitLab 对 `@tqq` 的欢迎消息，说明该 SSH 身份当前认证可用；这不证明它对某个尚未定位的声笺项目有写权限。
4. rev README 仍声明 `http://192.168.1.33:10124/xjiaoai-group/rev.git` 为唯一源，现 remote 已为上述 SSH alias。应先记录该历史 HTTP / 当前 SSH 差异；本轮没有修改 rev remote 或写入 rev。
5. 已配置 GitLab HTTP API 的匿名项目搜索（`shengjian`、`shenjian`、`DoubaoLanInputBridge`、`声笺`）均返回空；已知存在的 `rev` 搜索也为空，说明匿名可见范围不足，不能据此断言声笺项目不存在。当前未发现 glab 配置、GitLab 环境变量或可用 GitLab API token。
6. 后续需以已授权的 GitLab 项目查询或用户给定的精确项目路径确认目标，再添加保留原 GitHub origin 的 GitLab remote，推送独立分支并验远端 SHA。不要凭名称猜测项目存在、不要把声笺整树推到 rev，也不要改用裸主机名、更换账号或生成新密钥绕过认证。

本次子任务只写本报告；未 fetch/push、未修改认证、未提交代码、未操作用户会话或账号池。
