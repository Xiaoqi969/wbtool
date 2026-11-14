# -*- coding: utf-8 -*-
"""B5 宽度验收：胶囊是 274 到底"够不够 / 还能不能更短"。

    python island_qt/_probe_b5w.py            量测 + 断言（约 3 秒）
    python island_qt/_probe_b5w.py --shot     额外截图到 %TEMP%/b5w/

测什么：
  A 拆解   274 的每一像素花在哪
  B 穷扫   把三个 fmt_* 的整个输出空间（十几万条）全量过一遍，
           逐条断言「数值宽度 ≤ 槽宽」——不靠样本猜，靠枚举证明
  C 极限   999.9M / 999.99 / 9999/s 这一组够不够，还剩多少
  D 更短   每一处还能省几像素（仅供决策，不改代码）
"""
from __future__ import annotations

import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import content.compact as C  # noqa: E402


def all_strings():
    """枚举三个 formatted 的整个输出空间。"""
    tok, cre, rat = set(), set(), set()
    for i in range(0, 1000):
        tok.add(C.fmt_tokens(float(i)))
    for mag in (1e3, 1e6, 1e9):
        for k in range(10, 10000):
            tok.add(C.fmt_tokens(k / 10.0 * mag))
    for i in range(0, 100000):
        cre.add(C.fmt_credit(i / 100.0))
    for k in range(10, 10000):
        cre.add(C.fmt_credit(k / 10.0 * 1e3))
    for k in range(0, 30000):
        rat.add(C.fmt_rate(k / 10.0))
    for k in range(10, 10000):
        rat.add(C.fmt_rate(k / 10.0 * 1000.0))
    for k in range(0, 3000):
        rat.add(C.fmt_rate(k * 1e3 + 500.0))
    return tok, cre, rat


def main() -> int:
    shot = "--shot" in sys.argv
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    c = C.Compact()
    fm = c._fm_value
    adv = fm.horizontalAdvance
    sep = C.SEP_D + 2 * C.SEP_GAP

    w_token = c._x_credit - sep
    w_credit = c._x_rate - c._x_credit - sep
    w_rate = c.width - C.PAD_L - c._x_rate - C.PAD_R

    print("=" * 70)
    print("A 拆解  width = %.1f" % c.width)
    print("-" * 70)
    print("  PAD_L                  %6.1f" % C.PAD_L)
    print("  ① Token  %5.1f = label %4.1f + gap %.0f + 数值槽 %5.1f"
          % (w_token, c._dx_token - C.GAP_LABEL, C.GAP_LABEL, w_token - c._dx_token))
    print("  分隔点   %5.1f = %.1f + 2×%.0f" % (sep, C.SEP_D, C.SEP_GAP))
    print("  ② 积分  %5.1f = label %4.1f + gap %.0f + 数值槽 %5.1f"
          % (w_credit, c._dx_credit - C.GAP_LABEL, C.GAP_LABEL, w_credit - c._dx_credit))
    print("  分隔点   %5.1f" % sep)
    print("  ③ 流速  %5.1f = label %4.1f + gap %.0f + 数值槽 %5.1f"
          % (w_rate, c._dx_rate - C.GAP_LABEL, C.GAP_LABEL, w_rate - c._dx_rate))
    print("  PAD_R                  %6.1f" % C.PAD_R)

    print()
    print("=" * 70)
    print("B 穷扫全输出空间（不靠样本，逐条断言）")
    print("-" * 70)
    tok, cre, rat = all_strings()
    bad_total = 0
    for name, pool, slot in (("Token", tok, w_token - c._dx_token),
                             ("积分", cre, w_credit - c._dx_credit),
                             ("流速", rat, w_rate - c._dx_rate)):
        over = sorted((s for s in pool if adv(s) > slot), key=lambda s: -adv(s))
        wmax = max(adv(s) for s in pool)
        longest = max(pool, key=len)
        print("  %-5s 输出 %6d 种；最宽 %dpx（槽 %5.1f）；最长 %d 字符（%s）"
              % (name, len(pool), wmax, slot, len(longest), longest))
        if over:
            bad_total += len(over)
            print("        ✗ 溢出 %d 种，例：%s" % (len(over), over[:5]))
        else:
            print("        ✓ 无一条溢出，余量 %+.1fpx" % (slot - wmax))
    print("  %s" % ("全部通过" if not bad_total else "✗ 共 %d 种溢出" % bad_total))

    print()
    print("=" * 70)
    print("C 用户点名的极限值 999.9M / 999.99 / 9999/s")
    print("-" * 70)
    for tag, t, cr, rt in (("用户说的", 999.9e6, 999.99, 9999.0),
                           ("再往上一档", 999.9e9, 999.99, 999.9e3),
                           ("真的极限", 999.9e9, 999.99, 999.9e3)):
        st, sc, sr = C.fmt_tokens(t), C.fmt_credit(cr), C.fmt_rate(rt)
        vals = (("Token", st, w_token - c._dx_token), ("积分", sc, w_credit - c._dx_credit),
                ("流速", sr, w_rate - c._dx_rate))
        used = (C.PAD_L + c._dx_token + adv(st) + sep + c._dx_credit + adv(sc) + sep
                + c._dx_rate + adv(sr) + C.PAD_R)
        print("  %s：Token %s · 积分 %s · 流速 %s" % (tag, st, sc, sr))
        print("     这行用 %.1fpx / 胶囊 %.1fpx → 余 %+.1fpx；三格 %s"
              % (used, c.width, c.width - used,
                 "  ".join("%s %.0f/%.0f" % (n, adv(s), slot) for n, s, slot in vals)))

    print()
    print("=" * 70)
    print("D 还能更短吗（每一项的像素代价，仅决策参考）")
    print("-" * 70)
    plans = [
        ("PAD_L 16→12 + PAD_R 14→12（贴边）", 6.0),
        ("SEP_GAP 5→4（两个点各两边）", 4.0),
        ("GAP_LABEL 4→3（三处）", 3.0),
        ("积分 2 位小数→1 位（999.99→999.9）", adv("999.99") - adv("999.9")),
        ("流速 1 位小数→0 位（243.3/s→243/s）", adv("999.9/s") - adv("999/s")),
        ("label「Token」→「T」", adv("Token") * 0 + c._fm_label.horizontalAdvance("Token")
         - c._fm_label.horizontalAdvance("T")),
        ("去掉一个分隔点（三段并两段）", sep),
    ]
    tot = 0.0
    for name, save in plans:
        tot += save
        print("  %-38s 省 %5.1fpx → %.0f" % (name, save, c.width - save))
    print("  %-38s 省 %5.1fpx → %.0f（要牺牲语义）" % ("全部叠加", tot, c.width - tot))

    if shot:
        out = os.path.join(os.environ.get("TEMP", "."), "b5w")
        os.makedirs(out, exist_ok=True)
        cases = [("limit", (999.9e6, 999.99, 9999.0)),
                 ("hit-max", (999.9e9, 999.99, 999.9e3)),
                 ("rate-max", (158.8e6, 216.86, 999.9e3)),
                 ("typical", (57.4e6, 89.37, 243.3))]
        for tag, (t, cr, rt) in cases:
            cc = C.Compact()
            cc.set_summary({"today": {"token": t, "credit": cr, "ratePerSec": rt}})
            sc = 3
            img = QtGui.QImage(int(c.width * sc), int(C.H * sc),
                               QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QtGui.QColor(20, 20, 24))
            p = QtGui.QPainter(img)
            p.scale(sc, sc)
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            cc.paint(p, QtCore.QRectF(0, 0, c.width, C.H))
            p.end()
            fp = os.path.join(out, tag + ".png")
            img.save(fp)
            print("  截图 %s  (%.1f, %.1f)  %s" % (fp, c.width, C.H, cc.plain_text()))

    del app
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
