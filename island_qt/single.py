# -*- coding: utf-8 -*-
"""island_qt/single.py — 单实例判重 + 唤回。

两条通道分工明确，缺一不可：

    QLockFile            权威判重。进程活着锁就在，进程死掉锁自动失效。
    QLocalServer/Socket  唤回。把「显示并提到最前」这个动作交给已经跑着的那个实例。

只有锁：用户双击图标 → 第二个进程默默退出 → 看起来像没反应（Electron 版
用 `second-instance` 事件唤回，体验上不能倒退）。
只有 socket：上次异常退出留下的残骸会让新实例以为自己不是第一个，于是起不来。

所以先用锁判定「是否已有活实例」，再把「唤回」发过去。
"""
from __future__ import annotations

from PySide6 import QtCore, QtNetwork

NAME = "wbtool-island-qt"     # 同一用户机器上固定一个名字


def notify_existing(timeout_ms: int = 400) -> bool:
    """告诉已经运行的实例「用户又点了一次」；连不上返回 False。"""
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    try:
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        if sock.state() != QtNetwork.QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(timeout_ms)
    except Exception:  # noqa: BLE001  唤回是尽力而为，失败也不该拦住启动流程
        pass
    return True


class InstanceServer(QtCore.QObject):
    """第一个实例监听本地管道，收到消息就 signal 一次。"""

    activated = QtCore.Signal()

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QtNetwork.QLocalServer(self)
        # 清掉上次异常退出留下的残骸：不清的话 listen() 会一路失败，唤回通道永久失效
        QtNetwork.QLocalServer.removeServer(NAME)
        self._server.newConnection.connect(self._on_new_connection)
        self.listening = self._server.listen(NAME)

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.disconnected.connect(conn.deleteLater)
            # **连接本身就算信号**，不等 payload。
            # 实测（Windows 命名管道）：newConnection 触发时缓冲区常常还是空的，
            # 数据要等下一个事件循环才到；第一版「读到 show 才唤回」于是在探针里
            # 表现为「投递成功、信号不来」。唤回这件事没有内容歧义 —— 有人来连
            # 就是要我看你一眼。
            self.activated.emit()

    def close(self) -> None:
        self._server.close()
