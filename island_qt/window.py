# -*- coding: utf-8 -*-
"""island_qt/window.py — 灵动岛窗口（截至 B7：形变 + 内容 + 拖拽 + 系统集成）。

从 wisland 的 island.py（1347 行）裁剪而来，只留 WBtool 需要的那部分：

    保留   透明无边框置顶窗口（217-222 行）、PreciseTimer 16ms 循环（300-303 行）、
           _needs_frames 空闲停帧（544-553 行）、paintEvent 三层绘制（946-1028 行）、
           背景预采样（902-934 行）、弹簧形变与两终态（383-384 / 570-583 行）、
           拖拽移窗（由窗口整体移动实现，不是 wisland 的弹簧跟随中心）
    删除   拖拽吸边 / 液桥 neck+drip / 鼠标穿透「模式」/ 全局热键 / ShellHook /
           全屏隐藏 / 多页栈与导航栏 / 宠物形象 / 媒体播放控件

窗口容器固定 900×680（容纳展开态 640 + 阴影），本体水平居中、上沿靠近窗口顶部。
透明区域靠 WM_NCHITTEST 返回 HTTRANSPARENT 穿透到下层 —— 这条是 WBtool 的硬需求，
用户最初的问题就是灵动岛挡住了浏览器标签页，所以不能靠「窗口刚好和胶囊一样大」蒙混。

三条硬约束（清单附 B 铁律）：
    1. 尺寸唯一真源是弹簧当前值，永不读回 geometry() 反推；
    2. 窗口位置只在首次放置时算一次，形变过程中不移动窗口 —— 移动分层窗口与重绘
       不是原子操作，逐帧移动会出现内容错位、没有玻璃底的帧。
       **唯一例外是拖拽**：那是用户明确要求的移动，且拖拽前会先收起胶囊，
       保证拖拽期间形状不再变化（见 `_begin_drag`）；
    3. 形变期间不刷新内容，形变结束后补发，避免文字抽搐。
"""
from __future__ import annotations

import ctypes
import math
import os
import time
from ctypes import wintypes

from PySide6 import QtCore, QtGui, QtWidgets

from content.compact import Compact
from content.detail import QUOTA_CYCLE_SEC, DetailPage
from engine.anim import Spring, clamp
from engine.glass import Backdrop
from engine.shape import body_path, body_points, deform, poly_path
from prefs import load_prefs, save_prefs, saved_body_pos
from ui.theme import theme

Qt = QtCore.Qt

# ---- 几何（逻辑像素）----
WIN_W, WIN_H = 900, 680          # 容器，要装得下展开态 + 阴影
CAPSULE_H = 34                   # 收起态高度，对齐 wisland 的 H_IDLE
EXP_W = 640                      # 展开态宽度，对齐 wisland 的 EXP_W
EXP_H_MIN, EXP_H_MAX = 200, 640  # 展开态高度的上下限：内容再少不留空壳、再多也不顶出屏幕
# 本体上沿在窗口内的 y，形变时不动（只向下长）。
#
# 2026-11-28 由「居中 (680-34)/2 = 323」改成 20：展开态只能往下长，居中意味着下方只剩
# 357px，而 EXP_H_MAX 是 640 —— 额度卡让内容涨到 464 时，面板底部（脚注）直接被窗口
# 下沿裁掉。窗口本身是透明且点击穿透的，本体在窗口里靠上放没有任何视觉代价，
# 只要保证 20 + EXP_H_MAX + 阴影 14 ≤ 680 即可用满 640 的展开高度。
BODY_TOP = 20.0
TOP_MARGIN = 8                   # 本体上沿距屏幕可用区顶部
CORNER_MAX = 30.0                # 展开态圆角上限（wisland island.py:756 的 base_r 上限）

# ---- 弹簧参数（wisland 实测值，勿与 Electron 版的 190/110 刚度混用）----
# 展开 420/0.62、收起 460/0.64（island.py:383-384 与 565-571）。
# 清单里写的 440/0.60 是「切页」参数（show_page），不是展开/收起。
SPRING_EXPAND = (420.0, 0.62)
SPRING_COLLAPSE = (460.0, 0.64)
DEFORM_MIN_SPEED = 30.0          # 低于这个速度不做形变（同 island.py:783 的 speed > 30）

# ---- 背景采样 ----
PAD_BACKDROP = 40                # 采样区外扩，覆盖圆角抗锯齿边缘
GRID = 16                        # 采样区对齐网格，避免轮廓微动导致区域抖动
IDLE_FPS = 0.5                   # 静止时采样频率（Hz）

# ---- Win32 ----
WM_NCHITTEST = 0x0084
WM_SETTINGCHANGE = 0x001A
HTTRANSPARENT = -1
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
SPI_GETCLIENTAREAANIMATION = 0x1042
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)

user32 = ctypes.WinDLL("user32")
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, wintypes.UINT]


def read_reduced_motion() -> bool:
    """系统「动画效果」被关掉时返回 True。

    这是 Windows 上与 CSS `prefers-reduced-motion` 同源的开关（Electron 的
    `nativeTheme.shouldUseReducedMotion` 也是读它）：辅助功能 → 视觉效果 →
    动画效果。系统级「关掉动画」的用户，大概率是前庭敏感或有认知负担，
    我们那套 420ms 弹簧对他们不是「精致」而是「晃」。
    """
    try:
        v = ctypes.c_int(0)
        if user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(v), 0):
            return v.value == 0
    except Exception:  # noqa: BLE001  非 Windows 一律按「有动画」处理
        pass
    return False

# ---- 光学效果常量 ----
# 这些不是主题色：阴影必须是黑、高光必须是白，任何色板下都不变。
# 集中在这里是为了让「配色一律走 theme 令牌」这条审计规则能一眼看清。
SHADOW_RGB = (0, 0, 0)                          # 阴影只用黑，色板里没有也不该有
SHADOW_LAYERS = ((14, 5), (8, 9), (4, 14))      # (描边宽度, alpha)，廉价近似柔和阴影
PAD_SHADOW = SHADOW_LAYERS[0][0] + 4            # 脏矩形外扩，盖住阴影
GLOSS_DARK = ((255, 255, 255, 14), (255, 255, 255, 0), (255, 255, 255, 10))
GLOSS_LIGHT = ((255, 255, 255, 26), (255, 255, 255, 0), (255, 255, 255, 10))
FALLBACK_GLASS = (128, 128, 128, 200)           # 采样失败时的灰底，绝不透明、绝不崩
CLICK_SLOP = 4                   # 位移小于这个像素算点击（同 Electron 版拖拽阈值）


class IslandWindow(QtWidgets.QWidget):
    """灵动岛本体：收起态尺寸由内容算定、展开 640×DetailPage 实际高度，中间态只由弹簧产生。"""

    # 首帧真正落到屏幕上（paintEvent 走完一次）时发一次。
    # 供 main.py 把「首次全量扫描」推迟到画面出现之后：扫描要读 20+ 个 jsonl、约 1.7s，
    # 抢在首帧前启动会和绘制争 GIL，把胶囊出现时间往后拖近 0.5s。
    firstFrame = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setWindowTitle("WBtool 灵动岛")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.resize(WIN_W, WIN_H)

        # ---- 形变状态 ----
        self.compact = Compact()                   # 收起态内容：宽度由它算定
        self.detail = DetailPage(EXP_W)            # 展开态明细：高度由它算定
        self._exp_h = self._detail_height()        # 当前展开态目标高度（内容变了才会改）
        self.expanded = False
        self.sw = Spring(self.compact.width, *SPRING_EXPAND)
        self.sh = Spring(CAPSULE_H, *SPRING_EXPAND)
        self.content_a = Spring(0.0, 700, 1.0)     # 展开态内容淡入
        self.compact_a = Spring(1.0, 420, 1.0)     # 收起态内容淡出
        self.deform_gain = 0.0                     # 形变期不做速度形变（wisland 展开是纯圆角插值）
        self._floor_t: dict[str, float | None] = {"w": None, "h": None}
        self._floor_on: dict[str, bool] = {"w": False, "h": False}

        self.body = self._body_rect(self.sw.x, self.sh.x)
        self.path = body_path(self.body, self._radii(self.sw.x, self.sh.x))
        self._visible = True
        self._first_painted = False

        # ---- 数据 ----
        self.summary: dict = {}
        self._pending: dict | None = None

        # ---- 毛玻璃引擎 ----
        self.backdrop = Backdrop()
        self.backdrop.hwnd = 0
        self.backdrop.self_exclude = True
        self.backdrop.ready.connect(self._on_backdrop)
        self._bd_init = False
        self._bd_prev = None              # 上一帧采样，用于交叉淡入
        self._bd_fade_t0 = 0.0
        self._bd_shown = None
        self._bd_seq = 0                  # 采样结果版本号（背景缓存键用，不能依赖 id()）

        # ---- 渲染循环（16ms PreciseTimer，空闲自动停）----
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

        # ---- 背景采样节拍 ----
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._request_backdrop)

        # ---- 额度卡轮播（模型多于一个时自动轮流展示；收起态不画，所以跟着展开/收起开关）----
        self._quota_cycle = QtCore.QTimer(self)
        self._quota_cycle.setInterval(int(QUOTA_CYCLE_SEC * 1000))
        self._quota_cycle.timeout.connect(self._on_quota_cycle)

        # ---- 背景缓存（静止时阴影+玻璃+轮廓的合成图；滚动帧只贴图不重画）----
        self._bg_pm: QtGui.QPixmap | None = None
        self._bg_at = QtCore.QPoint(0, 0)
        self._bg_key: tuple | None = None

        # ---- 点击 / 拖拽 ----
        self._press_pos: QtCore.QPointF | None = None
        self._press_moved = False
        self._drag_grab: QtCore.QPointF | None = None   # 按下时光标相对窗口左上角的偏移
        self.dragging = False

        # ---- 系统偏好 ----
        self.pinned = load_prefs().get("pinned") is not False
        self.reduced = read_reduced_motion()

        # ---- 窗口放置（只算一次，形变中不移动）----
        self._win_origin = (0, 0)
        self._place_window(force=True)

        theme.changed.connect(self.update)

    # ================================================================ 几何
    def _avail(self) -> QtCore.QRect:
        return self.screen().availableGeometry() if self.screen() else \
            QtGui.QGuiApplication.primaryScreen().availableGeometry()

    def _body_rect(self, w: float, h: float) -> QtCore.QRectF:
        """本体在窗口坐标里：水平居中、上沿固定（只向下长）。"""
        return QtCore.QRectF((WIN_W - w) / 2.0, BODY_TOP, w, h)

    def _dirty_rect(self) -> QtCore.QRect:
        """整颗本体 + 阴影的脏矩形（数据刷新、主题切换时用）。"""
        return self.body.toAlignedRect().adjusted(-PAD_SHADOW, -PAD_SHADOW, PAD_SHADOW, PAD_SHADOW)

    def _radii(self, w: float, h: float) -> tuple[float, float, float, float]:
        """收起态是整颗药丸（h/2），展开态收敛到 30（wisland island.py:754-757）。"""
        r = min(CORNER_MAX, h / 2.0, w / 2.0)
        return (r, r, r, r)

    def _default_body_origin(self) -> tuple[float, float]:
        """默认位置：主屏可用区水平居中、贴顶 8px。返回本体左上角的全局坐标。"""
        a = self._avail()
        w = self.compact.width
        return (a.left() + a.width() / 2.0 - w / 2.0, a.top() + TOP_MARGIN)

    def _screen_at(self, x: float, y: float) -> QtGui.QScreen:
        return (QtGui.QGuiApplication.screenAt(QtCore.QPoint(int(x), int(y)))
                or self.screen() or QtGui.QGuiApplication.primaryScreen())

    def _clamp_body_origin(self, bx: float, by: float, w: float, h: float) -> tuple[float, float]:
        """把本体左上角夹回屏内：至少留 80px 宽 / 40px 高在屏内（同 Electron 的 clampPos）。

        比「窗口整个留在屏内」松得多 —— 本体只有 274 宽，而容器有 900 宽，
        按容器夹的话右边一大片区域会永远拖不进去。
        """
        a = self._screen_at(bx + w / 2, by + h / 2).availableGeometry()
        min_x, max_x = a.left() - w + 80, a.right() + 1 - 80
        min_y, max_y = a.top() - 8, a.bottom() + 1 - 40
        return (min(max_x, max(min_x, float(bx))), min(max_y, max(min_y, float(by))))

    def body_origin(self) -> tuple[float, float]:
        """本体左上角的全局坐标 —— 存盘存的是这个，不是窗口位置。"""
        p = self.pos()
        return (p.x() + self.body.x(), p.y() + self.body.y())

    def _place_window(self, force: bool = False) -> None:
        """首次放置：优先用上次拖到的本体位置，没存过就居中贴顶。"""
        w, h = self.compact.width, CAPSULE_H
        saved = saved_body_pos()
        bx, by = self._default_body_origin() if saved is None else \
            self._clamp_body_origin(saved[0], saved[1], w, h)
        body = self._body_rect(w, h)
        wx, wy = int(round(bx - body.x())), int(round(by - body.y()))
        if force or (wx, wy) != self._win_origin:
            self._win_origin = (wx, wy)
            self.move(wx, wy)

    def target_size(self) -> tuple[float, float]:
        return (EXP_W, self._exp_h) if self.expanded else (self.compact.width, CAPSULE_H)

    # ================================================================ 生命周期
    def showEvent(self, e: QtGui.QShowEvent) -> None:  # noqa: N802
        super().showEvent(e)
        if not self._bd_init:
            self._bd_init = True
            self.backdrop.hwnd = int(self.winId())
            self.backdrop.start()
            self._apply_noactivate()
            self._poll.start()
            self._request_backdrop(urgent=True)
            self.set_pinned(self.pinned, persist=False)   # 把存下来的置顶状态真正应用一次
        self._kick()

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:  # noqa: N802
        self._save_pos()
        self.timer.stop()
        self._poll.stop()
        self._quota_cycle.stop()
        self.backdrop.stop(wait=True)      # 必须等采样线程收工，否则它会 emit 给已销毁的窗口
        super().closeEvent(e)

    def _apply_noactivate(self) -> None:
        """点击胶囊不抢焦点：任务栏其它窗口不会闪。"""
        try:
            hwnd = int(self.winId())
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if not ex & WS_EX_NOACTIVATE:
                user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        except Exception:  # noqa: BLE001  非 Windows 或句柄未就绪时静默跳过
            pass

    def toggle_visible(self) -> None:
        self._visible = not self._visible
        if self._visible:
            self._poll.start()
            self.show()
            self._request_backdrop(urgent=True)
            self._kick()
            self._sync_quota_timer()     # 隐藏期间停掉的轮播，显示回来要接着转
        else:
            self._poll.stop()        # 隐藏时别再按 0.5Hz 截屏，省 CPU
            self._quota_cycle.stop()  # 看不见的东西不用轮播
            self.timer.stop()
            self.hide()

    # ================================================================ 展开 / 收起
    def toggle(self) -> None:
        if self.expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        if self.expanded:
            return
        self.expanded = True
        self.detail.quota_reset_cycle()    # 展开第一眼先看「已用最多」的那个模型
        self._sync_quota_timer()
        self._reset_floor()
        w, h = self.target_size()
        if self.reduced:
            self._snap_to_end(True, w, h)
            return
        self.compact_a.to(0.0, 900, 1.0)     # 收起态内容先淡出，形状跟着长
        self.content_a.snap(0.0)             # 展开态内容先隐藏，形状到位后才淡入
        self.sw.to(w, *SPRING_EXPAND)
        self.sh.to(h, *SPRING_EXPAND)
        self._kick()

    def collapse(self) -> None:
        if not self.expanded:
            return
        self.expanded = False
        self._quota_cycle.stop()          # 收起态不画额度卡，定时器跟着停，别在背后空转
        w, h = self.target_size()
        if self.reduced:
            self._snap_to_end(False, w, h)
            return
        self.content_a.snap(0.0)             # 立即隐藏，玻璃形状再收回胶囊
        self.compact_a.to(1.0, 420, 1.0)
        self.sw.to(w, *SPRING_COLLAPSE)
        self.sh.to(h, *SPRING_COLLAPSE)
        self._kick()

    def _snap_to_end(self, expanded: bool, w: float, h: float) -> None:
        """减弱动效：一步落终态。

        弹簧全 snap，交叉淡入也跳过 —— 那 0.25s 的淡入同样属于「动画」，
        既然用户明确要求减弱动效，就不该留下一个更小号的同款。
        """
        self.sw.snap(w)
        self.sh.snap(h)
        self.content_a.snap(1.0 if expanded else 0.0)
        self.compact_a.snap(0.0 if expanded else 1.0)
        self._bd_prev = None
        self._rebuild()

    def _reset_floor(self) -> None:
        self._floor_t = {"w": None, "h": None}
        self._floor_on = {"w": False, "h": False}

    def _hold_floor(self) -> None:
        """展开态越过目标后不再回落到目标以下：保留过冲回弹，但不会比内容小。"""
        for sp, key in ((self.sw, "w"), (self.sh, "h")):
            if self._floor_t.get(key) != sp.target:
                self._floor_t[key] = sp.target
                self._floor_on[key] = sp.x >= sp.target
            if sp.x >= sp.target:
                self._floor_on[key] = True
            elif self._floor_on.get(key):
                sp.x, sp.v = sp.target, 0.0

    # ================================================================ 点击 / 拖拽
    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:  # noqa: N802
        if os.environ.get("ISLAND_QT_DEBUG"):
            print(f"[island_qt] press {e.position().x():.0f},{e.position().y():.0f}", flush=True)
        if e.button() == Qt.MouseButton.LeftButton and self._hit(e.position()):
            self._press_pos = e.position()
            self._press_moved = False
            # 偏移量用「光标全局位置 - 窗口左上角」算：拖拽时窗口跟着光标走，
            # 手指与胶囊的相对位置始终不变（不会出现「胶囊从光标下面滑走」）。
            self._drag_grab = e.globalPosition() - QtCore.QPointF(self.pos())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._press_pos is not None and not self._press_moved:
            d = e.position() - self._press_pos
            if abs(d.x()) > CLICK_SLOP or abs(d.y()) > CLICK_SLOP:
                self._press_moved = True
                self._begin_drag()
        if self.dragging:
            self._drag_to(e.globalPosition())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            moved = self._press_moved
            self._press_pos = None
            self._press_moved = False
            if self.dragging:
                self._end_drag()
            elif not moved:
                self.toggle()        # 位移小于 4px 才算点击（同 island.js 的拖拽阈值）
            e.accept()
            return
        super().mouseReleaseEvent(e)

    # ================================================================ 拖拽
    def _begin_drag(self) -> None:
        """越过阈值就进入拖拽。展开态抓起来先收回胶囊，像把一张纸片捡起来。"""
        self.dragging = True
        if self.expanded:
            self.collapse()
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        self._poll.stop()            # 拖拽期间不要 0.5Hz 那套，换成整屏一次采样
        self._drag_backdrop()

    def _drag_to(self, gpos: QtCore.QPointF) -> None:
        if self._drag_grab is None:
            return
        w, h = self.body.width(), self.body.height()
        bx, by = self._clamp_body_origin(gpos.x() - self._drag_grab.x() + self.body.x(),
                                         gpos.y() - self._drag_grab.y() + self.body.y(), w, h)
        nx = int(round(bx - self.body.x()))
        ny = int(round(by - self.body.y()))
        if (nx, ny) != (self.pos().x(), self.pos().y()):
            self.move(nx, ny)
            self._win_origin = (nx, ny)
            self.update()            # 分层窗口移动后必须自己重画透明内容

    def _end_drag(self) -> None:
        self.dragging = False
        QtWidgets.QApplication.restoreOverrideCursor()
        self._save_pos()
        self._poll.start()
        self._request_backdrop(urgent=True)   # 采样区从整屏收回本体大小
        self._kick()
        self.update(self._dirty_rect())

    def _drag_backdrop(self) -> None:
        """拖拽期间把采样区放大到整屏。

        采样区随窗口移动的话，区域每变一次就要重新截屏（引擎限 45fps），拖快一点
        玻璃底会糊在上一格的位置；放成整屏就只剩一个区域，一次采样够整个拖拽过程
        用 —— 模糊小图才 160×90，比反复截小区域还便宜。
        """
        scr = self.screen() or QtGui.QGuiApplication.primaryScreen()
        sg = scr.geometry()
        if sg.isValid() and sg.width() > 8:
            self.backdrop.request(scr, sg, 1 / 10.0, urgent=True)

    def _save_pos(self) -> None:
        bx, by = self._collapsed_origin()
        save_prefs(x=round(bx, 1), y=round(by, 1))

    def _collapsed_origin(self) -> tuple[float, float]:
        """收起态本体左上角的全局坐标（存盘用）。

        不能用 `body_origin()`：展开态的 body 是 640 宽的大框，左上角比胶囊靠左 180px，
        存下去下次启动胶囊就会右移一截。
        """
        p = self.pos()
        body = self._body_rect(self.compact.width, CAPSULE_H)
        return (p.x() + body.x(), p.y() + body.y())

    # ================================================================ 置顶 / 唤回
    def set_pinned(self, pinned: bool, persist: bool = True) -> None:
        """置顶开关。走 Win32 SetWindowPos 而不是 setWindowFlags：

        Qt 的 setWindowFlags 在 Windows 上会销毁并重建原生窗口 —— backdrop 的 hwnd 失效、
        WS_EX_NOACTIVATE 丢失（点一下就抢焦点）、位置和内容全部要重来。这里只改 z 序，
        其余一概不动。
        """
        self.pinned = bool(pinned)
        try:
            user32.SetWindowPos(int(self.winId()),
                                HWND_TOPMOST if self.pinned else HWND_NOTOPMOST,
                                0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:  # noqa: BLE001
            pass
        if persist:
            save_prefs(pinned=self.pinned)

    def bring_front(self) -> None:
        """托盘点击 / 第二次启动时唤回：隐藏就显示，然后提到最前（不抢焦点）。"""
        if not self._visible:
            self.toggle_visible()
        elif not self.isVisible():
            self.show()
        self.raise_()
        if self.pinned:      # 置顶层之间 raise_ 未必越过其它置顶窗口，补一次 SetWindowPos
            self.set_pinned(True, persist=False)

    # ================================================================ 穿透
    def nativeEvent(self, event_type, message):  # noqa: N802
        """WM_NCHITTEST：胶囊形状之外一律 HTTRANSPARENT，鼠标继续落到下层窗口。

        只按窗口矩形做命中（Qt 默认行为）会重演「灵动岛挡住浏览器标签页」的老问题，
        所以这里用路径精确判定，连阴影区都放行。

        注意坐标系：lParam 给的是**物理像素**屏幕坐标，而 Qt 的几何全是逻辑像素。
        高 DPI 下必须先按 glass.py 同一套公式反算回逻辑坐标（Qt6 在 Windows 上
        保持屏幕原点不缩放：逻辑 = 原点 + (物理 - 原点) / dpr），否则 dpr=1.5 时
        判定点会被放大 1.5 倍，连胶囊正中的点击都会被判成穿透。
        """
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_SETTINGCHANGE:
                # 用户在设置里改「动画效果」时要立刻跟进。广播的那一刻系统未必写完值，
                # 推迟一拍再读。
                QtCore.QTimer.singleShot(0, self._on_settings_changed)
            if msg.message == WM_NCHITTEST:
                px = ctypes.c_short(msg.lParam & 0xFFFF).value
                py = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                scr = self.screen() or QtGui.QGuiApplication.primaryScreen()
                sg = scr.geometry()
                dpr = scr.devicePixelRatio() or 1.0
                gx = sg.x() + (px - sg.x()) / dpr
                gy = sg.y() + (py - sg.y()) / dpr
                org = self.pos()
                lp = QtCore.QPointF(gx - org.x(), gy - org.y())
                hit = self._hit(lp)
                self._dbg_nchit(px, py, lp, hit)
                if not hit:
                    return True, HTTRANSPARENT
        except Exception:  # noqa: BLE001
            pass
        return False, 0

    def _dbg_nchit(self, px, py, lp, hit) -> None:
        """ISLAND_QT_NCHIT=1 时打印命中判定的翻转点，供穿透自检用（只在变化时打印）。"""
        if not os.environ.get("ISLAND_QT_NCHIT"):
            return
        if getattr(self, "_dbg_last", None) == hit:
            return
        self._dbg_last = hit
        print(f"[nchit] phys=({px},{py}) local=({lp.x():.0f},{lp.y():.0f}) hit={hit}", flush=True)

    def _on_settings_changed(self) -> None:
        """系统设置变了：只剩「动画效果」这一项与我们有关。"""
        r = read_reduced_motion()
        if r == self.reduced:
            return
        self.reduced = r
        if not r:
            return
        # 刚被要求「减少动画」：正在跑的弹簧立刻落终态，剩下的过冲不该再演给用户看
        w, h = self.target_size()
        self.sw.snap(w)
        self.sh.snap(h)
        self.content_a.snap(1.0 if self.expanded else 0.0)
        self.compact_a.snap(0.0 if self.expanded else 1.0)
        self._bd_prev = None
        self._rebuild()

    def _hit(self, lp: QtCore.QPointF) -> bool:
        if not self.path.isEmpty() and self.path.contains(lp):
            return True
        return self.body.adjusted(-3, -3, 3, 3).contains(lp)

    # ================================================================ 数据
    def apply_summary(self, data: dict) -> None:
        """扫描线程送来的 summary。形变期间只记下，结束后补发（铁律 #4）。"""
        if not self._settled():
            self._pending = data
            self._kick()                  # 得有人把循环叫醒，否则攒下的数据永远等不到补发
            return
        self.summary = data or {}
        compact_changed = self.compact.set_summary(self.summary)
        detail_changed = self.detail.set_summary(self.summary)
        self._sync_quota_timer()          # 模型数变了（首个配额出现 / 最后一个过期）要跟着开关
        if self._sync_exp_height():
            self.update(self._dirty_rect())        # 展开态：高度在动，内容也在动
        elif compact_changed and not self.expanded:
            self.update(self._dirty_rect())
        elif detail_changed and self.expanded:
            self.update(self._dirty_rect())

    # ---- 额度卡轮播 ----
    def _sync_quota_timer(self) -> None:
        """只有展开态、且额度卡里不止一个模型时才需要轮播。"""
        if self.expanded and self.detail.quota_count() > 1:
            if not self._quota_cycle.isActive():
                self._quota_cycle.start()
        elif self._quota_cycle.isActive():
            self._quota_cycle.stop()

    def _on_quota_cycle(self) -> None:
        if not self.expanded:
            return
        # 减弱动效时不淡入：淡入本身也是动画，用户既然要求减弱就不该每 4 秒来一次
        if not self.detail.quota_cycle(fade=not self.reduced):
            self._quota_cycle.stop()      # 只剩一个模型了，没必要再转
            return
        self.update(self._dirty_rect())
        if not self.reduced:
            self._kick()                  # 淡入要出帧；跑完由 _needs_frames 自然停

    def compact_text(self) -> str:
        return self.compact.plain_text()

    # ---- 展开态高度：内容说了算 ----
    def _detail_height(self) -> float:
        return float(min(EXP_H_MAX, max(EXP_H_MIN, round(self.detail.preferred_height()))))

    def _sync_exp_height(self) -> bool:
        """行数变化时只改高度目标（wisland island.py:444 的做法）。

        **收起态绝不能动 `sh`**：收起时的真值就是 34，改它会让胶囊当场长成展开态那么高。
        收起态只记下 `_exp_h`，它只在 `target_size()` 里被读、被展开时用。
        返回「展开态几何是否需要重画」。
        """
        h = self._detail_height()
        if abs(h - self._exp_h) < 0.5:
            return False
        self._exp_h = h
        if not self.expanded:
            return False
        self.sh.to(h, 440, 0.62)
        self._kick()
        return True

    # ================================================================ 背景采样
    def _request_backdrop(self, urgent: bool = False) -> None:
        if not self._bd_init:
            return
        # 采样区取「当前形状 ∪ 目标形状」：一次截图够整段展开动画用，且区域在动画期间恒定，
        # 不会因为每帧变大就反复触发重新截屏（Backdrop 只在区域变化时被唤醒）。
        tw, th = self.target_size()
        need_rect = self.body.toAlignedRect().united(self._body_rect(tw, th).toAlignedRect())
        g = need_rect.adjusted(-PAD_BACKDROP, -PAD_BACKDROP, PAD_BACKDROP, PAD_BACKDROP)
        x0, y0 = (g.left() // GRID) * GRID, (g.top() // GRID) * GRID
        x1 = -((-(g.right() + 1)) // GRID) * GRID
        y1 = -((-(g.bottom() + 1)) // GRID) * GRID
        g = QtCore.QRect(x0, y0, x1 - x0, y1 - y0)
        need = self.body.toAlignedRect().translated(self.pos())
        # 启动前 3 秒高频采样：主题靠 feed_luminance 的 EMA 收敛，0.5Hz 要 7 秒才切对明暗，
        # 这段时间快一点，用户第一眼看到的就不是错的主题。之后回落到 IDLE_FPS。
        fps = 5.0 if (time.perf_counter() - self._t0) < 3.0 else IDLE_FPS
        self.backdrop.request(
            self.screen(), g.translated(self.pos()), 1 / fps,
            urgent=urgent or not self.backdrop.covers(need),
        )

    def _on_backdrop(self, changed: bool) -> None:
        theme.feed_luminance(self.backdrop.luminance)
        if not changed:
            return
        st = self.backdrop.state
        self._bd_seq += 1
        if self._bd_shown is not None and self._bd_shown[0] is not st[0]:
            self._bd_prev = self._bd_shown          # 旧背景淡出、新背景淡入
            self._bd_fade_t0 = time.perf_counter()
            self._kick()
        self.update(self._dirty_rect())

    # ================================================================ 渲染循环
    def _kick(self) -> None:
        if not self.timer.isActive():
            self._last = time.perf_counter()
            self.timer.start()

    def _settled(self) -> bool:
        return (self.sw.rest and self.sh.rest and self.content_a.rest
                and self.compact_a.rest and self._bd_prev is None)

    def _needs_frames(self) -> bool:
        """空闲停帧：没在交叉淡入 / 没有形变 / 额度卡不在切换淡入，就让 16ms 循环彻底停下。

        收起态内容恒为三格静态文字（会话明细只在展开态），因此静止时没有第二种
        需要持续出帧的东西 —— 停帧就是真的停。
        """
        return not self._settled() or self.detail.quota_animating()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(1 / 30.0, max(1 / 240.0, now - self._last))
        self._last = now

        for s in (self.sw, self.sh, self.content_a, self.compact_a):
            s.step(dt)
        if self.expanded:
            self._hold_floor()

        # 形状长到完整尺寸后才让内容淡入（之后不会再缩到比内容小，全程不需要遮罩）
        if (self.expanded and self.content_a.target < 1
                and self.sw.x >= self.sw.target - 1.0 and self.sh.x >= self.sh.target - 1.0):
            self.content_a.to(1.0, 700, 1.0)

        if self._bd_prev is not None and now - self._bd_fade_t0 > 0.25:
            self._bd_prev = None

        self._rebuild()
        # 补发形变期间攒下的数据：循环可能因为别的原因还在跑，不能只在「停下那一次」补
        if self._settled() and self._pending is not None:
            data, self._pending = self._pending, None
            self.apply_summary(data)
        if not self._needs_frames():
            self.timer.stop()

    def _rebuild(self) -> None:
        """按弹簧当前值重算本体几何与轮廓，并按「旧 ∪ 新」提交脏矩形。"""
        w = max(12.0, self.sw.x)
        h = max(12.0, self.sh.x)
        body = self._body_rect(w, h)
        radii = self._radii(w, h)

        path = QtGui.QPainterPath()
        if self.deform_gain > 0.0:
            vx = self.sw.v * 0.5 * self.deform_gain
            vy = self.sh.v * 0.5 * self.deform_gain
            if math.hypot(vx, vy) > DEFORM_MIN_SPEED:
                pts = body_points(body, radii, 4.0)
                pts = deform(pts, body.center().x(), body.center().y(), vx, vy,
                             min(w, h) / 2 + 12)
                path = poly_path(pts)
        if path.isEmpty():
            path = body_path(body, radii)

        old = self.path.boundingRect().toAlignedRect()
        self.body, self.path = body, path
        new = path.boundingRect().toAlignedRect()
        self.update(old.united(new).adjusted(-PAD_SHADOW, -PAD_SHADOW, PAD_SHADOW, PAD_SHADOW))

    # ================================================================ 绘制
    def paintEvent(self, e: QtGui.QPaintEvent) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        path = self.path
        if path.isEmpty():
            p.end()
            return

        # 1~3) 阴影 + 玻璃 + 轮廓。静止时整块缓存成一张图：三层宽描边是每帧最贵的部分
        #      （实测 0.65ms/帧，占单帧耗时的 3/4），贴图只要 0.05ms。
        #      拖拽时窗口在移，缓存键（含窗口位置）每帧都会变，走缓存等于每帧重建，直接画更快。
        if self._settled() and self._bd_prev is None and not self.dragging:
            pm, at = self._bg_snapshot()
            p.drawPixmap(at, pm)
        else:
            self._paint_scene(p, path)

        self._paint_content(p, path)
        p.end()

        if not self._first_painted:
            self._first_painted = True
            # 延到本次 paintEvent 返回之后再发：槽里会 start() 扫描线程，
            # 在绘制中途拉起线程没有必要，也不差这半个事件循环。
            QtCore.QTimer.singleShot(0, self.firstFrame.emit)

    def _paint_scene(self, p: QtGui.QPainter, path: QtGui.QPainterPath) -> None:
        # 1) 柔和阴影：几层半透明粗描边，比高斯模糊便宜得多
        sp = path.translated(0, 1.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for wdt, a in SHADOW_LAYERS:
            p.strokePath(sp, QtGui.QPen(QtGui.QColor(*SHADOW_RGB, a), wdt))

        # 2) 玻璃
        self._paint_glass(p, path)

        # 3) 轮廓：外侧极淡暗线 + 内侧自上而下的高光
        p.strokePath(path, QtGui.QPen(theme.outline(), 1.6))
        rg = QtGui.QLinearGradient(0, self.body.top(), 0, self.body.bottom())
        rg.setColorAt(0, theme.rim_top())
        rg.setColorAt(1, theme.rim_bottom())
        p.strokePath(path, QtGui.QPen(QtGui.QBrush(rg), 1.0))

    def _bg_snapshot(self) -> tuple[QtGui.QPixmap, QtCore.QPoint]:
        """静止态背景缓存。键覆盖几何 / 采样结果 / 主题，任一变化就重建。"""
        key = (round(self.body.x(), 2), round(self.body.y(), 2),
               round(self.body.width(), 2), round(self.body.height(), 2),
               self._bd_seq, theme.pal_name, self.pos().x(), self.pos().y())
        if self._bg_pm is not None and self._bg_key == key:
            return self._bg_pm, self._bg_at

        rect = self.path.boundingRect().toAlignedRect().adjusted(
            -PAD_SHADOW, -PAD_SHADOW, PAD_SHADOW, PAD_SHADOW)
        dpr = self.devicePixelRatioF() or 1.0
        pm = QtGui.QPixmap(max(1, round(rect.width() * dpr)), max(1, round(rect.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        bp = QtGui.QPainter(pm)
        bp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        bp.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        bp.translate(-rect.topLeft())
        self._paint_scene(bp, self.path)
        bp.end()

        self._bg_pm, self._bg_at, self._bg_key = pm, rect.topLeft(), key
        return pm, rect.topLeft()

    def _paint_glass(self, p: QtGui.QPainter, path: QtGui.QPainterPath) -> None:
        """毛玻璃底：真实截图模糊 → 主题色调 → 纵向光泽。"""
        br = Backdrop.brush_for(self.backdrop.state, self.pos())
        prev = Backdrop.brush_for(self._bd_prev, self.pos()) if self._bd_prev else None
        if prev is not None:
            p.fillPath(path, prev)
        if br is not None:
            if prev is not None:
                fade = min(1.0, (time.perf_counter() - self._bd_fade_t0) / 0.25)
                p.setOpacity(max(0.0, fade))
                p.fillPath(path, br)
                p.setOpacity(1.0)
            else:
                p.fillPath(path, br)
        else:
            # 降级路径（wisland glass.py 同款）：采样失败也绝不透明、绝不崩
            p.fillPath(path, QtGui.QColor(*FALLBACK_GLASS))

        p.fillPath(path, theme.tint_brush(self.body))

        g = QtGui.QLinearGradient(0, self.body.top(), 0, self.body.bottom())
        stops = GLOSS_DARK if theme.dark else GLOSS_LIGHT
        g.setColorAt(0.0, QtGui.QColor(*stops[0]))
        g.setColorAt(0.5, QtGui.QColor(*stops[1]))
        g.setColorAt(1.0, QtGui.QColor(*stops[2]))
        p.fillPath(path, g)

    def _paint_content(self, p: QtGui.QPainter, path: QtGui.QPainterPath) -> None:
        """两套内容叠着画，各自按弹簧值算不透明度；内容不越过胶囊轮廓。"""
        p.save()
        p.setClipPath(path)
        if self.compact_a.x > 0.004:
            self._paint_compact(p)
        if self.content_a.x > 0.004:
            self._paint_detail(p, clamp(self.content_a.x, 0.0, 1.0))
        p.restore()

    # ---- 收起态 ----
    def _paint_compact(self, p: QtGui.QPainter) -> None:
        """绘制区固定为「胶囊尺寸、上沿对齐本体上沿」而不是当前 body：形变期间文字留在

        原位淡出（等同 wisland 里 compact 是独立子控件），不会跟着大框重新居中漂走。
        不透明度由 compact 自己乘进颜色，避免嵌套 setOpacity 覆盖外层的 content_a。
        """
        w = self.compact.width
        r = QtCore.QRectF(self.body.center().x() - w / 2.0, self.body.top(), w, CAPSULE_H)
        self.compact.paint(p, r, clamp(self.compact_a.x, 0.0, 1.0))

    # ---- 展开态 ----
    def _paint_detail(self, p: QtGui.QPainter, a: float) -> None:
        """明细页自己乘不透明度（同收起态），不套 `p.setOpacity()`：
        嵌套 setOpacity 会把形变淡入覆盖成两级衰减。"""
        self.detail.paint(p, self.body, a)


