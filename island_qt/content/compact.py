# -*- coding: utf-8 -*-
"""island_qt/content/compact.py — 收起态内容（B5）。

排版语言照 wisland 的收起态（`island.py` 的 `_paint_idle` / `compact.py` 的 `_paint_activity`）：

    · 基线对齐。label 用次级色小字，数值用 DemiBold 等宽数字；
      不用「两段各自垂直居中」——13px 与 11px 中心对齐会错开半个像素，看着发飘。
    · 分隔用 wisland 自己的小圆点（`_paint_dots` 的 3.4×1.7 圆角块），
      不用「·」字符：字形度量随字体回退变化，换机器就歪。
    · 颜色一律走 `theme` 令牌；alpha 直接乘进颜色，不用 `p.setOpacity()`
      —— 外层形变淡入已经在控制不透明度，嵌套 setOpacity 会把它覆盖掉。

内容三格：`Token 57.4M` · `积分 89.37` · `流速 243.3/s`，**恒定三格**。

> 2026-11-14 用户决定：收起态不展示进行中的会话，会话明细只在展开态出现。
> 这里原有的走马灯（`对话 <标题>` 滚动、两端 alpha 渐隐、独立 30fps 节拍）已整段删除：
> 滚动版实测要 3.12% CPU 常驻，换来的信息在展开态能看得更全。

宽度是**构造期一次性算定**的常量：数值变化（57.4M → 57.5M、999.9K → 1.0M）
不会让胶囊变宽变窄，只有数字在自己的槽内变化 —— 这是「不抽搐」的前提。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui

from ui.theme import W, theme, ui_font

# ---- 几何 ----
H = 34.0                  # 胶囊高度（wisland H_IDLE）
PAD_L, PAD_R = 16.0, 14.0
GAP_LABEL = 4.0           # label 与数值之间
SEP_D = 3.4               # 分隔点直径（同 island.py 的页码点）
SEP_GAP = 5.0             # 点两侧留白（2026-11-14 由 6 收到 5：省下的 4px 补给数值槽）

# ---- 文案 ----
LABEL_TOKEN = "Token"
LABEL_CREDIT = "积分"
LABEL_RATE = "流速"
PLACEHOLDER = "—"          # 首份数据到达前的占位（不显示 0，避免被读成本日真实用量）
PH_ALPHA = 0.34            # 占位的绘制亮度（数值常态是 0.96）

# 槽宽按这些样本测最大值，避免真实数值长度变化时整行左右漂。
#
# 2026-11-14 修：数字是**比例数字**，不是等宽 tabular ——「1」6px、其余 7px；
# 字母更是差得多（M 12px、K 9px、B 8px）。所以「字符数一样就一样宽」不成立：
# 旧样本把宽数字（999.9）配窄字母（K），真实最坏「999.9M」= 46px 比槽宽 42px 宽 4px，
# 会直接压到右边的分隔点上（100.0M 起整个 M 域都溢）。样本必须按**最坏组合**取，
# 即「最宽数字 + 最宽字母」，不能按「最宽字符串」凭感觉挑一条。
SAMPLE_TOKEN = ("888", "999.9K", "999.9M", "9.9B")   # 最坏 999.9M / 888.8M = 46px
SAMPLE_CREDIT = ("0.00", "88.88", "999.99", "1.2k")  # 最坏 999.99 / 999.9k = 41px
SAMPLE_RATE = ("0/s", "999.9/s", "88.8k/s", "99.9k/s")  # 最坏 45px（见 fmt_rate 的 7 字符封顶）


# ================================================================ 格式化
def fmt_tokens(n: float) -> str:
    """1234567 → 1.2M。收起态只用一位小数，宽度可预期。"""
    n = float(n or 0)
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return str(int(n))


def fmt_credit(c: float) -> str:
    """积分：千以上折算成 k，避免数字把槽撑破（最坏 999.99 / 999.9k 都是 41px）。"""
    c = float(c or 0)
    if c >= 1e3:
        return f"{c / 1e3:.1f}k"
    return f"{c:.2f}"


def fmt_rate(v: float) -> str:
    """流速：0 就显示 0/s，不出现 0.0/s 这种噪声。

    **契约：输出不超过 7 个字符**（胶囊的流速槽就是按 7 字符 45px 定宽的）。
    2026-11-14 修：k/s 域原来一律留一位小数，于是 100.0k/s~999.9k/s 会变成 8 字符
    「999.9k/s」= 53px，比槽宽 45.2px 多 7.8px 直接怼到右内边距上。
    现在三位整数段（≥100k）只留整数位、≥1M 折成 M/s，最坏仍是 7 字符
    —— 「99.9k/s」45px 与「999.9/s」45px 同宽。
    """
    v = float(v or 0)
    if v < 0.05:
        return "0/s"
    if v >= 1e6:
        return f"{v / 1e6:.0f}M/s"
    if v >= 1e5:
        k = round(v / 1000.0)
        if k >= 1000:
            # 999.5k~999.9k 四舍五入会进位成「1000k/s」= 47px，比槽宽还宽 1.8px；
            # 这种量级本来就是 1.0M/s 了，直接折上去
            return "1.0M/s"
        return f"{k}k/s"
    if v >= 1000:
        return f"{v / 1000:.1f}k/s"
    return f"{v:.1f}/s"


class Compact:
    """收起态：一行三段数据。只负责内容，不碰窗口几何、不做任何滚动。"""

    def __init__(self) -> None:
        self.f_label = ui_font(11)
        self.f_value = ui_font(13, W.DemiBold, num=True)

        self._fm_label = QtGui.QFontMetrics(self.f_label)
        self._fm_value = QtGui.QFontMetrics(self.f_value)

        # ---- 数据 ----
        self._token = 0.0
        self._credit = 0.0
        self._rate = 0.0
        # 首份数据到达前不显示 0：扫描要 1.7s，显示 `0 · 0.00 · 0/s` 会被当成本日真实用量。
        # 用破折号占位，明确「还在读」。
        self._ready = False

        # ---- 固定槽宽（构造期一次算定，之后永不随数据变化）----
        self._dx_token = self._fm_label.horizontalAdvance(LABEL_TOKEN) + GAP_LABEL
        self._dx_credit = self._fm_label.horizontalAdvance(LABEL_CREDIT) + GAP_LABEL
        self._dx_rate = self._fm_label.horizontalAdvance(LABEL_RATE) + GAP_LABEL
        w_token = self._dx_token + max(self._fm_value.horizontalAdvance(s) for s in SAMPLE_TOKEN)
        w_credit = self._dx_credit + max(self._fm_value.horizontalAdvance(s) for s in SAMPLE_CREDIT)
        w_rate = self._dx_rate + max(self._fm_value.horizontalAdvance(s) for s in SAMPLE_RATE)
        sep = SEP_D + 2 * SEP_GAP

        self._x_credit = w_token + sep                  # 相对内容左沿
        self._x_rate = self._x_credit + w_credit + sep
        self.width = float(round(PAD_L + self._x_rate + w_rate + PAD_R))

        # 基线：按数值字号把整行垂直居中，label 与数值共用这条基线
        self._baseline = (H - self._fm_value.height()) / 2.0 + self._fm_value.ascent()

    # ================================================================ 数据
    def set_summary(self, data: dict) -> bool:
        """吃 scan_service 的 summary。返回内容是否变化（变了才需要重绘）。

        `active` 列表这里**故意不看**：收起态不展示会话，只看它会让胶囊为无关内容重绘。
        """
        s = data or {}
        t = s.get("today") or {}
        new = (float(t.get("token") or 0), float(t.get("credit") or 0),
               float(t.get("ratePerSec") or 0))
        if new == (self._token, self._credit, self._rate):
            if not self._ready:                    # 首份数据恰好全 0：也要退出占位态
                self._ready = True
                return True
            return False
        self._token, self._credit, self._rate = new
        self._ready = True
        return True

    def plain_text(self) -> str:
        """给 --self-test / 日志用的纯文本。"""
        if not self._ready:
            return f"{LABEL_TOKEN} —   ·   {LABEL_CREDIT} —   ·   {LABEL_RATE} —"
        return (f"{LABEL_TOKEN} {fmt_tokens(self._token)}   ·   "
                f"{LABEL_CREDIT} {fmt_credit(self._credit)}   ·   "
                f"{LABEL_RATE} {fmt_rate(self._rate)}")

    # ================================================================ 绘制
    def paint(self, p: QtGui.QPainter, rect: QtCore.QRectF, a: float = 1.0) -> None:
        if a <= 0.004 or rect.width() < 40:
            return
        base = rect.top() + self._baseline
        left = rect.left() + PAD_L
        v_tok = fmt_tokens(self._token) if self._ready else PLACEHOLDER
        v_cre = fmt_credit(self._credit) if self._ready else PLACEHOLDER
        v_rat = fmt_rate(self._rate) if self._ready else PLACEHOLDER
        # 占位态整体压暗：DemiBold 的破折号很实，全亮度看像三根白条、像"数据"，压暗才读得出"在读"。
        va = 0.96 * a if self._ready else PH_ALPHA * a

        self._draw_segment(p, left, base, self._dx_token, LABEL_TOKEN, v_tok, a, va)
        self._draw_sep(p, left + self._x_credit - SEP_GAP - SEP_D / 2, rect.center().y(), a)
        self._draw_segment(p, left + self._x_credit, base, self._dx_credit,
                           LABEL_CREDIT, v_cre, a, va)
        self._draw_sep(p, left + self._x_rate - SEP_GAP - SEP_D / 2, rect.center().y(), a)
        self._draw_segment(p, left + self._x_rate, base, self._dx_rate,
                           LABEL_RATE, v_rat, a, va)

    def _draw_segment(self, p: QtGui.QPainter, x: float, base: float, dx: float,
                      label: str, value: str, a: float, va: float | None = None) -> None:
        p.setFont(self.f_label)
        p.setPen(theme.text3(a))
        p.drawText(QtCore.QPointF(x, base), label)
        p.setFont(self.f_value)
        p.setPen(theme.text(0.96 * a if va is None else va))
        p.drawText(QtCore.QPointF(x + dx, base), value)

    def _draw_sep(self, p: QtGui.QPainter, cx: float, cy: float, a: float) -> None:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(theme.text3(0.7 * a))
        p.drawRoundedRect(QtCore.QRectF(cx - SEP_D / 2, cy - SEP_D / 2, SEP_D, SEP_D), 1.7, 1.7)
