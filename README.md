# 小爱语音遥控电脑（open-xiaoai 网关 · 最小版）

对小爱音箱说「**小爱同学，打开QQ**」→ 电脑启动 QQ，音箱播报「好的，QQ已打开」；
说「**小爱同学，关闭QQ**」→ 结束 QQ 进程。其余语音照常走原生小爱，互不干扰。

## 使用

1. 双击 `start.bat`（保持窗口开着；关窗口 = 停止服务）
2. 对音箱说命令即可

## 新机器部署（克隆后必读）

### 1. 环境要求

- Windows + Python 3.10+（3.13 实测通过），安装依赖：`pip install websockets`
- 一台已刷 [open-xiaoai](https://github.com/idootop/open-xiaoai/blob/main/docs/flash.md) 固件的小爱音箱，和电脑在**同一局域网**
- 防火墙放行 4399 端口（管理员运行）：

```bat
netsh advfirewall firewall add rule name="open-xiaoai-gateway" dir=in action=allow protocol=TCP localport=4399
```

- 端口默认 4399，可用环境变量 `GATEWAY_PORT` 修改

### 2. 必改配置（仓库里全是作者机器的信息）

| 文件 | 改什么 |
|---|---|
| `apps.json` 的 `_音箱` | `user` / `password`：你自己音箱的 SSH 账号密码（网关靠它登录音箱校正指向、重启 client） |
| `xiaoai_askpass.bat` | 和上面同步成同一份音箱密码（文件内容就是一行 `@echo 你的密码`） |
| `apps.json` 各应用的 `path` / `cmd` | 全是作者机器的安装路径；跑 `scan_apps.ps1` 扫自己的电脑照着改。不改的后果：对应「打开XX」失效，其余功能照常 |
| `apps.json` 的 `我的服务器` 条目 | 作者的云服务器（含 IP）；换成自己的，或整条删掉 |

### 3. 试运行

双击 `start.bat`（或 `python app.py`）。首次启动会自动在局域网里扫描发现音箱、把它的指向改成本机 IP；`gateway.log` 出现「✅ 音箱已连接」即部署成功，可以直接对音箱说话测试。

### 4. 开机自启（可选）

计划任务 `XiaoAI-Gateway` 是作者本机的配置，**不随仓库分发**。需要的话管理员运行下面命令自建（两个 `<...>` 换成实际路径）：

```bat
schtasks /Create /TN "XiaoAI-Gateway" /SC ONLOGON /RL HIGHEST /F /TR "\"<pythonw.exe 完整路径>\" \"<项目目录>\app.py\""
```

`pythonw.exe` 在 Python 安装目录下（无窗口运行）；`/RL HIGHEST` = 以最高权限启动（这样才能结束更高权限的进程）。

### 5. ⚠️ 安全提醒

`apps.json` 和 `xiaoai_askpass.bat` 里是**明文密码**。改完配置后不要 push 到任何公开仓库 / fork；仓库历史里遗留的作者密码请视为已泄露，不要复用，自己的音箱密码建议另换一套。

## 怎么加新应用 / 名字匹配规则

编辑 `apps.json`，每个应用三个可选匹配字段（全部生效，命中任一即可）：

```json
"网易云音乐": {
  "path": "D:\\...\\cloudmusic.exe",
  "process": "cloudmusic.exe",
  "aliases": ["网易云", "云音乐"],
  "patterns": ["网易(云)?音乐", "云音乐"]
}
```

- `aliases`：别名（精确匹配）
- `patterns`：**正则表达式**，对识别出的应用名做完整匹配；匹配时会去掉所有空格并忽略大小写，所以「v s code」「py charm」这类 ASR 分词变体也能命中
- 改完**不用重启**，下一条命令立即生效（只有改 `app.py` 才需要重启）

匹配不到的应用会说「这个XX我还不会打开」。扫一遍电脑上装了什么可以跑 `scan_apps.ps1`。

## 网站与搜索

- **打开我的服务器**：「打开我的服务器 / 打开服务器 / 打开腾讯云」→ Windows Terminal 直连 `ssh root@124.221.64.168`（SSH 公钥已装到服务器，免密登录）；也可以卖萌说「**喵喵打开**我的服务器」——「喵喵」是全指令通用的前缀词，喵喵打开QQ、喵喵搜原神 都行
- **打开网站**：「打开哔哩哔哩 / B站 / GitHub / 知乎 / 微博 / 百度 / 淘宝 / 京东 / YouTube（油管）/ Google」，也支持「浏览器打开哔哩哔哩」语序
- **语音搜索**：「浏览器搜原神」「搜原神」「搜一下原神」「百度一下XX」→ 默认浏览器打开百度搜索结果。想换搜索引擎改 `apps.json` 里的 `_搜索` 配置：

```json
"_搜索": { "name": "必应", "url": "https://www.bing.com/search?q={}" }
```

网站同样在 `apps.json` 里加 `url` 字段即可扩充（网址条目不支持语音关闭，会对你说「网页可关不了」）。

## 当前已收录的应用（25 个）

QQ、谷歌浏览器、Edge、记事本、计算器、Word、Excel、PPT、Steam、VS Code、PyCharm、IDEA、WebStorm、CLion、MATLAB、Navicat、Typora、Notepad++、有道云笔记、Xmind、uTools、Clash Verge、FinalShell、Git Bash、原神（米哈游启动器）。

口语示例：「小爱同学，打开扣扣 / 谷歌浏览器 / 记事本 / 计算器 / word / p p t / 梯子 / 原神」「关闭网易云……」——动词支持：打开/启动/运行 · 关闭/退出/结束/关掉，前后可带「帮我/请/吧/呀」等词。

## 文件说明

| 文件 | 作用 |
|---|---|
| `app.py` | 网关全部逻辑（监听 4399 → 匹配指令 → 执行 → 音箱 TTS 确认） |
| `apps.json` | 应用命令表 + `_音箱`/`_搜索` 配置（可自行扩展；含音箱密码，部署时必改） |
| `xiaoai_askpass.bat` | 音箱 SSH 密码应答脚本（与 `_音箱.password` 保持一致；含明文密码） |
| `scan_apps.ps1` | 扫描本机已安装的应用，辅助填写 `apps.json` 的路径 |
| `selftest.py` | 本机自测：`python selftest.py 打开QQ`，不需要音箱 |
| `speaker.json` | 音箱发现结果记录（运行时自动生成/更新，无需手改） |
| `gateway.log` | 运行日志（排查问题时看这个） |
| `client_ssh.log` | 音箱 client 的运行日志（由网关的常驻 SSH 会话保存） |
| `start.bat` | 启动脚本（调试用，会自动请求管理员权限） |

## 音箱侧改动（仅 2 条，可一键还原）

1. `/data/open-xiaoai/server.txt` 内容改为 `ws://<电脑IP>:4399`
2. 重启一次音箱

还原方法：把上面文件写回 `ws://124.221.64.168:4399` 再重启音箱即可。

## 故障排查

- **音箱没反应**：先看 `gateway.log` 有没有「音箱已连接」。没有 → 检查 ① start.bat 是否在跑 ② 电脑防火墙是否放行 4399 ③ 音箱 `server.txt` 是否指向本机 IP（IP 变了要更新，建议在路由器给电脑做 DHCP 保留）
- **识别到了但没执行**：看日志里 🎤 那行识别出了什么字，对照 `apps.json` 的名称和别名
- **只有 native 小爱在答**：说明指令没匹配上，同样看 🎤 日志
- **想不通就跑自测**：`python selftest.py 打开QQ` 能验证电脑侧整条链路

## IP 变化自愈（无需手动配置）

网关每次启动会自动完成"音箱发现 + 指向校正"：

1. 读取 `speaker.json` 里记录的音箱 IP，SSH 验证可达性（账号密码来自 `apps.json` 的 `_音箱` 配置）
2. 记录的 IP 失效时，**自动扫描本机所在网段**：找开 22 端口、dropbear 特征的设备挨个验证，能读到 `/data/open-xiaoai/server.txt` 的就是小爱音箱
3. 对比音箱的指向与本机当前 IP，过期就改写其 `server.txt` 并通过常驻 SSH 会话重启它的 client
4. 发现结果记录到 `speaker.json`，`client_ssh.log` 保存音箱 client 的运行日志

客户端由网关持有的 SSH 会话托管（音箱上没有 nohup/setsid 可用）：网关活着 client 就活着，网关退出后下次启动自动重新拉起。

## 常驻运行（计划任务，仅作者本机已配置）

> 新克隆的机器没有这个计划任务，按上文「新机器部署 · 4」自建。

作者机器上网关通过计划任务 `XiaoAI-Gateway` 常驻：**登录 Windows 自动以管理员权限无窗口启动**（pythonw），内存常驻约 **27 MB**。日志只写文件（`gateway.log` / `client_ssh.log`），没有黑窗口。

- 关闭常驻：`schtasks /Delete /TN "XiaoAI-Gateway" /F`
- 手动重启网关：`schtasks /End /TN "XiaoAI-Gateway" /F` 后再 `schtasks /Run /TN "XiaoAI-Gateway"`
- 调试用 `start.bat` 前先停掉计划任务实例，否则端口冲突第二个起不来

## 已知限制

- 网关接管「打开/关闭XX」时会掐断原生小爱的抢答（重启其语音服务，官方同款中断方式），所以她的抢答只会漏出半句甚至听不到；非遥控指令完全不影响原生小爱
- 电脑关机 / start.bat 没开时命令无效，音箱原生功能不受任何影响
