<p align="center">
  <img src="assets/wbtool-256.png" alt="wbtool logo" width="96">
</p>

<h1 align="center">wbtool · WorkBuddy 用量统计</h1>

<p align="center">
  一个完全离线、零第三方依赖的 Windows 小工具：扫描本机 WorkBuddy 会话日志，
  生成一份自包含的 HTML 图形化用量报告。<br>
  作者 <a href="https://xiaoqilucky.com"><b>小柒</b></a> ·
  <a href="https://github.com/Xiaoqi969/wbtool">GitHub 仓库</a> ·
  <a href="https://github.com/Xiaoqi969/wbtool/releases/latest">下载最新版</a> ·
  MIT License
</p>

> **WorkBuddy Usage Dashboard** — a local-only Windows tool that parses WorkBuddy
> session logs (`~/.workbuddy/projects/**/*.jsonl`) and renders a fully self-contained
> HTML dashboard of token / credit / activity statistics. No network, no telemetry,
> no conversation text ever leaves your machine.

---

## 一、这是什么

双击运行 → 自动扫描本机 WorkBuddy 的会话日志 → 生成 `wbtool_report.html` →
用浏览器打开报告 → **程序立即退出**。不常驻后台、不起本地服务、不联网、不修改任何原始日志。

报告是浅色青蓝风格的单文件 HTML，数据全部内联，**断网也能看**，可以直接保存或归档。

### 主要特性

- 🕒 **时间范围切换**：今天 / 近 7 天 / 近 30 天 / 全部，所有图表与表格联动重算
- 🪙 **积分与 Token 全口径**：输入、输出、缓存命中/未命中、思考 Token、正文 Token、调用积分、原价积分、生成工具积分、免费模型标记
- 📊 **多维视图**：每日趋势堆叠柱状图、按模型 / 按项目分布、工具调用排行、小时活跃分布、会话排行、消息类型、执行状态、模型配额、每日明细表
- 🔒 **隐私优先**：只内联统计数值，绝不写入对话正文、推理文本、工具参数或文件快照内容
- 🪶 **轻量**：纯 Python 标准库，无第三方依赖；报告约 1 MB，程序用完即退
- 🖼️ **WorkBuddy 官方图标**（见 [图标声明](#八图标与商标声明)）

---

## 二、下载与运行（Windows）

到 [Releases](https://github.com/Xiaoqi969/wbtool/releases/latest) 下载。提供两种构建，任选其一：

| | 🟢 目录版（推荐）`wbtool-portable.zip` | 单文件版 `wbtool.exe` |
|---|---|---|
| 结构 | 一个文件夹：`wbtool.exe` 启动器 + `_internal\` 运行时 | 单个 exe |
| exe 本体 | 很小（约 1 MB） | 约 6 MB，内含全部运行时 |
| 启动方式 | 直接加载外置运行时 | 每次启动先解压到临时目录 |
| 启动速度 / 内存峰值 | 更快、更低 | 稍慢、略高 |
| 杀软误报 | 更少 | 相对更常见 |
| 适合 | 固定放在一个目录里长期使用 | 想随手拷贝一个文件 |

**目录版解压后长这样**（`_internal` 请不要删，里面是 Python 运行时）：

```
wbtool/
├── wbtool.exe        ← 双击这个（只是启动器）
├── _internal/        ← 运行时与标准库，勿删
└── wbtool_report.html ← 运行后自动生成（含你的本机数据，别公开分享）
```

> 两种版本功能完全一致，区别只在打包方式。目录版把依赖外置，因此 exe 更小、
> 启动不用解压；但**总磁盘占用不会变小**，运行时只是从 exe 里搬到了文件夹。

**运行要求**：Windows 10/11，且本机安装过 WorkBuddy 并产生过会话记录。
把 exe 放在只读目录（如 `C:\Program Files\`）也没问题，程序会自动把报告写到用户目录。

---

## 三、从源码运行

不需要安装任何依赖，Python 3.8+ 即可：

```bash
git clone https://github.com/Xiaoqi969/wbtool.git
cd wbtool
python wb_usage_app.py              # 生成报告并自动打开浏览器
python wb_usage_app.py --no-open    # 只生成，不打开
```

想自己打包 exe 才需要 `pip install pyinstaller`，然后 `python build.py`。

---

## 四、报告包含哪些内容

| 区块 | 内容 |
|---|---|
| 顶部栏 | 标题、可点击的「作者:小柒 ↗」（→ `xiaoqilucky.com`）、范围切换、生成时间、调用次数 |
| 三张时段卡片 | 今天 / 近 7 天 / 近 30 天：合计 Token、输入、输出、缓存命中率、积分、调用次数 |
| 概览统计条 | 合计、输入、输出、缓存命中、调用次数等 8 项（随范围重算） |
| 积分消耗 | LLM 调用积分、原价积分、生成工具积分；按模型 / 按天分布，免费模型单独标注 |
| Token 构成 | 缓存命中 vs 未命中、思考 vs 正文的堆叠占比与精确数值 |
| 每日趋势 | 输入 / 输出双色堆叠柱状图，悬停看当日明细 |
| 分布视图 | 按模型、按项目（用真实工作目录 `cwd`）、工具调用排行 |
| 行为视角 | 小时活跃分布、会话排行（标题 / 项目 / 起止 / 调用 / Token / 积分） |
| 其他指标 | 消息类型分布、日志行数、推理消息、文件快照、图片输入块、执行完成 / 中断、模型配额 |
| 每日明细表 | 逐日 10 列：日期、调用、输入、输出、思考、缓存命中 / 未命中、合计 Token、积分、工具次数 |

### 数据口径

- 数据源是本机 `~/.workbuddy/projects/**/*.jsonl`，**统计的是这台电脑自己的用量**。
- 「Token」是原始 token 数；「积分」是日志中 `rawUsage.credit` 记录的计费值，
  与官网积分明细口径可能不同，两者不要直接相加。
- 缓存命中率极高是长上下文复用的正常表现；`hy3` / `hy4-free` 等免费模型积分为 0。

---

## 五、换台电脑能用吗

| 情况 | 结果 |
|---|---|
| 另一台 **Windows**，装了 WorkBuddy 且有会话记录 | ✅ 直接能用，路径自动适配当前用户 |
| 换电脑后**没有** WorkBuddy 数据 | ⚠️ 不会静默失败，会打开一页友好提示，说明期望位置和如何指定目录 |
| 没装 Edge / Edge 装在非标准位置 | ✅ 自动尝试 Chrome / Chromium / Firefox，最后回退系统默认浏览器 |
| **macOS / Linux** | ❌ 仅正式支持 Windows；exe 无法运行。源码可在其他平台直接跑，但不在支持范围 |

可用环境变量 `WORKBUDDY_PROJECTS_DIR` 或 `--projects` 指向别处的日志目录。

---

## 六、隐私说明（请认真看）

- 程序**只读**本机日志，不联网、不上传、不写回任何原始数据。
- 报告只内联统计字段；对话正文、推理文本、工具参数与输出、文件快照内容**一律不会**写进 HTML。
- ⚠️ 但报告里会包含**你的项目路径、模型名、会话标题和用量数值**，属于个人数据：
  - 仓库通过 `.gitignore` 排除 `wbtool_report.html` 与 `*.log`，**不会**上传；
  - 你分享自己生成的报告给别人前，请自行确认是否愿意公开这些信息。
- 本仓库不含任何真实用户数据，示例与文档均为脱敏内容。

---

## 七、命令行参数

```
python wb_usage_app.py [--projects DIR] [--out FILE] [--no-open] [--version]
```

| 参数 | 说明 |
|---|---|
| `--projects DIR` | 指定会话日志目录，默认 `~/.workbuddy/projects` |
| `--out FILE` | 指定报告输出路径，默认写到程序所在目录（不可写时自动回退用户目录 / 临时目录） |
| `--no-open` | 只生成报告，不自动打开浏览器（适合脚本 / 定时任务） |
| `--version` | 显示版本号 |

环境变量：`WORKBUDDY_PROJECTS_DIR`（优先级低于 `--projects`）。
运行日志写到 `wbtool.log`（同样被 `.gitignore` 排除）。

---

## 八、打包

```bash
python build.py            # 同时构建目录版 zip 与单文件版 exe（默认）
python build.py onedir     # 只构建目录版
python build.py onefile    # 只构建单文件版
```

产物输出到 `release/`（不进 Git）：`wbtool-portable.zip` 与 `wbtool.exe`。
构建中间产物放在系统临时目录，结束后自动清理。详见 [build.py](build.py) 文件头。

---

## 九、文件清单（逐文件备注）

| 文件 | 备注 |
|---|---|
| `wb_usage_app.py` | **主程序 / 唯一源码文件**。三段结构：数据扫描层、`HTML_TEMPLATE` 报告模板、入口逻辑。文件头有完整说明。 |
| `build.py` | **Windows 打包脚本**。支持 onedir / onefile 双模式，自动打 zip、输出体积对比。文件头有设计取舍说明。 |
| `README.md` | **本文件**。项目介绍、下载运行、数据口径、隐私说明、FAQ、文件清单。 |
| `LICENSE` | **MIT 许可证全文**，Copyright (c) 2026 小柒。注意不含 `assets/` 图标的授权。 |
| `CHANGELOG.md` | **版本变更记录**，当前 v1.0.0。 |
| `CONTRIBUTING.md` | **贡献指南**：本地运行、代码结构、验证清单、隐私红线、提交规范。 |
| `.gitignore` | **排除规则**：按「个人隐私数据 / 二进制程序 / 构建产物 / 缓存 / 编辑器」分组，每条带注释。 |
| `assets/wbtool.ico` | **exe 图标**：WorkBuddy 官方 logo，11 种尺寸，供 `--icon` 使用。 |
| `assets/wbtool-256.png` | **README 展示用小 logo**，由官方图标缩放而来。 |
| `assets/README.md` | **资源说明**：图标来源、版权声明、替换方法。 |

> 仓库**只提交上表这些纯文本与图标文件**。exe、zip、生成的报告、日志、构建产物一律不进 Git；
> 可执行程序通过 GitHub Release 分发。

---

## 十、图标与商标声明

`assets/` 下的图标取自 WorkBuddy 官方应用资源，仅用于标识「本工具读取 WorkBuddy 的会话数据」。
该图标**不在 MIT 许可证范围内**，版权归原权利人所有；本项目是非官方个人工具，
与 WorkBuddy 官方无隶属或背书关系。如需商用或权利方有异议，请按
[assets/README.md](assets/README.md) 替换或移除图标，功能不受影响。

---

## 十一、作者与许可证

**作者：小柒** · 个人主页 [xiaoqilucky.com](https://xiaoqilucky.com) · GitHub [@Xiaoqi969](https://github.com/Xiaoqi969)

代码采用 [MIT License](LICENSE)。欢迎 Issue、建议与 Pull Request，
贡献前请先读 [CONTRIBUTING.md](CONTRIBUTING.md)。

> 本项目与 WorkBuddy 官方无关，仅为读取本地日志的第三方统计工具。
