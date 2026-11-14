# -*- coding: utf-8 -*-
"""B5 验收探针：收起态排版 / 不抽搐 / 会话不入胶囊 / 帧代价。

不是产品代码，用完可删。运行：
    python island_qt/_probe_b5.py             量测（约 8 秒）
    python island_qt/_probe_b5.py --frames    额外截图（%TEMP%/b5-*.png）

测什么：
  A 布局     宽度、高 34、三格槽位（打印实测）
  B 不抽搐   四组数据各渲染一张，比较「积分起点以右」的像素是否完全一致
             —— 数字变长变短时，分隔点与后两格一格都不许动
  C 会话     只有 active 变化时 set_summary 返回 False、画面逐像素不变
             （2026-11-14 起收起态不展示进行中会话，只显示三格）
  D 帧代价   自然事件循环下：静止 3 秒的真实 CPU，且 16ms 循环必须是停的
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

from PySide6 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content.compact import PAD_L, PAD_R, Compact  # noqa: E402
from window import IslandWindow  # noqa: E402

QT = QtCore.Qt


# ================================================================ 工具
def render(compact: Compact, w: float, h: float, scale: int = 2) -> QtGui.QImage:
    """把收起态画到透明画布上（不依赖窗口，便于逐像素比对）。"""
    img = QtGui.QImage(int(w * scale), int(h * scale), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QT.GlobalColor.transparent)
    p = QtGui.QPainter(img)
    p.scale(scale, scale)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    compact.paint(p, QtCore.QRectF(0, 0, w, h), 1.0)
    p.end()
    return img


def diff_bbox(a: QtGui.QImage, b: QtGui.QImage) -> tuple[int, int, int, int] | None:
    """两张图不同像素的包围盒（图像坐标）。完全相同则返回 None。"""
    w, h = a.width(), a.height()
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if a.pixel(x, y) != b.pixel(x, y):
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
    return None if x1 < 0 else (x0, y0, x1, y1)


def ink_cols(img: QtGui.QImage, x_from: int) -> list[int]:
    """从 x_from 起，有笔画（alpha>0）的列号。用于证明右侧布局一动不动。"""
    cols = []
    for x in range(x_from, img.width()):
        for y in range(img.height()):
            if QtGui.QColor(img.pixel(x, y)).alpha() > 0:
                cols.append(x)
                break
    return cols


def data(token=57_400_000, credit=89.37, rate=243.3, active=None) -> dict:
    return {
        "today": {"token": token, "credit": credit, "in": 3, "out": 2, "ratePerSec": rate},
        "active": active or [],
        "files": 21,
        "updated": "22:30:00",
    }


LONG = [{"name": "把灵动岛移植到 PySide6 并且修掉 asar 那个坑", "tokens": 1, "last": "22:31"},
        {"name": "另一个会话", "tokens": 2, "last": "22:30"}]


# ================================================================ A / B / C
def test_layout() -> Compact:
    c = Compact()
    print(f"[A] width={c.width:.1f} h=34 x_credit={c._x_credit:.1f} x_rate={c._x_rate:.1f} "
          f"inner_end={c.width - PAD_R:.1f}", flush=True)
    print(f"[A] dx_token={c._dx_token:.1f} dx_credit={c._dx_credit:.1f} dx_rate={c._dx_rate:.1f} "
          f"baseline={c._baseline:.1f} label_h={c._fm_label.height()} value_h={c._fm_value.height()}",
          flush=True)
    print(f"[A] 宽度在 240~305 之间 = {240 <= c.width <= 305}", flush=True)
    return c


def test_no_jitter(c: Compact) -> None:
    cases = [("57.4M", 57_400_000), ("57.5M", 57_500_000),
             ("9.9M", 9_900_000), ("999.9K", 999_900)]
    imgs = []
    for name, tok in cases:
        c.set_summary(data(token=tok))
        imgs.append((name, render(c, c.width, 34)))

    ref_name, ref = imgs[0]
    cut = int((PAD_L + c._x_credit) * 2)          # 积分起点（图像坐标，scale=2）
    good = True
    for name, img in imgs[1:]:
        bbox = diff_bbox(ref, img)
        cols_same = ink_cols(ref, cut) == ink_cols(img, cut)
        inside = bbox is not None and bbox[2] < cut
        good = good and cols_same and inside
        print(f"[B] {ref_name} vs {name}: diff={bbox} 右侧像素一致={cols_same} 只在 Token 槽内={inside}",
              flush=True)
    print(f"[B] 结论：数字变化不牵动后半行 = {good}", flush=True)


def test_active_ignored(c: Compact) -> None:
    """会话列表进不了收起态：不触发变更、不改变一个像素。"""
    c.set_summary(data())
    before = render(c, c.width, 34)

    changed = c.set_summary(data(active=LONG))
    after = render(c, c.width, 34)
    print(f"[C] 只加会话：set_summary 返回 {changed}（应 False） 画面 diff={diff_bbox(before, after)}（应 None）",
          flush=True)

    # 数值变了才该重绘
    changed = c.set_summary(data(token=57_500_000, active=LONG))
    print(f"[C] 数值变化：set_summary 返回 {changed}（应 True）", flush=True)
    print(f"[C] text={c.plain_text()!r}", flush=True)


# ================================================================ D
def save(win: IslandWindow, name: str, outdir: str) -> None:
    """按逻辑坐标直接抓本体周围一块。

    **别用 `win.grab()` 整窗再裁**：整窗抓取在分层透明窗口上拿到的是一张不透明占位图，
    裁出来是纯黑 —— 一度以为画崩了，其实是取图方式错了。
    """
    b = win.body
    r = QtCore.QRect(int(b.left()) - 16, int(b.top()) - 16,
                     int(b.width()) + 32, int(b.height()) + 32)
    pm = win.grab(r)
    pm.save(os.path.join(outdir, name))
    print(f"[frame] {name}  body={b.width():.0f}x{b.height():.0f} grab={pm.width()}x{pm.height()}",
          flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    frames = "--frames" in argv
    outdir = tempfile.gettempdir()

    app = QtWidgets.QApplication(argv)
    app.setQuitOnLastWindowClosed(False)

    c = test_layout()
    test_no_jitter(c)
    test_active_ignored(c)

    win = IslandWindow()
    win.show()

    # 单一绝对时间表：到点执行一次，链式 singleShot 不额外占 CPU（CPU 量测要干净）
    t0 = time.perf_counter()

    def at(ms: int, fn) -> None:
        QtCore.QTimer.singleShot(max(0, int(ms - (time.perf_counter() - t0) * 1000)), fn)

    def cpu_span(sec: float, tag: str) -> None:
        t_cpu, t_wall = time.process_time(), time.perf_counter()

        def done() -> None:
            dt = time.perf_counter() - t_wall
            print(f"[D] {tag}: CPU={(time.process_time() - t_cpu) / dt * 100:.2f}% "
                  f"anim_timer={win.timer.isActive()}（应 False）", flush=True)
        at((time.perf_counter() - t0) * 1000 + sec * 1000, done)

    # 1) 只有三格数字
    at(600, lambda: win.apply_summary(data(token=123_910_000, credit=176.87, rate=243.3)))
    at(1400, lambda: frames and save(win, "b5-a-three.png", outdir))
    at(1500, lambda: cpu_span(3.0, "静止（三格）"))

    # 2) 有进行中会话：收起态一个字都不变，循环也不该被叫醒
    at(4800, lambda: win.apply_summary(
        data(token=123_910_000, credit=176.87, rate=243.3, active=LONG)))
    at(5000, lambda: frames and save(win, "b5-b-active.png", outdir))
    at(5100, lambda: cpu_span(3.0, "静止（有会话）"))

    def finish() -> None:
        win.close()
        print("[done]", flush=True)
        app.quit()

    at(8400, finish)

    QtCore.QTimer.singleShot(20000, app.quit)
    print(f"[probe] 截图目录 = {outdir}", flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
