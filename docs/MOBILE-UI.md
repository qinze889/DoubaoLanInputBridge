# 手机界面与模型选择

手机仍通过 `/shengjian/api/v2/console` 进入，原浏览器登录态继续使用，无需因界面更新重新扫码。

底部四个入口分别为对话、工作、生活、设备。对话页保留实时语音、文字、拍照/上传和摄像头入口；工作页集中显示执行、待处理和完成状态；生活页保留照片时间线、晚间整理和个人记忆；设备页管理连接、能力授权和撤销。

对话页顶部展开“模型与连接”即可分别选择对话/工作模型和识图模型。Chat/Work 选择保存在独立 core SQLite 的 `assistant_preferences` 表中，以账号隔离。识图选择继续使用生活服务的现有设置，因此拍照聊、镜头问答和晚间整理使用同一选择。

当前云端开放三个已通过真实流式工具调用的模型：DeepSeek V4.1 Flash、V4 Flash、V4 Pro。识图保留原先验证过的 24 个选项。模型名称来自服务端允许列表，不把上游凭据发送给浏览器。

新增 `GET/PATCH /assistant/preferences`。服务端 `SHENGJIAN_CHAT_MODELS` 是 JSON 字符串数组，仅加入已验证的模型；默认模型仍由 `SHENGJIAN_TEXT_MODEL` 指定。创建统一 Harness 对话任务时冻结 `chat_model`，电脑设备的模型代理按当前正在运行的自有任务路由，切换偏好只影响后续新建任务。已经排队或执行中的任务不变；Codex 执行引擎仍使用其自己的模型配置。当前界面不提供任意模型 ID 输入。

验证包括：账号隔离、SQLite 重开保留、任务幂等与模型快照、另一个设备不继承运行中任务的模型、320/390/1100 宽度和明暗主题四个分区、刷新后选择保留，以及原语音流、看图、后台进度查询/取消、生活记录的浏览器回归。界面改版不要求重装电脑 App。

- [上游流式工具调用验证](research/CHAT-MODEL-VALIDATION.json)
- [真实本机 Harness 模型切换与文件执行验证](research/MOBILE-MODEL-SELECTION-VALIDATION.json)

截图保存在本地 `artifacts/core-ui/mobile-*.png`，CI 运行 `scripts/smoke_mobile_ui.cjs` 并上传到 core UI 附件中。浏览器使用虚拟麦克风/摄像头，手机扬声器与麦克风体验仍以真机为准。

手机已增加[生图画室与独立生图模型选择](IMAGE-GENERATION.md)，通过 Responses 使用图片模型，Chat/Work 与识图偏好分别保留。
