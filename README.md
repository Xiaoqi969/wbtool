<p align="center">
  <img src="assets/WBtool-256.png" alt="WBtool logo" width="96">
</p>

<h1 align="center">WBtool · WorkBuddy 用量统计</h1>

<p align="center">
  两个完全离线的 Windows 小工具：一份自包含的 <b>HTML 用量报告</b>，一个常驻屏幕顶端的 <b>灵动岛</b>。<br>
  作者 <a href="https://xiaoqilucky.com"><b>小柒</b></a> ·
  <a href="https://github.com/Xiaoqi969/WBtool">GitHub 仓库</a> ·
  <a href="https://github.com/Xiaoqi969/WBtool/releases/latest">下载最新版</a> ·
  MIT License
</p>

> **WorkBuddy Usage Dashboard** — two local-only Windows tools that parse WorkBuddy
> session logs (`~/.workbuddy/projects/**/*.jsonl`): a self-contained HTML dashboard
> of token / credit / activity statistics, and a always-on-top "dynamic island" pill
> showing today's usage in real time. No network, no telemetry, no conversation text
> ever leaves your machine.

---

## 一、这是什么

两个程序，各干一件事，**可以只用其中一个，也可以同时用**。它们共用同一个解析内核 `scanlib.py`，所以灵动岛上的数字和 HTML 报告里的数字永远一致。

| | 🧾 HTML 报告 `WBtool.exe` | 🏝️ 灵动岛 `WBtool-island.exe` |
|---|---|---|
| 做什么 | 扫描日志 → 生成一份单文件 HTML 报告 → 打开浏览器 → **程序立即退出** | 屏幕顶部正中常驻一个半透明胶囊，**实时**显示今日用量 |
| 什么时候用 | 想回顾趋势、看模型/项目分布、清理旧日志 | 想知道「今天用了多少、现在多快」，不想每次都开报告 |
| 是否常驻 | 否，用完即退 | 是，托盘可退出 |
| 体积 | 6.3 MB（单文件） | 37 MB（单文件，含 Qt 运行时） |
| 技术栈 | Python 标准库，**零第三方依赖** | Python + PySide6（Qt 6） |

两者都**完全离线、默认严格只读**：不联网、不上传、不修改/移动/删除任何原始日志。只有报告程序在你显式执行 `--clean --yes` 时才会移走超期日志，且不是永久删除（见《七、数据清理》）。

---

## 二、下载与运行

到 [Releases](https://github.com/Xiaoqi969/WBtool/releases/latest) 下载，四个文件按需取：

| 文件 | 大小 | 是什么 |
|---|---|---|
| `WBtool-island.exe` | 37.0 MB | **灵动岛**，单文件，双击即常驻 |
| `WBtool-island-portable.zip` | 37.0 MB | 灵动岛目录版，解压后运行 `WBtool-island\WBtool-island.exe` |
| `WBtool.exe` | 6.3 MB | **HTML 报告**，单文件，双击出报告 |
| `WBtool-portable.zip` | 6.2 MB | 报告目录版，解压后运行 `WBtool\WBtool.exe` |

> 两个程序互不干扰，可以同时装。**功能上目录版与单文件版完全一致**，区别只在打包方式。

### 目录版还是单文件版

| | 🟢 目录版（推荐）`*-portable.zip` | 单文件版 `*.exe` |
|---|---|---|
| 结构 | 一个文件夹：exe 启动器 + `_internal\` 运行时 | 单个 exe |
| 启动方式 | 直接加载外置运行时 | 每次启动先解压到临时目录 |
| 启动速度 / 内存峰值 | 更快、更低 | 稍慢、略高 |
| 杀软误报 | 更少 | 相对更常见 |
| 适合 | 固定放在一个目录长期使用 | 想随手拷贝一个文件 |

**目录版解压后长这样**（`_internal` 是 Python 运行时，**不要删**）：

```
WBtool/                     ← 或 WBtool-island/
├── WBtool.exe              ← 双击这个（灵动岛版为 WBtool-island.exe）
├── _internal/              ← 运行时与标准库，勿删
└── WBtool_report.html      ← 报告版运行后在此生成（含你的本机数据，别公开分享）
```

> 目录版把依赖外置，所以 exe 更小、启动不用解压；但**总磁盘占用不会变小**，运行时只是从 exe 里搬到了文件夹。

### 运行要求

- **Windows 10 / 11**（仅正式支持 Windows；macOS / Linux 见《九、常见问题》）
- 本机安装过 WorkBuddy 并产生过会话记录
- 放在只读目录（如 `C:\Program Files\`）也没问题，程序会自动把报告写到可写位置

---

## 三、灵动岛

双击后，屏幕顶部正中常驻一个半透明胶囊。**每 10 秒**增量扫描一次日志（只读新增字节，68 MB 的日志也不会反复全量重读）。

### 收起态：只回答两个问题

「今天用了多少」「现在多快」——三格数字：**Token / 积分 / 流速**，末格是 `N/s` 形式的 token 流速（最近 15 秒滚动平均；上千折 `Nk/s`，上百万折 `M/s`）。

**收起态只有这三个数字**：不滚动、不轮播、不塞会话列表。它常驻在屏幕顶端，任何持续运动都会变成干扰；要看细节就展开。

首份数据到达前显示 `—` 而不是 `0`——首次扫描要 1.7 秒，显示 0 会被误读成「今天没用」。

### 展开态

**左键单击胶囊**，以**弹簧物理**驱动的形变「长大」成明细面板（宽度 / 高度 / 内容透明度三根独立弹簧，中途反向打断时位置与速度连续，末尾带轻微回弹），再点一次收起。展开后宽 640，高度按内容在 200~640 之间自适应：

- 四列指标卡：今日**合计 / 输入 / 输出 / 积分**；右上角药丸是**所有会话合计**的流速
- **额度曲线卡**（v3.2.0 起）：主曲线的模型名、本窗口已用百分比、重置时间；面积折线按「窗口起点 → 现在」铺开，纵轴按峰值自适应（10/20/25/50/100 五档）。已用 ≥80% 整卡转琥珀色。同一个模型在轴行里以「另有 xxx 41% · hy4 12%」列出，只画最该被看见的那一条
- 进行中的会话列表，最多 5 行，多出来的折成「还有 N 个会话」；**每一行都带它自己的流速**（同一套 15 秒窗口、同样只算输出 token），静默会话显示 `—` 而不是 `0/s`——「进行中」不等于「正在生成」。会话名取自你在 WorkBuddy 里改过的名字（读 `workbuddy.db` 的 `custom_title`），没改过才用 AI 自动生成的标题
- **每会话上下文占用**（v3.2.0 起）：会话行里一条 26px 细进度条 + 百分比（读 `workbuddy.db` 的 `session_usage.used / size`），≥80% 转琥珀色提示该开新会话；库里没有这条会话的记录就整列留空，不拿「最后一次调用的 token」反推
- 底部脚注标注刷新周期与日志文件数

### 交互一览

| 操作 | 结果 |
|---|---|
| 左键单击胶囊 | 展开 / 收起明细面板 |
| 按住拖动胶囊 | 移到任意位置并**自动记住**（下次原位出现） |
| 左键单击**托盘图标** | 把胶囊**提到最前**；隐藏状态下会先唤回 |
| 右键单击托盘图标 | 菜单三项：显示 / 隐藏、锁定置顶（始终最上层）、退出 |
| 再次双击启动器 | **不会**开出第二个胶囊，而是唤回已在运行的那个 |
| 系统开启「减弱动效」 | 形变直接跳到终态（热生效，无需重启） |

位置与「锁定置顶」状态存在 `%APPDATA%\WBtool-island\island-prefs.json`，与旧 Electron 版**同一文件同一键**，从 1.x 升级过来位置不变。

### 毛玻璃与开销

背景是**真·毛玻璃**：Win32 截取胶囊背后的桌面画面，降采样后做均值模糊，Win10 / Win11 表现一致，不依赖 Acrylic 等系统版本特性。

采样是**按需**的：启动前 3 秒 5 次/秒（让明暗主题尽快收敛），之后降到 **0.5 次/秒**；胶囊静止时帧循环自动停掉，隐藏或拖拽期间另行处理。稳态常驻 CPU 实测 **0.37%**。

### 2.0.0 为什么换引擎

2.0.0 起灵动岛由 Electron 换成 **PySide6（Qt 6）**，交互与视觉按旧版对齐重做：

| | Electron（1.3.0） | PySide6（2.0.0） |
|---|---|---|
| 单文件体积 | 105.2 MB | **37.0 MB**（−65%） |
| 冷启动（到首个可见窗口） | 8.79 s | **3.2 s**（实测 3.0~3.4 s） |
| 构建链 | Node.js + electron-builder | `pip install pyinstaller` + `python build.py` |

旧版仍可回退：`python build.py island` 会打出 `WBtool-island-legacy.exe`（需本机有 Node.js / npm，脚本会自动 `npm install`；仓库不存 `node_modules`）。默认构建完全不涉及它。

---

## 四、HTML 报告

报告是浅色青蓝风格的**单文件 HTML**，数据全部内联，**断网也能看**，可以直接保存或归档。约 2.7 MB（随数据量增长）。

### 主要特性

- 🕒 **时间范围切换**：今天 / 近 7 天 / 近 30 天 / 全部，所有图表与表格联动重算
- 🪙 **积分与 Token 全口径**：输入、输出、缓存命中/未命中、思考 Token、正文 Token、调用积分、原价积分、生成工具积分、免费模型标记
- 📊 **多维视图**：每日趋势堆叠柱状图、按模型 / 按项目分布、工具调用排行、小时活跃分布、会话排行、消息类型、执行状态、模型额度曲线、每日明细表
- 🧹 **超期日志清理预览**：报告底部列出超过 N 天的 jsonl 与可释放空间，一键复制清理命令；默认只读，需显式 `--clean --yes` 才归档（可恢复、零删除）
- 📌 **每日快照，清理后趋势不断**：每次生成报告会把当天用量存成 KB 级本地快照；日后即使清理了旧 jsonl，趋势 / 积分 / 模型 / 项目分布仍从快照补回而保持连续（详见《四、快照》与《七、数据清理》）
- 🔒 **隐私优先**：只内联统计数值，绝不写入对话正文、推理文本、工具参数或文件快照内容
- 🖼️ **WorkBuddy 官方图标**（见《十二、图标与许可》）

### 报告区块

| 区块 | 内容 |
|---|---|
| 顶部栏 | 标题、可点击的「作者:小柒 ↗」（→ `xiaoqilucky.com`）、「清除旧数据…」按钮（范围切换左侧）、范围切换、生成时间、调用次数、版本号 |
| 三张时段卡片 | 今天 / 近 7 天 / 近 30 天：合计 Token、输入、输出、缓存命中率、积分、调用次数 |
| 概览统计条 | 合计、输入、输出、缓存命中、调用次数等 8 项（随范围重算） |
| 积分消耗 | LLM 调用积分、原价积分、生成工具积分；按模型 / 按天分布，免费模型单独标注 |
| Token 构成 | 缓存命中 vs 未命中、思考 vs 正文的堆叠占比与精确数值 |
| 模型额度（v3.2.0 起） | 一个模型一张卡：本窗口已用 %、重置时间 / 剩余时长、采样次数与面积折线（24h 窗口铺满整幅，虚线标出「现在」，过期窗口降饱和并注明结束时刻）。**不随范围切换** |
| 每日趋势 | 输入 / 输出双色堆叠柱状图，悬停看当日明细 |
| 分布视图 | 按模型、按项目（用真实工作目录 `cwd`）、工具调用排行 |
| 行为视角 | 小时活跃分布、会话排行（标题 / 项目 / 起止 / 调用 / Token / 积分） |
| 其他指标 | 消息类型分布、日志行数、推理消息、文件快照、图片输入块、执行完成 / 中断 |
| 每日明细表 | 逐日 10 列：日期、调用、输入、输出、思考、缓存命中 / 未命中、合计 Token、积分、工具次数 |
| 数据清理 | 两级删除范围的清理清单（相对路径 / 大小 / 最晚记录 / 行数）、可释放空间、受保护会话数、风险警告（**不随范围切换**）。「清除旧数据…」按钮在顶部栏、范围切换左侧 |

### 数据口径

- 数据源是本机 `~/.workbuddy/projects/**/*.jsonl`，**统计的是这台电脑自己的用量**。
- 「Token」是原始 token 数；「积分」是日志中 `rawUsage.credit` 记录的计费值，
  与官网积分明细口径可能不同，两者不要直接相加。
- 缓存命中率极高是长上下文复用的正常表现；`hy3` / `hy4-free` 等免费模型积分为 0。
- **额度口径**（v3.2.0 起）：`providerData.rawUsage.quota.percent` 是「本窗口已用百分比」，
  `reset_at` 是**窗口结束时刻**（实测窗口 24h，percent 从 0 爬到 100 后重置）。
  同一模型只看采样最新的那个窗口，**过期窗口不会伪装成「现在」**：灵动岛直接不画，
  报告里照画但降饱和并写明「窗口已于 … 结束」。
- 灵动岛走同一个 `scanlib.py`，所以胶囊数字与报告**逐项相等**；差异只可能来自刷新时间差（最多 10 秒）。

### 每日快照（v3.1.0 起）

报告每次生成后，会在本地写一份 KB 级统计快照（实测 28 天约 31 KB），位置：

```
~/.wbtool/snapshots/<数据源hash>/daily_snapshot.json
```

- **为什么需要**：日志一旦被清理（《七、数据清理》），那些天的历史数字就不在了。快照把每天用量按「天 × 模型 × 项目」预聚合存下来——只存统计数值和模型名、项目目录名，**不含对话正文、推理文本、工具参数/输出、会话 ID 或绝对路径**。
- **清理后自动补回**：日后重新生成报告时，若某些天已无 jsonl，会从快照把它们补回，趋势 / 积分 / 模型 / 项目分布 / 每日明细保持连续；报告顶部会提示「本地快照已补回 N 个已清理的历史天」。被补回的历史会话在「会话排行」里归入 `unknown`（快照不存会话 ID，这是有意的隐私取舍）。
- **不碰你的数据**：快照只写`~/.wbtool/`下自己的文件，不修改 / 移动 / 删除任何原始日志；`--clean` 也只处理 jsonl，不会动快照。写入用「合并式 + 原子替换」，某次扫描没读到数据时绝不覆盖旧快照。若目录只读或写入失败，只影响历史延续，报告照常生成。
- **数据源隔离**：用 `--projects` 指定不同日志目录时，hash 不同、快照各自独立，不会串数据。
- **想彻底清空**：删除整个 `~/.wbtool/snapshots/` 目录即可，报告会退回"只按现存日志统计"的行为，不受影响。

---

## 五、从源码运行

### 报告（不需要任何依赖，Python 3.8+）

```bash
git clone https://github.com/Xiaoqi969/WBtool.git
cd WBtool
python wb_usage_app.py              # 生成报告并自动打开浏览器
python wb_usage_app.py --no-open    # 只生成，不打开
```

### 灵动岛（多一个 Qt 依赖，Python 3.9+）

```bash
pip install PySide6-Essentials     # 约 90 MB，含 Qt Core/Gui/Widgets/Network
python island_qt/main.py           # 直接起胶囊
python island_qt/main.py --debug   # 额外打印窗口几何、DPI、采样状态、启动分段耗时
python island_qt/main.py --self-test 20   # 20 秒后自检并退出（无人值守冒烟）
```

> 打包后没有控制台：冻结态下 stdout/stderr 自动落到 `%APPDATA%\WBtool-island\island-qt.log`，
> `--self-test` 的输出就是从这里读的。

想自己打 exe 才需要 `pip install pyinstaller`，然后 `python build.py`（见《十、打包与产物》）。

---

## 六、命令行参数

### 报告程序

```bash
python wb_usage_app.py [--projects DIR] [--out FILE] [--no-open] [--days N] [--version]
python wb_usage_app.py --clean-preview [--days N]
python wb_usage_app.py --clean --days N --yes                  # 回收站模式（默认）
python wb_usage_app.py --clean --mode backup --days N --yes    # 备份模式
```

| 参数 | 说明 |
|---|---|
| `--projects DIR` | 指定会话日志目录，默认 `~/.workbuddy/projects` |
| `--out FILE` | 报告 / 清理结果页的输出路径，默认写到程序所在目录（不可写时自动回退用户目录 / 临时目录） |
| `--no-open` | 只生成页面，不自动打开浏览器（适合脚本 / 定时任务） |
| `--days N` | 清除阈值天数，默认 30（两级删除范围见《七、数据清理》） |
| `--clean-preview` | **只读**：列出可清除的 jsonl 并生成结果页，绝不移动任何文件 |
| `--clean` | 清理入口；缺少 `--yes` 时自动降级为只读预览 |
| `--mode` | 清理去向（`--clean --yes` 时生效）：`backup` = 先完整备份到 `WBtool_backup/` 再删原文件；`recycle` = 移入系统回收站（默认） |
| `--yes` | 仅与 `--clean` 同用才真正执行；默认绝不移动 / 删除文件 |
| `--version` | 显示版本号 |

环境变量 `WORKBUDDY_PROJECTS_DIR`（优先级低于 `--projects`），灵动岛也认它。运行日志写到 `WBtool.log`（被 `.gitignore` 排除）。

### 灵动岛

| 参数 | 说明 |
|---|---|
| `--debug` | 打印启动分段计时（import / window / show / first frame / first data）、窗口几何、DPI、采样状态 |
| `--self-test N` | N 秒后打印状态并退出，用于无人值守冒烟（打包版从 `island-qt.log` 读结果） |

---

## 七、数据清理

报告底部「数据清理」面板会列出**符合清理条件**的 jsonl（相对路径 / 大小 / 最晚记录 / 行数）、可释放空间，以及受保护的活跃会话数。点「清除旧数据…」会弹出确认框。

### 两级删除范围（先保护、后清除，宁保守勿误删）

| 规则 | 说明 |
|---|---|
| ① 近 **7 天**内有过对话的会话 | **无论文件多旧，永不清除**（活跃工作优先保护） |
| ② 超过 7 天没有对话的会话 | **只清除全部数据都超过 N 天（默认 30）的整文件**；不逐行删，保留会话连续性 |
| 自动排除 | 今天仍在写入 / 被触碰的活跃文件一律排除；只处理 `*.jsonl` |

换言之，一个文件被判为「可清除」，当且仅当它**最近一次对话发生在 N 天之前**（此时它所有数据都早已超过 N 天，自然也满足「闲置 >7 天才考虑清除」）。

### 确认弹窗与两种去向（都可恢复）

弹窗里有一个**「备份数据」勾选框，默认不勾选**：

| 勾选？ | 去向 | 结果 |
|---|---|---|
| ✅ 勾选 | **备份模式** | 先完整备份到 `WBtool_backup/<时间戳>/`，再删原文件；随时可搬回 |
| ❌ 不勾选（默认） | **回收站模式** | 直接移入系统回收站；打开回收站即可还原 |

> ⚠️ 弹窗打开后，「确认清除」按钮会**禁用 3 秒**才可使用，避免误触。

### 为什么 HTML 里不能直接点按钮删

报告是 `file://` 静态页，**浏览器沙箱里的 JS 没有权限删除或写入本地文件**。所以弹窗确认后只会**生成并自动复制一条命令**，真正的清理由 exe 在命令行执行：

```bash
:: 1. 先看清单（只读，绝不移动文件）
WBtool.exe --clean-preview --days 30

:: 2. 回收站模式执行（默认；可恢复）
WBtool.exe --clean --days 30 --yes

:: 2'. 备份模式执行（先备份到 WBtool_backup/ 再删原文件）
WBtool.exe --clean --mode backup --days 30 --yes
```

> `--clean` **不加 `--yes` 会自动降级为只读预览**；`--clean-preview` 永远只读。
> 因为 exe 是无控制台的窗口程序，预览与执行结果都会生成 `WBtool_clean_report.html`
> 并自动打开浏览器，你能看到完整清单与去向（备份目录路径 / 回收站）。

### 备份 ≠ 永久删除

- **备份模式**：文件被**完整复制到**程序所在目录下的 `WBtool_backup/<时间戳>/`，并写 `manifest.json` 记录原相对路径，校验通过后**再删原文件**；需要时按 manifest 搬回即可。
- **回收站模式**：文件被移入**系统回收站**（借助 Windows `SHFileOperation`，零第三方依赖），不是永久删除，打开回收站就能还原；非 Windows 平台退化为移动到 `WBtool_trash/`。

⚠️ **但请注意**：jsonl 是 WorkBuddy 的会话日志，移走后对应的历史会话可能无法在 WorkBuddy 里恢复。执行前请先用 `--clean-preview` 看清清单，确认这些会话不再需要。

如果你用 `--projects` 或 `WORKBUDDY_PROJECTS_DIR` 指定了别的日志目录，请在命令后补上同样的参数（报告不内联你的绝对路径）。源码运行时把 `WBtool.exe` 换成 `python wb_usage_app.py`。

---

## 八、隐私说明（请认真看）

- 两个程序都**默认严格只读**：不联网、不上传，不修改 / 移动 / 删除任何原始日志；只有报告程序在你显式执行 `--clean --yes` 时才会把超期 jsonl 归档移走，且不是永久删除。
- 报告只内联统计字段；对话正文、推理文本、工具参数与输出、文件快照内容**一律不会**写进 HTML。灵动岛只把三格数字画在屏幕上，不落盘任何用量明细（偏好文件只存窗口坐标与置顶开关）。
- 报告生成的**每日快照**（`~/.wbtool/snapshots/`）同样只含统计数值、模型名与项目目录名，不含对话正文 / 推理 / 工具参数 / 会话 ID / 绝对路径；它只写在本机，不联网上传。
- 清理面板只列**相对路径**、大小与日期，不内联绝对路径或任何日志正文。
- ⚠️ 但报告里会包含**你的项目路径、模型名、会话标题和用量数值**，属于个人数据：
  - 仓库通过 `.gitignore` 排除 `WBtool_report.html`、`WBtool_clean_report.html` 与 `*.log`，**不会**上传；
  - 你分享自己生成的报告给别人前，请自行确认是否愿意公开这些信息。
- 本仓库不含任何真实用户数据，示例与文档均为脱敏内容。

---

## 九、常见问题

| 问题 | 答案 |
|---|---|
| 换台电脑还能用吗？ | 只要是 Windows、装了 WorkBuddy 且有会话记录，✅ 直接能用，路径自动适配当前用户 |
| 换电脑后没有 WorkBuddy 数据？ | ⚠️ 不会静默失败，会打开友好提示页，说明期望位置与如何指定目录 |
| 没装 Edge / Edge 在非标准位置？ | ✅ 自动尝试 Chrome / Chromium / Firefox，最后回退系统默认浏览器 |
| macOS / Linux 能用吗？ | ❌ exe 无法运行；源码可在其他平台跑，但不在支持范围 |
| 杀软报毒？ | PyInstaller 单文件版的通病（自解压行为像释放器）。目录版误报明显更少；本项目产物经 Defender 扫描无告警 |
| 胶囊一直是灰底？ | 截屏被安全软件/远程桌面禁止时自动降级为中性灰底，文字仍可读、不崩；放行后自动恢复毛玻璃 |
| 启动要 3 秒左右，能更快吗？ | 主要成本是 Qt 字体首次解析（本机 MiSans 约 0.9 s），与打包方式无关；用 `--debug` 可看分段耗时 |
| 双屏 / Windows 10 支持吗？ | 未做专门实测（开发机为 Win11 单屏）。缩放 67% / 100% / 125% / 150% / 200% 五档已验，胶囊逻辑尺寸恒定；多屏或 Win10 遇到问题请提 Issue |
| 怎么卸载？ | 删掉 exe（或解压目录）即可；想清干净再删 `%APPDATA%\WBtool-island\`（位置与置顶偏好）。程序不写注册表、不自启 |
| 胶囊数字和官网/报告不一致？ | 胶囊与报告共用内核，**逐项相等**，最多差一个刷新周期（10 秒）；与官网属于不同口径，见《四、HTML 报告》里的「数据口径」 |

---

## 十、打包与产物

```bash
python build.py            # 默认 == all：报告 + 灵动岛（两个都是 PyInstaller）
python build.py onedir     # 只构建报告目录版 zip
python build.py onefile    # 只构建报告单文件版 exe
python build.py island_qt  # 只构建灵动岛（exe + portable.zip）
python build.py island     # 只构建旧 Electron 版（已弃用，需 Node.js；产物名带 -legacy）
```

产物输出到 `release/`（不进 Git）：

| 产物 | 说明 |
|---|---|
| `WBtool-portable.zip` / `WBtool.exe` | 报告目录版 / 单文件版 |
| `WBtool-island.exe` | 灵动岛单文件版（PySide6） |
| `WBtool-island-portable.zip` | 灵动岛目录版（解压后 94.5 MB） |
| `WBtool-island-legacy.exe` / `-portable.zip` | 旧 Electron 版，仅 `build.py island` 产出，用于回退比对 |

前置条件：Windows + Python 3.8~3.13 + `pip install pyinstaller`；legacy 目标另需 Node.js / npm。**打灵动岛必须用装了 PySide6 的那个解释器**执行脚本（`pyinstaller_cmd()` 优先当前解释器，就是为避免误用 PATH 上另一套 Python）。中间产物放系统临时目录、结束后自动清理，不污染项目目录。详见 [build.py](build.py) 文件头。

---

## 十一、目录结构

| 文件 / 目录 | 备注 |
|---|---|
| `wb_usage_app.py` | **报告主程序**。四段结构：数据扫描层（含 `scan_old_files` 两级删除范围）、`HTML_TEMPLATE` 报告模板（含「清除旧数据…」确认弹窗）、**每日快照持久化**（`save_snapshot` 合并式写入 / `merge_snapshot` 历史补回，KB 级、离线、隐私）、超期日志清理（只读预览 / 备份 / 回收站，零第三方依赖）、入口与 CLI。 |
| `scanlib.py` | **共享解析内核**。解析 jsonl、判定时间戳单位、抽取可展示字段的唯一实现，报告与灵动岛共用；纯标准库、只读、不保留正文。改口径要同时改这两处消费方。 |
| `island_qt/` | **灵动岛（v2.0.0，PySide6 / Qt 6）**。`window.py` 透明无边框窗口 + 弹簧形变 + 毛玻璃合成 + 帧循环空闲停 + 拖拽/位置记忆/置顶/单实例唤回；`content/compact.py` 收起态三格数字；`content/detail.py` 展开态明细页（四列指标卡 / 额度曲线 / 带上下文进度的会话行）；`engine/glass.py` 截屏降采样模糊；`engine/anim.py` 弹簧积分；`engine/shape.py` 圆角路径；`ui/theme.py` 明暗双主题与字体；`scan_service.py` 10 秒增量扫描线程；`prefs.py` 偏好持久化；`single.py` 单实例管道；`tray.py` 托盘菜单；`main.py` 入口。另含 `_probe_b*.py` 量化验收脚本。 |
| `island/` | **旧版灵动岛工程（v1.3.0，Electron；2.0.0 起停用）**。仅保留源码用于回退比对，`python build.py island` 可打出 legacy 版。日常构建不需要它。 |
| `analysis/` | **移植与验收记录**（纯文档）：`porting-evaluation.md` 技术选型评估与「实际落地 vs 评估」对照、`porting-checklist.md` B0–B9 分批实作与逐条实测、`porting-baseline.md` 移植源 wisland 的快照指纹与《上游变动怎么同步》规程。 |
| `build.py` | **Windows 打包脚本**。报告与灵动岛走 PyInstaller；`island` 目标为旧 Electron 版入口（产物带 `-legacy`）。 |
| `assets/WBtool.ico` | **exe 图标**：WorkBuddy 官方 logo，11 种尺寸。 |
| `assets/WBtool-256.png` | **README 展示用小 logo**，由官方图标缩放而来。 |
| `assets/README.md` | **资源说明**：图标来源、版权声明、替换方法。 |
| `README.md` | 本文件。 |
| `CHANGELOG.md` | **版本变更记录**，当前 v3.2.0。 |
| `CONTRIBUTING.md` | **贡献指南**：本地运行、代码结构、验证清单、隐私红线、提交规范。 |
| `LICENSE` | **MIT 许可证全文**，Copyright (c) 2026 小柒。不含 `assets/` 图标的授权。 |
| `.gitignore` | 排除规则：按「个人隐私数据 / 二进制程序 / 构建产物 / 缓存 / 编辑器」分组，每条带注释。 |

> 仓库**只提交上表这些纯文本与图标文件**。exe、zip、生成的报告 / 结果页、日志、构建产物一律不进 Git；可执行程序通过 GitHub Release 分发。

---

## 十二、图标与许可

`assets/` 下的图标取自 WorkBuddy 官方应用资源，仅用于标识「本工具读取 WorkBuddy 的会话数据」。该图标**不在 MIT 许可证范围内**，版权归原权利人所有；本项目是非官方个人工具，与 WorkBuddy 官方无隶属或背书关系。如需商用或权利方有异议，请按 [assets/README.md](assets/README.md) 替换或移除图标，功能不受影响。

**作者：小柒** · 个人主页 [xiaoqilucky.com](https://xiaoqilucky.com) · GitHub [@Xiaoqi969](https://github.com/Xiaoqi969)

代码采用 [MIT License](LICENSE)。欢迎 Issue、建议与 Pull Request，贡献前请先读 [CONTRIBUTING.md](CONTRIBUTING.md)。版本差异见 [CHANGELOG.md](CHANGELOG.md)。

> 本项目与 WorkBuddy 官方无关，仅为读取本地日志的第三方统计工具。
