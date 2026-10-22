# 47 服务器中转与手机发送

[文档导航](README.md) · [CI 说明](CI.md)

## 入口与边界

当前后台部署在 **47.96.180.28（32 核、64GB）**，使用独立 `shengjian-relay` 用户、systemd 服务和数据目录。2026-10-22 从 47.114.61.223 迁出，保留原设备身份；旧生产机器已停用声笺服务，旧入口返回迁移提示。

1.4.0 提供四方式统一入口，既有 1.3.0 固定公网连接器可继续使用新域名。自行部署时，将 systemd 中的 `SHENGJIAN_ORIGIN` 与 Nginx server_name 设置为自己的有效 HTTPS 域名。

固定入口：`https://test.xjiaoai.com/shengjian/`。这里是独立的设备管理后台，手机扫描每台电脑自己的二维码。

电脑通过 HTTPS 长轮询主动连接服务器，不要求电脑有公网 IP、端口映射或 Cloudflare 临时域名。手机请求由服务器临时转给电脑，实际粘贴由电脑执行后返回结果。设备离线会提示离线，超过等待时间会提示结果未知，连接恢复不会自动重放键盘输入。电脑后台需要一直运行。

手机页面支持文字、图片、文件上传和电脑分享的下载。单文件建议小于 15 MiB，服务端请求/响应硬上限 16 MiB；更大文件仍使用已有的机器共享。手机发送前需要先在电脑上选中目标输入框。Mac 原生版由声笺主程序检查授权并执行键盘操作，Python 服务通过随机口令和 0600 私有 Unix socket 请求粘贴/回车，不需要独立服务的权限。Mac 仍须为声笺开启系统的设备控制和数据访问（辅助功能），服务器无法代替系统授权。本地临时签名更新后旧条目可能失效，需移除旧条目再添加当前应用。

公网只开放手机所需路由；`/desktop/*`、任意目标 URL 和机器文件系统路径不可通过中转调用。机器共享有独立的单次邀请及每对设备 HMAC 验证；仅允许配对、状态和分块文件路由。P2P 使用经过身份验证的 SDP 握手，文件数据走 WebRTC DTLS/SCTP 通道。P2P 模式在服务器拒绝文件中转，不自动回退。

## 后台管理

后台首次启动会在私有数据目录生成管理口令。管理员登录后可以添加设备、下载一次性展示的 `relay.json`、查看在线状态、复制手机链接/显示二维码、停用设备。手机连接使用每台设备独立的口令，不能管理其他电脑。停用会同时撤销手机和电脑连接。

把设备配置保存到电脑原有声笺数据目录，然后重启应用：

- Mac：`~/Library/Application Support/DoubaoLanInputBridge/relay.json`
- Windows：`%LOCALAPPDATA%\DoubaoLanInputBridge\relay.json`

配置包含敏感连接凭据，只保存在设备本地，不要提交到仓库或发送到聊天。1.4.0 起可在“连接方式”导入配置，并在固定公网、CF 隧道、P2P、局域网中明确选择一种。公网和 P2P 共用同一份设备配置。

## 独立部署

服务器运行 Python 3.12，安装 `server/requirements.txt`。入口：

```sh
python server/relay.py --data /var/lib/shengjian-relay --port 18766
```

后端仅监听 `127.0.0.1:18766`。`server/shengjian-relay.service` 为独立低权限 systemd 服务，代码放 `/opt/shengjian-relay/current`，私有状态放 `/var/lib/shengjian-relay`。`server/nginx-location.conf` 仅添加到 `test.xjiaoai.com` 的现有 HTTPS server 中，检查 `nginx -t` 后平滑 reload。

凭据文件权限为 0600、目录为 0700。手机文本和文件仅留在有上限的内存请求中，请求完成/超时后释放，不写入服务器数据库；桌面原有历史归档保持不变。服务重启会清除会话和未完成请求，不能将未知结果视作发送成功。备份仅需私有凭据文件，恢复后需重新登录后台。

默认最多 32 台设备、16 个并发请求、64 MiB 请求队列，配合 systemd 内存限制。代理层必须使用有效 HTTPS、关闭这段入口的访问日志，保留 `no-store` 和 `no-referrer`。下载强制作为附件，避免共享 HTML 在后台同源执行。

## 验证与参考

`tests/test_rtc_bridge.py`、`tests/test_p2p_relay.py` 通过真实 ICE/DTLS/SCTP 通道验证大文件、中文、机器权限隔离，以及服务器仅参与握手。`tests/test_relay.py` 通过真实 HTTP 服务验证中文发送、超过 1 MiB 的文件及 SHA256、身份隔离、立即撤销、私有 API 阻断、离线/超时反馈和连接器重复请求不重复执行。Windows CI 继续构建真实 NSIS 安装包，验证全新安装/旧进程升级和双向多分块文件传输。CI 无法验证用户手机的蜂窝网络及 Mac 的系统授权，必须另做现场验证。

参考 nanoMuse v1.0.5 的自托管 relay、设备主动连接和明确回执思路，独立实现本项目的 HTTP 合同，没有复制其业务源码：

- https://github.com/nano-muse/nanoMuse/blob/v1.0.5/docs/self-hosting.md
- https://github.com/nano-muse/nanoMuse/blob/v1.0.5/docs/hub.md

## 2026-10-22 Mac 实机修复验证

原生界面更新前，服务报告无辅助功能权限，公网 `/send` 返回 500。改为由原生主程序执行键盘操作后，重新添加当前应用的系统授权，`accessibility=true`。本地完整回归为 **263 passed**，Swift 原生界面编译及安装包签名完整性校验通过。

通过真实公网 HTTPS 入口 → 47 中转 → 已安装的 `/Applications/声笺.app` → 独立 AppKit 输入框，含中文和 emoji 的测试文字与输入框实际内容逐字符一致。测试目标具有标准 Edit/Paste 菜单，避免把没有粘贴快捷键的测试控件误判为产品失败。验证结束关闭测试输入框，并恢复测试前剪贴板。没有替代用户手机相机、具体浏览器或蜂窝网络的现场检查；手机需使用当前应用二维码重新连接。

## 1.4.0 四通道验证（2026-10-22）

使用隔离数据目录中的真实 Mac 打包服务，先后选择四种方式：局域网实际内网 IP 的手机页面返回 200；固定公网通过 test.xjiaoai.com 认证并调用文件 API；P2P 通过该域名完成 SDP 握手后，超过 1 MiB 的文件上传/下载 SHA256 相同，服务器计数仅增加一次握手；CF Quick Tunnel 的真实 HTTPS `/health` 通过，`/desktop/state` 返回 403。切回局域网后 CF 进程停止。临时设备验证后撤销并清理，没有使用用户文件。

独立浏览器也通过实际 WebRTC 数据通道验证中文、FormData 上传和二进制下载逐字节一致。地址发现超过等待期时，只要已取得可用候选地址便继续握手；没有候选地址或打洞失败则明确提示切换方式。两台冻结 Mac 服务通过 P2P 双向多分块 SHA256 校验。以上属于同机/服务器链路实测，不等同于用户手机蜂窝网络与 Windows 的跨 NAT 现场实测。
