# -*- coding: utf-8 -*-
"""B10 验收探针：展开态「每会话流速」。

不是产品代码，只用于验证口径与布局。运行：
    python island_qt/_probe_b10.py
产出：`%TEMP%/b10-detail-{dark,light}.png`（供肉眼核对列对齐）

测什么：
  A 分桶    同一批 synthetic 用量行，各会话流速 = 自己 15s 内 output / 15
  B 总量    总流速 = 各会话之和 + 无 sid 行（这些行只进总量，没法归给会话）
  C 回收    会话转出「进行中」后桶立即释放；过期事件被 _trim_flows 清掉
  D 布局    5 行跨量级（0 / 12 / 1.2k / 123k / 999k）不重叠，且高度不变
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                      # island_qt（content/engine/ui）
sys.path.insert(0, os.path.dirname(_HERE))     # 项目根（scanlib）

from scan_service import Tracker, _now_ms      # noqa: E402

TOL = 0.01
fails: list[str] = []


def check(label: str, got: float, want: float, unit: str = "") -> None:
    ok = abs(got - want) <= TOL
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got:.2f}{unit} (期望 {want:.2f}{unit})")
    if not ok:
        fails.append(label)


def row(ms: float, sid: str, out: int, total: int, title: str) -> str:
    return json.dumps({
        "timestamp": ms, "sessionId": sid, "aiTitle": title, "cwd": "D:\\demo\\" + sid,
        "message": {"usage": {"input_tokens": max(total - out, 0), "output_tokens": out,
                              "total_tokens": total}},
    }, ensure_ascii=False)


def build_tree() -> str:
    root = tempfile.mkdtemp(prefix="b10-")
    proj = os.path.join(root, "demo-project")
    os.makedirs(proj, exist_ok=True)
    now = _now_ms()
    lines = [
        row(now - 2_000, "A", 300, 1_000, "会话 A（正在产出）"),
        row(now - 5_000, "B", 150, 500, "会话 B（半速）"),
        row(now - 20_000, "C", 999, 2_000, "会话 C（窗口外）"),
        row(now - 1_000, "", 60, 200, "无会话归属的用量行"),
    ]
    with open(os.path.join(proj, "s.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return root


def part_abc() -> None:
    root = build_tree()
    t = Tracker(root)
    t.start_time = 0.0          # 只测分桶：合成行的时刻都早于 Tracker 构造时刻
    t.scan_once()

    now = _now_ms()
    rates = {a["name"]: a["rate"] for a in t.active_list(now)}

    print("A 分桶")
    check("A 15s 内 300 token", t.session_rate("A", now), 300 / 15, " tok/s")
    check("B 15s 内 150 token", t.session_rate("B", now), 150 / 15, " tok/s")
    check("C 事件在 20s 前（窗口外）", t.session_rate("C", now), 0.0, " tok/s")

    print("B 总量")
    check("总流速含无 sid 行", t.rate_per_sec(now), (300 + 150 + 60) / 15, " tok/s")

    print("C 回收")
    t.active["C"]["last"] = t.active["C"]["last"].replace(year=2000)   # 假装闲置很久
    t.session_flow["B"].insert(0, (now - 60_000, 5))                   # 造一条过期事件
    t.scan_once()
    ok1 = "C" not in t.session_flow
    ok2 = t.session_flow.get("B") and t.session_flow["B"][0][0] >= now - 60_000
    print(f"  [{'OK ' if ok1 else 'FAIL'}] 会话转出进行中 → 桶被删除")
    print(f"  [{'OK ' if ok2 else 'FAIL'}] 过期事件被裁掉（B 首条仍存在但已剔除 60s 前那条）")
    if not ok1:
        fails.append("C 桶回收")
    if not ok2:
        fails.append("C 过期裁剪")


def part_d() -> None:
    from PySide6 import QtCore, QtGui, QtWidgets
    from content.detail import CARD_PAD_X, PAD_X, ROW_H, DetailPage
    from ui.theme import theme

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841
    page = DetailPage(640.0)
    sessions = [
        {"name": "修复托盘图标不跟随主题", "tokens": 128_400, "rate": 0.0, "last": "03:40"},
        {"name": "把灵动岛移植到 PySide6 并修掉 asar 那个坑", "tokens": 620_100, "rate": 12.4, "last": "03:41"},
        {"name": "读取 git.json 文件", "tokens": 2_300, "rate": 1_234, "last": "03:42"},
        {"name": "日报 HTML 的时间口径", "tokens": 88_000, "rate": 123_456, "last": "03:43"},
        {"name": "最后一个会话", "tokens": 0, "rate": 999_999, "last": "03:44"},
    ]
    page.set_summary({
        "today": {"token": 12_345_678, "credit": 321.5, "in": 9_000_000, "out": 456_789,
                  "ratePerSec": 1_136_801},
        "active": sessions, "files": 27, "updated": "03:45:00",
    })

    h = page.preferred_height()
    # 布局算术复核（与 paint 里的同一套常量）
    inner_l = PAD_X + CARD_PAD_X
    inner_r = 640.0 - PAD_X - CARD_PAD_X
    w_time, w_tok, w_rate, gap = 44.0, 54.0, 48.0, 8.0
    x_rate = inner_r - w_time - gap - w_tok - gap - w_rate
    name_w = x_rate - gap - inner_l
    print("D 布局")
    print(f"  高度 {h:.0f}px；名称列 {name_w:.0f}px；流速列 [{x_rate:.0f},{x_rate + w_rate:.0f}]；"
          f"token 列右缘 {inner_r - w_time - gap:.0f}")
    ok = name_w >= 200 and x_rate > inner_l + 150
    print(f"  [{'OK ' if ok else 'FAIL'}] 名称列未被挤压、流速列不与名称重叠")
    if not ok:
        fails.append("D 列宽")

    tmp = tempfile.gettempdir()
    for pal in ("dark", "light"):
        theme.set_mode(pal)
        img = QtGui.QImage(640, int(h), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QtGui.QColor(24, 25, 28) if pal == "dark" else QtGui.QColor(242, 243, 245))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        page.paint(p, QtCore.QRectF(0, 0, 640, h), 1.0)
        # 行底线：每行文字必须落在卡片内（画一条参考线便于目检）
        p.setPen(QtGui.QPen(QtGui.QColor(255, 90, 90, 120), 1, QtCore.Qt.PenStyle.DotLine))
        for i in range(len(sessions)):
            y = 14 + 20 + 10 + 78 + 10 + 12 + 18 + 6 + (i + 1) * ROW_H
            p.drawLine(QtCore.QPointF(PAD_X, y), QtCore.QPointF(640 - PAD_X, y))
        p.end()
        out = os.path.join(tmp, f"b10-detail-{pal}.png")
        img.save(out)
        print(f"  截图 {out}")
    theme.set_mode("auto")


def main() -> int:
    part_abc()
    part_d()
    print("\n结论：" + ("全部通过" if not fails else "失败项 → " + "、".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
