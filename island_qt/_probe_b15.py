# -*- coding: utf-8 -*-
"""B15 探针：额度卡自动轮播（指针、顺序抖动、模型消失、淡入）。

不依赖 pytest，直接 `python island_qt/_probe_b15.py`。纯内存 + 离屏 QImage，
不碰真实数据目录，也不启动窗口。
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from content.detail import (  # noqa: E402
    QUOTA_CYCLE_SEC, QUOTA_FADE_SEC, QUOTA_H, DetailPage,
)

OK = 0


def check(cond, msg):
    global OK
    assert cond, "FAIL: " + msg
    OK += 1


def mk(*models, reset=1000):
    """models 是 (名字, 已用%) 或 (名字, 已用%, resetAt)。"""
    q = []
    for m in models:
        name, pct = m[0], m[1]
        r = m[2] if len(m) > 2 else reset
        q.append({"model": name, "percent": pct, "resetAt": r,
                  "series": [[0, 0.0], [1000, float(pct)]]})
    return {"today": {"token": 1, "in": 1, "out": 0, "credit": 0, "ratePerSec": 0},
            "active": [], "files": 1, "updated": "04:00:00", "quota": q}


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa: F841

    # ---------- 1. 指针基础 ----------
    print("A. 指针基础")
    p = DetailPage(640)
    check(p.quota_count() == 0, "空卡 count=0")
    check(p.quota_cycle() is False, "空卡 cycle 返回 False（不该越界）")
    check(p._quota_key() is None, "空卡没有 key")

    p.set_summary(mk(("a", 90), ("b", 50), ("c", 10)))
    check(p.quota_count() == 3, "三模型 count=3")
    check(p._quota_idx == 0 and p._quota_key() == ("a", 1000), "初始指针在第一张（已用最多）")
    check(p.quota_cycle() is True and p._quota_idx == 1, "cycle 前进到第 2 张")
    check(p._quota_key() == ("b", 1000), "第 2 张是 b")
    check(p.quota_cycle() and p._quota_idx == 2, "再前进到第 3 张")
    check(p.quota_cycle() and p._quota_idx == 0, "走到底回绕到第 1 张")

    # ---------- 2. 单模型不轮播 ----------
    print("B. 单模型")
    p.set_summary(mk(("only", 12)))
    check(p.quota_count() == 1, "单模型 count=1")
    check(p.quota_cycle() is False, "单模型 cycle 返回 False")
    check(p._quota_idx == 0, "单模型指针恒为 0")
    # 注意：从多模型退到单模型时允许有一次淡入（内容确实换了张卡），
    # 但单模型自己不该被「轮播」推动，也不该反复淡入
    p._quota_fade_t0 = 0.0
    check(p.quota_cycle() is False and p._quota_fade_t0 == 0.0, "单模型 cycle 不启动淡入")

    # ---------- 3. 淡入 ----------
    print("C. 淡入")
    p = DetailPage(640)
    p.set_summary(mk(("a", 10), ("b", 20)))
    check(p.quota_animating() is False, "首次出卡不淡入")
    check(p._quota_fade_alpha(1.0) == 1.0, "首次出卡 alpha 就是 1")
    p.quota_cycle()
    check(p.quota_animating() is True, "切换后进入淡入")
    a0 = p._quota_fade_alpha(1.0)
    check(0.29 <= a0 <= 0.5, "淡入起点约 0.3（不从 0 起，避免卡片看起来空了）")
    time.sleep(QUOTA_FADE_SEC + 0.08)
    check(p.quota_animating() is False, "淡入到期自动结束")
    check(p._quota_fade_alpha(1.0) == 1.0, "淡入结束后 alpha 回到 1")
    p.quota_cycle(fade=False)
    check(p.quota_animating() is False, "fade=False 直接落定（减弱动效路径）")
    check(p._quota_fade_alpha(1.0) == 1.0, "fade=False 不产生中间 alpha")

    # ---------- 4. 数据刷新时指针跟随「模型」而非「下标」----------
    print("D. 刷新时跟随模型")
    p = DetailPage(640)
    p.set_summary(mk(("a", 90), ("b", 50), ("c", 10)))
    p.quota_cycle()                          # 正在看 b
    check(p._quota_key()[0] == "b", "先切到 b")
    # b 涨到 99：排序变成 b,a,c，下标从 1 变 0，但用户该继续看到 b
    p.set_summary(mk(("b", 99), ("a", 90), ("c", 10)))
    check(p._quota_key()[0] == "b", "排序抖动后仍显示 b（不跟着下标跳）")
    check(p._quota_idx == 0, "指针位置随 b 的新下标更新")
    # 未变化的重扫不该改动指针
    p.set_summary(mk(("b", 99), ("a", 90), ("c", 10)))
    check(p._quota_key()[0] == "b", "数据未变时指针不动")

    # ---------- 5. 正在看的模型消失 ----------
    print("E. 模型消失 / 换窗口")
    p = DetailPage(640)
    p.set_summary(mk(("a", 90), ("b", 50)))
    p.quota_cycle()
    check(p._quota_key()[0] == "b", "在看 b")
    p.set_summary(mk(("a", 90),))
    check(p._quota_key()[0] == "a", "b 没了 → 回到已用最多的 a")
    check(p.quota_animating() is True, "被迫换卡时给一次淡入，好让眼睛知道内容变了")

    p = DetailPage(640)
    p.set_summary(mk(("a", 90, 111), ("b", 50, 222)))
    p.quota_cycle()
    check(p._quota_key()[0] == "b", "在看 b（窗口 222）")
    # 同名模型换了新窗口（resetAt 变了）＝ 一条全新的曲线，不该沿用指针
    p.set_summary(mk(("a", 90, 333), ("b", 5, 444)))
    check(p._quota_idx == 0 and p._quota_key() == ("a", 333), "窗口轮换后回到第一张")

    # ---------- 6. 展开时重置 ----------
    print("F. 展开重置")
    p = DetailPage(640)
    p.set_summary(mk(("a", 90), ("b", 50)))
    p.quota_cycle()
    p.quota_reset_cycle()
    check(p._quota_idx == 0, "重新展开回到已用最多的那张")
    check(p.quota_animating() is False, "展开不触发淡入（否则一打开就闪）")

    # ---------- 7. 高度与绘制稳定性 ----------
    print("G. 高度 / 绘制")
    p = DetailPage(640)
    p.set_summary(mk(("a", 90), ("b", 50), ("c", 10)))
    h = p.preferred_height()
    p.quota_cycle()
    check(p.preferred_height() == h, "切换模型不改高度（卡片高度固定）")
    check(abs(h - (p.preferred_height())) < 0.01, "高度稳定")
    check(QUOTA_H > 0 and QUOTA_CYCLE_SEC >= 3.0, "轮播间隔不短于 3s（来不及读就是闪烁）")

    p.set_summary(mk(("many-1", 90), ("many-2", 80), ("many-3", 70), ("many-4", 60),
                     ("many-5", 50), ("many-6", 40), ("many-7", 30)))
    p._quota_idx = 3
    img = QtGui.QImage(640, int(p.preferred_height()) + 2,
                       QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    pa = QtGui.QPainter(img)
    pa.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    rect = QtCore.QRectF(0, 0, 640, p.preferred_height())
    try:
        p.paint(pa, rect, 1.0)
        drew = True
    except Exception as e:                       # noqa: BLE001
        drew = False
        print("   paint 抛异常:", e)
    pa.end()
    check(drew, "7 个模型（点阵退化成页码）能正常绘制")
    # 半透明淡入中也要能画
    p.quota_cycle()
    img2 = QtGui.QImage(640, int(p.preferred_height()), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img2.fill(QtCore.Qt.GlobalColor.transparent)
    pa2 = QtGui.QPainter(img2)
    try:
        p.paint(pa2, rect, 0.6)
        drew2 = True
    except Exception as e:                       # noqa: BLE001
        drew2 = False
        print("   paint 抛异常:", e)
    pa2.end()
    check(drew2, "淡入中途（整体 alpha 0.6）能正常绘制")

    # ---------- 8. window 侧的接线（静态断言，避免起窗口）----------
    print("H. window 接线")
    src = (HERE / "window.py").read_text(encoding="utf-8")
    check("_sync_quota_timer" in src, "apply_summary 会同步轮播定时器")
    check(src.count("self._quota_cycle.stop()") >= 2, "收起与只剩一个模型时都停定时器")
    check("quota_reset_cycle()" in src, "展开时重置指针到第一张")
    check("quota_animating()" in src, "_needs_frames 认轮播淡入，动画期间继续出帧")
    check("fade=not self.reduced" in src, "减弱动效时切卡不淡入")

    print("B15 ALL PASS (%d checks)" % OK)


if __name__ == "__main__":
    main()
