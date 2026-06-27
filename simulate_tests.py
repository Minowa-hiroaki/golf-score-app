# -*- coding: utf-8 -*-
"""全ゲーム・境界条件の網羅シミュレーション（バグ検査）。
DBに触れないよう games.py のロジックのみを対象にする。
"""
import random
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from games import (
    tate_results, yoko_results, allocate_strokes, point_tourney_results,
    las_vegas_results, las_vegas_number, best_and_gross, form_teams,
    olympic_points_from_medals, DEFAULT_RULES,
)

PASS, FAIL = 0, 0
BUGS = []


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        BUGS.append(msg)
        print("  [FAIL]", msg)


def players_from(scores):
    return [{"name": n, "scores": s} for n, s in scores.items()]


# ===== 1. allocate_strokes =====
print("== allocate_strokes ==")
ch18 = list(range(1, 19))
check(sum(allocate_strokes(0, ch18, 18)) == 0, "hdcp0 -> 0打")
check(sum(allocate_strokes(10, ch18, 18)) == 10, "hdcp10 合計10打")
check(allocate_strokes(10, ch18, 18)[:10] == [1] * 10 and
      allocate_strokes(10, ch18, 18)[10:] == [0] * 8, "hdcp10 はHDCP1-10へ1打")
check(sum(allocate_strokes(18, ch18, 18)) == 18, "hdcp18 合計18")
check(sum(allocate_strokes(25, ch18, 18)) == 25, "hdcp25(>18) 合計25")
check(allocate_strokes(20, ch18, 18)[0] == 2, "hdcp20 HDCP1は2打")
check(sum(allocate_strokes(10, [], 18)) == 0, "コースHDCP無し<18 は0打(配分不可)")

# ===== 2. tate =====
print("== tate ==")
for npl in (2, 3, 4):
    sc = {f"P{i}": [random.randint(3, 7) for _ in range(18)] for i in range(npl)}
    g, nt, net, mat = tate_results(players_from(sc), 1)
    check(sum(net.values()) == 0, f"tate {npl}人 ネット得点ゼロ和")
    check(all(nt[n] == sum(sc[n]) for n in sc), f"tate {npl}人 ハンデ無しネット=グロス")
# ハンデあり
sc = {"A": [5] * 18, "B": [4] * 18}
g, nt, net, mat = tate_results(players_from(sc), 1, {"A": 18, "B": 0})
check(nt["A"] == 90 - 18 and nt["B"] == 72, "tate ハンデ反映 ネット")
check(net["A"] == 0 and net["B"] == 0, "tate ハンデでネット同点->0点")
# 得点倍率
g, nt, net, mat = tate_results(players_from({"A": [4] * 18, "B": [5] * 18}), 3)
check(net["A"] == 54 and net["B"] == -54, "tate 倍率3 反映")

# ===== 3. yoko =====
print("== yoko ==")
for npl in (2, 3, 4):
    sc = {f"P{i}": [random.randint(3, 7) for _ in range(18)] for i in range(npl)}
    hw, win, net = yoko_results(players_from(sc), 18, 1)
    check(sum(net.values()) == 0, f"yoko {npl}人 得点ゼロ和")
    check(sum(hw.values()) <= 18, f"yoko {npl}人 勝ちホール数<=18")
# 全ホール引き分け
hw, win, net = yoko_results(players_from({"A": [4] * 18, "B": [4] * 18}), 18, 1)
check(all(v == 0 for v in net.values()) and all(w is None for w in win),
      "yoko 全引分 -> 0点・勝者なし")
# ハンデ反映（Aが弱いがハンデでネット勝ち）
hw, win, net = yoko_results(players_from({"A": [5] * 18, "B": [4] * 18}), 18, 1,
                            {"A": 18, "B": 0}, ch18)
check(net["A"] == 0, "yoko フルハンデでネット互角=0点")

# ===== 4. point tourney =====
print("== point ==")
pr = DEFAULT_RULES["point"]
pars = [4] * 18
# A: 全バーディ(3) -> birdie点*18 ; B: 全パー
tot, _ = point_tourney_results(
    players_from({"A": [3] * 18, "B": [4] * 18}), pars, pr, 18)
check(tot["A"] == pr["birdie"] * 18, "point 全バーディ")
check(tot["B"] == pr["par"] * 18, "point 全パー")
# 各カテゴリ
tot, ph = point_tourney_results(
    players_from({"X": [2, 3, 4, 5, 6]}), [4, 4, 4, 4, 4], pr, 5)
check(ph["X"] == [pr["eagle"], pr["birdie"], pr["par"], pr["bogey"], pr["double"]],
      "point 各カテゴリ配点")

# ===== 5. las vegas =====
print("== las vegas ==")
check(las_vegas_number(4, 5) == 45 and las_vegas_number(5, 4) == 45,
      "vegas 数値化(少ない方が十の位)")
check(las_vegas_number(3, 3) == 33, "vegas 同値")
sc = {"A": [4] * 18, "B": [5] * 18, "C": [6] * 18, "D": [4] * 18}
lv = las_vegas_results(["A", "B"], ["C", "D"], sc, 18)
check(lv["net1"] == -lv["net2"], "vegas net1=-net2")

# ===== 6. form_teams =====
print("== form_teams ==")
t = form_teams({"a": 4, "b": 5, "c": 5, "d": 16})
check(set(t["teamA"]) == {"a", "d"} and set(t["teamB"]) == {"b", "c"},
      "teams: 最少+最多 / 2位+3位")
check(t["sumA"] == 20 and t["sumB"] == 10 and t["hi_team"] == "A" and t["N"] == 10,
      "teams: 合計とハンデ数")
t2 = form_teams({"a": 10, "b": 10, "c": 10, "d": 10})
check(t2["N"] == 0, "teams: 全員同HDCP -> N0")

# ===== 7. best & gross：ユーザー提示の例を厳密検証 =====
print("== best&gross (例の厳密検証) ==")
ph = {"Me": 4, "X": 5, "Y": 5, "Z": 16}  # A=Me+Z=20, B=10, AがN=10
pars = [4] * 18
chdcps = list(range(1, 19))  # H1=1..H10=10 がハンデホール
# H1=ベスト型, H2=グロス型（OUTスタート）


def bestcase(a_best):
    sc = {"Me": [a_best] + [4] * 17, "Z": [9] + [4] * 17,
          "X": [5] + [4] * 17, "Y": [9] + [4] * 17}
    r = best_and_gross(sc, pars, chdcps, ph, "OUT", False, 18)
    return r["per_hole"][0]


h = bestcase(5)
check(h["htype"] == "best" and h["ptsA"] == 1 and h["ptsB"] == 0, "B&G 例 ベスト5->A勝")
h = bestcase(6)
check(h["best_w"] is None, "B&G 例 ベスト6->ベスト引分")
h = bestcase(7)
check(h["best_w"] == "B", "B&G 例 ベスト7->B勝")


def grosscase(a_pair):
    sc = {"Me": [4, a_pair[0]] + [4] * 16, "Z": [4, a_pair[1]] + [4] * 16,
          "X": [4, 5] + [4] * 16, "Y": [4, 5] + [4] * 16}
    r = best_and_gross(sc, pars, chdcps, ph, "OUT", False, 18)
    return r["per_hole"][1]


h = grosscase((5, 5))
check(h["htype"] == "gross" and h["gross_w"] == "A", "B&G 例 グロス10->A勝")
h = grosscase((6, 5))
check(grosscase((6, 5))["gross_w"] is None, "B&G 例 グロス11->引分")
check(grosscase((7, 5))["gross_w"] == "B", "B&G 例 グロス12->B勝")

# 合計の整合性（totals = front + back）
sc = {n: [random.randint(3, 7) for _ in range(18)] for n in ph}
r = best_and_gross(sc, pars, chdcps, ph, "OUT", True, 18)
check(r["totals"]["A"] == r["front"]["A"] + r["back"]["A"], "B&G totals=front+back(A)")
check(r["totals"]["B"] == r["front"]["B"] + r["back"]["B"], "B&G totals=front+back(B)")
check(r["totals"]["A"] == sum(d["ptsA"] for d in r["per_hole"]), "B&G totals=ホール合計")

# ハンデホールのベスト/グロス交互
types = [r2 for r2 in [best_and_gross(sc, pars, chdcps, ph, "OUT", True, 18)
                       ["hcap_type"][hh] for hh in range(10)]]
check(types == ["best", "gross"] * 5, "B&G ハンデホールが交互(OUT,HDCP1-10)")

# INスタートで起点が変わる
rin = best_and_gross(sc, pars, chdcps, ph, "IN", True, 18)
# INスタート: 最初に来るハンデホールはHDCP<=10のうちプレー順最初(H10=HDCP10)
first_hcap_hole = next(hh for hh in (list(range(9, 18)) + list(range(9)))
                       if chdcps[hh] <= 10)
check(rin["hcap_type"][first_hcap_hole] == "best", "B&G INスタート 起点ベスト")

# N=0（ハンデ無し）でハンデホール無し
ph0 = {n: 10 for n in ph}  # 全員同HDCP
r0 = best_and_gross(sc, pars, chdcps, ph0, "OUT", True, 18)
check(len(r0["hcap_type"]) == 0, "B&G N0 -> ハンデホール無し")

# override（手動チーム・ハンデ）
ro = best_and_gross(sc, pars, chdcps, ph, "OUT", True, 18,
                    override={"teamA": ["Me", "X"], "teamB": ["Y", "Z"],
                              "hi_team": "B", "N": 5})
check(set(ro["teamA"]) == {"Me", "X"} and ro["N"] == 5 and ro["hi_team"] == "B",
      "B&G override 反映")

# played_count（ライブ途中）
rp = best_and_gross(sc, pars, chdcps, ph, "OUT", True, 18, played_count=3)
check(len(rp["per_hole"]) == 3, "B&G played_count=3 で3ホールのみ")

# 9ホールコース
sc9 = {n: [random.randint(3, 7) for _ in range(9)] for n in ph}
r9 = best_and_gross(sc9, [4] * 9, list(range(1, 10)), ph, "OUT", True, 9)
check(len(r9["per_hole"]) == 9 and r9["back"]["A"] == 0, "B&G 9ホール OK")

# バーディ賞: イーグルでも付与される（実打par-2）
scb = {"Me": [2] + [4] * 17, "Z": [9] + [4] * 17, "X": [5] + [4] * 17,
       "Y": [9] + [4] * 17}
rb = best_and_gross(scb, pars, chdcps, ph, "OUT", True, 18)
check(rb["per_hole"][0]["birdie"] is True, "B&G イーグルでもバーディ賞")

# ===== 8. ランダム不変条件ストレス =====
print("== ストレス(1000回) ==")
random.seed(42)
err = 0
for _ in range(1000):
    n = random.choice([2, 3, 4])
    holes = random.choice([9, 18])
    names = [f"P{i}" for i in range(n)]
    sc = {nm: [random.randint(1, 12) for _ in range(holes)] for nm in names}
    try:
        _, _, net, _ = tate_results(players_from(sc), random.randint(1, 5))
        assert sum(net.values()) == 0
        _, _, ynet = yoko_results(players_from(sc), holes, 1)
        assert sum(ynet.values()) == 0
        pt, _ = point_tourney_results(players_from(sc), [4] * holes,
                                      DEFAULT_RULES["point"], holes)
        if n == 4:
            lv = las_vegas_results(names[:2], names[2:], sc, holes)
            assert lv["net1"] == -lv["net2"]
            ph_r = {nm: random.randint(0, 36) for nm in names}
            chx = list(range(1, holes + 1))
            r = best_and_gross(sc, [4] * holes, chx, ph_r,
                               random.choice(["OUT", "IN"]),
                               random.choice([True, False]), holes)
            assert r["totals"]["A"] == sum(d["ptsA"] for d in r["per_hole"])
    except Exception as e:
        err += 1
        if err <= 3:
            print("  [EXC]", type(e).__name__, e)
check(err == 0, f"ストレス1000回 例外なし（{err}件）")

print(f"\n結果: PASS {PASS} / FAIL {FAIL}")
if BUGS:
    print("バグ候補:")
    for b in BUGS:
        print(" -", b)
else:
    print("バグは検出されませんでした。")
