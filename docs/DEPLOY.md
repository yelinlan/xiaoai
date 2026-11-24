# 部署教程 & 参考手册

> 项目简介、语音指令示例见 [README](../README.md)。本文是完整的部署教程（从零约半小时）和日常参考手册，按顺序做即可。

## 工作原理

```
小爱音箱（刷 open-xiaoai 固件，运行 client 转发程序）
   │  局域网 WebSocket：音箱 ──→ 电脑 4399 端口
   ▼
你的电脑（app.py 网关：监听 4399 → 匹配指令 → 执行 → 让音箱播报确认语）
```

- 音箱把语音识别结果转发给网关；网关只接管「打开/关闭/搜索」类指令，其余全部留给原生小爱
- 网关启动后会自动发现音箱、把音箱的转发目标改成自己、并托管 client 的启动/重启（详见「IP 变化自愈」）

## 你需要准备

| 项目 | 要求 |
|---|---|
| 小爱音箱 | **只支持两款机型**：小爱音箱 Pro（LX06）、Xiaomi 智能音箱 Pro（OH2P），需刷 open-xiaoai 固件（第 1 步） |
| 电脑 | Windows 10/11 + Python 3.10 以上（3.13 实测通过） |
| 网络 | 音箱和电脑在**同一局域网** |

> ⚠️ 刷机有失去保修、变砖的风险，请按官方教程谨慎操作、自行评估。刷完原生小爱功能一切如常，也可随时切回原系统。

## 部署教程（按顺序做，首次约半小时）

### 第 1 步：给音箱刷 open-xiaoai 固件

跟着官方教程刷：**[open-xiaoai 刷机教程](https://github.com/idootop/open-xiaoai/blob/main/docs/flash.md)**（新款用 Type-C 数据线直连电脑、免拆机；旧款需拆机接 Micro USB）。

刷完重启，音箱会自动开启 SSH：账号 `root`，默认密码 `open-xiaoai`。

查出音箱的局域网 IP（米家 App 的设备详情，或路由器后台），在电脑 cmd 里验证能登录：

```bat
ssh -o HostKeyAlgorithms=+ssh-rsa root@音箱IP
```

### 第 2 步：给音箱装 client 转发程序

client 是跑在音箱上的小程序，负责把识别事件转发给电脑网关。**在上一步的 SSH 会话里**依次执行：

```shell
mkdir /data/open-xiaoai
echo 'ws://你的电脑IP:4399' > /data/open-xiaoai/server.txt
curl -sSfL https://gitee.com/idootop/artifacts/releases/download/open-xiaoai-client/init.sh | sh
```

`你的电脑IP` 换成实际值。写错了也不要紧——网关每次启动都会自动把这个文件改写成正确指向，并负责 client 的启动/重启，之后你不需要再手动登录音箱。

### 第 3 步：电脑装 Python

到 [python.org](https://www.python.org/downloads/) 下载安装，安装第一屏**务必勾选 “Add python.exe to PATH”**。装完打开 cmd 验证，并安装唯一的依赖：

```bat
python --version
pip install websockets
```

（pip 下载慢可换清华镜像：`pip install websockets -i https://pypi.tuna.tsinghua.edu.cn/simple`）

### 第 4 步：获取本仓库

```bat
git clone https://github.com/yelinlan/xiaoai.git
```

没装 git 就在 GitHub 页面 **Code → Download ZIP** 解压到任意目录（路径最好不含中文和空格）。后文命令都在这个目录里执行。

### 第 5 步：防火墙放行 4399 端口

**管理员身份**打开 cmd（开始菜单搜 cmd → 右键“以管理员身份运行”），执行一次：

```bat
netsh advfirewall firewall add rule name="open-xiaoai-gateway" dir=in action=allow protocol=TCP localport=4399
```

端口默认 4399，可用环境变量 `GATEWAY_PORT` 修改（改了则防火墙规则、第 2 步的 server.txt 要同步改）。

### 第 6 步：改配置（必改 3 处，建议 1 处）

仓库里全是作者机器的信息，改成你自己的：

**① 音箱密码** — `apps.json` 里的 `_音箱` 块。刷机后没改过密码的话就是默认值：

```json
"_音箱": { "user": "root", "password": "open-xiaoai" }
```

**② 密码应答脚本** — `xiaoai_askpass.bat` 整个文件就一行，改成和①相同的密码：

```bat
@echo open-xiaoai
```

**③ 应用路径** — `apps.json` 里各应用的 `path` / `cmd` 全是作者电脑的安装路径。先扫一遍自己电脑装了什么：

```bat
powershell -ExecutionPolicy Bypass -File scan_apps.ps1
```

对照输出把路径逐个改掉。**不改的后果只是**对应应用「打开XX」失效，其余功能照常。

**④（建议）删掉作者的服务器条目** — `apps.json` 里 `"我的服务器": { ... }` 整块删掉（含作者云服务器 IP），或换成你自己的服务器。

> 改 JSON 注意别丢逗号、别丢引号；改坏了网关起不来，`gateway.log` 里会报解析错误。

### 第 7 步：启动并验证

双击 `start.bat`（弹 UAC 窗口点“是”）。黑窗口会实时打日志，按顺序确认三件事：

1. `🚀 小爱语音遥控网关启动 ws://你的IP:4399` —— 网关起来了
2. `✅ 音箱已连接: ('音箱IP', ...)` —— 音箱连上了（首次启动会自动扫描局域网找音箱，可能要几十秒；仓库自带的 `speaker.json` 记录的是作者音箱，失效后自动重扫，不用管它）
3. 对音箱说「**小爱同学，打开记事本**」→ 记事本弹出，音箱播报「好的，记事本已打开」

三条都过 = 部署完成 🎉。哪条没过 → 看文末「故障排查」。

这个窗口保持开着服务就在跑，关窗口即停止。想日常无黑窗口运行，做第 8 步。

### 第 8 步（可选）：开机自启、无窗口常驻

用 `pythonw.exe`（Python 安装目录下的无窗口版解释器）建一个「登录时启动」的计划任务。**管理员身份**的 PowerShell 里跑：

```powershell
$pythonw  = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe"  # 换成你的 pythonw.exe
$proj     = "D:\soft\xiaoai-gateway"
$taskName = "XiaoAI-Gateway"
$user     = "$env:USERDOMAIN\$env:USERNAME"

Register-ScheduledTask -TaskName $taskName -Force `
  -Action (New-ScheduledTaskAction -Execute $pythonw -Argument "`"$proj\app.py`"" -WorkingDirectory $proj) `
  -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) `
  -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest) `
  -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
               -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
               -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -StartWhenAvailable -MultipleInstances IgnoreNew) `
  -Description "小爱语音遥控网关：登录时无窗口常驻"
```

图省事的话 `schtasks` 一行也能建，但拿不到下面那些「不限运行时长 / 崩了自动重启」的设置：

```bat
schtasks /Create /TN "XiaoAI-Gateway" /SC ONLOGON /RL HIGHEST /F /TR "\"<pythonw.exe 完整路径>\" \"<项目目录>\app.py\""
```

之后登录 Windows 就自动启动：内存常驻约 27 MB，日志只写 `gateway.log`，没有黑窗口。上面几个参数为什么必须这么填：

- `-ExecutionTimeLimit (New-TimeSpan -Seconds 0)` = **不限运行时长**。计划任务默认 72 小时后强制结束，常驻服务必须关掉这个限制
- `-RestartCount 5` + `-RestartInterval 1 分钟` = 进程异常退出后自动拉起
- `-RunLevel Highest` = 以最高权限启动，这样才能结束更高权限的进程（`apps.json` 里的 `process`）
- `-LogonType Interactive` = 只在本人登录时跑，且配合 `Highest` **不弹 UAC** 就能静默提权
- `-MultipleInstances IgnoreNew` = 已经在跑就别再起第二个，避免抢同一个端口

日常操作：

- 手动重启：`Stop-ScheduledTask -TaskName "XiaoAI-Gateway"; Start-ScheduledTask -TaskName "XiaoAI-Gateway"`
- 调试用 `start.bat` 前先停掉计划任务，否则端口冲突第二个起不来：`Stop-ScheduledTask -TaskName "XiaoAI-Gateway"`
- 查是否在跑：`Get-ScheduledTaskInfo -TaskName "XiaoAI-Gateway"`（`LastTaskResult` 为 `267009` 就是「正在运行」），或 `Get-Process pythonw`
- 取消自启：`Unregister-ScheduledTask -TaskName "XiaoAI-Gateway" -Confirm:$false`
- `schtasks` 版对应命令：`/End`、`/Run`、`/Delete /F`

### ⚠️ 安全提醒

- `apps.json` 和 `xiaoai_askpass.bat` 里是**明文密码**：改完配置后不要 push / fork 到任何公开仓库
- 仓库历史里遗留的作者密码与服务器 IP 请视为已泄露，不要复用；建议把音箱 SSH 密码改掉（SSH 进音箱执行 `passwd`，然后同步更新上面的①②）
- 音箱上的 client 会执行 server 端发来的任意脚本，`server.txt` 只指向你自己的电脑，不要连来路不明的地址

---

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

匹配不到的应用会说「这个XX我还不会打开」。忘了装了什么就跑 `scan_apps.ps1` 扫一遍。

## 网站与搜索

- **打开网站**：「打开哔哩哔哩 / B站 / GitHub / 知乎 / 微博 / 百度 / 淘宝 / 京东 / YouTube（油管）/ Google」，也支持「浏览器打开哔哩哔哩」语序
- **语音搜索**：「浏览器搜原神」「搜原神」「搜一下原神」「百度一下XX」→ 默认浏览器打开百度搜索结果。想换搜索引擎改 `apps.json` 里的 `_搜索` 配置：

```json
"_搜索": { "name": "必应", "url": "https://www.bing.com/search?q={}" }
```

- **打开服务器**：`apps.json` 里可配一条「我的服务器」（`cmd` 写 `wt.exe ssh user@你的IP`），说「打开我的服务器」即在 Windows Terminal 里直连；不需要就删掉该条目
- 卖萌前缀：「**喵喵**」是全指令通用的前缀词，喵喵打开QQ、喵喵搜原神 都行

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
| `find_speaker.py` | 找音箱排查工具：`python find_speaker.py --ssh`，只读扫本网段，列出所有设备和候选音箱 |
| `speaker.json` | 音箱发现结果记录（IP + MAC，运行时自动生成/更新，无需手改） |
| `gateway.log` | 运行日志（排查问题时看这个） |
| `client_ssh.log` | 音箱 client 的运行日志（由网关的常驻 SSH 会话保存） |
| `start.bat` | 启动脚本（会自动请求管理员权限；调试用，常驻请用第 8 步的计划任务） |

## IP 变化自愈（无需手动配置）

网关有一个**后台守护循环**：启动时自愈一轮，之后每 5 分钟巡检一次（`GATEWAY_RESCAN` 环境变量可改），
音箱一断开就立刻复查。每一轮做的事：

1. 等本机拿到有效的局域网 IP（最长 90 秒）。**拿不到就跳过本轮**，绝不会把 `ws://127.0.0.1:4399` 写进音箱
2. 按 `speaker.json` 里记录的 IP 做 SSH 验证（账号密码来自 `apps.json` 的 `_音箱` 配置）
3. 记录的 IP 失效时**重新发现音箱**：先 ping 一遍 /24 预热 ARP 表，
   ① 按记录的 **MAC** 认领（音箱换了 IP 也认得出来）② 找 ARP 邻居里开着 22 端口、
   banner 是 dropbear 的 ③ 再全网段补扫一遍（有些设备不回 ICMP，ARP 表里看不到），
   逐个 SSH 验证能读到 `/data/open-xiaoai/server.txt` 的才是小爱音箱
4. 对比音箱的指向与本机当前 IP，过期就改写其 `server.txt` 并通过常驻 SSH 会话重启它的 client
5. 把发现的 IP + MAC 写回 `speaker.json`，`client_ssh.log` 保存音箱 client 的运行日志

客户端由网关持有的 SSH 会话托管（音箱上没有 nohup/setsid 可用）：网关活着 client 就活着，网关退出后下次启动自动重新拉起。建议在路由器给电脑和音箱做 DHCP 保留，IP 固定更稳。

整个过程**只读网络状态、不修改任何网络配置**。找不到音箱时跑 `python find_speaker.py --ssh`，
它会告诉你本网段到底有哪些设备、音箱在不在里面、指向对不对。

## 音箱侧还原

网关只改音箱的一处：`/data/open-xiaoai/server.txt`（转发目标地址）。想彻底还原：

- **停用本网关**：SSH 进音箱，`rm -rf /data/open-xiaoai` 后 `reboot`，音箱只跑原生小爱
- **恢复原厂系统**：按刷机教程把启动分区切回 `boot1`（`fw_env -s boot_part boot1` 后重启），补丁固件和原固件双系统共存、随时可切

## 故障排查

- **start.bat 窗口一闪就没了**：Python 没装好或没勾 PATH。cmd 里跑 `python --version` 验证，报错就重装 Python
- **音箱没反应**：先看 `gateway.log` 有没有「✅ 音箱已连接」。没有 → 检查 ① 网关是否在跑 ② 电脑防火墙是否放行 4399（第 5 步）③ 音箱上第 2 步的 client 是否装过 ④ `_音箱` 密码是否和音箱实际密码一致（密码错会发现不了音箱）
- **日志刷「⚠️ 未找到小爱音箱」**：说明本网段里根本没有开着 dropbear 的设备，跑 `python find_speaker.py --ssh` 看清单。按顺序查 ① 音箱通电没有（指示灯橙色闪烁＝没连上 WiFi）② 音箱连的是不是和电脑同一个 WiFi（`find_speaker.py` 会打印电脑所在的 SSID）③ 路由器有没有被重置/换过 ④ 音箱是不是重新刷过机（MAC 变了要重新配网）
- **日志刷「❌ 90 秒内没拿到有效局域网 IP」**：电脑自己没连上网（Wi-Fi 没连/DHCP 没拿到地址）。守护循环会每 30 秒起继续重试，网络恢复后自动接上，不用重启网关
- **日志有「🎤 识别到」但没执行**：对照 `apps.json` 的名称、别名、路径；路径不对时「打开」会失败并播报
- **只有原生小爱在答**：指令没匹配上网关，同样看 🎤 日志里识别出的原文
- **想不通就跑自测**：`python selftest.py 打开QQ` 不需要音箱，能验证电脑侧整条链路
- **日志报 apps.json 解析错误**：JSON 改坏了（多/少逗号、引号），核对第 6 步的改动

## 已知限制

- 网关接管「打开/关闭XX」时会掐断原生小爱的抢答（重启其语音服务，官方同款中断方式），所以她的抢答只会漏出半句甚至听不到；非遥控指令完全不影响原生小爱
- 电脑关机 / 网关没开时命令无效，音箱原生功能不受任何影响
