# wisland → WBtool 引擎移植清单（分批执行）

- **依据**：`analysis/porting-evaluation.md`（GO 结论、§七 落地顺序、§八 AI 工期校准）
- **移植范围**：用 wisland 的 Python + PySide6 灵动岛引擎，替换 WBtool 现有的 `island/`（Electron）
- **UI 来源（2026-11-14 用户决策）**：**视觉、尺寸、动效全部直接沿用 wisland**，不复刻 Electron 版的胶囊（原版 390×52 被判定偏大偏胖）。Electron 版只保留功能对照价值，`island.css` 不再作视觉参考。
- **不动的东西**：`wb_usage_app.py` 的报表逻辑、`build.py` 的主程序分支、README 里「两个启动器互不干扰」的定位
- **信息层级（2026-11-14 晚 用户决策）**：收起态**只显示三格数字**（Token / 积分 / 流速），**不展示进行中的会话**；会话明细一律放在展开态。
- **编写日期**：2026-11-14（同日按 UI 决策修订 B3–B6；晚间修订 B5 的收起态内容范围）

---

## 怎么用这份清单

1. **一次只做一批。** 每批是一个可独立运行、独立验收的单元，AI 执行通常 20–60 分钟，你每次只需花 2–5 分钟看结果。
2. **每批末尾有「停止点」。** 验收通过才进下一批；不通过就停在这一批继续修，绝不带着半成品往下走。
3. **新老并存，随时可退。** 新实现放在 `island_qt/`，旧 `island/` 原封不动。任何一批搞砸了，双击旧的 `release/WBtool-island.exe` 照常能用。（B9 之后正式名已归 PySide6 版，旧版产物名改为 `WBtool-island-legacy.exe`。）
4. **每批完成做一次本地 commit（不 push）。** 这样单批出问题可以单独回退；整条线做完再一起决定要不要正式发布。

> **实际执行与第 4 条不一致，如实记录**：B0–B9 全程没有逐批 commit，所有改动
> （`island_qt/`、`analysis/`、`scanlib.py`、`build.py`、`island/` 的 v1.4.0 拖拽改动、README/CHANGELOG）
> 一直留在工作区，最终在 B9 收尾、用户实测通过后一次性提交。
> 所以并不存在「逐批回退点」——真正的保险是物理隔离（新实现独立在 `island_qt/`，`island/` 未删除），
> 而不是版本历史。这条偏差留着，比事后假装按计划执行更诚实。

批次状态标记：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 已验收

---

## 批次总览

| 批次 | 名称 | 产出 | AI 耗时 | 需要你做什么 |
|---|---|---|---|---|
| B0 ✅ | 基线固化 + 环境准备 | `island_qt/` 空壳能弹出透明窗口 | 20 min | 看一眼截图 |
| B1 ✅ | **真实毛玻璃 PoC**（关键验证） | 胶囊背后是桌面模糊，不是灰底 | 40 min | 看截图判断「糊得像不像」 |
| B2 ✅ | 共享解析 `scanlib.py` + 扫描服务 | CLI 打印 summary JSON，与 Node 版数字一致 | 60 min | 看一眼数字对不对 |
| B3 ✅ | 窗口骨架 + 托盘 + 空闲停帧 | 胶囊常驻、托盘可用、空闲不烧 CPU | 60 min | 点一下托盘菜单 |
| B4 ✅ | 弹簧形变 + 三段式 | 点击展开/收起，节奏与现版一致 | 40 min | 点几下看手感 |
| B5 ✅ | 收起态内容（裁 compact、只换数据） | 34 高的胶囊 + 三格数字（**不含会话**） | 60 min | 与 wisland 原版对比 |
| B6 ✅ | 展开态明细页（继承 pages 卡片体系） | 640×自适应高度的卡片式明细 + 会话列表 | 70 min | 展开看一眼 |
| B7 ✅ | 交互与系统集成 | 拖拽记忆 + 置顶 + 减弱动效 + 单实例唤回 | 40 min | 逐项点一遍 |
| B8 ✅ | 构建改造（PyInstaller） | 新 exe 37.0MB，冷启 3.23s（旧版 105.2MB / 8.79s） | 40 min | 双击新 exe |
| B9 ✅ | 回归测试 + 文档 + 发布 | v2.0.0 可发布版本：DPI 1.0~3.0 全绿、降级不崩、文档同步、产物改名 | 60 min | 最终签收 |

> 合计 AI 计算量约 7–8 小时，但被切成 10 段。**你不需要守着一整天**——每批做完我会停下来等你确认。

---

## B0 · 基线固化 + 环境准备

`[x]` 2026-11-14 完成

**为什么先做**：wisland 是 4 天写完的高频迭代项目，本地快照又是非 git 目录（`git log` 报 `not a git repository`）。不先钉死基线，后面改到一半上游变了就没法对照。

**动作**
- 记录 wisland 快照指纹到 `analysis/porting-baseline.md`：`glass.py / anim.py / shape.py / island.py / compact.py` 的字节数与 mtime（当前实测：229 / 64 / 234 / 1347 / 719 行，全部 mtime `2026-11-10 14:37`）
- 安装 `PySide6-Essentials>=6.8`（**只装 Essentials**，不装 `requirements.txt` 里的 winrt / sherpa-onnx / fugashi 那堆业务依赖——我们只搬引擎）
- 新建 `island_qt/`：`main.py`、`window.py`、`engine/`、`content/`、`assets/`
- 在复制的 `glass.py / anim.py / shape.py` 文件头加 MIT 声明（保留 wisland 原作者版权，见评估报告风险 #4）
- `main.py` 起一个 390×52 的透明无边框窗口，2 秒后自动退出

**验收**
- [x] `python island_qt/main.py` 不报错，屏幕上出现一个透明小窗口
- [x] `python -c "import PySide6; print(PySide6.__version__)"` 输出 ≥ 6.8

**停止点**：PySide6 装不上（网络/编译）就先解决再往下。

**实际结果（2026-11-14）**
- 基线指纹已写入 `analysis/porting-baseline.md`（五文件行数/字节/sha256/mtime 全记录）。
- PySide6-Essentials **6.12.0** + shiboken6 6.12.0 安装成功。
- **踩坑**：清华镜像返回 `from versions: none`（未同步该包）；pypi 官方源实测约 12 KB/s（82 MB 需 2 小时）；**改用阿里云镜像 `https://mirrors.aliyun.com/pypi/simple/` 29 秒下完**。后续重装/CI 都用阿里云。
- 冒烟结果：`geometry=658,10 390x52 dpr=1.50`，胶囊圆角干净、文字居中、不抢焦点。
- **解释器有两份（2026-11-14 晚补记）**：B0 的 PySide6 装进了 WorkBuddy 自带解释器
  `C:\Users\lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe`；而用户在 PowerShell 里
  `python` 指向 `D:\python\python310\python.exe`（3.10.6），于是直接跑 `python island_qt/main.py`
  报 `ModuleNotFoundError: No module named 'PySide6'`。已用阿里云镜像把 `PySide6-Essentials 6.12.0`
  补装到 **python310**（3.10.6 64 位，abi3 轮子通用），现在两个解释器都能跑。
  **B8 打包请统一用 `D:\python\python310\python.exe`**（用户日常环境，PyInstaller 也只装这一份）。

---

## B1 · 真实毛玻璃 PoC（最关键，先跑最险的一步）

`[x]` 2026-11-14 完成 —— **真实模糊确认可用，移植的前提成立**

**为什么排第二**：这是整个移植的**唯一核心价值**，也是最可能失败的一环。GDI `StretchBlt` 在部分 GPU 驱动、HDR、或 Win10「禁止应用截屏」隐私设置下会返回空/黑。**先证伪，再投入后面 8 个批次。**

**动作**
- 复制 `wisland/wisland/ui/glass.py` → `island_qt/engine/glass.py`（整文件，229 行）
  - `grab_tiny()`：`StretchBlt(HALFTONE)` 把身后画面缩成 1/12 小图（原文件 69-93 行）
  - `exclude_from_capture()`：`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` 截屏时自排除（49-53 行）
  - `Backdrop`：后台线程 + `ready` 信号回主线程（96-201 行）
- 接进 B0 的空窗口：`paintEvent` 里用 `Backdrop.brush()` 画背景
- 胶囊内先放一句静态文字（「Token 57.4M」）验证前景与玻璃的层叠
- **必须验证降级路径**：`brush_for()` 返回 `None` 时填 `(128,128,128,200)` 灰底（原文件 208-218 行），不能崩

**验收**
- [x] 截图里胶囊背后能看出桌面的模糊色块（不是纯灰、不是纯黑、不是全透明）
- [x] 窗口静止 10 秒 CPU 占用 < 2%（`Backdrop` 有节流）
- [ ] 拖动窗口到另一个屏幕后，模糊背景跟着变（多 DPI 采样正确）

**停止点（重要）**：如果 `grab_tiny()` 一直返回 `None`，**停下来别继续**，回来报告。此时有三条路可选：(a) 保留灰底 + CSS 式渐变（等同现状，移植失去意义）；(b) 换 DXGI Desktop Duplication；(c) 放弃移植。这个决定必须你拍板。

**实际结果（2026-11-14）**
- **判定方法**（比"看着像"更硬）：探针 `island_qt/_probe_b1.py` 在胶囊正后方铺 8px 黑白高频细条纹 ——
  - 胶囊外：`0,0,0` / `255,255,255` 交替，条纹清晰；
  - 胶囊内：`82~90` 均匀灰，**极差 1**。
  - 高频细节被完全抹平 = 真实均值模糊生效，不是 CSS 渐变伪装的。
- 采样链路正常：`Backdrop.tiny` 40×9，`brush()` 返回有效 QBrush，未走灰底降级。
- **CPU 优化**：首版固定 2Hz 采样 → 7.2%（每次 StretchBlt + DWM 回读约 36ms）。改为「静止 0.5Hz / 移动后 0.5s 内 40Hz」→ **0.6%**。
- 未验证：多屏 / 跨 DPI 拖动（B1 阶段窗口不可拖，留到 B7 一起验）。
- 遗留：`_probe_b1.py` 不是产品代码，保留作后续批次的视觉验收工具。

---

## B2 · 共享解析 `scanlib.py` + 扫描服务

`[x]` 2026-11-14 完成

**为什么**：现在报表和灵动岛各写一套 jsonl 解析（`wb_usage_app.py` 1560 行 Python + `scanner.js` 250 行 JS），口径靠注释「严格对齐」维持。抽出共享模块后**永不口径分歧**，这是移植的第二个长期收益。

**动作**
- 从 `wb_usage_app.py` 抽出解析内核到 `scanlib.py`（**纯标准库，零依赖**）：
  - `norm_usage()`（113 行）、`bump()`（129）、`num()`（135）、`count_image_blocks()`（139）
  - `collect_all()`（242 行）里的 jsonl 逐行解析段（含时间戳 ms/s 判断、`fallback_proj`）
  - 保留 `PROJECTS_DIR` 环境变量覆盖行为（76 行）
- 让 `wb_usage_app.py` 改为 `from scanlib import ...`，**报表输出必须逐字节不变**
- 新增 `island_qt/scan_service.py`：`QThread` + 60s 定时，增量扫描（按文件 size/offset 只读新增字节），`ACTIVE_WINDOW_MIN=5`
- 输出契约**严格对齐** `scanner.js` 的 `summary()`（scanner.js 205-215 行）：
  ```json
  {
    "today": {"token": 0, "credit": 0, "in": 0, "out": 0, "ratePerSec": 0},
    "active": [{"name": "会话标题", "tokens": 0, "last": "HH:MM:SS"}],
    "files": 0,
    "updated": "HH:MM:SS"
  }
  ```
- **`ratePerSec` 的口径（2026-11-14 修正，两版同步）**：只算 **output token**，
  窗口 **15s**。原实现取 `nu.total / 60s`，把 prompt（且多为 KV cache 命中）
  也计入，agent 每轮工具调用重放 22 万上下文，实测显示 8,000~18,000/s，
  比真实生成速度高约 100 倍。改后实测 243/s，与 DeepSeek/ChatGPT/Claude
  客户端的 tok/s 可比。`today.token` 仍为 total（累计消耗，供成本口径使用），
  **不要**因为它看起来"大"而改成 output。

**验收**
- [x] `python wb_usage_app.py` 生成的报表与改动前对比，HTML 内容一致（除时间戳）
- [x] `python -m island_qt.scan_service --once` 打印的 JSON，四项 today 数字与 Node 版一致
- [x] 不动日志文件的情况下，第二次扫描（增量）耗时 < 50ms

**停止点**：数字对不上就停下来逐字段比对，不要靠「大概一致」过关。

**实际结果（2026-11-14）**

报表一致性用「固定输入」验证：把 `~/.workbuddy/projects` 快照到 `D:/tmp/proj-snap`（21 文件 / 227MB），
再用 `git show HEAD:wb_usage_app.py` 取改动前的版本，两边对同一快照各生成一份 HTML。
逐字符比对结果：**2,067,977 字节里只有 1 个字符不同**，即 `generatedAt` 的秒数（`21:05:25` vs `21:05:28`）。
调用次数与日志行数两边都是 8738 / 32214。

与 Node 版对齐（同一快照）：

| 字段 | Python | Node |
|---|---|---|
| token | 77225501 | 77225501 |
| credit | 121.65999999999995 | 121.66（CLI 侧做了三位舍入） |
| in | 76921869 | 76921869 |
| out | 303632 | 303632 |
| files | 21 | 21 |
| active | 2 条，名称/tokens 一致 | 2 条 |

性能：首次全量 1403 ms，第二次增量 **15 ms**（日志不变时只做 stat）。
增量正确性用临时目录测过四种情况：初始 2 行 220 → 追加整行 330 → 写入半行仍 330 → 补全该行 440，
末尾与「全新 Tracker 全量扫」结果一致（440），残行没有重复计数。

**顺带修了 scanner.js 的一个真 bug**：`_scanFile` 原先把偏移算成
`size - raw.length + complete.length`，把残行长度重复计入，导致 offset 越界（实测 460 字节文件算出 500）。
越界的后果是下一次 `size < offset` 被判定为「文件被截断」，触发一次 145MB 全量重扫——结果仍正确，
但每遇到一次残行就白烧一次全量。改成 `f.offset = size` 后偏移准确（460），增量结果不变。

**与清单原文的两处偏差**
1. 清单写的契约是 `"last": "HH:MM:SS"`，但 `scanner.js` 的 `summary()` 实际用 `localClock()` 返回 **HH:MM**。
   以代码为准实现 HH:MM，避免渲染层解析错位；`updated` 才是 HH:MM:SS。
2. `credit` 保留原始浮点，不做舍入——与 `scanner.js` 的 `summary()` 一致，舍入交给渲染层的 `toFixed(2)`。

---

## B3 · 窗口骨架 + 托盘 + 空闲停帧

`[x]` 2026-11-14 完成

**为什么**：`island.py` 有 1347 行，但 WBtool 只要其中约 40%。原样搬会把拖拽吸边、颈桥、宠物、媒体控件全带进来——评估报告明确说「**不要**原样搬」。

**动作**（从 `island.py` 抄骨架，逐段删）
- **先搬视觉底座（这是「好看」的来源，不是可选项）**：
  - `theme.py`（280 行）**整文件复制**：`G` 配色令牌类、`ui_font/icon_font` 字体栈（HarmonyOS Sans → MiSans → Segoe UI Variable → 微软雅黑）、`PALETTES`、`Theme` 类（跟随背景亮度的明暗切换）、`KIND_COLORS`
  - `widgets.py`（约 700 行）**按需取**：`rounded_pixmap` 等通用控件；媒体/歌词相关控件留到用到再取
- **保留**：
  - 窗口标志：无边框 / 透明 / `Qt.Tool` / `WA_ShowWithoutActivating`（217-222 行）
  - `PreciseTimer` 16ms 渲染循环（300-303 行）
  - `_needs_frames()` 空闲停帧（544-553 行）——决定 CPU 占用
  - `paintEvent` 的「阴影 + 玻璃 + 轮廓」三层（946-1028 行，其中 946-966 为主入口）
  - `_request_backdrop()` 的「收起态预截展开尺寸防首帧闪」（902-934 行）
  - 窗口容器尺寸 `WIN_W, WIN_H = 900, 680`（island.py:34，需容纳展开态 + 阴影）
- **删除**（WBtool 不需要，删掉能省 500+ 行）：
  - 拖拽 / 吸边 / `_nearest_edge` / `_gap_to` / `neck_path` / `drip_path`（461-538、656-671 行）
  - 鼠标穿透模式、全局热键、`ShellHook`、全屏自动隐藏（84-147 行整个类）
  - 多页栈 `show_page` / `_place_nav`（420-450、884-901 行）
  - 宠物形象、媒体播放控件（`_on_play_button` 1116-1120 行）
- 托盘：`QSystemTrayIcon` + 四项菜单（照搬 `app.py` 375-447 行）
- 单实例：`QLockFile`（`app.py` 118-122 行）

**验收**
- [x] 托盘图标出现，右键四项菜单齐全，点「显示/隐藏」有效
- [x] 胶囊常驻顶部居中，不抢焦点（点它时任务栏其它窗口不闪）
- [x] **空闲 30 秒**任务管理器 CPU < 1%，内存 < 120MB
- [x] `theme.py` 已接入：文字用 `ui_font()`、颜色用 `G` 令牌，**没有任何硬编码 RGB**
- [x] `window.py` 行数控制在 700–900（原 1347 行裁剪掉拖拽/颈桥/穿透/热键/多页/宠物/媒体）

**停止点**：CPU 降不下来先排查停帧逻辑，别急着进 B4。

**实际结果（2026-11-14）**

`window.py` 最终 **362 行**，比清单估的 700–900 少一半。原因不是漏做，是裁剪比预估更彻底：
拖拽/吸边/液桥/滴落/穿透模式/热键/ShellHook/全屏隐藏/多页栈/导航栏/宠物/媒体控件全部没进文件，
连 `anim.py` 的弹簧都还没接（B4 才用）。留下的只有：窗口标志、几何计算、16ms 循环 + 空闲停帧、
阴影/玻璃/轮廓三层绘制、背景采样、WM_NCHITTEST 穿透。

新增文件：

| 文件 | 行数 | 职责 |
|---|---|---|
| `island_qt/window.py` | 362 | 窗口本体（裁剪自 island.py） |
| `island_qt/tray.py` | 99 | 托盘图标 + 四项菜单 |
| `island_qt/ui/theme.py` | 279 | 整文件复制（273 行 + 6 行 MIT 头），sha256 与源一致 |
| `island_qt/main.py` | 123 | 入口：单实例 + 托盘 + 扫描线程装配 |

**踩到一个 DPI 坑（值得记）**：`WM_NCHITTEST` 的 `lParam` 是**物理像素**屏幕坐标，而 Qt 的几何全是逻辑像素。
第一版直接相减，dpr=1.5 下判定点被放大 1.5 倍（local 算出 877 而胶囊只到 590），于是**连胶囊正中的点击
都被判成穿透**，表现是「怎么点都没反应」。必须按 `glass.py` 同一套公式反算：
`逻辑 = 屏幕原点 + (物理 - 屏幕原点) / dpr`。

**穿透实测**（这是用户最初的痛点，单独验证）：窗口 900×680 覆盖胶囊外的空白区。
用 `mouse_event` 模拟真实点击 —— 点胶囊外（窗口内、胶囊下方 200px）时，岛**一条 WM_NCHITTEST 都没收到**，
说明系统在 alpha=0 的像素上直接跳过了这个 layered window；点胶囊正中时 `hit=True` 并正常进入 `mousePressEvent`。
两条路径都符合预期。

**不抢焦点**：点击胶囊前后 `GetForegroundWindow()` 都是同一个窗口（前台「红果短剧」未变），
`WS_EX_NOACTIVATE` + `WA_ShowWithoutActivating` 生效。

**性能**（30 秒空闲采样）：CPU 时间 **0.078s / 30s = 0.26% 单核**，私有内存 **92 MB**，进程数 1。
`_needs_frames()` 在没有交叉淡入时返回 False，16ms 定时器直接停掉，所以空闲是真的 0 帧。

**托盘**：图标出现在通知区（截图确认）；菜单四项与分隔线逐条核对无误 ——
`显示 / 隐藏灵动岛`、`临时提到最前`、`锁定置顶（始终最上层）`（带勾选）、`退出灵动岛`。
措辞与 Electron 版 `main.js:382-397` 完全一致，用户从旧版切过来不会有陌生感。

**顺手修的两个问题**
1. `glass.py` 的 `stop()` 只设标志不等待，退出时采样线程会 emit 给已销毁的窗口，抛
   `Signal source has been deleted`。加了可选参数 `stop(wait=True)`（默认行为不变），
   `closeEvent` 里用它，并在 `aboutToQuit` 显式 `win.close()`。现在退出 exit code 0、无异常。
2. 启动后主题要 7 秒才收敛（0.5Hz 采样 + EMA + 3 秒滞回），浅色桌面上头几秒会显示深色胶囊。
   改成「前 3 秒 5Hz、之后回落 0.5Hz」，实测 **5 秒内**判定正确。

---

## B4 · 弹簧形变 + 三段式

`[x]` 2026-11-14 完成

**为什么**：动效手感本身就是 UI 的一部分。既然整体改用 wisland 的视觉，弹簧参数也照抄它调好的实测值，不与 Electron 版混用。

**动作**
- 复制 `anim.py`（64 行，`Spring` 类：半隐式欧拉 + `dt` 钳制）
- 从 `shape.py` 只取三个函数：`body_path()`（52 行）、`deform()`（108 行）、`edge_corners()`（42 行）
  - **不调用** `neck_path()` / `drip_path()`（拖拽吸边专用，161 / 220 行）；两个函数**保留在文件里**（只删了调用），保持与上游逐行可比，见 `porting-baseline.md` §二
- 弹簧参数直接用 wisland 实测值（`island.py` 383-384 / 436-437 / 570-571 行）：
  - 展开：`sw.to(w, 420, 0.62)`、`sh.to(h, 420, 0.62)` —— w/h 同参数，整体弹开 + 轻微过冲
  - 收起：`sw.to(w, 440, 0.60)`、`sh.to(h, 440, 0.60)`
  - 形变中途调整：`460, 0.64`
  - **不要**再套 Electron 版的 190/110 刚度差 —— 那是「先横铺、再下落」三段式，不是 wisland 的手感
- 尺寸规格（`island.py:34-38`）：
  - 收起：**按内容测宽 × 34 高**（wisland `H_IDLE=34`，具体宽度见 B5）
  - 展开：**640 × H**（`EXP_W=640`、`PAD=12`、`NAV_H=36`）
  - 窗口容器 `WIN_W, WIN_H = 900, 680`，岛本体居中其中（容纳展开 + 阴影，不改窗口大小只改几何）
- 圆角：`body_path()` + `FILLET=13`，不再是 Electron 的「半圆 34 → 收敛 20」
- 打断续接：换目标不重置速度（`anim.py` 的 `to()` 天然支持）

**验收**
- [x] 点击展开：整体弹开、末端轻微过冲（**不是**「先横铺后下落」）
- [x] 展开中途再点一次，能立刻反向收回且不闪跳
- [x] 收起态尺寸恒定（宽度按内容固定），反复点 10 次不漂移、不变长

**停止点**：节奏不像就调 `k`，别改结构。

**实际结果（2026-11-14）**

`window.py` 从 362 行增到 **602 行**，新增内容只有形变（弹簧四件套 + 点击 + 两终态 + 脏矩形），
`anim.py` 在 B0 就已整文件复制（与源文件除编码声明外逐字节相同，sha256 `90766a2e…`）。

量化结果（`island_qt/_probe_b4.py`，125Hz 采样）：

| 指标 | 实测 |
|---|---|
| 展开 280×34 → 640×236 | 宽度峰值 **667**（过冲 26.8px / **4.2%**），约 420ms 到位、700ms 内静止 |
| 收起 640×236 → 280×34 | 无过冲以外的异常（下探由阻尼吸收），约 450ms 到位 |

| 中途反向（展开 300ms 时再点） | 换目标不重置速度，宽度继续冲到 667 后立即回落，**无闪跳** |
| 反复点 10 次 | 每次终态都是 `279.95 × 33.97`（弹簧 eps=0.05 的静止阈值），**无漂移** |
| 窗口位置 | 全程 `(404, -315)` 不变；本体上沿恒为窗口内 y=323 |
| 形变期 CPU | **20.2%** 单核（约 700ms，之后回落） |
| 展开态空闲 CPU | **0.39%**，16ms 循环 `timer_active=False` |

> B5 让收起宽度变成按内容算定的 **274**（三格、无会话），回归 B4 探针：过冲 27.3px（4.3%）、
> 10 次往返终态 `273.95 × 33.97`、窗口位置不变 —— 弹簧与终态判定未受影响。

**与清单原文的三处偏差（都以源码为准，不改清单结论）**

1. **收起参数用 460/0.64，不是 440/0.60。** 清单写的 440/0.60 是 `island.py:436-437` 的
   「切页」参数（`show_page`）；真正收回胶囊走的是 `_tick` 里 `not expanded` 分支的
   `460, 0.64`（`island.py:570-571`）。手感差异很小，但值要对。
2. **展开态圆角是 30，不是 FILLET=13。** `FILLET` 在 wisland 里是**液桥两侧的内凹圆角**，
   不是本体圆角；本体走 `base_r = min(30, h/2, w/2)`（`island.py:754-757`）。
   所以收起态是整颗药丸（h/2=17），长到 h≥60 后固定在 30 —— 这个切换由同一个公式连续产生，不需要额外插值。
3. **形变期不启用速度形变（`deform()`）。** wisland 的 `deform` 吃的是**整体位移速度**
   （拖拽/吸附），展开时是纯圆角矩形插值；照抄公式但给尺寸速度做形变会做出原版没有的怪味。
   函数已接好，`deform_gain` 留给 B7 拖拽时置 1.0。

另外补了两条清单没写但必须做的事：

- **窗口位置只算一次**（`_place_window`），形变过程中绝不 `move()`。B3 的写法是
  `_relayout()` 里按当前 h 反推窗口 y，展开时窗口会被逐帧上移 —— 分层窗口移动与重绘非原子，
  会重现 wisland 注释里警告的「内容错位 / 没有玻璃底的一帧」。现在窗口固定在
  `y = 可用区顶 + 8 - 323`，本体只向下长。
- **背景采样区取「当前形状 ∪ 目标形状」**：区域在整段动画里恒定，
  `Backdrop` 不会因为每帧变大就反复唤醒重新截屏（否则 45Hz 截屏会吃掉动画帧）。
  这也顺带实现了清单里「收起态预截展开尺寸防首帧闪」。

**视觉自检**（`--frames` 存 `%TEMP%/b4-*.png`）：60/130/220/320ms 四帧看下来，
圆角从药丸平滑收到 30、无撕裂、无文字拉伸；收起态文字固定在顶部原位淡出
（而不是跟着大框重新居中漂走 —— 这是把绘制区钉成「胶囊尺寸、上沿对齐本体」的原因，
等价于 wisland 里 compact 是独立子控件）。

**遗留**
- 展开态内容目前是占位版式（标题 + 分隔线 + 三列指标 + 一行说明），只为验证
  裁剪与淡入；B6 换成 `DetailPage` 的卡片体系后整体替换。
- `EXP_H = 236` 是占位值（= 66 + 170），B6 改成 `DetailPage.preferred_height()`。
- 点击只做了「位移 < 4px 算点击」，拖拽留在 B7。

---

## B5 · 收起态内容（wisland 排版语言，三格静态）

`[x]` 2026-11-14 完成（晚间按用户决策二次修订：删掉走马灯）

> **范围变更 1（2026-11-14 用户要求）**：原计划「按 Electron 版重写 compact」作废。既然整体改用 wisland 的 UI，这一批按 wisland 收起态的**排版语言**重做，数据换成 WBtool 的 Token/积分。
>
> **范围变更 2（2026-11-14 晚 用户要求）**：**收起态不展示进行中的会话，只在展开态展示**。
> 首版做的走马灯（`对话 <标题>` 在右区匀速左移、两端 alpha 渐隐、独立 30fps 节拍）整段删除，
> 收起态回到「三格数字恒常显示」，右区不再被会话抢占，改回常驻流速。影响见下面「实施要点」。

**动作**
- 新建 `island_qt/content/compact.py`（`class Compact`，156 行），**不照抄 719 行的 `compact.py`**：
  原文件里 `PetFace`（253 行）、媒体/歌词/字幕、`views` 切页在 WBtool 里全无对应物，
  留一堆 `return` 的死分支反而要维护。只留三样东西：
  - `paint()` 的分发骨架（clip + alpha 叠加，这里的 alpha 直接从弹簧值乘进颜色）
  - `_paint_idle` / `_paint_activity` 的排版手法：label 用次级色小字、数值用 DemiBold、**共用一条基线**
  - `_paint_dots` 的 3.4×1.7 小圆角块当分隔点 —— 不用「·」字符，字形度量随字体回退变化
- 宽度按 wisland 的测宽逻辑（`size_hint` 407-429 行）在**构造期一次算定**：
  `w = 16 + Token槽 + 点 + 积分槽 + 点 + 流速槽 + 14`，三槽都取样本串最大值 → **274px**，h 恒 34。
- 内容**恒定三格**：`Token` · `积分` · `流速`。`set_summary()` **故意不读** `active` 列表 ——
  会话数量变化既不触发重绘，也不改变一个像素。
- 数据从 `scan_service.summary` 消费；形变期间只存 `_pending`，落定后补发。

**验收**
- [x] 排版与 wisland 收起态同一套语言：11px 次级色 label + 13px DemiBold 数值、共用基线、圆点分隔
- [x] 宽度固定 274：注入 57.4M / 57.5M / 9.9M / 999.9K 四组数据逐像素比对，**「积分起点」以右像素完全一致**
- [x] 高度恒 34（B4 探针终态 273.95×33.97）
- [x] 有进行中会话时：`set_summary` 返回 `False`、画面 `diff=None`（会话进不了收起态）

**宽度复核（2026-11-14，用户问「274 是不是最短 / 999.9M·999.99·9999/s 是不是极限」）**

结论：**274 不变，但原来的算法有两个洞，已经补掉。** 详见 `_probe_b5w.py`（穷扫 + 断言）。

- **比例数字，不是等宽**：`1` 6px、其余 7px；字母 M 12px / K 9px / B 8px。
  所以「字符数一样就一样宽」不成立，旧的样本集把**宽数字配窄字母**（`999.9K`=42px），
  真实最坏 `999.9M`=**46px** 比槽宽 42px 宽 4px —— `100.0M` 起整个 M 域都会压到分隔点上。
  样本必须按「最宽数字 + 最宽字母」的最坏组合取，不能凭感觉挑一条。
- **流速 k 域 8 字符洞**：`v≥1000` 一律留一位小数，`100.0k/s~999.9k/s` 就是 8 字符 `999.9k/s`=**53px**，
  比槽宽 45.2px 多 7.8px，直接怼到右内边距上。现在给 `fmt_rate` 定下**输出 ≤7 字符**的契约：
  `≥100k` 只留整数、`≥1M` 折 `M/s`、`999.5k~999.9k` 进位成 `1.0M/s`（否则四舍五入出 `1000k/s`=47px）。
- **省出来的像素从哪来**：`SEP_GAP` 6→5（两个点共 4 处，省 4px）。
  重算：`16 + 79 + 13.4 + 67 + 13.4 + 71.2 + 14 = 274.0` —— **宽度一个像素没变，槽宽全部按真实最坏留足**。
- 用户点名的极限组 `999.9M · 999.99 · 9999/s`：实占 271.8px，余 **+2.2px**（流速显示为 `10.0k/s`）。
  再往上一档 `999.9B · 999.99 · 1.0M/s` 占 264.8px，余 +9.2px —— 格式化器能输出的任何组合都放得下。
- 穷扫（`Token` 30970 种 / `积分` 109990 种 / `流速` 11894 种）逐条断言：**零溢出**，三格余量 +0.0 / +0.0 / +0.2px。
- 「还能更短吗」：纯结构性再收（内边距、点距、label 间隙）最多到 **268px** 且会更挤；
  要到 252 以下必须牺牲语义（`Token`→`T`、砍小数位、三段并两段）。**274 是「语义不降级」下的合理下限。**

**实测（`_probe_b5.py`）**
- 布局：`width=274  x_credit=92.4  x_rate=172.8  baseline=22.5  label_h=14  value_h=17`，内沿 260
  （`x_credit` 原为 90.4，按真实最坏把 Token 槽加宽 4px、分隔点收窄 1px 后右移到 92.4；`x_rate` 未动）
- 不抽搐：四组数据差异包围盒全部落在 Token 槽内（最右 90.5 逻辑px，未越过第一个分隔点的左沿 98.7），
  「积分」「流速」两格像素零位移
- 会话隔离：只改 `active` 时 `set_summary=False`、像素级 `diff=None`；改数值才返回 `True`
- CPU：静止 **0.00%~0.52%**，`anim_timer=False`（16ms 循环彻底停），有会话时也一样

**实施要点（保留下来给 B6/B7 参考）**
- **静止态背景缓存**：阴影（3 层宽描边）+ 玻璃 + 轮廓合成到一张 QPixmap，贴图 0.05ms/帧。
  实测这三层是单帧最贵的部分（阴影单独 **0.65ms/帧**，占 3/4）。形变 / 背景交叉淡入期间不走缓存
  （每帧几何都变，缓存反而更贵）。
- **走马灯删除后的收益**：首版滚动要 1px/帧重绘，实测 3.12% CPU 常驻、还要一个独立 30fps 计时器；
  现在收起态只有一种静态画面，全程序只剩一个 16ms 循环，落定即停。
- **截图别用 `win.grab()` 整窗再裁**：分层透明窗口上整窗抓取拿到的是不透明占位图，裁出来纯黑。
  要按逻辑坐标 `win.grab(rect)`。这条踩过一次，差点误判成「画崩了」。

**遗留**
- 会话标题只在展开态消费；标题取自 `scan` 里的首条 user 消息，可能偏长，截断策略在 B6 定。

---

## B6 · 展开态明细面板

`[x]` 2026-11-14 完成

> **实作说明（与本节初稿的差异）**：初稿写的是「继承 `Page` + `Card` 控件树」。实际做成了
> **单 QPainter 合成**（`content/detail.py`，`class DetailPage`）。原因：我们的窗口是一张自绘的
> 透明分层表面，背景还有静止缓存；塞进子控件树就要每帧 `setMask()` 跟形状、还要处理透明子控件
> 的单独重绘 —— wisland 自己在 `_set_content_opacity` 里就因为「有内容没玻璃底」放弃了
> `QGraphicsOpacityEffect`。**视觉语言照抄 `widgets.py`**（`Card` 圆角 18、`theme.card()` 极淡白底、
> 无描边无分割线、Label 三档文字），只是把卡片和行画出来而不是摆控件。

**动作**
- 新建 `island_qt/content/detail.py`（239 行）：头部（标题 + 「流速」药丸）→ 指标卡 → 会话卡 → 脚注
- 指标卡四列：**Token 合计 / 输入 / 输出 / 积分**（收起态只有合计，展开才看得到 in/out 拆分）
- 会话卡：标题（可省略）+ 当日 token + 最后活跃时间；**最多 5 行**，超出折成「还有 N 个会话」
- 高度自适应：`preferred_height()` 由行数算出，窗口只调高度弹簧目标（`island.py:444` 的做法），
  并用 `EXP_H_MIN/MAX = 200/640` 夹住，内容再少不留空壳、再多也不顶出屏幕
- 内容裁剪沿用 `p.setClipPath(本体轮廓)`（等价于 `island.py:854` 的 `setMask()`），
  淡入沿用 B4 的 `content_a`（形状到位后 700ms 淡入）

**验收**
- [x] 展开后卡片风格与 wisland 原版一致（圆角 18、留白 14、无描边无分割线）
- [x] 明细完整显示，四角不溢出胶囊（内容画在 `clipPath` 内）
- [x] 会话数 4 → 6 时高度平滑增长：304 → 348，单帧最大步进 **7.57px**、峰值过冲 **+3.26px**、**315ms** 到位
- [x] 会话列表为空时显示「暂无进行中的会话」+ 计数「0 个」，卡片高度 238 不塌
- [x] 明细里每个数字都能和报表 HTML 对上（同一 `scanlib`，逐项相等）

**实测（`_probe_b6.py`）**
- 高度：n=0/1 → **238**；n=3 → 282；n=5 → 326；n=6 与 n=10 都是 **348**（5 行 + 溢出提示封顶）
- 展开 640×304（4 会话）、收起 274×34；展开态静止 CPU **0.00%**、`timer=False`
- 对账：`158,817,880 / 输入 157,909,815 / 输出 908,065 / 积分 216.86`，与 `wb_usage_app.collect_all()`
  的今日聚合逐项相等（1112 条记录）

**踩到的一个坑**
- 首版 `_sync_exp_height()` 在**收起态**也把 `sh` 弹到目标高度（想「提前备好」），结果胶囊
  当场长成 304 高。收起态的真值只能是 34：收起时只记 `_exp_h`，几何一个像素都不动。

**探针自身的一个坑（2026-11-14 记）**
- `_probe_b6.py` 的展开是**真实鼠标事件**（`mouse_event` 点屏幕坐标），依赖当时前台窗口与
  光标位置。若刚跑完另一个 GUI 探针、有窗口压在胶囊上，点击会落到别处，表现为「高度 34 → 34、
  0ms 到位」的假失败。连跑 3 次均正常（304→348 / 315~319ms / 过冲 +3.3px）即可排除。
- 这只是探针的脆弱点，不是应用缺陷：直接调 `win.expand()` 不受影响（B7 的 `[F] reduced` 走的就是这条路）。

**遗留**
- 会话标题取自 `scan` 的首条 user 消息，长标题走 `elidedText` 省略；要「悬停看全名」得等 B7 加交互。
- 面板里目前没有可点的东西（不翻页、不跳转报表），B7 再决定要不要给卡片加 hover。

---

## B7 · 交互与系统集成

`[x]` 2026-11-14 完成

> **与初稿的四处偏离**（都是实测撞出来的，不是偏好）：
> 1. **置顶不用 `setWindowFlags`**。Qt 在 Windows 上改窗口标志会销毁并重建原生窗口：
>    backdrop 的 `hwnd` 失效（玻璃底变灰）、`WS_EX_NOACTIVATE` 丢失（点一下就抢焦点）、
>    位置和内容全要重来。改成 `SetWindowPos(HWND_TOPMOST / HWND_NOTOPMOST)` 只改 z 序。
> 2. **位置存的是「本体左上角」，不是窗口坐标**。容器 900×680 而胶囊只有 274，
>    存窗口坐标换个屏幕尺寸就飞出界。所幸 Electron 版窗口 == 本体，语义天然一致 ——
>    `island-prefs.json` 可以直接复用，用户从旧版切过来还在原地。
> 3. **单实例用「连接即信号」**，不等 payload。Windows 命名管道上实测：`newConnection`
>    触发时 `readAll()` 还是空的，数据要等下一轮事件循环。「读到 show 才唤回」会漏。
> 4. **拖拽时采样区放大到整屏**。采样区跟着窗口走的话，每移 16px 就要重新截屏（引擎限
>    45fps），拖快一点玻璃底会糊在上一格；放成整屏就只剩一个区域，一次采样够全程用，
>    模糊小图才 160×90，比反复截小区域还便宜。

**动作**
- 单击展开/收起：位移 < `CLICK_SLOP=4px` 算点击（同 `island.js` 的拖拽阈值），越过即转拖拽
- **拖拽移窗**：整颗胶囊可拖（按本体路径命中，阴影区不响应）；抓起来时若展开则先收回胶囊
- 拖拽按「光标 − 按下偏移」定位，胶囊相对光标不滑；位置按 `clampPos` 夹回屏内
- 松开写 `%APPDATA%/WBtool-island/island-prefs.json`（与 Electron 版同一个文件、同一组键），
  退出时再写一次
- 置顶切换走 `SetWindowPos`，托盘勾选状态从 prefs 恢复，切换即落盘
- 减弱动效：读 `SPI_GETCLIENTAREAANIMATION`（Windows「辅助功能 → 视觉效果 → 动画效果」，
  Electron 的 `shouldUseReducedMotion` 同源），`WM_SETTINGCHANGE` 时热更新
- 单实例：`QLockFile` 判重（权威）+ `QLocalServer` 唤回（把「显示并提到最前」发给活实例）

**验收**
- [x] 拖到屏幕任意角落都不丢，重启后回到原位
- [x] 拖开后能点到下面的浏览器标签页（原位置 `WindowFromPoint` 已不是本窗口）
- [x] 勾掉「锁定置顶」后会被其它窗口盖住，勾回来恢复
- [x] 开两个实例，第二个自动退出并唤回第一个

**实测（`_probe_b7.py`，真实鼠标事件而非合成 Qt 事件）**
- 拖拽：真鼠标拖 +320,+200 → 本体位移 **+320,+200**（零误差），拖拽中 `dragging=True`
- 夹边：拖出屏幕后本体 `-137,-8`，落在允许区间 `x[-194,1627] y[-8,979]` 内，屏内仍可见 137×26
  （左上角贴边时按 Electron 规则允许出顶 8px）
- 记忆：存盘 `717,60` → 关窗 → 重建窗口读到 `717,60`（偏差 0）
- 点击：原地按下松开 → `expanded=True`，640×238（没被拖拽吞掉）
- 置顶：`WS_EX_TOPMOST` True → **False**（关闭）→ **True**（恢复）
- 减弱动效：`expand()` 一步到 640×238、`collapse()` 一步回 274×34，各 **0.10ms**，`anim_timer=False`
- 单实例：进程内唤回投递成功；另起子进程（真实第二实例）退出码 0，本进程收到信号 2 次
- 真实双实例：第二个 `python island_qt/main.py` 打印「已唤回运行中的实例」并自行退出
- 拖拽期 CPU **20.4%**（2.2s 连续拖动）：成本在「移动分层窗口 + 每帧重画」，属于系统开销；
  松手后立刻回到 0%（16ms 循环停）

**实施要点（踩过的坑）**
- **拖拽是「窗口位置只算一次」这条铁律的唯一例外**：形变中绝不移动窗口（移动与重绘非原子），
  但拖拽本身就是移动 —— 所以拖拽前先 `collapse()`，让形状在拖拽期间不再变化；拖拽时也不走
  背景缓存（缓存键含窗口位置，每帧都会 miss，直接画更快）。
- **探针里别用 `win.grab()` 整窗抓取**：分层透明窗口上拿到的是不透明占位图（裁出来纯黑）。
  按逻辑坐标 `win.grab(rect)` 才对 —— 这条 B5 就踩过，B7 又差点复现。
- **`child.wait()` 会冻结事件循环**：单实例探针里 wait 子进程期间 `newConnection` 排不上队，
  表现为「明明投递成功却收到 0 次信号」。wait 返回后再让循环转 200ms 才读计数。
- **`QLocalSocket` 连上不等于服务端已 accept**：`listen()` 之后要先进一次事件循环，
  同一回调里立刻 connect 会「连得上但服务端永远收不到 `newConnection`」。

**遗留**
- 不支持多屏之间按 DPI 重算缩放（拖到 150% 与 100% 屏之间，胶囊按逻辑像素等比走，
  视觉大小会变 —— wisland 也一样，暂不处理）。
- 拖拽没有 wisland 的吸边（`neck_path` / `drip_path`）与液滴形变，按清单是刻意不做的。

**移植后调整（2026-11-15，用户实测后决定）**
- **左键单击托盘图标 = 临时提到最前**。原行为是「显示 / 隐藏」切换（与 Electron 版
  `island/src/main.js:410` 完全一致），用户测过多日后认为提到最前更常用，遂改。
- 菜单里的「临时提到最前」随之下线，避免同一功能两个入口：菜单由 4 项变 3 项
  （显示/隐藏、锁定置顶、退出）。tooltip 补一行「单击提到最前」帮助发现。
- **单击不会丢唤回能力**：`bring_front()` 本身就是「隐藏则先 `toggle_visible()`，再 `raise_()`
  并按需补一次 `SetWindowPos`」。实测：手动隐藏后单击 → `visible=True/_visible=True`；
  可见时再单击 → 保持可见（不再 toggle）；`Context` 与 `DoubleClick` 均不触发。
- 顺带消掉一个老毛病：原先双击托盘 = 两次 `Trigger` = 隐藏→显示闪一下；改后两次都只是
  「提到最前」，双击不再有视觉跳变。

---

## B8 · 构建改造（PyInstaller）

`[x]` 2026-11-14 完成

**动作**
- `build.py` 增加 `island_qt` 目标：PyInstaller onedir + onefile
  - 隐式导入：`PySide6.QtCore` / `QtGui` / `QtWidgets`
  - Qt 插件：确保 `platforms/qwindows.dll`、`styles`、`imageformats` 被收集
  - 排除：`PySide6.QtWebEngine*`、`Qt3D*`、`QtCharts`、`QtMultimedia`（体积大头）
- **保留** `island` 目标（Electron）不删——直到 B9 验收通过，双轨并存
- 产物命名区分：`release/WBtool-island-qt.exe`（新版）vs `release/WBtool-island.exe`（旧版），避免覆盖导致无法回退
  - **B9 收口后改名**：正式名 `WBtool-island.exe` 归 PySide6 版，旧 Electron 版让位成 `WBtool-island-legacy.exe`（理由：升级用户手上的下载链接不能变，且 `all` 模式不再依赖 Node）

**验收**
- [x] 新 exe 双击能启动，胶囊与开发模式一致
- [x] 体积对比记录：PySide6 版 **37.0MB** vs Electron 版 105.2MB
- [x] 冷启动时间对比：PySide6 **3.23s** vs Electron **8.79s**

**实作（`build.py island_qt`，用 `D:/python/python310/python.exe` 执行）**

产物与体积（同一台机器、同一把尺子）：

| 形态 | PySide6 | Electron | 变化 |
|---|---|---|---|
| 单文件 exe | **37.0 MB** | 105.2 MB | **−64.8%** |
| 目录版 zip | **37.0 MB** | 146.0 MB | −74.7% |
| 解压后占用 | 95 MB | 237.7 MB | −60% |

冷启动（`_probe_b8.py`：CreateProcess → **第一个可见顶层窗口**，各 3 次取中位）：

| 形态 | PySide6 | Electron | 结论 |
|---|---|---|---|
| 单文件（含自解压） | **3.23s**（3.21/3.21/3.24，首次冷盘 7.2s） | 8.79s（8.62/8.79/9.36） | **快 2.7 倍** |
| 应用本体（两边都解开 zip，不算自解压） | 1.61s（1.56/1.61/2.00） | 1.25s | 慢 0.36s |

> **两个数为什么要分开报**：单文件启动的大头是自解压（Qt 解 37MB、Electron 解 105MB），
> 比它其实是在比压缩率；应用本体的差距才反映引擎本身。结论是「本体 Qt 略慢 0.36s，
> 但端到端快 5.5s」—— 用户感知的是后者。

**Qt 本体那 1.6s 花在哪（`window.py` 构造内外逐段计时）**
- `Compact()` **969ms** —— 几乎全是 Qt 字体引擎的首次度量（第一次 `horizontalAdvance`
  单独就要 474~982ms，之后再量是 1µs）；`ui_font()` 本身 0.1ms、`QFontMetrics` 0ms。
  这是 DirectWrite 字体库初始化，与打包无关，开发态一样慢。
- 首次全量扫描 **1754ms**（24 个文件、增量读）—— 跑在 `ScanWorker` 线程里，不和首帧阻塞，
  但会争 GIL。**B9 可优化点**：把 `worker.start()` 推迟到首帧之后（`QTimer.singleShot(150, ...)`），
  胶囊先出来、数字后到，观感更接近 Electron 版。本轮不动，留作后续。

**三个打包坑（都踩过）**
1. **`pyinstaller_cmd()` 必须先试当前解释器**。本机 PATH 上的 `pyinstaller` 属于 3.13 那套，
   打在 3.10 上的包会缺 PySide6，双击才报 `ModuleNotFoundError`。改成「当前解释器 → PATH → Scripts」。
2. **`ELECTRON_RUN_AS_NODE=1` 会让 Electron 变纯 Node**（WorkBuddy / VS Code 这类宿主会注入）。
   带着它启动，`electron.exe` 不初始化 Chromium，直接当 node 跑 `main.js`，`app` 是 undefined →
   秒退。表现极具迷惑性：旧版 portable 包「双击没反应」、TEMP 里连解包目录都没有，看着像包坏了。
   `_probe_b8.py` 里的 `_child_env()` 专门剥掉它和 `NODE_OPTIONS` —— **不剥，Electron 那列一个数都测不出来**。
3. **冻结态没有控制台**：`--windowed` 把 `sys.stdout` 置 `None`，`print` 静默丢弃。main.py 加了
   `_redirect_stdio_if_frozen()`，冻结时把 stdout/stderr 落到 `%APPDATA%/WBtool-island/island-qt.log`
   （行缓冲）。没有它，`--self-test` 在 exe 里等于没输出。

**其他实现细节**
- 排除表按「装了但没用」逐条列（Qml/Quick 全家、Designer/UiTools/Help/Test、Sql、PrintSupport、
  Svg、OpenGL、DBus、Xml、Concurrent、LabsStyleKit + 完整版才有的 WebEngine/Multimedia/Charts/3D/Pdf），
  不写通配；本机只装 Essentials，所以省下的主要是不被静态分析拉进来的模块。
- `--paths` 同时给 ROOT 与 island_qt（`prefs`/`window` 在同目录、`scanlib` 在父目录）；
  `--add-data assets/WBtool.ico;assets` —— tray.py 用 `__file__.parent.parent/assets/`，
  冻结后 `__file__` 落在 `_MEIPASS/island_qt/`，图标必须落到 `_MEIPASS/assets/`。
- 单实例锁**不会**被强杀搞坏：QT 的 `QLockFile` 即便 `setStaleLockTime(0)`，锁里记的 pid 已死时
  仍按 stale 处理。实测「杀光两个进程 → 锁文件还在 → 下次启动照常起来」（日志有新的 frozen boot 行）。
  注意 onefile 是**双进程**（引导器 + 子进程，同名），任务管理器里要结束整个进程组。

**停止点**：若 PyInstaller 打包后 Qt 起不来（常见于插件缺失），停在 B8 修，别动 B9。

---

## B9 · 回归测试 + 文档 + 发布

`[x]` 已完成（2026-11-14）

**动作**
- 回归矩阵：
  - 100% / 125% / 150% / 200% DPI
  - 单屏 / 双屏（含不同 DPI 混合）
  - Win10 22H2 / Win11 24H2
  - 截图权限受限场景（Win10 隐私设置关闭截屏）→ 灰底降级是否正常
  - 杀软误报检查（对比 Electron 版）
- 文档同步（**同一次提交内完成**）：
  - `README.md`：技术栈从 Electron 改为 PySide6，更新构建前置条件（不再需要 Node/npm）
  - `CHANGELOG.md`：新增版本条目，说明「引擎替换 + 真实毛玻璃 + 工具链统一」
  - `analysis/porting-evaluation.md`：末尾补一节「实际落地结果 vs 评估」
- 版本号：`1.4.0` → `2.0.0`（引擎层完全替换，属于破坏性变更）
- 旧 `island/` 归档到 `island-legacy/` 或直接删除（你拍板）
  - **本轮处理**：暂不删、不改名，只把 `build.py` 的默认流程改成不再构建它（产物带 `-legacy`）。
    等你说「删」再动——删目录属于不可逆操作，不擅自做。

**验收**
- [x] 回归矩阵全绿（除「双屏 / Win10」本机无法覆盖，见表下注）
- [x] 文档里没有「Electron」残留描述（`grep -ri electron README.md CHANGELOG.md`）
      → 现状：README 已全量改写；CHANGELOG 仅历史条目（v1.2.0/v1.3.0）保留 Electron 字样，
        这是史实，不应抹掉；v2.0.0 条目已声明「引擎替换」，口径不冲突。
- [ ] 你实机用一天没有异常（人工项，待你观察）

### 实测（`_probe_b9_matrix.py` / `_probe_b9_cpu.py` / `_probe_b9.py`）

| 项 | 方法 | 结果 |
|---|---|---|
| DPI 1.0 | `QT_SCALE_FACTOR=0.667`（×系统 1.5 → dpr 1.0） | 窗口 900×680、本体 274×34，文字完整不裁 |
| DPI 1.5 | `QT_SCALE_FACTOR=1` → dpr 1.5 | 同上 |
| DPI 1.88 | `QT_SCALE_FACTOR=1.25` → dpr 1.88 | 同上 |
| DPI 2.25 | `QT_SCALE_FACTOR=1.5` → dpr 2.25 | 同上 |
| DPI 3.0 | `QT_SCALE_FACTOR=2` → dpr 3.0 | 同上，圆角与描边无变形 |
| 截图受限 | 进程内把 `grab_tiny` 打成永远返回 None | 降级为中性灰底（中心像素 214,214,214,248），文字仍可读，不崩、不全透明 |
| 扫描节拍 | 真实 `ScanWorker` 跑 70s | 7 次，相邻间隔恒为 **10.0s** |
| 常驻 CPU | 剔除首次全量后量 68s | **0.37%**（10 秒间隔 + 增量读，未因缩短间隔上升） |
| 双屏 / 混合 DPI | 本机仅 1 块屏（1707×1067 dpr1.5） | **未覆盖**，需实机增屏验证 |
| 杀软 | Windows Defender 签名 1.463.290.0 全盘扫描 `WBtool-island.exe` / `WBtool.exe` / `WBtool-island-portable.zip` | 三者均 **no threats**（0.9~2s 返回） |
| Win10 22H2 | 本机 Win11 24H2（26100） | **未覆盖**，代码路径无版本分支（GDI 截屏 + `SPI_GETCLIENTAREAANIMATION`） |

### 本轮同时修的三件事（属于 B9 的「发布前收口」）

1. **扫描间隔 60s → 10s**：Qt 版初版误写 60 秒，导致「流速」60 秒才动一次，相对 v1.3.0（`SCAN_MS=10000`）是功能退化。改回后实测稳态 CPU 0.37%，证明增量读确实增量。
2. **首份数据前不再显示 0**：扫描要 1.7s，这段时间显示 `Token 0 · 积分 0.00 · 流速 0/s` 会被当成今日真实用量。改为三格破折号占位（亮度 0.34，明确是「还在读」），首份数据到达即替换。
3. **产物命名归位**：`release/WBtool-island.exe` 从此指 PySide6 版；旧 Electron 版改名 `WBtool-island-legacy.exe`（仅 `build.py island` 产出）。README 的下载/构建/文件清单三处同步。

### 启动优化（本轮新增）

- **首次全量扫描推迟到首帧之后**：`IslandWindow.firstFrame` 信号 + 1.5s 兜底。A/B 实测（`_probe_b9.py`，同进程 5 次）首帧 123ms → **83ms**（省 40ms）；端到端冷启两次中位分别 3.03s / 3.22s，**差异在噪声内**，不宣称提速。真实收益是**语义正确**：胶囊先出来、数字后到，且扫描不再与绘制争 GIL。
- **启动分段计时**：`--debug` 或冻结态打印 `import / window / show / first frame / first data`。实测：开发态 import 259ms、window 1365ms（其中首次 `horizontalAdvance` **922ms**）、show 1433ms、first frame 1484ms、first data 3191ms；冻结态（exe）import 154ms、window 1548ms、show 1619ms、first frame 1675ms、first data 3502ms（PyInstaller 自解压的 ~1.4s 在进程外，不计入）。
- **字体成本归因**：`horizontalAdvance` 首次 922ms 与字族数量无关（1 族 533ms vs 5 族 564ms），真正原因是**命中了 MiSans**（本机装了该 CJK 字体，首次解析 0.6~0.9s；Segoe UI 同条件仅 29ms）。要再压只能改字体族优先级——**属视觉决策，本轮未动**，等你拍板。


---

## 附 A · 文件映射表

| 目标文件 | 来源 | 处理方式 |
|---|---|---|
| `island_qt/engine/glass.py` | `wisland/ui/glass.py`（229 行） | 整文件复制 |
| `island_qt/engine/anim.py` | `wisland/ui/anim.py`（64 行） | 整文件复制 |
| `island_qt/engine/shape.py` | `wisland/ui/shape.py`（234 行） | 只取 3 个函数，删颈桥/残滴 |
| `island_qt/ui/theme.py` | `wisland/ui/theme.py`（约 280 行） | **整文件复制**（配色/字体/明暗主题） |
| `island_qt/ui/widgets.py` | `wisland/ui/widgets.py`（约 700 行） | 按需取 `Card`/`Themed`/`vbox`/`rounded_pixmap` |
| `island_qt/window.py` | `wisland/ui/island.py`（1347 行） | 大改裁剪：留窗口/几何/玻璃/停帧/绘制 |
| `island_qt/content/compact.py` | `wisland/ui/compact.py`（719 行） | **裁剪**：删 PetFace/媒体/字幕/歌词/走马灯，改写 `_paint_idle` 为三格静态 |
| `island_qt/content/detail.py` | `wisland/ui/pages/base.py` + `home.py` | 继承 `Page`，抄卡片排版 |
| `island_qt/main.py` | `wisland/app.py`（编排范式） | 新建，服务换成单一 scan_service |
| `scanlib.py` | `wb_usage_app.py` | 抽出解析内核，报表改为调用它 |
| `island_qt/scan_service.py` | `island/src/scanner.js` | Python 重写，契约不变 |
| `build.py` | 现有 | 增加 PyInstaller island 目标 |

## 附 B · 必须搬过去的铁律（来自现版 Electron 实现，血泪教训）

1. **尺寸唯一真源**：窗口尺寸只读弹簧当前值，永不读回 `geometry()` 反推。
2. **水平锚点持久化**：形变中心只在「首次创建」和「拖拽到位」时写一次，否则逐帧 round 会累积成「每轮右移 1px」的漂移。
3. **拖拽用 `setGeometry` 显式带 width/height**：Windows 上 `move()` 会连带改尺寸（Electron 版曾经拖 40 帧从 390×52 涨到 418×80）。
4. **形变期间不刷新内容**，结束后补发，避免文字抽搐。
5. **两个合法终态**：收起（按内容测宽 × 34）与展开 640×H，中间态只由弹簧产生。
6. **不混用两套 UI 语言**：形状、圆角、字体、配色、动效全部来自 wisland；Electron 版的 `island.css` 只作功能对照，不作视觉参考。
7. **信息分层**：收起态只回答「今天用了多少、现在多快」（三格数字），**不塞会话、不滚动、不轮播**；
   要看细节就展开。收起态一旦会动，CPU 就下不来（滚动版实测 3.12% 常驻），而且它在屏幕顶端常驻，
   任何持续运动都会变成干扰。

## 附 C · 停工条件（出现这些情况就停下来问）

- B1 毛玻璃拿不到真实模糊（决定整个移植是否有意义）
- PySide6 在本机装不上或 Qt 无法创建透明窗口
- 单批实际耗时超过预估 2 倍
- 需要改动 `wb_usage_app.py` 的报表输出（会影响已有用户）
- 任何需要你审美/偏好判断的（字号、颜色、动效快慢）
