# -*- coding: utf-8 -*-
"""B13 探针：上下文占用（session_usage）与额度曲线（quota）的口径回归。

不依赖 pytest，直接 `python island_qt/_probe_b13.py`。全部数据走临时目录 / 临时
sqlite，不碰真实 ~/.workbuddy，也不写任何文件到仓库外。
"""
import datetime as dt
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import scanlib  # noqa: E402
from scan_service import QUOTA_SERIES_MAX, Tracker, _downsample  # noqa: E402
from content.detail import (  # noqa: E402
    QUOTA_H, _ctx_pct, _parse_quota, _reset_text, _start_text, _y_scale, DetailPage,
)

OK = 0


def check(cond, msg):
    global OK
    assert cond, "FAIL: " + msg
    OK += 1


def make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, custom_title TEXT, deleted_at INTEGER)")
    con.execute("CREATE TABLE session_usage (session_id TEXT PRIMARY KEY, used INTEGER NOT NULL,"
                " size INTEGER NOT NULL, updated_at INTEGER NOT NULL, credit_json TEXT)")
    con.executemany("INSERT INTO sessions VALUES (?,?,?)",
                    [("s1", "会话一", None), ("s2", None, None), ("s3", "已删", 123)])
    con.executemany("INSERT INTO session_usage VALUES (?,?,?,?,?)",
                    [("s1", 67500, 300000, 0, None),
                     ("s2", 299000, 300000, 0, None),
                     ("s3", 5, 0, 0, None),        # size=0 → 丢弃（除零/0% 都不该出现）
                     ("s4", -3, 1000, 0, None)])   # 负数 → 夹到 0
    con.commit()
    con.close()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="wb_b13_"))
    db = tmp / "workbuddy.db"
    make_db(db)

    # ---------- 1. session_context ----------
    ctx = scanlib.session_context(db)
    check(ctx.get("s1") == (67500, 300000), "读到 used/size")
    check("s3" not in ctx, "size=0 的行被丢弃")
    check(ctx.get("s4") == (0, 1000), "负 used 夹到 0")
    check(scanlib.session_context(tmp / "nope.db") == {}, "库不存在→空表，不抛")
    check(scanlib.custom_titles(db) == {"s1": "会话一"}, "custom_titles 仍按 deleted_at 过滤")

    # ---------- 2. _ctx_pct ----------
    check(abs(_ctx_pct({"ctx": {"used": 67500, "size": 300000}}) - 22.5) < 1e-9, "22.5%")
    check(_ctx_pct({"ctx": None}) is None, "无 ctx → None")
    check(_ctx_pct({"ctx": {"used": 1, "size": 0}}) is None, "size=0 → None（不给假数）")
    check(_ctx_pct({"ctx": {"used": 400000, "size": 300000}}) == 100.0, "超出窗口夹到 100")
    check(_ctx_pct({"ctx": {"used": "x", "size": 10}}) is None, "脏字段 → None")

    # ---------- 3. 配额分桶：窗口乱序不改结论 ----------
    now = time.time()
    t = Tracker(tmp / "projects")
    m = dt.datetime.fromtimestamp(now - 3600)
    old_reset, cur_reset = int(now - 3000), int(now + 7200)

    def add(reset, pct, moment):
        t._add_quota({"model": "hy4", "percent": pct, "resetAt": str(reset)}, moment)

    add(cur_reset, 1, m)                       # 新窗口先到
    add(old_reset, 40, m - dt.timedelta(hours=1))
    add(old_reset, 99, m - dt.timedelta(minutes=30))   # 旧窗口后到，且数字更大
    add(cur_reset, 7, m + dt.timedelta(minutes=1))
    q = t.quota_list()
    check(len(q) == 1 and q[0]["model"] == "hy4", "一个模型一条曲线")
    check(q[0]["percent"] == 7.0, "取采样最新的窗口(7%)，不被旧窗口的 99% 顶掉")
    check(len(t.quota["hy4"]) == 2, "两个窗口各自分桶，互不清空")

    # 过期窗口不展示
    t2 = Tracker(tmp / "projects")
    t2._add_quota({"model": "glm", "percent": 99, "resetAt": str(int(now - 600))}, m)
    check(t2.quota_list() == [], "窗口已结束的旧账不画（宁缺勿骗）")

    # 缺 reset_at 的窗口不会过期、也不会被丢掉
    t3 = Tracker(tmp / "projects")
    t3._add_quota({"model": "glm", "percent": 5, "resetAt": ""}, m)
    q3 = t3.quota_list()
    check(len(q3) == 1 and q3[0]["resetAt"] == 0, "无 reset_at 也保留，交给 UI 标『未知』")

    # ---------- 4. 曲线抽稀 ----------
    pts = [(i * 1000.0, float(i)) for i in range(1000)]
    ds = _downsample(pts, QUOTA_SERIES_MAX)
    check(len(ds) == QUOTA_SERIES_MAX, "抽稀到上限点数")
    check(ds[-1] == pts[-1], "末点必须保留（它就是当前已用）")
    check(ds[0] == pts[0], "首点保留（窗口起点）")
    check(_downsample(pts[:5], QUOTA_SERIES_MAX) == pts[:5], "点少时原样返回")

    # ---------- 5. summary 契约 ----------
    proj = tmp / "projects" / "demo"
    proj.mkdir(parents=True)
    line = {
        "type": "assistant", "sessionId": "s1", "cwd": str(proj),
        "timestamp": int(now * 1000) - 1000,
        "message": {"usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
        "providerData": {"model": "hy4", "rawUsage": {"credit": 1.5,
                          "quota": {"model": "hy4", "percent": 42, "reset_at": str(cur_reset)}}},
    }
    import json
    (proj / "s1.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")

    old_db_env = os.environ.get("WORKBUDDY_DB_PATH")
    os.environ["WORKBUDDY_DB_PATH"] = str(db)
    try:
        t4 = Tracker(tmp / "projects")
        t4.scan_once()
        s = t4.summary()
        check("quota" in s and "ctx" in s["active"][0], "summary 带 quota 与每会话 ctx")
        check(s["active"][0]["ctx"] == {"used": 67500, "size": 300000}, "上下文取库里的权威值")
        check(s["quota"][0]["percent"] == 42.0, "曲线末点 = 最后一次采样的百分比")
        check(isinstance(s["quota"][0]["series"][0], list), "series 是 JSON 友好的 list")
    finally:
        if old_db_env is None:
            os.environ.pop("WORKBUDDY_DB_PATH", None)
        else:
            os.environ["WORKBUDDY_DB_PATH"] = old_db_env

    # ---------- 6. 渲染层整形 ----------
    pq = _parse_quota([{"model": "a", "percent": 3, "resetAt": "123", "series": [[1, 0], [2, 3]]},
                       {"model": "b", "series": []},          # 没有点 → 丢掉
                       {"model": "c", "series": [[1, "x"]]},  # 脏点 → 丢掉
                       "junk"])
    check(len(pq) == 1 and pq[0]["model"] == "a" and pq[0]["resetAt"] == 123, "配额整形过滤空/脏项")
    check(_y_scale(0) == 5.0 and _y_scale(3) == 5.0, "极小值给 5% 刻度")
    check(_y_scale(26) == 50.0 and _y_scale(93) == 100.0, "26%→50，93%→100")
    check(_y_scale(100) == 100.0, "满格仍是 100")
    check(_reset_text(0) == "重置时间未知", "无重置时间给明确文案")
    check("重置" in _reset_text(int(now) + 3600), "有 reset 就写重置")
    check(_start_text(now * 1000).endswith("起"), "起点标签以『起』结尾")

    # ---------- 7. 高度自适应 ----------
    d = DetailPage(640)
    h0 = d.preferred_height()
    d.set_summary({"today": {}, "active": [], "quota": []})
    check(d.preferred_height() == h0, "没有配额数据 → 不留空壳")
    d.set_summary({"today": {}, "active": [],
                   "quota": [{"model": "a", "percent": 3, "resetAt": int(now) + 99,
                              "series": [[1, 0], [2, 3]]}]})
    check(d.preferred_height() == h0 + QUOTA_H + 10.0, "有配额 → 高度加卡片高 + 间距")
    check(d.set_summary({"today": {}, "active": [], "quota": []}) is True, "数据变化要重绘")
    check(d.set_summary({"today": {}, "active": [], "quota": []}) is False, "数据不变不重绘")

    print("B13 ALL PASS (%d checks)" % OK)


if __name__ == "__main__":
    main()
