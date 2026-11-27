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

import time

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

# 额度卡：标题行 18 + 间距 8 + 曲线 42 + 间距 3 + 轴标签 12，上下各 12/11 —— 合计 106
QUOTA_H = 106.0
QUOTA_PAD_T = 12.0
QUOTA_TITLE_H = 18.0
QUOTA_CHART_H = 42.0
QUOTA_AXIS_H = 12.0
QUOTA_WARN = 80.0        # 已用 ≥80% 转警示色（琥珀），≥95% 的文字性提示由百分比本身承担

# 会话行内的上下文进度条：26px 细条 + 5px 间距 + 29px 百分比，合计一列 60
CTX_BAR_W = 26.0
CTX_BAR_H = 3.4
CTX_GAP = 5.0
CTX_TEXT_W = 29.0
CTX_W = CTX_BAR_W + CTX_GAP + CTX_TEXT_W
CTX_WARN = 80.0          # 上下文占用 ≥80% 转警示色：再聊几轮就该开新会话了

# ---- 文案 ----
TITLE = "今日用量"
SEC_SESSIONS = "进行中会话"
SEC_QUOTA = "额度"
EMPTY_TEXT = "暂无进行中的会话"
FOOT_TMPL = "每 %d 秒刷新 · %d 个日志文件"
REFRESH_SEC = 10          # 与 scan_service.SCAN_INTERVAL_SEC 一致（曾误写成 60）


class DetailPage:
    """展开态内容：头部（标题 + 流速药丸）→ 指标卡 → 额度卡 → 会话卡 → 脚注。"""

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
        self.f_pct = ui_font(13, W.DemiBold, num=True)   # 额度卡里的「已用 93%」
        self.f_scale = ui_font(9.5, num=True)            # 曲线刻度的极小字

        self._fm_name = QtGui.QFontMetrics(self.f_name)
        self._fm_meta = QtGui.QFontMetrics(self.f_meta)
        self._fm_pct = QtGui.QFontMetrics(self.f_pct)
        self._fm_time = QtGui.QFontMetrics(self.f_time)
        self._fm_sec = QtGui.QFontMetrics(self.f_sec)

        # ---- 数据 ----
        self._token = 0.0
        self._in = 0.0
        self._out = 0.0
        self._credit = 0.0
        self._rate = 0.0
        self._updated = "--:--:--"
        self._files = 0
        # (标题, 今日 token, 该会话自己的流速 tok/s, 最后活跃, 上下文占用% 或 None)
        self._sessions: list[tuple[str, float, float, str, float | None]] = []
        # [{"model", "percent", "resetAt", "series": [(毫秒, 已用%), ...]}]，已用最多的排第一
        self._quota: list[dict] = []

    # ================================================================ 数据
    def set_summary(self, data: dict) -> bool:
        """吃 scan_service 的 summary。返回内容是否变化。"""
        s = data or {}
        t = s.get("today") or {}
        sessions = [(str(a.get("name") or "会话"), float(a.get("tokens") or 0),
                     float(a.get("rate") or 0), str(a.get("last") or ""), _ctx_pct(a))
                    for a in (s.get("active") or [])]
        quota = _parse_quota(s.get("quota"))
        new = (float(t.get("token") or 0), float(t.get("in") or 0), float(t.get("out") or 0),
               float(t.get("credit") or 0), float(t.get("ratePerSec") or 0),
               int(s.get("files") or 0), str(s.get("updated") or ""), sessions, quota)
        old = (self._token, self._in, self._out, self._credit, self._rate,
               self._files, self._updated, self._sessions, self._quota)
        if new == old:
            return False
        (self._token, self._in, self._out, self._credit, self._rate,
         self._files, self._updated, self._sessions, self._quota) = new
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
        h = PAD_TOP + HEADER_H + GAP + STATS_H
        if self._quota:                    # 没有配额采样就不留空壳，卡片整体不出现
            h += GAP + QUOTA_H
        return h + GAP + self._sessions_h() + 8.0 + FOOT_H + PAD_BOTTOM

    # ================================================================ 绘制
    def paint(self, p: QtGui.QPainter, rect: QtCore.QRectF, a: float = 1.0) -> None:
        if a <= 0.004:
            return
        p.save()
        p.translate(rect.left(), rect.top())
        W_ = rect.width()

        y = self._paint_header(p, W_, a)
        y = self._paint_stats(p, W_, y + GAP, a)
        if self._quota:
            y = self._paint_quota(p, W_, y + GAP, a)
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

    # ---- 额度卡：当前配额窗口的消耗曲线 ----
    def _paint_quota(self, p: QtGui.QPainter, w: float, top: float, a: float) -> float:
        """一张卡回答两件事：这窗口已经用掉多少、曲线是怎么爬上来的。

        为什么画曲线而不是只写一个百分比：百分比只能说「现在 93%」，说不出
        「是刚才那一小时冲上去的，还是一整天匀速漏的」——前者该收手，后者无所谓。
        曲线从 0 爬起的斜率就是答案。
        """
        card = QtCore.QRectF(PAD_X, top, w - 2 * PAD_X, QUOTA_H)
        self._card(p, card, a)
        inner_l = card.left() + CARD_PAD_X
        inner_r = card.right() - CARD_PAD_X
        q = self._quota[0]
        pct = float(q["percent"])
        hot = pct >= QUOTA_WARN

        # --- 标题行：左「额度 + 模型名」，右「已用 N% · HH:MM 重置」---
        ty = card.top() + QUOTA_PAD_T
        p.setFont(self.f_sec)
        p.setPen(theme.text2(a))
        p.drawText(QtCore.QRectF(inner_l, ty, 60, QUOTA_TITLE_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, SEC_QUOTA)

        right_txt = _reset_text(q["resetAt"])
        w_right = self._fm_time.horizontalAdvance(right_txt)
        pct_txt = f"已用 {pct:.0f}%"
        w_pct = self._fm_pct.horizontalAdvance(pct_txt)
        x_pct = inner_r - w_right - 6 - w_pct
        p.setFont(self.f_pct)
        p.setPen(theme.warn(a) if hot else theme.text(0.95 * a))
        p.drawText(QtCore.QRectF(x_pct, ty, w_pct, QUOTA_TITLE_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, pct_txt)
        p.setFont(self.f_time)
        p.setPen(theme.text3(a))
        p.drawText(QtCore.QRectF(inner_r - w_right, ty, w_right, QUOTA_TITLE_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right_txt)

        # 模型名夹在两者之间，长了就省略（模型名最坏也就 20 字符，正常放得下）
        x_model = inner_l + self._fm_sec.horizontalAdvance(SEC_QUOTA) + 7
        model_w = max(0.0, x_pct - 10 - x_model)
        p.setFont(self.f_meta)
        p.setPen(theme.text3(a))
        p.drawText(QtCore.QRectF(x_model, ty, model_w, QUOTA_TITLE_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self._fm_meta.elidedText(str(q["model"]),
                                            QtCore.Qt.TextElideMode.ElideMiddle, int(model_w)))

        # --- 曲线 ---
        cy = ty + QUOTA_TITLE_H + 8.0
        chart = QtCore.QRectF(inner_l, cy, inner_r - inner_l, QUOTA_CHART_H)
        self._paint_curve(p, chart, q["series"], a, hot)

        # --- 轴标签行：左「HH:MM 起」，右「现在 HH:MM」，中间放其他模型的当前值 ---
        ay = chart.bottom() + 3.0
        p.setFont(self.f_time)
        p.setPen(theme.text3(0.9 * a))
        start_txt = _start_text(q["series"][0][0])
        p.drawText(QtCore.QRectF(inner_l, ay, 130, QUOTA_AXIS_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, start_txt)
        now_txt = "现在 " + _clock(time.time() * 1000)
        w_now = self._fm_time.horizontalAdvance(now_txt)
        p.drawText(QtCore.QRectF(inner_r - w_now, ay, w_now, QUOTA_AXIS_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, now_txt)

        if len(self._quota) > 1:
            others = "另有 " + " · ".join(
                f"{o['model']} {float(o['percent']):.0f}%" for o in self._quota[1:3])
            if len(self._quota) > 3:
                others += f" · 另 {len(self._quota) - 3} 个"
            x0 = inner_l + self._fm_time.horizontalAdvance(start_txt) + 14
            room = (inner_r - w_now - 12) - x0
            if room > 40:
                p.setPen(theme.text3(0.72 * a))
                p.drawText(QtCore.QRectF(x0, ay, room, QUOTA_AXIS_H),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           self._fm_time.elidedText(others, QtCore.Qt.TextElideMode.ElideRight,
                                                    int(room)))
        return card.bottom()

    def _paint_curve(self, p: QtGui.QPainter, r: QtCore.QRectF,
                     series: list[tuple[float, float]], a: float, hot: bool) -> None:
        """面积折线。横轴 = 本窗口第一个采样 → 现在，纵轴按峰值自动取刻度。

        纵轴自适应（5/10/20/25/50/100 六档）而不是固定 100：多数窗口前几小时只爬到
        3~5%，固定 100 会把它压成贴着底边的一条直线，看不出任何形状；刻度值写在
        曲线空白的那一角，避免「3% 看着像 30%」的误读。
        """
        if not series:
            return
        if len(series) < 2:
            # 只有一个采样点时没有「曲线」可言：画个孤零零的点会被当成渲染故障，
            # 直接说明「还在采样」，等第二轮（≤10s）就有形状了。
            p.setFont(self.f_time)
            p.setPen(theme.text3(0.7 * a))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "本窗口刚开始，曲线还在采样")
            return
        accent = theme.warn() if hot else theme.accent

        t0 = series[0][0]
        t1 = max(series[-1][0], time.time() * 1000)
        # 至少铺 15 分钟：刚开新窗口时只有两三个点，按真实秒数铺开会被拉成一条陡峭的
        # 竖线（看着像「一秒烧掉 20%」），给个最小跨度才是这个时间尺度下的正确读法。
        span = max(15 * 60 * 1000.0, t1 - t0)
        ymax = _y_scale(max(p for _, p in series))

        def px(ms: float) -> float:
            return r.left() + (ms - t0) / span * r.width()

        # 上下各留 2px 内缩：0% 的曲线如果正好压在绘图区底线上，会跟轴标签挤在一起、
        # 看着像一条分隔线；留一点缝，它才像「贴着底部但没用额度」。
        base_y = r.bottom() - 2.5

        def py(pct: float) -> float:
            h = (r.height() - 4.5) * min(1.0, max(0.0, pct / ymax))
            return base_y - h

        pts = [(px(ms), py(pct)) for ms, pct in series]

        # 面积：顶端浓、底端透明，毛玻璃上不糊
        area = QtGui.QPainterPath(QtCore.QPointF(pts[0][0], base_y))
        for x, y in pts:
            area.lineTo(x, y)
        area.lineTo(pts[-1][0], base_y)
        area.closeSubpath()
        g = QtGui.QLinearGradient(0, r.top(), 0, base_y)
        c = QtGui.QColor(accent)
        c.setAlphaF(0.30 * a)
        g.setColorAt(0.0, c)
        c2 = QtGui.QColor(accent)
        c2.setAlphaF(0.02 * a)
        g.setColorAt(1.0, c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawPath(area)

        # 线
        line = QtGui.QPainterPath(QtCore.QPointF(*pts[0]))
        for x, y in pts[1:]:
            line.lineTo(x, y)
        pen = QtGui.QPen(QtGui.QColor(accent), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        col = QtGui.QColor(accent)
        col.setAlphaF(0.92 * a)
        pen.setColor(col)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.strokePath(line, pen)

        # 末点：实心点 + 一圈淡光晕，标出「这就是此刻」
        lx, ly = pts[-1]
        halo = QtGui.QColor(accent)
        halo.setAlphaF(0.16 * a)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QtCore.QPointF(lx, ly), 5.5, 5.5)
        dot = QtGui.QColor(accent)
        dot.setAlphaF(0.95 * a)
        p.setBrush(dot)
        p.drawEllipse(QtCore.QPointF(lx, ly), 2.6, 2.6)

        # 刻度：默认左上角（曲线从 0 爬起，那里永远是空的）；万一开头就很高，
        # 挪到右上角避开，两个角都占着就不画 —— 宁可少一条注释，不叠字。
        p.setFont(self.f_scale)
        p.setPen(theme.text3(0.55 * a))
        cut = t0 + span * (34.0 / max(1.0, r.width()))
        head_high = any(pct > ymax * 0.55 for ms, pct in series if ms <= cut)
        tail_high = any(pct > ymax * 0.55 for ms, pct in series if ms >= t1 - span * (34.0 / max(1.0, r.width())))
        align = Qt.AlignmentFlag.AlignLeft
        if head_high and not tail_high:
            align = Qt.AlignmentFlag.AlignRight
        elif head_high and tail_high:
            return
        p.drawText(QtCore.QRectF(r.left(), r.top() - 2, r.width(), 12),
                   align | Qt.AlignmentFlag.AlignTop, f"0–{ymax:g}%")

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

        # 列：标题（可省略）| 上下文占用 | 本会话流速 | 今日 token | 最后活跃
        w_time, w_tok, w_rate, gap = 44.0, 54.0, 48.0, 8.0
        x_ctx = inner_r - w_time - gap - w_tok - gap - w_rate - gap - CTX_W
        x_rate = x_ctx + CTX_W + gap
        name_w = x_ctx - gap - inner_l
        for i, (name, tok, rate, last, ctx) in enumerate(self._sessions[:MAX_ROWS]):
            ry = y + i * ROW_H
            p.setFont(self.f_name)
            p.setPen(theme.text(0.92 * a))
            elided = self._fm_name.elidedText(name, QtCore.Qt.TextElideMode.ElideRight, int(name_w))
            p.drawText(QtCore.QRectF(inner_l, ry, name_w, ROW_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
            # 上下文占用：横条 + 百分比。没有权威值（库里没这一行）就整列留空 ——
            # 用最后一次调用的 token 反推会在自动压缩后失真，宁可不显示。
            if ctx is not None:
                self._paint_ctx(p, x_ctx, ry, ctx, a)
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

    def _paint_ctx(self, p: QtGui.QPainter, x: float, ry: float, pct: float, a: float) -> None:
        """上下文进度：细条 + 百分比。≥80% 转琥珀色 —— 再聊几轮就要触发自动压缩了。"""
        pct = max(0.0, min(100.0, float(pct)))
        hot = pct >= CTX_WARN
        col = theme.warn() if hot else theme.accent
        by = ry + (ROW_H - CTX_BAR_H) / 2.0

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.track())
        p.drawRoundedRect(QtCore.QRectF(x, by, CTX_BAR_W, CTX_BAR_H), CTX_BAR_H / 2, CTX_BAR_H / 2)
        fill_w = CTX_BAR_W * pct / 100.0
        if fill_w > 0:      # 极小值也留一个圆点，否则「用过」和「未知」看起来一样
            fill_w = max(CTX_BAR_H, fill_w)
            p.setBrush(col)
            p.drawRoundedRect(QtCore.QRectF(x, by, fill_w, CTX_BAR_H), CTX_BAR_H / 2, CTX_BAR_H / 2)

        p.setFont(self.f_time)
        p.setPen(theme.warn(a) if hot else theme.text3(a))
        # 千分之几的占用四舍五入成 0% 会让人以为「没用过」，写成 <1% 才准确
        pct_txt = f"{pct:.0f}%" if pct >= 0.5 else ("<1%" if pct > 0 else "0%")
        p.drawText(QtCore.QRectF(x + CTX_BAR_W + CTX_GAP, ry, CTX_TEXT_W, ROW_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, pct_txt)

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


# ================================================================ 数据整形 / 小工具
def _ctx_pct(item: dict) -> float | None:
    """{"used": 67500, "size": 300000} → 22.5。缺字段或窗口为 0 返回 None（不给假数）。"""
    c = item.get("ctx") or {}
    try:
        used, size = float(c.get("used") or 0), float(c.get("size") or 0)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    return max(0.0, min(100.0, used / size * 100.0))


def _parse_quota(raw) -> list[dict]:
    """把 summary 的 quota 规整成绘制用的结构；没有可画点的模型整条丢掉。"""
    out: list[dict] = []
    for q in (raw or []):
        if not isinstance(q, dict):
            continue
        series = []
        for pt in (q.get("series") or []):
            try:
                series.append((float(pt[0]), float(pt[1])))
            except (TypeError, ValueError, IndexError):
                continue
        if not series:
            continue
        try:
            reset = int(q.get("resetAt") or 0)
        except (TypeError, ValueError):
            reset = 0
        out.append({"model": str(q.get("model") or "?"),
                    "percent": float(q.get("percent") or series[-1][1]),
                    "resetAt": reset,
                    "series": series})
    return out


def _clock(ms: float) -> str:
    return time.strftime("%H:%M", time.localtime(ms / 1000.0))


def _start_text(ms: float) -> str:
    """窗口起点：同一天只给 HH:MM，跨天补日期（「23:18 起」可能是昨天，必须说清）。"""
    t = time.localtime(ms / 1000.0)
    if t[:3] == time.localtime()[:3]:
        return time.strftime("%H:%M 起", t)
    return time.strftime("%m-%d %H:%M 起", t)


def _reset_text(reset_at: int) -> str:
    """重置时刻：同一天只给 HH:MM，跨天补上日期（否则「02:52 重置」会被读成今天）。"""
    if not reset_at:
        return "重置时间未知"
    t = time.localtime(reset_at)
    today = time.localtime()[:3]
    if t[:3] == today:
        return time.strftime("%H:%M 重置", t)
    return time.strftime("%m-%d %H:%M 重置", t)


def _y_scale(peak: float) -> float:
    """曲线纵轴上限：5 / 10 / 20 / 25 / 50 / 100 六档，留 12% 顶部余量。"""
    for step in (5.0, 10.0, 20.0, 25.0, 50.0, 100.0):
        if peak * 1.12 <= step:
            return step
    return 100.0
