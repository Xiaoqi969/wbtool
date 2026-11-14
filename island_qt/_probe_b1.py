# -*- coding: utf-8 -*-
"""B1 验收探针：在灵动岛背后铺一块高对比彩色底，用于肉眼/截图判断毛玻璃是否真的糊了。

不是产品代码，只用于「玻璃是否真模糊」的可视化验收。用完可删。
运行：python island_qt/_probe_b1.py --self-test 12
"""
from __future__ import annotations

import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import IslandWindow  # noqa: E402


class ColorBackdrop(QtWidgets.QWidget):
    """全屏彩色条纹 + 大字号，模糊后应变成柔和的色带、文字应糊成色块。"""

    def __init__(self) -> None:
        super().__init__(
            None,
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint,   # 否则会被 WorkBuddy 等置顶窗口盖住
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        scr = QtGui.QGuiApplication.primaryScreen()
        self.setGeometry(scr.geometry())

    def paintEvent(self, e: QtGui.QPaintEvent) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        w, h = self.width(), self.height()
        step = 56
        for i, x in enumerate(range(0, w, step)):
            c = QtGui.QColor.fromHsv((i * 26) % 360, 215, 235)
            p.fillRect(x, 0, step, h, c)
        # 顶部 140px：8px 黑白高频细条纹 —— 玻璃生效时会被糊成均匀灰带；
        # 若仍能看清条纹，说明模糊没起作用。胶囊（y≈15..93 物理）正压在这条带上。
        for x in range(0, w, 8):
            c = QtGui.QColor(255, 255, 255) if (x // 8) % 2 else QtGui.QColor(0, 0, 0)
            p.fillRect(x, 0, 8, 140, c)
        # 下半屏大字号：模糊后应变成灰块
        p.setPen(QtGui.QColor(0, 0, 0, 230))
        f = p.font()
        f.setPixelSize(120)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QtCore.QRect(0, h // 2, w, h // 2),
                   QtCore.Qt.AlignmentFlag.AlignCenter, "GLASS TEST 毛玻璃")
        p.end()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QtWidgets.QApplication(argv)
    app.setQuitOnLastWindowClosed(False)

    back = ColorBackdrop()
    back.show()          # 铺满整屏的彩色底（不 lower，否则会被别的窗口盖住）

    win = IslandWindow()
    win.show()           # 置顶显示

    g = win.geometry()
    print(f"[probe] island={g.x()},{g.y()} {g.width()}x{g.height()}", flush=True)

    sec = 12
    if "--self-test" in argv:
        i = argv.index("--self-test")
        if i + 1 < len(argv):
            try:
                sec = int(argv[i + 1])
            except ValueError:
                pass

    if "--dump" in argv:
        # 把 Backdrop 采到的缩略图放大存盘，直接看「玻璃里到底是什么」
        import tempfile

        def _dump() -> None:
            tiny = win.backdrop.tiny
            if tiny is None:
                print("[probe] tiny=None", flush=True)
            else:
                out = os.path.join(tempfile.gettempdir(), "b1-backdrop-tiny.png")
                tiny.scaled(tiny.width() * 8, tiny.height() * 8).save(out)
                print(f"[probe] dump={out} size={tiny.width()}x{tiny.height()}", flush=True)
            app.quit()

        QtCore.QTimer.singleShot(4000, _dump)

    if "--cpu" in argv:
        # 自测：用进程自身的 CPU 时间除以墙钟，得到「占单核百分比」
        import time

        t0 = time.process_time()
        w0 = time.perf_counter()

        def _cpu_report() -> None:
            cpu = time.process_time() - t0
            wall = time.perf_counter() - w0
            print(f"[probe] cpu={cpu / wall * 100:.1f}% of core  ({cpu:.2f}s / {wall:.1f}s)",
                  flush=True)
            app.quit()

        QtCore.QTimer.singleShot(10000, _cpu_report)

    QtCore.QTimer.singleShot(sec * 1000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
