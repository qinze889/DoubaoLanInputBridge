# 声笺 v2：账号、语音和电脑任务

入口：`https://test.xjiaoai.com/shengjian/api/v2/console`。这是一项测试服务；旧 `/shengjian/` 传输服务独立运行。v2 使用自己的 SQLite WAL 数据库和系统账号，模型配置、豆包账号池与旧传输数据均不复制进此数据库。

## 当前实际完成范围

- Windows 的 Mac 风格 UI 与交互 CI 已合入 PR #6；Mac 分享修复已合入 PR #5。稳定版发布仍等待实际 Windows 安装、升级、托盘及设备互传验收。
- 邀请码注册、Argon2id 密码登录、会话退出、设备登记与撤销、按设备授权、任务与递增事件、一次性审批、积分预留及结算。
- 手机网页登录、文字对话、录音识别、语音回复、停止播报、电脑派任务、进度和取消。当前录音采用“说完一句后识别”；不会声称已有流式 ASR 中间结果或已通过连续 30 分钟验收。
- 服务器实际发现 `workbuddy/cn:deepseek-v4.1-flash` 及 `doubao-voice/asr`、`doubao-voice/tts`。模型回复、TTS 与测试音频的 ASR 均实际返回成功。登录 Cookie 留在现有网关账号池，声笺只持有限定来源和模型的服务凭据。
- 桌面连接器主动连出 WebSocket，持久化领取任务 ID，串行在配置的工作目录中运行。DeepSeek Harness `0.2.1-rc.2` 的 headless JSON 引擎已实际通过 sub-buddy 完成文件写入；完整公网任务派发、事件补读、幂等提交和取消确认已实测。Codex 使用 App Server stdio；已用真实子进程协议夹具测试初始化、单次审批与停止进程，尚未宣称完成真实账号模型验收。
- CPU、内存、工作目录所在磁盘、网络累计字节和 Agent 状态通过设备心跳上报。当前不声称具有进程级服务告警或系统推送。
- iOS Foundation 客户端新增 HTTPS 固定中转链接的解析、POST 登录及 Cookie 转发，连接码不会出现在转发 URL。保留旧 LAN/CF 连接；P2P 使用网页。设备页提供 v2 网页入口。原生 v2 语音界面尚未接入。
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

## 运行与维护

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

当前 schema 为 v1；新功能尚未经过历史生产库迁移。后续改表必须增加明确迁移版本和升级前快照，不可仅修改建表语句。

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
.venv/bin/python -m pytest tests/test_core_v2.py tests/test_core_providers.py tests/test_gateway_voice.py tests/test_official_voice.py tests/test_desktop_agent.py -q
node scripts/smoke_core_ui.cjs
swift run --package-path ios ClientChecks
```

完整 XCTest 和 iOS 模拟器构建需要完整 Xcode；本机只有 Command Line Tools，因此本机执行 Foundation 自检，完整构建交由 Apple CI。Git SSH 连接失败时停止推送链路，不换账号、不生成 SSH 密钥；当前新改动在本地等待远端恢复。

## 来源与边界

- rev：`doubao/gateway-audio` 的音频协议、错误语义、账号池和串行约束；本实现调用其已部署公开音频接口，没有把整套 overlay 覆盖到声笺或复制 Cookie。
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)：MIT，固定 npm `@deepseek-ai/dsh@0.2.1-rc.2`，使用官方 headless JSON 输出及 `approval/request` 扩展点。审批插件为本仓库独立实现。升级版本必须重新验收事件、审批及取消语义。
- [Codex App Server](https://learn.chatgpt.com/docs/app-server)：使用本机 CLI 生成的 JSON schema核对 initialize、thread/start、turn/start、command/file approval。只接受本次操作，不写 acceptForSession 或永久策略。
- NanoMuse：仅参考设备任务、会话寿命与交互思路；没有复制其 GPL 实现，也不宣称已经具备全部 Muse 功能。
