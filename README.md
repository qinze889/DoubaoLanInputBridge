# DoubaoLanInputBridge

豆包语音输入桥的可迭代版本。

## 当前版本

- 版本：`0.9.6`
- 修复：Access Key 改为原子写入，二维码和服务端按磁盘最新 Key 跨进程同步；即使残留多个 APP 进程，刷新二维码后监听服务也会接受新 Key。
- 调整：旧二维码访问不再显示英文 `Invalid access key`，改为中文二维码失效提示页。
- 新增：扫码弹窗增加“刷新二维码”，会重新生成 Access Key 并同步到运行中的服务，旧二维码和旧链接立即失效。
- 修复：Qt 主界面扫码、健康检查和连接自检恢复运行时局域网地址检测，不再使用固定 `192.168.1.63` 生成手机扫码链接。
- 调整：电脑 APP 的“发布给手机”改为二选一菜单，可选择发布文字或发布文件；发布文字会生成 txt 放入手机文件缓冲区。
- 新增：手机 Web 的图库入口从“只选图片”扩展为“图库媒体”，支持选择图片和视频；历史预览新增视频/媒体类型区分。
- 调整：手机 Web 移除遮罩式初始入场动画，改为轻量页面淡入；“文件与下载”默认始终收起，文件缓冲区不再自动展开。
- 调整：桌面主界面继续减法优化，压缩左侧说明、减少重复扫码入口、降低状态卡拥挤感。
- 调整：手机 Web 首屏以输入和发送为核心，润色工具和文件工具改为自定义折叠面板，减少首屏拥挤。
- 调整：管理页改为紧凑设置面板，默认只展示常用维护和防火墙修复入口，低频诊断工具折叠到“更多工具”。
- 新增：管理页提供“放行防火墙”入口，通过管理员 UAC 创建或更新 Windows 防火墙持久入站规则，解决手机同 Wi-Fi 仍无法访问的问题。
- 新增：扫码连接弹窗增加连接自检信息、手机健康检查地址和复制自检信息按钮，便于排查手机连不上。
- 说明：Wi-Fi 自动连接二维码需要明文 Wi-Fi 密码，当前不自动生成，避免泄露家庭或办公 Wi-Fi 密码。
- 修复：服务启停按钮、状态卡和侧栏状态统一联动；停止服务时先显示“停止中”，真实关闭后再显示“已停止”。
- 调整：停止服务确认框改为中文按钮，避免 Qt 默认 Yes/No 造成割裂。
- 调整：桌面主界面进一步面向普通用户，日志不再默认露出，扫码连接和发布给手机成为右侧核心操作。
- 调整：停止服务降级为小型危险操作，并在停止前二次确认，降低误触风险。
- 调整：最近内容预览卡片压缩标题、弱化时间和信息行，搜索框更醒目，并显示自动刷新状态与上次刷新时间。
- 调整：二维码弹窗隐藏完整访问密钥，只展示局域网 host:port 摘要，保留复制完整链接按钮。
- 调整：管理弹窗改为紧凑设置面板，低频维护项默认收起。
- 调整：发布给手机完成后明确提示手机 Web 底部“文件缓冲区”可刷新下载。
- 修复：自更新后台启动 PowerShell 时显式隐藏窗口，减少更新过程中弹出空白/命令窗口的情况。
- 调整：手机 Web 将发送按钮前置到文件区上方，文件选择和文件缓冲区放在发送按钮下面。
- 调整：最近内容预览卡片按文字、文件、图片、混合类型使用不同颜色和标签，区分更醒目。
- 调整：电脑 APP 主界面只保留常用操作，更新、配置、历史、诊断和连接复制统一移入“管理”弹窗。
- 调整：手机 Web 底部常驻“文件缓冲区”，电脑发布给手机的文件统一显示在这里。
- 新增：电脑 APP 可选择本地文件“发布给手机”，手机扫码页面刷新后可下载。
- 新增：电脑端最近内容预览支持搜索，卡片增加可见的复制、打开和文件夹按钮。
- 修复：托盘区左键/双击唤起主窗口改为全激活事件处理，并增加 Win32 置前兜底。
- 新增：电脑 APP 增加“运行自检”入口，一键复制脱敏自检报告，覆盖版本、服务、更新源、历史目录、托盘和单实例状态。
- 调整：发布临时产物加入 `.gitignore`，避免备份、临时更新 exe 和临时报告误入版本库。
- 修复：托盘区单击/双击和桌面快捷方式重复启动都能唤起已有窗口。
- 修复：桌面 APP 增加单实例运行保护，重复启动时只唤起已有窗口，不再启动第二个服务进程。
- 修复：打包运行时本地更新路由不再从 PyInstaller 临时目录查找更新源，避免“检查更新”访问 `__updates__/update.json` 返回 404。
- 调整：Qt 预览卡片改为单击选中、双击执行；文字双击复制，图片/文件双击打开文件；滚动条改为细圆角现代样式。
- 重构：桌面 APP 打包入口切换为 PySide6/Qt，不再使用 Tkinter 界面作为主 UI。
- 新增：Qt 主界面使用现代预览卡片、原生滚动区域、可点击记录和二维码弹窗。
- 新增：主界面预览层支持鼠标滚轮；预览卡片支持单击复制文字/打开文件，双击文件打开所在文件夹，并增加悬停反馈。
- 修复：主界面最近内容预览改为普通行列表，避免启动时 Treeview values 解析异常导致 APP 崩溃。
- 调整：电脑 APP 主界面中间区域改为最近内容预览层，二维码不再常驻占位，点击“扫码连接手机”后弹窗显示。
- 修复：历史剪贴板的预览列改为真正的图片缩略图列，图片历史可直接在列表里看到小图。
- 新增：历史剪贴板增加“预览”和“信息”列，默认显示最近 10 条，支持垂直/水平滑动查看。
- 修复：二维码和手机访问地址只允许 `192.168.*.*` 网段，禁止 `198.*`、`10.*`、`172.*` 等其它网段抢占。
- 新增：电脑 APP 增加“查看历史”入口，保存最近发送文本和文件剪贴板记录，文件历史可直接打开文件或打开所在文件夹。
- 调整：历史剪贴板仅放在电脑 APP 内，手机网页不展示历史，避免手机端界面变重。
- 说明：历史记录写入本机 `%LOCALAPPDATA%\DoubaoLanInputBridge\clipboard_history.json`，默认保留最近 7 天和最多 100 条，可在电脑端清空。
- 新增：对外分发脚本生成普通用户可读的 `index.html` 使用说明，并自动打包 `DoubaoLanInputBridge-<version>-windows.zip`。
- 新增：对外分发版能力，包括电脑端配置入口、首次启动引导、脱敏诊断信息复制、`release/` 分发目录生成。
- 更新：本地更新源改为局域网 HTTP 地址，默认使用当前电脑局域网 IP 和服务端口，清单下载地址会随请求 Host 动态生成。
- 产物：`dist/DoubaoLanInputBridge_zh2en.exe`
- 调整：最近活动日志默认收起，主界面不再展示本机日志绝对路径；快速操作改为“打开本机数据目录”。
- 调整：电脑 APP 左侧从“导航栏”改为连接步骤说明，减少假导航；二维码标题更短并放大二维码显示。
- 调整：电脑 APP 隐藏二维码下方局域网地址和端口信息卡，避免挤压二维码；服务启动/停止合并为一个切换按钮。
- 新增：启动服务时如果默认端口被占用，会自动尝试后续端口并刷新二维码。
- 调整：电脑 APP 按“扫码工作台”重构 UI/UX，放大二维码入口，强化服务控制、端口、更新、Key 和最近活动的视觉层级。
- 新增功能：网页端增加“中译英”按钮，将文本框中的中文翻译成英文后再发送。
- 新增功能：电脑端增加“检查更新”按钮；配置更新源后，检测到新版本可一键下载、替换并重启。
- 新增功能：网页端增加“润色提示词”按钮；本地电脑维护 `prompt_library.json` 模式库，并调用 MiniMax-M3 进行大模型润色。
- 新增功能：提示词润色默认自动识别类型，结果先显示在下方工作区；需要补充时只在工作区追问，点击“采用结果”后才写回主输入框。
- 新增功能：Web 服务界面重设计，隐藏首屏长链接，增加圆润面板、视觉背景、按钮分组和轻量动效。
- 调整：Web 服务界面不再显示局域网链接、服务在线状态和连接信息，这些信息保留在电脑 APP 中。
- 调整：Web 页刷新时显示短暂标题入场动画，功能区直接从输入内容开始；输入框默认小尺寸，可展开到大尺寸；移除“末尾加换行”和“回车延时”控件，回车延时固定 0.5 秒。
- 新增功能：Web 页支持上传图片、视频、Word、PDF 和小文件，服务保存到本机后把文件路径放入 Windows 剪贴板，文件内容不做解析处理。
- 调整：Web 页文件上传区改为现代拖放组件，支持选择文件、拖放文件、查看已选文件列表和一键清空。
- 调整：输入框恢复为简洁的“展开输入框/收起输入框”；文件区保留手机端单入口自动上传和电脑本机发布给手机下载模式。
- 调整：手机端文件上传拆分为“选图库媒体”和“选文档/文件”，图库入口支持图片和视频；手机下载列表只在电脑本机分享模式显示。
- 调整：手机端选择文件后先进入待发送状态，点击“发送”后再上传并粘贴到电脑；多文件会逐个写入剪贴板并逐个触发粘贴。
- 调整：电脑 APP 移除“访问地址”文本栏，改为本地生成二维码，手机扫码后直接打开局域网输入页。
- 调整：扫码链接主机改为运行时变量，默认自动使用当前电脑局域网 IP，也可通过 `DOUBAO_BRIDGE_HOST` 或 `mobile_host.txt` 覆盖，方便其他电脑复用。
- 调整：电脑 APP 增加醒目的服务状态卡片，启动成功、停止、启动失败和更新检查都有大号状态反馈，避免“服务已启动，端口...”提示太小看不到。
- 修复：二维码改用成熟本地生成库，修正微信无法识别手写二维码的问题。
- 新增：电脑 APP 增加 Windows 系统托盘图标，关闭窗口时隐藏到托盘，托盘菜单支持显示窗口、复制扫码链接、打开本机页面、检查更新和退出。
- 调整：设置定制 APP 图标，用于 exe 文件、窗口标题栏和系统托盘。
- 调整：健康检查增加版本、进程号和 exe 路径，APP 启动/隐藏/退出写入日志；托盘不可用时关闭窗口会最小化而不是直接退出。
- 修复：关闭窗口后程序消失的问题；关闭按钮改为最小化保活，托盘点击事件改由 Tk 主循环安全处理。
- 调整：Web 页背景使用 `assets/paper000.jpg` 纸纹图片，并加入轻微漂移和光影动效。

## 地址含义

- `127.0.0.1`：本机回环地址，只能在运行软件的电脑上访问。
- `192.168.x.x`：局域网地址，手机和电脑在同一个 Wi-Fi 下通常用这个地址。
- `172.x.x.x`：电脑上的另一块网卡地址，常见于虚拟网卡、热点、VPN、WSL/Hyper-V 等。

URL 中的 `key=...` 是访问密钥。拿到密钥且能连到这台电脑网络的人，可以调用发送功能。

## 对外分发说明

可以直接分发 `dist/DoubaoLanInputBridge_zh2en.exe`，也可以生成对外分发目录：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make_release.ps1
```

脚本会输出：

```text
release\DoubaoLanInputBridge-<version>\
```

其中包含 exe、首次使用说明、HTML 使用说明和分发清单，并会在 `release\` 下生成：

```text
DoubaoLanInputBridge-<version>-windows.zip
```

访问密钥、日志、上传文件、词库、更新源等运行数据会写入每台电脑自己的：

```text
%LOCALAPPDATA%\DoubaoLanInputBridge
```

不要把自己电脑上的 `%LOCALAPPDATA%\DoubaoLanInputBridge`、`run_data*`、`local_update_source` 或包含 API Key 的文件一起发给别人。MiniMax API Key 和访问密钥应由每台电脑单独配置或生成。

电脑端“配置”按钮可设置 MiniMax API Key、更新源 URL 和手机访问主机覆盖；“复制诊断信息”按钮会复制脱敏运行信息，不包含访问 Key 或 API Key。

## 手机扫码主机变量

二维码里的主机地址不是固定网段。默认情况下，软件启动时会自动读取当前电脑的局域网 IPv4 地址，并生成类似：

```text
http://当前电脑IP:8765/?key=访问密钥
```

如果自动识别到的地址不适合手机访问，可以手动指定主机变量：

1. 环境变量 `DOUBAO_BRIDGE_HOST`
2. 用户数据目录里的 `mobile_host.txt`

示例：

```powershell
$env:DOUBAO_BRIDGE_HOST = "192.168.31.25"
```

或写入：

```text
%LOCALAPPDATA%\DoubaoLanInputBridge\mobile_host.txt
```

内容可以是纯主机名/IP，也可以是带端口的 URL，程序会自动提取主机部分：

```text
192.168.31.25
bridge-pc.local
http://192.168.31.25:8765/?key=old
```

## 开发验证

```powershell
C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests
C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe -m py_compile src\gui_app.py tests\test_html_translate.py tests\test_update_check.py tests\test_prompt_enrichment.py tests\test_file_clipboard.py scripts\import_prompts_chat.py
```

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

打包脚本会把 PyInstaller 安装到项目内 `tools/pyinstaller`，输出到 `dist/`。如果项目 `dist` 里的旧 app 正在运行，脚本会先关闭它，打包成功后自动重新打开新版 app。

如果只想打包、不想自动重新打开：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1 -NoRestart
```

## 更新检查

电脑端“检查更新”按钮会读取一个 JSON 更新清单。更新源按顺序读取：

1. 环境变量 `DOUBAO_BRIDGE_UPDATE_URL`
2. 用户数据目录里的 `update_url.txt`

更新清单格式：

```json
{
  "version": "0.2.1",
  "url": "https://example.com/DoubaoLanInputBridge_zh2en.exe",
  "sha256": "可选，推荐填写 exe 的 SHA256",
  "notes": "本次更新说明"
}
```

当 `version` 高于当前版本时，软件会弹窗提示。清单包含 `url` 时，可以一键下载并安装：

1. 下载新版 exe 到用户数据目录。
2. 如清单提供 `sha256`，先校验下载包。
3. 启动独立更新脚本。
4. 当前 app 关闭。
5. 更新脚本把旧 exe 移动到 `dist\backup\`，再把新版 exe 移到原位置。
6. 更新完成后重新打开新版 app。

自动更新日志位于：

```text
%LOCALAPPDATA%\DoubaoLanInputBridge\update.log
```

## 局域网更新源

当前阶段使用局域网更新源即可，不需要 VPS。生成并配置：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\publish_local_update.ps1 -ConfigureCurrentUser
```

脚本会生成：

```text
local_update_source\update.json
local_update_source\DoubaoLanInputBridge_zh2en-<version>.exe
```

并把当前用户的更新源写入：

```text
%LOCALAPPDATA%\DoubaoLanInputBridge\update_url.txt
```

写入格式类似：

```text
http://192.168.x.x:8765/__updates__/update.json
```

其中 IP 默认自动取当前电脑的局域网 IPv4，端口默认 `8765`。如果服务启动时端口被占用并自动顺延，电脑 APP 会在服务启动成功后把 `update_url.txt` 自动改成实际端口，例如 `8769`。

`/__updates__/update.json` 由当前 Web 服务读取 `local_update_source\update.json` 后返回；下载包地址会按本次访问的 Host 动态改写成：

```text
http://当前电脑局域网IP:当前服务端口/__updates__/DoubaoLanInputBridge_zh2en-<version>.exe
```

以后放到 VPS 时，再把 `local_update_source` 目录里的文件上传到服务器，并把 `update_url.txt` 改成服务器上的 `update.json` 地址即可。

## 提示词库

网页端“润色提示词”默认自动识别润色方向，也可以手动选择对话、原始、图像、代码、写作类型。它使用本机 JSON 模式库提供各类型规则，然后调用 MiniMax OpenAI 兼容接口生成结果。默认模式库位置：

```text
%LOCALAPPDATA%\DoubaoLanInputBridge\prompt_library.json
```

电脑端有“打开词库目录”按钮。首次打开或首次润色时会自动生成默认库。

润色结果不会立刻覆盖主输入框：

1. 点击“润色提示词”后，候选结果会先显示在下方工作区。
2. 如果模型判断关键信息不足，会在工作区只追问一个问题。
3. 回答后点击“继续润色”，模型生成候选结果。
4. 确认满意后点击“采用结果”，才会把候选结果写回主输入框。

MiniMax API Key 按顺序读取：

1. 环境变量 `MINIMAX_API_KEY`
2. 用户数据目录里的 `minimax_api_key.txt`
3. 环境变量 `OPENAI_API_KEY`

可选配置：

```powershell
$env:OPENAI_BASE_URL = "https://api.minimaxi.com/v1"
$env:OPENAI_API_KEY = "你的 MiniMax Key"
$env:MINIMAX_MODEL = "MiniMax-M3"
```

也可以用更明确的变量名：

```powershell
$env:MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
$env:MINIMAX_API_KEY = "你的 MiniMax Key"
$env:MINIMAX_MODEL = "MiniMax-M3"
```

当前内置润色类型：

- 对话提示词
- 原始提示词
- 图像提示词
- 代码提示词
- 写作提示词

库结构见 [docs/prompt_library_schema.md](docs/prompt_library_schema.md)。

可选导入 GitHub `prompts.chat` 种子库：

```powershell
C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe scripts\import_prompts_chat.py "$env:LOCALAPPDATA\DoubaoLanInputBridge\prompt_library.json"
```

## 风险点

- “中译英”当前使用 `https://api.mymemory.translated.net`，翻译文本会发送到第三方服务。
- 如果网络不可用、接口限流或被防火墙拦截，翻译会失败；原“发送”功能不依赖该翻译接口。
- “润色提示词”会把文本发送到 MiniMax；未配置 API Key、网络不可用、账户限流或余额不足时会失败。
- 程序会将文字写入剪贴板并触发 `Ctrl+V`，使用前需要先让电脑目标输入框获得焦点。

