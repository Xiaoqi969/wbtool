# -*- coding: utf-8 -*-
"""island_qt/tray.py — 托盘图标与菜单。

菜单结构照搬 Electron 版（island/src/main.js:382-397），保证用户从旧版切过来时位置和措辞不变：
    显示 / 隐藏灵动岛
    ─────────
    锁定置顶（始终最上层）
    ─────────
    退出灵动岛

2026-11-15 用户决定：**左键单击托盘图标 = 临时提到最前**（原先单击是显示/隐藏切换，
与 Electron 版一致；现改为提到最前，菜单里的「临时提到最前」项随之下线，避免同一功能两个入口）。
单击仍能唤回隐藏态：window.bring_front() 内部就是「隐藏则先显示，再 raise 到最前」。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui, QtWidgets

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "wbtool.ico"


def build_icon() -> QtGui.QIcon:
    if ICON_PATH.exists():
        return QtGui.QIcon(str(ICON_PATH))
    # 图标缺失时用系统标准图标兜底，不要让托盘直接消失
    return QtGui.QIcon.fromTheme(
        "applications-system",
        QtWidgets.QApplication.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon),
    )


class IslandTray(QtWidgets.QSystemTrayIcon):
    """托盘。pinned 状态切换会同时改窗口的置顶等级与提示文案。"""

    def __init__(self, window, app: QtWidgets.QApplication) -> None:
        super().__init__(build_icon(), app)
        self.window = window
        self.app = app
        self.pinned = bool(window.pinned)     # 勾选状态跟着存下来的偏好走，不能写死 True
        self._menu = QtWidgets.QMenu()
        self.setContextMenu(self._menu)
        self._build()
        self.activated.connect(self._on_activated)
        self._update_tooltip()

    # ------------------------------------------------------------------ 菜单
    def _build(self) -> None:
        m = self._menu
        m.clear()

        a = m.addAction("显示 / 隐藏灵动岛")
        a.triggered.connect(self.window.toggle_visible)

        # 「临时提到最前」已改为左键单击托盘直接触发（用户 2026-11-15 决定），
        # 菜单里不再保留同样功能的第二入口。
        m.addSeparator()

        a = m.addAction("锁定置顶（始终最上层）")
        a.setCheckable(True)
        a.setChecked(self.pinned)
        a.toggled.connect(self.set_pinned)

        m.addSeparator()

        a = m.addAction("退出灵动岛")
        a.triggered.connect(self.app.quit)

    # ------------------------------------------------------------------ 行为
    def _on_activated(self, reason) -> None:
        """左键单击托盘 = 临时提到最前（隐藏态下会先显示出来）。

        不用 ActivationReason.DoubleClick：Windows 双击会先发一次 Trigger，
        再单独处理 DoubleClick 等于同一动作做两遍。
        """
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self._bring_front()

    def _bring_front(self) -> None:
        self.window.bring_front()
        # 不调 activateWindow()：WindowDoesNotAcceptFocus 下它无效，而且会闪任务栏

    def set_pinned(self, pinned: bool) -> None:
        """置顶开关：关掉时降为普通层，其它窗口可以盖住它。写盘由 window 负责。"""
        self.window.set_pinned(bool(pinned))
        self.pinned = self.window.pinned
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        state = "已锁定置顶" if self.pinned else "未锁定（任务栏可唤回）"
        self.setToolTip(f"wbtool 灵动岛 · {state} · 单击提到最前")
