# -*- coding: utf-8 -*-
"""island_qt/_probe_b7.py — B7（拖拽 / 位置记忆 / 减弱动效 / 单实例）验收探针。

    python island_qt/_probe_b7.py              量测 + 结论
    python island_qt/_probe_b7.py --frames     额外截一张拖拽后的样子

用 **真实鼠标事件**（SetCursorPos + mouse_event）而不是 QTest：拖拽走的是
「按下 → WM_MOUSEMOVE → 窗口跟着移」这条真实链路，投递合成 Qt 事件测不到
隐式 grab、穿透判定和分层窗口移动这些真正会出问题的地方。

七段：
  A 拖拽      真实鼠标拖 +320,+200：窗口该跟着走，本体位移应等量
  B 夹边      拖到屏幕左上角外面：本体至少留 80×40 在屏内
  C 记忆      重建窗口（等价于重启进程）后回到上次拖到的位置
  D 点击      位移在阈值内的按下-松开仍然是展开/收起，没被拖拽吞掉
  E 置顶      关掉「锁定置顶」后 WS_EX_TOPMOST 消失，勾回来恢复
  F 减弱动效  要求减少动画时，展开一步到位、16ms 循环不启动
  G 单实例    第二个实例通过本地管道唤回第一个

探针会改 prefs 里的位置，跑完自动还原。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from prefs import save_prefs, saved_body_pos  # noqa: E402
from window import CAPSULE_H, IslandWindow, read_reduced_motion  # noqa: E402

u32 = ctypes.WinDLL("user32")
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
OUT = os.environ.get("TEMP") or "."
STEP_MS = 14          # 每步 14ms：约 70Hz 的移动事件，够 Qt 每帧都收到


# ================================================================ 鼠标
def phys(p: QtCore.QPoint) -> tuple[int, int]:
    """逻辑坐标 → 物理坐标（Qt 在 Windows 上保持屏幕原点不缩放）。"""
    scr = QtWidgets.QApplication.screenAt(p) or QtGui.QGuiApplication.primaryScreen()
    sg = scr.geometry()
    d = scr.devicePixelRatio() or 1.0
    return (int(round(sg.x() + (p.x() - sg.x()) * d)),
            int(round(sg.y() + (p.y() - sg.y()) * d)))


def set_cursor(p: QtCore.QPoint) -> None:
    u32.SetCursorPos(*phys(p))


def mouse_down() -> None:
    u32.mouse_event(2, 0, 0, 0, 0)


def mouse_up() -> None:
    u32.mouse_event(4, 0, 0, 0, 0)


def topmost(hwnd: int) -> bool:
    return bool(u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


# ================================================================ 时间表
class Plan:
    """按绝对时间执行动作。用真实时钟而不是链式 singleShot：
    鼠标、动画、采样都是异步的，链式调用容易在等待中把后续动作排乱。"""

    def __init__(self) -> None:
        self.items: list[tuple[int, object]] = []
        self.t0 = time.perf_counter()
        self.timer = QtCore.QTimer()
        self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._pump)

    def at(self, ms: int, fn) -> None:
        self.items.append((ms, fn))
        self.items.sort(key=lambda it: it[0])

    def _pump(self) -> None:
        now = (time.perf_counter() - self.t0) * 1000
        while self.items and self.items[0][0] <= now:
            _, fn = self.items.pop(0)
            fn()
        if not self.items:
            self.timer.stop()

    def run(self, timeout_ms: int = 20000) -> None:
        self.timer.start()
        QtCore.QTimer.singleShot(timeout_ms, QtWidgets.QApplication.instance().quit)
        QtWidgets.QApplication.instance().exec()


def drag(plan: Plan, win: IslandWindow, at_ms: int, dx: int, dy: int, steps: int = 16) -> int:
    """从胶囊中心按下，分步移动 +dx,+dy 后松开。返回松手的时刻。"""
    center: list[QtCore.QPoint] = []

    def prepare() -> None:
        center.append(win.mapToGlobal(win.body.center().toPoint()))
        set_cursor(center[0])

    plan.at(at_ms, prepare)
    plan.at(at_ms + 90, mouse_down)
    for i in range(1, steps + 1):
        plan.at(at_ms + 90 + i * STEP_MS,
                lambda i=i: set_cursor(QtCore.QPoint(
                    round(center[0].x() + dx * i / steps),
                    round(center[0].y() + dy * i / steps))))
    # 松手比最后一帧移动晚 30ms：同一时刻会「先松开、后处理移动」，
    # 丢掉最后一格 20px，位移量出来就少一截。
    end = at_ms + 90 + steps * STEP_MS + 30
    plan.at(end, mouse_up)
    return end


# ================================================================ 主体
def main() -> int:
    frames = "--frames" in sys.argv
    original = saved_body_pos()
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)

    win = IslandWindow()
    win.show()
    plan = Plan()
    seen: dict = {}

    # ---- A 拖拽 ----
    def report_start() -> None:
        seen["start"] = win.body_origin()
        print(f"[起] 本体 {seen['start'][0]:.0f},{seen['start'][1]:.0f}  "
              f"窗口 {win.pos().x()},{win.pos().y()}  截图={frames}  "
              f"pinned={win.pinned} reduced={win.reduced}", flush=True)

    plan.at(300, report_start)
    end_a = drag(plan, win, 500, 320, 200)

    def report_a() -> None:
        bx, by = win.body_origin()
        dx, dy = bx - seen["start"][0], by - seen["start"][1]
        seen["a"] = (bx, by)
        print(f"[A] 拖 +320,+200 → 实际位移 {dx:+.0f},{dy:+.0f}  "
              f"dragging={win.dragging}  窗口 {win.pos().x()},{win.pos().y()}", flush=True)

    plan.at(end_a + 250, report_a)

    # ---- B 夹边 ----
    end_b = drag(plan, win, end_a + 500, -2600, -2600)

    def report_b() -> None:
        bx, by = win.body_origin()
        w, h = win.body.width(), win.body.height()
        a = win.screen().availableGeometry()
        lo_x, hi_x = a.left() - w + 80, a.right() + 1 - 80
        lo_y, hi_y = a.top() - 8, a.bottom() + 1 - 40
        inside = lo_x - 1.5 <= bx <= hi_x + 1.5 and lo_y - 1.5 <= by <= hi_y + 1.5
        vis_w = min(a.right() + 1, bx + w) - max(a.left(), bx)
        vis_h = min(a.bottom() + 1, by + h) - max(a.top(), by)
        print(f"[B] 拖到屏幕外 → 本体 {bx:.0f},{by:.0f}  允许区间 "
              f"x[{lo_x:.0f},{hi_x:.0f}] y[{lo_y:.0f},{hi_y:.0f}]  在区间内={inside}  "
              f"屏内可见 {vis_w:.0f}x{vis_h:.0f}（左上角贴边时允许出顶 8px）", flush=True)

    plan.at(end_b + 250, report_b)

    if frames:
        def shot() -> None:
            b = win.body
            r = QtCore.QRect(int(b.left()) - 16, int(b.top()) - 16,
                             int(b.width()) + 32, int(b.height()) + 32)
            win.grab(r).save(os.path.join(OUT, "b7-dragged.png"))
            print(f"[frame] b7-dragged.png  body={b.width():.0f}x{b.height():.0f}", flush=True)
        plan.at(end_b + 300, shot)

    # ---- C 前置：把窗口挪回屏幕中间，方便后面点 ----
    def recenter() -> None:
        a = win.screen().availableGeometry()
        bx = a.left() + a.width() / 2 - win.body.width() / 2
        by = a.top() + 60
        p = win.pos()
        win.move(int(round(bx - win.body.x())), int(round(by - win.body.y())))
        win._win_origin = (win.pos().x(), win.pos().y())
        print(f"[C] 挪回中间：本体 {bx:.0f},{by:.0f}", flush=True)

    plan.at(end_b + 700, recenter)

    # ---- D 点击（阈值内） ----
    def click() -> None:
        set_cursor(win.mapToGlobal(win.body.center().toPoint()))

    t_click = end_b + 1100
    plan.at(t_click, click)
    plan.at(t_click + 120, mouse_down)
    plan.at(t_click + 200, mouse_up)

    def report_d() -> None:
        print(f"[D] 原地点击 → expanded={win.expanded}  "
              f"尺寸 {win.body.width():.0f}x{win.body.height():.0f}", flush=True)

    plan.at(t_click + 1400, report_d)
    plan.at(t_click + 1500, lambda: win.collapse() if win.expanded else None)

    # ---- E 置顶 ----
    def pin_probe() -> None:
        hwnd = int(win.winId())
        before = topmost(hwnd)
        win.set_pinned(False, persist=False)
        off = topmost(hwnd)
        win.set_pinned(True, persist=False)
        on = topmost(hwnd)
        print(f"[E] WS_EX_TOPMOST  初始={before}  关闭后={off}  恢复后={on}", flush=True)

    plan.at(t_click + 2200, pin_probe)

    # ---- F 减弱动效 ----
    def reduced_on() -> None:
        win.reduced = True
        t = time.perf_counter()
        win.expand()
        tw, th = win.target_size()
        ms = (time.perf_counter() - t) * 1000
        print(f"[F] reduced 展开：立即 {win.body.width():.0f}x{win.body.height():.0f}"
              f"（目标 {tw:.0f}x{th:.0f}）耗时 {ms:.2f}ms  anim_timer={win.timer.isActive()}",
              flush=True)
        win.collapse()
        print(f"[F] reduced 收起：立即 {win.body.width():.0f}x{win.body.height():.0f}"
              f"（目标 {win.compact.width:.0f}x{CAPSULE_H}）"
              f"  anim_timer={win.timer.isActive()}", flush=True)
        win.reduced = read_reduced_motion()

    plan.at(t_click + 2600, reduced_on)

    # ---- G 单实例 ----
    def single_instance() -> None:
        import subprocess

        from single import InstanceServer, notify_existing

        srv = InstanceServer()
        fired: list[int] = []
        srv.activated.connect(lambda: fired.append(1))
        child_box: list = []

        def send() -> None:
            # listen() 之后要先进一次事件循环，Windows 上的管道实例才真正就绪；
            # 同一回调里立刻去连，会「连得上但服务端永远收不到 newConnection」。
            ok = notify_existing(800)
            print(f"[G] 监听={srv.listening}  进程内唤回={ok}", flush=True)
            # 真实的第二实例：另起一个进程，走 main.py 里同一条路径
            code = (f"import sys; sys.path.insert(0, {_HERE!r}); "
                    "from single import notify_existing; "
                    "sys.exit(0 if notify_existing(1500) else 1)")
            child_box.append(subprocess.Popen([sys.executable, "-c", code],
                                              stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL))

        def check() -> None:
            # wait() 是阻塞的，阻塞期间 newConnection 排不上队 —— 等它返回后
            # 再让事件循环转 250ms 才读信号，否则永远是「收到 0 次」。
            rc = child_box[0].wait(timeout=5) if child_box else -1
            QtCore.QTimer.singleShot(250, lambda: report(rc))

        def report(rc: int) -> None:
            print(f"[G] 第二实例唤回退出码={rc}（0=送达）  本进程收到信号={len(fired)} 次",
                  flush=True)
            srv.close()
            finish()

        QtCore.QTimer.singleShot(400, send)
        QtCore.QTimer.singleShot(1800, check)

    plan.at(t_click + 3000, single_instance)

    # ---- C 记忆（重建窗口 = 重启进程的等价物） ----
    def finish() -> None:
        bx, by = win.body_origin()
        win.close()                      # closeEvent 里才写盘：先关再读，否则读到的是上一次拖拽的位置
        saved = saved_body_pos()

        second = IslandWindow()
        sx, sy = second.body_origin()
        second.close()
        ok = saved is not None and abs(sx - saved[0]) < 1.5 and abs(sy - saved[1]) < 1.5
        print(f"[C] 存盘 {saved[0]:.0f},{saved[1]:.0f}  关闭前本体 {bx:.0f},{by:.0f}  "
              f"重建后本体 {sx:.0f},{sy:.0f}  一致={ok}", flush=True)

        if original:
            save_prefs(x=original[0], y=original[1])
            print(f"[还原] prefs 回到 {original[0]:.0f},{original[1]:.0f}", flush=True)
        app.quit()

    plan.run(15000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
