# -*- coding: utf-8 -*-
"""B12 探针：每日快照持久化（save/load/merge）的正确性与隐私回归。

不依赖 pytest，直接 `python island_qt/_probe_b12.py`。全部断言走本地临时目录，
不碰真实 ~/.wbtool 快照，也不碰真实 WorkBuddy 日志。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wb_usage_app as w

OK = 0


def check(cond, msg):
    global OK
    assert cond, "FAIL: " + msg
    OK += 1


def mkrec(day, model, proj, i, o, cr):
    # 忠实模拟真实 collect_all：一条 record = 一次调用，无 n 字段。
    return {"d": day, "h": 9, "m": model, "p": proj, "s": "sid-secret-xyz",
            "i": i, "o": o, "t": i + o, "c": 0, "cm": 0, "ch": 0, "th": 0,
            "cr": cr, "oc": 0}


def daily_blob(i):
    return {"tools": {"Read": i}, "types": {"assistant": i}, "status": {},
            "hours": {"9": i}, "images": 0, "reasoning": 0, "snapshots": 0,
            "genCredit": 0.0, "genEvents": 0, "lines": i}


def main():
    # 用独立 HOME + 独立 projects 目录，彻底隔离真实数据
    tmp = tempfile.mkdtemp(prefix="wb_b12_")
    home = Path(tmp) / "home"
    proj = Path(tmp) / "projects"
    home.mkdir(); proj.mkdir(parents=True)
    old_home, old_projects = w.HOME, w.PROJECTS_DIR
    w.HOME, w.PROJECTS_DIR = home, proj
    try:
        sdir = w.snapshot_dir()
        check(str(home) in str(sdir), "快照目录在隔离 HOME 下")

        # --- 场景1: 首日扫描 → 存快照 ---
        # 11-01: hy3/projA 三条(=3次)，glm/projA 一条；11-02: hy3/projB 两条
        # 三条 hy3 各带 i=100 是刻意的：存快照会把它们相加成 300，注入时还原成一条 i=300/n=3
        data = {"records": [mkrec("2026-11-01", "hy3", "projA", 100, 50, 1.5),
                            mkrec("2026-11-01", "hy3", "projA", 100, 50, 1.5),
                            mkrec("2026-11-01", "hy3", "projA", 100, 50, 1.5),
                            mkrec("2026-11-01", "glm", "projA", 20, 10, 0.5),
                            mkrec("2026-11-02", "hy3", "projB", 200, 80, 2.0),
                            mkrec("2026-11-02", "hy3", "projB", 200, 80, 2.0)],
                "daily": {"2026-11-01": daily_blob(4), "2026-11-02": daily_blob(2)}}
        check(w.save_snapshot(data) is True, "save 成功")
        snap_file = sdir / w.SNAPSHOT_NAME
        check(snap_file.exists(), "快照文件已生成")
        check(snap_file.stat().st_size < 100_000, "快照为 KB 级")

        raw = snap_file.read_text(encoding="utf-8")
        check("sid-secret-xyz" not in raw, "隐私: 不含会话 ID")
        check("projA" in raw and "hy3" in raw, "快照含模型/项目统计")

        loaded = w.load_snapshot()
        check(set(loaded["days"]) == {"2026-11-01", "2026-11-02"}, "load 天数正确")

        # --- 场景2: 日志被清理（只剩 11-03）→ merge 补回历史 ---
        fresh = {"records": [mkrec("2026-11-03", "hy3", "projA", 10, 5, 0.3)],
                 "daily": {"2026-11-03": daily_blob(1)}}
        info = w.merge_snapshot(fresh)
        check(info["injected_days"] == 2, "补回 2 个历史天")
        check(info["injected_records"] == 6, "补回调用次数=各组合 n 之和(3+1+2)")
        days = {r["d"] for r in fresh["records"]}
        check(days == {"2026-11-01", "2026-11-02", "2026-11-03"}, "三天齐全")
        check("2026-11-01" in fresh["daily"] and "2026-11-02" in fresh["daily"],
              "daily 行为统计也补回")

        # 注入记录：三条 hy3 合并成一条 i=300，n=3（不是被复制成三条 i=300）
        inj = [r for r in fresh["records"] if r["d"] == "2026-11-01" and r["m"] == "hy3"][0]
        check(inj["i"] == 300 and inj["o"] == 150 and inj["cr"] == 4.5, "注入 token=三条之和,未被重复放大")
        check(inj.get("n") == 3, "注入记录携带调用次数 n=3")
        check(inj["s"] == "", "注入记录会话 ID 留空")

        # --- 场景3: 幂等——再 merge 一次不再注入（历史已在 fresh 里）---
        info2 = w.merge_snapshot(fresh)
        check(info2["injected_days"] == 0, "重复 merge 不注入（幂等）")

        # --- 场景4: save 只写本次真实天，不把注入天回写放大 ---
        w.save_snapshot(fresh)
        raw2 = json.loads(snap_file.read_text(encoding="utf-8"))
        check(set(raw2["days"]) == {"2026-11-01", "2026-11-02", "2026-11-03"}, "save 后仍是 3 天")
        day1 = raw2["days"]["2026-11-01"]["rows"]
        k = "hy3\x1fprojA"
        check(day1[k]["i"] == 300 and day1[k]["n"] == 3, "回写未放大 token/n")

        # --- 场景5: 异常路径静默 ---
        snap_file.write_text("{bad json", encoding="utf-8")
        check(w.load_snapshot() == {"days": {}}, "损坏快照→空")
        snap_file.write_text(json.dumps({"version": 99, "days": {"x": {}}}), encoding="utf-8")
        check(w.load_snapshot() == {"days": {}}, "版本不符→空")
        snap_file.unlink()
        check(w.load_snapshot() == {"days": {}}, "快照缺失→空")

        # --- 场景6: 不同 projects_dir 隔离 ---
        proj2 = Path(tmp) / "projects2"
        proj2.mkdir()
        check(w.snapshot_dir(proj) != w.snapshot_dir(proj2), "不同数据源快照目录不同")

        # --- 场景7: addTo 的 n 权重（模拟前端逻辑）---
        b = {k: 0 for k in w._SNAP_NUM_KEYS} | {"n": 0}
        for r in [inj]:
            for k in w._SNAP_NUM_KEYS:
                b[k] += r.get(k, 0)
            b["n"] += (r.get("n") or 1)
        check(b["i"] == 300 and b["n"] == 3, "前端 addTo 的 n 权重语义正确")

        # 真实 record（无 n 字段）必须仍按 1 次计，保证 addTo 改动零影响
        real = mkrec("2026-11-05", "hy3", "projX", 7, 3, 0.2)  # 无 n
        b2 = {"n": 0}
        b2["n"] += (real.get("n") or 1)
        check(b2["n"] == 1, "真实 record 无 n 字段→仍计 1 次")

        # --- 场景8: 合并式 save——部分清理后旧历史天不被抹掉 ---
        base = {"records": [mkrec("2026-12-01", "hy3", "p", 10, 5, 1),
                            mkrec("2026-12-02", "hy3", "p", 20, 10, 2)],
                "daily": {"2026-12-01": daily_blob(1), "2026-12-02": daily_blob(1)}}
        w.save_snapshot(base)
        # 再来一次只含 12-02 的扫描（模拟 12-01 日志被清）
        partial = {"records": [mkrec("2026-12-02", "hy3", "p", 20, 10, 2)],
                   "daily": {"2026-12-02": daily_blob(1)}}
        w.save_snapshot(partial)
        kept = w.load_snapshot()["days"]
        check("2026-12-01" in kept, "合并式 save 保留未被覆盖的历史天")
        check(kept["2026-12-02"]["rows"]["hy3\x1fp"]["i"] == 20, "同名天以本次为准重算,不叠加")

        # 空数据 save 不抹快照
        w.save_snapshot({"records": [], "daily": {}})
        check(set(w.load_snapshot()["days"]) == {"2026-12-01", "2026-12-02"}, "空扫描不覆盖快照")

        # --- 场景9: 隐私——绝对路径/用户名不得落盘（独立数据源，不干扰上面）---
        proj_p = Path(tmp) / "privacy_proj"
        proj_p.mkdir()
        absrec = {"d": "2026-12-10", "m": "hy3", "p": r"c:\Users\lenovo\Downloads\私密项目",
                  "i": 5, "o": 2, "t": 7, "c": 0, "cm": 0, "ch": 0, "th": 0, "cr": 0.1, "oc": 0}
        w.save_snapshot({"records": [absrec], "daily": {}}, proj_p)
        obj_p = json.loads((w.snapshot_dir(proj_p) / w.SNAPSHOT_NAME).read_text(encoding="utf-8"))
        stored_key = list(obj_p["days"]["2026-12-10"]["rows"].keys())[0]
        # 只检查存下来的项目段（不含 updatedAt 的时间冒号，那是合法字段）
        proj_seg = stored_key.split("\x1f", 1)[1]
        check(":" not in proj_seg and "lenovo" not in proj_seg.lower() and "Users" not in proj_seg,
              "隐私: 项目段不含盘符/用户名/Users 路径段")
        check("私密项目" in proj_seg, "脱敏后仍保留项目末段(分布可用)")

        print("B12 ALL PASS (%d checks)" % OK)
    finally:
        w.HOME, w.PROJECTS_DIR = old_home, old_projects


if __name__ == "__main__":
    main()
