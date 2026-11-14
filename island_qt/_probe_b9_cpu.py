# -*- coding: utf-8 -*-
"""B9 稳态量测：扫描间隔改回 10 秒后，常驻 CPU 与扫描节拍。

做什么：
  - 起真实窗口 + 真实 ScanWorker，跑 70 秒
  - 记 CPU 占比（time.process_time / wall）与 summaryReady 次数

为什么关心：v1.3.0 是 10 秒一刷（流速才"活"），Qt 版一度写成 60 秒。
改回 10 秒必须确认「增量读」真的增量——否则每 10 秒全量重扫 1.7 秒，CPU 会明显上去。

用法：python island_qt/_probe_b9_cpu.py [秒数]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE.parent), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6 import QtCore, QtWidgets       # noqa: E402

SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 70.0


def main() -> int:
    app = QtWidgets.QApplication([])
    from scan_service import SCAN_INTERVAL_SEC, ScanWorker
    from window import IslandWindow

    win = IslandWindow()
    win.show()

    seen: list[float] = []
    worker = ScanWorker()

    # 首次全量扫描（约 1.7s 读 20+ 个 jsonl）是一次性成本，不该摊进「常驻」：
    # 第一份 summary 到达时把 CPU 计时归零，之后量到的才是稳态增量扫描的代价。
    marks = {"t_wall": time.perf_counter(), "t_cpu": time.process_time()}

    def _on_summary(_d: dict) -> None:
        if not seen:
            marks["t_wall"] = time.perf_counter()
            marks["t_cpu"] = time.process_time()
        seen.append(time.perf_counter())

    worker.summaryReady.connect(_on_summary)
    worker.summaryReady.connect(win.apply_summary)
    worker.start()

    QtCore.QTimer.singleShot(int(SEC * 1000), app.quit)
    app.exec()
    wall = time.perf_counter() - marks["t_wall"]
    cpu = (time.process_time() - marks["t_cpu"]) / wall * 100

    worker.stop()
    worker.wait(3000)
    win.close()

    gaps = [round((b - a), 1) for a, b in zip(seen, seen[1:])]
    print(f"间隔设定 {SCAN_INTERVAL_SEC}s | 实际扫描 {len(seen)} 次 / {wall:.0f}s")
    print(f"相邻两次间隔（秒）：{gaps}")
    print(f"常驻 CPU（含窗口+扫描）：{cpu:.2f}%")
    print(f"文本：{win.compact_text() if hasattr(win, 'compact_text') else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
