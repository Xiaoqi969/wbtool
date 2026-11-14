# -*- coding: utf-8 -*-
"""B8 验收：打包产物能不能起来、多大、冷启动多久。

    python island_qt/_probe_b8.py           量测（每组 3 次，约 40 秒）
    python island_qt/_probe_b8.py --runs 5  多跑几次

测什么：
  A 体积   release 下三个产物（Qt 单文件 / Qt 目录版 / Electron 单文件）的字节数
  B 启动   从 CreateProcess 到**第一个可见顶层窗口**出现的毫秒数 —— 两个版本用同一把尺子
  C 落定   Qt 版启动后自报的状态（读 main.py 写的 island-qt.log）

口径说明：
  1. 用「第一个可见顶层窗口」而不是进程内打点：onefile 的耗时大头是**解包**
     （Python 解释器还没起来），进程内计时会把它整个漏掉；Electron portable 的自解压同理。
  2. 必须找**子孙进程**的窗口：PyInstaller onefile 的引导器解包后会 re-exec 出一个子进程，
     Electron portable 的自解压壳也一样 —— 只盯 Popen 的 pid 会一个窗口都看不到。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def proc_tree(root: int) -> set[int]:
    """root 及其全部子孙的 pid（PyInstaller 引导器 / 自解压壳都会派生子进程）。"""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return {root}
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    parent = {}
    if k32.Process32FirstW(snap, ctypes.byref(e)):
        while True:
            parent[e.th32ProcessID] = e.th32ParentProcessID
            if not k32.Process32NextW(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)

    tree, frontier = {root}, [root]
    while frontier:
        cur = frontier.pop()
        for pid, ppid in parent.items():
            if ppid == cur and pid not in tree:
                tree.add(pid)
                frontier.append(pid)
    return tree


def _all_pids() -> set[int]:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return set()
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    out = set()
    if k32.Process32FirstW(snap, ctypes.byref(e)):
        while True:
            out.add(e.th32ProcessID)
            if not k32.Process32NextW(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return out


def _exe_name(pid: int) -> str:
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        k32.CloseHandle(h)


def windows_of(pids: set[int]):
    """这些 pid 的可见顶层窗口（排除 0 尺寸与 <60×20 的辅助窗口）。"""
    found = []

    def cb(hwnd, _lparam):
        owner = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value not in pids or not u32.IsWindowVisible(hwnd):
            return True
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w >= 60 and h >= 20:
            found.append((int(hwnd), w, h, r.left, r.top))
        return True

    u32.EnumWindows(EnumProc(cb), 0)
    return found


def kill_tree(pids: set[int]) -> None:
    for pid in pids:
        h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if h:
            k32.TerminateProcess(h, 0)
            k32.CloseHandle(h)


def _child_env() -> dict:
    """去掉会让 Electron 变成「纯 Node」的继承变量。

    **踩坑**：本机环境里 `ELECTRON_RUN_AS_NODE=1`（WorkBuddy / VS Code 一类宿主会注入）。
    带着它启动，electron.exe 根本不初始化 Chromium，而是当 node 跑 main.js，
    于是 `app` 是 undefined → `requestSingleInstanceLock` 抛错 → 立刻退出（退出码 1）。
    表现极具迷惑性：旧版 portable 包"双击没反应"、解包目录里连残留都没有 —— 看起来像
    打包坏了，其实是测量环境的问题。清掉这两个变量，Electron 才是 Electron。
    """
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env.pop("NODE_OPTIONS", None)
    return env


def measure(label: str, exe: Path, args: list[str], runs: int, wait_exit: bool) -> list[float]:
    print(f"\n[{label}] {exe.name}  {exe.stat().st_size / 1024 / 1024:.1f} MB")
    want = exe.name.lower()
    times: list[float] = []
    for i in range(runs):
        before = _all_pids()
        t0 = time.perf_counter()
        proc = subprocess.Popen([str(exe), *args], env=_child_env())
        hit, pids = None, {proc.pid}
        while time.perf_counter() - t0 < 25.0:
            pids = proc_tree(proc.pid)
            # 自解压壳退出后父链会断，补一手「同名的全新进程」兜底
            for pid in _all_pids() - before:
                if pid not in pids and _exe_name(pid) == want:
                    pids.add(pid)
            wins = windows_of(pids)
            if wins:
                hit = (time.perf_counter() - t0, wins[0])
                break
            if proc.poll() is not None and not (pids - {proc.pid}):
                break                            # 壳已退且没有子进程：单实例拦截或崩溃
            time.sleep(0.005)
        if hit is None:
            print(f"  第 {i + 1} 次：✗ 没出窗口（退出码 {proc.poll()}）")
            kill_tree(pids)
            time.sleep(0.8)
            continue
        ms, (hwnd, w, h, x, y) = hit
        times.append(ms * 1000)
        print(f"  第 {i + 1} 次：{ms * 1000:6.0f} ms  → 窗口 {w}×{h} @ ({x},{y})  pid {len(pids)}")
        if wait_exit:
            try:
                proc.wait(timeout=25)            # --self-test 自己退，顺便验证锁不留残
                continue
            except subprocess.TimeoutExpired:
                pass
        kill_tree(proc_tree(proc.pid) | pids)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.8)                          # 让上一个实例的锁 / 端口释放
    if times:
        print(f"  中位 {statistics.median(times):.0f} ms   最快 {min(times):.0f} ms   最慢 {max(times):.0f} ms")
    return times


def prepare_onedir() -> dict[str, Path]:
    """把两个 portable.zip 解开，得到「不含自解压壳」的裸 exe —— 公平对比用。

    为什么必须另开这一组：单文件 exe 的启动耗时大头是**自解压**（Qt 解 37MB、
    Electron 解 105MB），而 Electron portable 壳在本机的无人值守会话里根本解不出来
    （rc=9，TEMP 里连解包目录都没建）。拿「Qt 单文件」比「Electron 目录版」就成了
    一边算解包、一边不算，毫无可比性 —— 所以两边都解包，比**应用本体**的启动。
    """
    import zipfile

    base = Path(os.environ.get("TEMP", ".")) / "b8-onedir"
    out = {}
    for tag, zp, exe_name in (
        ("Qt 目录版", RELEASE / "wbtool-island-portable.zip", "wbtool-island.exe"),
        ("Electron 目录版", RELEASE / "wbtool-island-legacy-portable.zip", "wbtool-island.exe"),
    ):
        if not zp.is_file():
            continue
        dest = base / tag.replace(" ", "-")
        exe = dest / exe_name
        if not exe.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zp) as z:
                z.extractall(dest)
        # 两边打包结构不同：PyInstaller 目录版里套一层同名文件夹，Electron 的包文件直接铺在顶层
        if not exe.is_file():
            hits = list(dest.rglob(exe_name))
            exe = hits[0] if hits else exe
        if exe.is_file():
            out[tag] = exe
    return out


def main() -> int:
    runs = 3
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])

    exes = {
        "Qt 单文件": RELEASE / "wbtool-island.exe",
        "Electron 单文件": RELEASE / "wbtool-island-legacy.exe",
    }
    zips = {
        "Qt 目录版": RELEASE / "wbtool-island-portable.zip",
        "Electron 目录版": RELEASE / "wbtool-island-legacy-portable.zip",
    }

    print("=" * 70)
    print("A 体积")
    print("-" * 70)
    for k, p in list(exes.items()) + list(zips.items()):
        if p.is_file():
            print(f"  {k:<14} {p.name:<28} {p.stat().st_size / 1024 / 1024:6.1f} MB")
    print("  （Qt 目录版解压后约 95 MB，含 Qt Core/Gui/Widgets/Network 与平台插件）")

    print()
    print("=" * 70)
    print("B 冷启动（CreateProcess → 第一个可见顶层窗口）")
    print("-" * 70)
    qt = exes["Qt 单文件"]
    if qt.is_file():
        measure("Qt 单文件（含自解压）", qt, ["--self-test", "8"], runs, wait_exit=True)
    ec = exes["Electron 单文件"]
    if ec.is_file() and "--skip-electron-portable" not in sys.argv:
        measure("Electron 单文件（portable 壳）", ec, [], runs, wait_exit=False)

    print()
    print("=" * 70)
    print("B2 应用本体启动（两边都解开 zip，不算自解压）")
    print("-" * 70)
    for tag, exe in prepare_onedir().items():
        is_qt = "Qt" in tag
        measure(tag, exe, ["--self-test", "8"] if is_qt else [],
                runs, wait_exit=is_qt)

    print()
    print("=" * 70)
    print("C Qt 版自报状态（main.py 冻结态日志）")
    print("-" * 70)
    log = Path(os.environ.get("APPDATA", ".")) / "wbtool-island" / "island-qt.log"
    if log.is_file():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-4:]:
            print("  " + line)
    else:
        print("  未找到 " + str(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
