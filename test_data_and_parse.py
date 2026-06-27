# -*- coding: utf-8 -*-
"""データ保存層とコース解析の検査（ネット/API不使用・ファイルモード）。"""
import sys
import io
import os
import tempfile
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PASS, FAIL, BUGS = 0, 0, []


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        BUGS.append(msg)
        print("  [FAIL]", msg)


# ---- data_manager をファイルモードに強制 ----
import data_manager as dm
dm._db_url = lambda: None
dm._gsheets_conf = lambda: None
dm.DATA_DIR = tempfile.mkdtemp()
dm._FILES = {k: os.path.join(dm.DATA_DIR, f"{k}.json")
             for k in ("courses", "rounds", "prefs")}
dm._cache.clear()

print("== data_manager ==")
check(dm._backend() == "file", "ファイルモードに切替")
check(dm.load_courses() == [] and dm.load_rounds() == [], "初期は空")

# コース 追加/上書き/削除
dm.save_course({"name": "A CC", "pars": [4] * 18, "total_par": 72, "holes": 18})
r = dm.save_course({"name": "A CC", "pars": [4] * 18, "total_par": 70, "holes": 18})
check(r["replaced"] is True, "同名は上書き")
check(len(dm.load_courses()) == 1 and dm.load_courses()[0]["total_par"] == 70,
      "上書きで内容更新・件数1")
dm.save_course({"name": "B CC", "pars": [4] * 18, "total_par": 72, "holes": 18})
dm.delete_course("A CC")
check([c["name"] for c in dm.load_courses()] == ["B CC"], "削除OK")

# ラウンド 追加(id採番)/更新/削除
r1 = dm.save_round({"date": "2026-01-01", "course_name": "B CC", "pars": [4] * 18,
                    "num_holes": 18, "players": [{"name": "私", "scores": [4] * 18}]})
r2 = dm.save_round({"date": "2026-01-02", "course_name": "B CC", "pars": [4] * 18,
                    "num_holes": 18, "players": [{"name": "私", "scores": [5] * 18}]})
check(r1["id"] == 1 and r2["id"] == 2, "id採番 1,2")
dm.update_round(1, olympic={"私": [1] * 18})
check(dm.load_rounds()[0].get("olympic") == {"私": [1] * 18}, "update_round 反映")
dm.delete_round(1)
ids = [r["id"] for r in dm.load_rounds()]
check(ids == [2], "delete_round 後 id=2のみ")
# 削除後に追加 -> id重複しない（max+1）
r3 = dm.save_round({"date": "2026-01-03", "course_name": "B CC", "pars": [4] * 18,
                    "num_holes": 18, "players": [{"name": "私", "scores": [4] * 18}]})
check(r3["id"] == 3, "削除後の採番は max+1=3（重複なし）")

# 集計ヘルパー
check(dm.get_all_player_names() == ["私"], "プレーヤー名一覧")
avgs = dm.get_hole_averages("私")
check(len(avgs) == 18 and avgs[0]["avg_score"] in (4, 4.5, 5), "ホール平均 算出")

# prefs
dm.update_prefs(my_name="私", last_tee="Regular")
check(dm.load_prefs().get("my_name") == "私", "prefs 保存")

# ---- course_search 解析 ----
from course_search import (_parse_hole_table, _course_name_from_label,
                           _build_course, extract_cid)
print("== course_search ==")

check(_course_name_from_label("東コースOUT") == "東コース", "ラベル->コース名(東)")
check(_course_name_from_label("西コースIN") == "西コース", "ラベル->コース名(西)")
check(extract_cid("https://x/guide/layout_disp/c_id/240014/") == "240014",
      "URLからc_id")
check(extract_cid("110015") == "110015", "数字そのまま")

# 表（HOLE/PAR/各ティー/HDCP + 計列）を解析
df = pd.DataFrame([
    ["HOLE", "1", "2", "3", "4", "5", "6", "7", "8", "9", "計"],
    ["PAR", "4", "4", "3", "5", "4", "5", "4", "3", "4", "36"],
    ["Back", "400", "390", "180", "520", "410", "500", "420", "160", "430", "3410"],
    ["Regular", "380", "370", "160", "500", "390", "480", "400", "150", "410", "3240"],
    ["HDCP", "9", "3", "7", "15", "1", "13", "17", "5", "11", "-"],
])
holes = _parse_hole_table(df)
check(len(holes) == 9, "9ホール抽出")
check(holes[0]["par"] == 4 and holes[0]["hdcp"] == 9, "H1 par/hdcp")
check(holes[0]["yards"]["Back"] == 400 and holes[0]["yards"]["Regular"] == 380,
      "H1 ティー別ヤード")
check(holes[3]["par"] == 5 and holes[3]["hdcp"] == 15, "H4 par/hdcp")
# 計列(36, 3410)を誤ってホールに含めない
check(all(h["hole"] <= 9 for h in holes), "計列をホールに含めない")

# build_course 重複ホール除去
hd = [{"hole": 1, "par": 4}, {"hole": 1, "par": 5}, {"hole": 2, "par": 3}]
bc = _build_course("東", hd)
check(bc["hole_count"] == 2 and bc["total_par"] == 7, "重複ホール除去")

# par/hdcp 異常値の除外
df_bad = pd.DataFrame([
    ["HOLE", "1", "2", "計"],
    ["PAR", "4", "9", "13"],  # par9は範囲外->除外
])
hb = _parse_hole_table(df_bad)
check(len(hb) == 1 and hb[0]["par"] == 4, "範囲外Par(9)を除外")

print(f"\n結果: PASS {PASS} / FAIL {FAIL}")
if BUGS:
    print("バグ候補:")
    for b in BUGS:
        print(" -", b)
else:
    print("バグは検出されませんでした。")
