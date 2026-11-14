# -*- coding: utf-8 -*-
"""B9 启动优化 A/B 量测：扫描线程「首帧前启动」vs「首帧后启动」。

量三段（都相对进程启动）：
    win    IslandWindow 构造完成（含字体首次度量 + 毛玻璃初始化）
    paint  首帧真正画完（firstFrame 触发点）
    data   第一份 summary 送进窗口（胶囊开始显示真实数字）

用法：
    python island_qt/_probe_b9.py immediate 3
    python island_qt/_probe_b9.py defer 3
"""
from __future__ import annotations

import statistics
import sys
import time

T0 = time.perf_counter()          # 必须早于任何 import：这才是"双击到出画面"的口径

from pathlib import Path                     # noqa: E402

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parent), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6 import QtCore, QtWidgets        # noqa: E402


def one_run(mode: str) -> dict[str, float]:
    """跑一次完整启动，等到第一份数据就退出。"""
    t_run = time.perf_counter()   # 每次单独计时（T0 是进程级的，只对第一次有意义）
    marks: dict[str, float] = {}
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    import window as W
    from scan_service import ScanWorker

    win = W.IslandWindow()
    marks["win"] = time.perf_counter()

    worker = ScanWorker()

    def _on_data(_d) -> None:
        if "data" not in marks:
            marks["data"] = time.perf_counter()
            QtCore.QTimer.singleShot(0, app.quit)

    worker.summaryReady.connect(_on_data)        # 先记时间，再交给窗口
    worker.summaryReady.connect(win.apply_summary)

    def _on_first_frame(*_a) -> None:
        marks.setdefault("paint", time.perf_counter())
        if not worker.isRunning():
            worker.start()

    win.firstFrame.connect(_on_first_frame)
    if mode == "immediate":
        worker.start()                            # 旧行为：构造完就开扫，与首帧抢 GIL
    win.show()

    guard = QtCore.QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(app.quit)
    guard.start(20000)
    app.exec()

    worker.stop()
    worker.wait(3000)
    win.close()
    win.deleteLater()
    app.processEvents()
    return {k: (v - t_run) * 1000.0 for k, v in marks.items()}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "defer"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    rows = [one_run(mode) for _ in range(runs)]

    keys = ("win", "paint", "data")
    print(f"[{mode}] {runs} 次，单位 ms（相对进程启动）")
    print("  " + "  ".join(f"{k:>6s}" for k in keys))
    for r in rows:
        print("  " + "  ".join(f"{r.get(k, float('nan')):6.0f}" for k in keys))
    med = {k: statistics.median(r.get(k, float("nan")) for r in rows) for k in keys}
    print("  " + "  ".join(f"中位 {v:6.0f}" for k, v in med.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
