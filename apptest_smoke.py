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
# 観戦URL・QRの生成経路をテストで必ず通す。
# これが未設定だとURLが空になり qr_svg が一度も呼ばれず、
# 2026-08-27 の「segnoにStringIOを渡してTypeError」を取り逃がした。
os.environ["APP_BASE_URL"] = "https://example.streamlit.app"
tmp = tempfile.mkdtemp()

import data_manager as dm
dm.DATA_DIR = tmp
dm._FILES = {k: os.path.join(tmp, f"{k}.json")
             for k in ("courses", "rounds", "prefs", "live")}
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

# 分析タブ描画確認用に、同一コース2ラウンド＋別コース1ラウンドを用意
import random as _rnd
_rnd.seed(1)
dm._store("rounds", [
    {"id": 1, "date": "2026-01-01", "course_name": "テストCC",
     "pars": course["pars"], "num_holes": 18,
     "players": [{"name": "私", "scores": [_rnd.randint(3, 7) for _ in range(18)],
                  "putts": [2] * 18}]},
    {"id": 2, "date": "2026-01-08", "course_name": "テストCC",
     "pars": course["pars"], "num_holes": 18,
     "players": [{"name": "私", "scores": [_rnd.randint(3, 7) for _ in range(18)],
                  "putts": [2] * 18}]},
    {"id": 3, "date": "2026-01-15", "course_name": "別コース",
     "pars": [4] * 18, "num_holes": 18,
     "players": [{"name": "私", "scores": [_rnd.randint(3, 7) for _ in range(18)]}]},
])

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


def ss_get(at, key, default=None):
    """AppTest の session_state は .get() を持たないため、KeyError を吸収する。"""
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def click_save(at):
    for b in at.button:
        if "スコアを保存" in (b.label or ""):
            b.click()
            return
    raise AssertionError("保存ボタンが見つからない")


print("== AppTest: 起動 ==")
at0 = run_case("初期起動（分析タブにデータあり）", lambda at: None)


def case_analysis(at):
    # 集計・分析タブのプレーヤー選択を操作（描画確認）
    for sb in at.selectbox:
        if sb.key == "stats_player":
            sb.set_value("私")
    at.run()
    # コース別ホール分析のコース選択
    for sb in at.selectbox:
        if sb.key == "course_hole_select":
            sb.set_value("テストCC")
    at.run()


run_case("分析タブ描画（Par別/内訳/コース別）", case_analysis)

print("== 1人で保存（先のNameError再現確認）==")


def case_1p(at):
    at.text_input(key="player_name_0").set_value("私")
    at.run()
    click_save(at)
    at.run()


run_case("1人・保存", case_1p)

print("== パット記録ON → 各ホール下に入力 → 保存 ==")


def case_putts(at):
    at.text_input(key="player_name_0").set_value("私")
    at.run()
    for cb in at.checkbox:
        if cb.key == "record_putts":
            cb.set_value(True)
    at.run()
    # パット入力はボタン方式（1〜5）。現在ホール分のボタンが出ていること
    ptbtns = [b.key for b in at.button if str(b.key).startswith("ptbtn_0_0_")]
    assert len(ptbtns) == 5, f"パットボタンが5個でない: {ptbtns}"
    at.button(key="ptbtn_0_0_2").click()
    at.run()
    assert at.session_state["putt_0_0"] == 2, "パットが記録されていない"
    click_save(at)
    at.run()


run_case("パット記録ON・保存", case_putts)

print("== ホール単位入力（パー基準ボタン）==")


def case_hole_ui(at):
    at.text_input(key="player_name_0").set_value("私")
    at.run()
    # H1 は Par4 → ボタンは 3,4,5,6,7 の5個
    keys = sorted(b.key for b in at.button if str(b.key).startswith("scbtn_0_0_"))
    assert len(keys) == 5, f"H1のスコアボタンが5個でない: {keys}"
    # 未入力のうちは scored_ が立っていない
    assert not ss_get(at, "scored_0_0"), "入力前なのに入力済みになっている"
    # パー(4)を押す
    at.button(key="scbtn_0_0_4").click()
    at.run()
    assert at.session_state["score_0_0"] == 4, "スコアが入っていない"
    assert at.session_state["scored_0_0"] is True, "入力済みになっていない"
    # 1人なのでこのホールは全員完了 → 自動で次のホールへ
    assert at.session_state["cur_hole"] == 1, \
        f"自動で次のホールへ進んでいない: {at.session_state['cur_hole']}"
    # H2 は「…」から7打以上を直接入力できる
    at.button(key="othbtn_0_1").click()
    at.run()
    at.number_input(key="othnum_0_1").set_value(9)
    at.run()
    assert at.session_state["score_0_1"] == 9, "「…」からの直接入力が効いていない"
    assert at.session_state["scored_0_1"] is True
    # スルーは入力済みホール数に自動追従する
    assert ss_get(at, "_done_holes") == 2, \
        f"入力済みホール数が合わない: {ss_get(at, '_done_holes')}"
    click_save(at)
    at.run()


run_case("ホール単位入力・保存", case_hole_ui)

print("== 観戦モード（?live=xxxx）==")


def case_live_view(at_unused):
    dm.save_live("testlive", {
        "live_id": "testlive", "updated_at": "2026-08-27T10:00:00",
        "date": "2026-08-27", "course_name": "テストCC", "tee": "Regular",
        "pars": course["pars"], "num_holes": 18, "through": 9,
        "players": [
            {"name": "私", "scores": [4] * 18, "entered": [True] * 9 + [False] * 9},
            {"name": "Aさん", "scores": [5] * 18,
             "entered": [True] * 9 + [False] * 9}],
        "standings": {"tate": {"私": 9, "Aさん": -9},
                      "yoko": {"私": 9, "Aさん": -9}},
    })
    v = AppTest.from_file("app.py", default_timeout=60)
    v.query_params["live"] = "testlive"
    v.run()
    assert not v.exception, f"観戦ページで例外: {v.exception}"
    titles = [t.value for t in v.title]
    assert any("ライブスコア" in str(t) for t in titles), f"見出しが無い: {titles}"
    # 編集用タブ（スコア入力など）が出ていないこと＝読み取り専用
    labels = [str(b.label) for b in v.button]
    assert not any("スコアを保存" in l for l in labels), \
        f"観戦ページに保存ボタンが出ている: {labels}"
    subs = [str(x.value) for x in v.subheader]
    assert any("テストCC" in x for x in subs), f"コース名が出ていない: {subs}"
    caps = " ".join(str(c.value) for c in v.caption)
    assert "スルー 9 / 18" in caps, f"スルー表示が無い: {caps}"
    assert len(v.dataframe) >= 2, "スコア表または順位表が出ていない"
    assert not any("ゴルフスコア集計" in str(t.value) for t in v.title), \
        "観戦ページに編集用アプリの見出しが出ている"


run_case("観戦モード描画", case_live_view)

print("== ライブ共有のQR生成 ==")


def case_qr(at):
    at.text_input(key="player_name_0").set_value("私")
    at.run()
    assert not at.exception, f"例外: {at.exception}"
    # QRのSVGと観戦URLが画面に出ていること
    body = " ".join(str(m.value) for m in at.markdown)
    codes = " ".join(str(c.value) for c in at.code)
    assert "<svg" in body, "QRのSVGが描かれていない"
    assert "example.streamlit.app/?live=" in codes, f"観戦URLが出ていない: {codes[:200]}"


run_case("ライブ共有・QR生成", case_qr)

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
