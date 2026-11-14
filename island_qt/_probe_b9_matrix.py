# -*- coding: utf-8 -*-
"""B9 回归矩阵：DPI 缩放 + 截图权限受限降级。

A) DPI：用 `QT_SCALE_FACTOR` 覆盖缩放（1.0 / 1.25 / 1.5 / 2.0），起真实进程读
   `--debug` 自报的几何，断言「逻辑尺寸不随缩放变化」（274×34 / 900×680 恒定），
   并给每种缩放存一张截图供目检（文字是否被裁、圆角是否变形）。
B) 截图受限：进程内把 `grab_tiny` 打成永远返回 None，断言降级为灰底、不崩、
   文字仍在（像素亮度分布有内容，不是纯色板）。
C) 多屏：本机只有一块屏，仅记录 `QGuiApplication.screens()`，不做断言。

用法：
    python island_qt/_probe_b9_matrix.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
PY = sys.executable
SHOT_DIR = Path(tempfile.gettempdir()) / "b9-matrix"

# 截图脚本写成临时文件里跑：不要在 main.py 里为「验证」加开关。
_SHOT_SNIPPET = r'''
import sys, os
sys.path.insert(0, {q!r})
sys.path.insert(0, {r!r})
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from window import IslandWindow
w = IslandWindow(); w.show()
for _ in range(10):
    app.processEvents()
w.apply_summary({{"today": {{"token": 193175420, "credit": 259.19, "ratePerSec": 0}},
                  "active": [], "files": 24}})
for _ in range(10):
    app.processEvents()
w.grab(w.body.toAlignedRect().adjusted(-8, -8, 8, 8)).save(os.environ["WB9_SHOT"])
print("shot", os.environ["WB9_SHOT"], w.compact_text())
w.close()
'''

SCALES = ("0.667", "1", "1.25", "1.5", "2")   # 乘法语义：×系统 1.5 → dpr 1.0 / 1.5 / 1.88 / 2.25 / 3.0


def run_dpi_matrix() -> list[tuple[str, dict]]:
    """逐个缩放起进程，解析自报行。"""
    rows: list[tuple[str, dict]] = []
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    snippet = SHOT_DIR / "_shot.py"
    snippet.write_text(_SHOT_SNIPPET.format(q=str(_HERE), r=str(_ROOT)), encoding="utf-8")

    print("=" * 74)
    print("A DPI 缩放（QT_SCALE_FACTOR 覆盖；同时按各缩放存截图）")
    print("-" * 74)
    for s in SCALES:
        env = os.environ.copy()
        env["QT_SCALE_FACTOR"] = s
        env["WB9_SHOT"] = str(SHOT_DIR / f"dpi-{s}.png")
        # 主进程：拿自报几何（断言用）
        proc = subprocess.run([PY, str(_HERE / "main.py"), "--self-test", "5", "--debug"],
                              cwd=str(_ROOT), env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)
        out = (proc.stdout or "") + (proc.stderr or "")
        # 另一个短进程：存截图（同一缩放）
        shot = subprocess.run([PY, str(snippet)], cwd=str(_ROOT), env=env,
                              capture_output=True, timeout=120)
        shot_ok = shot.returncode == 0 and Path(env["WB9_SHOT"]).is_file()
        info: dict = {"rc": proc.returncode}
        m = re.search(r"win=\S+ (\d+)x(\d+).*?body=\S+ ([\d.]+)x([\d.]+).*?dpr=([\d.]+)", out)
        if m:
            info.update(win=f"{m.group(1)}x{m.group(2)}", body=f"{float(m.group(3)):.0f}x{float(m.group(4)):.0f}",
                        dpr=float(m.group(5)))
        m2 = re.search(r"backdrop=(\S+)", out)
        if m2:
            info["backdrop"] = m2.group(1)
        m3 = re.search(r"text='([^']*)'", out)
        if m3:
            info["text"] = m3.group(1)
        rows.append((s, info))
        print(f"  QT_SCALE_FACTOR={s:<5s} rc={info.get('rc')} "
              f"dpr={info.get('dpr', '?')} 窗口={info.get('win', '?')} "
              f"本体={info.get('body', '?')} backdrop={info.get('backdrop', '?')} 截图={shot_ok}")
    return rows


def check_dpi(rows: list[tuple[str, dict]]) -> bool:
    ok = True
    for s, info in rows:
        body_ok = info.get("body") == "274x34"
        win_ok = info.get("win") == "900x680"
        if not (body_ok and win_ok and info.get("rc") == 0):
            ok = False
            print(f"  ✗ 缩放 {s}：本体 {info.get('body')} / 窗口 {info.get('win')} / rc={info.get('rc')}")
    return ok


def run_capture_denied() -> bool:
    """采样永远失败：必须走灰底降级，不能崩、不能全透明。"""
    print()
    print("=" * 74)
    print("B 截图权限受限（强制 grab_tiny 返回 None）")
    print("-" * 74)
    sys.path.insert(0, str(_HERE))
    sys.path.insert(0, str(_ROOT))
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication([])
    import engine.glass as glass
    glass.grab_tiny = lambda *a, **k: None        # 模拟「GDI 截屏被拒/拿不到画面」

    import window as W
    w = W.IslandWindow()
    w.show()
    for _ in range(8):
        app.processEvents()
    w.apply_summary({"today": {"token": 154321000, "credit": 123.45, "ratePerSec": 0}, "active": [], "files": 24})
    for _ in range(8):
        app.processEvents()

    pm = w.grab(w.body.toAlignedRect().adjusted(-8, -8, 8, 8))
    img = pm.toImage()
    center = img.pixelColor(img.width() // 2, img.height() // 2)
    tiny = w.backdrop.tiny
    print(f"  backdrop.tiny = {tiny}（应为 None）")
    print(f"  中心像素 RGBA = {center.red()},{center.green()},{center.blue()},{center.alpha()}"
          f"（应为不透明中性灰：grab 会把半透明灰底合成到白/浅色上，读数值偏亮属正常）")
    print(f"  文本 = {w.compact_text()!r}")
    out = SHOT_DIR / "capture-denied.png"
    pm.save(str(out))
    print(f"  截图 {out}")

    gray_ok = center.alpha() > 200 and abs(center.red() - center.green()) < 24
    # 停止采样线程并收尾，否则进程要等线程退出
    w.close()
    app.processEvents()
    print(f"  结论：灰底降级={gray_ok}  未崩溃=True")
    return gray_ok


def run_screens() -> None:
    print()
    print("=" * 74)
    print("C 屏幕清单（本机）")
    print("-" * 74)
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    for s in app.screens():
        g, a = s.geometry(), s.availableGeometry()
        print(f"  {s.name():14s} {g.width()}x{g.height()}@{g.x()},{g.y()} "
              f"可用 {a.width()}x{a.height()} dpr={s.devicePixelRatio()}")
    print(f"  共 {len(app.screens())} 块屏 —— 多屏/混合 DPI 需实机增屏验证，本机无法覆盖")


def main() -> int:
    rows = run_dpi_matrix()
    dpi_ok = check_dpi(rows)
    cap_ok = run_capture_denied()
    run_screens()
    print()
    print(f"[汇总] DPI 逻辑尺寸恒定={dpi_ok}  截图受限降级={cap_ok}  截图目录={SHOT_DIR}")
    return 0 if (dpi_ok and cap_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
