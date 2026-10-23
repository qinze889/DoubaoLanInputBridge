# rev 网关的声笺流式音频扩展

`audio_stream.py` 是新增路由模块，安装到现有网关的 `server/routers/audio_stream.py`，并在 `server/main.py` 的静态兜底路由之前注册：

```python
from .routers import audio_stream
app.include_router(audio_stream.router)
```

不替换既有 `audio.py`、`doubao_audio.py`、`doubao_asr_protocol.py`。复用其鉴权、模型授权、账号池、稳定设备身份和同一个进程内 `serial()` 锁，因此不能另开一个独立服务进程长期与旧网关并行承载音频。来源是本机 rev 的 `doubao/gateway-audio`，运行基线为服务器 `20261020-bc87fd59627d`；本文件不包含登录 Cookie 或用户凭据。

- `WS /v1/audio/transcriptions/stream`：Bearer 服务凭据；16 kHz mono s16le 音频帧，最大 6400 字节／帧、30 秒／句；`finish` 控制句尾。直接转发中间结果；只在上游确认 SessionFinished 后发送最终文本和完成事件。保留原设备 ID，不换身份或重发。
- `POST /v1/audio/speech/stream`：同旧 speech JSON 字段；输出 NDJSON，依次 `audio.ready`、`audio.chunk`、`audio.finished`。音频为 base64 编码 24 kHz mono s16le PCM。服务端以 FFmpeg 管道增量解码 AAC，未完成或异常返回 `error` 事件。
- 两个入口均校验实际客户端与可信转发地址，只接受 loopback；服务凭据还需通过原有来源、模型、IP、期限与限流校验。
- 客户端关闭请求时，屏蔽外层取消作用域，先关闭上游连接、停止 FFmpeg，再释放来源锁，防止新一句与未清理的旧请求交叠。没有自动重试。

依赖现有网关 Python 环境中的 aiohttp、anyio、FastAPI 以及 FFmpeg。开发验证使用服务器已安装的 aiohttp 3.14.5。

上线时复制已知网关 release 到新目录，仅新增本模块和 import；先以禁用后台调度的临时 loopback 实例验收。正式切换前备份数据库与 systemd 配置，读取运行队列，等现有请求完成，再使用正常 service 入口启动新 release。旧接口行为不变。systemd 的多份 drop-in 按名字排序，应检查最终 WorkingDirectory 及 `/proc/<MainPID>/cwd`，不能只用模型目录 HTTP 200 判断新版本已生效。切换可临时使用不强杀的优雅退出，完成后恢复原停止超时。检查失败恢复原 WorkingDirectory 并重启；不回滚用户模型调用或覆盖现有账号库。

声笺侧启用 `SHENGJIAN_AUDIO_STREAM=1`；仅在两个实际端点验收成功后开启。关闭此配置会恢复原有整句识别模式，旧 `/voice/asr`、`/voice/speech` 始终保留。

AAC 探测窗口由 2048 缩至 32 字节，并显式刷新输出包。在 24/44.1/48 kHz、单／双声道合成样例中，完整解码输出逐样本一致，首批输出由约 304–363 ms 降至 39–40 ms。脚本为 `scripts/check_stream_decoder.py`，参数依据 [FFmpeg 格式文档](https://www.ffmpeg.org/ffmpeg-all.html)。没有启用本次测试中解码失败的 direct 选项。真实首音还包含上游推理、握手和网络时间，解码降幅不等于端到端保证。
