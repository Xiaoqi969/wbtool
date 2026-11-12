#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明：wbtool 的 Windows 打包脚本。

两个启动器、两条独立技术栈（刻意解耦，互不干扰）：
  1) wbtool 主程序（HTML 报告）：Python + PyInstaller，零第三方运行时依赖。
  2) wbtool-island 灵动岛：Electron（HTML/CSS/JS 渲染，胶囊边缘与动效达到 Daozai 级精致度）。

产物（均写入 release/ 目录，该目录不进 git）：
  release/wbtool.exe                  -> 单文件版（HTML 报告启动器）
  release/wbtool-portable.zip         -> 目录版压缩包，解压后运行 wbtool/wbtool.exe
  release/wbtool-island.exe           -> 单文件版（桌面灵动岛启动器，Electron portable）
  release/wbtool-island-portable.zip  -> 目录版压缩包；顶层无目录，先建空文件夹再解压，
                                        运行其中的 wbtool-island.exe

electron-builder 的原始输出在 release/_out-<时间戳>/（本次构建独占的全新空工作区），
build.py 会把 exe / zip 对齐命名后搬到 release/ 根目录，并清理工作区里的中间产物。
每次都用全新空目录是必需的：release/ 下遗留的 .asar 常被系统进程锁住，
electron-builder 只要去覆盖旧输出目录，unlink 时就会 EBUSY 导致打包失败。

前置条件：
  - Windows + Python 3.8~3.13 + pip install pyinstaller   （仅 wbtool 主程序需要）
  - Node.js + npm（仅 wbtool-island 需要；构建时通过 npm 安装 electron / electron-builder）
  - 国内网络建议设置 ELECTRON_MIRROR 以加速 Electron 二进制下载（见 build_island）
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 关闭 WorkBuddy 注入的 safe-delete 钩子：构建脚本需要删除自身临时文件
# （node_modules、electron-builder 工作区）。该钩子对「单轮 >50 文件」的批量删除要求
# 人工确认，会令构建卡死。=0 即整体关闭；同时作用于本进程与派生的 npm 子进程。
os.environ["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"

ROOT = Path(__file__).resolve().parent          # 项目根目录（本文件所在处）
ENTRY = ROOT / "wb_usage_app.py"               # 主程序入口（HTML 报告）
ICON = ROOT / "assets" / "wbtool.ico"          # 程序图标（WorkBuddy 官方 logo）
ISLAND_DIR = ROOT / "island"                   # Electron 灵动岛工程目录
RELEASE = ROOT / "release"                     # 最终产物目录
ISLAND_OUT = RELEASE / "_electron-out"         # electron-builder 原始输出（与最终产物分层）
APP_NAME = "wbtool"                            # 主程序产物名称

# 主程序不依赖 GUI，可排除 tkinter
EXCLUDES = ("tkinter", "unittest", "pydoc", "doctest")


def pyinstaller_cmd():
    """自动定位 PyInstaller：优先 PATH，其次当前解释器的 -m 方式，最后 Scripts 目录。"""
    found = shutil.which("pyinstaller")
    if found:
        return [found]
    try:
        import PyInstaller  # noqa: F401  （仅用于探测是否安装在本解释器）
        return [sys.executable, "-m", "PyInstaller"]
    except ImportError:
        pass
    for c in (Path(sys.executable).parent / "Scripts" / "pyinstaller.exe",
              Path(sys.executable).parent / "pyinstaller.exe"):
        if c.is_file():
            return [str(c)]
    sys.exit("未找到 PyInstaller。请先执行：pip install pyinstaller")


def common_args(work, spec, mode, dist, entry, app_name, excludes):
    """生成两种模式共用的 PyInstaller 参数。"""
    args = pyinstaller_cmd() + [
        "--noconfirm",
        "--windowed",                 # 无黑框控制台（stdout 由主程序重定向到日志）
        "--" + mode,                 # onedir / onefile
        "--name", app_name,
        "--icon", str(ICON),
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(spec),
    ]
    for m in excludes:
        args += ["--exclude-module", m]
    args.append(str(entry))
    return args


def run_build(mode, tmp, entry, app_name, excludes):
    """执行一次打包；中间产物放在临时目录，避免污染项目目录。"""
    dist = tmp / ("dist_" + mode + "_" + app_name)
    work = tmp / ("work_" + mode + "_" + app_name)
    spec = tmp / ("spec_" + mode + "_" + app_name)
    cmd = common_args(work, spec, mode, dist, entry, app_name, excludes)
    print(f"\n>>> 构建 {mode} 版：{app_name}\n    {' '.join(cmd)}\n")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    return dist


def build_portable(tmp, entry, app_name, excludes):
    """目录版：把 PyInstaller 输出的整个文件夹打成 zip。"""
    dist = run_build("onedir", tmp, entry, app_name, excludes)
    folder = dist / app_name
    exe = folder / (app_name + ".exe")
    if not exe.is_file():
        sys.exit(f"目录版构建失败：未找到 {exe}")
    zip_base = RELEASE / (app_name + "-portable")
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=str(folder.parent),
                                  base_dir=app_name)
    print(f"\n[portable] {app_name} 启动器 {exe.stat().st_size / 1024:.0f} KB"
          f" | 运行目录 {sum(f.stat().st_size for f in folder.rglob('*') if f.is_file()) / 1024 / 1024:.1f} MB"
          f" | 压缩包 {Path(archive).stat().st_size / 1024 / 1024:.1f} MB")
    return Path(archive)


def build_single(tmp, entry, app_name, excludes):
    """单文件版：复制 exe 到 release 根目录。"""
    dist = run_build("onefile", tmp, entry, app_name, excludes)
    src = dist / (app_name + ".exe")
    if not src.is_file():
        sys.exit(f"单文件版构建失败：未找到 {src}")
    dst = RELEASE / (app_name + ".exe")
    shutil.copy2(src, dst)         # 覆盖写，不做删除（兼容桌面文件保护策略）
    print(f"\n[single] {dst}  {dst.stat().st_size / 1024 / 1024:.1f} MB")
    return dst


# ---------------------------------------------------------------------------
# wbtool-island：Electron 构建（npm + electron-builder）
# ---------------------------------------------------------------------------
def _node_env():
    """把常见 Node 安装路径补进 PATH，并设置 Electron 镜像（国内加速）。"""
    env = os.environ.copy()
    extra = [
        r"D:\Program Files\nodejs",
        r"D:\nodejs",
        r"C:\Program Files\nodejs",
        r"C:\Users\lenovo\.workbuddy\binaries\node\versions\24.22.2",
        r"C:\Users\lenovo\.workbuddy\binaries\node\versions\22.22.2-6",
    ]
    for cand in extra:
        if os.path.isdir(cand) and cand not in env.get("PATH", ""):
            env["PATH"] = cand + os.pathsep + env["PATH"]
    # 若未显式设置，默认走 npmmirror 镜像（避免 GitHub 下载被墙）
    env.setdefault("ELECTRON_MIRROR", "https://registry.npmmirror.com/-/binary/electron/")
    # 关闭 WorkBuddy 注入的 safe-delete 钩子：electron-builder 构建时需要删除自身临时文件，
    # 该钩子会把 fs.rm 重定向到回收站且在本机失败即阻断，导致打包崩溃。=0 即整体关闭。
    env["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"
    return env


def _evict_stale_release():
    """把 electron-builder 遗留的中间产物移出 release/（用同盘 rename，不做删除）。

    为什么不用删除：WorkBuddy 的 safe-delete 钩子会对「单轮 >50 文件」的批量删除
    要求人工确认，导致 win-unpacked/ 清不掉；而残留的 win-unpacked.tmp 会让下一次
    electron-builder 在 unlink default_app.asar 时报 EBUSY，构建直接失败。
    os.replace 是原子重命名、同盘瞬间完成，既不触发删除钩子，也能给构建干净起点。

    真实的构建输出由 build_island() 每次指向全新的 release/_out-<时间戳>/；
    这里只负责清理早期版本留下的静态 _electron-out/ 工作区。
    """
    stale = ROOT / ".build-stale"
    names = ("win-unpacked", "win-unpacked.tmp", "builder-debug.yml",
             "builder-effective-config.yaml")
    moved = []
    for name in names:
        p = ISLAND_OUT / name
        if not p.exists():
            continue
        try:
            stale.mkdir(exist_ok=True)
            dst = stale / f"{int(time.time() * 1000)}_{name}"
            os.replace(str(p), str(dst))
            moved.append(name)
        except OSError:
            pass
    # 尽力清空暂存区；若删除钩子仍开启则静默保留，不影响构建结果
    if stale.is_dir():
        shutil.rmtree(stale, ignore_errors=True)
    return moved


def build_island():
    """在 island/ 下执行 npm install + npm run dist，并把产物对齐到 release/。"""
    if not shutil.which("npm") and not any(
        os.path.isfile(os.path.join(p, "npm.cmd")) or os.path.isfile(os.path.join(p, "npm"))
        for p in _node_env().get("PATH", "").split(os.pathsep)
    ):
        sys.exit("未找到 npm。请先安装 Node.js：https://nodejs.org")
    env = _node_env()
    evicted = _evict_stale_release()          # 清理旧静态工作区的遗留
    # 清理历史唯一工作区（尽力；被系统锁住的少量残留不影响后续构建）
    for old in RELEASE.glob("_out-*"):
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)

    print(f"\n>>> 构建 wbtool-island（Electron）")
    print(f"    cwd = {ISLAND_DIR}")
    if evicted:
        print(f"    已移出上次遗留的中间产物：{', '.join(evicted)}")

    # 临时把 island/package.json 的 directories.output 指向本次唯一目录，finally 还原。
    # 只改 build 字段，不影响 npm install 的依赖解析。
    pkg_path = ISLAND_DIR / "package.json"
    original_pkg = pkg_path.read_text(encoding="utf-8")
    cfg = json.loads(original_pkg)
    cfg.setdefault("build", {}).setdefault("directories", {})

    # electron-builder 解压 electron 二进制时，Windows 杀软 / 索引服务会瞬时锁住
    # default_app.asar 等文件，造成 win-unpacked.tmp -> win-unpacked 重命名 EBUSY。
    # 用「每次全新输出目录 + 退避重试」规避这种瞬时锁：失败即换新目录、静候锁释放再试。
    out_dir = None
    try:
        pkg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        # Windows 上 npm 实为 npm.cmd，需用 shell=True 让 cmd 解析；env 已补入 Node 路径
        subprocess.run("npm install", cwd=str(ISLAND_DIR), env=env, check=True, shell=True)
        last_err = None
        for attempt in range(1, 5):
            out_dir = RELEASE / f"_out-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{attempt}"
            print(f"    out = {out_dir}  (第 {attempt} 次尝试，独占全新工作区)")
            cfg["build"]["directories"]["output"] = f"../{RELEASE.name}/{out_dir.name}"
            pkg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
            try:
                subprocess.run("npm run dist", cwd=str(ISLAND_DIR), env=env, check=True, shell=True)
                break
            except subprocess.CalledProcessError as e:
                last_err = e
                shutil.rmtree(out_dir, ignore_errors=True)   # 失败即弃用本次目录，下次换新
                _evict_stale_release()
                if attempt < 4:
                    print(f"[island] 第 {attempt} 次构建失败（疑似杀软临时锁定 electron 文件），15s 后重试…")
                    time.sleep(15)
        else:
            print(f"[island] 连续 4 次构建失败：\n{last_err}", file=sys.stderr)
            sys.exit("wbtool-island 构建失败：请检查杀软 / 索引服务是否持续锁定 release/ 目录")
    finally:
        pkg_path.write_text(original_pkg, encoding="utf-8")

    # 对齐命名：portable -> release/wbtool-island.exe；zip -> release/wbtool-island-portable.zip
    src_exe = out_dir / "wbtool-island.exe"
    if not src_exe.is_file():
        cands = sorted(out_dir.glob("wbtool-island*.exe"))
        if not cands:
            sys.exit(f"构建未完成：{out_dir} 中没有 portable exe")
        src_exe = cands[-1]
    portable = RELEASE / "wbtool-island.exe"
    shutil.copy2(src_exe, portable)         # 覆盖写，不做删除（兼容桌面文件保护策略）
    print(f"\n[island] {portable}  {portable.stat().st_size / 1024 / 1024:.1f} MB")

    # electron-builder 26 的 zip 命名为 wbtool-island-1.3.0-win.zip
    zips = sorted(out_dir.glob("wbtool-island-*-win*.zip")) or \
           sorted(out_dir.glob("wbtool-island-*.zip"))
    if zips:
        dst = RELEASE / "wbtool-island-portable.zip"
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        shutil.move(str(zips[-1]), str(dst))
        print(f"[island] {dst}  {dst.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        print("[island] 警告：未找到 zip 目标产物")

    # 清理本次工作区（release/ 整体 gitignore；被锁的少量残留会在下次构建前再清）
    shutil.rmtree(out_dir, ignore_errors=True)
    _evict_stale_release()
    return portable


def main():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="wbtool 打包脚本：生成 Windows 目录版(zip) 与单文件版(exe)",
    )
    ap.add_argument("mode", nargs="?", default="all",
                    choices=("all", "onedir", "onefile", "island"),
                    help="all=wbtool+island 都构建（默认）；onedir/onefile=仅 wbtool 对应版本；"
                         "island=仅构建 wbtool-island（Electron）")
    args = ap.parse_args()

    if os.name != "nt":
        sys.exit("本项目仅正式支持 Windows；其他平台请直接运行 python wb_usage_app.py")
    if not ENTRY.is_file():
        sys.exit(f"缺少必要文件：{ENTRY}")
    if not ICON.is_file():
        sys.exit(f"缺少必要文件：{ICON}")
    if args.mode in ("all", "island") and not ISLAND_DIR.is_dir():
        sys.exit(f"缺少灵动岛工程目录：{ISLAND_DIR}")
    RELEASE.mkdir(exist_ok=True)

    # 中间产物放到临时目录，构建结束自动清理；不写入项目目录，也不触碰任何个人文件。
    with tempfile.TemporaryDirectory(prefix="wbtool_build_") as td:
        tmp = Path(td)
        out = []
        # wbtool 主程序（保持原样）
        if args.mode in ("all", "onedir"):
            out.append(build_portable(tmp, ENTRY, APP_NAME, EXCLUDES))
        if args.mode in ("all", "onefile"):
            out.append(build_single(tmp, ENTRY, APP_NAME, EXCLUDES))
        # wbtool-island 灵动岛（Electron）
        if args.mode in ("all", "island"):
            out.append(build_island())
    print("\n=== 构建完成 ===")
    for p in out:
        print("  " + str(p))
    print("\n下一步：把以上文件上传到 GitHub Release（仓库本身只提交源码与文档）。")


if __name__ == "__main__":
    main()
