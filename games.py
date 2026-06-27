"""ゴルフのポイントゲーム集計ロジック

- タテ: 18Hのトータルストロークで競う（1ストローク=1点）。総打数が少ないほど良い。
- ヨコ: 各ホール単位の勝敗（ホールマッチ）。ホールで最少打数が勝ち。
- オリンピック: グリーン上のパット競争。金4/銀3/銅2/鉄1、チップイン5（手入力）。

複数人(2〜4人)に対応するため、対戦は総当たり(ペアごと)のネットポイントで表す。
"""


# 得点ルールの初期値
DEFAULT_RULES = {
    "tate_pt": 1,   # タテ: 1ストロークあたりの点数
    "yoko_pt": 1,   # ヨコ: 1ホールあたりの点数
    "olympic": {"金": 4, "銀": 3, "銅": 2, "鉄": 1, "チップイン": 5},
    # ポイントターニー: パーとの差ごとの配点
    "point": {"eagle": 4, "birdie": 2, "par": 1, "bogey": 0, "double": -1},
}


def point_tourney_results(players, pars, rule, num_holes=18, played_count=None):
    """ポイントターニー（ポイント制）。パーとの差に応じて配点し合計で競う。
    rule: {"eagle","birdie","par","bogey","double"}
    Returns: (totals dict, per_hole dict{name:[pts...]})
    """
    def pts(diff):
        if diff <= -2:
            return rule["eagle"]
        if diff == -1:
            return rule["birdie"]
        if diff == 0:
            return rule["par"]
        if diff == 1:
            return rule["bogey"]
        return rule["double"]

    cnt = num_holes if played_count is None else played_count
    totals, per_hole = {}, {}
    for p in players:
        n, t, row = p["name"], 0, []
        for h in range(cnt):
            v = pts(p["scores"][h] - pars[h])
            t += v
            row.append(v)
        totals[n] = t
        per_hole[n] = row
    return totals, per_hole


def las_vegas_number(s1, s2):
    """2人のスコアを「少ない方=10の位、多い方=1の位」で数値化する。"""
    lo, hi = min(s1, s2), max(s1, s2)
    return lo * 10 + hi


def las_vegas_results(team1, team2, scores_by_name, num_holes=18,
                      played_count=None):
    """ラスベガス（2対2）。各チームの2人スコアを数値化し、差を勝ち点とする。
    Returns: dict net1, net2, per_hole[{hole,n1,n2,diff}]
    """
    cnt = num_holes if played_count is None else played_count
    net1 = 0
    per_hole = []
    for h in range(cnt):
        n1 = las_vegas_number(scores_by_name[team1[0]][h],
                              scores_by_name[team1[1]][h])
        n2 = las_vegas_number(scores_by_name[team2[0]][h],
                              scores_by_name[team2[1]][h])
        diff = n2 - n1  # チーム1が小さい(良い)ほどプラス
        net1 += diff
        per_hole.append({"hole": h + 1, "n1": n1, "n2": n2, "diff": diff})
    return {"net1": net1, "net2": -net1, "per_hole": per_hole}

# オリンピックのメダル選択肢（入力用）
OLYMPIC_MEDALS = ["なし", "鉄", "銅", "銀", "金", "チップイン"]


def allocate_strokes(handicap, course_hdcps, num_holes):
    """ハンデ(打数)を、コースHDCPの難しい順にホールへ配分する。
    例: ハンデ10 → コースHDCP 1〜10 のホールに各1打。18超は2巡目。
    """
    strokes = [0] * num_holes
    if not handicap or handicap <= 0:
        return strokes
    base = handicap // 18
    extra = handicap % 18
    for h in range(num_holes):
        ch = course_hdcps[h] if h < len(course_hdcps) and course_hdcps[h] else None
        s = base
        if ch is not None and ch <= extra:
            s += 1
        strokes[h] = s
    return strokes


def tate_results(players, point=1, handicaps=None):
    """タテ: トータルストローク勝負（ハンデ対応）。
    handicaps: {name: ハンデ打数}（ネット=グロス−ハンデ）
    Returns: (gross dict, net_total dict, net_points dict, matrix dict)
      net_total[a] = グロス − ハンデ
      net_points[a] = Σ(相手ネット − 自分ネット) × point（少ないほどプラス）
      matrix は素のネット打数差（point未適用）
    """
    handicaps = handicaps or {}
    gross = {p["name"]: sum(p["scores"]) for p in players}
    net_total = {n: gross[n] - handicaps.get(n, 0) for n in gross}
    names = list(gross.keys())
    net = {n: 0 for n in names}
    matrix = {}
    for a in names:
        for b in names:
            if a == b:
                continue
            diff = net_total[b] - net_total[a]
            matrix[(a, b)] = diff
            net[a] += diff
    net = {n: net[n] * point for n in names}
    return gross, net_total, net, matrix


def yoko_results(players, num_holes, point=1, handicaps=None, course_hdcps=None):
    """ヨコ: ホールマッチ（ハンデ対応）。各ホールでネット最少打数が勝ち。
    handicaps: {name: ハンデ打数}。コースHDCPに応じてホールへ配分し、ネットで比較。
    Returns: (holes_won dict, hole_winners list, net dict)
    """
    names = [p["name"] for p in players]
    gross = {p["name"]: p["scores"] for p in players}
    handicaps = handicaps or {}
    course_hdcps = course_hdcps or []

    # 各人のホール別ハンデ配分 → ネットスコア
    alloc = {n: allocate_strokes(handicaps.get(n, 0), course_hdcps, num_holes)
             for n in names}
    netsc = {n: [gross[n][h] - alloc[n][h] for h in range(min(num_holes, len(gross[n])))]
             for n in names}

    holes_won = {n: 0 for n in names}
    hole_winners = []
    for h in range(num_holes):
        vals = {n: netsc[n][h] for n in names if h < len(netsc[n])}
        if not vals:
            hole_winners.append(None)
            continue
        best = min(vals.values())
        winners = [n for n, v in vals.items() if v == best]
        if len(winners) == 1:
            holes_won[winners[0]] += 1
            hole_winners.append(winners[0])
        else:
            hole_winners.append(None)

    net = {n: 0 for n in names}
    for a in names:
        for b in names:
            if a == b:
                continue
            for h in range(num_holes):
                if h < len(netsc[a]) and h < len(netsc[b]):
                    if netsc[a][h] < netsc[b][h]:
                        net[a] += 1
                    elif netsc[a][h] > netsc[b][h]:
                        net[a] -= 1
    net = {n: net[n] * point for n in names}
    return holes_won, hole_winners, net


def play_order_indices(num_holes, start="OUT"):
    """プレー順のホールindexリスト。INスタートは後半→前半の順。"""
    if num_holes == 18 and start == "IN":
        return list(range(9, 18)) + list(range(9))
    return list(range(num_holes))


def form_teams(player_hdcps):
    """HDCPからチーム分け。
    Aチーム=最少+最多、Bチーム=2位+3位。合計が多い側がハンデN(=差)をもらう。
    Returns dict: teamA, teamB, sumA, sumB, hi_team("A"/"B"), N
    """
    order = sorted(player_hdcps, key=lambda n: (player_hdcps[n], n))
    teamA = [order[0], order[3]]
    teamB = [order[1], order[2]]
    sumA = player_hdcps[teamA[0]] + player_hdcps[teamA[1]]
    sumB = player_hdcps[teamB[0]] + player_hdcps[teamB[1]]
    if sumA >= sumB:
        hi_team, N = "A", sumA - sumB
    else:
        hi_team, N = "B", sumB - sumA
    return {"teamA": teamA, "teamB": teamB, "sumA": sumA, "sumB": sumB,
            "hi_team": hi_team, "N": N}


def best_and_gross(scores_by_name, pars, course_hdcps, player_hdcps,
                   start="OUT", birdie_bonus=True, num_holes=18,
                   played_count=None, override=None):
    """ベスト＆グロス（4人チーム戦）の集計。

    scores_by_name: {name:[scores...]}
    pars: [par...]、course_hdcps: [コースHDCP順位...]、player_hdcps: {name:HDCP}
    played_count: プレー順で何ホールまでを集計対象にするか（ライブ用）。Noneで全部。
    Returns: dict（チーム情報・ハンデホール・ホール別明細・合計）
    """
    if override and override.get("teamA") and override.get("teamB"):
        sumA = sum(player_hdcps.get(n, 0) for n in override["teamA"])
        sumB = sum(player_hdcps.get(n, 0) for n in override["teamB"])
        teams = {"teamA": override["teamA"], "teamB": override["teamB"],
                 "sumA": sumA, "sumB": sumB,
                 "hi_team": override.get("hi_team", "A" if sumA >= sumB else "B"),
                 "N": int(override.get("N", abs(sumA - sumB)))}
    else:
        teams = form_teams(player_hdcps)
    A, B = teams["teamA"], teams["teamB"]
    hi = teams["hi_team"]
    N = teams["N"]

    order = play_order_indices(num_holes, start)

    # ハンデホール判定（コースHDCP <= N）＋プレー順でベスト/グロス交互（コース全体基準）
    hcap_type = {}
    cnt = 0
    for h in order:
        ch = course_hdcps[h] if h < len(course_hdcps) and course_hdcps[h] else None
        if N > 0 and ch is not None and ch <= N:
            hcap_type[h] = "best" if cnt % 2 == 0 else "gross"
            cnt += 1

    scored = order if played_count is None else order[:played_count]
    per_hole = []
    for h in scored:
        a1, a2 = scores_by_name[A[0]][h], scores_by_name[A[1]][h]
        b1, b2 = scores_by_name[B[0]][h], scores_by_name[B[1]][h]
        A_best, B_best = min(a1, a2), min(b1, b2)
        A_gross, B_gross = a1 + a2, b1 + b2

        Ab, Bb, Ag, Bg = A_best, B_best, A_gross, B_gross
        htype = hcap_type.get(h)
        if htype == "best":
            if hi == "A":
                Ab -= 1
            else:
                Bb -= 1
        elif htype == "gross":
            if hi == "A":
                Ag -= 1
            else:
                Bg -= 1

        ptsA = ptsB = 0
        best_w = "A" if Ab < Bb else ("B" if Bb < Ab else None)
        gross_w = "A" if Ag < Bg else ("B" if Bg < Ag else None)
        if best_w == "A":
            ptsA += 1
        elif best_w == "B":
            ptsB += 1
        if gross_w == "A":
            ptsA += 1
        elif gross_w == "B":
            ptsB += 1

        birdie = False
        if birdie_bonus and best_w:
            win_team = A if best_w == "A" else B
            win_best_actual = min(scores_by_name[win_team[0]][h],
                                  scores_by_name[win_team[1]][h])
            if win_best_actual <= pars[h] - 1:  # 実打がバーディ以上
                birdie = True
                if best_w == "A":
                    ptsA += 1
                else:
                    ptsB += 1

        per_hole.append({
            "hole": h + 1, "htype": htype,
            "A_best": A_best, "B_best": B_best,
            "A_gross": A_gross, "B_gross": B_gross,
            "Ab": Ab, "Bb": Bb, "Ag": Ag, "Bg": Bg,
            "best_w": best_w, "gross_w": gross_w, "birdie": birdie,
            "ptsA": ptsA, "ptsB": ptsB,
        })

    def _sum(seq, key, lo, hi_):
        return sum(d[key] for d in seq if lo <= d["hole"] <= hi_)

    totals = {"A": sum(d["ptsA"] for d in per_hole),
              "B": sum(d["ptsB"] for d in per_hole)}
    front = {"A": _sum(per_hole, "ptsA", 1, 9),
             "B": _sum(per_hole, "ptsB", 1, 9)}
    back = {"A": _sum(per_hole, "ptsA", 10, 18),
            "B": _sum(per_hole, "ptsB", 10, 18)}

    return {**teams, "start": start, "birdie_bonus": birdie_bonus,
            "hcap_type": hcap_type, "per_hole": per_hole,
            "totals": totals, "front": front, "back": back}


def olympic_points_from_medals(medals_by_player, olympic_rule):
    """メダル名のリストを配点ルールでポイントに変換する。
    medals_by_player: {name: ["金","なし",...]} → {name: [4,0,...]}
    """
    return {
        n: [int(olympic_rule.get(m, 0)) for m in medals]
        for n, medals in medals_by_player.items()
    }


def olympic_totals(olympic_points):
    """オリンピック: 各プレーヤーのホール別ポイント合計。
    olympic_points: {name: [hole points...]}
    """
    return {n: sum(pts) for n, pts in olympic_points.items()}


# オリンピックの配点（参考表示用）
OLYMPIC_GUIDE = {
    "金": 4, "銀": 3, "銅": 2, "鉄": 1, "チップイン": 5, "なし": 0,
}

# 各ゲームのルール説明（ガイド）
GAME_GUIDE = {
    "タテ": (
        "**タテ（トータルストローク勝負）**\n\n"
        "- 18ホールの総打数で競います（1ストローク＝1点）。\n"
        "- 総当たりで「相手の総打数 − 自分の総打数」を合計。\n"
        "- 打数が少ない人ほど高得点（プラス）になります。\n"
        "- 実力が近いメンバー同士に向いたゲームです。"
    ),
    "ヨコ": (
        "**ヨコ（ホールマッチ）**\n\n"
        "- 各ホールごとに勝敗を決めます。\n"
        "- そのホールで最少打数の人がホールの勝ち（同打数は引き分け）。\n"
        "- 「勝ちホール数」と、総当たりの「勝ち − 負け」で集計。\n"
        "- 1ホールごとにチャンスがあり、初心者にも向きます。"
    ),
    "オリンピック": (
        "**オリンピック（グリーン上のパット競争）**\n\n"
        "- ピンからの距離などで点数を付けます。\n"
        "- 金＝4 / 銀＝3 / 銅＝2 / 鉄＝1、チップインは5点、なし＝0。\n"
        "- 各ホール・各プレーヤーの点数を入力し、合計で競います。"
    ),
    "ポイントターニー": (
        "**ポイントターニー（ポイント制）**\n\n"
        "- 各ホールのスコアをパーと比べ、配点を積み重ねます。\n"
        "- 既定：イーグル以上=4 / バーディ=2 / パー=1 / ボギー=0 / ダブルボギー以上=−1。\n"
        "- 配点は「⚙️ 得点ルールの設定」で変更できます。\n"
        "- 合計点が多い人の勝ち（個人戦）。"
    ),
    "ラスベガス": (
        "**ラスベガス（2対2ペア戦）**\n\n"
        "- 2人ペアを2チーム作ります。\n"
        "- 各チームの2人のスコアを『少ない方=10の位、多い方=1の位』で数値化。\n"
        "  例：4と5 → 45、5と6 → 56。\n"
        "- 2チームの数値の差が、そのホールの勝ち点（小さいチームが獲得）。\n"
        "- 18H（またはハーフ）の合計で勝負。ギャンブル性が高めです。"
    ),
    "ベスト＆グロス": (
        "**ベスト＆グロス（4人チーム戦・ヨコの一種）**\n\n"
        "- **チーム分け**：HDCPの少ない人+多い人=Aチーム、2位+3位=Bチーム。\n"
        "- **ハンデ**：チームHDCP合計の差Nを、合計が多いチームがもらう。\n"
        "  コースHDCPが小さい順にN個がハンデホール（その型でハイハンデチーム−1）。\n"
        "- **毎ホール**：①ベスト（各チーム良い方）勝負 ②グロス（2人合計）勝負 各1点。\n"
        "- **バーディ賞（任意）**：ベスト勝負の勝者の実打がバーディ以上なら+1点。\n"
        "- ハンデホールはプレー順に ベスト型→グロス型→… と交互。\n"
        "- 引き分けはそのホール無得点（持ち越しなし）。\n"
        "- ハーフ(9H)ごと、または18Hで精算。総得点が多いチームの勝ち。"
    ),
}
