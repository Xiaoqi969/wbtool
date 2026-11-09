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
> HTML dashboard of token / credit / activity statistics, plus a read-only preview of
> expired log files. No network, no telemetry, no conversation text ever leaves your machine.

---

## 一、这是什么

双击运行 → 自动扫描本机 WorkBuddy 的会话日志 → 生成 `wbtool_report.html` →
用浏览器打开报告 → **程序立即退出**。不常驻后台、不起本地服务、不联网。

报告是浅色青蓝风格的单文件 HTML，数据全部内联，**断网也能看**，可以直接保存或归档。

**默认完全只读**，不修改、移动或删除任何原始日志。只有显式执行 `--clean --yes`
才会把超期 jsonl 归档移走，且不是永久删除（见 [六、数据清理](#六数据清理)）。

### 主要特性

- 🕒 **时间范围切换**：今天 / 近 7 天 / 近 30 天 / 全部，所有图表与表格联动重算
- 🪙 **积分与 Token 全口径**：输入、输出、缓存命中/未命中、思考 Token、正文 Token、调用积分、原价积分、生成工具积分、免费模型标记
- 📊 **多维视图**：每日趋势堆叠柱状图、按模型 / 按项目分布、工具调用排行、小时活跃分布、会话排行、消息类型、执行状态、模型配额、每日明细表
- 🧹 **超期日志清理预览**：报告底部列出超过 N 天的 jsonl 与可释放空间，一键复制清理命令；默认只读，需显式 `--clean --yes` 才归档（可恢复、零删除）
- 🔒 **隐私优先**：只内联统计数值，绝不写入对话正文、推理文本、工具参数或文件快照内容
- 🪶 **轻量**：纯 Python 标准库，无第三方依赖；报告约 1 MB，程序用完即退
- 🖼️ **WorkBuddy 官方图标**（见 [图标声明](#十一图标与商标声明)）

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
| 顶部栏 | 标题、可点击的「作者:小柒 ↗」（→ `xiaoqilucky.com`）、范围切换、生成时间、调用次数、版本号 |
| 三张时段卡片 | 今天 / 近 7 天 / 近 30 天：合计 Token、输入、输出、缓存命中率、积分、调用次数 |
| 概览统计条 | 合计、输入、输出、缓存命中、调用次数等 8 项（随范围重算） |
| 积分消耗 | LLM 调用积分、原价积分、生成工具积分；按模型 / 按天分布，免费模型单独标注 |
| Token 构成 | 缓存命中 vs 未命中、思考 vs 正文的堆叠占比与精确数值 |
| 每日趋势 | 输入 / 输出双色堆叠柱状图，悬停看当日明细 |
| 分布视图 | 按模型、按项目（用真实工作目录 `cwd`）、工具调用排行 |
| 行为视角 | 小时活跃分布、会话排行（标题 / 项目 / 起止 / 调用 / Token / 积分） |
| 其他指标 | 消息类型分布、日志行数、推理消息、文件快照、图片输入块、执行完成 / 中断、模型配额 |
| 每日明细表 | 逐日 10 列：日期、调用、输入、输出、思考、缓存命中 / 未命中、合计 Token、积分、工具次数 |
| 数据清理 | 两级删除范围的清理清单（相对路径 / 大小 / 最晚记录 / 行数）、可释放空间、受保护会话数、风险警告、可点击「清除旧数据…」弹窗选择备份 / 回收站（**不随范围切换**） |

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

## 六、数据清理（两级删除范围）

报告底部「数据清理」面板会列出**符合清理条件**的 jsonl（相对路径 / 大小 / 最晚记录 / 行数）、
可释放空间，以及受保护的活跃会话数。点「清除旧数据…」会弹出确认框。

### 两级删除范围（先保护、后清除，宁保守勿误删）

| 规则 | 说明 |
|---|---|
| ① 近 **7 天**内有过对话的会话 | **无论文件多旧，永不清除**（活跃工作优先保护） |
| ② 超过 7 天没有对话的会话 | **只清除全部数据都超过 N 天（默认 30）的整文件**；不逐行删，保留会话连续性 |
| 自动排除 | 今天仍在写入 / 被触碰的活跃文件一律排除；只处理 `*.jsonl` |

换言之，一个文件被判为「可清除」，当且仅当它**最近一次对话发生在 N 天之前**
（此时它所有数据都早已超过 N 天，自然也满足「闲置 >7 天才考虑清除」）。

### 确认弹窗与两种去向（都可恢复）

弹窗里有一个**「备份数据」勾选框，默认不勾选**：

| 勾选？ | 去向 | 结果 |
|---|---|---|
| ✅ 勾选 | **备份模式** | 先完整备份到 `wbtool_backup/<时间戳>/`，再删原文件；随时可搬回 |
| ❌ 不勾选（默认） | **回收站模式** | 直接移入系统回收站；打开回收站即可还原 |

> ⚠️ 弹窗打开后，「确认清除」按钮会**禁用 3 秒**才可使用，避免误触。

### 为什么 HTML 里不能直接点按钮删

报告是 `file://` 静态页，**浏览器沙箱里的 JS 没有权限删除或写入本地文件**。
所以弹窗确认后只会**生成并自动复制一条命令**，真正的清理由 exe 在命令行执行：

```bash
:: 1. 先看清单（只读，绝不移动文件）
wbtool.exe --clean-preview --days 30

:: 2. 回收站模式执行（默认；可恢复）
wbtool.exe --clean --days 30 --yes

:: 2'. 备份模式执行（先备份到 wbtool_backup/ 再删原文件）
wbtool.exe --clean --mode backup --days 30 --yes
```

> `--clean` **不加 `--yes` 会自动降级为只读预览**；`--clean-preview` 永远只读。
> 因为 exe 是无控制台的窗口程序，预览与执行结果都会生成 `wbtool_clean_report.html`
> 并自动打开浏览器，你能看到完整清单与去向（备份目录路径 / 回收站）。

### 备份 ≠ 永久删除

- **备份模式**：文件被**完整复制到**程序所在目录（wbtool 文件夹）下的
  `wbtool_backup/<时间戳>/`，并写 `manifest.json` 记录原相对路径，校验通过后**再删原文件**；
  需要时按 manifest 搬回即可。
- **回收站模式**：文件被移入**系统回收站**（借助 Windows `SHFileOperation`，零第三方依赖），
  不是永久删除，打开回收站就能还原；非 Windows 平台退化为移动到 `wbtool_trash/`。

⚠️ **但请注意**：jsonl 是 WorkBuddy 的会话日志，移走后对应的历史会话可能无法在
WorkBuddy 里恢复。执行前请先用 `--clean-preview` 看清清单，确认这些会话不再需要。

如果你用 `--projects` 或 `WORKBUDDY_PROJECTS_DIR` 指定了别的日志目录，
请在命令后补上同样的参数（报告不内联你的绝对路径）。源码运行时把 `wbtool.exe`
换成 `python wb_usage_app.py`。

---

## 七、隐私说明（请认真看）

- 程序**默认严格只读**：不联网、不上传，不修改 / 移动 / 删除任何原始日志；
  只有显式执行 `--clean --yes` 才会把超期 jsonl 归档移走，且不是永久删除。
- 报告只内联统计字段；对话正文、推理文本、工具参数与输出、文件快照内容**一律不会**写进 HTML。
- 清理面板只列**相对路径**、大小与日期，不内联绝对路径或任何日志正文。
- ⚠️ 但报告里会包含**你的项目路径、模型名、会话标题和用量数值**，属于个人数据：
  - 仓库通过 `.gitignore` 排除 `wbtool_report.html`、`wbtool_clean_report.html` 与 `*.log`，**不会**上传；
  - 你分享自己生成的报告给别人前，请自行确认是否愿意公开这些信息。
- 本仓库不含任何真实用户数据，示例与文档均为脱敏内容。

---

## 八、命令行参数

```bash
python wb_usage_app.py [--projects DIR] [--out FILE] [--no-open] [--days N] [--version]
python wb_usage_app.py --clean-preview [--days N]
python wb_usage_app.py --clean --days N --yes                  # 回收站模式（默认）
python wb_usage_app.py --clean --mode backup --days N --yes    # 备份模式
```

| 参数 | 说明 |
|---|---|
| `--projects DIR` | 指定会话日志目录，默认 `~/.workbuddy/projects` |
| `--out FILE` | 指定报告 / 清理结果页输出路径，默认写到程序所在目录（不可写时自动回退用户目录 / 临时目录） |
| `--no-open` | 只生成页面，不自动打开浏览器（适合脚本 / 定时任务） |
| `--days N` | 清除阈值天数，默认 30（两级删除范围见 [六、数据清理](#六数据清理)：近 7 天活跃会话永不清除；闲置会话仅清除全量超 N 天的整文件） |
| `--clean-preview` | **只读**：列出可清除的 jsonl 并生成结果页，绝不移动任何文件 |
| `--clean` | 清理入口；缺少 `--yes` 时自动降级为只读预览 |
| `--mode` | 清理去向（`--clean --yes` 时生效）：`backup`=先完整备份到 `wbtool_backup/` 再删原文件；`recycle`=移入系统回收站（默认） |
| `--yes` | 仅与 `--clean` 同用才真正执行清理；默认绝不移动 / 删除文件 |
| `--version` | 显示版本号 |

环境变量：`WORKBUDDY_PROJECTS_DIR`（优先级低于 `--projects`）。
运行日志写到 `wbtool.log`（同样被 `.gitignore` 排除）。

---

## 九、打包

```bash
python build.py            # 同时构建目录版 zip 与单文件版 exe（默认）
python build.py onedir     # 只构建目录版
python build.py onefile    # 只构建单文件版
```

产物输出到 `release/`（不进 Git）：`wbtool-portable.zip` 与 `wbtool.exe`。
构建中间产物放在系统临时目录，结束后自动清理。详见 [build.py](build.py) 文件头。

---

## 十、文件清单（逐文件备注）

| 文件 | 备注 |
|---|---|
| `wb_usage_app.py` | **主程序 / 唯一源码文件**。四段结构：数据扫描层（含 `scan_old_files` 两级删除范围）、`HTML_TEMPLATE` 报告模板（含「清除旧数据…」确认弹窗）、超期日志清理（只读预览 / 备份到 `wbtool_backup/` / 移入回收站，零第三方依赖）、入口逻辑与 CLI。文件头有完整说明。 |
| `build.py` | **Windows 打包脚本**。支持 onedir / onefile 双模式，自动打 zip、输出体积对比。文件头有设计取舍说明。 |
| `README.md` | **本文件**。项目介绍、下载运行、数据口径、数据清理、隐私说明、FAQ、文件清单。 |
| `LICENSE` | **MIT 许可证全文**，Copyright (c) 2026 小柒。注意不含 `assets/` 图标的授权。 |
| `CHANGELOG.md` | **版本变更记录**，当前 v1.1.0。 |
| `CONTRIBUTING.md` | **贡献指南**：本地运行、代码结构、验证清单、隐私红线、提交规范。 |
| `.gitignore` | **排除规则**：按「个人隐私数据 / 二进制程序 / 构建产物 / 缓存 / 编辑器」分组，每条带注释。 |
| `assets/wbtool.ico` | **exe 图标**：WorkBuddy 官方 logo，11 种尺寸，供 `--icon` 使用。 |
| `assets/wbtool-256.png` | **README 展示用小 logo**，由官方图标缩放而来。 |
| `assets/README.md` | **资源说明**：图标来源、版权声明、替换方法。 |

> 仓库**只提交上表这些纯文本与图标文件**。exe、zip、生成的报告 / 结果页、日志、构建产物一律不进 Git；
> 可执行程序通过 GitHub Release 分发。

---

## 十一、图标与商标声明

`assets/` 下的图标取自 WorkBuddy 官方应用资源，仅用于标识「本工具读取 WorkBuddy 的会话数据」。
该图标**不在 MIT 许可证范围内**，版权归原权利人所有；本项目是非官方个人工具，
与 WorkBuddy 官方无隶属或背书关系。如需商用或权利方有异议，请按
[assets/README.md](assets/README.md) 替换或移除图标，功能不受影响。

---

## 十二、作者与许可证

**作者：小柒** · 个人主页 [xiaoqilucky.com](https://xiaoqilucky.com) · GitHub [@Xiaoqi969](https://github.com/Xiaoqi969)

代码采用 [MIT License](LICENSE)。欢迎 Issue、建议与 Pull Request，
贡献前请先读 [CONTRIBUTING.md](CONTRIBUTING.md)。

> 本项目与 WorkBuddy 官方无关，仅为读取本地日志的第三方统计工具。
