# -*- coding: utf-8 -*-
"""island_qt/scan_service.py — 灵动岛的扫描服务（Python 版）。

契约严格对齐 island/src/scanner.js 的 summary()，渲染层可无缝换源：
    {
      "today":  {"token": 0, "credit": 0, "in": 0, "out": 0, "ratePerSec": 0},
      "active": [{"name": "会话标题", "tokens": 0, "last": "HH:MM", "rate": 0.0,
                  "ctx": {"used": 0, "size": 0} | null}],
      "quota":  [{"model": "hy4", "percent": 93, "resetAt": 1794747829,
                  "series": [[毫秒, 已用百分比], ...]}],
      "files":  0,
      "updated": "HH:MM:SS"
    }

`active[].rate` 是该会话**自己的**生成速度（tok/s），2026-11-18 新增：总值只能回答
「现在整体多快」，展开态里 5 个会话同时在跑时，看不出是谁在产出、谁只是挂着。
口径与 `today.ratePerSec` 完全一致（同一个窗口、同样只算 output），只是按 sid 分桶。

`active[].ctx`（2026-11-28 新增）是该会话的上下文占用，读 `workbuddy.db` 的
`session_usage.used/size`。有了它才能回答「这个会话还能聊多久 / 是不是该开新会话」——
token 总量只说明今天用了多少，跟「当前这轮还剩多少余量」是两件事。

`quota[]`（2026-11-28 新增）是模型配额的消耗曲线：每行 LLM 调用都带
`rawUsage.quota = {model, percent, reset_at}`，percent 是该配额窗口的**已用**百分比。
按 reset_at 分窗（窗口一换就把旧点丢掉，曲线只讲当前这一窗），summary 里降采样到
QUOTA_SERIES_MAX 个点交给渲染层画面积折线。

两层结构：
    Tracker   纯 Python，无 Qt 依赖——可单独 import、可 CLI 跑、可单测
    ScanWorker QThread 封装，每 10 秒调一次 Tracker.scan_once()，发 summaryReady

增量：IncrementalReader 按字节偏移只读新增行；文件被重写时自动全量重算。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

try:                                    # CLI 与单测不依赖 Qt
    from PySide6 import QtCore
    _HAS_QT = True
except ImportError:                     # pragma: no cover
    QtCore = None                       # type: ignore[assignment]
    _HAS_QT = False

from scanlib import (
    ACTIVE_WINDOW_MIN,
    RATE_WINDOW_MS,
    IncrementalReader,
    clock_of,
    custom_titles,
    day_of,
    default_projects_dir,
    downsample_pts,
    session_context,
    to_line,
)

# 与 v1.3.0 的 SCAN_MS=10000 对齐：流速是「最近 15 秒滚动窗口」（RATE_WINDOW_MS），
# 10 秒一刷才会活地跳动。代价很低——IncrementalReader 按文件记已读偏移，稳态每轮只读新增字节
# （首轮全量约 1.7s）。
SCAN_INTERVAL_SEC = 10

# 配额曲线交给渲染层前降采样到这个点数。实测一个 24h 窗口能有 1400+ 条样本，
# 直接画既拖慢重绘也没意义（面板宽 580px，一个像素放不下两条线）。
QUOTA_SERIES_MAX = 160
# 单模型样本上限（内存护栏）。按毫秒排序后只留最近这么多条，跨天也不会无限涨。
QUOTA_POINTS_MAX = 1500
# 单模型最多保留几个配额窗口（同一个模型会残留历史窗口的采样）。
QUOTA_WINDOWS_MAX = 4


def _now_ms() -> float:
    return time.time() * 1000


class Tracker:
    """增量聚合器。字段语义与 scanner.js 的 Scanner 一一对应。"""

    def __init__(self, root=None) -> None:
        self.root = Path(root) if root else default_projects_dir()
        self.reader = IncrementalReader()
        self.titles: Dict[str, str] = {}            # sid -> 用户改过的界面名（每轮刷新）
        self.totals: Dict[str, dict] = {}          # day -> {t, cr, in, out}
        self.session_tokens: Dict[str, dict] = {}  # sid -> {day: tokens}
        self.active: Dict[str, dict] = {}          # sid -> {last, title, proj}
        self.files: set = set()
        self.start_time = _now_ms()                # 用于流速：只统计启动后的用量
        self.boot_tokens = 0
        self.flow: List[tuple] = []                # [(事件毫秒, 本次新增 output token)]
        # sid -> [(事件毫秒, output)]，与 flow 同一套事件，只是按会话分桶。
        # 只服务展开态的「每会话流速」，不参与任何落盘；会话转出 active 即整条丢弃。
        self.session_flow: Dict[str, List[tuple]] = {}
        # sid -> (used, size)：上下文占用，每轮从 workbuddy.db 重读（权威值）
        self.ctx: Dict[str, tuple] = {}
        # model -> {reset_at: [(毫秒, 已用百分比)]}。按窗口分桶而不是只留一份：
        # 扫描顺序不等于时间顺序，旧会话文件后扫到会把「当前窗口」冲掉（见 _add_quota）。
        self.quota: Dict[str, Dict[int, List[tuple]]] = {}
        self._recomputing = False

    # -- 扫描 ---------------------------------------------------------------
    def scan_once(self) -> "Tracker":
        now = dt.datetime.now()
        # 每轮重读用户改过的会话名：改名是低频操作，但改完希望下一轮（≤10s）就生效。
        # 只读 SQLite 约 10~30ms，相对首轮扫描 1.7s / 稳态增量可忽略。
        self.titles = custom_titles()
        # 上下文占用同理：客户端每轮对话后更新，跟着 10s 的节拍走，展开态才不会看到过时的百分比。
        self.ctx = session_context()
        if self.root.is_dir():
            self._walk(str(self.root), now)
        cutoff = now - dt.timedelta(minutes=ACTIVE_WINDOW_MIN)
        for sid in [k for k, v in self.active.items() if v["last"] < cutoff]:
            del self.active[sid]
            # 会话已经不在「进行中」列表里，它的流速桶也一并丢掉（否则每轮累积成泄漏）
            self.session_flow.pop(sid, None)
        self._trim_flows(_now_ms())
        return self

    def _trim_flows(self, now_ms: float) -> None:
        """裁掉两倍窗口以外的旧事件。

        `rate_per_sec` / `session_rate` 里也各有一道懒裁剪，但那只覆盖「被查询到」的桶；
        长跑时旧会话会一直留在字典里，所以每轮扫描再统一收一次。
        """
        lo = now_ms - 2 * RATE_WINDOW_MS
        if self.flow and self.flow[0][0] < lo:
            self.flow = [e for e in self.flow if e[0] >= lo]
        for sid, evts in list(self.session_flow.items()):
            if not evts or evts[-1][0] < lo:
                self.session_flow.pop(sid, None)
            elif evts[0][0] < lo:
                self.session_flow[sid] = [e for e in evts if e[0] >= lo]

    def _walk(self, path: str, now: dt.datetime) -> None:
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for e in entries:
            try:
                # 不跟随符号链接/junction：日志目录里出现自引用会无限递归
                if e.is_dir(follow_symlinks=False):
                    self._walk(e.path, now)
                elif e.name.endswith(".jsonl"):
                    self._scan_file(e.path, now)
            except OSError:
                continue

    def _scan_file(self, path: str, now: dt.datetime) -> None:
        self.files.add(path)
        rows, truncated = self.reader.read(path)
        if truncated:
            self._recompute(now)
            return
        fallback_proj = os.path.basename(os.path.dirname(path))
        for row in rows:
            if row.data is None:
                continue
            self._process(row, fallback_proj, now)

    def _recompute(self, now: dt.datetime) -> None:
        """文件被重写/截断：清空所有聚合从头再扫（对齐 scanner.js 的 _recomputeAll）。"""
        if self._recomputing:       # 防止极端情况下递归自激
            return
        self._recomputing = True
        try:
            self.totals.clear()
            self.session_tokens.clear()
            self.active.clear()
            self.files.clear()
            self.boot_tokens = 0
            self.flow.clear()
            self.session_flow.clear()
            self.quota.clear()          # 全量重扫会把配额点再走一遍，不清会重复
            self.reader.reset()
            self._walk(str(self.root), now)
        finally:
            self._recomputing = False

    def _process(self, row, fallback_proj: str, now: dt.datetime) -> None:
        ln = to_line(row, fallback_proj, self.titles)
        moment, day = row.moment, row.day

        # 生成工具的独立积分事件（图片生成等）
        if ln.typ == "credit-usage":
            amt = ln.pd.get("credit")
            if isinstance(amt, (int, float)) and not isinstance(amt, bool):
                self._add_day(day, 0, 0, 0, float(amt), ln.sid)

        if ln.quota and moment:
            self._add_quota(ln.quota, moment)

        nu = ln.nu
        if nu:
            self._add_day(day, nu["input"], nu["output"], nu["total"], ln.credit, ln.sid)
            if moment:
                ms = moment.timestamp() * 1000
                if ms >= self.start_time:
                    self.boot_tokens += nu["total"]
                    # 流速只记 output：total 里 99%+ 是 prompt（且多为 cache 命中），
                    # 那是「读进去」的量，不是模型「写出来」的速度。
                    self.flow.append((ms, nu["output"]))
                    if ln.sid:
                        self.session_flow.setdefault(ln.sid, []).append((ms, nu["output"]))

        if ln.sid:
            s = self.active.get(ln.sid)
            if s is None:
                s = {"last": moment or now, "title": "", "proj": ""}
                self.active[ln.sid] = s
            if moment and s["last"] < moment:
                s["last"] = moment
            if ln.title:
                s["title"] = ln.title
            if ln.cwd and not s["proj"]:
                s["proj"] = ln.cwd

    def _add_quota(self, q: dict, moment: dt.datetime) -> None:
        """记一条配额采样点，按 (模型, 窗口) 分桶。

        为什么要按 reset_at 分桶、而不是「换个 reset 就清空」：扫描顺序不等于时间顺序。
        同一个模型常常一会儿读到上周的旧会话文件、一会儿读到今天的新文件，后写的会
        把先写的整段清掉，「当前窗口」会随机变成某个旧窗口。分桶之后各存各的，
        出 summary 时再挑「采样时间最新」的那一桶。

        窗口语义（实测）：`reset_at` 是**本窗口的结束时刻**，窗口长 24h，percent 从 0
        爬到 100 后重置 —— 所以 reset_at 已经过去的那一桶是过期数据，不能再当成
        「现在已用多少」展示（见 `quota_list`）。
        """
        model = q.get("model") or ""
        if not model:
            return
        try:
            reset = int(float(q.get("resetAt") or 0))
        except (TypeError, ValueError):
            reset = 0
        pct = float(q.get("percent") or 0)
        ms = moment.timestamp() * 1000

        per_model = self.quota.setdefault(model, {})
        pts = per_model.setdefault(reset, [])
        pts.append((ms, pct))
        if len(pts) > QUOTA_POINTS_MAX:
            del pts[:-QUOTA_POINTS_MAX]
        if len(per_model) > QUOTA_WINDOWS_MAX:      # 只留采样最新的几个窗口，防内存缓慢涨
            keep = sorted(per_model, key=lambda r: per_model[r][-1][0], reverse=True)
            for r in keep[QUOTA_WINDOWS_MAX:]:
                per_model.pop(r, None)

    def _add_day(self, day: str, in_t, out_t, tokens, credit, sid: str) -> None:
        td = self.totals.setdefault(day, {"t": 0, "cr": 0.0, "in": 0, "out": 0})
        td["t"] += tokens
        td["cr"] += credit
        td["in"] += in_t
        td["out"] += out_t
        if sid:
            st = self.session_tokens.setdefault(sid, {})
            st[day] = st.get(day, 0) + tokens

    # -- 查询 ---------------------------------------------------------------
    def today(self) -> dict:
        return self.totals.get(day_of(dt.datetime.now()), {"t": 0, "cr": 0.0, "in": 0, "out": 0})

    def active_list(self, now_ms: Optional[float] = None) -> List[dict]:
        d = day_of(dt.datetime.now())
        now = _now_ms() if now_ms is None else now_ms
        out = []
        for sid, v in self.active.items():
            tok = (self.session_tokens.get(sid) or {}).get(d, 0)
            c = self.ctx.get(sid)
            out.append({
                "name": v["title"] or v["proj"] or "会话",
                "last": v["last"],
                "tokens": tok,
                "rate": self.session_rate(sid, now),
                "ctx": {"used": c[0], "size": c[1]} if c else None,
            })
        out.sort(key=lambda a: a["last"], reverse=True)
        return out

    def rate_per_sec(self, now_ms: Optional[float] = None) -> float:
        """生成速度（tok/s）：最近 RATE_WINDOW_MS 内产出的 output token 除以窗口秒数。

        口径对齐 DeepSeek / ChatGPT / Claude 客户端的 tok/s —— 只算模型生成的
        token，不含 prompt。若把 total 也算进来，agent 每轮工具调用重放整个上下文
        都会计入，数字会比真实生成速度高两个数量级。

        用事件自身时间戳判断窗口归属，比「扫描时刻」更贴近真实消耗时点。
        """
        now = _now_ms() if now_ms is None else now_ms
        cutoff = now - RATE_WINDOW_MS
        if self.flow and self.flow[0][0] < cutoff - RATE_WINDOW_MS:
            self.flow = [e for e in self.flow if e[0] >= cutoff - RATE_WINDOW_MS]
        total = sum(e[1] for e in self.flow if e[0] >= cutoff)
        return total / (RATE_WINDOW_MS / 1000)

    def session_rate(self, sid: str, now_ms: Optional[float] = None) -> float:
        """单个会话的生成速度（tok/s）。窗口、口径、事件时间戳判定都与 `rate_per_sec` 相同。

        与总量流速的关系是「分桶」，不是「平均」：几个会话同时产出时，各行的和约等于总流速
        （差在 `flow` 还包含 sid 为空的用量行——这类行没会话可归，只进总量）。
        """
        evts = self.session_flow.get(sid)
        if not evts:
            return 0.0
        now = _now_ms() if now_ms is None else now_ms
        cutoff = now - RATE_WINDOW_MS
        if evts[0][0] < cutoff - RATE_WINDOW_MS:
            evts = [e for e in evts if e[0] >= cutoff - RATE_WINDOW_MS]
            self.session_flow[sid] = evts
        total = sum(e[1] for e in evts if e[0] >= cutoff)
        return total / (RATE_WINDOW_MS / 1000)

    def quota_list(self) -> List[dict]:
        """每个模型一条「当前窗口」的配额曲线，按「已用最多」优先排序。

        取窗口的规则：同一模型可能有多个窗口（历史会话文件还在盘上），取**采样时间
        最新**的那一桶；若这一桶的 reset_at 已经过去，说明窗口已重置、里面的百分比
        是上一窗的旧账，整条丢掉（宁可不画，也不画一条骗人的 99%）。

        排序理由：面板只画一条主曲线，该画最该被看见的那条 —— 快用完的模型。
        """
        now_s = time.time()
        out = []
        for model, windows in self.quota.items():
            if not windows:
                continue
            reset = max(windows, key=lambda r: windows[r][-1][0])
            pts = sorted(windows[reset])
            if not pts:
                continue
            if reset and reset <= now_s - 120:      # 窗口已结束（留 2 分钟时钟容差）
                continue
            series = _downsample(pts, QUOTA_SERIES_MAX)
            out.append({
                "model": model,
                "percent": series[-1][1],
                "resetAt": reset,
                "series": [[ms, pct] for ms, pct in series],
            })
        out.sort(key=lambda a: (-a["percent"], -a["series"][-1][0]))
        return out

    def summary(self) -> dict:
        t = self.today()
        now = _now_ms()                 # 同一帧里所有流速用同一个「现在」，避免各算各的
        return {
            "today": {
                "token": t["t"],
                "credit": t["cr"],
                "in": t["in"],
                "out": t["out"],
                "ratePerSec": self.rate_per_sec(now),
            },
            "active": [
                {"name": a["name"], "tokens": a["tokens"], "last": clock_of(a["last"]),
                 "rate": a["rate"], "ctx": a["ctx"]}
                for a in self.active_list(now)
            ],
            "quota": self.quota_list(),
            "files": len(self.files),
            "updated": dt.datetime.now().strftime("%H:%M:%S"),
        }


def _downsample(pts: List[tuple], n: int) -> List[tuple]:
    """等距抽稀到 n 个点，末尾点必须保留（它就是「当前已用」）。

    实现在 scanlib.downsample_pts（报表侧也调它），这里保留同名薄壳是为了
    探针与外部调用方（_probe_b13）的 import 不变。
    """
    return downsample_pts(pts, n)


if _HAS_QT:
    class ScanWorker(QtCore.QThread):      # type: ignore[misc]
        """后台扫描线程：立即扫一次，之后每 interval 秒一次，结果用信号送回主线程。"""

        summaryReady = QtCore.Signal(dict)
        failed = QtCore.Signal(str)

        def __init__(self, root=None, interval_sec: int = SCAN_INTERVAL_SEC, parent=None):
            super().__init__(parent)
            self.tracker = Tracker(root)
            self.interval_sec = max(5, int(interval_sec))
            self._stop_evt = threading.Event()

        def run(self) -> None:            # noqa: D102
            while not self._stop_evt.is_set():
                try:
                    self.tracker.scan_once()
                    self.summaryReady.emit(self.tracker.summary())
                except Exception as exc:  # 单次扫描失败不该拖死线程
                    self.failed.emit(f"{type(exc).__name__}: {exc}")
                self._stop_evt.wait(self.interval_sec)

        def stop(self) -> None:
            self._stop_evt.set()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--once" in argv:
        t = Tracker()
        t0 = time.time()
        t.scan_once()
        data = t.summary()
        data["_scanMs"] = round((time.time() - t0) * 1000, 1)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print("用法: python -m island_qt.scan_service --once", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
