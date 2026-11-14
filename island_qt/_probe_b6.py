# -*- coding: utf-8 -*-
"""B6 验收探针：明细页高度 / 展开收起 / 高度平滑增长 / 空态 / 帧代价。

不是产品代码，用完可删。运行：
    python island_qt/_probe_b6.py             量测（约 14 秒）
    python island_qt/_probe_b6.py --frames    额外截图（%TEMP%/b6-*.png）

测什么：
  A 高度    n = 0 / 1 / 3 / 5 / 6 / 10 时的 preferred_height，超 5 行折成「还有 N 个」
  B 点击    真实鼠标事件展开 640×H、再点收回 274×34
  C 增长    展开态下会话 4 → 6：高度沿弹簧平滑增长，峰值过冲与单帧步进都不该像「跳」
  D 空态    没有进行中会话时给一行提示，卡片不塌
  E 帧代价  展开态静止 3 秒的 CPU 与停帧状态
  F 对账    面板上的今日 token / in / out / 积分 与报表 HTML 的聚合结果逐项相等
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time

from PySide6 import QtCore, QtGui, QtWidgets

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                      # island_qt（content/engine/ui）
sys.path.insert(0, os.path.dirname(_HERE))     # 项目根（scanlib / wb_usage_app）

from content.detail import MAX_ROWS, DetailPage  # noqa: E402
from window import IslandWindow  # noqa: E402

u32 = ctypes.windll.user32
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]


def sessions(n: int) -> list[dict]:
    names = ["监测work Buddy token消耗的软件推荐", "读取 git.json 文件", "d:\\gitprojects",
             "把灵动岛移植到 PySide6 并修掉 asar 那个坑", "修复托盘图标不跟随主题", "写 B6 明细页",
             "重构 scanner 的增量读取", "日报 HTML 的时间口径", "打包体积对比", "最后一个会话"]
    return [{"name": names[i % len(names)], "tokens": 99_600_000 / (i + 1),
             "last": f"22:{47 - i:02d}"} for i in range(n)]


def data(n: int, token=156_500_000) -> dict:
    return {"today": {"token": token, "credit": 214.31, "in": 155_600_000,
                      "out": 894_900, "ratePerSec": 243.3},
            "active": sessions(n), "files": 24, "updated": "22:47:03"}


# ================================================================ A
def test_height() -> None:
    d = DetailPage()
    base = None
    for n in (0, 1, 3, 5, 6, 10):
        d.set_summary(data(n))
        h = d.preferred_height()
        rows = d._rows()
        if base is None:
            base = h
        print(f"[A] n={n:2d} rows={rows} preferred_height={h:.0f}  (上限 5 行 + 溢出提示 = {MAX_ROWS + 1})",
              flush=True)
    d.set_summary(data(0))
    print(f"[A] 空态高度={d.preferred_height():.0f}（含一行「暂无」提示，卡片不塌）", flush=True)


# ================================================================ F 对账
def test_parity() -> None:
    """面板数字必须和报表 HTML 同源同值：两边都走 scanlib，这里确认没有第二套口径。"""
    import datetime as dt

    from scan_service import Tracker
    import wb_usage_app as report_app

    tr = Tracker()
    tr.scan_once()
    s = tr.summary()["today"]
    day = dt.datetime.now().strftime("%Y-%m-%d")
    recs = [r for r in report_app.collect_all()["records"] if r["d"] == day]
    rep = {"token": sum(r["t"] for r in recs), "in": sum(r["i"] for r in recs),
           "out": sum(r["o"] for r in recs), "credit": sum(r["cr"] for r in recs)}
    bad = [k for k in rep if abs(float(s.get(k) or 0) - rep[k]) > 0.01]
    print(f"[F] {day} 记录 {len(recs)} 条；灵动岛 {s['token']:,} / {s['in']:,} / {s['out']:,} / {s['credit']:.2f}", flush=True)
    print(f"[F] 报表     {rep['token']:,} / {rep['in']:,} / {rep['out']:,} / {rep['credit']:.2f}；"
          f"逐项相等={not bad}", flush=True)


# ================================================================ 点击 / 截图工具
def click(w: QtWidgets.QWidget) -> None:
    scr = w.screen()
    sg = scr.geometry()
    dpr = scr.devicePixelRatio() or 1.0
    g = w.mapToGlobal(w.body.center().toPoint())
    u32.SetCursorPos(int(sg.x() + (g.x() - sg.x()) * dpr), int(sg.y() + (g.y() - sg.y()) * dpr))


def save(win: IslandWindow, name: str, outdir: str) -> None:
    b = win.body
    r = QtCore.QRect(int(b.left()) - 16, int(b.top()) - 16, int(b.width()) + 32, int(b.height()) + 32)
    win.grab(r).save(os.path.join(outdir, name))
    print(f"[frame] {name}  body={b.width():.0f}x{b.height():.0f}", flush=True)


# ================================================================ 主流程
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    frames = "--frames" in argv
    outdir = tempfile.gettempdir()

    app = QtWidgets.QApplication(argv)
    app.setQuitOnLastWindowClosed(False)

    test_height()
    test_parity()

    win = IslandWindow()
    win.show()
    hz: list[tuple[float, float]] = []          # (ms, body.h) 用于看增长曲线

    t0 = time.perf_counter()

    def at(ms: int, fn) -> None:
        QtCore.QTimer.singleShot(max(0, int(ms - (time.perf_counter() - t0) * 1000)), fn)

    def click_and_wait(tag: str, after) -> None:
        """移动光标 → 60ms 后按键（立刻按会落在旧坐标上，测出来的结论是假的）。"""
        click(win)

        def fire() -> None:
            u32.mouse_event(2, 0, 0, 0, 0)
            u32.mouse_event(4, 0, 0, 0, 0)
        at(int((time.perf_counter() - t0) * 1000) + 60, fire)
        at(int((time.perf_counter() - t0) * 1000) + 80, after)

    # ---- B：展开 ----
    at(500, lambda: win.apply_summary(data(4)))
    at(900, lambda: print(f"[B] 收起  {win.body.width():.0f}x{win.body.height():.0f} "
                          f"exp_h={win._exp_h:.0f}", flush=True))
    at(1000, lambda: click_and_wait("expand", lambda: None))
    at(2000, lambda: (print(f"[B] 展开  {win.body.width():.0f}x{win.body.height():.0f} "
                            f"expanded={win.expanded}", flush=True),
                      frames and save(win, "b6-a-expanded.png", outdir)))

    # ---- C：展开态下 2 → 6 个会话，高度平滑增长 ----
    def grow() -> None:
        hz.clear()
        win.apply_summary(data(6))
        print(f"[C] 目标高度 {win._exp_h:.0f}，开始采样", flush=True)
        tick()

    sampler = QtCore.QTimer()
    sampler.setInterval(16)
    sampler.timeout.connect(lambda: hz.append(
        ((time.perf_counter() - t_grow) * 1000, win.body.height())))

    def tick() -> None:
        t = (time.perf_counter() - t_grow) * 1000
        hz.append((t, win.body.height()))
        if t < 1400:
            QtCore.QTimer.singleShot(16, tick)
        else:
            heights = [h for _, h in hz]
            peak = max(heights) - heights[-1]
            step = max((hz[i + 1][1] - hz[i][1] for i in range(len(hz) - 1)), default=0)
            settle = next((t for t, h in hz if abs(h - heights[-1]) < 0.5), 0.0)
            print(f"[C] 高度 {heights[0]:.0f} → {heights[-1]:.0f}，单帧最大步进={step:.2f}px，"
                  f"峰值过冲={peak:+.2f}px，{settle:.0f}ms 到位，采样 {len(hz)} 帧", flush=True)
            at(int((time.perf_counter() - t0) * 1000) + 100,
               lambda: frames and save(win, "b6-b-six.png", outdir))

    def start_grow() -> None:
        global t_grow
        t_grow = time.perf_counter()
        grow()

    at(2600, start_grow)

    # ---- D：空态 ----
    at(4600, lambda: win.apply_summary(data(0)))
    at(5400, lambda: (print(f"[D] 空态高度 {win.body.height():.0f}", flush=True),
                      frames and save(win, "b6-c-empty.png", outdir)))

    # ---- E：展开态静止 CPU ----
    def cpu_span(sec: float, tag: str) -> None:
        t_cpu, t_wall = time.process_time(), time.perf_counter()

        def done() -> None:
            dt = time.perf_counter() - t_wall
            print(f"[E] {tag}: CPU={(time.process_time() - t_cpu) / dt * 100:.2f}% "
                  f"timer={win.timer.isActive()}（应 False）", flush=True)
        at(int((time.perf_counter() - t0) * 1000 + sec * 1000), done)

    at(5600, lambda: cpu_span(3.0, "展开态静止"))

    # ---- 收起 ----
    at(9000, lambda: click_and_wait("collapse", lambda: None))
    at(10000, lambda: (print(f"[B] 收起  {win.body.width():.0f}x{win.body.height():.0f} "
                             f"expanded={win.expanded} timer={win.timer.isActive()}", flush=True),
                       win.close(), print("[done]", flush=True), app.quit()))

    QtCore.QTimer.singleShot(25000, app.quit)
    print(f"[probe] 截图目录 = {outdir}", flush=True)
    return app.exec()


t_grow = 0.0


if __name__ == "__main__":
    sys.exit(main())
