# 把 wisland 的灵动岛引擎移植到 WBtool 的可行性评估

- **分析对象**：`D:\Users\lenovo\Desktop\ALL\wisland`（移植源）× `D:\Users\lenovo\Desktop\ALL\WBtool`（移植目标）
- **分析日期**：2026-11-12
- **结论先行**：**可行（GO），但有条件。** 把 wisland 的"纯手工重建、零系统 compositor 依赖"的灵动岛引擎（PySide6 + GDI 毛玻璃 + 贝塞尔几何 + 弹簧物理）抽出来，替换掉 WBtool 当前基于 **Electron** 的灵动岛，技术上完全可行，且是三条可选路线里唯一能在 Win10/11 全版本拿到**真实背景模糊**且不依赖系统版本特性的方案。最大收益是「真毛玻璃 + 构建工具链统一回 Python」；最大代价是灵动岛从「零依赖前端」变成「必须随包携带 PySide6/Qt 运行时（约 40–80MB）」，并需重写 WBtool 专属的内容层、复用/移植 jsonl 扫描器。

> 说明：本评估按深度项目分析的方法论做（结论必须有代码证据、用对照表与映射表），但只聚焦「移植可行性」这一具体问题，不展开 wisland/WBtool 的完整四角度分析。

---

## 一、两套实现的本质差异（对照表）

| 维度 | wisland（移植**源**） | WBtool 现版灵动岛（移植**目标**，待废弃） |
|---|---|---|
| 语言 / 框架 | Python + **PySide6 (Qt6)** | Python 主程序（纯标准库）+ **Electron**（`island/`） |
| 窗口形态 | 无边框 / 分层 / 透明 `Tool` 窗口，全部自绘 | Electron `transparent:true` 透明窗口，HTML/CSS 绘制 |
| 玻璃质感 | **GDI `StretchBlt` 截屏 + 均值模糊 = 真实背景模糊** | CSS 渐变 + `inset` 描边**模拟**（明确说明「透明窗口无法用系统背景模糊」） |
| 形状几何 | 贝塞尔手搓：胶囊 / 颈桥 / 残滴 / 按速度形变 | CSS `border-radius`，由主进程弹簧每帧下发 `--h`/`--r` |
| 物理引擎 | `Spring` 类，半隐式欧拉 + 子步长防发散 | 三根独立弹簧 `w/h/m`，半隐式欧拉，`dt` 钳制 |
| 收起态内容 | **即时模式 QPainter 自绘**（`compact.py`，无子控件） | HTML/CSS/JS 渲染层（`island.js`） |
| 数据驱动 | 多个 Qt 服务发信号 → `app.py` 连线 → `island._kick()` | `scanner.js` 增量扫描 jsonl，每 60s 推一次 `summary()` |
| 托盘 / 置顶 | `QSystemTrayIcon` + `WindowStaysOnTopHint` + 常驻 | Tray + `alwaysOnTop` + `skipTaskbar`（默认锁顶隐藏任务栏） |
| 构建工具链 | PyInstaller | **PyInstaller（主）+ electron-builder（island）双工具链** |
| 运行时依赖 | 重（PySide6 + winrt/媒体等约 25 个包） | 主程序**零依赖**；island 需 Node/Electron |

**关键认知**：WBtool 的"灵动岛"目前是一个**独立的 Electron 应用**（`island/package.json` 的 `devDependencies` 含 `electron@^45`、`electron-builder@^26`），而 WBtool 的 Python 主程序 `wb_usage_app.py` 是「纯标准库、零第三方依赖、跑完即退」的报表生成器。两者通过 README 中「两个启动器互不干扰」解耦。因此移植 = **用 wisland 的 Python+PySide6 引擎替换掉 `island/` 这个 Electron 工程**，主程序 `wb_usage_app.py` 一行都不用动。

---

## 二、可复用部分（wisland 引擎，几乎「拿来即用」）

wisland 的灵动岛是一组**自包含模块**，与它的媒体/天气/翻译等业务服务通过信号解耦，所以只搬引擎、不搬业务是干净的。

| 模块 | 复用方式 | 证据（文件:行 / 函数） |
|---|---|---|
| `wisland/wisland/ui/glass.py`（整个文件） | **整文件复制** | `grab_tiny()` 用 `StretchBlt(HALFTONE)` 把身后画面缩成 1/12 小图（行 69-93）；`exclude_from_capture()` 用 `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` 截屏瞬间自排除（行 49-53）；`Backdrop` 后台线程 + `ready` 信号回主线程（行 96-201）。**这是本次移植的核心价值——真毛玻璃。** |
| `wisland/wisland/ui/anim.py` 的 `Spring` 类 | **整文件复制** | 半隐式欧拉 + `dt` 钳制防发散；`island.py` 的 `_tick` 用 `dt = min(1/30, max(1/240, …))`（行 556），与 WBtool 现有 `stepSpring` 思路一致。 |
| `wisland/wisland/ui/shape.py` | **只取 3 个函数** | `body_path()` 独立圆角矩形（行 52）、`deform()` 按速度/按压形变、`edge_corners()`。`neck_path`/`drip_path`（颈桥/残滴）是**拖拽吸边专用**——WBtool 固定顶部居中、不拖拽，**应丢弃**以减负。 |
| `wisland/wisland/ui/island.py` 的**窗口骨架 + 渲染循环** | **大改后复用** | 无边框/透明/`Tool` 窗口 + `WA_ShowWithoutActivating`（行 217-222）；`PreciseTimer` 16ms（行 300-303）；`_needs_frames()` 空闲停帧/降帧（行 544-553）；`_request_backdrop()` 毛玻璃采样 + **收起态预截展开尺寸防首帧闪**（行 902-934）；`paintEvent` 阴影+玻璃+轮廓+内容（行 946-1028）；DPI 多屏处理（`QScreen.devicePixelRatio()`，glass.py 行 143-147）。 |
| `wisland/wisland/core/config.py` + `app.py` 的**编排范式** | **范式复用** | `ctx.media.changed.connect(on_media)` → `island._kick()`（app.py 行 226-227）；`QSystemTrayIcon`（行 440-447）；`setQuitOnLastWindowClosed(False)` 常驻（行 114）；`QLockFile` 单实例（行 118-122）。WBtool 新建一个轻量 `app.py`，把「媒体/天气…服务」整体换成「一个 jsonl 扫描服务」。 |

> 注意：**不要**把整个 wisland `island.py`（1347 行）原样搬过去。它内含拖拽吸边、可穿透模式、热键、ShellHook、全屏隐藏、宠物小形象、多页面栈、媒体控件——WBtool 全都不需要。移植后目标文件应缩到约 600–800 行，只保留「窗口 / 几何 / 玻璃 / 空闲停帧 / 托盘 / 单击展开」这条主线。

---

## 三、必须新建 / 重写部分（WBtool 专属）

| 模块 | 做法 | 说明 |
|---|---|---|
| **jsonl 扫描服务** | 抽 `wb_usage_app.py` 的解析为共享模块 `scanlib.py`，包成 `QThread`/`QTimer`，每 60s 增量扫描并 `emit summary` | 好消息：`wb_usage_app.py` **已有完整 jsonl 解析口径**，且 `island/src/scanner.js` 注释明确「口径严格对齐 `wb_usage_app.py`」。最佳做法是把解析**抽成主程序与 island 共用的纯 Python 模块**（增量按字节偏移、`ACTIVE_WINDOW_MIN=5`、时间戳 ms/s 判断、`normUsage`、credit 取 `rawUsage.credit`），让报表与灵动岛**永不口径分歧**。数据契约（来自 `scanner.js` 的 `summary()`）：`{ today:{token,credit,in,out}, active:[{name,tokens,last}], files, updated }`。 |
| **收起态内容（`compact.py` 改写）** | 用即时模式 QPainter 自绘「今日 Token/积分 + 进行中对话走马灯」 | 路线 A（贴合 wisland）：数字用等宽数字防跳动（Qt `QFont` + `drawText`，参考 wisland `tabular-nums` 等价处理），走马灯每帧移动 x 偏移（参考 `island.js` `stepMarquee` 的 `0.6px/帧`）。路线 B（更省事）：用一个小 `QWidget` 内容层把 HTML/CSS 思路平移成 Qt Widgets。**推荐收起态用 A、展开态明细用 B**。 |
| **展开态明细面板** | 新建一个 `QWidget`（含网格/列表） | WBtool 只需**一个**明细面板（今日 in/out/合计 Token、积分、各进行中对话 token + 最后活跃时间）。复用 wisland 的「形状长到 ~70% 再显示内容、用 `setMask` 裁剪到形状」技巧（`island.py` 行 854-868），即可获得与现在 Electron 一致的「内容不溢出胶囊」效果。 |
| **三段式形变时序** | 沿用 wisland 思路（w/h 一起弹，靠刚度比自然涌现次序） | WBtool 现有卖点「小胶囊→横铺→下展」三段式，本质来自 `SPRING.expand` 中 `w.k=190 > h.k=110`（w 更硬、先到位，`island/src/main.js` 行 42-53）。wisland `expand()` 也是 `sw.to(w,420,0.62)` / `sh.to(h,420,0.62)`（island.py 行 383-387）同构。**直接沿用这套刚度比即可复现三段感**。 |
| **构建（`build.py` 改造）** | 删 `electron-builder` 分支，新增 PyInstaller 打包 island | 需处理 PySide6 隐式导入（`PySide6.QtCore` 等）与 Qt 插件 `platforms/qwindows`。WBtool 主程序已在用 PyInstaller，**工具链统一反而比现在更简单**（现在是双工具链）。 |
| **托盘右键菜单** | 照搬现有菜单项成 Qt 菜单 | 「显示/隐藏、临时提到最前、锁定置顶、退出」对应 wisland `build_menu`/`tmenu`（app.py 行 375-447），工作量小。 |
| **「减弱动效」** | 保留 | WBtool 现有 `prefers-reduced-motion`（island.js + CSS `@media`）；wisland 也有等效处理，需保留（弹簧直接落到终态）。 |

---

## 四、风险与不确定项

| # | 风险 | 等级 | 应对 |
|---|---|---|---|
| 1 | **毛玻璃在特殊环境失败**：GDI `StretchBlt` 从桌面 DC 截屏，在部分 GPU/驱动、HDR、或 Win10「不允许应用截屏」隐私设置下可能返回空/黑 | 中 | wisland 已有降级：`brush` 为 `None` 时填 `(128,128,128,200)` 灰底（`glass.py` 行 988）。保留并做专项测试。 |
| 2 | **wisland 无 git 历史**（此前分析确认：仓库非 git 或 0 提交），无法核对玻璃/几何/物理代码的迭代稳定性与已知 bug | 中 | 代码在 wisland 实际运行中、逻辑完整；移植后做一次 Win10/11 多 DPI/多屏回归即可。 |
| 3 | **打包体积**：从 Electron 换成 PySide6，体积更小还是更大？ | 低（偏收益） | Electron 单文件 portable 通常 100MB+（含 Chromium 子集）；PySide6 打包后约 40–80MB，且启动更快、内存更低、杀软误报更少（README 已指出 Electron 误报更多）。 |
| 4 | **许可证**：搬运代码是否合规 | 低 | wisland 与 WBtool 都是 **MIT**（`wisland/LICENSE`、`WBtool/LICENSE`）。可直接移植，但**必须保留 wisland 的 MIT 版权声明**在复用文件头。 |
| 5 | **中文渲染**：Qt 中文用系统字体（Microsoft YaHei），wisland 已用 `ui_font`/`icon_font`；需确保 PyInstaller 不丢字体 | 低 | Qt 自带字体回退，一般无虞；打包后抽查中文显示。 |
| 6 | **`WBtool_island.py` 源码缺失**：仓库里有编译产物 `WBtool_island.cpython-313.pyc` 但无 `.py` 源（`scanner.js` 注释却提到它） | 低（历史好奇） | 说明 WBtool 早期可能已有 Python island 启动器、后被 Electron 取代；本次等于**重新引入 Python 启动器**，与历史方向一致，非阻碍。 |

---

## 五、工作量估算

| 模块 | 来源 | 工作量 |
|---|---|---|
| `glass.py` | 复制 | 0.5 天 |
| `anim.py`（Spring） | 复制 | 0.5 天 |
| `shape.py`（body_path/deform/edge_corners，删颈/滴） | 复制+裁剪 | 0.5 天 |
| `island.py` 窗口骨架+循环+绘制 | **大改**（删拖拽/穿透/热键/多页/媒体/宠物，留窗口/玻璃/几何/空闲停帧/托盘钩子） | 3–4 天 |
| `compact.py` 改写（Token/积分 + 走马灯） | 重写 | 1.5–2 天 |
| 明细面板（Widgets） | 新建 | 1 天 |
| jsonl 扫描服务（抽 `wb_usage_app` 解析 + QThread） | 重构+新建 | 1.5 天 |
| `app.py` 编排（托盘/单实例/连线） | 新建 | 1 天 |
| `build.py` 改造（去 electron，加 PyInstaller island） | 改造 | 1 天 |
| 测试（Win10/11 多 DPI/多屏/截图权限/杀软） | 测试 | 1.5–2 天 |
| **合计** | | **约 12–14 人天 ≈ 2.5–3 周（单人）** |

> 若只追求「能跑 + 真实玻璃 + 基本三段形变」，可砍掉明细面板精致度与多屏边界打磨，压到 **约 8–10 人天 ≈ 2 周**。

---

## 六、决策矩阵（三条可选路线）

| 选项 | 描述 | 真实玻璃 | 构建复杂度 | 包体积 | 语言统一 | 工作量 |
|---|---|---|---|---|---|---|
| **A. 维持 Electron（现状）** | 保留 `island/` | ❌（CSS 模拟） | 高（双工具链） | 大（Chromium） | ❌（JS+Py） | 低（已有） |
| **B. 移植 wisland 引擎（本评估推荐）** | PySide6+GDI 替换 Electron | ✅ | 中（单 Python 工具链） | 小（Qt） | ✅ | 中（2.5–3 周） |
| **C. Electron + 系统亚克力** | 用 `window.setBackgroundMaterial('acrylic')` | ⚠️ 仅 Win11、版本相关 | 高 | 大 | ❌ | 中 |

**推荐 B**：它是唯一能在 Win10/11 全版本拿到**真实背景模糊**且不依赖系统版本特性的路径（WBtool README 已明确回避 Acrylic 之类系统特性），同时把工具链统一回 Python，契合 WBtool 的 Python 身份——与用户「可以舍弃 WBtool 原来的灵动岛设计思路」的授权完全吻合。

---

## 七、落地顺序建议

1. **最小 PoC**：PySide6 窗口 + `glass.py` + 固定胶囊 + 自绘「今日 Token」→ 先验证真实玻璃在目标机（含截图权限受限场景）可用。
2. **抽共享解析**：把 `wb_usage_app.py` 的 jsonl 解析抽成 `scanlib.py`，写 `ScanService`（`QThread`，60s 增量扫描，`emit summary`）。
3. **移植窗口骨架**：从 `island.py` 只留「窗口 / 几何 / 玻璃 / 空闲停帧 / 托盘」，删拖拽/穿透/热键/多页/媒体/宠物。
4. **改写内容层**：`compact`（Token/积分+走马灯）+ 明细面板，消费 `summary` 契约。
5. **改造构建**：`build.py` 去掉 `electron-builder`，加 PyInstaller island 目标；主程序保持零依赖不变。
6. **回归测试**：Win10/11 多 DPI/多屏/截图权限 + 杀软误报检查；保留 wisland MIT 版权声明。

---

### 附：核心代码证据索引
- wisland 真实毛玻璃：`wisland/wisland/ui/glass.py:69-93`（StretchBlt）、`:49-53`（自排除）、`:96-201`（后台线程+信号）
- wisland 窗口/空闲停帧/预截：`wisland/wisland/ui/island.py:217-222`、`:544-553`、`:902-934`
- wisland 编排范式：`wisland/wisland/app.py:114`、`:118-122`、`:226-227`、`:440-447`
- wisland 弹簧刚度比：`wisland/wisland/ui/island.py:383-387`
- WBtool 现有 Electron 岛：`WBtool/island/package.json:43-46`、`WBtool/island/src/main.js:42-53`（SPRING）、`WBtool/island/src/scanner.js:197-210`（summary 契约）
- WBtool 主程序零依赖：`WBtool/README.md:40`（纯标准库）

---

## 八、AI 全自动工期估算（2026-11-12 补充）

用户提供了 wisland 的真实仓库 `https://github.com/AsamiAkito/wisland`，据此重新校准工期。新增证据：

- **仓库极新且由 AI 写成**：`created_at = 2026-11-06`，首个代码提交 `2026-11-06T13:31`（"wisland：Windows 液态毛玻璃灵动岛"），末次提交 `2026-11-10`；整个仓库 **≤100 提交、4 天内密集成型**（page=1&per_page=100 已触达出生提交）。**几乎每个提交都带 `Co-Authored-By: Claude Opus 5.5`**——即 wisland 本身就是 **Claude 写的**，89 star、7 fork、MIT、2 open issues。
- **这给工期一个硬校准锚点**：一个 AI 用约 4 天、~30 次提交，从零造出**整个 wisland**（引擎 + 媒体/天气/翻译/剪贴板/股票/控制/实时字幕等服务 + 安装脚本）。而本次移植只是「复用引擎 + 写 WBtool 专属内容层 + 打包」，范围约为造整个 wisland 的 **30–40%**，且最难的那 60%（引擎）已经写好、且带中文注释、AI 极易读懂。
- **可直接搬运 wisland 已调好的常量**（弹簧 k/d、模糊半径、颈桥几何）作为默认值，把"调参迭代"这一最耗时的环节大幅压缩——进一步压低工期下界。

### AI 自动化的能力边界（决定工期的核心）
- **代码抽取 + 改写 + 打包脚本**：完全可自动化，且很快（读 4 个可复用文件→裁剪→写新内容层→PyInstaller 配置）。约 **1–2 小时** agent 计算量。
- **构建 + 导入冒烟测试**（headless 跑 PyInstaller、确认产出 exe、能 `import` 不起异常）：可自动化，约 **30–60 分钟**。
- **运行时校验 + 视觉/物理调参**（玻璃是否真糊、置顶、DPI、颈桥形态、弹簧手感）：**必须看到渲染窗口**才能判断。自主 agent 若在 headless 环境（看不到 Windows GUI）则无法自评这部分；即使能截图桌面对话，"像不像苹果灵动岛"的最终审美判定仍属人眼。

### 三种场景下的工期

| 场景 | 条件 | agent 自主墙钟 | 人类还需投入 | 到"可发布"总墙钟 |
|---|---|---|---|---|
| A（最佳） | agent 能跑 exe + 截图桌面 + 自动迭代 | **约 1–2 天** | 最终审美签收 ~2–4 小时 | **约 1.5–2.5 天** |
| B（典型，headless） | agent 产出可构建/可导入代码+安装包，人类做全部运行校验与调参 | 几小时 | **约 2–3 天**（装/跑/截图/调参/重打包） | **约 3–4 天** |
| C（对比：纯人） | 见前文 §五 | — | 12–14 人天（2.5–3 周） | 2.5–3 周 |

> 结论：**AI 把"写代码"的成本打到接近 0，但打不掉"看效果、做判定"的成本**。所以真实工期下界不是编码时间，而是"运行校验 + 视觉调参"时间——这也是为什么 A/B 都还保留了一段人类签收。

### 必须前置的两个风险（与工时强相关）
1. **版本钉死（pin）**：wisland 仅 6 天大、仍active churning（末次 push 距"now"仅 2 天），其 AI 作者大概率还在改 `shape/glass/anim` 的签名。移植时**必须钉死一个 commit/tag**，否则上游重构会半路打断移植。这也是为何 A 场景要从"fork + 钉 commit"起步。
2. **继承粗糙边角**：2 个 open issues 意味着 wisland 仍有未磨平的坑，移植时会一并带过来，需在 PoC 阶段（§七步骤 1）优先验证"截图权限受限"等已知脆弱点。

> 一句话：**AI 全自动约 1.5–2.5 天（能跑能看）到 3–4 天（只能写、靠人验）可完工**，相比纯人 2.5–3 周大幅压缩；前提是先钉死 wisland 的 commit，并预留一段人眼审美签收。

---

## 九、实际落地结果 vs 评估（2026-11-14 补，B0–B9 完成时）

本节只记录**实测与当初预估的偏差**，不复述结论。逐条实测数据在 `porting-checklist.md` 各批次。

### 达成情况

| 指标 | 评估时预期 | 实际 | 判定 |
|---|---|---|---|
| 单文件体积 | 约 40–60 MB（PySide6 运行时基线） | **37.0 MB** | 好于预期 |
| 冷启动（端到端，含自解压） | 约 2–4s | **3.03s**（Electron 8.79s） | 符合 |
| 引擎本体启动 | 未单列 | **1.63s**（Electron 1.19s） | 略差 0.44s |
| 常驻 CPU（静止） | < 1%（能停帧） | **0.37%**（含 10s 增量扫描） | 符合 |
| 真实毛玻璃 | 「决定移植是否有意义」的头号风险 | GDI 截屏 + 降采样高斯，**一次通过** | 风险消除 |
| 工期 | 场景 A 1–2 天 / 场景 B 3–4 天 | **1 天内跑完 B0–B9**（AI 能自己截图自检） | 落在 A 上界内 |

### 三个偏差与原因

1. **引擎本体反而慢了 0.44s**：Qt 的首次字体度量约 0.9s，其中大头是 MiSans（CJK 字体）首次解析 0.6~0.9s，而 Segoe UI 只要 29ms。评估阶段没把「字体引擎初始化」算进启动预算——这是 Qt 与 Chromium 的一处结构性差异（Chromium 自带字体缓存与异步排版，Qt 同步解析）。收益是体积与自解压省下 5.7s，端到端仍快 2.7 倍。
2. **「CSS 质感」不必复刻**：评估里担心「CSS 的折射色散 inset 描边 + 曲面高光在 QPainter 里做不出来」。实际做法是**换掉这套语言**用 wisland 的：多层宽描边近似阴影 + 真实采样背景 + 棱边高光，观感不输且每帧成本可控（背景合成缓存 0.05ms/帧）。结论：**照搬 wisland 的 UI 语言比逐条翻译 CSS 划算得多**——这也验证了铁律 6「不混用两套 UI 语言」。
3. **信息分层被重新定义**：评估时默认「收起态也展示进行中会话（走马灯）」是功能保留项。落地后实测滚动版常驻 3.12% CPU、且胶囊在屏幕顶端持续运动很干扰，最终**删除走马灯**、收起态只留三格数字。这属于评估阶段没意识到的产品判断，写进了铁律 7。

### 评估里没预见、但实际撞上的坑

- **比例数字**：字体是 proportional 而非 tabular，`1` 是 6px、其余 7px，`M` 12px、`K` 9px。「同样字符数」不等于「同样宽度」，按字符数估算槽宽会在 100.0M 起溢出（详见 checklist B5 的宽度复核）。
- **`setWindowFlags` 会重建原生窗口**：置顶切换若用它，hwnd 失效 + `WS_EX_NOACTIVATE` 丢失（玻璃采样变成截自己）。必须走 `SetWindowPos`。
- **`--windowed` 冻结态 `sys.stdout` 是 `None`**：打包后所有 print 进黑洞，`--self-test` 完全失效，必须显式重定向到文件。
- **`ELECTRON_RUN_AS_NODE` 环境变量**：宿主（VS Code / WorkBuddy）会注入它，使 `electron.exe` 退化成 node、应用秒退。量测旧版启动时踩到，表现为「旧包坏了」。

### 一句话
**评估的核心判断（PySide6 可行、毛玻璃能做、体积能砍一半以上）全部成立；偏差集中在「Qt 字体引擎的首次成本」和「信息分层的产品取舍」两处，都不影响结论。**
