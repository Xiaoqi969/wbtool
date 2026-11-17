# -*- coding: utf-8 -*-
"""island_qt/scan_service.py — 灵动岛的扫描服务（Python 版）。

契约严格对齐 island/src/scanner.js 的 summary()，渲染层可无缝换源：
    {
      "today":  {"token": 0, "credit": 0, "in": 0, "out": 0, "ratePerSec": 0},
      "active": [{"name": "会话标题", "tokens": 0, "last": "HH:MM", "rate": 0.0}],
      "files":  0,
      "updated": "HH:MM:SS"
    }

`active[].rate` 是该会话**自己的**生成速度（tok/s），2026-11-18 新增：总值只能回答
「现在整体多快」，展开态里 5 个会话同时在跑时，看不出是谁在产出、谁只是挂着。
口径与 `today.ratePerSec` 完全一致（同一个窗口、同样只算 output），只是按 sid 分桶。

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
    day_of,
    default_projects_dir,
    to_line,
)

# 与 v1.3.0 的 SCAN_MS=10000 对齐：流速是「最近 15 秒滚动窗口」（RATE_WINDOW_MS），
# 10 秒一刷才会活地跳动。代价很低——IncrementalReader 按文件记已读偏移，稳态每轮只读新增字节
# （首轮全量约 1.7s）。
SCAN_INTERVAL_SEC = 10


def _now_ms() -> float:
    return time.time() * 1000


class Tracker:
    """增量聚合器。字段语义与 scanner.js 的 Scanner 一一对应。"""

    def __init__(self, root=None) -> None:
        self.root = Path(root) if root else default_projects_dir()
        self.reader = IncrementalReader()
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
        self._recomputing = False

    # -- 扫描 ---------------------------------------------------------------
    def scan_once(self) -> "Tracker":
        now = dt.datetime.now()
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
            self.reader.reset()
            self._walk(str(self.root), now)
        finally:
            self._recomputing = False

    def _process(self, row, fallback_proj: str, now: dt.datetime) -> None:
        ln = to_line(row, fallback_proj)
        moment, day = row.moment, row.day

        # 生成工具的独立积分事件（图片生成等）
        if ln.typ == "credit-usage":
            amt = ln.pd.get("credit")
            if isinstance(amt, (int, float)) and not isinstance(amt, bool):
                self._add_day(day, 0, 0, 0, float(amt), ln.sid)

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
            out.append({
                "name": v["title"] or v["proj"] or "会话",
                "last": v["last"],
                "tokens": tok,
                "rate": self.session_rate(sid, now),
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
                 "rate": a["rate"]}
                for a in self.active_list(now)
            ],
            "files": len(self.files),
            "updated": dt.datetime.now().strftime("%H:%M:%S"),
        }


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
