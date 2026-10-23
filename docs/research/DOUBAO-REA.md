# 豆包 2.32.6：REA MCP 调查与声笺取舍

日期：2026-10-23。本轮直接使用 REA MCP 检查本机已安装文件，未注入、运行或激活豆包，未读取用户 Cookie、账号凭据、聊天记录或请求第三方私有 API。本文把静态观察、推断和未知分别列出；不是恢复了豆包全部服务端代码。

## 目标与可复查证据

目标 `/Applications/Doubao.app`，Bundle ID `com.bot.pc.doubao`，版本 `2.32.6`。主程序是 arm64 原生入口，内部另有 `Contents/Helpers/Doubao Browser.app`，Chromium 框架目录版本 `147.0.7727.149`。本机 `/Applications/豆包浏览器.app` 不是可直接按目录读取的独立 app，未以它替换目标。

| REA Evidence | 范围 | 观察及限制 |
| --- | --- | --- |
| `ev_9da6b601c477d0f238ae20c602d9b0318bd32ef7ed71d3a69bc70bf5b2222c99` | 主程序 Mach-O，SHA `fc864bb35e99dfc0398101e8d6c7075ac85120f0e731c9606ce6eba2a6a2a62c` | AppKit、ApplicationServices、CoreGraphics、AVFoundation、CoreAudio 等链接依赖；链接不证明某条工具路径运行 |
| `ev_2d1a2214bb1a1262f4ac6bdf2d807ef96564292d5dd1defaf6313961f772e266` | 主程序签名元数据 | Developer ID 团队 `96L78H6LMH`、hardened runtime，声明麦克风、摄像头、Apple Events 等 entitlement；签名元数据不能替代具体系统授权或证明全部资源来源 |
| `ev_4f084e38f5accea7adc851e369b44ddd66c88805b5e9d7e371da00560801d713` | `Helpers/libmcp_helper.dylib`，SHA `b13508d453bd327f40ca3ae95895ac8a979c3a1efb6d70964f6031c146550460` | 存在 `_saman_mcp_helper_abi_version`、`_saman_mcp_helper_run` 导出与 socket 引入；没有据此宣称恢复 MCP 的完整认证/服务协议 |
| `ev_be3445bc3c6887901691f1ee2a28a1686fe99ae4cfbbfef60c2625306562a763` | 包内 `rpa-component-extension`，目录 SHA `6bdd136df494a49093c1d9c145395b801536febe8830cf57266af7590a59003e` | 2 JS、47,225 AST 节点、0 解析失败；语义图触及 100,000 节点上限，8,123 个未知，不能称为完全反混淆 |
| `ev_e6b79a4b52be9df5bbfbbf53076b9c47a360e6b90addb15cb45af06d1c28a566` | 上项 summary | 保留父 Evidence，避免重复分析大图 |
| `ev_0a7849c24cf19338bfe5141875a65f446e537140078f2482b9407ed24846d249` | RPA background.js module view | 绑定成员 SHA `08960946891bcfabe4a8ca614377fd446bf1eab4908d9edf2f1578cb902f0c09` 与源范围；没有执行 bundle |
| `ev_8f3842fa9a153b3b92b14be1fa1ec34f23db32bc9affe28949f2c35a1f7d5364` | `apps/entry-main`，目录 SHA `6aa0340175ee4cd1939f83c637280a3611f32a829bf9771a60dcf75df92c67ff` | 1 JS、86,277 AST 节点，worker 资源限制使覆盖 partial，语义关系尚不完整 |
| `ev_2d20ec15a8cb39831d6f1fa5a6e093a5fe801c89d40f1655fab89e30b352be2c` | 下述 6 个完整成员文件的派生选集，目录 SHA `82341472c97eacff1d38a773ce8ffcaeca9aa89b93ad18dcb29265ff275a6d3e` | 41,038 字节、6 JS、11,462 AST 节点、151 findings、0 解析失败；只对选集完整，依赖未纳入，2,588 个语义未知 |
| `ev_59f3c32ea37a104a569efb3e70c5cccd6769d4a40baeca14431d208a59af82cb` | 选集 summary | 来源路径与各成员 SHA 保存在忽略目录 `artifacts/rea/doubao-feature-selection/selection-manifest.json` |
| `ev_82bd2466db05858e8d30f271ff5f8dbdd8c05c603253770b4e8c075d405025d8` | 选集模块身份页 | 同一文件可对应多个打包模块，后续引用须使用 node ID，不能只凭文件名当作函数调用关系 |

两个 feature trace 没有命中：`ev_0447802c8d2efcb883ff803d051bf3fd1730e542d7c0289b95dde18d5e026068`（chrome.debugger）与 `ev_ecdfcfcc7a47fa0c1a8389221af8d2e4f12385a949c709cb5b39a514a6333302`（subagent）。这只是 REA 图实体的未命中，不能当作功能不存在。具体文字观察来自另行读取哈希绑定成员，下面不会冒称图已追通。

`recover_javascript_sources` 本机不可用：该 provider 要求另行提供 Wakaru Linux x64 二进制。已读取技能恢复说明，未反复重试、未安装不相关运行时，也未把未解开的混淆代码说成原始源码。

## 按功能归纳

选集来自包内 `.../Resources/local_webcontents/extensions/ai-views/static/js/async/`，选入完整文件而非截断/修改源代码：

| 功能 | 实际静态观察 | 可以借鉴的机制 | 尚未知 |
| --- | --- | --- | --- |
| 子代理及任务面板 | `s2-agent-moa-task-list-conversation.js` 有 Thread、SuperTask、SubAgent 分类及 sub_agent、任务进度/任务计划面板路径 | 父任务统一展示、子任务状态分开、完成后聚合结果 | 模型如何决定拆分、服务端真实并发数、预算、调度策略；不能仅据开关 enable_multi_subagent 还原这些 |
| 会话与任务衔接 | `async-agent-thread-message-lifecycle.js` 构造任务输入，包含读取 Agents.md、准备上传、官方技能安装/下载等桥接调用 | 区分对话消息、任务输入、文件/技能依赖；本机任务有自己的生命周期 | 任意独立会话之间能否发消息、服务端 ACL、持久邮箱实现；UI 子任务不能证明跨会话通信 |
| 技能 | entry-main 有技能清单/引导/增删改桥接名；线程生命周期中观察到 `neotix.aiSkill.readAgentsMd`、download、uploadPrepare、getInstallGlobalOfficialSkillsInfo、installGlobalOfficialSkills | 技能目录、元数据/正文分层、准备依赖、来源/版本可追溯 | 私有技能正文和服务端执行不在这些观察内；不能将一组 prompt API 直接视为可分发技能包 |
| 连接器 | `s2-agent-connector-menu-option.js`、`s2-agent-connector-tool-button.js` 有连接器选择与 pendingConnectorIds 等界面状态；entry-main 有 connector_oauth 入口 | 身份绑定、授权进行中状态、工具选择和撤销分层 | OAuth 后端、真实 token scopes、第三方调用协议；本轮未请求认证接口 |
| 定时任务 | `s2-cron-jobs-submit-pipeline.js` 有 CronJob、模板及 connector 参数进入提交流程 | 明确把日程内容、连接器依赖和执行任务分开 | 服务端时区、漏跑/重试、幂等、休眠唤醒策略；不能照搬 UI 参数就说实现完整调度 |
| 语音 | 原生入口有音频框架与麦克风 entitlement；rev 已有单独 ASR/TTS 网关报告及当前声笺实际接入 | 延续既有串流 ASR/文字任务/TTS 分层与中断控制，避免将执行器绑定在录音连接上 | 本轮没有采集豆包实时语音运行时，不能报告其首音耗时、AEC 或全双工内部算法已恢复 |
| 浏览器 / computer use | 安装包有独立 Chromium helper 和 RPA 扩展；RPA 混淆文件可见快照/截图字段、clickCount、键码及调试连接关闭处理 | 独立浏览器会话、观察—操作—再观察、动作与结果分开、连接失败不盲目重放 | 是否总是 headless、是否抢用户焦点、完整虚拟桌面/输入实现、账号灰度均未通过静态资源证明 |
| 原生工具 / MCP | 原生 helper 的 ABI/run 导出与 socket 导入；主入口声明受限应用 Apple Events | 工具桥接、原生 ABI 与模型协议隔离；桌面系统权限独立管理 | ABI 细节、协议和参数安全语义未恢复，不直接调用未知 helper |

**RPA 来源要单独保留疑问。** background.js 开头自称 `RPA Dev Local external build: deterministic JavaScript obfuscation.`，另含回环 WebSocket 端点。它存在于本机安装目录是观察事实；本轮不能确认这是厂商正式发布、自建扩展还是本机后加组件。因此不能把该扩展的每个细节归因为“豆包官方原理”，也不会将它作为声笺发布依赖。

## 声笺采用的集合

1. 保留现有豆包语音适配、sub-buddy 和 MIT 许可的 DeepSeek Harness，不整体替换为目标客户端的私有覆盖层。
2. 网页执行采用声笺独立无界面 Chrome/Edge profile，使用公开 CDP 的 Page/Runtime 接口，不连接用户当前浏览器。结构化网页快照与失效 ID 由声笺实现。公开接口来源：[Page](https://chromedevtools.github.io/devtools-protocol/tot/Page/)、[Runtime](https://chromedevtools.github.io/devtools-protocol/tot/Runtime/)。
3. 复用 Harness 已有 spawn/fork、父子消息和完成通知；声笺选择 3 个子代理、深度 1。并发浏览器各自隔离，原生 AX 操作只由主代理进行。不是从豆包/GPT 推导其并发上限。
4. 自有 SKILL.md 首批为后台网页、电脑日报、任务目录整理；按需读取。只扫描声笺自己的技能目录，避免把本机其他 Agent 的全部技能或配置隐式接入。
5. 本地专属记忆与日程使用声笺独立 SQLite WAL。采用清晰领取、过期与未知状态，不假设豆包的私有实现与此一致。
6. 会话邮箱、完整连接器管理、OAuth、跨任务长期会话、团队共享任务作为独立产品能力接入，先明确授权与测试，不把已安装 npm 模块显示为“已连接”。具体既有模块与缺口见 [能力地图](SHENGJIAN-CAPABILITY-MAP.md)，GPT 对照见 [GPT 调查](GPT-REA.md)。

所有目标程序私有源模块仅留在本机忽略的分析材料目录，不纳入声笺源码或安装包。每条原生 REA 会话已关闭。本 MCP 连接在关闭原生会话后导出返回 records=0，不能称为完整图证据包；已将本轮原始完整 inline MCP 响应另存 `artifacts/rea/doubao-mcp-inline-evidence.json`，明确标记非 canonical bundle。父图编号、覆盖限制与成员哈希仍可从这些实际响应复核，完整父语义图未保留。
