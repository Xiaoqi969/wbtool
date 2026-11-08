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
| `wb_usage_app.py` → 数据扫描层 | `collect_all()` 逐行解析 jsonl，只提取统计字段 |
| `wb_usage_app.py` → `HTML_TEMPLATE` | 内联 CSS / HTML / JS 的报告模板，占位符 `__DATA__`、`__ALIAS__` |
| `wb_usage_app.py` → 入口逻辑 | 路径解析、浏览器发现、日志、提示页、CLI |
| `build.py` | Windows 双模式打包脚本 |

## 修改后请至少跑一遍

```bash
# 1. Python 语法
python -c "import py_compile; py_compile.compile('wb_usage_app.py', doraise=True)"

# 2. 生成报告并检查 JS（把最后一个 <script> 内容交给 node --check）
python wb_usage_app.py --no-open

# 3. 前端渲染检查（无头 Edge 导出 DOM，确认没有 undefined / NaN / 空面板）
msedge --headless --disable-gpu --virtual-time-budget=3000 --dump-dom file:///.../wbtool_report.html

# 4. 打包
python build.py
```

改动模板时，请验证「今天 / 近 7 天 / 近 30 天 / 全部」四个范围都能正常重算。

## 隐私红线（重要）

- **不要**把 `wbtool_report.html`、`*.log`、任何含真实项目路径或会话标题的文件提交进仓库，也不要贴进 Issue。
- **不要**让报告内联对话正文、推理文本、工具参数/输出、文件快照内容。
- 需要示例数据时，请构造脱敏的合成 jsonl，不要复制本机真实日志。

## 提交规范

- 提交信息用简短中文或英文，说明改了什么、为什么。
- 改动报告界面时，同步更新 `README.md` 的「报告包含哪些内容」与 `CHANGELOG.md`。
- 每个新增文件请在文件头写清它的用途（本项目所有文件都带备注）。
