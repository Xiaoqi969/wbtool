# -*- coding: utf-8 -*-
"""island_qt/prefs.py — 位置与置顶的跨启动记忆。

文件与键**完全沿用 Electron 版**：`%APPDATA%/WBtool-island/island-prefs.json`，
内容 `{"x": 本体左上角全局逻辑 x, "y": ..., "pinned": bool}`。

为什么坐标语义能直接复用：Electron 版的窗口就是胶囊本体本身（`setBounds` 不带容器），
所以它存的 x/y 本来就是「本体左上角」。Qt 版为了容纳展开态 + 阴影用了 900×680 的固定
容器，只要存/取时都换算成本体坐标，同一个文件就能继续用 —— 用户从旧版切过来，
胶囊还在他上次拖到的那个位置，不用重拖。

写入用「临时文件 + os.replace」原子替换：强杀或掉电时不会留下半截 JSON，
否则下次启动读不出位置，胶囊会莫名其妙跳回屏幕中央。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PINNED = True


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "WBtool-island"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prefs_path() -> Path:
    return data_dir() / "island-prefs.json"


def load_prefs() -> dict:
    try:
        raw = prefs_path().read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(**patch) -> None:
    """读-改-写整份 JSON：只动传入的键，其余原样保留（旧版写进来的别的键也不丢）。"""
    data = load_prefs()
    data.update(patch)
    target = prefs_path()
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def saved_body_pos() -> tuple[float, float] | None:
    """上次拖到的本体左上角（全局逻辑像素）；没存过或数据不合法返回 None。"""
    p = load_prefs()
    x, y = p.get("x"), p.get("y")
    if isinstance(x, bool) or isinstance(y, bool):
        return None
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return float(x), float(y)
    return None
