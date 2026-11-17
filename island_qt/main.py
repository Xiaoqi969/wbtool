# -*- coding: utf-8 -*-
"""wbtool 灵动岛 · PySide6 版入口。

阶段进度：
    B0  透明无边框窗口 + 自绘胶囊                        ✅
    B1  真实毛玻璃（GDI 截屏 + 均值模糊）                ✅
    B2  共享解析 scanlib + 增量扫描服务                  ✅
    B3  窗口骨架 + 托盘 + 空闲停帧 + 主题接入            ✅
    B4  弹簧形变（点击展开 / 收起）                      ✅
    B5  收起态内容（wisland 排版，三格静态）              ✅
    B6  展开态明细页（卡片 + 会话列表）                   ✅
    B7  拖拽 / 位置记忆 / 减弱动效 / 单实例唤回            ✅
    B8  PyInstaller 打包（37.0MB，冷启 3.2s）              ✅
    B9  回归矩阵 + 文档 + 发布（v2.0.0）                  ✅

运行：
    python island_qt/main.py                 正常启动
    python island_qt/main.py --self-test 20  20 秒后自检并退出（无人值守冒烟）
    python island_qt/main.py --debug         启动时打印窗口几何与采样状态

打包后没有控制台：冻结态下 stdout/stderr 自动落到
    %APPDATA%/wbtool-island/island-qt.log
（见 `_redirect_stdio_if_frozen`，`--self-test` 的输出就是从这里读的）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_T_BOOT = time.perf_counter()      # 尽早取：这一行之前只有 stdlib 导入

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
# 同时支持 `python island_qt/main.py` 与从仓库根导入包内模块
for _p in (str(_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6 import QtCore, QtWidgets  # noqa: E402

from prefs import data_dir, prefs_path          # noqa: E402
from scan_service import ScanWorker            # noqa: E402
from single import InstanceServer, notify_existing   # noqa: E402
from tray import IslandTray                    # noqa: E402
from window import IslandWindow                # noqa: E402

APP_NAME = "wbtool-island"


def _redirect_stdio_if_frozen() -> Path | None:
    """打包后没有控制台：把 stdout/stderr 落到 `%APPDATA%/wbtool-island/island-qt.log`。

    没有这一步，`--self-test` 与一切排查信息在 exe 里全进黑洞（PyInstaller 的
    --windowed 会把 sys.stdout 置 None，print 静默丢弃）。开发态不动，终端照常看。
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        log = data_dir() / "island-qt.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        f = open(log, "w", encoding="utf-8", buffering=1)   # 行缓冲：崩溃前的最后一行也在盘上
        sys.stdout = f
        sys.stderr = f
        print(f"[island_qt] frozen boot {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        return log
    except Exception:                                      # noqa: BLE001
        return None                                        # 日志失败不能拖垮启动


def acquire_lock() -> QtCore.QLockFile | None:
    """单实例：第二个实例直接退出，避免两个胶囊叠在一起各自烧一份截屏。"""
    lock = QtCore.QLockFile(str(data_dir() / "island-qt.lock"))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(100) else None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _redirect_stdio_if_frozen()
    trace = getattr(sys, "frozen", False) or "--debug" in argv

    def _mark(label: str) -> None:
        """启动分段计时。只写进日志（冻结态）或 --debug，不影响正常使用。

        有了这四行，下次有人抱怨"启动慢"能立刻看出是 Qt 引导、字体引擎还是首帧。
        """
        if trace:
            print(f"[boot] {label:<12s}{1000 * (time.perf_counter() - _T_BOOT):7.0f}ms", flush=True)

    _mark("import")
    app = QtWidgets.QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    lock = acquire_lock()
    if lock is None:
        # 已有活实例：把「显示并提到最前」发过去，然后自己退出。
        # 只默默退出的话，用户双击图标看起来像什么都没发生（Electron 版有 second-instance）。
        if notify_existing():
            print("[island_qt] 已唤回运行中的实例", flush=True)
        else:
            print("[island_qt] 已有实例在运行（唤回通道无响应），本次启动退出", flush=True)
        return 0

    win = IslandWindow()
    _mark("window")

    # 扫描线程必须等胶囊先画出来再跑：首次全量扫描要读 20+ 个 jsonl、约 1.7s，
    # 与首帧同时争 GIL 会把胶囊出现的时间往后拖。这里先挂到「首帧已呈现」上，
    # 另配 1.5s 兜底（远端桌面/被遮挡等拿不到 paint 的情况下照常开扫）。
    worker = ScanWorker()
    worker.summaryReady.connect(win.apply_summary)
    worker.failed.connect(lambda msg: print(f"[island_qt] 扫描失败 {msg}", flush=True))
    _scan_started = False
    _data_seen = False

    def _on_data(_d: dict) -> None:
        nonlocal _data_seen
        if not _data_seen:
            _data_seen = True
            _mark("first data")

    win.firstFrame.connect(lambda: _mark("first frame"))
    worker.summaryReady.connect(_on_data)

    def _start_scan(*_args) -> None:
        nonlocal _scan_started
        if _scan_started:
            return
        _scan_started = True
        worker.start()

    win.firstFrame.connect(_start_scan)
    QtCore.QTimer.singleShot(1500, _start_scan)

    win.show()
    _mark("show")
    server = InstanceServer()
    if server.listening:
        server.activated.connect(win.bring_front)
    else:
        print("[island_qt] 唤回通道不可用：再次启动只会退出，不会把已运行的实例叫到前面", flush=True)

    tray = IslandTray(win, app)
    tray.show()

    def _shutdown() -> None:
        worker.stop()
        worker.wait(3000)
        win.close()          # 触发 closeEvent → 停掉采样线程并等它退出

    app.aboutToQuit.connect(_shutdown)

    debug = "--debug" in argv
    if debug:
        g = win.geometry()
        bx, by = win.body_origin()
        print(f"[island_qt] win={g.x()},{g.y()} {g.width()}x{g.height()} "
              f"body={win.body.x():.0f},{win.body.y():.0f} {win.body.width():.0f}x{win.body.height():.0f} "
              f"dpr={win.devicePixelRatioF():.2f} pos=({bx:.0f},{by:.0f}) "
              f"pinned={win.pinned} reduced={win.reduced} prefs={prefs_path()}", flush=True)

    # --self-test N：N 秒后打印状态并退出，便于无人值守冒烟
    sec = 0
    if "--self-test" in argv:
        i = argv.index("--self-test")
        if i + 1 < len(argv):
            try:
                sec = int(argv[i + 1])
            except ValueError:
                sec = 0
    if sec > 0:
        def _report() -> None:
            tiny = win.backdrop.tiny
            s = win.summary or {}
            t = s.get("today") or {}
            bx, by = win.body_origin()
            from ui.theme import theme as _th
            print(f"[island_qt] backdrop={'OK ' + str(tiny.width()) + 'x' + str(tiny.height()) if tiny else 'None(降级灰底)'} "
                  f"theme={_th.pal_name} lum={win.backdrop.luminance:.3f} "
                  f"token={t.get('token', 0)} credit={t.get('credit', 0):.2f} "
                  f"active={len(s.get('active') or [])} files={s.get('files', 0)} "
                  f"pos=({bx:.0f},{by:.0f}) pinned={win.pinned} reduced={win.reduced} "
                  f"visible={win.isVisible()} "
                  f"tray={tray.isVisible() and QtWidgets.QSystemTrayIcon.isSystemTrayAvailable()} "
                  f"text={win.compact_text()!r}", flush=True)
        QtCore.QTimer.singleShot(max(1, sec - 1) * 1000, _report)
        QtCore.QTimer.singleShot(sec * 1000, app.quit)

    rc = app.exec()
    try:
        lock.unlock()
    except Exception:  # noqa: BLE001
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
