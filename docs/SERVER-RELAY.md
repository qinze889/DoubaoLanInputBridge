# 47 服务器中转与手机发送

## 入口与边界

固定入口：`https://server.xjiaoai.com/shengjian/`。这里是独立的设备管理后台，手机扫描每台电脑自己的二维码。

电脑通过 HTTPS 长轮询主动连接服务器，不要求电脑有公网 IP、端口映射或 Cloudflare 临时域名。手机请求由服务器临时转给电脑，实际粘贴由电脑执行后返回结果。设备离线会提示离线，超过等待时间会提示结果未知，连接恢复不会自动重放键盘输入。电脑后台需要一直运行。

手机页面支持文字、图片、文件上传和电脑分享的下载。单文件建议小于 15 MiB，服务端请求/响应硬上限 16 MiB；更大文件仍使用已有的机器共享。手机发送前需要先在电脑上选中目标输入框。Mac 必须向实际运行的声笺/服务程序授予辅助功能权限；服务器无法代替系统授权。

公网只开放手机所需路由；`/desktop/*`、任意目标 URL 和机器文件系统路径不可通过中转调用。原有 Mac/Windows 机器共享仍兼容，并保留其独立配对和 Cloudflare 通道。

## 后台管理

后台首次启动会在私有数据目录生成管理口令。管理员登录后可以添加设备、下载一次性展示的 `relay.json`、查看在线状态、复制手机链接/显示二维码、停用设备。手机连接使用每台设备独立的口令，不能管理其他电脑。停用会同时撤销手机和电脑连接。

把设备配置保存到电脑原有声笺数据目录，然后重启应用：

- Mac：`~/Library/Application Support/DoubaoLanInputBridge/relay.json`
- Windows：`%LOCALAPPDATA%\DoubaoLanInputBridge\relay.json`

配置包含敏感连接凭据，只保存在设备本地，不要提交到仓库或发送到聊天。新版桌面二维码会自动优先使用固定中转入口。Mac 的公网开关可以启停连接。

## 独立部署

服务器运行 Python 3.12，安装 `server/requirements.txt`。入口：

```sh
python server/relay.py --data /var/lib/shengjian-relay --port 18766
```

后端仅监听 `127.0.0.1:18766`。`server/shengjian-relay.service` 为独立低权限 systemd 服务，代码放 `/opt/shengjian-relay/current`，私有状态放 `/var/lib/shengjian-relay`。`server/nginx-location.conf` 仅添加到 `server.xjiaoai.com` 的现有 HTTPS server 中，检查 `nginx -t` 后平滑 reload。

凭据文件权限为 0600、目录为 0700。手机文本和文件仅留在有上限的内存请求中，请求完成/超时后释放，不写入服务器数据库；桌面原有历史归档保持不变。服务重启会清除会话和未完成请求，不能将未知结果视作发送成功。备份仅需私有凭据文件，恢复后需重新登录后台。

默认最多 32 台设备、16 个并发请求、64 MiB 请求队列，配合 systemd 内存限制。代理层必须使用有效 HTTPS、关闭这段入口的访问日志，保留 `no-store` 和 `no-referrer`。下载强制作为附件，避免共享 HTML 在后台同源执行。

## 验证与参考

`tests/test_relay.py` 通过真实 HTTP 服务验证中文发送、超过 1 MiB 的文件及 SHA256、身份隔离、立即撤销、私有 API 阻断、离线/超时反馈和连接器重复请求不重复执行。Windows CI 继续构建真实 NSIS 安装包，验证全新安装/旧进程升级和双向多分块文件传输。CI 无法验证用户手机的蜂窝网络及 Mac 的系统授权，必须另做现场验证。

参考 nanoMuse v1.0.5 的自托管 relay、设备主动连接和明确回执思路，独立实现本项目的 HTTP 合同，没有复制其业务源码：

- https://github.com/nano-muse/nanoMuse/blob/v1.0.5/docs/self-hosting.md
- https://github.com/nano-muse/nanoMuse/blob/v1.0.5/docs/hub.md
