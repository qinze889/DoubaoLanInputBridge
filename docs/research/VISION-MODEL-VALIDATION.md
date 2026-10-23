# WorkBuddy 识图模型实测与可选列表

2026-10-23，Asia/Shanghai。经声笺已有 WorkBuddy 网关和同一服务凭据测试 49 个目录声明支持图片的候选；24 个通过两张图片检查，25 个本轮未通过。只开放前者，默认仍为 GLM-5V Turbo。

## 方法与边界

两张 640×320 的合成 PNG：第一张左侧红色圆形、右侧蓝色方形及随机串 R827461；第二张左侧一个绿色三角形、右侧三个橙色圆形及随机串 K593208。问题没有提供答案；校验颜色、形状、文字，并人工复核左右位置和数量。每个候选只在第一张通过后测试第二张。并发上限 2，每次请求超时 38 秒，非流式最大输出 250 tokens；目录声明支持 low 档时使用 low。

这证明该网关中的相应模型 ID 在本次账号/路由下可完成这些看图任务，不证明基座原生视觉，也不证明复杂真实照片、密集文字或跨账号的稳定表现。fast/balanced/deep 为路由档位，实际底层模型可能变化。下表为单次小图完整响应耗时，不是首音时间，也不是生产照片整理耗时承诺。

HTTP 503 可能来自上游不可用、限制或共享来源冷却，不能据此认定模型不具备视觉能力；400、超时同样先归为本轮未验证通过。超时结果未知，没有自动重放。未改动账号池限制或清除网关模型限制。

## 两轮通过：已开放选择

| 模型 ID（前缀均为 workbuddy/cn:） | 图一秒数 | 图二秒数 |
| --- | ---: | ---: |
| `fast-model` | 2.96 | 3.77 |
| `balanced-model` | 5.5 | 3.44 |
| `deep-model` | 13.61 | 4.97 |
| `hy3` | 2.6 | 2.73 |
| `hy3-b` | 3.09 | 3.01 |
| `hy3-c` | 3.24 | 2.54 |
| `hy3-x` | 2.39 | 3.42 |
| `hy4-preview` | 3.72 | 3.67 |
| `hy4-preview-ctrl` | 4.46 | 3.12 |
| `hy4-preview-exp` | 4.43 | 3.91 |
| `glm-5v-turbo` | 2.19 | 2.53 |
| `glm-5.3` | 3.51 | 3.08 |
| `glm-5.3-flash` | 2.96 | 3.1 |
| `glm-5.3-flashx` | 3.52 | 2.82 |
| `glm-5.2` | 3.27 | 2.57 |
| `kimi-k2.8-preview` | 5.96 | 4.44 |
| `kimi-k3-2` | 5.22 | 6.39 |
| `kimi-k2.6` | 3.11 | 2.3 |
| `kimi-k2.7` | 4.82 | 5.01 |
| `kimi-k2.5` | 2.19 | 2.47 |
| `minimax-m3-pay` | 2.39 | 2.5 |
| `deepseek-v4.1-flash` | 2.01 | 2.04 |
| `deepseek-v4-flash` | 2.94 | 3.23 |
| `deepseek-v4-pro` | 3.34 | 3.07 |

## 本轮未通过：暂不开放

| 模型 | 观察 |
| --- | --- |
| `auto` | 请求超时，结果未知 |
| `hy4-preview-x` | http_503 |
| `minimax-m2.5` | http_503 |
| `glm-5.0-turbo` | http_503 |
| `glm-4.6v` | http_503 |
| `kimi-k2-thinking` | http_503 |
| `minimax-m2.7` | 返回文字明确表示无法查看图片 |
| `glm-4.6` | http_503 |
| `deepseek-v3-2-volc` | 返回文字明确表示无法查看图片 |
| `deepseek-v3-1-volc` | http_503 |
| `deepseek-v3-1-lkeap` | http_503 |
| `deepseek-v3-1` | http_503 |
| `deepseek-v3-0324-lkeap` | http_503 |
| `kimi-k2-instruct-taiji` | http_503 |
| `default-1.1` | http_503 |
| `default-1.2` | http_503 |
| `hunyuan-2.0-instruct` | http_503 |
| `hunyuan-chat` | http_503 |
| `step-5-preview` | http_503 |
| `space-bunny` | http_503 |
| `deepseek-r1-0528-lkeap` | http_503 |
| `mimo-v2.6-pro` | http_400 |
| `kimi-k3-1` | http_503 |
| `minimax-m3` | http_503 |
| `minimax-m3.1-flash` | http_400 |

## 接入行为

生活记录页顶部提供识图模型选择器，立即保存到当前账号，其他账号保持各自设置。只有服务器配置的已验证列表可选，任意模型 ID 会被拒绝。更换模型后主动整理会产生新的整理版本和额度使用；仅切换设置不会重新处理已有日记。晚间整理仍按原始记录版本去重。

任务创建时固定模型，进行中的任务不会被设置修改切换。图片描述按图片及模型分别缓存，切换模型不会冒用原模型结果；任务和照片描述标明实际模型。原始图片、记忆来源、账号隔离与删除撤回行为保持。

服务端配置 SHENGJIAN_LIFE_VISION_MODELS 为经过验证的模型 ID JSON 数组；默认 SHENGJIAN_VISION_MODEL 仍保留。列表不扩展普通文字模型选择器，避免改变本机 Harness 默认模型。
