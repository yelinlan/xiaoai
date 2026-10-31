# 发布准备：新建精简仓库目录并本地 commit

## 产出
`C:\Users\Administrator\IdeaProjects\xiaoai-gateway\` — 干净的可分享项目目录，本地 git 仓库含一次完整 commit。**不推远程**（按你的要求；将来要推时 `git remote add origin <你的仓库地址>` + `git push` 即可）。**现在跑着的原目录 `xiaoai\` 实例完全不动**。

## 文件处理清单

**复制并保留**：
- `app.py` — 核心网关（含全部功能：遥控/网站/搜索/打字/听写/抢答屏蔽/IP自愈/常驻）
- `apps.json` — 应用表保留你的个人配置原样；**唯一改动：`_音箱.password` 清空为 `""`**（README 说明需自行填写）
- `README.md` — 保留现有内容，顶部新增开源说明区：项目简介、**前置条件**（小爱音箱 Pro LX06 已按 [flash.md](https://github.com/idootop/open-xiaoai/blob/main/docs/flash.md) 刷机）、**特性亮点**（①接管指令时自动屏蔽小爱原生抢答，避免两种声音 ②免唤醒词语音输入听写 ③IP 变化自愈 ④无窗口常驻 38MB）、架构图、安装步骤
- `start.bat`、`selftest.py`、`test_sensevoice.py`、`scan_apps.ps1`
- 新增 `LICENSE`（MIT）
- 新增 `.gitignore`：`*.log`、`speaker.json`、`xiaoai_askpass.bat`、`__pycache__/`、`.zcode/`、`models/`、`NUL`、`_ssh_err.log`、`_t*.mp3/wav`
- 新增 `scripts/download_models.ps1` — 一键下载两个本地识别模型（SenseVoice + 流式 zipformer + silero VAD，从 sherpa-onnx 官方 releases，支持 gh-proxy 加速参数）到项目 `models/` 目录

**不复制（运行时产物/敏感/垃圾）**：
`gateway.log`、`client_ssh.log`、`speaker.json`、`xiaoai_askpass.bat`、`NUL`、`_ssh_err.log`、`_t1.mp3`、`_t3.wav`、`__pycache__/`、`.zcode/`、`resolve_lnk.ps1`（一次性工具）

**模型路径改造**：`app.py` 中三个模型目录常量默认值从 `~\.zcode\models\...` 改为项目内 `models\...`（环境变量仍可覆盖）；模型本身**不进仓库**（.gitignore 排除），由下载脚本获取。你本机 `xiaoai\` 的运行实例不受影响（它有自己的路径）。

## 执行步骤
1. 新建 `xiaoai-gateway/` 目录，按上述清单复制文件
2. `apps.json` 删密码；`app.py` 模型路径默认值改为 `models/`
3. 写 `scripts/download_models.ps1`、`.gitignore`、`LICENSE`、README 增补开源说明区
4. `git init` → 检查 git 身份配置（缺失则设仓库级 user.name=yelinlan、user.email=yelinlan@users.noreply.github.com）→ `git add` → `git commit -m "..."`（提交信息概述全部功能）
5. 最终核对：`git status` 干净、`git log` 一条完整提交、目录里无任何密码/日志文件（grep 复查 yelinlan@123456 不存在）

## 明确不做
- 不推送任何远程仓库（需要推送时自行 `git remote add` + `git push`）
- 不动 `xiaoai\` 原目录与正在运行的计划任务实例