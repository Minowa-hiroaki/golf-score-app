#!/usr/bin/env python3
# rename_ibaraki.py — 茨木の略記コース名を既存DBの正式表記へ名寄せ
#
# 変更するのは course_name のみ。打数・日付・ティー・その他フィールドは一切変更しない。
# 寄せ先の正式表記は「DBから自動検出」するため、スペース/全角半角の取り違えが起きない。
# リネーム後に (date, 寄せ先名) が既存と衝突する場合（同一ラウンドの二重登録疑い）は
# 勝手に消さず、報告して中止する。

import data_manager as dm
from collections import defaultdict

ABBREV_EAST = "茨木CC 東/東"   # 今回登録した略記（East）
ABBREV_WEST = "茨木CC 西/西"   # 今回登録した略記（West）

rounds = dm.load_rounds()
print(f"総ラウンド数: {len(rounds)}")

# --- 1) 既存DBから茨木の正式表記を自動検出 ---
names = {r.get("course_name") for r in rounds if r.get("course_name")}
ibaraki = {n for n in names if "茨木" in n}
formal = ibaraki - {ABBREV_EAST, ABBREV_WEST}

print("\n茨木を含むコース名（現状）:")
for n in sorted(ibaraki):
    print(f"  「{n}」")

formal_east = [n for n in formal if "東" in n]
formal_west = [n for n in formal if "西" in n]

problem = False
if len(formal_east) != 1:
    print(f"⚠️ 正式表記(東)の検出が {len(formal_east)}件: {formal_east}"); problem = True
if len(formal_west) != 1:
    print(f"⚠️ 正式表記(西)の検出が {len(formal_west)}件: {formal_west}"); problem = True
if problem:
    print("\n自動検出に失敗。寄せ先名を手動指定して RENAME を書き換えてください。中止します。")
    raise SystemExit(1)

RENAME = {
    ABBREV_EAST: formal_east[0],
    ABBREV_WEST: formal_west[0],
}
print("\n名寄せマップ:")
for a, b in RENAME.items():
    print(f"  「{a}」→「{b}」")

# --- 2) 変更前の日付一覧 ---
byname = defaultdict(list)
for r in rounds:
    byname[r.get("course_name")].append(r.get("date"))

# --- 3) 衝突チェック（リネーム後に (date, 寄せ先名) が重複しないか） ---
collision = False
for old, new in RENAME.items():
    exist_dates = set(byname.get(new, []))
    for d in byname.get(old, []):
        if d in exist_dates:
            print(f"⚠️ 衝突: {d} が「{old}」と「{new}」の両方に存在（同一ラウンドの二重登録疑い）")
            collision = True
if collision:
    print("\n衝突があるため中止。該当日をHiroに確認してから対処します（勝手に消しません）。")
    raise SystemExit(1)

# --- 4) リネーム実行 ---
changed = 0
for r in rounds:
    cn = r.get("course_name")
    if cn in RENAME:
        r["course_name"] = RENAME[cn]
        changed += 1
        print(f"rename: {r.get('date')}  「{cn}」→「{RENAME[cn]}」")
print(f"\n変更 {changed}件")

if changed == 0:
    print("変更対象なし（既に名寄せ済み？）。保存せず終了。")
    raise SystemExit(0)

# --- 5) 保存 ---
dm._store("rounds", rounds)
dm.clear_cache()

# --- 6) 確認 ---
r2 = dm.load_rounds()
cnt = defaultdict(int)
for r in r2:
    if "茨木" in (r.get("course_name") or ""):
        cnt[r["course_name"]] += 1
print("\n--- 保存後（茨木関連）---")
for n, c in sorted(cnt.items()):
    print(f"  「{n}」: {c}件")
print(f"保存後 総ラウンド数: {len(r2)}（174のまま = リネームのみで件数不変が正常）")
