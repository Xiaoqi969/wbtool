# -*- coding: utf-8 -*-
"""B14 探针：报表侧「模型额度曲线」的口径回归。

不依赖 pytest，直接 `python island_qt/_probe_b14.py`。全部数据走临时目录，不读真实
~/.workbuddy，也不落盘（快照注入那段不走 build_report，避免往用户目录写东西）。

覆盖点（对应 v3.2.0 新增的 add_quota_point / quota_series / 报告模板）：
    1. 分桶乱序：同一模型跨窗口的采样后扫到，不会冲掉当前窗口
    2. 每模型只出一条曲线，且取「采样最新」的窗口
    3. reset_at 已过 → expired，且排序排在进行中的窗口之后
    4. 抽稀 ≤ QUOTA_SERIES_MAX，末点必须保留（曲线终点要等于「已用 %」）
    5. 单窗口采样上限、脏数据（无 model / 空 reset / 时间戳缺失）
    6. 模板里旧 quotaBox 已移除、新面板齐全
"""
import datetime as dt
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

import wb_usage_app as A  # noqa: E402

OK = 0


def check(cond, msg):
    global OK
    assert cond, "FAIL: " + msg
    OK += 1


def line(ts_ms, model, pct, reset, sid="s1", proj="C:\\Users\\x\\demo"):
    return json.dumps({
        "type": "assistant", "timestamp": ts_ms, "sessionId": sid, "cwd": proj,
        "aiTitle": "演示会话",
        "providerData": {
            "model": model,
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "rawUsage": {"quota": {"model": model, "percent": pct, "reset_at": str(reset)}},
        },
    }, ensure_ascii=False)


def main():
    now = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="wb_b14_"))
    try:
        # ---------- 1. 分桶 + 乱序 ----------
        buckets = {}
        t0 = (now - 7200) * 1000
        A.add_quota_point(buckets, {"model": "m1", "percent": 5, "resetAt": str(int(now) + 3600)},
                          dt.datetime.fromtimestamp(now - 7000))
        A.add_quota_point(buckets, {"model": "m1", "percent": 9, "resetAt": str(int(now) + 3600)},
                          dt.datetime.fromtimestamp(now - 6000))
        # 旧窗口的点在「后扫到」的位置出现：不能覆盖上面的新窗口
        A.add_quota_point(buckets, {"model": "m1", "percent": 99, "resetAt": str(int(now) - 86400)},
                          dt.datetime.fromtimestamp(now - 90000))
        check(len(buckets) == 2, "同一模型两个窗口 → 两个桶")
        out = A.quota_series(buckets, now_ts=now)
        check(len(out) == 1, "每个模型只输出一条曲线")
        check(out[0]["percent"] == 9, "取采样最新的窗口（不是后扫到的旧窗口）")
        check(out[0]["expired"] is False, "reset 在未来 → 未过期")

        # ---------- 2. 过期窗口标记与排序 ----------
        b2 = {}
        A.add_quota_point(b2, {"model": "old", "percent": 100, "resetAt": str(int(now) - 3600)},
                          dt.datetime.fromtimestamp(now - 90000))
        A.add_quota_point(b2, {"model": "new", "percent": 30, "resetAt": str(int(now) + 3600)},
                          dt.datetime.fromtimestamp(now - 600))
        o2 = A.quota_series(b2, now_ts=now)
        check([x["model"] for x in o2] == ["new", "old"], "进行中的窗口排在过期窗口之前")
        check(o2[1]["expired"] is True, "reset 已过 → expired=True")

        # ---------- 3. 抽稀：末点保留 ----------
        b3 = {}
        base = now - 3600
        for i in range(1000):
            A.add_quota_point(b3, {"model": "m3", "percent": i / 10.0, "resetAt": str(int(now) + 60)},
                              dt.datetime.fromtimestamp(base + i * 3))
        s3 = A.quota_series(b3, now_ts=now)[0]
        check(len(s3["series"]) <= A.QUOTA_SERIES_MAX, "曲线点数不超过 QUOTA_SERIES_MAX")
        check(len(s3["series"]) == A.QUOTA_SERIES_MAX, "采样足够多时抽稀到上限")
        check(s3["series"][-1][1] == s3["percent"], "末点百分比 == 展示的已用 %")
        last_raw = sorted(b3[("m3", int(now) + 60)], key=lambda p: p[0])[-1]
        check(tuple(s3["series"][-1]) == last_raw, "末点就是最后一条真实采样（不是平均出来的）")
        times = [p[0] for p in s3["series"]]
        check(times == sorted(times), "曲线按时间升序（多文件交错扫描后仍有序）")
        check(s3["points"] == 1000, "原始采样数一并回传，用于说明密度")

        # ---------- 4. 脏数据 ----------
        b4 = {}
        A.add_quota_point(b4, {"model": "", "percent": 50, "resetAt": "1"}, dt.datetime.now())
        A.add_quota_point(b4, {"model": "m4", "percent": 50, "resetAt": ""}, dt.datetime.now())
        A.add_quota_point(b4, {"model": "m4", "percent": 50, "resetAt": "abc"}, dt.datetime.now())
        check(("", 1) not in b4, "空模型名被丢弃")
        check(("m4", 0) in b4, "reset_at 非法 → 归到 reset=0 的桶，不抛异常")
        check(A.quota_series({}, now_ts=now) == [], "空输入 → 空输出")
        b5 = {}
        A.add_quota_point(b5, {"model": "m5", "percent": 1, "resetAt": "1"}, None)
        check(b5 == {}, "时间戳缺失的小行不进桶（不拿 mtime 冒充采样时刻）")

        # ---------- 5. 单窗口采样上限 ----------
        b6 = {}
        for i in range(A.QUOTA_POINTS_MAX + 200):
            A.add_quota_point(b6, {"model": "m6", "percent": i % 100, "resetAt": "1"},
                              dt.datetime.fromtimestamp(now - 10000 + i * 0.1))
        check(len(b6[("m6", 1)]) == A.QUOTA_POINTS_MAX, "单窗口采样数被夹在上限内")
        check(A.quota_series(b6, now_ts=now)[0]["percent"] ==
              b6[("m6", 1)][-1][1], "夹断后仍以最后一条采样为准")

        # ---------- 6. 端到端：合成 jsonl → collect_all ----------
        proj = tmp / "projects" / "demo"
        proj.mkdir(parents=True)
        rows = [line(int((now - 3600 + i * 60) * 1000), "hy4-flash", i, int(now) + 7200)
                for i in range(0, 60, 5)]
        rows.append(line(int((now - 60) * 1000), "hy4-flash", 40, int(now) + 7200, sid="s2"))
        (proj / "a.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        data = A.collect_all(tmp / "projects")
        q = data["quota"]
        check(len(q) == 1, "端到端：一个模型一条曲线")
        check(q[0]["model"] == "hy4-flash" and q[0]["percent"] == 40, "端到端：取最新采样值")
        check(q[0]["resetAt"] == int(now) + 7200, "端到端：reset_at 解析为秒级整数")
        check(len(q[0]["series"]) == q[0]["points"], "端到端：点数未超上限时原样保留")
        check(all(isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))
                  for p in q[0]["series"]), "曲线点只有两个数字（不含任何文本）")
        check(data["totalLines"] >= 13, "端到端：日志行数正常计入")

        # ---------- 7. 模板 ----------
        tpl = A.HTML_TEMPLATE
        check('id="quotaCards"' in tpl, "模板含额度卡容器")
        check("function quotaChart" in tpl and "function renderQuota" in tpl, "模板含绘图与渲染函数")
        check("quotaBox" not in tpl, "旧的「最近一次」chip 容器已移除")
        check("renderQuota()" in tpl, "renderQuota 已接入 renderAll")
        check('"expired"' not in tpl.split("const DATA")[0], "过期标记只在数据里，不写死在模板")

        html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False)) \
                  .replace("__ALIAS__", json.dumps(A.MODEL_ALIAS, ensure_ascii=False))
        check('"quota"' in html and "hy4-flash" in html, "DATA.quota 已内联进报告")
        check("__DATA__" not in html and "__ALIAS__" not in html, "占位符全部替换")

        print(f"B14 OK: {OK} 项断言全部通过")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
