# -*- coding: utf-8 -*-
"""B4 验收探针：弹簧形变 / 中途反向 / 反复点击不漂移。

不是产品代码，只用来把「手感」量化成数字并留下帧截图。用完可删。
运行：
    python island_qt/_probe_b4.py            跑完整序列（约 18 秒），打印汇总
    python island_qt/_probe_b4.py --frames   额外把展开过程存成 PNG（%TEMP%/b4-*.png）

所有动作按绝对时间表调度（不是回调里再排下一个），事件循环有延迟时不会链断。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

from PySide6 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import IslandWindow  # noqa: E402
from window import CAPSULE_H, EXP_W  # noqa: E402


def color_backdrop() -> QtWidgets.QWidget:
    """铺一块彩色底，方便看玻璃是否跟着形状走。"""
    w = QtWidgets.QWidget(None, QtCore.Qt.WindowType.FramelessWindowHint
                          | QtCore.Qt.WindowType.WindowStaysOnTopHint)
    w.setGeometry(QtGui.QGuiApplication.primaryScreen().geometry())

    def paint(e):
        p = QtGui.QPainter(w)
        for i, x in enumerate(range(0, w.width(), 64)):
            p.fillRect(x, 0, 64, w.height(), QtGui.QColor.fromHsv((i * 24) % 360, 170, 220))
        p.end()

    w.paintEvent = paint  # type: ignore[method-assign]
    return w


class Recorder(QtCore.QObject):
    """按固定间隔记录 (t_ms, w, h, content_a, compact_a)。"""

    def __init__(self, win: IslandWindow) -> None:
        super().__init__()
        self.win = win
        self.rows: list[tuple[float, float, float, float, float]] = []
        self.t0 = time.perf_counter()
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._sample)

    def reset(self) -> None:
        self.rows.clear()
        self.t0 = time.perf_counter()
        self.timer.start()

    def snapshot(self) -> list[tuple[float, float, float, float, float]]:
        return list(self.rows)

    def _sample(self) -> None:
        w = self.win
        self.rows.append(((time.perf_counter() - self.t0) * 1000,
                          w.sw.x, w.sh.x, w.content_a.x, w.compact_a.x))


def summarize(rows, label: str, results: dict) -> None:
    if not rows:
        print(f"[{label}] no samples", flush=True)
        return
    ws = [r[1] for r in rows]
    hs = [r[2] for r in rows]
    dur = rows[-1][0]
    print(f"[{label}] {len(rows)} samples / {dur:.0f}ms ({len(rows) / dur * 1000:.0f} Hz) "
          f"w: {ws[0]:.0f}→max {max(ws):.0f}→{ws[-1]:.0f} | "
          f"h: {hs[0]:.0f}→max {max(hs):.0f}→{hs[-1]:.0f}", flush=True)
    jw = max((abs(ws[i] - ws[i - 1]) for i in range(1, len(ws))), default=0.0)
    jh = max((abs(hs[i] - hs[i - 1]) for i in range(1, len(hs))), default=0.0)
    print(f"[{label}] max step per sample: dw={jw:.1f}px dh={jh:.1f}px", flush=True)
    results[f"{label}_max_w"] = max(ws)
    results[f"{label}_max_h"] = max(hs)
    results[f"{label}_end_w"] = ws[-1]
    results[f"{label}_end_h"] = hs[-1]
    results[f"{label}_max_step"] = max(jw, jh)
    results[f"{label}_content_a"] = rows[-1][3]
    results[f"{label}_compact_a"] = rows[-1][4]


def save_frame(win: IslandWindow, name: str, outdir: str) -> None:
    path = os.path.join(outdir, name)
    win.grab().save(path)
    print(f"[frame] {path} w={win.sw.x:.0f} h={win.sh.x:.0f}", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    frames = "--frames" in argv
    outdir = tempfile.gettempdir()

    app = QtWidgets.QApplication(argv)
    app.setQuitOnLastWindowClosed(False)

    back = color_backdrop()
    back.show()

    win = IslandWindow()
    win.show()
    rec = Recorder(win)

    results: dict[str, float] = {}
    seq: list[tuple[float, float]] = []
    events: list[tuple[int, str, object]] = []

    def at(ms: int, fn) -> None:
        events.append((ms, fn))

    # ---- 时间表 ----
    at(1150, lambda: frames and save_frame(win, "b4-0-collapsed.png", outdir))
    at(1200, lambda: (rec.reset(), win.expand()))
    at(1200 + 60, lambda: frames and save_frame(win, "b4-a-60ms.png", outdir))
    at(1200 + 130, lambda: frames and save_frame(win, "b4-b-130ms.png", outdir))
    at(1200 + 220, lambda: frames and save_frame(win, "b4-c-220ms.png", outdir))
    at(1200 + 320, lambda: frames and save_frame(win, "b4-d-320ms.png", outdir))
    at(2500, lambda: frames and save_frame(win, "b4-e-settled.png", outdir))
    at(2600, lambda: summarize(rec.snapshot(), "expand", results))
    at(2700, lambda: (rec.reset(), win.collapse()))
    at(4200, lambda: summarize(rec.snapshot(), "collapse", results))

    # 中途反向：展开到一半再点一次
    at(4400, lambda: (rec.reset(), win.expand()))
    at(4700, win.collapse)
    at(6000, lambda: summarize(rec.snapshot(), "reverse", results))

    # 反复点 10 次：终态尺寸是否恒定
    base = 6200
    step_ms = 1100
    for i in range(10):
        at(base + i * step_ms, win.expand)
        at(base + i * step_ms + 450, win.collapse)
        at(base + i * step_ms + 1080,
           lambda: seq.append((win.sw.x, win.sh.x)))

    def finish() -> None:
        sizes = sorted({(round(a, 2), round(b, 2)) for a, b in seq})
        print(f"[repeat] 10 cycles collapsed sizes = {sizes}", flush=True)
        results["repeat_last_w"] = seq[-1][0] if seq else -1
        results["repeat_last_h"] = seq[-1][1] if seq else -1
        print("[summary]", flush=True)
        for k in ("expand_max_w", "expand_end_w", "expand_end_h", "expand_max_step",
                  "expand_content_a", "expand_compact_a",
                  "collapse_max_h", "collapse_end_h", "collapse_end_w",
                  "reverse_max_step", "reverse_end_w", "reverse_end_h",
                  "repeat_last_w", "repeat_last_h"):
            print(f"  {k} = {results.get(k)}", flush=True)
        overshoot = results.get("expand_max_w", 0) - EXP_W
        ok = (abs(results.get("expand_end_w", 0) - EXP_W) < 0.6
              and abs(results.get("collapse_end_w", 0) - win.compact.width) < 0.6
              and abs(results.get("expand_end_h", 0) - win._exp_h) < 0.6
              and abs(results.get("collapse_end_h", 0) - CAPSULE_H) < 0.6
              and abs(results.get("repeat_last_w", 0) - win.compact.width) < 0.6
              and abs(results.get("repeat_last_h", 0) - CAPSULE_H) < 0.6)
        print(f"[summary] overshoot={overshoot:.1f}px ({overshoot / EXP_W * 100:.1f}%) "
              f"terminal states exact = {ok}", flush=True)
        app.quit()

    at(base + 10 * step_ms + 400, finish)

    # ---- 单一驱动时钟：绝对时间到了就执行，事件循环卡顿只会推迟、不会丢 ----
    t0 = time.perf_counter()
    events.sort(key=lambda e: e[0])

    pump = QtCore.QTimer()
    pump.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    pump.setInterval(4)

    def tick() -> None:
        now = (time.perf_counter() - t0) * 1000
        while events and events[0][0] <= now:
            _, fn = events.pop(0)
            fn()
        if not events:
            pump.stop()

    pump.timeout.connect(tick)
    pump.start()

    print(f"[probe] capture dir = {outdir}", flush=True)
    QtCore.QTimer.singleShot(40000, app.quit)     # 兜底
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
