# 移植基线（B0 固化）

- **固化日期**：2026-11-14
- **基线来源**：本地快照 `D:\Users\lenovo\Desktop\ALL\wisland`，**非 git 仓库**（`git log` 报 `not a git repository`），全部文件 mtime 停在 `2026-11-10 14:37:07`，对应上游 `github.com/AsamiAkito/wisland` 末次提交前后
- **为什么固化**：wisland 是 4 天内由 AI 密集成型的仓库，仍处 churn 状态（评估报告 §八「必须前置的风险 1」）。本地又没有 git 历史可回溯，所以后续移植必须以上表指纹为唯一对照基准；一旦有人（或上游）改了源文件，指纹会立刻失配。

## 一、关键源文件指纹

| 文件 | 行数 | 字节 | sha256（前 16 位） | mtime |
|---|---|---|---|---|
| `wisland/ui/glass.py` | 229 | 9142 | `814c17493a6878ac` | 2026-11-10 14:37:07 |
| `wisland/ui/anim.py` | 64 | 1874 | `90766a2e9ca8c0a9` | 2026-11-10 14:37:07 |
| `wisland/ui/shape.py` | 234 | 8871 | `2e14e9f1ed4189b5` | 2026-11-10 14:37:07 |
| `wisland/ui/island.py` | 1347 | 60816 | `db879e0d1387f641` | 2026-11-10 14:37:07 |
| `wisland/ui/compact.py` | 719 | 32231 | `f2b77ee69982dcb1` | 2026-11-10 14:37:07 |

> 复核命令（在 `wisland/wisland/ui` 下）：
> ```bash
> sha256sum glass.py anim.py shape.py island.py compact.py | cut -c1-16
> ```
> 若输出与上表不一致，说明源已变动，**先停下来核对差异再继续**。

## 二、移植目标对应的源文件

| 目标 | 源 | 处理 |
|---|---|---|
| `island_qt/engine/glass.py` | `wisland/ui/glass.py` | 整文件复制（229 行全要）+ 6 行 MIT 头 + **1 处本地补丁**：`stop(wait=False)` 增加可选等待（退出时 join 1.5s，避免向已销毁窗口 emit）。日后同步上游时**不要把这处补丁 revert 掉** |
| `island_qt/engine/anim.py` | `wisland/ui/anim.py` | 整文件复制（64 行）+ 6 行 MIT 头 |
| `island_qt/engine/shape.py` | `wisland/ui/shape.py` | 整体复制（仅加 8 行 MIT 头）；**只调用** `body_path` / `deform` / `edge_corners`，`neck_path` / `drip_path` 原样保留但不调用——留全文件是为了与上游逐行可比，日后同步 diff 不必区分「删过」与「改过」 |
| `island_qt/window.py` | `wisland/ui/island.py` | 大改裁剪：1347 → **831 行**（去音乐/字幕/宠物/导航等业务，只留窗口+形变调度） |
| `island_qt/content/compact.py` | `wisland/ui/compact.py` | 重写：719 → **194 行**，只借排版语言与测宽思路 |

## 三、运行环境

| 项 | 值 |
|---|---|
| Python | 3.13.14（`C:\Users\lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe`） |
| pip | 26.1.2（`python -m pip`，注意裸 `pip` 指向的是 3.10 那套，**必须用 `python -m pip`**） |
| PySide6 | 见下方安装记录 |
| 安装源注意 | 清华镜像**没有** `PySide6-Essentials` 的 wheel（返回 `from versions: none`），必须用官方源 `https://pypi.org/simple` |

## 四、许可证

- wisland 为 MIT（`wisland/LICENSE`），WBtool 也是 MIT，可直接移植。
- 复用文件（`glass.py` / `anim.py` / `shape.py` 片段）**必须保留 wisland 原版权声明**，已在各文件头加注。

## 五、B3 追加的移植文件（2026-11-14）

`theme.py` 是「好看」的真正来源，B3 整文件复制，指纹一并钉住：

| 文件 | 行数 | 字节 | sha256 前 16 位 | 目标位置 |
|---|---|---|---|---|
| `wisland/ui/theme.py` | 273 | 9437 | `4eb937a1054839fe` | `island_qt/ui/theme.py`（复制后 279 行，仅加 6 行 MIT 头） |

`widgets.py`（710 行）暂未复制：B3 的收起态是纯 `QPainter` 自绘，用不到卡片控件；
B6 做展开态明细页时按需取 `Card` / `Themed` 等，届时补记指纹。

## 六、上游变动怎么同步（2026-11-15 定）

**结论：要同步，但只有「引擎层」需要；业务层不要抄。** 移植不是 fork，两边会持续分叉，所以按文件分层处理：

| 类 | 文件 | 与上游的关系 | 上游改了怎么办 |
|---|---|---|---|
| **A 直接同步** | `engine/glass.py`、`engine/anim.py`、`engine/shape.py`、`ui/theme.py` | 几乎原件，只多 MIT 头（glass 另有一处 `stop(wait)` 补丁） | 去掉文件头后与上游 diff → 套过来 → 跑 `_probe_b5/b6/b7/b9` 回归 |
| **B 只读不抄** | `window.py`（1347→831）、`content/compact.py`（719→194） | 结构已分叉，不是同一份代码 | 读懂「修的是哪个问题」→ 判断 WBtool 是否存在该问题 → 按自己的结构改。**禁止整份覆盖** |
| **C 不用管** | `services/`、`learn/`、`live/`、`pages/`、`widgets.py` | 根本没搬 | 忽略 |

判断信号：commit message 涉及**绘制 / 弹簧 / DPI / 玻璃 / 圆角** → 看 A 类；涉及**具体页面或服务**（天气、Anki、字幕、翻译）→ 基本是 C 类。

### 同步步骤

1. 先核对本文表格的指纹。**全部命中**才说明本地原件没被人动过；失配就先查清是谁改的。
2. 上游拉成带历史的仓库再比（本地 `D:\Users\lenovo\Desktop\ALL\wisland` **不是 git 仓库**，无法 diff 版本）：
   `git clone https://github.com/AsamiAkito/wisland /tmp/wisland-up` → `git log --oneline 3f1ec1d..origin/main -- wisland/ui`
3. **A 类**：把目标文件去掉开头 MIT 头，与上游 diff；若差异只剩上游改动，直接补丁，并保留 `glass.py` 的 `stop(wait)` 补丁。
4. **B 类**：只读 commit diff 与注释，判断影响面；确需跟进时在 WBtool 侧重写，不合并上游文件。
5. 同步完更新本文指纹表（行数 / 字节 / sha256 / 日期）与本轮说明，与代码同一个提交。

### 当前状态（2026-11-15 01:30 实测）

- 本地快照 mtime 全部停在 `2026-11-10 14:37:07`，对应上游提交 **`3f1ec1d`**（该提交时间 06:37:07Z）。
- 上游最新提交 **`11ebd0f`**（06:48:14Z），比本地只多一个提交，改动文件仅 `wisland/services/weather.py` —— **C 类，对移植零影响**。
- 此后 5 天上游无新提交（`commits?since=2026-11-10T06:48:15Z` 返回 0 条）。→ **当前同步欠账为零**，不必主动拉。

