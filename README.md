# 小爱语音遥控电脑

对小爱音箱说「**小爱同学，打开QQ**」→ 电脑启动 QQ，音箱播报「好的，QQ已打开」。
还能关应用、开网站、语音搜索；其余语音照常走原生小爱，互不干扰。

| 对它说 | 效果 |
|---|---|
| 小爱同学，打开 QQ / 记事本 / 原神 | 启动应用，音箱播报确认 |
| 小爱同学，关闭QQ | 结束进程 |
| 小爱同学，搜原神 | 默认浏览器打开百度搜索 |
| 小爱同学，打开哔哩哔哩 | 打开网站 |

「喵喵」开头也行（喵喵打开QQ）；动词支持 打开/启动/运行 · 关闭/退出/结束/关掉。

## 快速开始

前提：**小爱音箱 Pro（LX06）或 Xiaomi 智能音箱 Pro（OH2P）**（其他机型不支持）、Windows 电脑，两者同一 WiFi。刷机有变砖风险，请自行评估。

1. **拿代码**：`git clone https://github.com/yelinlan/xiaoai.git`（或本页 Code → Download ZIP 解压）
2. **刷音箱**：按[官方刷机教程](https://github.com/idootop/open-xiaoai/blob/main/docs/flash.md)给音箱刷 open-xiaoai 固件，然后 SSH 进音箱（账号 `root`，默认密码 `open-xiaoai`）装转发 client——就 3 条命令，见[部署教程第 2 步](docs/DEPLOY.md)
3. **装依赖**：装 [Python](https://www.python.org/downloads/)（勾选 Add to PATH），然后 `pip install websockets`
4. **改配置**：
   - `apps.json` 的 `_音箱.password` → `open-xiaoai`（刷机默认密码）
   - `apps.json` 各应用的 `path` → 你自己的安装路径（跑 `powershell -ExecutionPolicy Bypass -File scan_apps.ps1` 扫出清单照着改；不改的应用说「打开XX」无效，其余照常）
   - `xiaoai_askpass.bat` → 内容改成一行 `@echo open-xiaoai`
   - `apps.json` 的 `我的服务器` 条目是作者的，整块删掉
5. **防火墙放行**（管理员 cmd，一次即可）：

   ```bat
   netsh advfirewall firewall add rule name="open-xiaoai-gateway" dir=in action=allow protocol=TCP localport=4399
   ```

6. **启动**：双击 `start.bat`（弹 UAC 点"是"），日志出现 `✅ 音箱已连接` → 对音箱说话就行
   - 想**开机自启、不要黑窗口**：按[部署教程第 8 步](docs/DEPLOY.md)建一个用 `pythonw.exe` 的计划任务，之后就不用再双击 `start.bat`。两个一起开会抢端口，调试前先 `Stop-ScheduledTask -TaskName "XiaoAI-Gateway"`

> 卡住了？每步详细说明、验证清单、开机自启、故障排查，都在 **[docs/DEPLOY.md](docs/DEPLOY.md)**。

## 突然连不上了？

网关会**自己找音箱**：启动时扫一遍，之后每 5 分钟巡检一次，音箱一断开就立刻复查。
电脑换了 IP（DHCP 重租 / 换网卡 / 断网重连）或者音箱换了 IP，它都会重新发现音箱、
把音箱上的 `/data/open-xiaoai/server.txt` 改成本机最新地址、再重启音箱的 client，不用手工干预。
`speaker.json` 里还记了音箱的 **MAC**，所以音箱 IP 变了也照样认得出来。

日志一直刷 `⚠️ 未找到小爱音箱` 时，跑这个只读排查工具：

```bat
python find_speaker.py --ssh
```

它列出本网段所有设备（IP + MAC）、哪些开着 dropbear、哪些应答小米协议，
并直接告诉你音箱当前的指向对不对。**不改任何网络配置，随便跑。**

仍然找不到音箱，按顺序查：音箱通电没有（指示灯橙色闪烁＝没连上 WiFi）→ 音箱连的是不是
和电脑同一个 WiFi → 路由器有没有被重置过（电脑 IP 变了就说明 DHCP 重新分配过）→
音箱是不是重新刷过机（MAC 变了要重新配网）。

## 加自己的应用

编辑 `apps.json`，照抄一个现有条目改名字和路径即可，**改完不用重启**，下一句话就生效：

```json
"网易云音乐": {
  "path": "D:\\...\\cloudmusic.exe",
  "process": "cloudmusic.exe",
  "aliases": ["网易云", "云音乐"],
  "patterns": ["网易(云)?音乐"]
}
```

`aliases` 是别名，`patterns` 是正则（自动忽略空格和大小写）；`process` 用于「关闭XX」。匹配不到会说「这个XX我还不会打开」。

## 注意

- `apps.json` / `xiaoai_askpass.bat` 是**明文密码**：改完别 push / fork 到公开仓库；建议 SSH 进音箱 `passwd` 改掉默认密码
- 电脑关机或网关没在跑时命令无效，音箱原生功能不受影响
- 仓库历史里作者自己的密码/IP 视为已泄露，别复用
