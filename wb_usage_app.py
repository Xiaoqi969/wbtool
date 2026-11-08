#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wbtool - WorkBuddy 用量统计（Windows 单文件图形化工具）
=========================================================
文件说明：本文件是项目唯一的主程序，包含【数据扫描层】【HTML 报告模板】【入口逻辑】三部分。
          HTML 模板内联在下方 HTML_TEMPLATE 常量中，因此生成的报告完全离线自包含。

项目主页: https://github.com/Xiaoqi969/wbtool
作者    : 小柒 | https://xiaoqilucky.com
许可证  : MIT

工作流程（用完即走，不常驻后台、不起服务、不联网）：
  1. 扫描 ~/.workbuddy/projects/**/*.jsonl，聚合全部可展示的统计字段
  2. 生成一份完全自包含、离线可用的 HTML 报告
  3. 用系统浏览器（优先 Microsoft Edge）打开报告
  4. 程序退出

隐私承诺：绝不内联对话正文、推理文本、工具参数/输出、文件快照内容。
          报告仅含统计数值、模型名、项目路径与时间。

命令行：
  python wb_usage_app.py                      扫描并打开报告
  python wb_usage_app.py --no-open           只生成报告，不打开浏览器
  python wb_usage_app.py --out FILE          指定报告输出路径
  python wb_usage_app.py --projects DIR      指定 jsonl 目录（覆盖默认）
  python wb_usage_app.py --version           显示版本号

环境变量：
  WORKBUDDY_PROJECTS_DIR   覆盖默认的 ~/.workbuddy/projects

打包（Windows）：
  python build.py
  等价于: pyinstaller --onefile --windowed --icon assets/wbtool.ico --name wbtool wb_usage_app.py
"""
import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback
import webbrowser
from html import escape as esc_html
from pathlib import Path

__version__ = "1.0.0"
APP_NAME = "wbtool"
AUTHOR = "小柒"
AUTHOR_URL = "https://xiaoqilucky.com"

HOME = Path.home()
PROJECTS_DIR = Path(os.environ.get("WORKBUDDY_PROJECTS_DIR") or (HOME / ".workbuddy" / "projects"))

MODEL_ALIAS = {
    "hy3": "混元 hy3",
    "hy4-free": "混元 hy4-free",
    "hy4free": "混元 hy4-free",
    "glm-5.3-flash": "GLM 5.3 Flash",
    "deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "kimi-k3.1-pro": "Kimi K3.1 Pro",
}

# 浏览器候选：先查平台常见安装路径，再查 PATH，最后回退系统默认浏览器。
# Windows 是本项目唯一正式支持的平台，但保留其他平台的路径以便源码直接运行。
BROWSER_CANDIDATES = {
    "Windows": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "Darwin": [
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ],
    "Linux": [],
}
BROWSER_COMMANDS = (
    "msedge", "microsoft-edge", "microsoft-edge-stable",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "firefox",
)

IMAGE_TYPES = ("image_blob_ref", "input_image", "image")


# ----------------------------------------------------------------------------
# 数据扫描：只提取可展示的统计字段，不读取任何正文内容
# ----------------------------------------------------------------------------
def norm_usage(u):
    if not isinstance(u, dict):
        return None
    inp = u.get("input_tokens", u.get("inputTokens", 0)) or 0
    out = u.get("output_tokens", u.get("outputTokens", 0)) or 0
    tot = u.get("total_tokens", u.get("totalTokens", 0)) or 0
    cache = u.get("cache_read_input_tokens", 0)
    if not cache:
        det = u.get("inputTokensDetails") or u.get("input_tokens_details") or []
        if isinstance(det, list):
            cache = sum(d.get("cached_tokens", 0) or 0 for d in det if isinstance(d, dict))
    if tot == 0 and (inp or out):
        tot = inp + out
    return {"input": inp, "output": out, "total": tot, "cache": cache or 0}


def bump(counter, key, amount=1):
    if key is None:
        return
    counter[key] = counter.get(key, 0) + amount


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def count_image_blocks(o):
    """只统计浅层 content 列表里的图片类型标记，不读取任何图片/文本数据。"""
    n = 0
    for key in ("content", "rawContent"):
        v = o.get(key)
        if isinstance(v, list):
            for b in v:
                if isinstance(b, dict) and b.get("type") in IMAGE_TYPES:
                    n += 1
    msg = o.get("message")
    if isinstance(msg, dict):
        v = msg.get("content")
        if isinstance(v, list):
            for b in v:
                if isinstance(b, dict) and b.get("type") in IMAGE_TYPES:
                    n += 1
    return n


def collect_all(projects_dir=None):
    """扫描 jsonl，只提取可展示的统计字段；projects_dir 为 None 时使用默认目录。"""
    records = []          # 每次 LLM 调用：token / 积分 / 模型 / 项目 / 会话 / 时间
    daily = {}            # 按天预聚合的行为统计
    sessions = {}         # 会话元信息（不含正文）
    gen_credit = []       # 生成工具（图片等）独立积分事件
    quota_latest = {}     # 每个模型最新配额
    total_lines = 0

    scan_root = Path(projects_dir) if projects_dir else PROJECTS_DIR
    for root, _, files in os.walk(scan_root):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(root, fn)
            try:
                mtime = os.path.getmtime(path) * 1000
            except OSError:
                mtime = None
            fallback_proj = os.path.basename(os.path.dirname(path))
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    total_lines += 1
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(o, dict):
                        continue

                    ts = o.get("timestamp")
                    if not isinstance(ts, (int, float)):
                        ts = mtime
                    if ts and ts > 1e11:
                        moment = dt.datetime.fromtimestamp(ts / 1000)
                    elif ts:
                        moment = dt.datetime.fromtimestamp(ts)
                    else:
                        moment = None
                    day = moment.strftime("%Y-%m-%d") if moment else "unknown"
                    hour = moment.hour if moment else -1

                    typ = o.get("type") if isinstance(o.get("type"), str) else "unknown"
                    sid = o.get("sessionId") if isinstance(o.get("sessionId"), str) else ""
                    cwd = o.get("cwd") if isinstance(o.get("cwd"), str) else ""
                    proj = cwd or fallback_proj
                    pd = o.get("providerData") if isinstance(o.get("providerData"), dict) else {}

                    # --- 按天行为聚合 ---
                    d = daily.setdefault(day, {
                        "tools": {}, "types": {}, "status": {}, "hours": {},
                        "images": 0, "reasoning": 0, "snapshots": 0,
                        "genCredit": 0.0, "genEvents": 0, "lines": 0,
                    })
                    d["lines"] += 1
                    bump(d["types"], typ)
                    if hour >= 0:
                        bump(d["hours"], str(hour))
                    st = o.get("status")
                    if isinstance(st, str):
                        bump(d["status"], st)
                    if typ == "function_call":
                        nm = o.get("name")
                        if isinstance(nm, str) and len(nm) < 80:
                            bump(d["tools"], nm)
                    if typ == "reasoning":
                        d["reasoning"] += 1
                    if typ == "file-history-snapshot":
                        d["snapshots"] += 1
                    d["images"] += count_image_blocks(o)

                    # --- 会话元信息 ---
                    if sid:
                        s = sessions.setdefault(sid, {
                            "id": sid, "title": "", "cwd": proj,
                            "first": day, "last": day, "lines": 0,
                        })
                        s["lines"] += 1
                        # 真实工作目录优先：会话首行可能缺 cwd，后续行补上
                        if cwd and ":" in cwd and ":" not in s["cwd"]:
                            s["cwd"] = cwd
                        if day != "unknown":
                            if s["first"] == "unknown" or day < s["first"]:
                                s["first"] = day
                            if day > s["last"]:
                                s["last"] = day
                        if not s["title"] and isinstance(o.get("aiTitle"), str):
                            s["title"] = o["aiTitle"][:80]

                    # --- 生成工具独立积分（图片生成等） ---
                    if typ == "credit-usage":
                        amt = pd.get("credit")
                        if isinstance(amt, (int, float)):
                            amt = float(amt)
                            d["genCredit"] += amt
                            d["genEvents"] += 1
                            src = pd.get("source") if isinstance(pd.get("source"), str) else ""
                            gen_credit.append({"d": day, "a": amt, "src": src})

                    # --- LLM 调用记录 ---
                    msg = o.get("message") if isinstance(o.get("message"), dict) else {}
                    usage = msg.get("usage") or pd.get("usage")
                    nu = norm_usage(usage)
                    if not nu:
                        continue
                    ru = pd.get("rawUsage") if isinstance(pd.get("rawUsage"), dict) else {}
                    credit = float(num(ru.get("credit")))
                    original = float(num(ru.get("original_credit")))
                    thinking = num(ru.get("completion_thinking_tokens"))
                    if not thinking:
                        det = ru.get("completion_tokens_details")
                        if isinstance(det, dict):
                            thinking = num(det.get("reasoning_tokens"))
                    miss = num(ru.get("prompt_cache_miss_tokens"))
                    hit = num(ru.get("prompt_cache_hit_tokens")) or nu["cache"]
                    model = pd.get("model") if isinstance(pd.get("model"), str) else "unknown"

                    q = ru.get("quota")
                    if isinstance(q, dict) and isinstance(q.get("model"), str):
                        quota_latest[q["model"]] = {
                            "model": q["model"],
                            "percent": num(q.get("percent")),
                            "resetAt": q.get("reset_at") if isinstance(q.get("reset_at"), str) else "",
                        }

                    records.append({
                        "d": day, "h": hour, "m": model, "p": proj, "s": sid,
                        "i": nu["input"], "o": nu["output"], "t": nu["total"],
                        "c": nu["cache"], "cm": miss, "ch": hit,
                        "th": thinking, "cr": credit, "oc": original,
                    })

    sessions_out = []
    for s in sessions.values():
        sessions_out.append({
            "id": s["id"],
            "title": s["title"] or s["id"][:8],
            "cwd": s["cwd"],
            "first": s["first"], "last": s["last"], "lines": s["lines"],
        })
    quota_out = sorted(quota_latest.values(), key=lambda x: x["model"])
    return {
        "records": records,
        "daily": daily,
        "sessions": sessions_out,
        "genCredit": gen_credit,
        "quota": quota_out,
        "totalLines": total_lines,
    }


# ----------------------------------------------------------------------------
# HTML 报告模板（浅色 + 青蓝强调，全部可展示维度）
# ----------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WorkBuddy 用量统计</title>
<style>
:root{
  --bg:#f4f7f8; --panel:#fff; --line:#e8edf0; --text:#1f2937; --muted:#8a94a3;
  --teal:#0aa6b8; --teal-l:#5fd0dc; --teal-d:#07808f; --teal-soft:#e6f6f8;
  --amber:#e0a020; --shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.05);
}
*{box-sizing:border-box}
html,body{margin:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:14px;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:26px 24px 56px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px 20px;box-shadow:var(--shadow);margin-bottom:16px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:13px}
.logo{width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,#0aa6b8,#36d4e0);color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:19px;box-shadow:0 4px 12px rgba(10,166,184,.25)}
.brand .t{font-weight:700;font-size:18px;letter-spacing:.2px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.brand .s{font-size:12px;color:var(--muted);margin-top:2px}
.brand .author{display:inline-flex;align-items:center;font-size:11.5px;font-weight:600;letter-spacing:0;color:var(--teal-d);background:var(--teal-soft);border:1px solid #cbeaee;border-radius:999px;padding:3px 9px;text-decoration:none;transition:all .15s}
.brand .author:hover{background:var(--teal-d);border-color:var(--teal-d);color:#fff}
.right{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.meta{font-size:12.5px;color:var(--muted);text-align:right;line-height:1.7}
.ranges{display:flex;gap:4px;background:#f1f5f6;padding:4px;border-radius:10px}
.ranges button{border:0;background:transparent;color:#5b6573;font-size:12.5px;padding:6px 12px;border-radius:7px;cursor:pointer;font-family:inherit;transition:all .15s}
.ranges button:hover{color:var(--teal-d)}
.ranges button.on{background:#fff;color:var(--teal-d);font-weight:700;box-shadow:0 1px 3px rgba(16,24,40,.12)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}
.pcard{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;box-shadow:var(--shadow);display:flex;flex-direction:column}
.pcard .pt{font-size:13px;color:var(--muted);font-weight:600;display:flex;align-items:center;gap:8px}
.pcard .pt .dot{width:9px;height:9px;border-radius:50%;background:var(--teal)}
.pcard .pbig{font-size:29px;font-weight:800;margin:10px 0 2px;letter-spacing:.3px;color:#16202b;font-variant-numeric:tabular-nums;line-height:1.1}
.pcard .plab{font-size:12px;color:var(--muted);margin-bottom:13px}
.pcard .prow{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;color:#5b6573;padding:7px 0;border-top:1px solid #f1f4f6}
.pcard .prow span:last-child{color:#7b8794;font-variant-numeric:tabular-nums}
.pcard .prow b{color:var(--teal-d);font-weight:700}
.ov{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.ovc{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px 15px;box-shadow:var(--shadow)}
.ovc .k{font-size:11.5px;color:var(--muted);margin-bottom:6px}
.ovc .v{font-size:19px;font-weight:700;color:#16202b;font-variant-numeric:tabular-nums;line-height:1.2}
.ovc .v small{font-size:11px;color:var(--muted);font-weight:500;margin-left:3px}
.ovc.hl{background:var(--teal-soft);border-color:#cbeaee}
.ovc.hl .v{color:var(--teal-d)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow);margin-bottom:16px}
.ph{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:10px}
.ph h2{font-size:14.5px;margin:0;font-weight:700}
.ph .hint{font-size:11.5px;color:var(--muted)}
.legend{display:flex;gap:14px;font-size:11.5px;color:#5b6573;margin:0 0 8px;flex-wrap:wrap}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.grid2 .panel{margin-bottom:0}
.chart-wrap{width:100%;overflow-x:auto}
.hbar{display:flex;flex-direction:column;gap:9px}
.hrow{display:flex;align-items:center;gap:12px;font-size:12.5px}
.hrow .lab{width:170px;flex:0 0 170px;color:#3a4151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hrow .track{flex:1;background:#f0f4f5;border-radius:6px;height:20px;position:relative;overflow:hidden}
.hrow .fill{height:100%;border-radius:6px;min-width:3px;background:linear-gradient(90deg,#0aa6b8,#5fd0dc)}
.hrow .fill.amber{background:linear-gradient(90deg,#e0a020,#f5cf6b)}
.hrow .val{width:160px;flex:0 0 160px;text-align:right;color:#5b6172;font-variant-numeric:tabular-nums}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.tbl th{text-align:right;color:var(--muted);font-weight:600;font-size:11.5px;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tbl td{text-align:right;padding:8px 10px;border-bottom:1px solid #f3f6f7;color:#475569;font-variant-numeric:tabular-nums;white-space:nowrap}
.tbl tr:last-child td{border-bottom:0}
.tbl tbody tr:hover{background:#f8fbfc}
.tbl .d{color:#16202b;font-weight:600}
.tbl .mini{display:inline-block;width:44px;height:6px;border-radius:3px;background:#eef2f4;overflow:hidden;vertical-align:middle;margin-left:8px}
.tbl .mini i{display:block;height:100%;background:var(--teal)}
.tbl-wrap{max-height:380px;overflow:auto}
.stack{display:flex;height:26px;border-radius:7px;overflow:hidden;background:#f0f4f5;margin:8px 0 4px}
.stack i{display:block;height:100%}
.stack .a{background:#0aa6b8}.stack .b{background:#5fd0dc}.stack .c{background:#e0a020}.stack .d{background:#f5cf6b}
.bl{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 20px;font-size:12.5px;color:#475569;margin-top:10px}
.bl div{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid #f3f6f7;padding:5px 0}
.bl b{color:#16202b;font-variant-numeric:tabular-nums}
.mini3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px}
.mini3 .ovc{padding:11px 13px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.chip{background:#f1f6f7;border:1px solid var(--line);border-radius:8px;padding:7px 11px;font-size:12px;color:#475569}
.chip b{color:var(--teal-d);font-variant-numeric:tabular-nums}
.free{color:#0a9b6a;font-weight:600}
#tip{position:fixed;pointer-events:none;background:#16202b;color:#fff;padding:8px 11px;border-radius:9px;font-size:12px;line-height:1.55;box-shadow:0 6px 20px rgba(0,0,0,.25);opacity:0;transition:opacity .12s;z-index:99;white-space:nowrap}
#tip b{color:#7dd3fc}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:#cdd5db;border-radius:8px}
@media(max-width:860px){.ov{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.hrow .lab{width:120px;flex-basis:120px}.hrow .val{width:120px;flex-basis:120px}}
@media(max-width:720px){.cards{grid-template-columns:1fr}.topbar{flex-direction:column;align-items:flex-start}.meta{text-align:left}.right{width:100%}.mini3,.bl{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="brand">
      <div class="logo">W</div>
      <div>
        <div class="t">WorkBuddy 用量统计<a class="author" href="https://xiaoqilucky.com" target="_blank" rel="noopener noreferrer" title="访问作者主页 xiaoqilucky.com">作者:小柒 ↗</a></div>
        <div class="s">会话日志 · 本地扫描 · 不含对话正文</div>
      </div>
    </div>
    <div class="right">
      <div class="ranges" id="ranges">
        <button data-n="1">今天</button>
        <button data-n="7">近 7 天</button>
        <button data-n="30" class="on">近 30 天</button>
        <button data-n="all">全部</button>
      </div>
      <div class="meta" id="meta"></div>
    </div>
  </div>

  <div class="cards" id="cards"></div>
  <div class="ov" id="overview"></div>

  <div class="panel">
    <div class="ph"><h2>积分消耗</h2><div class="hint" id="creditHint"></div></div>
    <div class="mini3" id="creditCards"></div>
    <div class="grid2" style="margin-bottom:0">
      <div>
        <div style="font-size:12px;color:var(--muted);margin-bottom:8px">按模型（LLM 积分）</div>
        <div class="hbar" id="creditByModel"></div>
      </div>
      <div>
        <div style="font-size:12px;color:var(--muted);margin-bottom:8px">按天（LLM 积分）</div>
        <div class="chart-wrap" id="creditByDay"></div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="ph"><h2>Token 构成</h2><div class="hint">输入 = 缓存命中 + 未命中；输出 = 思考 + 正文</div></div>
    <div class="stack" id="tokenStack"></div>
    <div class="legend"><span><i class="sw" style="background:#0aa6b8"></i>缓存命中</span><span><i class="sw" style="background:#5fd0dc"></i>缓存未命中</span><span><i class="sw" style="background:#e0a020"></i>思考 token</span><span><i class="sw" style="background:#f5cf6b"></i>正文输出</span></div>
    <div class="bl" id="tokenBreak"></div>
  </div>

  <div class="panel">
    <div class="ph"><h2>每日 Token 趋势</h2><div class="hint" id="trendHint"></div></div>
    <div class="legend"><span><i class="sw" style="background:#0aa6b8"></i>输入</span><span><i class="sw" style="background:#5fd0dc"></i>输出</span><span style="color:#8a94a3">悬停查看当日明细</span></div>
    <div class="chart-wrap" id="trend"></div>
  </div>

  <div class="grid2">
    <div class="panel"><div class="ph"><h2>按模型分布</h2><div class="hint">合计 Token</div></div>
      <div class="chart-wrap"><div class="hbar" id="modelBars"></div></div></div>
    <div class="panel"><div class="ph"><h2>按项目分布</h2><div class="hint">按真实工作目录 cwd</div></div>
      <div class="chart-wrap"><div class="hbar" id="projBars"></div></div></div>
  </div>

  <div class="grid2">
    <div class="panel"><div class="ph"><h2>工具调用</h2><div class="hint" id="toolHint"></div></div>
      <div class="chart-wrap"><div class="hbar" id="toolBars"></div></div></div>
    <div class="panel"><div class="ph"><h2>小时活跃分布</h2><div class="hint" id="hourHint"></div></div>
      <div class="chart-wrap" id="hourChart"></div></div>
  </div>

  <div class="panel">
    <div class="ph"><h2>会话排行</h2><div class="hint" id="sessionHint"></div></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr>
      <th>会话</th><th>项目</th><th>起止</th><th>调用</th><th>合计 Token</th><th>积分</th>
    </tr></thead><tbody id="sessionRows"></tbody></table></div>
  </div>

  <div class="panel">
    <div class="ph"><h2>活动构成与其他指标</h2><div class="hint" id="miscHint"></div></div>
    <div class="grid2" style="margin-bottom:12px">
      <div><div style="font-size:12px;color:var(--muted);margin-bottom:8px">消息类型分布</div>
        <div class="hbar" id="typeBars"></div></div>
      <div><div style="font-size:12px;color:var(--muted);margin-bottom:8px">其他指标</div>
        <div class="chips" id="miscChips"></div>
        <div id="quotaBox" style="margin-top:12px"></div></div>
    </div>
  </div>

  <div class="panel">
    <div class="ph"><h2>每日明细</h2><div class="hint" id="tableHint"></div></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr>
      <th>日期</th><th>调用</th><th>输入</th><th>输出</th><th>合计 Token</th><th>缓存命中率</th>
      <th>思考</th><th>缓存未命中</th><th>积分</th><th>工具调用</th>
    </tr></thead><tbody id="dailyRows"></tbody></table></div>
  </div>
</div>
<div id="tip"></div>

<script>
const DATA = __DATA__;
const ALIAS = __ALIAS__;
const fmt = n => (n==null?0:n).toLocaleString('en-US');
const money = n => (Math.round((n||0)*100)/100).toFixed(2);
const short = n => { if(n>=1e9)return (n/1e9).toFixed(2)+'B'; if(n>=1e6)return (n/1e6).toFixed(2)+'M'; if(n>=1e3)return (n/1e3).toFixed(1)+'K'; return ''+Math.round(n||0); };
const esc = s => String(s==null?'':s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modelName = m => ALIAS[m] || m;
const prettyProj = p => {
  const raw=String(p||'');
  if(/^[a-zA-Z]:[\\\/]/.test(raw)){
    const a=raw.replace(/^[a-zA-Z]:[\\\/]/,'').replace(/\\/g,'/').split('/').filter(Boolean);
    return (a.length>3?a.slice(-3):a).join(' / ');
  }
  const a=raw.replace(/^[dc]-/,'').split('-').filter(Boolean);
  return (a.length>3?a.slice(0,3).join(' / ')+' / …':a.join(' / '));
};
const pct = (a,b) => b?Math.round(a/b*100):0;

function dateMinus(dstr,n){ const [y,m,dd]=dstr.split('-').map(Number); const x=new Date(y,m-1,dd); x.setDate(x.getDate()-n); const p=v=>String(v).padStart(2,'0'); return `${x.getFullYear()}-${p(x.getMonth()+1)}-${p(x.getDate())}`; }
function inRange(day,N){ if(N==='all') return true; return day!=='unknown' && day>=dateMinus(DATA.today,N-1); }
function rangeRecs(N){ if(N==='all') return DATA.records.slice(); return DATA.records.filter(r=>inRange(r.d,N)); }
function rangeDaily(N){
  const out={tools:{},types:{},status:{},hours:{},images:0,reasoning:0,snapshots:0,genCredit:0,genEvents:0,lines:0};
  Object.keys(DATA.daily).forEach(k=>{
    if(!inRange(k,N)) return;
    const d=DATA.daily[k]; out.lines+=d.lines; out.images+=d.images; out.reasoning+=d.reasoning;
    out.snapshots+=d.snapshots; out.genCredit+=d.genCredit; out.genEvents+=d.genEvents;
    ['tools','types','status','hours'].forEach(f=>Object.keys(d[f]||{}).forEach(x=>out[f][x]=(out[f][x]||0)+d[f][x]));
  });
  return out;
}
const ZERO = () => ({i:0,o:0,t:0,c:0,cm:0,ch:0,th:0,cr:0,oc:0,n:0});
function addTo(b,r){ b.i+=r.i;b.o+=r.o;b.t+=r.t;b.c+=r.c;b.cm+=r.cm;b.ch+=r.ch;b.th+=r.th;b.cr+=r.cr;b.oc+=r.oc;b.n++; }
function aggregate(recs){
  const total=ZERO(), byDay={}, byModel={}, byProj={}, bySession={};
  const add=(b,k,r)=>{ if(!b[k])b[k]=ZERO(); addTo(b[k],r); };
  recs.forEach(r=>{ addTo(total,r); add(byDay,r.d,r); add(byModel,r.m,r); add(byProj,r.p,r); add(bySession,r.s||'unknown',r); });
  const arr=b=>Object.keys(b).map(k=>({k,...b[k]}));
  const byT=(a,b)=>b.t-a.t;
  return {total,
    dayArr:arr(byDay).sort((a,b)=>a.k.localeCompare(b.k)),
    modelArr:arr(byModel).sort(byT), projArr:arr(byProj).sort(byT),
    sessionArr:arr(bySession).sort(byT), bySession};
}
function kv(obj,sortByVal){
  const a=Object.keys(obj).map(k=>({k,t:obj[k]}));
  return a.sort((x,y)=>sortByVal?y.t-x.t:x.k.localeCompare(y.k));
}

function periodCard(title,N){
  const t=aggregate(rangeRecs(N)).total;
  return `<div class="pcard"><div class="pt"><span class="dot"></span>${title}</div>
    <div class="pbig">${fmt(t.t)}</div><div class="plab">合计 Token</div>
    <div class="prow"><span>输入 ${fmt(t.i)}</span><span>输出 ${fmt(t.o)}</span></div>
    <div class="prow"><span>缓存命中 <b>${fmt(t.ch)}</b> (${pct(t.ch,t.i)}%)</span><span>调用 ${fmt(t.n)} 次</span></div>
    <div class="prow"><span>积分 <b>${money(t.cr)}</b></span><span>思考 ${fmt(t.th)}</span></div></div>`;
}
function overviewCards(t){
  return [
    ['合计 Token',fmt(t.t),'',0],['输入 Token',fmt(t.i),'',0],['输出 Token',fmt(t.o),'',0],
    ['缓存命中',fmt(t.ch),'('+pct(t.ch,t.i)+'%)',0],['缓存未命中',fmt(t.cm),'',0],
    ['思考 Token',fmt(t.th),'占输出 '+pct(t.th,t.o)+'%',0],
    ['LLM 积分',money(t.cr),'',1],['调用次数',fmt(t.n),'次',0]
  ].map(([k,v,u,hl])=>`<div class="ovc${hl?' hl':''}"><div class="k">${k}</div><div class="v">${v}<small>${u}</small></div></div>`).join('');
}
function bars(items,keyFn,valFn,labelFn,topN,amber){
  const list=topN?items.slice(0,topN):items;
  if(!list.length) return '<div style="color:#8a94a3;padding:14px">该范围无数据</div>';
  const max=Math.max(...list.map(valFn),1);
  return list.map(d=>{ const p=Math.max(1.5,Math.round(valFn(d)/max*100)), name=keyFn(d);
    return `<div class="hrow"><div class="lab" title="${esc(name)}">${esc(name)}</div>
      <div class="track"><div class="fill${amber?' amber':''}" style="width:${p}%"></div></div>
      <div class="val">${labelFn(d)}</div></div>`; }).join('');
}
function svgBars(items,opt){
  if(!items.length) return '<div style="color:#8a94a3;padding:20px">该范围无数据</div>';
  const H=opt.H||170,padB=24,padT=12,padL=38,padR=8;
  const step=Math.max(14,opt.W/items.length);
  const W=Math.max(opt.W,items.length*step+padL+padR), bw=Math.max(6,Math.min(40,step*0.62));
  const max=Math.max(...items.map(d=>d.v),1), plotH=H-padT-padB;
  let s=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  for(let g=0;g<=3;g++){ const y=padT+plotH*g/3;
    s+=`<line x1="${padL}" y1="${y}" x2="${W-4}" y2="${y}" stroke="#eef2f4"/>`;
    s+=`<text x="${padL-6}" y="${y+3}" font-size="9" fill="#a8b2bd" text-anchor="end">${opt.axis(max*(3-g)/3)}</text>`; }
  items.forEach((d,i)=>{
    const cx=padL+i*step+step/2, x=cx-bw/2, h=d.v/max*plotH, y=H-padB-h;
    s+=`<rect x="${x}" y="${y}" width="${bw}" height="${h}" rx="2" fill="${d.color||'#0aa6b8'}"><title>${esc(d.k)}: ${esc(opt.axis(d.v))}</title></rect>`;
    if(opt.labelEvery===undefined || i%opt.labelEvery===0 || i===items.length-1)
      s+=`<text x="${cx}" y="${H-8}" font-size="9" fill="#8a94a3" text-anchor="middle">${esc(d.k)}</text>`;
  });
  return s+'</svg>';
}
function trendBars(days){
  if(!days.length) return '<div style="color:#8a94a3;padding:24px">该范围无数据</div>';
  const H=220,padB=28,padT=16,padL=46,padR=10;
  const step=Math.max(15,1000/days.length);
  const W=Math.max(1000,days.length*step+padL+padR), bw=Math.max(8,Math.min(48,step*0.62));
  const max=Math.max(...days.map(d=>d.t),1), plotH=H-padT-padB;
  let s=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  for(let g=0;g<=4;g++){ const y=padT+plotH*g/4;
    s+=`<line x1="${padL}" y1="${y}" x2="${W-4}" y2="${y}" stroke="#eef2f4"/>`;
    s+=`<text x="${padL-7}" y="${y+3}" font-size="9.5" fill="#a8b2bd" text-anchor="end">${short(max*(4-g)/4)}</text>`; }
  days.forEach((d,idx)=>{
    const cx=padL+idx*step+step/2, x=cx-bw/2;
    const hI=d.i/max*plotH,hO=d.o/max*plotH,yI=H-padB-hI,yO=H-padB-hI-hO;
    const tip=`<b>${esc(d.k)}</b><br>合计 ${fmt(d.t)}<br>输入 ${fmt(d.i)} · 输出 ${fmt(d.o)}<br>缓存命中 ${fmt(d.ch)} · 未命中 ${fmt(d.cm)}<br>思考 ${fmt(d.th)} · 积分 ${money(d.cr)}<br>调用 ${fmt(d.n)} 次`;
    s+=`<rect class="bar" x="${x}" y="${yI}" width="${bw}" height="${hI}" rx="2" fill="#0aa6b8" data-tip="${tip}"></rect>`;
    s+=`<rect class="bar" x="${x}" y="${yO}" width="${bw}" height="${hO}" rx="2" fill="#5fd0dc" data-tip="${tip}"></rect>`;
    const every=Math.max(1,Math.ceil(days.length/12));
    if(idx%every===0||idx===days.length-1)
      s+=`<text x="${cx}" y="${H-9}" font-size="9" fill="#8a94a3" text-anchor="middle">${esc(d.k.slice(5))}</text>`;
  });
  return s+'</svg>';
}
function bindBars(){
  const tip=document.getElementById('tip');
  document.querySelectorAll('#trend rect.bar').forEach(r=>{
    r.addEventListener('mousemove',e=>{ tip.innerHTML=r.getAttribute('data-tip'); tip.style.opacity=1;
      tip.style.left=Math.min(e.clientX+14,window.innerWidth-250)+'px'; tip.style.top=(e.clientY+14)+'px'; });
    r.addEventListener('mouseleave',()=>tip.style.opacity=0);
  });
}
function renderCredit(a,ev){
  const t=a.total;
  document.getElementById('creditHint').textContent=`口径：LLM 调用积分 rawUsage.credit + 生成工具独立积分`;
  const total=t.cr+ev.genCredit;
  document.getElementById('creditCards').innerHTML=[
    ['LLM 调用积分',money(t.cr)],
    ['生成工具积分',money(ev.genCredit)+' <small>('+ev.genEvents+' 次)</small>'],
    ['合计积分',money(total)]
  ].map(([k,v])=>`<div class="ovc"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('')
   + (t.oc>0?`<div class="ovc" style="grid-column:1/-1"><div class="k">原价积分 original_credit</div><div class="v">${money(t.oc)}</div></div>`:'');
  const cm=a.modelArr.slice().sort((x,y)=>y.cr-x.cr);
  document.getElementById('creditByModel').innerHTML=bars(cm,d=>modelName(d.k),d=>d.cr,
    d=>d.cr>0?money(d.cr)+' 积分':'<span class="free">免费</span>',0,true);
  const cd=a.dayArr.map(d=>({k:d.k.slice(5),v:d.cr}));
  document.getElementById('creditByDay').innerHTML=svgBars(cd,{W:430,H:170,axis:v=>money(v),labelEvery:Math.max(1,Math.ceil(cd.length/8))});
}
function renderTokenBreak(t){
  const hit=t.ch,miss=t.cm,think=t.th,body=Math.max(0,t.o-t.th);
  const sum=hit+miss+think+body||1;
  document.getElementById('tokenStack').innerHTML=
    `<i class="a" style="width:${hit/sum*100}%"></i><i class="b" style="width:${miss/sum*100}%"></i>`+
    `<i class="c" style="width:${think/sum*100}%"></i><i class="d" style="width:${body/sum*100}%"></i>`;
  document.getElementById('tokenBreak').innerHTML=[
    ['缓存命中输入',fmt(hit),'占输入 '+pct(hit,t.i)+'%'],
    ['缓存未命中输入',fmt(miss),'占输入 '+pct(miss,t.i)+'%'],
    ['思考 / 推理 token',fmt(think),'占输出 '+pct(think,t.o)+'%'],
    ['正文输出 token',fmt(body),'占输出 '+pct(body,t.o)+'%'],
    ['缓存命中率',pct(hit,hit+miss)+'%','命中 '+short(hit)+' / 未命中 '+short(miss)],
    ['原价积分',money(t.oc),t.oc>0?'有折扣记录':'无记录']
  ].map(([k,v,u])=>`<div><span>${k}</span><b>${v} <small style="color:#8a94a3;font-weight:400">${u}</small></b></div>`).join('');
}
function renderMisc(ev){
  const types=kv(ev.types,true);
  document.getElementById('typeBars').innerHTML=bars(types,d=>d.k,d=>d.t,d=>fmt(d.t)+' 条',12);
  const st=ev.status||{};
  const chips=[
    ['日志行数',fmt(ev.lines)],['推理消息',fmt(ev.reasoning)],['文件快照',fmt(ev.snapshots)],
    ['图片输入块',fmt(ev.images)],['工具调用次数',fmt(kv(ev.tools,true).reduce((s,x)=>s+x.t,0))],
    ['工具种类',fmt(kv(ev.tools,true).length)],
    ['执行完成',fmt(st.completed||0)],['执行中断',fmt(st.incomplete||0)],
    ['生成工具积分',money(ev.genCredit)]
  ];
  document.getElementById('miscChips').innerHTML=chips.map(([k,v])=>`<div class="chip">${k} <b>${v}</b></div>`).join('');
  document.getElementById('miscHint').textContent=`${Object.keys(ev.types).length} 种消息类型`;
  const q=DATA.quota||[];
  document.getElementById('quotaBox').innerHTML=q.length?
    '<div style="font-size:12px;color:var(--muted);margin-bottom:6px">模型配额（最近一次）</div><div class="chips">'+
    q.map(x=>{ let rt=''; const n=Number(x.resetAt); if(n){ const d=new Date(n>1e11?n:n*1000); if(!isNaN(d)) rt=' · 重置 '+d.toLocaleDateString('zh-CN'); }
      return `<div class="chip">${esc(x.model)} 已用 <b>${x.percent}%</b>${esc(rt)}</div>`; }).join('')+'</div>'
    :'<div style="font-size:12px;color:var(--muted)">无配额记录</div>';
}
function renderSessions(a,N){
  const meta={}; (DATA.sessions||[]).forEach(s=>meta[s.id]=s);
  const rows=a.sessionArr.filter(x=>x.k!=='unknown').map(x=>{
    const m=meta[x.k]||{title:x.k.slice(0,8),cwd:'',first:'',last:''};
    return {title:m.title,cwd:m.cwd,first:m.first,last:m.last,...x};
  }).sort((x,y)=>y.t-x.t);
  document.getElementById('sessionHint').textContent=`${rows.length} 个会话 · ${N==='all'?'全部历史':'近 '+N+' 天'}`;
  if(!rows.length){ document.getElementById('sessionRows').innerHTML='<tr><td colspan="6" style="text-align:center;color:#8a94a3">该范围无数据</td></tr>'; return; }
  document.getElementById('sessionRows').innerHTML=rows.map(r=>
    `<tr><td class="d" title="${esc(r.k)}">${esc(r.title)}</td><td style="text-align:left;max-width:190px;overflow:hidden;text-overflow:ellipsis" title="${esc(r.cwd)}">${esc(prettyProj(r.cwd))}</td>
     <td>${esc(r.first)} ~ ${esc(r.last)}</td><td>${fmt(r.n)}</td><td><b>${fmt(r.t)}</b></td><td>${money(r.cr)}</td></tr>`).join('');
}
function renderHours(ev){
  const items=[]; for(let h=0;h<24;h++){ const v=(ev.hours||{})[String(h)]||0; items.push({k:String(h).padStart(2,'0'),v}); }
  const peak=items.reduce((a,b)=>b.v>a.v?b:a,items[0]);
  document.getElementById('hourHint').textContent=`高峰 ${peak.k}:00 · ${fmt(peak.v)} 行`;
  document.getElementById('hourChart').innerHTML=svgBars(items,{W:430,H:170,axis:v=>short(v),labelEvery:3});
}
function renderDailyTable(a,ev){
  const sorted=a.dayArr.slice().sort((x,y)=>y.k.localeCompare(x.k));
  const max=Math.max(...sorted.map(d=>d.t),1);
  document.getElementById('tableHint').textContent=`共 ${sorted.length} 天`;
  if(!sorted.length){ document.getElementById('dailyRows').innerHTML='<tr><td colspan="10" style="text-align:center;color:#8a94a3">该范围无数据</td></tr>'; return; }
  document.getElementById('dailyRows').innerHTML=sorted.map(d=>{
    const dd=DATA.daily[d.k]||{tools:{}};
    const tools=Object.keys(dd.tools||{}).reduce((s,k)=>s+dd.tools[k],0);
    return `<tr><td class="d">${esc(d.k)}<span class="mini"><i style="width:${Math.max(2,Math.round(d.t/max*100))}%"></i></span></td>
      <td>${fmt(d.n)}</td><td>${fmt(d.i)}</td><td>${fmt(d.o)}</td><td><b>${fmt(d.t)}</b></td>
      <td>${pct(d.ch,d.ch+d.cm)}%</td><td>${fmt(d.th)}</td><td>${fmt(d.cm)}</td>
      <td>${money(d.cr)}</td><td>${fmt(tools)}</td></tr>`;
  }).join('');
}
function renderAll(N){
  const a=aggregate(rangeRecs(N)), ev=rangeDaily(N);
  document.getElementById('overview').innerHTML=overviewCards(a.total);
  renderCredit(a,ev); renderTokenBreak(a.total);
  document.getElementById('trend').innerHTML=trendBars(a.dayArr); bindBars();
  document.getElementById('trendHint').textContent=`${a.dayArr.length} 天 · ${fmt(a.total.n)} 次调用`;
  document.getElementById('modelBars').innerHTML=bars(a.modelArr,d=>modelName(d.k),d=>d.t,d=>short(d.t)+' · '+fmt(d.n)+'次');
  document.getElementById('projBars').innerHTML=bars(a.projArr,d=>prettyProj(d.k),d=>d.t,d=>short(d.t)+' · '+fmt(d.n)+'次',15);
  const tools=kv(ev.tools,true);
  document.getElementById('toolHint').textContent=`${tools.length} 种 · ${fmt(tools.reduce((s,x)=>s+x.t,0))} 次`;
  document.getElementById('toolBars').innerHTML=bars(tools,d=>d.k,d=>d.t,d=>fmt(d.t)+' 次',12);
  renderHours(ev); renderSessions(a,N); renderMisc(ev); renderDailyTable(a,ev);
}

document.getElementById('meta').innerHTML='数据更新于 '+esc(DATA.generatedAt)+'<br>共 '+DATA.records.length+' 次调用 / '+fmt(DATA.totalLines)+' 行日志 · '+esc(DATA.appName||'wbtool')+' v'+esc(DATA.appVersion||'');
document.getElementById('cards').innerHTML=periodCard('今天',1)+periodCard('近 7 天',7)+periodCard('近 30 天',30);
document.querySelectorAll('#ranges button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('#ranges button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); renderAll(b.dataset.n==='all'?'all':Number(b.dataset.n));
}));
renderAll(30);
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# 入口逻辑：路径解析 / 浏览器 / 日志 / 提示页 / 命令行
# ----------------------------------------------------------------------------
_LOG_REDIRECTED = False   # --windowed 打包后 stdout 指向日志文件，避免重复输出


def app_dir():
    """程序所在目录：PyInstaller 冻结后取 sys.executable，源码运行时取脚本路径。"""
    p = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve()
    return p.parent


def find_browser():
    """平台常见安装路径 → PATH 命令 → None（交给系统默认浏览器）。"""
    for c in BROWSER_CANDIDATES.get(platform.system(), []):
        if os.path.isfile(c):
            return c
    for cmd in BROWSER_COMMANDS:
        found = shutil.which(cmd)
        if found:
            return found
    return None


def open_report(path):
    """用标准 file:// URL 打开报告；优先 Edge/Chrome，最后交给 webbrowser。"""
    url = Path(path).resolve().as_uri()
    exe = find_browser()
    if exe:
        try:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def log_line(text):
    """写运行日志：程序目录 → 家目录 → 临时目录，只读环境自动降级。"""
    line = "[" + dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "] " + text + "\n"
    if not _LOG_REDIRECTED:
        try:
            print(line, end="")
        except Exception:
            pass
    for d in (app_dir(), HOME, Path(tempfile.gettempdir())):
        try:
            with (d / "wbtool.log").open("a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            continue


def write_report(html, explicit=None):
    """写报告；显式路径优先，否则依次尝试 程序目录 → 家目录 → 临时目录。

    这样即使 exe 被放在 C:\\Program Files 等只读位置也不会崩溃。
    """
    if explicit:
        targets = [Path(explicit).expanduser()]
    else:
        name = "wbtool_report.html"
        targets = [app_dir() / name, HOME / name, Path(tempfile.gettempdir()) / name]
    last = None
    for p in targets:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")
            return p
        except OSError as e:
            last = e
    raise RuntimeError(f"无法写入报告（已尝试 {len(targets)} 个位置）：{last}")


def notice_html(title, lines):
    """换电脑后无数据、或运行出错时显示的友好提示页（与主看板同一套浅色青蓝风格）。"""
    items = "".join("<li>" + esc_html(x) + "</li>" for x in lines)
    tpl = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · wbtool</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f4f7f8;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Roboto,Arial,sans-serif;font-size:14px;display:flex;justify-content:center;padding:64px 20px}
.box{background:#fff;border:1px solid #e8edf0;border-radius:16px;padding:28px 32px;max-width:680px;width:100%;box-shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.05)}
.hd{display:flex;align-items:center;gap:14px;margin-bottom:20px}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#0aa6b8,#36d4e0);color:#fff;font-weight:800;font-size:21px;display:flex;align-items:center;justify-content:center;flex:0 0 44px}
h1{font-size:19px;margin:0 0 4px;font-weight:700}
.sub{font-size:12px;color:#8a94a3;margin:0}
a{color:#07808f;text-decoration:none;font-weight:600}
a:hover{text-decoration:underline}
ul{margin:0;padding-left:20px;line-height:2.1;color:#475569}
code{background:#f1f6f7;padding:2px 6px;border-radius:5px;font-size:12.5px;word-break:break-all}
.tip{margin:20px 0 0;padding-top:14px;border-top:1px solid #e8edf0;font-size:12.5px;color:#8a94a3;line-height:1.8}
</style>
</head>
<body>
<div class="box">
  <div class="hd">
    <div class="logo">W</div>
    <div>
      <h1>__TITLE__</h1>
      <p class="sub">wbtool v__VERSION__ · <a href="__AUTHOR_URL__" target="_blank" rel="noopener noreferrer">作者:__AUTHOR__ ↗</a></p>
    </div>
  </div>
  <ul>__ITEMS__</ul>
  <p class="tip">本工具完全离线运行：只读取本机 WorkBuddy 会话日志中的统计字段，不联网、不上传、不修改原始数据，也不会内联任何对话正文。</p>
</div>
</body>
</html>"""
    return (tpl.replace("__TITLE__", esc_html(title))
               .replace("__VERSION__", __version__)
               .replace("__AUTHOR__", esc_html(AUTHOR))
               .replace("__AUTHOR_URL__", AUTHOR_URL)
               .replace("__ITEMS__", items))


def build_report(projects_dir, out=None, do_open=True):
    """核心流程：扫描 → 生成 → 打开。返回 (报告路径, 调用次数, 日志行数)。"""
    root = Path(projects_dir).expanduser()
    if not root.is_dir():
        html = notice_html("未找到 WorkBuddy 数据目录", [
            "期望位置：" + str(root),
            "请先安装并登录 WorkBuddy，产生会话记录后再运行本工具。",
            "数据目录可通过环境变量 WORKBUDDY_PROJECTS_DIR 或参数 --projects 指定。",
            "换一台电脑时，本报告统计的是那台电脑自己的用量数据。",
        ])
        p = write_report(html, out)
        if do_open:
            open_report(p)
        log_line(f"数据目录不存在：{root} → 已生成提示页 {p}")
        return p, 0, 0

    log_line(f"开始扫描 {root}")
    data = collect_all(root)
    if data["totalLines"] == 0:
        html = notice_html("数据目录里还没有会话记录", [
            "已找到目录：" + str(root),
            "但目录中没有可读取的 .jsonl 会话日志。",
            "使用 WorkBuddy 进行几次对话后，再运行本工具即可。",
        ])
        p = write_report(html, out)
        if do_open:
            open_report(p)
        log_line(f"目录内无 jsonl：{root} → 已生成提示页 {p}")
        return p, 0, 0

    data["today"] = dt.date.today().strftime("%Y-%m-%d")
    data["generatedAt"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["appName"] = APP_NAME
    data["appVersion"] = __version__
    data["author"] = AUTHOR
    data["authorUrl"] = AUTHOR_URL
    html = (HTML_TEMPLATE
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__ALIAS__", json.dumps(MODEL_ALIAS, ensure_ascii=False)))
    p = write_report(html, out)
    log_line(f"已生成报告 {p}（{len(data['records'])} 次调用 / {data['totalLines']} 行日志）")
    if do_open:
        log_line("已用浏览器打开报告" if open_report(p) else "未能自动打开浏览器，请手动打开报告文件")
    return p, len(data["records"]), data["totalLines"]


def parse_args(argv=None):
    """命令行参数定义。"""
    ap = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_NAME} v{__version__} — WorkBuddy 本地用量统计（作者：{AUTHOR} {AUTHOR_URL}）",
        epilog="项目主页: https://github.com/Xiaoqi969/wbtool",
    )
    ap.add_argument("--projects", metavar="DIR", default=str(PROJECTS_DIR),
                    help="会话日志目录，默认 ~/.workbuddy/projects")
    ap.add_argument("--out", metavar="FILE", help="报告输出路径，默认写到程序所在目录")
    ap.add_argument("--no-open", action="store_true", help="只生成报告，不自动打开浏览器")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap.parse_args(argv)


def main(argv=None):
    """程序入口；任何异常都会落日志并尽量显示一页友好提示。"""
    args = parse_args(argv)
    try:
        path, calls, lines = build_report(args.projects, args.out, not args.no_open)
        log_line(f"完成：{path}（{calls} 次调用 / {lines} 行日志）")
        return 0
    except Exception:
        err = traceback.format_exc()
        log_line("运行失败：\n" + err)
        try:
            html = notice_html("生成报告时出错", [
                "扫描或生成报告时发生异常，完整堆栈已写入 wbtool.log。",
                "请确认已安装 WorkBuddy 且数据目录可读。",
                err.strip().splitlines()[-1],
            ])
            open_report(write_report(html))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    # 统一控制台输出为 UTF-8：windowed exe 的 stdout 编码可能不是 UTF-8，
    # 否则中文日志在命令行里会显示成乱码（日志文件始终按 UTF-8 写入）。
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    # PyInstaller --windowed 打包后没有控制台，把 stdout/stderr 落到日志文件。
    if sys.stdout is None:
        for d in (app_dir(), HOME, Path(tempfile.gettempdir())):
            try:
                f = (d / "wbtool.log").open("a", encoding="utf-8")
                sys.stdout = f
                sys.stderr = f
                _LOG_REDIRECTED = True
                break
            except OSError:
                continue
    sys.exit(main())
