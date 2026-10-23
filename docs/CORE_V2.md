# 声笺 v2：账号、语音和电脑任务

入口：`https://test.xjiaoai.com/shengjian/api/v2/console`。这是一项测试服务；旧 `/shengjian/` 传输服务独立运行。v2 使用自己的 SQLite WAL 数据库和系统账号，模型配置、豆包账号池与旧传输数据均不复制进此数据库。

## 当前实际完成范围

- Windows 的 Mac 风格 UI 与交互 CI 已合入 PR #6；Mac 分享修复已合入 PR #5。Windows 真机覆盖升级、配置保留、关闭驻留及二次启动恢复窗口已通过；稳定版发布仍等待实际设备互传与人工界面验收。
- 邀请码注册、Argon2id 密码登录、会话退出、设备登记与撤销、按设备授权、任务与递增事件、一次性审批、积分预留及结算。
- 手机网页登录、文字对话、录音识别、语音回复、停止播报、电脑派任务、进度和取消。长回复按最多 1000 字分段播报，完成的电脑任务可语音汇报；停止播报会阻止后续合成请求，不会取消任务。网页新增流式连续语音：麦克风复用，边说边显示 ASR 中间字；模型按 SSE 增量显示文字，短句立即合成，PCM 音频块收到即排程播放；模型思考、合成及播报时均可开口打断。打断会终止当前模型请求、合成请求及已排程音频，不重发旧句。尚未通过手机真机连续 30 分钟验收。
- 服务器实际发现 `workbuddy/cn:deepseek-v4.1-flash` 及 `doubao-voice/asr`、`doubao-voice/tts`。模型回复、TTS 与测试音频的 ASR 均实际返回成功。登录 Cookie 留在现有网关账号池，声笺只持有限定来源和模型的服务凭据。
- 桌面连接器主动连出 WebSocket，持久化领取任务 ID，串行在配置的工作目录中运行。DeepSeek Harness `0.2.1-rc.2` 的 headless JSON 引擎已实际通过 sub-buddy 完成文件写入；完整公网任务派发、事件补读、幂等提交和取消确认已实测。Codex 使用 App Server stdio；已用真实子进程协议夹具测试初始化、单次审批与停止进程，尚未宣称完成真实账号模型验收。
- Mac / Windows 增加“电脑 Agent”侧栏入口，明确展示 DeepSeek Harness、版本、上游模型、任务目录、连接与任务状态，可启停及输入任务。连接器已装入桌面服务，不必另跑 Python 安装器；原生 Mac / Tauri 打包流程包含固定版本 Harness 与 Node，首次启用无需 npm 下载。源码和旧版未带运行时的包保留本机 Node.js + npm 安装路径。绑定当前声笺账号，只授予任务和状态能力，专用工作目录为 `~/Documents/声笺任务`。启用状态随 App 恢复；退出 App 会关闭连接器，关闭窗口驻留时继续工作。
- CPU、内存、工作目录所在磁盘、网络累计字节和 Agent 状态通过设备心跳上报。当前不声称具有进程级服务告警或系统推送。
- iOS Foundation 客户端支持 HTTPS 固定中转链接的解析、POST 登录及 Cookie 转发，连接码不会出现在转发 URL。保留旧 LAN/CF 连接；P2P 使用网页。App 内“对话”页嵌入 v2 网页并复用持久 Cookie，扫码可直达；独立原生音频引擎尚未接入。
- Mac 开发版独立 Bundle ID、名字和数据目录，正式构建强制 Developer ID + 公证，禁止自动退回临时签名。开发包及冻结的双向 WebRTC 文件传输已经验证。用户尚未开通 Apple Developer，正式身份升级及辅助权限复用验收仍被阻塞。

屏幕视频、键鼠控制、Android scrcpy、iPhone 镜像接入、coturn 和原生手机连续语音仍属于后续阶段。连接器不声明这些未实现能力，设备页面也不把它们显示为可用。

## 首次使用

1. 在 v2 页面使用一次性邀请码注册账号；自己设置用户名和密码。
2. 在电脑运行安装器。密码由本机终端隐藏读取，不保存；只把设备 token 写入私有配置。安装器会安装独立 Python 环境和固定版本 Harness，不修改现有应用的登录凭据。

```sh
.venv/bin/python scripts/setup_desktop_agent.py \
  --workspace "$HOME/Documents/声笺任务" --name "我的 Mac" --autostart
```

`--workspace` 必须是专用目录。安装器登记并授予任务、状态能力；其他电脑上的命令不允许覆盖此目录或选择任意执行文件。Mac 的自动启动是 `~/Library/LaunchAgents/com.shengjian.desktop-agent.plist`；Windows 使用当前用户启动目录。未传 `--autostart` 时只输出前台运行命令。

3. 手机选择在线电脑并发送任务。语音识别结果可以编辑后发送。停止播报只停止声音；取消任务需等待电脑停止所持有的执行进程后确认。
4. 在设备页撤销设备会立即断开连接。更换连接器或手工重登记前先撤销旧设备；不要复制设备 token 给其他电脑。

安装器和 v2 目前仍是测试版本。Windows `.cmd` 入口使用 Node 直接启动脚本；不经过字符串 shell 拼接。Windows 原生安装与升级仍需要真机验证。

新版桌面 App 也可直接操作：账号区登录与手机相同的账号 → 侧栏“电脑 Agent” → “启用 DeepSeek Harness”。安装器保留给独立连接器与无人值守部署。App 内启用和独立安装器的设备配置分别保存，不自动覆盖对方。

## 语音与 Agent 交互

手机对话页的“电脑 Agent · DeepSeek Harness”切换到在线电脑，然后开启实时对话，直接说任务即可。普通对话模式也识别明确的“让电脑…”“用 Harness…”等派任务指令；只有一台授权电脑在线时自动选择，多台时要求先选择。无在线电脑时提示打开电脑 Agent，不伪造执行成功或偷偷排入离线队列。旧的手动文字离线排队协议保留。

`POST /assistant/turn` 接收真实 ASR 最终文字、稳定请求 ID、选中的设备及当前任务 ID，复用现有设备授权、任务、事件及额度。支持“汇报进度”“汇报结果”“查看电脑状态”“取消当前任务”；“继续…”“改成…”等后续要求附带当前任务和结果参考，生成新的串行任务，复用任务目录内文件，不宣称跨任务复用了模型内部会话。重复任务请求 ID 返回原任务；不同正文复用同 ID 会拒绝。

任务提交后停留在对话页，提供“查看任务与确认”按钮；完成、失败、取消和需要确认时加入对话。声音在用户不说话、上一段播报结束后播放；插话和停止播报会清理待播通知。任务的生命周期独立于语音连接。“停止播报”“停一下”只停止声音；明确说“取消当前任务”才发送取消请求，实际停止仍以电脑回执为准。

审批必须明确说“允许本次操作”或“拒绝本次操作”，且当前任务只有一个待审批操作；“好的”等普通词不会作为授权。预览与按次按钮仍保留在任务页。所有查询、后续和取消都校验账号和设备归属，不能借别人的任务 ID 访问或执行。

2026-10-23 本轮验收：公网服务 `20261023-4c2ebd476171` 已部署，三个新增或变更页面资产的公网 SHA256 与源码一致。350 项全量回归通过；浏览器通过最终 ASR → 派任务 → 完成播报 → 进度查询 → 后续任务 → 取消的交互链路，以及既有语音打断与登录隔离回归。Mac 安装包通过签名、架构、冻结传输与内置 Node / Harness 验证，并更新到本机开发版。实际执行中观察到 App 内置 Node 进程，Harness 经 `workbuddy/cn:deepseek-v4.1-flash` 成功创建验收文件且正文核对一致，连接器保持在线。首次联网安装曾超时，已改为打包固定版本引擎与完整依赖，构建使用 `packaging/harness/package-lock.json` 锁定；内置 Node 与 npm 包许可证随运行时保留。Windows UI 构建和交互通过，新 Windows 安装包尚未生成；远端 Git / CI 状态不变。手机真实麦克风下的新 Agent 交互仍待用户体验验收。

## 网页连续语音

点击对话页上方“开始实时对话”，首次允许麦克风即可连续交谈。说话时显示可修订的中间识别文字，约 0.45 秒停顿后定稿并提交；100 ms 连续语音触发打断检测。保留人声起点之前约 120 ms 的前导音频，避免过长静音排在识别队列中。检测在模型等待、合成和播报期间继续工作，打断旧回复后只处理新一句。安静时仅本地检测，不上传麦克风音频。

模型 SSE 文字边到边显示。首段从 4 字后的标点即可触发合成，后续按短句切分；无标点时首段最多 16 个、后续最多 64 个 Unicode 字符。首段已有 6 字而下个 token 迟到时最多等待约 140 ms，无需等整篇回复。模型目录在语音会话开启时预取。TTS 上游 AAC 经 FFmpeg 管道实时转换为 24 kHz PCM，浏览器 AudioContext 排程播放；音频领先播放位置最多约 2 秒，打断时清空排程并中止网络请求。

排程播放的真实 PCM 同时作为本地回声参考，与浏览器原生 AEC 配合，以高通、延迟相关和线性残差拟合抑制自身回放；不确定或混入真人声音时保留近端语音。打断后清除尚未播放的参考，保留已播放尾音。手机硬件、混响和非线性扬声器仍需真机验证。

打断后的上下文只记录完整播过的短段和明确的打断状态，不把尚未播出的文字当成用户已听到。短暂停顿后继续说、而前段 ASR 尚在定稿时，会暂存后一段，拿到前段真实最终结果后合并提交一次。等待和缓冲均有上限，异常时暂停，不猜测或重放。

已声明支持 early audio 的流式路径在鉴权消息之后即可发送有界起音，不再等手机收到 ready 才上传。ready 之前最多发送约 1.75 秒音频，finish 只发送一次。回复结束时也不清空已采到的下一句话起音，避免尾字和开头相碰时吞字。

网页显示按采集与播放时钟估算的本轮首音时间，包含断句等待；设备输出延迟依赖浏览器报告，计时不上传。`SHENGJIAN_VOICE_REASONING_EFFORT=low` 仅给明确选择该档的语音请求传入 low，已核对来源目录及真实返回；普通文字和电脑任务不自动改档。替换模型前需重新确认其支持的档位。

优先使用 AudioWorklet 在音频线程采集，独立于页面渲染；不支持时退回 512 帧 ScriptProcessor。16/44.1/48 kHz 连续重采样保留。每句仍限制在 25 秒切分，低于来源 30 秒上限。页面切后台、断网、麦克风断开、系统暂停音频均结束当前麦克风会话，不自动重连或重放。

选择电脑作为目的地时，同一入口连续派任务；任务仍在定稿后提交，不用中间字执行命令。结束语音、打断播报和取消电脑任务是独立操作。电脑任务继续遵守幂等 ID 和停止确认。

流式能力由认证接口 `/voice/capabilities` 明确返回。`SHENGJIAN_AUDIO_STREAM=1` 只对实际安装流式网关的实例开启；关闭时保留旧整句 ASR 与 MP3 播报，界面不伪造中间字。新增协议及网关安装约定见 [流式扩展](../server/gateway_stream/README.md)。旧客户端接口不变。

服务器侧合成音频实测：ASR 在录音结束前约 0.89 秒返回第一条中间字；TTS 首批 PCM 两轮分别约 0.83 与 1.84 秒；取消合成后开启下一句 ASR 约 132 ms。这是少量服务器侧测量，包含来源波动，不代表手机端到端承诺。网页计时仅保存在页面内存，不另行上传遥测；语音和文字仍按请求发送给识别、合成与模型服务，录音不持久化。公网入口完整链路另一次实测：首条中间字约 951 ms、句尾后 339 ms 定稿、模型首字 1622 ms、句尾到首批回复 PCM 3339 ms；音频先于模型生成完毕到达，测试账号没有残留预留额度。真实耳机、免提回声、网络切换和 30 分钟对话仍需要真机验收。

## 运行与维护

2026-10-23 后续延迟验收：三次公网接口测得 ASR 完成控制至首批回复 PCM 为 2819、3108、3610 ms，中位数 3108 ms；其中模型首字分别为 1931、1825、2386 ms，测试均完整结束且没有残留预留额度。这些数字不包含手机约 450 ms 的断句等待，不能当成手机听感或稳定低于 3 秒的承诺。回声和接续已通过仿真、跨采样率及浏览器验证，真实免提、房间混响和长会话仍等待手机验收。

```sh
python -m pip install -r server/requirements-v2.txt
python -m server.core_v2 --data /var/lib/shengjian-core --port 18767
```

服务只监听 loopback。示例 systemd 单元见 `server/shengjian-core-v2.service`，HTTPS/WS 反代见 `server/nginx-core-v2.conf`，应作为旧中转 location 的同级项载入。反代覆盖客户端地址头，HTTP JSON 最大 128 KiB；WebSocket 音频单帧及整句均有独立上限。

生产实例目录：`/opt/shengjian-core/current`、`/var/lib/shengjian-core`、`/etc/shengjian-core/providers.env`。凭据文件权限为 600；配置由 systemd 读取，服务使用 `shengjian-core` 用户。部署包含源文件 SHA256 manifest、独立 release 目录和旧 Nginx 配置恢复点。

管理令牌保存在数据目录 `admin.token`，不通过命令参数传入。邀请码和备份都写入指定的新私有文件，拒绝覆盖已有文件：

```sh
python -m server.core_v2.admin invite --credits 1000 --output /private/new-invite.txt
python -m server.core_v2.admin backup --output /private/core-before-update.sqlite3
```

备份使用 SQLite backup API，包含 WAL 中已提交的数据。恢复前停止 v2 服务，保留当前数据库和 WAL 的副本，移走当前 WAL/SHM，再以相同权限和所有者恢复完整快照，启动后检查健康及账号隔离。不要把旧传输库、网关库或其他业务库当作 v2 恢复源。回滚服务版本不能撤销已经运行的电脑操作。

当前 schema 为 v2。启动时在事务内从 v1 增加登录会话的设备关联、一次性扫码票据表及索引，保留现有用户、邀请码、设备、任务和账本。升级前使用 SQLite backup API 保存快照；旧版程序不支持 v2 迁移语义，回滚需停止服务并恢复配套数据库快照。

## App 登录与扫码

Mac / Windows 的“连接手机”页新增账号登录、注册码注册和语音二维码。电脑凭据保存在 macOS 钥匙串或当前 Windows 用户的 DPAPI 加密文件中，密码不保存，界面不取得长期 token。下次打开检查云端会话，正常时直接显示语音二维码。旧文件传输二维码与网络选择继续独立使用。

尚未登录电脑时也显示固定语音入口二维码，手机可以直接打开测试；手机已有登录态便自动恢复，否则需要先登录一次。电脑登录后二维码变为一次性免登录票据，两种二维码的提示会随状态切换。

`POST /auth/qr` 使用已登录的电脑 token 生成 120 秒、一次性票据；刷新立即作废同一会话的旧票据。二维码只包含 `/console#login=...`，票据放 URL fragment，不进入 HTTP 请求 URL 或 Referer，页面读取后立即清除。`POST /auth/qr/redeem` 原子消费票据、登记无执行能力的手机设备，并签发独立登录 token；电脑退出后未兑换的票据失效，已登录手机可在设备页单独撤销。此二维码提供账号访问，请只让自己的手机扫描。

网页登录使用 30 天 `Secure; HttpOnly; SameSite=Strict` Cookie，长期凭据不再写入 JS 持久存储。页面重开通过同源 `POST /auth/session` 恢复内存中的会话，用于现有 Bearer / WebSocket 协议；原有会话存储仅兼容旧页面。退出必须取得云端撤销回执，离线时明确报错并保留状态。认证入口拒绝跨站 Origin / Sec-Fetch-Site 请求。

iOS 增加 App 内“对话”页，使用限定声笺域名的 WKWebView 与持久 Cookie；扫码识别到云端入口后直接切换此页。旧配对信息仍保存在 Keychain。首次语音需系统麦克风许可；这是 App 内网页语音，尚非独立原生音频引擎。完整 iOS 构建及真机权限、Cookie 冷启动验收仍需 Xcode 和签名环境。

云端仍只有独立 `/var/lib/shengjian-core/core.sqlite3`：`users` 为用户表，`devices` 为设备表，`sessions` 为登录 token 表，`invites` 为注册码表，`qr_tickets` 为扫码票据表，另有任务、事件、用量和积分表。密码使用 Argon2id，token、注册码和票据仅保存哈希。手机设备撤销会删除关联会话；不会获得电脑连接器的任务、输入或屏幕能力。

2026-10-23 验收：云端已升级至 `20261023-4c75935ada58`，schema v1 → v2，升级前快照已保留，外键检查无错误；公网 HTTPS 的登录、Cookie 恢复、扫码兑换、重放拒绝、设备撤销和退出通过。Mac 全量 343 项回归通过，开发版 DMG / ZIP 完成签名、架构及冻结 P2P 传输验证，并安装到 `/Applications/声笺开发版.app`；实际打包服务的账号端点正常。Windows UI 构建、检查与浏览器交互通过，DPAPI 真机验证因远程 SSH exec 通道失败未完成，新安装包尚未生成。iOS Foundation 检查通过，完整 Xcode 与真机验证仍待签名环境。此轮没有新增远端 CI 或推送。

模型环境变量：`SHENGJIAN_MODEL_BASE_URL`、`SHENGJIAN_MODEL_API_KEY`、`SHENGJIAN_TEXT_MODEL`、可选 `SHENGJIAN_VISION_MODEL`。配置的模型必须实际出现在上游 `/models` 中；只有明确配置的视觉模型接受内联 PNG/JPEG。

优先语音变量：`SHENGJIAN_AUDIO_BASE_URL`、`SHENGJIAN_AUDIO_API_KEY`，指向已有 rev 网关的 `/v1`。网关 ASR 接收 WAV 文件，TTS 返回 MP3；继承其串行和账号状态限制，不轮换身份规避限制。单句最长 30 秒，文本合成最多 1000 字。网关错误被转换成公开错误码，不把登录态或上游原始错误发给手机。

可选官方通道使用 `SHENGJIAN_DOUBAO_API_KEY`、`SHENGJIAN_DOUBAO_SPEAKER` 及 ASR/TTS resource 配置，仅当未配置登录态网关时选择。官方通道未进行实际凭据验收，不作为当前测试服务的依赖。

服务凭据应限定 loopback、账号、模型和期限；当前首个服务凭据有效期为 30 天。到期前需用同一管理身份续配，不能切换身份或把 Cookie 放入手机。

## 任务与账本约定

- `request_id` 在账号内唯一；同 ID 同请求返回原任务，不重新执行，不同请求返回冲突。
- 在把任务发送给电脑前记录 dispatched。连接丢失或服务重启后，未确认完成的 dispatched 任务显示 `unknown`，不会重放键鼠或命令。
- 设备本机也在 SQLite 中先记录任务身份，再启动引擎。已见 ID 从不重新运行。网络断开会停止连接器持有的进程；无法证明原操作结果时保持未知。
- 取消尚未派发的任务可立即确认；已派发任务只记录取消请求，等电脑确认后才显示 cancelled。
- 手机按序号补读事件，服务器按事件 ID 去重。审批限定账号、任务和一次性审批 ID，重复同决定幂等，冲突决定拒绝。审批答复传到引擎后由电脑回报 running。
- 用量按唯一调用 ID 先预留，拿到完整用量后结算，重复调用 ID 拒绝。明确拒绝和连接未建立可释放预留；5xx、断流、无用量、无法判定结果时保留预留供核对。`GET /usage` 提供本账号最近用量；管理员通过 `/admin/usage/{id}/settle` 核对后结算或释放。结算不允许超过预留，超额需人工核对。
- 积分是内部测试额度，尚无在线支付或对外价格。当前文字按千 token 单位、TTS 按百字单位、ASR 按音频秒记账，不把此测试刻度当作上游价格。

## 验证

`core-v2.yml` 强制运行独立账号、越权拒绝、撤销、重启不重放、取消、审批、额度并发和语音协议测试，以及桌面/手机尺寸、明暗主题的浏览器交互检查。浏览器截图写入 `artifacts/core-ui/`，不提交生成文件。

```sh
.venv/bin/python -m pytest tests/test_core_v2.py tests/test_core_providers.py tests/test_gateway_voice.py tests/test_official_voice.py tests/test_desktop_agent.py tests/test_stream_voice.py tests/test_gateway_stream_adapter.py -q
node scripts/smoke_core_ui.cjs
node scripts/smoke_stream_voice.cjs
swift run --package-path ios ClientChecks
```

完整 XCTest 和 iOS 模拟器构建需要完整 Xcode；本机只有 Command Line Tools，因此本机执行 Foundation 自检，完整构建交由 Apple CI。Git SSH 连接失败时停止推送链路，不换账号、不生成 SSH 密钥；新代码已在本地提交，等待远端恢复后推送。

## 来源与边界

- rev：`doubao/gateway-audio` 的音频协议、错误语义、账号池和串行约束；本实现调用其已部署公开音频接口，没有把整套 overlay 覆盖到声笺或复制 Cookie。
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)：MIT，固定 npm `@deepseek-ai/dsh@0.2.1-rc.2`，使用官方 headless JSON 输出及 `approval/request` 扩展点。审批插件为本仓库独立实现。升级版本必须重新验收事件、审批及取消语义。
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)：使用本机 CLI 生成的 JSON schema核对 initialize、thread/start、turn/start、command/file approval。只接受本次操作，不写 acceptForSession 或永久策略。
- NanoMuse：仅参考设备任务、会话寿命与交互思路；没有复制其 GPL 实现，也不宣称已经具备全部 Muse 功能。

## 生活记录与视觉模型

见 [生活记录、WorkBuddy 看图和晚间记忆](LIFE-RECORDS.md)。新增 `/life`、`/life/settings`、`/life/entries`、`/life/images`、`/life/consolidate` 和 `/life/memories` 认证接口，使用独立 life SQLite WAL。图像模型已实际接通 `workbuddy/cn:glm-5v-turbo`，凭据只留服务器。
