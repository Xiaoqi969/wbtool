#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件说明：wbtool 的 Windows 打包脚本（PyInstaller）。
          同时构建两种产物，运行时不依赖任何第三方库（PyInstaller 仅打包时需要）。

设计取舍（作者要求「依赖外置、exe 只负责启动」）：
  - portable（onedir，主交付）：wbtool.exe 只是很小的启动器，Python 运行时与标准库
    全部放在同级 _internal/ 文件夹。启动无需解压，内存峰值更低，杀软误报更少。
    代价是分发时是一个文件夹，因此自动打成 wbtool-portable.zip。
  - single（onefile，备用）：单个 wbtool.exe，双击即用，但每次启动需解压运行时。

用法：
  python build.py              # 同时构建两种（默认）
  python build.py onedir       # 只构建 portable 版
  python build.py onefile      # 只构建 single 版
  python build.py --help       # 查看全部参数

产物（均写入 release/ 目录，该目录不进 git）：
  release/wbtool-portable.zip  -> 目录版压缩包，解压后运行 wbtool/wbtool.exe
  release/wbtool.exe           -> 单文件版

前置条件：Windows + Python 3.8~3.13 + pip install pyinstaller
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # 项目根目录（本文件所在处）
ENTRY = ROOT / "wb_usage_app.py"               # 主程序入口
ICON = ROOT / "assets" / "wbtool.ico"          # 程序图标（WorkBuddy 官方 logo）
RELEASE = ROOT / "release"                     # 最终产物目录
APP_NAME = "wbtool"                            # 产物名称

# 只排除确定用不到的大块标准库，减少打包体积；不敢排除 webbrowser/argparse 等实际依赖项。
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


def common_args(work: Path, spec: Path, mode: str, dist: Path):
    """生成两种模式共用的 PyInstaller 参数。"""
    args = pyinstaller_cmd() + [
        "--noconfirm",
        "--windowed",                 # 无黑框控制台（stdout 由主程序重定向到日志）
        "--" + mode,                 # onedir / onefile
        "--name", APP_NAME,
        "--icon", str(ICON),
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(spec),
    ]
    for m in EXCLUDES:
        args += ["--exclude-module", m]
    args.append(str(ENTRY))
    return args


def run_build(mode: str, tmp: Path):
    """执行一次打包；中间产物放在临时目录，避免污染项目目录。"""
    dist = tmp / ("dist_" + mode)
    work = tmp / ("work_" + mode)
    spec = tmp / ("spec_" + mode)
    cmd = common_args(work, spec, mode, dist)
    print(f"\n>>> 构建 {mode} 版\n    {' '.join(cmd)}\n")
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    return dist


def build_portable(tmp: Path):
    """目录版：把 PyInstaller 输出的整个文件夹打成 zip。"""
    dist = run_build("onedir", tmp)
    folder = dist / APP_NAME
    exe = folder / (APP_NAME + ".exe")
    if not exe.is_file():
        sys.exit(f"目录版构建失败：未找到 {exe}")
    zip_base = RELEASE / "wbtool-portable"
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=str(folder.parent),
                                  base_dir=APP_NAME)
    print(f"\n[portable] 启动器 {exe.stat().st_size / 1024:.0f} KB"
          f" | 运行目录 {sum(f.stat().st_size for f in folder.rglob('*') if f.is_file()) / 1024 / 1024:.1f} MB"
          f" | 压缩包 {Path(archive).stat().st_size / 1024 / 1024:.1f} MB")
    return Path(archive)


def build_single(tmp: Path):
    """单文件版：复制 exe 到 release 根目录。"""
    dist = run_build("onefile", tmp)
    src = dist / (APP_NAME + ".exe")
    if not src.is_file():
        sys.exit(f"单文件版构建失败：未找到 {src}")
    dst = RELEASE / (APP_NAME + ".exe")
    shutil.copy2(src, dst)         # 覆盖写，不做删除（兼容桌面文件保护策略）
    print(f"\n[single] {dst}  {dst.stat().st_size / 1024 / 1024:.1f} MB")
    return dst


def main():
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="wbtool 打包脚本：生成 Windows 目录版(zip) 与单文件版(exe)",
    )
    ap.add_argument("mode", nargs="?", default="all",
                    choices=("all", "onedir", "onefile"),
                    help="all=两种都构建（默认）；onedir=目录版；onefile=单文件版")
    args = ap.parse_args()

    if os.name != "nt":
        sys.exit("本项目仅正式支持 Windows；其他平台请直接运行 python wb_usage_app.py")
    for p in (ENTRY, ICON):
        if not p.is_file():
            sys.exit(f"缺少必要文件：{p}")
    RELEASE.mkdir(exist_ok=True)

    # 中间产物放到临时目录，构建结束自动清理；不写入项目目录，也不触碰任何个人文件。
    with tempfile.TemporaryDirectory(prefix="wbtool_build_") as td:
        tmp = Path(td)
        out = []
        if args.mode in ("all", "onedir"):
            out.append(build_portable(tmp))
        if args.mode in ("all", "onefile"):
            out.append(build_single(tmp))
    print("\n=== 构建完成 ===")
    for p in out:
        print("  " + str(p))
    print("\n下一步：把以上文件上传到 GitHub Release（仓库本身只提交源码与文档）。")


if __name__ == "__main__":
    main()
