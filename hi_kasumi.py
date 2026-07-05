#!/usr/bin/env python3
# hi_kasumi.py — 霞ヶ関(東/西)・ブルーティー限定の「近似」ハンディキャップインデックス
#
# 読み取り専用。DBには一切書き込まない。
#
# 近似である理由（重要）:
#   1) CR/SRが分かるのは霞ヶ関 東/西のブルーのみ。よって「霞ヶ関ブルー限定の直近20」で計算する。
#      本来のJGA HIは全コース・全ティーの直近20なので、J-SYSの数値とは一致しない。
#   2) PCC(プレーイングコンディション調整)は復元不能 → 0 と仮定。
#   3) 調整スコア(ネットダブルボギー上限)はコースハンデ→HIに依存する循環。
#      収束したHIを一律に使って反復近似する（J-SYSは各ラウンド時点のHIを使う）。
#   4) ソフト/ハードキャップ、上限54.0のうちキャップ類は未考慮（上限54.0のみ適用）。
#
# 画像(IMG_1628/1629)由来の確定値:
#   東/東 ブルー: CR 70.6 / SR 126 (Par71)
#   西/西 ブルー: CR 71.6 / SR 130 (Par73)

import math
import data_manager as dm

# ---- コース定義（ブルーティー）----
KE_HDCP = [9,15,3,13,1,7,11,17,5,  16,10,4,14,2,8,12,18,6]   # 東/東
KW_HDCP = [9,15,3,13,7,1,11,5,17,  10,16,4,8,14,2,12,6,18]   # 西/西
COURSE_INFO = {
    "霞ヶ関CC 東/東": {"cr": 70.6, "sr": 126, "par": 71, "hdcp": KE_HDCP},
    "霞ヶ関CC 西/西": {"cr": 71.6, "sr": 130, "par": 73, "hdcp": KW_HDCP},
}
TEE_OK = {"ブルー"}     # CR/SR はこのティーの値
PCC = 0.0
PLAYER = "hiroaki minowa"
WINDOW = 20             # 直近何ラウンドを母集団にするか（WHSは20）


def course_handicap(hi, sr, cr, par):
    return round(hi * (sr / 113.0) + (cr - par))


def strokes_per_hole(ch, hdcp_index):
    n = len(hdcp_index)
    base = ch // n
    rem = ch % n
    return [base + (1 if hdcp_index[i] <= rem else 0) for i in range(n)]


def adjusted_gross(scores, pars, ch, hdcp_index):
    sph = strokes_per_hole(ch, hdcp_index)
    return sum(min(s, pars[i] + 2 + sph[i]) for i, s in enumerate(scores))


def score_diff(ags, cr, sr, pcc=PCC):
    return round((113.0 / sr) * (ags - cr - pcc), 1)


def hi_from_diffs(diffs):
    """直近母集団のSDリストから HI を算出（枚数別ベスト枚数＋調整）。"""
    ds = sorted(diffs)
    n = len(ds)
    if n < 3:
        return None
    table = {3:(1,-2.0),4:(1,-1.0),5:(1,0.0),6:(2,-1.0),7:(2,0.0),8:(2,0.0),
             9:(3,0.0),10:(3,0.0),11:(3,0.0),12:(4,0.0),13:(4,0.0),14:(4,0.0),
             15:(5,0.0),16:(5,0.0),17:(6,0.0),18:(6,0.0),19:(7,0.0),20:(8,0.0)}
    use, adj = table[min(n, 20)]
    hi = sum(ds[:use]) / use + adj
    return min(math.floor(hi * 10) / 10, 54.0), use


def main():
    rounds = dm.load_rounds()

    # 対象抽出：霞ヶ関 東/西 かつ ブルー
    elig, skipped_tee, skipped_other = [], 0, 0
    for r in rounds:
        cn = r.get("course_name")
        if cn not in COURSE_INFO:
            continue
        info = COURSE_INFO[cn]
        tee = r.get("tee")
        if tee not in TEE_OK:
            skipped_tee += 1
            continue
        # プレーヤーの打数
        sc = None
        for p in r["players"]:
            if p["name"] == PLAYER:
                sc = p["scores"]
                break
        if not sc or len(sc) != 18:
            skipped_other += 1
            continue
        pars = r.get("pars") or []
        if len(pars) != 18:
            skipped_other += 1
            continue
        elig.append({
            "date": str(r.get("date", "")),
            "course": cn, "tee": tee,
            "cr": info["cr"], "sr": info["sr"], "par": info["par"],
            "hdcp": info["hdcp"], "scores": sc, "pars": pars,
            "gross": sum(sc),
        })

    print(f"霞ヶ関(東/西)・ブルーの対象ラウンド: {len(elig)}")
    print(f"  （霞ヶ関でブルー以外のためスキップ: {skipped_tee} / データ不備スキップ: {skipped_other}）")
    if len(elig) < 3:
        print("SDが3枚未満のためHIを算出できません。")
        return

    # 直近WINDOW件（日付降順）
    elig.sort(key=lambda x: x["date"], reverse=True)
    window = elig[:WINDOW]
    print(f"直近{len(window)}ラウンドを母集団に使用"
          f"（{window[-1]['date']} 〜 {window[0]['date']}）\n")

    # 反復：CHはHIに依存 → 収束させる
    hi = 20.0
    for _ in range(100):
        diffs = []
        for r in window:
            ch = course_handicap(hi, r["sr"], r["cr"], r["par"])
            ags = adjusted_gross(r["scores"], r["pars"], ch, r["hdcp"])
            diffs.append(score_diff(ags, r["cr"], r["sr"]))
        res = hi_from_diffs(diffs)
        if res is None:
            print("算出不可"); return
        new_hi, use = res
        if abs(new_hi - hi) < 0.05:
            hi = new_hi
            break
        hi = new_hi

    # 最終内訳
    rows = []
    for r in window:
        ch = course_handicap(hi, r["sr"], r["cr"], r["par"])
        ags = adjusted_gross(r["scores"], r["pars"], ch, r["hdcp"])
        sd = score_diff(ags, r["cr"], r["sr"])
        rows.append((r["date"], r["course"], r["gross"], ags, ch, sd))

    diffs = [x[5] for x in rows]
    res = hi_from_diffs(diffs)
    hi, use = res
    used_threshold = sorted(diffs)[use - 1]  # ベスト何枚目までが採用か

    print(f"{'日付':<12}{'コース':<18}{'gross':>6}{'AGS':>6}{'CH':>4}{'SD':>7}  採用")
    print("-" * 62)
    counted = 0
    for d, c, g, a, ch, sd in sorted(rows, key=lambda x: x[5]):
        mark = ""
        if counted < use:
            mark = "★"; counted += 1
        print(f"{d:<12}{c:<18}{g:>6}{a:>6}{ch:>4}{sd:>7}  {mark}")

    print("\n" + "=" * 50)
    print(f"■ 近似HI（霞ヶ関ブルー基準）= {hi}")
    print(f"   直近{len(window)}枚のうちベスト{use}枚の平均で算出（★印が採用SD）")
    print("=" * 50)
    print("※ J-SYSの正式HIは全コース・全ティーの直近20＋PCC＋各時点HIで計算されるため、"
          "この近似値とは一致しません。傾向把握用です。")


if __name__ == "__main__":
    main()
