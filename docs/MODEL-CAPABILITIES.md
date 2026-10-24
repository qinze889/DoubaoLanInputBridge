# 模型按任务与协议选择

参考 [Magpie catalog.Model](https://github.com/yetone/magpie/blob/main/internal/catalog/catalog.go) 对 provider、APIs、图片输入和输入/输出模态分别建模的做法。其 [public catalog](https://github.com/yetone/magpie/blob/main/internal/catalog/public.go) 也明确区分生图模型目录与普通模型目录。本次只参考结构，声笺实现自己的小型能力清单，没有移植 Magpie 网关或修改它的源码。

四个入口独立选择、按账号保存：

| 入口 | 输入 → 输出 | 已验证上游协议 | 当前来源 |
| --- | --- | --- | --- |
| 聊天与工作 | 文字 → 文字／工具执行 | Chat Completions，经本机 DeepSeek Harness | 三个已验证 DeepSeek 型号 |
| 识图 | 文字＋图片 → 文字 | Chat Completions 图片输入 | 24 个真实识图验收模型 |
| 生图 | 文字 → 图片 | Responses | Hunyuan Image Alpha、MiniMax Image-01 |
| 改图 | 文字＋参考图 → 图片 | Images Edits multipart | Hunyuan Image Alpha Edit |

`GET /shengjian/api/v2/models/capabilities` 需要登录，返回每个精确模型的来源、任务、输入／输出模态、协议和验证依据。依据是管理员已验证的任务白名单与当前凭据下实际发现的模型交集；不根据名称中含有 image 或 vision 就自动放开能力。相同模型可以有多个经独立验证的任务项。

生图与改图分别由 `SHENGJIAN_IMAGE_MODELS` 和 `SHENGJIAN_IMAGE_EDIT_MODELS` 配置；更换模型只影响下一次提交，已排队任务冻结原模型。Responses 并不保证当前上游所有模型都能接受图片输入；参考编辑使用已经真实通过的 `/images/edits`，不会在协议失败后偷偷退回文字生图。

上游地址、登录态和模型凭据仅保留在服务端，不会出现在能力清单。Magpie 参考快照查看时间为 2026-10-24；这里只保留公开源码链接，实际行为以声笺真实接口验收为准。
