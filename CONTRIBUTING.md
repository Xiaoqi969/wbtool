# 贡献指南

> 文件说明：说明如何本地运行、修改、验证与提交改动。欢迎 Issue 和 Pull Request。

## 本地运行

本项目**零第三方依赖**，Python 3.8+ 直接运行即可（仅打包时才需要 PyInstaller）：

```bash
python wb_usage_app.py --no-open
```

生成 `wbtool_report.html` 后用浏览器打开即可。想自动打开浏览器就去掉 `--no-open`。

## 代码结构

| 位置 | 作用 |
|---|---|
| `wb_usage_app.py` → 数据扫描层 | `collect_all()` 逐行解析 jsonl，只提取统计字段；`scan_old_files()` 只读找出超期文件 |
| `wb_usage_app.py` → `HTML_TEMPLATE` | 内联 CSS / HTML / JS 的报告模板，占位符 `__DATA__`、`__ALIAS__`；含底部「数据清理」面板 |
| `wb_usage_app.py` → 清理流程 | `clean_execute()`（只读预览 / 备份到 `wbtool_backup/` / 移入回收站）、`send_to_recycle_bin()`（Windows 回收站，零依赖）、`clean_result_html()`（结果页）、`run_clean()`（CLI 入口） |
| `wb_usage_app.py` → 入口逻辑 | 路径解析、浏览器发现、日志、提示页、CLI 参数 |
| `build.py` | Windows 双模式打包脚本 |

## 修改后请至少跑一遍

```bash
# 1. Python 语法
python -c "import py_compile; py_compile.compile('wb_usage_app.py', doraise=True)"

# 2. 生成报告并检查 JS（把最后一个 <script> 内容交给 node --check）
python wb_usage_app.py --no-open

# 3. 前端渲染检查（无头 Edge 导出 DOM，确认没有 undefined / NaN / 空面板）
msedge --headless --disable-gpu --virtual-time-budget=3000 --dump-dom file:///.../wbtool_report.html

# 4. 清理流程（务必只用脱敏合成数据，见下方红线）
python wb_usage_app.py --clean-preview --projects ./demo-logs --days 30 --no-open

# 5. 打包
python build.py
```

改动模板时，请验证「今天 / 近 7 天 / 近 30 天 / 全部」四个范围都能正常重算。
改动清理逻辑时，请分别验证：两级删除范围（近 7 天活跃会话受保护、闲置会话仅清全量超 N 天）、
活跃 / 被触碰文件不命中、预览不移动文件、缺 `--yes` 降级为预览、
备份模式内容完整且可恢复（或回收站模式可还原）。

## 隐私红线（重要）

- **不要**把 `wbtool_report.html`、`wbtool_clean_report.html`、`*.log`、任何含真实项目路径或会话标题的文件提交进仓库，也不要贴进 Issue。
- **不要**让报告内联对话正文、推理文本、工具参数/输出、文件快照内容；清理面板只列相对路径、大小与日期。
- 需要示例数据时，请构造脱敏的合成 jsonl，不要复制本机真实日志。
- **不要**对本机真实日志跑 `--clean --yes` 做验证。清理测试一律放在临时合成目录，
  并确认备份目录在日志目录之外；备份 / 回收站都是可恢复的移动，但仍会移走会话历史。

## 提交规范

- 提交信息用简短中文或英文，说明改了什么、为什么。
- 改动报告界面时，同步更新 `README.md` 的「报告包含哪些内容」与 `CHANGELOG.md`。
- 改动清理流程时，同步更新 `README.md` 的「六、数据清理」、命令行参数表与 `CHANGELOG.md`。
- 每个新增文件请在文件头写清它的用途（本项目所有文件都带备注）。
