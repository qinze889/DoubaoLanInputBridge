# GPT / ChatGPT / Codex：声笺复用调查

调查日期：2026-10-23。范围为本机已安装包的只读静态检查、REA MCP 和当前官方文档；未启动、注入或激活目标客户端，未读取账号 Cookie、令牌、聊天数据库或用户内容。本文记录观察与设计取舍，不表示已经复制或恢复服务端实现。

## 目标身份与证据边界

本机只有一个明确匹配的安装包：`/Applications/ChatGPT.app`。其 `Info.plist` 声明 Bundle ID `com.openai.codex`，版本 `26.1013.40934`，构建 `20770`，主程序 `ChatGPT`。不能把这个安装包称作旧版独立 ChatGPT 原生客户端。

| 文件 | SHA-256 |
| --- | --- |
| `Contents/Info.plist` | `8520b12f2bcf41fe7bb2d7d0fca7043ed495497c5a5405aafea01933f1b53058` |
| `Contents/MacOS/ChatGPT` | `0e00971d153a24b34bcba44fce1253d1a68573e09441bb7717585094227966b4` |
| `Contents/Resources/app.asar` | `5ddc4e48259aa6f979e04529b1a5a4ae54b0f5c4ad6db5c6e004924c10916ddb` |
| `Contents/Resources/codex-cli/codex-package.json` | `558c7aabb05ccc87bdb8c8514f87659fec72929a39919c7156f8b8889f7589b3` |
| `Contents/Resources/cua_node/manifest.json` | `b64afbf6eda206e63d1fb0367d6f450fd7d153ef4becdd793c483378e3492974` |

ASAR 582,430,926 字节，目录有 21,174 个叶节点。包内元数据声明 Codex CLI `0.163.0-alpha.10.2`、`aarch64-apple-darwin`；CUA Node 运行时清单声明 Node `24.21.0-cua.1` 和独立 `node_repl`。这证明组件随包交付，不能单凭名字证明它们在当前账号下启用或怎样在服务端运行。

REA MCP 调用记录：

- `inspect_plist({path: ...})` 在本连接版本仍要求活动 app，返回 `target_unavailable`；没有为了绕过该限制打开共享原生分析会话。
- `analyze_javascript_application` 对实际 `app.asar` 首先因 unpacked `permissions.node` 声明与实测哈希不一致而返回 `artifact_integrity_mismatch`。声明值 `5f2f66c4fe19493bba7ca2e0c322ed256e39f66d4a58865875431c2ddd4d58a1`，实测值 `b74218997ea3eab75d05966ed67baf00fb2e1e3151453c5db4898338f8cf4297`。签名或 strip 是工具提出的可能原因，本调查未证明具体原因。
- 随后显式改用 `integrity_policy=record-and-continue`、`detail=summary`；MCP 在 300 秒传输等待后超时。按原始 ASAR SHA 查询 Evidence bundle，没有可恢复的完整分析记录。因此没有声称完整图分析成功，也没有重复启动同一整包分析。
- 为继续查明具体问题，从同一 ASAR **按原偏移逐字节读取**下表 L-1 至 L-8 的 8 个模块至临时目录，另写来源 SHA/成员 SHA 清单，交给同一个 REA MCP 做限定目录分析。没有执行模块或补造缺失依赖。该派生目录 SHA 为 `eb9162b96884053ff1aa89d4980de699b678896f6479e7a4f6369056c678f20a`。

成功的 REA MCP 证据：

| Evidence ID | 范围与结论 |
| --- | --- |
| `ev_4d8d0213672a909bdff007f36366446526c0f48214a5a89e9fc65e742d11b609` | 8 个实测哈希匹配模块及来源清单的限定静态分析父记录：读取文本 23,069 字节，解析 8 个 JS 文件、5,877 个 AST 节点，0 个解析失败、230 个 findings。仅对选入目录完整；未包含依赖导致语义覆盖 unknown、1,294 项 unknown。 |
| `ev_db2ae99c9cc6b41f43aadba8d8d3d869be22e47ad3bcee5a03e30c7a60d455bc` | 上述父记录的 summary projection；不是完整 ASAR 的 Evidence。 |
| `ev_500393eedb5da013e64c4b0f5c3ff5704e122c5cf4f818e9a32d6c48cc79d56e` | 模块身份分页，记录 source-module、asset 和未解析模块引用等不同角色；同一路径可能有多个节点。 |
| `ev_ed3dda20470785db251e757624a7a76ce737f34ced8d2f066a2f54209e2da1a4` | L-5 的 source-module：确认 SHA、CommonJS、`readHostedSkills` 导出及源码范围。 |
| `ev_2db75c4c8d404ff49d299ceeb370f47360a716d082d2d53d88db297bcfd29fdd` | L-3 的 source-module：确认 SHA、ESM、导出及源码范围；不证明函数实际运行。 |
| `ev_9f64ed207da707a141be079c8b0c5559c9ee1030b5a766fe07efe41bf0cb75f6` | L-6 对未纳入的 app-initial 模块的未解析引用，明确保留低置信推断，不能当作依赖解析成功。 |
| `ev_5d7bf2e54f53b88b1ec849717942cd388d5b9f421d92e663d4ded2ae5015b6d7` | 对私有查询路径做静态 feature seed 时图中 no-match；不能据此认定该文本或功能不存在，L-4 的原始模块直接读取已确认文本。 |

下面 `L-*` 是另行逐字节读取源模块的本地静态证据编号，不是伪造的 REA Evidence ID；REA 图的语义未知不以人工推断冒充工具已验证。

本轮 MCP 完整证据包已导出并压缩保存至本机 `/tmp/shengjian-gpt-rea-evidence-20261023.json.gz`（90,398,603 字节）；解压后 canonical JSON SHA-256 为 `c9a15c68591df3b2836c64ec4c4f430863895190b38c2f94f11a0b285d1d75d5`。这是临时证据材料，不纳入源码分发；它可包含大量静态语义元数据，不能视为可移植的产品实现。

## 已读到的客户端实现

以下结论来自 ASAR 文件内容及 SHA，不来自文件名猜测。只摘录机制，不把私有实现复制进声笺。

| 编号 | 模块与 SHA-256 | 实际观察 | 不能据此认定的事情 |
| --- | --- | --- | --- |
| L-1 | `webview/assets/subagents-204a0bfeaba2.js` / `a72d7b94ea4f8f77db3864f6a3db701191d5d58700a6b879b08f3d1255472edb` | 子代理按 `threadId`、显示名与 waiting/working/done/failed 状态呈现；完成后查询最终答复，主页面采用摘要 | 缩略图仅展示前 4 项，不代表服务端并发上限为 4 |
| L-2 | `webview/assets/open-local-conversation-subagents-panel-788bc8caa60b.js` / `44f0773ec4698bb0b9e32e843c92cf2aa016c910e19828001590cf79bc3c4ab9` | 本地子代理面板有 hostId、父子 conversation ID、持久路由和分步后台历史加载；异步完成前后核对当前选择，避免旧请求覆盖新选择 | UI 逻辑不证明服务端授权完整性，也不证明跨账号可读 |
| L-3 | `webview/assets/verify-descendant-be22b1809f2c.js` / `4277a0ff1dbb16516bad2e0a209a4a4a5e3575f1370416ee3984b65f0712de39` | 展示前验证后代关系、host 是否匹配，并用 visited 集合防祖先链环路；缺失时有受控补载 | 不能据此构建任意会话间读取或发送权限 |
| L-4 | `webview/assets/chatgpt-subagent-final-response-query-8082a0f565c5.js` / `f88d9aa6829bb1356b8a1befc554cd46e373091568e2d59bfef473e8d4c7544b` | 以 conversation/thread/activation 组成查询键，优先提取 final_answer；暂无结果采用有界退避重试 | 观察到私有查询路径不表示可作为声笺公开集成接口；本调查未请求该接口 |
| L-5 | `.vite/build/skills-B8B2Ke2-.js` / `5f57de2c330133761ae55585305802fc423ecb5fa91ec6b32a17636340d291e1` | 技能读取有 schema 验证、绝对路径检查、文件/流长度上限、去重和有界分批处理，区分 repo/user；支持界面元数据 | 工作流说明不等于授予任意代码权限；该函数存在不证明每个平台都走此分支 |
| L-6 | `webview/assets/plugin-connector-setup-6e6492f1f4b2.js` / `85dedf04fe042cec039d402ae56374a8287b0ff2e0f9155ee24e2d4eff4087b8` | 连接器设置前校验 accountId/userId/connectorId/addAccountAttemptId，并以安装键避免旧安装流程重复续跑 | 没有恢复 OAuth 服务端、第三方凭据或连接器后端源码 |
| L-7 | `webview/assets/realtime-voice-codex-status-signal-76aaed8558fc.js` / `d0579b65e8d517ea3eabf68650b5c715aef56ae7bed231377fcdbdc614d1942a` | 语音界面从当前线程的进行中 items 派生 thinking、命令、文件编辑、MCP、等待会话、网页搜索等状态，支持并行工具数量摘要 | 不是把终端原始日志全部念出来；也不证明音频模型负责执行工具 |
| L-8 | `webview/assets/voice-prewarm-b62476fa3508.js` / `2ddcc250e1268a90cd65788f2bd964cf1eb2d85b466b63a30d67a437e70dcbed` | 语音有条件预热：账号、会话参数及资格变化会取消旧预热，使用 AbortController 和会话缓存 | 不能仅凭预热代码推断真实首音延迟；不能照搬其私有会话凭据或后端 |
| L-9 | `webview/assets/realtime-voice-handoff-target-f23194b33767.js` / `4fc7e834a53fcf4a97d68fb501de24f74e4a05d3b7fb28121db6848486cd1861` | 该模块的 handoff 实际是语音浮层/主线程界面之间的动画与锚点交接 | 名称含 handoff 不等于多代理控制权交接，不能当作 agent 调度实现证据 |

## 当前公开产品与集成边界

2026-10-23 实际访问的官方文档已将部分旧 Codex URL 重定向至 `learn.chatgpt.com`，内容描述 ChatGPT Work 与 Codex 的共有能力。不能据旧产品印象称“ChatGPT 完全没有子代理或技能”。账号可用性仍取决于各产品与账户权限。

| 能力 | 官方公开边界 | 声笺采用方式 |
| --- | --- | --- |
| 子代理并行 | ChatGPT Work 和 Codex 提供子代理工作流；文档建议先并行读密集任务，注意并行写入冲突。[子代理](https://learn.chatgpt.com/docs/agent-configuration/subagents) | 主代理负责用户答复，子代理返回有界摘要；先对检索、分析、报告开放有限并发 |
| 会话控制 | App Server 提供 start/resume/fork、事件流、进行中 turn 的 steer/interrupt；有独立 thread/session 标识。[App Server](https://learn.chatgpt.com/docs/app-server) | Codex 适配器优先走公开 stdio；产品自建会话表与授权邮箱，不借用本机其他用户聊天 |
| 技能 | SKILL.md 加资源，先加载元数据，再按需读取完整说明。[技能](https://learn.chatgpt.com/docs/build-skills) | 原生支持相同的开放目录格式，做大小、路径、版本与权限校验 |
| 连接器与插件 | 技能承载工作流；MCP 服务承载数据、身份与受控动作。[插件技能](https://developers.openai.com/plugins/concepts/skills) [MCP](https://learn.chatgpt.com/docs/extend/mcp) | MCP 客户端与工具目录独立于模型，账户级 OAuth 与设备授权交集生效 |
| 编排方式 | SDK 区分 specialist 接管与主代理把 specialist 当工具两种方式。[编排](https://developers.openai.com/api/docs/guides/agents/orchestration) | 手机对话优先采用主代理保留答复权，后台子代理做有界任务 |
| 语音与任务 | 官方区分独立语音前端、统一实时会话、可替换 ASR/文字/TTS 链路。[语音架构](https://developers.openai.com/api/docs/guides/voice-agents) | 保留豆包语音与 DeepSeek Harness；工具执行寿命独立于音频连接，播报中断不等同于任务取消 |
| 托管运行时 | SDK 在应用运行，Agents API 是 OpenAI 托管 Harness；并不是同一个部署形态。[运行时](https://developers.openai.com/api/docs/guides/agents/sdk) | 无需为借鉴编排机制改用 OpenAI 托管任务；继续现有本机执行与云端路由 |

App Server 文档当前将 WebSocket 传输标为实验性；不能直接把本机端口开放到公网当声笺生产接口。声笺的账号、设备认证、额度和断线恢复继续由自身 v2 服务负责。

## 推荐接入声笺的最小集合

这些是基于证据的声笺设计决策，不声称与目标程序的私有实现相同。

1. **语音只管交互，任务独立持久化。** 建立 conversation/task/turn 三层 ID；一条正式 ASR 最终文本生成一次幂等请求。补充要求使用 steer 类型事件；“停止播报”和“取消任务”分别处理，取消必须收到电脑确认。
2. **有界子代理。** 初始上限 3 个、最大深度 1，主代理统一汇报；每个子代理独立上下文、任务预算、工具范围和结果摘要。上限是声笺选择，不是从 GPT 产品中推断。共享目录写入和同一设备输入串行化；浏览器 profile/快照不能在并行子代理间共用。
3. **显式会话邮箱。** 消息保存 from/to、owner、device、parent、message ID、递增 seq、created/ack；只能给已授权关联会话发送明确委托或结果。默认不广播、不复制全量历史；客户端验证后代关系只是辅助，服务端必须独立校验授权。
4. **技能目录加按需加载。** 先提供“电脑日报”“整理任务目录”“后台网页检索”三个本地技能。元数据可索引，完整内容按需加载；拒绝路径逃逸与超大文件，脚本仍经过现有工具权限。不要直接安装目标程序私有技能目录。
5. **连接器适配层。** 每个连接器记录工具 schema、账号、授权 scope、来源、版本、健康状态。初版只做显式配置的 MCP 服务和已授权系统；凭据留在 Keychain/服务端。撤销账号或设备时终止对应工具会话。
6. **后台执行优先。** 网页走独立无界面浏览器；文件和报告走结构化工具；原生应用只在可证明不抢焦点时使用后台 AX。单纯调用公开 App Server 并不会给任意桌面软件生成独立虚拟桌面。
7. **有界状态摘要与预热。** 手机显示当前工具、并行数和需要处理事项；播报关键节点而非原始日志。语音预热按账号/设备/配置形成缓存键，切换或撤销时取消旧预热，避免错用旧会话。

可直接复用的是公开协议、开放技能格式及另行核对许可后的开源组件。安装包中的私有 JS、原生库、签名插件、认证端点和账号令牌不作为声笺可分发依赖；当前没有确认其再分发许可。

## 尚未回答的清单

| 问题 | 状态与下一步 |
| --- | --- |
| 所有 GPT 服务端子代理的调度算法、并发上限、跨会话通信实现 | 未知；客户端显示与公开 API 无法恢复服务端源码 |
| 这个账号下哪些连接器、模型、技能已开通 | 未调查；本轮没有访问账户内容 |
| 私有 CUA 运行时是否能给任意 Mac 软件提供独立虚拟桌面 | 未证实；清单和文件名不足以作结论，需要专门的功能入口及受控运行观察 |
| 语音预热的实际首音改善及打断回声表现 | 仅静态机制；必须用声笺真机指标验收 |
| ASAR 完整图 | 整包超时，未完成；8 模块限定 REA MCP 分析及 Evidence ID 已记录，不能外推为整包覆盖 |
| 模块是否能原样移植 | 无许可与依赖闭包证明，不采用原样复制方案 |
