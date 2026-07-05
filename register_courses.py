#!/usr/bin/env python3
# register_courses.py
# 集計に出ているコース（＝ラウンドが存在する course_name）を登録コース(coursesマスタ)に一括登録する。
#
# 方針:
#   - 各コースの pars は、そのコース名を持つラウンドの pars から採取。
#     複数ラウンドで pars が食い違うコースは "割れ" として中止（勝手に決めない）。
#   - hdcps は霞ヶ関のみ充当（西=KW_HDCP / 東=KE_HDCP）。他コースは全None。
#     充当時は Par配列(pars)と HDCP配列の整合(長さ18・{1..18}の順列)を検査。
#   - yards / tees は今回のラウンドに無いので空（既存スキーマの形だけ保持）。
#   - 既存 courses に同名がある場合は save_course が「上書き」になるため、
#     既存を壊さないよう既定でスキップ（OVERWRITE_EXISTING=False）。
#   - 連結スコアの特殊コースは既定で除外（EXCLUDE）。
#
# 実行:
#   1) まず APPLY=False のまま実行し、登録プランを目視確認
#   2) 問題なければ APPLY=True にして再実行 → coursesマスタに書き込み
#   3) アプリを完全再起動（Ctrl+C → streamlit run app.py）して反映確認

import data_manager as dm
from collections import defaultdict

# ===== 設定 =====
APPLY = False                 # True にすると実際に書き込む
OVERWRITE_EXISTING = False    # True にすると既存の同名登録コースを上書きする（既定は保護してスキップ）

# 除外するコース名（連結スコアの特殊コースなど）
EXCLUDE = {
    "霞ヶ関CC 東IN/東IN(連結)",
    "霞ヶ関CC 西OUT/西OUT(連結)",
}

# 霞ヶ関のHDCP（IMG_1628/1629 より、{1..18}の順列であることを確認済み）
KW_HDCP = [9,15,3,13,7,1,11,5,17,  10,16,4,8,14,2,12,6,18]   # 西/西 (Par73)
KE_HDCP = [9,15,3,13,1,7,11,17,5,  16,10,4,14,2,8,12,18,6]   # 東/東 (Par71)
HDCP_MAP = {
    "霞ヶ関CC 西/西": KW_HDCP,
    "霞ヶ関CC 東/東": KE_HDCP,
}

# ===== ここから処理 =====
rounds = dm.load_rounds()
print(f"総ラウンド数: {len(rounds)}")

# コース名 -> そのコースの pars 候補（ラウンドから）
pars_by_course = defaultdict(list)   # name -> list of tuple(pars)
for r in rounds:
    cn = r.get("course_name")
    pars = r.get("pars")
    if not cn or not pars:
        continue
    pars_by_course[cn].append(tuple(pars))

existing_names = {c["name"] for c in dm.load_courses()}
print(f"既存の登録コース: {len(existing_names)}件  {sorted(existing_names)}")

def is_perm_1_18(seq):
    return len(seq) == 18 and sorted(seq) == list(range(1, 19))

plans = []      # 登録予定
skips = []      # スキップ理由付き
errors = []     # 中止級の問題

for name in sorted(pars_by_course.keys()):
    if name in EXCLUDE:
        skips.append((name, "除外指定(EXCLUDE)"))
        continue

    par_variants = set(pars_by_course[name])
    if len(par_variants) != 1:
        errors.append((name, f"pars がラウンド間で割れている: {sorted(par_variants)}"))
        continue
    pars = list(next(iter(par_variants)))
    if len(pars) != 18:
        errors.append((name, f"pars が18ホールでない: {len(pars)}"))
        continue

    # HDCP 充当
    hdcps = [None] * 18
    if name in HDCP_MAP:
        h = HDCP_MAP[name]
        if not is_perm_1_18(h):
            errors.append((name, "HDCP配列が{1..18}の順列でない")); continue
        hdcps = list(h)

    # 既存との衝突（上書き保護）
    if name in existing_names and not OVERWRITE_EXISTING:
        skips.append((name, "既に登録コースに存在（上書き保護のためスキップ）"))
        continue

    hole_data = [
        {"hole": i + 1, "par": pars[i], "hdcp": hdcps[i], "yards": {}}
        for i in range(18)
    ]
    course = {
        "name": name,
        "holes": 18,
        "hole_data": hole_data,
        "pars": pars,
        "hdcps": hdcps,
        "tees": [],
        "yards": {},
        "total_par": sum(pars),
    }
    plans.append(course)

# ===== レポート =====
print("\n===== 登録プラン =====")
for c in plans:
    hd = "HDCP有" if any(x is not None for x in c["hdcps"]) else "HDCP無"
    print(f"  ADD  {c['name']}  (Par{c['total_par']}, {hd})  rounds={len(pars_by_course[c['name']])}")

print("\n----- スキップ -----")
for n, why in skips:
    print(f"  skip {n}  … {why}")

if errors:
    print("\n⚠️ ----- 要確認（中止対象）-----")
    for n, why in errors:
        print(f"  STOP {n}  … {why}")

print(f"\n登録予定 {len(plans)}件 / スキップ {len(skips)}件 / 問題 {len(errors)}件")

if errors:
    print("\n問題(割れ等)があるため書き込みを中止しました。上記STOPを確認してください。")
    raise SystemExit(1)

if not APPLY:
    print("\n[dry-run] APPLY=False のため書き込みはしていません。")
    print("内容に問題なければ APPLY=True にして再実行してください。")
    raise SystemExit(0)

# ===== 書き込み =====
added = 0
for c in plans:
    res = dm.save_course(c)
    added += 1
    tag = "上書き" if res.get("replaced") else "追加"
    print(f"save: {c['name']}  ({tag})")

print(f"\n書き込み完了 {added}件。")
print("→ アプリを完全再起動（Ctrl+C → streamlit run app.py）して登録コースを確認してください。")
