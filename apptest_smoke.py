# -*- coding: utf-8 -*-
"""Streamlit AppTest で app.py を実プログラムとして実行し、
人数・ゲーム選択の各組み合わせで例外が出ないかを検査する。
ファイル保存モードで動かす（API不使用）。
"""
import os
import sys
import io
import json
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ファイル保存モードを強制 & データ用一時フォルダ
os.environ["GOLF_BACKEND"] = "file"
tmp = tempfile.mkdtemp()

import data_manager as dm
dm.DATA_DIR = tmp
dm._FILES = {k: os.path.join(tmp, f"{k}.json")
             for k in ("courses", "rounds", "prefs")}
dm._cache.clear()

# テスト用コース（HDCP・ティー付き 18H）を1件用意
course = {
    "name": "テストCC", "holes": 18,
    "pars": [4, 4, 3, 5, 4, 4, 3, 5, 4, 4, 4, 3, 5, 4, 4, 3, 5, 4],
    "hdcps": [9, 3, 7, 15, 1, 13, 17, 5, 11, 8, 4, 12, 14, 2, 16, 6, 18, 10],
    "tees": ["Back", "Regular"],
    "yards": {"Back": [400] * 18, "Regular": [380] * 18},
    "total_par": 0,
    "hole_data": [],
}
course["total_par"] = sum(course["pars"])
dm._store("courses", [course])

from streamlit.testing.v1 import AppTest

PASS, FAIL, BUGS = 0, 0, []


def run_case(label, setup):
    global PASS, FAIL
    at = AppTest.from_file("app.py", default_timeout=60)
    try:
        at.run()
        setup(at)  # setup内で必要な at.run() を行う
        if at.exception:
            FAIL += 1
            BUGS.append(f"{label}: 例外 {at.exception}")
            print(f"  [FAIL] {label}: {at.exception}")
        else:
            PASS += 1
            print(f"  [OK] {label}")
    except Exception as e:
        FAIL += 1
        BUGS.append(f"{label}: {type(e).__name__} {e}")
        print(f"  [EXC] {label}: {type(e).__name__} {e}")
    return at


def set_player_name(at, idx, name):
    for ti in at.text_input:
        if ti.key == f"player_name_{idx}":
            ti.set_value(name)
            return
    raise AssertionError(f"player_name_{idx} が見つからない")


def click_save(at):
    for b in at.button:
        if "スコアを保存" in (b.label or ""):
            b.click()
            return
    raise AssertionError("保存ボタンが見つからない")


print("== AppTest: 起動 ==")
at0 = run_case("初期起動", lambda at: None)

print("== 1人で保存（先のNameError再現確認）==")


def case_1p(at):
    at.text_input(key="player_name_0").set_value("私")
    at.run()
    click_save(at)
    at.run()


run_case("1人・保存", case_1p)

print("== 2人 + タテ/ヨコ + ハンデ ==")


def case_2p(at):
    for r in at.radio:
        if r.label and "プレーヤー数" in r.label:
            r.set_value(2)
    at.run()
    set_player_name(at, 0, "私")
    try:
        set_player_name(at, 1, "Aさん")
    except AssertionError:
        pass
    at.run()
    click_save(at)
    at.run()


run_case("2人・保存", case_2p)

print("== ハンデ設定を手動に切替（タテ/ヨコにハンデ適用）==")


def case_hcap(at):
    for r in at.radio:
        if r.label and "プレーヤー数" in r.label:
            r.set_value(2)
    at.run()
    set_player_name(at, 0, "私")
    try:
        set_player_name(at, 1, "Aさん")
    except AssertionError:
        pass
    at.run()
    # ハンデの決め方を「手動で設定」に
    for r in at.radio:
        if r.key == "hcap_mode":
            r.set_value("手動で設定")
    at.run()
    click_save(at)
    at.run()


run_case("ハンデ手動・保存", case_hcap)

print("== 4人 + 全ゲーム（B&G/ラスベガス/オリンピック含む）==")


def case_4p_all(at):
    for r in at.radio:
        if r.label and "プレーヤー数" in r.label:
            r.set_value(4)
    at.run()
    for i, nm in enumerate(["私", "A", "B", "C"]):
        set_player_name(at, i, nm)
    at.run()
    # 全ゲーム選択
    at.multiselect(key="live_games").set_value(
        ["タテ", "ヨコ", "オリンピック", "ポイントターニー",
         "ラスベガス", "ベスト＆グロス"])
    at.run()
    # 各自HDCP入力（B&G/タテ/ヨコ共通）
    for nm, v in zip(["私", "A", "B", "C"], [10, 18, 5, 20]):
        for ni in at.number_input:
            if ni.key == f"hcap_{nm}":
                ni.set_value(v)
    at.run()
    # ラスベガスのチーム1を2人選択
    try:
        at.multiselect(key="lv_team1").set_value(["私", "A"])
        at.run()
    except Exception:
        pass
    click_save(at)
    at.run()


run_case("4人・全ゲーム・保存", case_4p_all)

print("== 4人・B&Gで手動チーム指定 ==")


def case_bg_manual(at):
    for r in at.radio:
        if r.label and "プレーヤー数" in r.label:
            r.set_value(4)
    at.run()
    for i, nm in enumerate(["私", "A", "B", "C"]):
        set_player_name(at, i, nm)
    at.run()
    at.multiselect(key="live_games").set_value(["ベスト＆グロス"])
    at.run()
    # 手動チーム指定ON
    for cb in at.checkbox:
        if cb.key == "bg_manual":
            cb.set_value(True)
    at.run()
    try:
        at.multiselect(key="bg_manual_teamA").set_value(["私", "B"])
        at.run()
    except Exception:
        pass
    click_save(at)
    at.run()


run_case("4人・B&G手動・保存", case_bg_manual)

print(f"\n結果: PASS {PASS} / FAIL {FAIL}")
if BUGS:
    print("バグ候補:")
    for b in BUGS:
        print(" -", b)
else:
    print("AppTestでバグは検出されませんでした。")
