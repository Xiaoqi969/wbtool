#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B11 探针：会话名以 SQLite custom_title 为准，回落 aiTitle，异常不崩。

不依赖 Qt / 第三方库；用临时目录造 SQLite 与 jsonl，跑完即删。
用法：python island_qt/_probe_b11.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scanlib import custom_titles, to_line  # noqa: E402

FAIL = []


def ck(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("  " + detail if detail else ""))
    if not cond:
        FAIL.append(name)


def make_db(path, rows):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE sessions (id TEXT, custom_title TEXT, deleted_at INTEGER)")
    for sid, title, deleted in rows:
        con.execute("INSERT INTO sessions VALUES (?,?,?)", (sid, title, deleted))
    con.commit()
    con.close()


def fake_row(sid, ai_title):
    """造一个最小 Row：只需 data 字段。"""
    from scanlib import Row
    return Row({"sessionId": sid, "aiTitle": ai_title, "type": "ai-title"}, None, "unknown")


def main():
    with tempfile.TemporaryDirectory(prefix="B11_") as td:
        tmp = Path(td)
        db = tmp / "workbuddy.db"

        print("=== A. custom_titles 读取与过滤 ===")
        make_db(db, [
            ("s1", "用户改的名", None),      # 有效
            ("s2", "", None),                # 空串要过滤
            ("s3", "已删会话名", 123),       # 软删除要过滤
            ("s4", None, None),              # NULL 要过滤
        ])
        t = custom_titles(db)
        ck("只读到 s1", t == {"s1": "用户改的名"}, repr(t))

        print("=== B. 映射覆盖 aiTitle / 回落 ===")
        ck("命中用新名", to_line(fake_row("s1", "AI原名"), "", t).title == "用户改的名")
        ck("未命中回落 aiTitle", to_line(fake_row("sX", "AI原名"), "", t).title == "AI原名")
        ck("空映射回落 aiTitle", to_line(fake_row("s1", "AI原名"), "", {}).title == "AI原名")
        ck("不传 titles 行为不变", to_line(fake_row("s1", "AI原名")).title == "AI原名")
        ck("都为空则空串", to_line(fake_row("sX", ""), "", t).title == "")

        print("=== C. 异常路径不崩 ===")
        ck("库不存在返回空表", custom_titles(tmp / "none.db") == {})
        bad = tmp / "bad.db"
        bad.write_text("not a sqlite db", encoding="utf-8")
        ck("坏库返回空表", custom_titles(bad) == {})
        nocol = tmp / "nocol.db"
        con = sqlite3.connect(str(nocol))
        con.execute("CREATE TABLE other (x TEXT)")
        con.commit()
        con.close()
        ck("缺表返回空表", custom_titles(nocol) == {})

        print("=== D. 只读属性：不写库、不改 mtime ===")
        before = db.stat().st_mtime_ns
        for _ in range(3):
            custom_titles(db)
        ck("多次读取不改 mtime", db.stat().st_mtime_ns == before)

    print()
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
