# -*- coding: utf-8 -*-
"""scanlib.py — WorkBuddy 会话 jsonl 的共享解析内核。

为什么存在
    WBtool 有两处消费同一批 jsonl：报表（wb_usage_app.py）和灵动岛
    （island_qt/scan_service.py）。此前各写一套解析，口径靠注释「严格对齐」维持。
    本模块把「读文件 / 判时间戳单位 / 抽可展示字段」收敛成唯一实现，两边共用。

设计约束
    1. 纯标准库、零第三方依赖（PyInstaller 不会因此多打东西）
    2. 只读：永不修改、移动或写入任何日志文件
    3. 只提取可展示的统计字段，不保留正文内容

口径（与 island/src/scanner.js 严格对齐；改动请同步两边）
    - 时间戳：>1e11 视为毫秒，否则秒；本地时间，与 HTML 报告一致
    - Token：usage 经 norm_usage 拆出 input/output/total
    - 积分：providerData.rawUsage.credit（LLM 调用行）+ type=="credit-usage" 事件
    - 会话名：优先 SQLite sessions.custom_title（用户在界面里改过的名字），
      取不到回落 jsonl 的 aiTitle（AI 自动生成的原始标题），再回落 cwd / "会话"
    - 进行中：最后活动在 ACTIVE_WINDOW_MIN 分钟内
    - 上下文占用：SQLite session_usage 的 used / size（客户端写的权威值）
    - 额度：jsonl 行内 providerData.rawUsage.quota = {model, percent, reset_at}，
      percent 是该窗口**已用**百分比，reset_at 是下次重置的 unix 秒
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple

# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
ACTIVE_WINDOW_MIN = 5           # 分钟内有活动算「进行中」
# 流速统计窗口。窗口要短，否则一次爆发会被摊平后在屏幕上挂满整分钟，
# 看不出「此刻生成快不快」。15s 是实测下来既能立刻反映生成、又不会因
# 工具调用停顿而频繁跳到 0 的折中值。
RATE_WINDOW_MS = 15_000
MS_THRESHOLD = 1e11             # 大于此值视为毫秒时间戳
UNKNOWN_DAY = "unknown"         # 取不到时间戳的桶名
IMAGE_TYPES = ("image_blob_ref", "input_image", "image")


def default_projects_dir() -> Path:
    """会话日志根目录：WORKBUDDY_PROJECTS_DIR 优先，否则 ~/.workbuddy/projects。"""
    env = os.environ.get("WORKBUDDY_PROJECTS_DIR")
    return Path(env) if env else Path.home() / ".workbuddy" / "projects"


def default_db_path() -> Path:
    """会话元数据库：WORKBUDDY_DB_PATH 优先，否则 ~/.workbuddy/workbuddy.db。"""
    env = os.environ.get("WORKBUDDY_DB_PATH")
    return Path(env) if env else Path.home() / ".workbuddy" / "workbuddy.db"


def _open_ro(db_path=None):
    """只读打开 workbuddy.db，返回 connection（调用方负责 close）。不可用则抛异常。"""
    from urllib.parse import quote
    import sqlite3
    path = Path(db_path) if db_path else default_db_path()
    uri = "file:" + quote(str(path), safe="/:") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=0.5)


def session_context(db_path=None) -> Dict[str, Tuple[int, int]]:
    """读 {sessionId: (已用 token, 上下文窗口大小)}——每个会话的上下文占用。

    这是「上下文还剩多少」的唯一权威来源：WorkBuddy 每次调用后把
    `used / size` 写进 workbuddy.db 的 `session_usage` 表，包含了系统提示、
    工具结果与历史轮次的实际占用。jsonl 只能靠「最后一次调用的 input+output」
    反推，遇到自动压缩、会话分叉、缓存命中口径差异都会失真，所以只作数据源缺口
    时的备选（本函数不提供，调用方自行决定要不要退）。

    只读打开、读不到就返回空表，绝不让统计因客户端升级或库被占用而挂掉。
    size <= 0 的行直接丢弃：那是「窗口未知」，拿它算百分比会除零或得出 0%。
    """
    try:
        con = _open_ro(db_path)
        try:
            rows = con.execute(
                "SELECT session_id, used, size FROM session_usage WHERE size > 0"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return {}
    out: Dict[str, Tuple[int, int]] = {}
    for sid, used, size in rows:
        if isinstance(sid, str) and isinstance(used, int) and isinstance(size, int) and size > 0:
            out[sid] = (max(0, used), size)
    return out


def custom_titles(db_path=None) -> Dict[str, str]:
    """读 {sessionId: 用户改过的会话名}；读不到就返回空表，绝不抛错。

    为什么单独读 SQLite：WorkBuddy 改名只写 workbuddy.db 的 sessions 表，
    jsonl 里的 ai-title 事件是 AI 首次生成时写死的、改名时不会更新。报表和
    灵动岛要显示用户看到的界面名，必须以库里的 custom_title 为准。

    只读打开（URI mode=ro），不创建、不修改、不加锁升级；库被 WorkBuddy
    占用或表结构变化时静默回落到 aiTitle，不让用量统计因改名功能挂掉。
    """
    path = Path(db_path) if db_path else default_db_path()
    try:
        con = _open_ro(path)
        try:
            rows = con.execute(
                "SELECT id, custom_title FROM sessions "
                "WHERE deleted_at IS NULL AND custom_title IS NOT NULL AND custom_title != ''"
            ).fetchall()
        finally:
            con.close()
        return {sid: title for sid, title in rows
                if isinstance(sid, str) and isinstance(title, str) and title}
    except Exception:
        return {}


# ----------------------------------------------------------------------------
# 字段归一
# ----------------------------------------------------------------------------
def num(v):
    """把非数值统一成 0。bool 是 int 的子类，这里必须排除，否则 True 会变成 1。"""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def bump(counter: dict, key, amount=1) -> None:
    if key is None:
        return
    counter[key] = counter.get(key, 0) + amount


def norm_usage(u) -> Optional[dict]:
    """把各行五花八门的 usage 字段规整成 {input, output, total, cache}。

    兼容两套命名（snake_case / camelCase），total 缺失时用 input+output 兜底，
    cache 优先取 cache_read_input_tokens，取不到再从 inputTokensDetails 累加。
    """
    if not isinstance(u, dict):
        return None
    inp = u.get("input_tokens", u.get("inputTokens", 0)) or 0
    out = u.get("output_tokens", u.get("outputTokens", 0)) or 0
    tot = u.get("total_tokens", u.get("totalTokens", 0)) or 0
    cache = u.get("cache_read_input_tokens", 0)
    if not cache:
        det = u.get("inputTokensDetails") or u.get("input_tokens_details") or []
        if isinstance(det, list):
            cache = sum(d.get("cached_tokens", 0) or 0 for d in det if isinstance(d, dict))
    if tot == 0 and (inp or out):
        tot = inp + out
    return {"input": inp, "output": out, "total": tot, "cache": cache or 0}


def count_image_blocks(o: dict) -> int:
    """只统计浅层 content 列表里的图片类型标记，不读取任何图片/文本数据。"""
    n = 0
    for key in ("content", "rawContent"):
        v = o.get(key)
        if isinstance(v, list):
            for b in v:
                if isinstance(b, dict) and b.get("type") in IMAGE_TYPES:
                    n += 1
    msg = o.get("message")
    if isinstance(msg, dict):
        v = msg.get("content")
        if isinstance(v, list):
            for b in v:
                if isinstance(b, dict) and b.get("type") in IMAGE_TYPES:
                    n += 1
    return n


# ----------------------------------------------------------------------------
# 时间戳
# ----------------------------------------------------------------------------
def to_moment(ts, mtime_ms=None) -> Optional[dt.datetime]:
    """把 timestamp 字段转成本地 datetime。

    mtime_ms：行内没有可用时间戳时是否回落到文件修改时间。
        报表传文件 mtime（沿用历史行为，让缺时间戳的行也归到当天）；
        灵动岛传 None（与 scanner.js 一致，这类行归入 unknown）。
    """
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        ts = mtime_ms
    if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(ts / 1000 if ts > MS_THRESHOLD else ts)
    except (OSError, ValueError, OverflowError):
        return None


def day_of(moment: Optional[dt.datetime]) -> str:
    return moment.strftime("%Y-%m-%d") if moment else UNKNOWN_DAY


def clock_of(moment: Optional[dt.datetime]) -> str:
    return moment.strftime("%H:%M") if moment else "--:--"


def downsample_pts(pts: List[tuple], n: int) -> List[tuple]:
    """把 (时间, 已用%) 序列等距抽稀到 n 个点，末点必须保留。

    报表与灵动岛共用（此前只写在 scan_service 里）：抽稀而不是分桶平均——
    配额曲线单调上升，平均会把台阶抹圆，末点也会被拉低，让「已用 93%」
    和曲线终点对不上，看起来像两个数据源。
    """
    m = len(pts)
    if m <= n:
        return list(pts)
    out = [pts[int(i * (m - 1) / (n - 1))] for i in range(n)]
    out[-1] = pts[-1]
    return out


def short_proj(path: str) -> str:
    """项目路径脱敏：去盘符、剥离用户主目录前缀、只留末 3 段。

    供快照落盘前使用——避免把 `c:\\Users\\<name>\\...` 这类完整绝对路径
    （含 Windows 用户名）写进长期留存的快照文件。分隔符用 `/`（无空格），
    与报告前端 prettyProj() 的 split 口径一致，保证二次处理幂等。
    """
    if not isinstance(path, str) or not path:
        return ""
    import re
    a = re.sub(r"^[a-zA-Z]:[\\/]", "", path).replace("\\", "/").split("/")
    a = [x for x in a if x]
    # 剥离 `Users/<name>/` 或 `home/<name>/` 前缀，连用户名一起去掉
    if len(a) >= 2 and a[0].lower() in ("users", "home", "用户"):
        a = a[2:]
    elif len(a) >= 1 and a[0].startswith("~"):
        a = a[1:]
    return "/".join(a[-3:] if len(a) > 3 else a)


# ----------------------------------------------------------------------------
# 逐行读取
# ----------------------------------------------------------------------------
class Row(NamedTuple):
    """一行 jsonl 的读取结果。data 为 None 表示该行无法解析（已被跳过）。"""
    data: Optional[dict]
    moment: Optional[dt.datetime]
    day: str


class Line(NamedTuple):
    """一行 jsonl 的可展示语义（不含正文）。

    报表与灵动岛都从这里取字段，口径不可能再分叉。
    """
    typ: str
    sid: str
    cwd: str
    proj: str
    pd: dict
    title: str
    msg: dict
    nu: Optional[dict]
    credit: float
    original: float
    thinking: float
    miss: float
    hit: float
    model: str
    quota: Optional[dict]


def iter_jsonl(path, *, mtime_ms=None) -> Iterator[Row]:
    """全量逐行读取一个 jsonl 文件。

    空行不产出；解析失败或非 dict 的行产出一个 data=None 的 Row，
    让调用方自行决定「计数但不统计」（报表需要总行数，灵动岛直接丢弃）。
    """
    try:
        fh = open(path, "r", encoding="utf-8", errors="ignore")
    except OSError:
        return
    with fh:
        for raw in fh:
            text = raw.strip()
            if not text:
                continue
            try:
                o = json.loads(text)
            except json.JSONDecodeError:
                yield Row(None, None, UNKNOWN_DAY)
                continue
            if not isinstance(o, dict):
                yield Row(None, None, UNKNOWN_DAY)
                continue
            moment = to_moment(o.get("timestamp"), mtime_ms)
            yield Row(o, moment, day_of(moment))


def to_line(row: Row, fallback_proj: str = "", titles: Optional[Dict[str, str]] = None) -> Line:
    """从 Row 抽出两边都要用的字段。row.data 必须非空。

    titles 是 custom_titles() 的结果：sid 命中则用用户改过的界面名，
    否则回落到 aiTitle。不传时行为与旧版完全一致（便于探针/单测）。"""
    o = row.data or {}
    pd = o.get("providerData") if isinstance(o.get("providerData"), dict) else {}
    typ = o.get("type") if isinstance(o.get("type"), str) else UNKNOWN_DAY
    sid = o.get("sessionId") if isinstance(o.get("sessionId"), str) else ""
    cwd = o.get("cwd") if isinstance(o.get("cwd"), str) else ""
    msg = o.get("message") if isinstance(o.get("message"), dict) else {}
    usage = msg.get("usage") or pd.get("usage")
    nu = norm_usage(usage)
    ru = pd.get("rawUsage") if isinstance(pd.get("rawUsage"), dict) else {}

    credit = float(num(ru.get("credit")))
    original = float(num(ru.get("original_credit")))
    thinking = num(ru.get("completion_thinking_tokens"))
    if not thinking:
        det = ru.get("completion_tokens_details")
        if isinstance(det, dict):
            thinking = num(det.get("reasoning_tokens"))
    miss = num(ru.get("prompt_cache_miss_tokens"))
    hit = num(ru.get("prompt_cache_hit_tokens")) or (nu["cache"] if nu else 0)

    q = ru.get("quota")
    quota = None
    if isinstance(q, dict) and isinstance(q.get("model"), str):
        quota = {
            "model": q["model"],
            "percent": num(q.get("percent")),
            "resetAt": q.get("reset_at") if isinstance(q.get("reset_at"), str) else "",
        }

    name = (titles or {}).get(sid) or (o.get("aiTitle") if isinstance(o.get("aiTitle"), str) else "")
    return Line(
        typ=typ,
        sid=sid,
        cwd=cwd,
        proj=cwd or fallback_proj,
        pd=pd,
        title=name,
        msg=msg,
        nu=nu,
        credit=credit,
        original=original,
        thinking=thinking,
        miss=miss,
        hit=hit,
        model=pd.get("model") if isinstance(pd.get("model"), str) else "unknown",
        quota=quota,
    )


class IncrementalReader:
    """按字节偏移增量读取 jsonl，只解析新出现的完整行。

    行为与 scanner.js 的 _scanFile 一致：
      - 文件长于已读偏移 → 只读新增字节
      - 文件短于已读偏移（被重写/截断）→ 重置该文件并按全量重读，同时回报 truncated
      - 末尾没有换行的残行留在缓冲里，等下次补齐再解析（不会误解析半行 JSON）
    """

    def __init__(self) -> None:
        self._state: Dict[str, dict] = {}   # path -> {"offset": int, "buf": bytes}

    def reset(self) -> None:
        self._state.clear()

    def read(self, path, *, mtime_ms=None) -> Tuple[List[Row], bool]:
        """返回 (新解析出的行, 是否发生截断重写)。"""
        try:
            size = os.path.getsize(path)
        except OSError:
            return [], False

        st = self._state.get(path)
        if st is None:
            st = {"offset": 0, "buf": b""}
            self._state[path] = st
        if size < st["offset"]:
            # 文件被重写：丢掉旧状态，从零开始，并让上层清空自己的聚合
            st["offset"] = 0
            st["buf"] = b""
            rows = self._read_chunk(path, st, size, mtime_ms)
            return rows, True
        if size == st["offset"]:
            return [], False
        return self._read_chunk(path, st, size, mtime_ms), False

    def _read_chunk(self, path, st: dict, size: int, mtime_ms) -> List[Row]:
        try:
            with open(path, "rb") as fh:
                fh.seek(st["offset"])
                raw = fh.read(size - st["offset"])
        except OSError:
            return []

        # 关键：offset 永远推进到文件末尾。末尾残行留在 buf 里等下次补全，
        # 不从 offset 回退重读——回退会让残行在下次扫描时被重复解析。
        st["offset"] = size
        nl = raw.rfind(b"\n")
        if nl == -1:
            st["buf"] = st["buf"] + raw
            return []

        complete = st["buf"] + raw[: nl + 1]
        st["buf"] = raw[nl + 1:]

        rows: List[Row] = []
        for text in complete.decode("utf-8", "ignore").split("\n"):
            text = text.strip()
            if not text:
                continue
            try:
                o = json.loads(text)
            except json.JSONDecodeError:
                rows.append(Row(None, None, UNKNOWN_DAY))
                continue
            if not isinstance(o, dict):
                rows.append(Row(None, None, UNKNOWN_DAY))
                continue
            moment = to_moment(o.get("timestamp"), mtime_ms)
            rows.append(Row(o, moment, day_of(moment)))
        return rows
