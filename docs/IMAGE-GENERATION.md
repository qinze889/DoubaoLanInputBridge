# 手机生图与 Responses 接入

手机刷新原 `/shengjian/api/v2/console` 即可使用，不需要重装电脑 App 或重新扫码。

在对话页切换到“生成图片”，顶部“模型与连接”可单独选择生图模型。当前通过真实云端验收的两个精确模型是：

| 名称 | 上游 ID | 实测结果 |
| --- | --- | --- |
| Hunyuan Image Alpha / WorkBuddy | `workbuddy/cn:hunyuan-image-alpha` | 1024×1024，可解码 PNG |
| MiniMax Image-01 | `minimax/image-01` | 1024×1024，可解码 PNG |

也可在对话中明确输入或说“帮我生成一张……图片”“帮我画一只……”。识别完成后会提交云端生图任务；不需要电脑 Agent 在线，不会占用电脑前台。可以继续聊天，之后到生图区查看。图片支持保存 PNG、“聊这张图”，后者把生成结果接到现有视觉工具和语音对话。

生成作品自动保存到生活记录，明确标记为 AI 生成、`role=assistant`，不作为用户真实生活事件或身份事实沉淀。Chat/Work 模型、识图模型、生图模型分别保存，不把 DeepSeek 对话模型标成生图权重。当前支持文字生图，参考图编辑和连续修图尚未开放。

## 协议与实际兼容边界

服务端向现有上游 `/responses` 提交一次请求：`model` 为所选精确生图模型，`input` 为文字需求，`tools=[{"type":"image_generation"}]`，强制该工具，非流式获取最终结果。生图任务异步，不因手机页面退出、刷新或断线而重放请求。未迁移现有本机 Harness 文本工具循环。

标准 Responses 图片输出支持 `image_generation_call.result` 的 base64。现场上游还存在旧兼容形式：图片模型先经过 Chat 适配，最终返回 `output_text` 中的生成资源链接，而非标准图片工具项。首轮[原生形状检查](research/IMAGE-RESPONSES-NATIVE-SHAPE-PROBE.json)因此未通过；这不是“未生图”的证据，未自动重新提交原请求。后续独立测试验证了[资源形式的 Responses 结果](research/IMAGE-RESPONSES-ASSET-VALIDATION.json)。

声笺兼容两种形式。资源下载仅接受管理员明确配置的 HTTPS origin 与 `/generated-images/<64位随机十六进制>.(png|jpg|webp)`，不附带模型凭据，不跟随跳转，有字节和图像像素上限。只下载已生成资源，不因缺少图片工具项再次调用生图。上游当前不会向声笺提供逐步图片预览；本版显示排队/生成/完成状态，不伪装部分图片流。

原图经完整解码后以 PNG 保存在独立 core SQLite 的 `image_jobs` BLOB 中，随现有数据库备份；生活记录另存 JPEG 预览。所有模型设置、任务、原图和预览均按账号鉴权，浏览器只获取同站授权资源。当前作品存储上限约 200 MiB/账号，最近 30 项显示在画室。

## 任务与额度

`GET/PATCH /images/settings` 保存账号生图偏好；`POST /images/jobs`、`GET /images/jobs`、`GET /images/jobs/{id}`、`GET /images/jobs/{id}/file` 提供持久任务与私人 PNG。服务端只开放 `SHENGJIAN_IMAGE_MODELS` 中已验证且仍在上游目录的模型。

同一账号一次只接收一个未完成生图，全局并发上限 2；请求 ID 幂等。浏览器提交未获确认时保留同一请求 ID，重试恢复原任务。任务状态为 queued/running/succeeded/failed/unknown。服务重启不重放：未提交的 queued 任务失败并释放预留；已 running 任务结果未知，保留预留供核实。

`SHENGJIAN_IMAGE_CREDITS` 当前设置为成功每张 10 **应用积分**，失败确认未提交时释放，结果不明时保留预留。该值是声笺后台积分配置，不代表上游货币价格；当前上游 Responses 文字兼容层返回的 token 零值也不表示生图免费。模型凭据仅在服务端。

## 验证

- [公网真实任务、两模型 PNG、幂等恢复和手机页面渲染](research/IMAGE-GENERATION-PUBLIC-VALIDATION.json)：两张真实 1024×1024 图，测试任务分别约 12.23 / 18.47 秒，仅为小样本结果。
- 后端测试覆盖标准图片工具项、旧资源输出、账号隔离、SQLite 重开、幂等、拒绝、超时/未知、非图片文本、不可信资源 origin，以及生成成功后资源连接失败不错误释放预留。
- `scripts/smoke_image_generation.cjs` 覆盖模型保存、刷新恢复、PNG 下载、“聊这张图”、明确的对话生图请求、明暗手机布局和账号切换；已加入 CI。
- 原语音流、视觉会话、Work 进度/取消和手机四分区回归继续通过。自动测试使用虚拟麦克风，不替代真机免提听测。

官方协议依据：[Responses image generation tool](https://developers.openai.com/api/docs/guides/tools-image-generation)。Responses 统一调用格式，具体模型仍需实际支持图片输出，不能由文字/识图目录推定。
