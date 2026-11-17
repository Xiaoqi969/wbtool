# -*- coding: utf-8 -*-
"""island_qt/content/detail.py — 展开态明细页（B6）。

视觉语言照 wisland 的 `pages/`（`Card` 圆角 18、极淡白底、无描边无分割线、Label 三档文字）：

    · 卡片不是「框」，是**一层极淡的白底**。分隔靠留白与字号层级，不画线 ——
      毛玻璃上画细线会与背景纹理打架，看着脏。
    · 数字一律等宽族（`ui_font(..., num=True)`），刷新时不左右跳。
    · 标题 13 DemiBold / 卡片 label 11 次级 / 主数值 19 DemiBold / 行内 12.5，
      层级只有四档，再多就吵。

与 wisland 的实现差异（有意为之）：wisland 的页面是 QWidget 子控件树（`Card` + `vbox` + `Label`），
我们用**单 QPainter 合成**——窗口本身是一张自绘的透明分层表面，背景还带静止缓存；塞进子控件树
就要每帧 `setMask()` 跟形状、还要处理透明子控件的单独重绘（wisland 自己在 `_set_content_opacity`
里也为此放弃了 `QGraphicsOpacityEffect`）。所以这里把卡片和行**画**出来，参数照抄 `widgets.py`。

高度自适应：`preferred_height()` 由行数算出，窗口只调高度弹簧的目标值（`island.py:444` 的做法）。
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui

from content.compact import fmt_credit, fmt_rate, fmt_tokens
from ui.theme import W, theme, ui_font

Qt = QtCore.Qt

# ---- 几何（相对本页左上角；本页宽度就是展开态宽度）----
PAD_X = 16.0             # 左右内边距
PAD_TOP = 14.0
PAD_BOTTOM = 14.0
HEADER_H = 20.0
GAP = 10.0               # 区块之间的竖向间距
CARD_R = 18.0            # 卡片圆角（同 widgets.py 的 Card(radius=18)）
CARD_PAD_X = 14.0
STATS_H = 78.0           # 三列指标卡固定高
ROW_H = 22.0             # 会话行高
MAX_ROWS = 5             # 超过就折成一行「还有 N 个会话」，不把面板拉成一条
FOOT_H = 14.0

# ---- 文案 ----
TITLE = "今日用量"
SEC_SESSIONS = "进行中会话"
EMPTY_TEXT = "暂无进行中的会话"
FOOT_TMPL = "每 %d 秒刷新 · %d 个日志文件"
REFRESH_SEC = 10          # 与 scan_service.SCAN_INTERVAL_SEC 一致（曾误写成 60）


class DetailPage:
    """展开态内容：头部（标题 + 流速药丸）→ 指标卡 → 会话卡 → 脚注。"""

    def __init__(self, width: float = 640.0) -> None:
        self.width = float(width)

        self.f_title = ui_font(13, W.DemiBold)
        self.f_meta = ui_font(10.5, num=True)
        self.f_label = ui_font(11)
        self.f_value = ui_font(19, W.DemiBold, num=True)
        self.f_pill = ui_font(11, num=True)
        self.f_sec = ui_font(11.5, W.DemiBold)
        self.f_name = ui_font(12.5)
        self.f_tok = ui_font(11.5, num=True)
        self.f_time = ui_font(10.5, num=True)
        self.f_empty = ui_font(11.5)
        self.f_foot = ui_font(10)

        self._fm_name = QtGui.QFontMetrics(self.f_name)

        # ---- 数据 ----
        self._token = 0.0
        self._in = 0.0
        self._out = 0.0
        self._credit = 0.0
        self._rate = 0.0
        self._updated = "--:--:--"
        self._files = 0
        # (标题, 今日 token, 该会话自己的流速 tok/s, 最后活跃)
        self._sessions: list[tuple[str, float, float, str]] = []

    # ================================================================ 数据
    def set_summary(self, data: dict) -> bool:
        """吃 scan_service 的 summary。返回内容是否变化。"""
        s = data or {}
        t = s.get("today") or {}
        sessions = [(str(a.get("name") or "会话"), float(a.get("tokens") or 0),
                     float(a.get("rate") or 0), str(a.get("last") or ""))
                    for a in (s.get("active") or [])]
        new = (float(t.get("token") or 0), float(t.get("in") or 0), float(t.get("out") or 0),
               float(t.get("credit") or 0), float(t.get("ratePerSec") or 0),
               int(s.get("files") or 0), str(s.get("updated") or ""), sessions)
        old = (self._token, self._in, self._out, self._credit, self._rate,
               self._files, self._updated, self._sessions)
        if new == old:
            return False
        (self._token, self._in, self._out, self._credit, self._rate,
         self._files, self._updated, self._sessions) = new
        return True

    # ================================================================ 高度
    def _rows(self) -> int:
        """会话卡里实际占几行（含「还有 N 个」那行）。空列表也占一行提示。"""
        n = len(self._sessions)
        if n == 0:
            return 1
        return min(n, MAX_ROWS) + (1 if n > MAX_ROWS else 0)

    def _sessions_h(self) -> float:
        # 卡内：上内边距 + 小标题 + 间距 + 行 + 下内边距
        return 12.0 + 18.0 + 6.0 + self._rows() * ROW_H + 12.0

    def preferred_height(self) -> float:
        return (PAD_TOP + HEADER_H + GAP + STATS_H + GAP
                + self._sessions_h() + 8.0 + FOOT_H + PAD_BOTTOM)

    # ================================================================ 绘制
    def paint(self, p: QtGui.QPainter, rect: QtCore.QRectF, a: float = 1.0) -> None:
        if a <= 0.004:
            return
        p.save()
        p.translate(rect.left(), rect.top())
        W_ = rect.width()

        y = self._paint_header(p, W_, a)
        y = self._paint_stats(p, W_, y + GAP, a)
        y = self._paint_sessions(p, W_, y + GAP, a)
        self._paint_footer(p, W_, y + 8.0, a)
        p.restore()

    # ---- 头部：标题 + 「流速」药丸 ----
    def _paint_header(self, p: QtGui.QPainter, w: float, a: float) -> float:
        r = QtCore.QRectF(PAD_X, PAD_TOP, w - 2 * PAD_X, HEADER_H)
        p.setFont(self.f_title)
        p.setPen(theme.text(0.95 * a))
        p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, TITLE)

        # 药丸：所有会话合计的流速。标「总」是为了和下面每行的「本会话流速」区分开
        txt = f"总流速 {fmt_rate(self._rate)}"
        fm = QtGui.QFontMetrics(self.f_pill)
        pw = fm.horizontalAdvance(txt) + 18
        pr = QtCore.QRectF(r.right() - pw, r.center().y() - 9.5, pw, 19)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        bg = theme.hover()
        bg.setAlphaF(max(0.0, min(1.0, bg.alphaF() * 0.55 * a)))
        p.setBrush(bg)
        p.drawRoundedRect(pr, 9.5, 9.5)
        p.setFont(self.f_pill)
        p.setPen(theme.text2(a))
        p.drawText(pr, Qt.AlignmentFlag.AlignCenter, txt)
        return r.bottom()

    # ---- 指标卡：Token 合计 / 输入 / 输出 / 积分 ----
    def _paint_stats(self, p: QtGui.QPainter, w: float, top: float, a: float) -> float:
        card = QtCore.QRectF(PAD_X, top, w - 2 * PAD_X, STATS_H)
        self._card(p, card, a)

        cols = (("Token 合计", fmt_tokens(self._token)),
                ("输入", fmt_tokens(self._in)),
                ("输出", fmt_tokens(self._out)),
                ("积分", fmt_credit(self._credit)))
        inner_l = card.left() + CARD_PAD_X
        inner_w = card.width() - 2 * CARD_PAD_X
        cw = inner_w / len(cols)
        for i, (label, value) in enumerate(cols):
            x = inner_l + cw * i
            p.setFont(self.f_label)
            p.setPen(theme.text3(a))
            p.drawText(QtCore.QRectF(x, card.top() + 12, cw - 6, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.setFont(self.f_value)
            p.setPen(theme.text(0.96 * a))
            p.drawText(QtCore.QRectF(x, card.top() + 30, cw - 6, 27),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
        return card.bottom()

    # ---- 会话卡 ----
    def _paint_sessions(self, p: QtGui.QPainter, w: float, top: float, a: float) -> float:
        card = QtCore.QRectF(PAD_X, top, w - 2 * PAD_X, self._sessions_h())
        self._card(p, card, a)

        inner_l = card.left() + CARD_PAD_X
        inner_r = card.right() - CARD_PAD_X
        n = len(self._sessions)

        p.setFont(self.f_sec)
        p.setPen(theme.text2(a))
        p.drawText(QtCore.QRectF(inner_l, card.top() + 10, card.width() * 0.6, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, SEC_SESSIONS)
        p.setFont(self.f_meta)
        p.setPen(theme.text3(a))
        p.drawText(QtCore.QRectF(inner_r - 80, card.top() + 10, 80, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{n} 个")

        y = card.top() + 12.0 + 18.0 + 6.0
        if n == 0:
            p.setFont(self.f_empty)
            p.setPen(theme.text3(a))
            p.drawText(QtCore.QRectF(inner_l, y, card.width() - 2 * CARD_PAD_X, ROW_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, EMPTY_TEXT)
            return card.bottom()

        # 列：标题（可省略）| 本会话流速 | 今日 token | 最后活跃
        w_time, w_tok, w_rate, gap = 44.0, 54.0, 48.0, 8.0
        x_rate = inner_r - w_time - gap - w_tok - gap - w_rate
        name_w = x_rate - gap - inner_l
        for i, (name, tok, rate, last) in enumerate(self._sessions[:MAX_ROWS]):
            ry = y + i * ROW_H
            p.setFont(self.f_name)
            p.setPen(theme.text(0.92 * a))
            elided = self._fm_name.elidedText(name, QtCore.Qt.TextElideMode.ElideRight, int(name_w))
            p.drawText(QtCore.QRectF(inner_l, ry, name_w, ROW_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
            # 本会话流速：只有真的在产出才给数字，静默会话留一个破折号——
            # 五行都写 0/s 是噪声不是信息（进行中 ≠ 正在生成）。
            p.setFont(self.f_tok)
            if rate >= 0.05:
                p.setPen(theme.text2(a))
                rate_text = fmt_rate(rate)
            else:
                p.setPen(theme.text3(0.9 * a))
                rate_text = "—"
            p.drawText(QtCore.QRectF(x_rate, ry, w_rate, ROW_H),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, rate_text)
            p.setPen(theme.text2(a))
            p.drawText(QtCore.QRectF(inner_r - w_time - gap - w_tok, ry, w_tok, ROW_H),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, fmt_tokens(tok))
            p.setFont(self.f_time)
            p.setPen(theme.text3(a))
            p.drawText(QtCore.QRectF(inner_r - w_time, ry, w_time, ROW_H),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, last)

        if n > MAX_ROWS:
            ry = y + MAX_ROWS * ROW_H
            p.setFont(self.f_time)
            p.setPen(theme.text3(a))
            p.drawText(QtCore.QRectF(inner_l, ry, inner_r - inner_l, ROW_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"还有 {n - MAX_ROWS} 个会话")
        return card.bottom()

    # ---- 脚注 ----
    def _paint_footer(self, p: QtGui.QPainter, w: float, top: float, a: float) -> None:
        p.setFont(self.f_foot)
        p.setPen(theme.text3(0.85 * a))
        p.drawText(QtCore.QRectF(PAD_X, top, w - 2 * PAD_X, FOOT_H),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                   FOOT_TMPL % (REFRESH_SEC, self._files))

    # ---- 卡片底：极淡白，无描边 ----
    def _card(self, p: QtGui.QPainter, r: QtCore.QRectF, a: float) -> None:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(theme.card(a))
        p.drawRoundedRect(r, CARD_R, CARD_R)
