import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, datetime
from data_manager import (
    load_courses, save_course, delete_course, load_rounds, save_round,
    delete_round, update_round, get_hole_averages, get_all_player_names,
    ensure_data_dir, load_prefs, update_prefs,
    get_par_type_stats, get_score_breakdown, get_player_courses,
    get_course_hole_averages, get_recent_putt_avg, get_course_score_averages,
    rename_player, player_round_counts, player_rounds_of, forget_player,
)
from games import (
    tate_results, yoko_results, olympic_totals, olympic_points_from_medals,
    best_and_gross, point_tourney_results, las_vegas_results, LV_TEAM_MODES,
    OLYMPIC_GUIDE, GAME_GUIDE, DEFAULT_RULES, OLYMPIC_MEDALS,
    extra_points, EXTRA_HOLE_AWARDS,
)
from data_manager import save_live, load_live
import live_share
import ocr_score

GAME_OPTIONS = ["タテ", "ヨコ", "オリンピック", "ポイントターニー",
                "ラスベガス", "ベスト＆グロス"]


def get_rules():
    """保存済みの得点ルール（無ければ初期値）を返す"""
    saved = load_prefs().get("rules", {})
    rules = {"tate_pt": DEFAULT_RULES["tate_pt"],
             "yoko_pt": DEFAULT_RULES["yoko_pt"],
             "olympic": dict(DEFAULT_RULES["olympic"]),
             "point": dict(DEFAULT_RULES["point"])}
    if "tate_pt" in saved:
        rules["tate_pt"] = saved["tate_pt"]
    if "yoko_pt" in saved:
        rules["yoko_pt"] = saved["yoko_pt"]
    if isinstance(saved.get("olympic"), dict):
        rules["olympic"].update(saved["olympic"])
    if isinstance(saved.get("point"), dict):
        rules["point"].update(saved["point"])
    return rules
from course_search import (
    create_manual_course, create_default_18hole_course,
    search_rakuten, fetch_holes_from_layout, extract_cid,
)


def _secret_or_env(name, session_key):
    """secrets / 環境変数 / 画面入力 の順に値を探す。前後の空白・改行は除去する。"""
    try:
        v = st.secrets.get(name)
        if v:
            return str(v).strip()
    except Exception:
        pass
    if os.environ.get(name):
        return os.environ[name].strip()
    return str(st.session_state.get(session_key, "")).strip()


def get_rakuten_app_id():
    """楽天 applicationId を secrets / 環境変数 / 入力欄 から取得"""
    return _secret_or_env("RAKUTEN_APP_ID", "rakuten_app_id")


def get_rakuten_access_key():
    """楽天 accessKey を secrets / 環境変数 / 入力欄 から取得。
    2026年2月の楽天ウェブサービス刷新で applicationId と併せて必須になった。"""
    return _secret_or_env("RAKUTEN_ACCESS_KEY", "rakuten_access_key")


def get_app_pin():
    """編集側の暗証番号。secrets / 環境変数 だけを見る。

    _secret_or_env は画面入力(session_state)もフォールバックに使うため、
    暗証番号には使わない（session_state 経由で値を差し込まれる余地をなくす）。
    """
    try:
        v = st.secrets.get("APP_PIN")
        if v:
            return str(v).strip()
    except Exception:
        pass
    return (os.environ.get("APP_PIN") or "").strip()


def get_rakuten_referer():
    """楽天アプリに登録した「許可されたWebサイト」のURL。
    新基盤は呼び出し元サイトを見るため、サーバー側からの呼び出しでは
    Referer/Origin を自分で付けないと 403 になる。"""
    return _secret_or_env("RAKUTEN_REFERER", "rakuten_referer")


def hole_columns(num_holes):
    """表の列ラベル。18Hなら OUT / IN / 計、9Hなら 計 を含む"""
    cols = [f"H{i+1}" for i in range(num_holes)]
    if num_holes == 18:
        cols.insert(9, "OUT")
        cols.append("IN")
    cols.append("計")
    return cols


def expand_row(values, num_holes, agg="sum"):
    """各ホールの値に OUT/IN/合計 を挿入した行を返す。
    agg="sum": 小計・合計を計算 / agg="none": 合計欄は "-"（HDCP用）
    """
    def fmt(x):
        return x if x is not None else "-"

    def s(seq):
        return sum(v for v in seq if isinstance(v, (int, float)))

    vals = list(values)
    out = [fmt(v) for v in vals]
    if agg == "none":
        if num_holes == 18:
            out.insert(9, "-")
            out.append("-")
        out.append("-")
        return out
    if num_holes == 18:
        out.insert(9, s(vals[:9]))
        out.append(s(vals[9:]))
    out.append(s(vals))
    return out


def make_info_table(num_holes, pars, hdcps=None, tees_yards=None):
    """Par/HDCP/ティー別ヤード（小計・合計付き）の表(DataFrame)を作る。
    tees_yards: [(ティー名, ヤード配列), ...]
    """
    info = {"ホール": hole_columns(num_holes),
            "Par": expand_row(pars, num_holes, "sum")}
    if hdcps and any(x is not None for x in hdcps):
        info["HDCP"] = expand_row(hdcps, num_holes, "none")
    for name, yards in (tees_yards or []):
        if any(y is not None for y in yards):
            info[name] = expand_row(yards, num_holes, "sum")
    return pd.DataFrame(info).set_index("ホール").T


def _kana_key(s):
    """簡易あいうえお順キー：カタカナをひらがなに寄せて並べる"""
    out = []
    for ch in str(s):
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:  # カタカナ → ひらがな
            out.append(chr(o - 0x60))
        else:
            out.append(ch)
    return "".join(out)




# ===== ライブ観戦（QR共有）と LINE 速報 =====
def app_base_url():
    """観戦URLの土台になるアプリのURL。secrets → 楽天のReferer → 画面入力 の順。"""
    for name in ("APP_BASE_URL", "RAKUTEN_REFERER"):
        v = _secret_or_env(name, "app_base_url")
        if v:
            return v.rstrip("/")
    return ""


def live_id_for(play_date, course_name):
    """同じ日・同じコースなら常に同じ観戦IDになるようにする（再起動しても不変）。"""
    import hashlib
    seed = f"{play_date}|{course_name}".encode("utf-8")
    return hashlib.md5(seed).hexdigest()[:8]


def viewer_url(live_id):
    base = app_base_url()
    return f"{base}/?live={live_id}" if base else ""


def build_live_payload(live_id, play_date, course_name, selected_tee, pars,
                       num_holes, players, all_scores, entered_map, through,
                       standings):
    """観戦ページとLINE速報が使うスナップショットを作る。"""
    return {
        "live_id": live_id,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "date": str(play_date),
        "course_name": course_name,
        "tee": selected_tee,
        "pars": list(pars),
        "num_holes": num_holes,
        "through": int(through),
        "players": [{"name": n, "scores": list(all_scores[n]),
                     "entered": list(entered_map.get(n, []))} for n in players],
        "standings": standings,
    }


@st.fragment(run_every="10s")
def _live_view_body(live_id):
    """観戦ページの中身。10秒ごとにここだけ再実行して最新を取り込む。"""
    from data_manager import clear_cache
    clear_cache()
    payload = load_live(live_id)
    if not payload:
        st.info("まだデータがありません。ラウンドが始まるまでお待ちください。")
        st.caption("この画面は10秒ごとに自動で更新されます。")
        return

    pars = payload.get("pars") or []
    num_holes = payload.get("num_holes") or len(pars)
    through = int(payload.get("through") or 0)
    par_cut = sum(pars[:through])

    st.subheader(payload.get("course_name", ""))
    meta = [payload.get("date", "")]
    if payload.get("tee"):
        meta.append(f"ティー: {payload['tee']}")
    meta.append(f"スルー {through} / {num_holes} ホール")
    st.caption("　·　".join([m for m in meta if m]))

    rows = []
    for p in payload.get("players", []):
        sc = p.get("scores") or []
        ent = p.get("entered") or []
        row = {"名前": p.get("name", "")}
        for h in range(num_holes):
            row[str(h + 1)] = (str(sc[h]) if h < len(ent) and ent[h] else "—")
        if num_holes == 18:
            row["OUT"] = sum(sc[:9])
            row["IN"] = sum(sc[9:18])
        row["TOTAL"] = sum(sc[:through]) if through else 0
        row["対Par"] = f"{sum(sc[:through]) - par_cut:+d}" if through else "—"
        rows.append(row)
    par_row = {"名前": "Par"}
    for h in range(num_holes):
        par_row[str(h + 1)] = str(pars[h])
    if num_holes == 18:
        par_row["OUT"] = sum(pars[:9])
        par_row["IN"] = sum(pars[9:])
    par_row["TOTAL"] = sum(pars)
    par_row["対Par"] = ""
    st.dataframe(pd.DataFrame([par_row] + rows), use_container_width=True,
                 hide_index=True)

    labels = {"tate": "タテ", "yoko": "ヨコ", "olympic": "オリンピック",
              "point": "ポイントターニー"}
    st_d = payload.get("standings") or {}
    shown = [(labels[k], st_d[k]) for k in labels if st_d.get(k)]
    if shown:
        cols = st.columns(len(shown))
        for col, (lab, d) in zip(cols, shown):
            with col:
                order = sorted(d, key=lambda n: d[n], reverse=True)
                st.markdown(f"**{lab}**")
                st.dataframe(pd.DataFrame({
                    "順": [f"{i + 1}" for i in range(len(order))],
                    "名前": order,
                    "得点": [f"{d[n]:+d}" for n in order],
                }), use_container_width=True, hide_index=True)

    st.caption(f"最終更新 {payload.get('updated_at', '')}　"
               "／　この画面は10秒ごとに自動で更新されます。")


def render_live_viewer(live_id):
    """観戦専用ページ（?live=xxxx で開いたとき）。読むだけで編集はできない。"""
    st.title("⛳ ライブスコア")
    _live_view_body(live_id)


def render_live_share_settings(play_date, course_name, num_holes, n_players):
    """ライブ共有（QR）とLINE速報の設定。観戦URLとQRをここに出す。"""
    lid = live_id_for(play_date, course_name)
    url = viewer_url(lid)
    with st.expander("📣 ライブ共有・LINE速報", expanded=False):
        st.checkbox(
            "同伴者に途中経過を見せる（ライブ共有をON）", key="live_share_on",
            help="ONにすると、1ホール全員分の入力が終わるたびに"
                 "観戦ページの内容が更新されます。")

        if not url:
            st.warning(
                "観戦URLの土台になるアプリのURLが未設定です。"
                "secrets に APP_BASE_URL（例 https://xxxx.streamlit.app）を"
                "設定してください。ここでの入力はこのセッション限りです。")
            v = st.text_input("アプリのURL", value="",
                              placeholder="https://xxxx.streamlit.app",
                              key="app_base_url")
            if v:
                url = f"{v.rstrip('/')}/?live={lid}"

        if url:
            st.markdown("**観戦ページ（このQRを読んでもらう）**")
            c1, c2 = st.columns([1, 2])
            with c1:
                svg = live_share.qr_svg(url)
                if svg:
                    st.markdown(svg, unsafe_allow_html=True)
                else:
                    st.caption("QRの生成には segno が必要です"
                               "（requirements.txt に追加済み）。")
            with c2:
                st.code(url, language=None)
                st.caption("同伴者はこのページを開くだけです。"
                           "10秒ごとに自動更新され、編集はできません。"
                           "LINEの通数も消費しません。")

        st.divider()
        st.markdown("**LINE速報**")
        tok = _secret_or_env("LINE_CHANNEL_ACCESS_TOKEN", "line_token")
        to = _secret_or_env("LINE_TO", "line_to")
        if tok and to:
            st.caption("🔑 LINEの設定: 済み（secrets / 環境変数から読み込み）")
        else:
            miss = [n for n, v in (("チャネルアクセストークン", tok),
                                   ("送信先ID", to)) if not v]
            st.info("LINE速報は未設定です（" + " / ".join(miss) + "）。"
                    "secrets に LINE_CHANNEL_ACCESS_TOKEN と LINE_TO を"
                    "設定すると使えます。設定しなくても観戦ページは使えます。")

        mode = st.selectbox(
            "配信頻度", live_share.SEND_MODES, index=1, key="line_send_mode",
            help="LINEの無料枠は月200通で、グループ送信は人数分カウントされます。")
        units = live_share.estimate_units(mode, num_holes, n_players)
        if units:
            st.caption(f"このラウンドでの消費見込み: 約 **{units} 通**"
                       f"（{n_players}人 × {units // max(1, n_players)}回）。"
                       f"無料枠 月200通なら約 {200 // units} ラウンド分です。")
        return lid, url
    return lid, url


# ===== 特別ポイント（ドラコン・ニアピン・3パット） =====
def render_extra_points(players, num_holes, rule, key_prefix="ex", saved=None):
    """ドラコン・ニアピン・3パットの入力UI。

    ドラコン/ニアピンは1ホールにつき1人なので「ホール×誰が取ったか」で入力する。
    オリンピックのメダルとは**別枠**なので、同じホールでメダルと同時に成立する。
    3パットはローカルルールのため、パット数からの自動判定はせず手入力にする。

    Returns: (totals, per_hole, awards_by_hole, threeputt)
    """
    saved = saved or {}
    kp = key_prefix
    idx = [f"H{i + 1}" for i in range(num_holes)]
    opts = ["なし"] + list(players)

    st.markdown("**🏆 特別ポイント（ドラコン・ニアピン・3パット）**")
    st.caption(f"ドラコン={rule.get('ドラコン', 0)} / "
               f"ニアピン={rule.get('ニアピン', 0)} / "
               f"3パット={rule.get('3パット', 0)}　"
               "オリンピックのメダルとは別枠なので、同じホールで同時に成立します。")

    saved_aw = saved.get("awards_by_hole") or {}
    aw_data = {}
    for award in EXTRA_HOLE_AWARDS:
        col = ["なし"] * num_holes
        for h, who in (saved_aw.get(award) or {}).items():
            h = int(h)
            if 0 <= h < num_holes and who in players:
                col[h] = who
        aw_data[award] = col
    aw_edited = st.data_editor(
        pd.DataFrame(aw_data, index=idx), use_container_width=True,
        key=f"{kp}_awards_editor",
        column_config={a: st.column_config.SelectboxColumn(
            a, options=opts, required=True) for a in EXTRA_HOLE_AWARDS})

    awards_by_hole = {}
    for award in EXTRA_HOLE_AWARDS:
        awards_by_hole[award] = {
            h: who for h, who in enumerate(list(aw_edited[award]))
            if who and who != "なし"}

    with st.expander("3パットしたホール（手入力）"):
        saved_tp = saved.get("threeputt") or {}
        tp_data = {}
        for n in players:
            row = [bool(v) for v in (saved_tp.get(n) or [])]
            row += [False] * (num_holes - len(row))
            tp_data[n] = row[:num_holes]
        tp_edited = st.data_editor(
            pd.DataFrame(tp_data, index=idx), use_container_width=True,
            key=f"{kp}_threeputt_editor",
            column_config={n: st.column_config.CheckboxColumn(n, default=False)
                           for n in players})
        threeputt = {n: [bool(v) for v in list(tp_edited[n])] for n in players}

    totals, per_hole = extra_points(players, num_holes, rule,
                                    awards_by_hole, threeputt)
    return totals, per_hole, awards_by_hole, threeputt


# ===== ラスベガスのオプション（選択式） =====
def render_lasvegas_rule_options(num_holes, key_prefix="lv", saved=None):
    """ラスベガスのルール選択UI（プレーヤーが決まっていなくても表示できる）。

    ルールの出典: enjoy-golfer.com「ゴルフのラスベガスの計算方法を徹底解説！」
    既定はすべてOFF＝素のラスベガス（固定チーム・逆転なし）。
    """
    saved = saved or {}
    kp = key_prefix
    with st.expander("🎰 ラスベガスの設定（使うオプションだけ選ぶ）", expanded=True):
        st.caption("何も選ばなければ、素のラスベガス（固定チーム・"
                   "少ない方=10の位）で集計します。")
        c1, c2 = st.columns(2)
        with c1:
            rotate = st.checkbox(
                "3ホールごとにチームを入れ替える", key=f"{kp}_rotate",
                value=bool(saved.get("team_mode") == "3ホールごとに入れ替え"),
                help="打順(プレーヤー1〜4の並び)をもとに、1-3H は 1-2 vs 3-4、"
                     "4-6H は 1-3 vs 2-4、7-9H は 1-4 vs 2-3 …と回します。"
                     "OFFなら全ホール同じチーム（既定）。")
            birdie_reverse = st.checkbox(
                "バーディ逆転", key=f"{kp}_birdie_reverse",
                value=bool(saved.get("birdie_reverse")),
                help="自分のチームにバーディ以上が出ると、相手チームの数値が"
                     "ひっくり返ります（例: 相手 5と7 の 57 → 75）。")
        with c2:
            drop_ones = st.checkbox(
                "1の位切り捨て", key=f"{kp}_drop_ones",
                value=bool(saved.get("drop_ones")),
                help="チームの数値の1の位を切り捨てます（57→50、46→40）。")
            carry = st.checkbox(
                "キャリー", key=f"{kp}_carry", value=bool(saved.get("carry")),
                help="同点のホールは勝ち点ゼロで持ち越し、次のホールが2倍に"
                     "なります（連続で同点なら3倍…）。")

        st.markdown("**プッシュ（宣言したホールの勝ち点を倍にする）**")
        saved_push = {int(k): v for k, v in (saved.get("push_by_hole") or {}).items()}
        d2 = [h + 1 for h, v in saved_push.items() if v == 2]
        d4 = [h + 1 for h, v in saved_push.items() if v == 4]
        holes = list(range(1, num_holes + 1))
        k2, k4 = f"{kp}_push2", f"{kp}_push4"
        if k2 not in st.session_state and d2:
            st.session_state[k2] = d2
        if k4 not in st.session_state and d4:
            st.session_state[k4] = d4
        p2 = st.multiselect("2倍にするホール（1人が宣言）", holes, key=k2)
        p4 = st.multiselect("4倍にするホール（2人が宣言）", holes, key=k4)

    push_by_hole = {}
    for n in p2:
        push_by_hole[n - 1] = 2
    for n in p4:
        push_by_hole[n - 1] = 4  # 4倍が優先
    st.session_state[f"_{kp}_push"] = push_by_hole

    team_mode = "3ホールごとに入れ替え" if rotate else "固定"
    st.session_state[f"{kp}_team_mode"] = team_mode
    return {"team_mode": team_mode, "birdie_reverse": birdie_reverse,
            "drop_ones": drop_ones, "carry": carry,
            "push_by_hole": push_by_hole}


def render_lasvegas_team(names, team_mode, key_prefix="lv", saved=None):
    """チーム1の2人を選ぶUI。入れ替え方式のときは打順を案内するだけ。"""
    saved = saved or {}
    kp = key_prefix
    if team_mode != "固定":
        st.caption(f"打順: {' → '.join(names)}　"
                   "（3ホールごとに組み合わせが変わります）")
        return []
    t1_key = f"{kp}_team1"
    default_t1 = [n for n in (saved.get("team1") or []) if n in names]
    if t1_key not in st.session_state and len(default_t1) == 2:
        st.session_state[t1_key] = default_t1
    return st.multiselect("チーム1（2人選択）", names, key=t1_key,
                          max_selections=2)


def render_lasvegas_result(lv, team1, team2, team_mode, live=False):
    """ラスベガスの結果表示。チームを入れ替える方式では人別で見せる。"""
    bp = lv.get("by_player") or {}
    if team_mode == "固定" and len(team1) == 2 and len(team2) == 2:
        st.dataframe(pd.DataFrame({
            "チーム": [f"{team1[0]}＋{team1[1]}", f"{team2[0]}＋{team2[1]}"],
            "得点": [f"{lv['net1']:+d}", f"{lv['net2']:+d}"],
        }), use_container_width=True, hide_index=True)
        if live:
            lead = ("チーム1 リード" if lv["net1"] > 0 else
                    "チーム2 リード" if lv["net1"] < 0 else "同点")
            st.markdown(f"**{lead}**")
        else:
            win = ("チーム1の勝ち" if lv["net1"] > 0 else
                   "チーム2の勝ち" if lv["net1"] < 0 else "引き分け")
            st.markdown(f"### {win}")
    else:
        order = sorted(bp, key=lambda n: bp[n], reverse=True)
        st.caption("3ホールごとに組み合わせが変わるため、人ごとの合計で表示します。")
        st.dataframe(pd.DataFrame({
            "順": [f"{i + 1}" for i in range(len(order))],
            "名前": order,
            "得点": [f"{bp[n]:+d}" for n in order],
        }), use_container_width=True, hide_index=True)

    with st.expander("ホール別明細"):
        rows = []
        for d in lv["per_hole"]:
            mark = []
            if d.get("birdie1"):
                mark.append("T1バーディ")
            if d.get("birdie2"):
                mark.append("T2バーディ")
            rows.append({
                "H": d["hole"],
                "チーム1": "＋".join(d.get("t1") or []),
                "数値1": d["n1"],
                "チーム2": "＋".join(d.get("t2") or []),
                "数値2": d["n2"],
                "差": f"{d['diff']:+d}",
                "倍率": f"×{d.get('mult', 1)}",
                "得点": f"{d.get('gain', d['diff']):+d}",
                "備考": " / ".join(mark),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)


# ===== ホール単位のスコア入力（パー基準ボタン方式） =====
DIFF_LABELS = {-3: "アルバトロス", -2: "イーグル", -1: "バーディ", 0: "パー",
               1: "ボギー", 2: "ダボ", 3: "トリプル"}


def diff_label(diff):
    """パーとの差を日本語のスコア名にする。範囲外は ±N で返す。"""
    if diff in DIFF_LABELS:
        return DIFF_LABELS[diff]
    return f"+{diff}" if diff > 0 else str(diff)


def _sc_key(pi, h):
    return f"score_{pi}_{h}"


def _done_key(pi, h):
    return f"scored_{pi}_{h}"


def _pt_key(pi, h):
    return f"putt_{pi}_{h}"


def hole_candidates(par):
    """そのホールでボタンに出す打数（パー基準 −1〜+3、1打未満は出さない）。"""
    return [par + d for d in (-1, 0, 1, 2, 3) if par + d >= 1]


def render_hole_input(players, pars, num_holes, tee_yards, course_hdcps,
                      record_putts):
    """1ホールずつ、全員分をまとめて入力する画面を描く。

    以前はプレーヤーごとに18ホールを縦に並べていたため、1ホール入力するたびに
    画面を上下に往復する必要があった（3人なら1ホールにつき往復2回）。
    ここではホールを単位にして、全員分を1画面に収める。

    値は従来どおり session_state の score_{pi}_{h} に入れる（保存処理・ライブ集計は
    そのまま動く）。加えて scored_{pi}_{h} で「実際に入力したか」を持ち、
    未入力とパー入力を区別できるようにしている。

    Returns: (all_scores {name: [打数...]}, all_putts {name: [パット...] or []})
    """
    ss = st.session_state
    np_ = len(players)
    ss.setdefault("cur_hole", 0)
    if ss["cur_hole"] >= num_holes:
        ss["cur_hole"] = 0
    h = ss["cur_hole"]
    par = pars[h]

    def entered(pi, hh):
        return bool(ss.get(_done_key(pi, hh)))

    def value(pi, hh):
        v = ss.get(_sc_key(pi, hh))
        return int(v) if isinstance(v, (int, float)) else pars[hh]

    # --- ホール移動 ---
    n1, n2, n3 = st.columns([1, 3, 1])
    with n1:
        if st.button("◀ 前", use_container_width=True, disabled=(h == 0),
                     key="hole_prev"):
            ss["cur_hole"] = max(0, h - 1)
            st.rerun()
    with n2:
        bits = [f"### H{h + 1}", f"Par {par}"]
        y = tee_yards[h] if h < len(tee_yards) and tee_yards[h] else None
        if y:
            bits.append(f"{y}Y")
        hd = course_hdcps[h] if h < len(course_hdcps) and course_hdcps[h] else None
        if hd:
            bits.append(f"HDCP {hd}")
        st.markdown("　·　".join(bits))
    with n3:
        if st.button("次 ▶", use_container_width=True,
                     disabled=(h >= num_holes - 1), key="hole_next"):
            ss["cur_hole"] = min(num_holes - 1, h + 1)
            st.rerun()

    done_holes = sum(1 for hh in range(num_holes)
                     if all(entered(pi, hh) for pi in range(np_)))
    ss["_done_holes"] = done_holes
    st.progress(done_holes / num_holes,
                text=f"入力済み {done_holes} / {num_holes} ホール")

    # 【重要】この checkbox はプレーヤー行より前に描くこと。
    # 後ろに置くと、ボタンを押した回は st.rerun() で到達せず未描画になり、
    # Streamlit が widget 状態を破棄して OFF が保持されない。
    st.checkbox("全員入力したら自動で次のホールへ進む", value=True, key="auto_next")

    cands = hole_candidates(par)
    st.caption("　".join(f"**{n}**={diff_label(n - par)}" for n in cands)
               + "　／　それ以外は「…」")

    was_all = all(entered(pi, h) for pi in range(np_))
    changed = False

    for pi, name in enumerate(players):
        cur, ok = value(pi, h), entered(pi, h)
        cols = st.columns([2.2] + [1] * len(cands) + [0.9])
        with cols[0]:
            st.markdown(f"**{name}**")
            st.caption(f"{cur}（{diff_label(cur - par)}）" if ok else "未入力")
        for ci, n in enumerate(cands):
            with cols[ci + 1]:
                sel = ok and cur == n
                if st.button(str(n), key=f"scbtn_{pi}_{h}_{n}",
                             use_container_width=True,
                             type=("primary" if sel else "secondary")):
                    ss[_sc_key(pi, h)] = n
                    ss[_done_key(pi, h)] = True
                    ss.pop(f"otheropen_{pi}_{h}", None)
                    changed = True
        with cols[-1]:
            oth = f"otheropen_{pi}_{h}"
            is_other = ok and cur not in cands
            if st.button("…", key=f"othbtn_{pi}_{h}", use_container_width=True,
                         type=("primary" if is_other else "secondary"),
                         help="7打以上など、ボタンに無い打数を直接入力します"):
                ss[oth] = not ss.get(oth, False)
                st.rerun()
            if ss.get(oth):
                v = st.number_input("打数", min_value=1, max_value=20, value=cur,
                                    key=f"othnum_{pi}_{h}",
                                    label_visibility="collapsed")
                if int(v) != cur or not ok:
                    ss[_sc_key(pi, h)] = int(v)
                    ss[_done_key(pi, h)] = True

        if record_putts:
            pc = st.columns([2.2] + [1] * 5 + [0.9])
            with pc[0]:
                cur_pt = ss.get(_pt_key(pi, h))
                st.caption(f"パット {cur_pt}" if cur_pt else "パット 未入力")
            for ci, n in enumerate([1, 2, 3, 4, 5]):
                with pc[ci + 1]:
                    psel = ss.get(_pt_key(pi, h)) == n
                    if st.button(str(n), key=f"ptbtn_{pi}_{h}_{n}",
                                 use_container_width=True,
                                 type=("primary" if psel else "secondary")):
                        ss[_pt_key(pi, h)] = n
                        st.rerun()
        st.divider()

    # 全員そろった瞬間だけ、自動で次のホールへ進む（修正時は動かない）
    if changed:
        now_all = all(entered(pi, h) for pi in range(np_))
        if now_all and not was_all:
            # このホールが全員そろった、というできごとを記録しておく。
            # ライブ共有の保存とLINE速報は、集計が出そろう後段でまとめて行う。
            ss["_completed_hole"] = h + 1
        if (now_all and not was_all and h < num_holes - 1
                and ss.get("auto_next", True)):
            ss["cur_hole"] = h + 1
        st.rerun()

    # --- 値の組み立て（未入力ホールはParで埋める。集計側の従来動作に合わせる）---
    all_scores, all_putts = {}, {}
    for pi, name in enumerate(players):
        all_scores[name] = [value(pi, hh) for hh in range(num_holes)]
        all_putts[name] = ([int(ss.get(_pt_key(pi, hh)) or 2)
                            for hh in range(num_holes)] if record_putts else [])

    st.session_state["_entered_map"] = {
        name: [entered(pi, hh) for hh in range(num_holes)]
        for pi, name in enumerate(players)}

    # --- 一覧（確認・ホール移動）。畳むと現在地を見失うため常時表示にする ---
    st.markdown(f"##### 📋 全ホール一覧（入力済み {done_holes}/{num_holes}）")
    if True:
        rows = []
        for pi, name in enumerate(players):
            row = {"名前": name}
            for hh in range(num_holes):
                row[str(hh + 1)] = (str(value(pi, hh)) if entered(pi, hh) else "—")
            if num_holes == 18:
                row["OUT"] = sum(value(pi, hh) for hh in range(9))
                row["IN"] = sum(value(pi, hh) for hh in range(9, 18))
            row["TOTAL"] = sum(all_scores[name])
            rows.append(row)
        par_row = {"名前": "Par"}
        for hh in range(num_holes):
            par_row[str(hh + 1)] = str(pars[hh])
        if num_holes == 18:
            par_row["OUT"] = sum(pars[:9])
            par_row["IN"] = sum(pars[9:])
        par_row["TOTAL"] = sum(pars)
        st.dataframe(pd.DataFrame([par_row] + rows), use_container_width=True,
                     hide_index=True)
        st.caption("「—」は未入力です。合計にはParを仮置きして計算しています。")
        jump = st.selectbox("ホールへ移動", range(1, num_holes + 1),
                            index=h, key="hole_jump",
                            format_func=lambda n: f"H{n}（Par {pars[n - 1]}）")
        if st.button("このホールへ移動", key="hole_jump_go"):
            ss["cur_hole"] = jump - 1
            st.rerun()

    return all_scores, all_putts

st.set_page_config(
    page_title="ゴルフスコア集計",
    page_icon="⛳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* モバイル対応 */
    .stNumberInput > div > div > input { font-size: 18px; text-align: center; }
    .block-container { padding: 3rem 1rem 2rem 1rem; max-width: 100%; }
    header[data-testid="stHeader"] { height: 0; }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1.1rem !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 2px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 12px; font-size: 14px; }
</style>
""", unsafe_allow_html=True)

ensure_data_dir()

# データ保存先への接続診断（エラー内容を画面に表示する）
try:
    load_courses()
except Exception as e:
    st.error("データ保存先（Googleスプレッドシート等）への接続でエラーが発生しました。")
    detail = getattr(getattr(e, "response", None), "text", None) or str(e)
    st.code(detail)
    info = None
    try:
        from data_manager import _gsheets_conf
        conf = _gsheets_conf()
        if conf:
            sa, sid = conf
            st.caption(
                f"使用中のサービスアカウント: {sa.get('client_email')}\n"
                f"プロジェクト: {sa.get('project_id')}\n"
                f"シートID: {sid}"
            )
    except Exception:
        pass
    st.info("上のエラー内容と『使用中のサービスアカウント』を確認してください。"
            "・スプレッドシートをそのアカウントに『編集者』で共有しているか "
            "・Google Sheets APIが有効か をご確認ください。")
    st.stop()

# 観戦モード(?live=)ではこの見出しを出さない（観戦ページ側で自前の見出しを出す）
if not st.query_params.get("live"):
    st.title("⛳ ゴルフスコア集計")


def _ocr_api_key():
    """名刺アプリと同じ順でキーを取得：環境変数→secrets→サイドバー入力。
    キー値はこのコードに直書きしない。"""
    key = os.environ.get("OPENAI_API_KEY", "")
    try:
        key = key or st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass
    return key


def _render_image_ocr(course_name, course_pars, course_hdcps,
                      selected_tee, tee_yards, play_date):
    """ゴルフ場端末のスコア画面をOCRして18穴に流し込み、save_roundで保存する。
    既存のライブ入力フォームには一切触れない独立フロー。"""
    ss = st.session_state
    ss.setdefault("ocr_ver", 0)
    ss.setdefault("ocr_scores", [None] * 18)   # 18穴バッファ（int or None）
    ss.setdefault("ocr_halves", {})            # {"OUT":{names:[...],scores:[[..],..],detected}, "IN":{...}}
    ss.setdefault("ocr_names", [])             # 基準ハーフ(名前が多い方)の name_raw 一覧（列順）

    # キーは secrets / 環境変数 で設定するのが本筋。設定済みなら画面には出さない
    # （伏字でも肩越しに見える・セッションに残る・誤操作で消えるため）。
    default_key = _ocr_api_key()
    if default_key:
        st.caption("🔑 OpenAI APIキー: 設定済み（secrets / 環境変数から読み込み）")
        api_key = default_key
    else:
        st.warning("OpenAI APIキーが未設定です。"
                   "本来は .streamlit/secrets.toml か環境変数 OPENAI_API_KEY に "
                   "設定してください。ここでの入力はこのセッション限りの応急処置です。")
        api_key = st.text_input(
            "OpenAI API キー（応急）", value="", type="password", key="ocr_api_key")
    model = st.selectbox("モデル", ["gpt-5.5", "gpt-4o", "gpt-4o-mini"],
                         index=0, key="ocr_model",
                         help="既定は gpt-5.5。空返り等でうまく読めない時は gpt-4o に切替。")

    st.caption("スコア確認画面の画像をアップロードしてください（OUT/INをまとめて選択可・自動判別）。"
               "1枚だけでも読めます（残りは下の表で手入力）。")
    ups = st.file_uploader("スコア画像（1〜2枚）", type=["jpg", "jpeg", "png"],
                           accept_multiple_files=True, key="ocr_ups")

    def _bytes(x):
        return x.getvalue() if x is not None else None

    imgs = [_bytes(u) for u in (ups or []) if u is not None]

    if st.button("🔍 画像を読み取る", key="ocr_run"):
        if not (api_key or "").strip():
            st.warning("APIキーが未設定です（環境変数/secrets/この欄のいずれか）。")
        elif not imgs:
            st.warning("スコア画像を1枚以上アップロードしてください。")
        else:
            errors = []
            # 各画像をOCRし、OUT/INは half 表示・ホール番号(which_half)で自動判別する。
            parsed = []
            for b in imgs:
                if not b:
                    continue
                try:
                    data = ocr_score.ocr_screen(b, api_key, model=model)
                except Exception as e:
                    errors.append(f"読み取りエラー {e}")
                    continue
                parsed.append((data, ocr_score.which_half(data)))

            def _mk(data, det):
                players = data.get("players", []) or []
                return {
                    "names": [(p.get("name_raw") or "").strip() for p in players],
                    "scores": [p.get("scores") or [] for p in players],
                    "detected": det,
                }
            # 1周目: 判別できた画像を該当枠へ / 2周目: 残りを空き枠(OUT→IN)へ
            halves, leftover = {}, []
            for data, det in parsed:
                if det in ("OUT", "IN") and det not in halves:
                    halves[det] = _mk(data, det)
                else:
                    leftover.append((data, det))
            free = [h for h in ("OUT", "IN") if h not in halves]
            for (data, det), h in zip(leftover, free):
                halves[h] = _mk(data, det)

            # 基準ハーフ = (氏名数→列数) が最大の方（通常OUT）。列の並びと選択肢の氏名に使う。
            # 氏名が全く読めない画面でも列数で選び、空名は後で「プレーヤーN」表示にする。
            ref_names, ref_key = [], (-1, -1)
            for hp in halves.values():
                key = (len([n for n in hp["names"] if n]), len(hp["names"]))
                if key > ref_key:
                    ref_key, ref_names = key, hp["names"]
            ss.ocr_halves = halves
            ss.ocr_names = ref_names
            ss.ocr_ver += 1
            for e in errors:
                st.error(e)
            if halves:
                st.success(f"読み取り完了：{ '・'.join(halves.keys()) }（自動判別）。"
                           "下でプレーヤーを選び、内容を確認してください。")

    if not ss.ocr_names:
        return

    # OUT/INで検出したプレーヤー列数が食い違うと、氏名の無いハーフは列位置がずれる
    # （例: 片方だけPT列を1人と誤検出）。気付けるよう警告する。
    counts = {h: len(hp["scores"]) for h, hp in ss.ocr_halves.items()}
    if len(set(counts.values())) > 1:
        st.warning(f"OUT/INで検出したプレーヤー列数が違います {counts}。"
                   "氏名の無いハーフは列位置がずれる可能性があります。"
                   "下の🔧デバッグで各列を確認し、必要なら下の表で手修正してください。")

    # 読み取りデバッグ（画像ごとの生結果）— OUT/INが合わない時の原因切り分け用
    with st.expander("🔧 読み取りデバッグ（画像ごとの生結果）", expanded=False):
        for h, hp in ss.ocr_halves.items():
            det = hp.get("detected")
            warn = "" if (det is None or det == h) else f"　⚠ 検出={det}（枠と不一致）"
            st.markdown(f"**{h}枠**{warn}")
            rows = list(zip(hp["names"], hp["scores"]))
            if not rows:
                st.caption("　プレーヤーを検出できませんでした。")
            for i, (n, s) in enumerate(rows):
                st.text(f"  列{i+1}: 名前='{n}'  scores={s}")

    # ===== 全員をライブ入力フォームへ取り込む（途中経過・ゲーム状況を見る）=====
    st.markdown("**▼ ラウンド途中でも使えます**")
    st.caption("読み取った全員のスコアを下の入力フォームに取り込み、続きのホールをこのアプリで"
               "入力できます。取り込むと「📊 現在のゲーム状況（ライブ）」にラスベガス等の"
               "途中経過が出ます（スルー＝消化ホール数は自動設定）。")
    if st.button("▶ 全員をライブ入力に取り込んで続ける", key=f"ocr_to_live_{ss.ocr_ver}"):
        ref = ss.ocr_names
        n_cols = min(max((len(hp["scores"]) for hp in ss.ocr_halves.values()),
                         default=0), 4)
        # 各列(プレーヤー)の18穴スコアを OUT/IN から組み立てる
        cols_scores = []
        for j in range(n_cols):
            nm = ref[j] if j < len(ref) else ""
            s18 = [None] * 18
            for half, hp in ss.ocr_halves.items():
                sc = ocr_score.match_player_scores(hp["names"], hp["scores"], nm, j)
                ocr_score.merge_half_into(s18, half, sc)
            cols_scores.append((nm, s18))
        # 自分(hiroaki minowa)の列を先頭スロットへ
        my_name = (load_prefs() or {}).get("my_name") or "hiroaki minowa"

        def _is_me(nm):
            c = ocr_score.normalize_name(nm)
            return c is not None and c in (my_name, "hiroaki minowa")
        order = sorted(range(len(cols_scores)),
                       key=lambda j: (0 if _is_me(cols_scores[j][0]) else 1, j))
        roster = [cols_scores[j] for j in order]
        # スルー = 最後に埋まっているホール+1（途中でも可）
        filled = [h for _, s in roster for h in range(18) if isinstance(s[h], int)]
        through = (max(filled) + 1) if filled else 18
        # ライブ入力フォームの各ウィジェットを session_state で prefill する
        existing = set(get_all_player_names())
        st.session_state["num_players"] = len(roster) or 1
        for pi, (nm, s18) in enumerate(roster):
            canon = ocr_score.normalize_name(nm)
            disp_name = canon or nm or f"プレーヤー{pi+1}"
            if pi == 0:
                st.session_state["player_name_0"] = disp_name
            elif disp_name in existing:
                st.session_state[f"player_pick_{pi}"] = disp_name
            else:
                st.session_state[f"player_pick_{pi}"] = "＋ 新しい名前を入力"
                st.session_state[f"player_name_{pi}"] = disp_name
            for h in range(18):
                v = s18[h]
                st.session_state[f"score_{pi}_{h}"] = (
                    int(v) if isinstance(v, int) else int(course_pars[h]))
                # 読み取れたホールだけ「入力済み」にする（残りは未入力のまま）
                st.session_state[f"scored_{pi}_{h}"] = isinstance(v, int)
        st.session_state["live_through"] = min(max(through, 1), 18)
        ss.ocr_imported_msg = (
            f"{len(roster)}人・{through}ホールまでを下の入力フォームに取り込みました。"
            "続きのホールを入力し、「📊 現在のゲーム状況（ライブ）」で途中経過を確認できます。")
        st.rerun()

    st.divider()

    # プレーヤー選択（氏名自動一致で自分を既定に）。氏名が無い列は「プレーヤーN」表示。
    disp = [(n if n else f"プレーヤー{i+1}") for i, n in enumerate(ss.ocr_names)]
    prefs_name = (load_prefs() or {}).get("my_name")
    auto_idx = 0
    for i, nm in enumerate(ss.ocr_names):
        canon = ocr_score.normalize_name(nm)
        if canon and (canon == prefs_name or canon == "hiroaki minowa"):
            auto_idx = i
            break
    pick_idx = st.selectbox("登録するプレーヤー", list(range(len(disp))),
                            index=auto_idx, format_func=lambda i: disp[i],
                            key=f"ocr_pick_{ss.ocr_ver}")
    pick = ss.ocr_names[pick_idx]        # 生の表示名（名寄せ・保存名に使う）
    canon = ocr_score.normalize_name(pick)
    save_name = canon or (pick if pick else disp[pick_idx])
    if canon:
        st.caption(f"氏名一致：『{disp[pick_idx]}』→ {canon}")
    else:
        st.caption(f"『{disp[pick_idx]}』は既知の別名に未登録。この表示名のまま保存します。")

    # 選択プレーヤーのOUT/INを18穴バッファへ流し込み（既存の手入力は温存）。
    # 各ハーフとも「氏名一致→列位置(pick_idx)」で対応列を決める（match_player_scores）。
    buf = list(ss.ocr_scores)
    if all(v is None for v in buf) or ss.get("ocr_last_pick") != f"{ss.ocr_ver}:{pick_idx}":
        buf = [None] * 18
        for half, hp in ss.ocr_halves.items():
            sc = ocr_score.match_player_scores(hp["names"], hp["scores"],
                                               pick, pick_idx)
            ocr_score.merge_half_into(buf, half, sc)
        ss.ocr_scores = buf
        ss.ocr_last_pick = f"{ss.ocr_ver}:{pick_idx}"

    # 検算表示
    read = ss.ocr_scores
    out_sum = sum(s for s in read[:9] if isinstance(s, int))
    in_sum = sum(s for s in read[9:] if isinstance(s, int))
    out_n = sum(1 for s in read[:9] if isinstance(s, int))
    in_n = sum(1 for s in read[9:] if isinstance(s, int))
    st.caption(f"読み取り小計 — OUT {out_sum}（{out_n}/9）／IN {in_sum}（{in_n}/9）"
               f"／合計 {out_sum + in_sum}")

    # 編集テーブル（H1-18、空欄は手入力・誤読はここで修正）
    df = pd.DataFrame({
        "Par": course_pars,
        "スコア": [None if s is None else int(s) for s in read],
    }, index=[f"H{i+1}" for i in range(18)])
    edited = st.data_editor(
        df, key=f"ocr_editor_{ss.ocr_ver}_{pick_idx}", use_container_width=True,
        column_config={
            "Par": st.column_config.NumberColumn("Par", disabled=True),
            "スコア": st.column_config.NumberColumn("スコア", min_value=1,
                                                    max_value=20, step=1),
        })
    # 編集結果をバッファへ反映
    new_scores = []
    for v in edited["スコア"].tolist():
        new_scores.append(int(v) if pd.notna(v) else None)
    ss.ocr_scores = new_scores

    # 保存
    mode, final_scores, a, b = ocr_score.finalize_scores(new_scores)
    if mode == "invalid":
        st.info("空欄のホールがあります。18ホール全て、または片方のナイン（1-9 か 10-18）を"
                "すべて埋めると保存できます。")
        return
    label = {"full18": "18ホール", "out9": "OUT 9ホール", "in9": "IN 9ホール"}[mode]
    st.write(f"保存内容：**{save_name}** / {course_name} / {selected_tee or 'ティー未設定'}"
             f" / {play_date.isoformat()} / {label} / 合計 {sum(final_scores)}")
    if st.button("💾 この内容で保存", type="primary", key=f"ocr_save_{ss.ocr_ver}"):
        rec_pars = course_pars[a:b]
        rec_hdcps = (course_hdcps[a:b] if course_hdcps and len(course_hdcps) >= b
                     else None)
        round_data = {
            "date": play_date.isoformat(),
            "course_name": course_name,
            "pars": rec_pars,
            "hdcps": rec_hdcps,
            "tee": selected_tee,
            "yards": (tee_yards[a:b] if tee_yards and len(tee_yards) >= b else []),
            "num_holes": len(final_scores),
            "players": [{"name": save_name, "scores": final_scores, "putts": []}],
        }
        save_round(round_data)
        # 読み取り結果(halves/names)は保持し、同じ画像から別プレーヤーを続けて
        # 登録できるようにする。編集バッファだけ空にし、次に選んだ人で再マージさせる。
        ss.ocr_scores = [None] * 18
        ss.pop("ocr_last_pick", None)
        st.success(f"保存しました：{save_name} {course_name} 合計{sum(final_scores)}。"
                   "上の「登録するプレーヤー」で別の人を選べば続けて登録できます。")
        st.balloons()


# ===== 観戦モード =====
# URLに ?live=xxxx が付いていたら、読み取り専用の観戦ページだけを描いて終了する。
# 同伴者はQRを読むだけでここに来るので、編集用のタブは一切出さない。
# ここは暗証番号の対象外（読むだけなので、同伴者に手間をかけさせない）。
_live_param = st.query_params.get("live")
if _live_param:
    render_live_viewer(_live_param)
    st.stop()


# ===== 編集側の入口ロック =====
# 観戦ページを同伴者に見せるにはアプリを公開設定にする必要があるが、
# そうすると編集画面（保存・削除・名前変更）まで誰でも触れてしまう。
# secrets に APP_PIN があるときだけ、編集側に暗証番号をかける。
# 未設定なら今までどおり素通り＝この機能を使わない選択もできる。
_app_pin = get_app_pin()
if _app_pin and not st.session_state.get("_unlocked"):
    st.title("⛳ ゴルフスコア集計")
    st.caption("編集するには暗証番号が必要です。"
               "観戦ページ（QRから開くページ）は暗証番号なしで見られます。")
    _pin_in = st.text_input("暗証番号", type="password", key="pin_input")
    if _pin_in:
        if _pin_in.strip() == _app_pin:
            st.session_state["_unlocked"] = True
            st.rerun()
        else:
            st.error("暗証番号が違います。")
    st.stop()

tab1, tab2, tab5, tab3, tab4 = st.tabs(
    ["📝 スコア入力", "📊 集計・分析", "🎮 ゲーム集計",
     "⛳ コース管理", "📋 ラウンド履歴"]
)

# --- タブ1: スコア入力 ---
with tab1:
    st.header("スコア入力")

    courses = load_courses()
    course_names = [c["name"] for c in courses]

    if not course_names:
        st.warning("まず「コース管理」タブでゴルフ場を登録してください。")
    else:
        prefs = load_prefs()
        play_date = st.date_input("プレー日", value=date.today())

        # 検索欄と選択欄を分けていたが、selectbox 自体が入力での絞り込みに
        # 対応しているため二重だった。1つにまとめる。
        selected_course_name = st.selectbox(
            "⛳ ゴルフ場", course_names, key="score_course_select",
            help="欄をタップして名前の一部を入力すると絞り込めます（例: 霞）。")
        selected_course = next(c for c in courses if c["name"] == selected_course_name)
        pars = selected_course["pars"]
        num_holes = selected_course["holes"]
        course_hdcps = selected_course.get("hdcps") or []
        course_tees = selected_course.get("tees") or []

        # ティー選択：どのコースも初期はRegular（あれば）。無ければ前回ティー→先頭。
        selected_tee = None
        tee_yards = []
        if course_tees:
            reg = next((t for t in course_tees
                        if t.strip().lower() in ("regular", "レギュラー")), None)
            desired = reg or prefs.get("last_tee") or course_tees[0]
            course_changed = (st.session_state.get("_tee_course")
                              != selected_course_name)
            if (course_changed or "tee_select" not in st.session_state
                    or st.session_state.get("tee_select") not in course_tees):
                st.session_state["tee_select"] = (
                    desired if desired in course_tees else course_tees[0]
                )
            st.session_state["_tee_course"] = selected_course_name
            selected_tee = st.selectbox("ティー", course_tees, key="tee_select")
            tee_yards = selected_course["yards"].get(selected_tee, [])

        # コース情報（Par / HDCP / ヤード）の参照表
        with st.expander("📋 コース情報（Par・HDCP・ヤード）"):
            tees_yards = [(f"{selected_tee}(Y)", tee_yards)] if selected_tee else []
            st.dataframe(
                make_info_table(num_holes, pars, course_hdcps, tees_yards),
                use_container_width=True,
            )

        # ===== 📷 画像から入力（ゴルフ場端末のスコア画面をOCR） =====
        if num_holes == 18:
            with st.expander("📷 画像から入力（スコア画面を撮影/アップロード）"):
                _render_image_ocr(selected_course_name, pars, course_hdcps,
                                  selected_tee, tee_yards, play_date)
        _imp = st.session_state.pop("ocr_imported_msg", None)
        if _imp:
            st.success(_imp)

        # ===== ゲーム設定（コース選択の近く） =====
        st.subheader("🎮 ゲーム設定")
        if "live_games" not in st.session_state:
            st.session_state["live_games"] = prefs.get("games", ["タテ", "ヨコ"])
        games_sel = st.multiselect(
            "やるゲームを選択", GAME_OPTIONS,
            key="live_games",
            help="このグループでやるゲームだけ選んでください。選んだゲームだけ集計・表示します。",
        )

        with st.expander("📖 ゲームのルール（ガイド）"):
            for g in GAME_OPTIONS:
                st.markdown(GAME_GUIDE[g])
                st.markdown("---")

        # ベスト＆グロスの設定（選択時）
        bg_start, bg_birdie, bg_settle = "OUT", True, "18ホール通し"
        if "ベスト＆グロス" in games_sel:
            with st.expander("⛳ ベスト＆グロスの設定", expanded=True):
                bcol1, bcol2 = st.columns(2)
                with bcol1:
                    bg_start = st.radio("スタート", ["OUT", "IN"], horizontal=True,
                                        key="bg_start",
                                        help="ハンデホールのベスト/グロス交互の起点になります。")
                with bcol2:
                    bg_settle = st.radio("精算単位",
                                         ["18ホール通し", "ハーフ(9H)ごと"],
                                         key="bg_settle")
                bg_birdie = st.checkbox("バーディ賞を有効にする（実打バーディで+1点）",
                                        value=True, key="bg_birdie")

        # ラスベガスの設定（選択時）。プレーヤーが決まる前でも選べるよう
        # ここ（ゲーム設定の並び）に置く。チーム1の選択だけ後段で行う。
        lv_rules = {"team_mode": "固定", "birdie_reverse": False,
                    "drop_ones": False, "carry": False, "push_by_hole": {}}
        if "ラスベガス" in games_sel:
            lv_rules = render_lasvegas_rule_options(
                num_holes, key_prefix="lv", saved=prefs.get("lasvegas") or {})

        # 得点ルールのカスタマイズ
        _r = get_rules()
        with st.expander("⚙️ 得点ルールの設定（カスタマイズ）"):
            rc1, rc2 = st.columns(2)
            with rc1:
                tate_pt = st.number_input(
                    "タテ：1ストローク = 何点", min_value=1, max_value=100,
                    value=int(_r["tate_pt"]), key="rule_tate_pt")
            with rc2:
                yoko_pt = st.number_input(
                    "ヨコ：1ホール勝ち = 何点", min_value=1, max_value=100,
                    value=int(_r["yoko_pt"]), key="rule_yoko_pt")
            st.markdown("**オリンピックの配点**")
            oc = st.columns(5)
            olympic_rule = {}
            for col, medal in zip(oc, ["金", "銀", "銅", "鉄", "チップイン"]):
                with col:
                    olympic_rule[medal] = st.number_input(
                        medal, min_value=0, max_value=99,
                        value=int(_r["olympic"][medal]), key=f"rule_oly_{medal}")

            st.markdown("**特別ポイント（オリンピックとは別枠）**")
            _re = {**DEFAULT_RULES["extra"], **(_r.get("extra") or {})}
            ec = st.columns(3)
            extra_rule = {}
            for col, (k, hlp) in zip(ec, [
                    ("ドラコン", "そのホールで一番飛んだ人"),
                    ("ニアピン", "そのホールでピンに一番近い人"),
                    ("3パット", "3パット以上した人（ローカルルール。手入力）")]):
                with col:
                    extra_rule[k] = st.number_input(
                        k, min_value=-99, max_value=99,
                        value=int(_re[k]), key=f"rule_ex_{k}", help=hlp)

            st.markdown("**ポイントターニーの配点（パーとの差）**")
            pc = st.columns(5)
            point_labels = [("eagle", "イーグル以上"), ("birdie", "バーディ"),
                            ("par", "パー"), ("bogey", "ボギー"),
                            ("double", "ダブル以上")]
            point_rule = {}
            for col, (k, lab) in zip(pc, point_labels):
                with col:
                    point_rule[k] = st.number_input(
                        lab, min_value=-10, max_value=99,
                        value=int(_r["point"][k]), key=f"rule_pt_{k}")

            current_rules = {"tate_pt": tate_pt, "yoko_pt": yoko_pt,
                             "olympic": olympic_rule, "point": point_rule,
                             "extra": extra_rule}
            if st.button("💾 このルールを保存（次回も使う）", key="save_rules"):
                update_prefs(rules=current_rules)
                st.success("得点ルールを保存しました。")

        current_rules = {
            "tate_pt": st.session_state.get("rule_tate_pt", _r["tate_pt"]),
            "yoko_pt": st.session_state.get("rule_yoko_pt", _r["yoko_pt"]),
            "olympic": {m: st.session_state.get(f"rule_oly_{m}", _r["olympic"][m])
                        for m in ["金", "銀", "銅", "鉄", "チップイン"]},
            "point": {k: st.session_state.get(f"rule_pt_{k}", _r["point"][k])
                      for k in ["eagle", "birdie", "par", "bogey", "double"]},
            "extra": {k: st.session_state.get(
                f"rule_ex_{k}",
                {**DEFAULT_RULES["extra"], **(_r.get("extra") or {})}[k])
                for k in ["ドラコン", "ニアピン", "3パット"]},
        }

        # パット数を記録するか（早い段階で確認）
        if "record_putts" not in st.session_state:
            st.session_state["record_putts"] = bool(prefs.get("record_putts", False))
        record_putts = st.checkbox(
            "🟢 パット数も記録する", key="record_putts",
            help="ONにすると、各ホールのスコアのすぐ下にパット入力欄が出ます。")

        st.subheader("プレーヤー設定")
        existing_players = get_all_player_names()
        _live_id_hint = live_id_for(play_date, selected_course_name)

        # 自分の名前は前回を記憶（次回以降は自動入力）
        if "player_name_0" not in st.session_state:
            st.session_state["player_name_0"] = prefs.get("my_name", "")

        num_players = st.radio("プレーヤー数", [1, 2, 3, 4], horizontal=True,
                               key="num_players")

        NEW_OPT = "＋ 新しい名前を入力"
        # 既存プレーヤーは あいうえお順（かな優先）に並べる
        sorted_players = sorted(existing_players, key=_kana_key)

        players = []
        for i in range(num_players):
            if i == 0:
                name = st.text_input("自分の名前", key="player_name_0")
            else:
                label = f"プレーヤー{i + 1}"
                if sorted_players:
                    opts = sorted_players + [NEW_OPT]
                    pick = st.selectbox(
                        f"{label}", opts, index=len(opts) - 1,
                        key=f"player_pick_{i}",
                        placeholder="名前を入力して検索 / 選択",
                        help="一覧から選ぶか、入力すると候補が絞り込まれます。",
                    )
                    if pick == NEW_OPT:
                        name = st.text_input(f"{label}の名前を入力",
                                             key=f"player_name_{i}")
                    else:
                        name = pick
                else:
                    name = st.text_input(f"{label}の名前", key=f"player_name_{i}")
            players.append(name)

        live_id, live_url = render_live_share_settings(
            play_date, selected_course_name, num_holes, max(1, len(players)))

        if all(players):
            st.subheader("スコア入力")

            # ===== ホール単位の入力 =====
            # 以前はプレーヤーごとに18ホールを縦に並べていたため、1ホール入力する
            # たびに画面を上下に往復する必要があった。ホール単位に組み替えている。
            all_scores, all_putts = render_hole_input(
                players, pars, num_holes, tee_yards, course_hdcps, record_putts)

            # ===== ライブ・ゲーム集計（入力しながら途中経過を表示） =====
            # 保存処理でも参照するため、人数に関わらず既定値を用意しておく
            live_olympic = None
            live_standings = {}   # ライブ共有・LINE速報に渡す各ゲームの順位
            live_extra = None
            ex_awards, ex_threeputt = {}, {}
            medals = {}
            hcap_games = []
            raw_hdcp = {n: 0 for n in players}
            ty_handicaps = {n: 0 for n in players}
            bg_player_hdcps = None
            bg_override = None
            st.subheader("📊 現在のゲーム状況（ライブ）")
            st.caption("※ ゲームの種類・得点ルールは上の「🎮 ゲーム設定」で変更できます。")

            # スルー（集計対象ホール数）は、全員そろって入力できているホール数に
            # 自動追従させる。手で変えたいときだけ切り替える。
            auto_done = int(st.session_state.get("_done_holes", 0))
            manual_through = st.checkbox(
                "集計対象ホール数を手動で指定する", key="through_manual",
                help="既定は「全員のスコアが入力済みのホール数」に自動追従します。")
            if manual_through:
                through = st.number_input(
                    "集計対象ホール数（スルー）", min_value=1, max_value=num_holes,
                    value=max(1, auto_done or num_holes), key="live_through",
                    help="未入力ホールはParのまま計算されます。")
            else:
                through = max(1, auto_done)
                st.caption(f"集計対象: スルー **{through}** ホール"
                           f"（全員入力済みのホール数に自動追従）")

            if len(players) >= 2:
                live_players = [
                    {"name": n, "scores": all_scores[n][:through]} for n in players
                ]

                if not games_sel:
                    st.info("上の「🎮 ゲーム設定」でゲームを選ぶと、ここに途中経過が出ます。")

                # ===== 共通ハンデ設定（タテ/ヨコ/ベスト＆グロス） =====
                raw_hdcp = {n: 0 for n in players}     # B&G用（生のHDCP）
                ty_handicaps = {n: 0 for n in players}  # タテ/ヨコ用（打数）
                hcap_games = [g for g in games_sel
                              if g in ("タテ", "ヨコ", "ベスト＆グロス")]
                if hcap_games:
                    saved_ph = prefs.get("player_hdcps", {})
                    with st.expander("⛳ ハンデ設定（タテ/ヨコ/ベスト＆グロス共通）",
                                     expanded=True):
                        hmode = st.radio(
                            "ハンデの決め方",
                            ["HDCPを入力して自動", "手動で設定", "ハンデなし"],
                            index=2, key="hcap_mode", horizontal=True,
                            help="既定は「ハンデなし」。ハンデ戦のときだけ左の2つに切り替えてください。")
                        if hmode == "ハンデなし":
                            st.caption("全員ハンデ0（グロスのまま）で集計します。")
                        if hmode != "ハンデなし":
                            hc = st.columns(len(players))
                            for col, n in zip(hc, players):
                                with col:
                                    raw_hdcp[n] = st.number_input(
                                        f"{n}", min_value=0, max_value=54,
                                        value=int(saved_ph.get(n, 0)),
                                        key=f"hcap_{n}")
                            if hmode == "HDCPを入力して自動":
                                ty_handicaps = dict(raw_hdcp)
                                st.caption("各自のHDCPをそのままフルでハンデ（打）として"
                                           "使います（スクラッチ基準）。")
                            else:
                                ty_handicaps = dict(raw_hdcp)
                                st.caption("入力した打数をそのままハンデとして使います"
                                           "（タテ/ヨコ）。")
                            if "ヨコ" in games_sel and (
                                    not course_hdcps or not any(course_hdcps)):
                                st.warning("ヨコのハンデ配分にはコースHDCPが必要です。"
                                           "「コース管理」で設定してください。")

                # タテ / ヨコ を選択分だけ横並びで表示
                stroke_games = [g for g in games_sel if g in ("タテ", "ヨコ")]
                if stroke_games:
                    cols = st.columns(len(stroke_games))
                    for col, g in zip(cols, stroke_games):
                        with col:
                            if g == "タテ":
                                st.markdown(f"**タテ**（1打={current_rules['tate_pt']}点）")
                                g_tot, nt_tot, t_net, _ = tate_results(
                                    live_players, current_rules["tate_pt"],
                                    ty_handicaps)
                                live_standings["tate"] = dict(t_net)
                                t_order = sorted(players, key=lambda n: nt_tot[n])
                                st.dataframe(pd.DataFrame({
                                    "順": [f"{i+1}" for i in range(len(t_order))],
                                    "名前": t_order,
                                    "グロス": [g_tot[n] for n in t_order],
                                    "ネット": [nt_tot[n] for n in t_order],
                                    "得点": [f"{t_net[n]:+d}" for n in t_order],
                                }), use_container_width=True, hide_index=True)
                            else:
                                st.markdown(f"**ヨコ**（1勝={current_rules['yoko_pt']}点）")
                                y_won, _, y_net = yoko_results(
                                    live_players, through, current_rules["yoko_pt"],
                                    ty_handicaps, course_hdcps)
                                live_standings["yoko"] = dict(y_net)
                                y_order = sorted(players,
                                                 key=lambda n: y_net[n], reverse=True)
                                st.dataframe(pd.DataFrame({
                                    "順": [f"{i+1}" for i in range(len(y_order))],
                                    "名前": y_order,
                                    "勝H": [y_won[n] for n in y_order],
                                    "得点": [f"{y_net[n]:+d}" for n in y_order],
                                }), use_container_width=True, hide_index=True)

                # オリンピック（選択時のみ：メダルで入力 → 配点で集計）
                if "オリンピック" in games_sel:
                    oru = current_rules["olympic"]
                    st.markdown("**🏅 オリンピック**")
                    st.caption(
                        f"金={oru['金']} / 銀={oru['銀']} / 銅={oru['銅']} / "
                        f"鉄={oru['鉄']} / チップイン={oru['チップイン']} / なし=0　"
                        "（各セルでメダルを選択）"
                    )
                    oly_data = {n: ["なし"] * num_holes for n in players}
                    oly_df = pd.DataFrame(
                        oly_data, index=[f"H{i+1}" for i in range(num_holes)])
                    oly_edited = st.data_editor(
                        oly_df, use_container_width=True, key="live_olympic_editor",
                        column_config={
                            n: st.column_config.SelectboxColumn(
                                n, options=OLYMPIC_MEDALS, required=True)
                            for n in players
                        },
                    )
                    medals = {n: list(oly_edited[n]) for n in players}
                    live_olympic = olympic_points_from_medals(medals, oru)
                    o_tot = {n: sum(live_olympic[n][:through]) for n in players}

                    ex_rule = current_rules.get("extra") or DEFAULT_RULES["extra"]
                    (ex_tot, live_extra, ex_awards,
                     ex_threeputt) = render_extra_points(
                        players, num_holes, ex_rule, key_prefix="ex")
                    ex_tot = {n: sum(live_extra[n][:through]) for n in players}

                    tot_all = {n: o_tot[n] + ex_tot.get(n, 0) for n in players}
                    live_standings["olympic"] = dict(tot_all)
                    o_order = sorted(players, key=lambda n: tot_all[n],
                                     reverse=True)
                    st.dataframe(pd.DataFrame({
                        "順": [f"{i+1}" for i in range(len(o_order))],
                        "名前": o_order,
                        "メダル": [o_tot[n] for n in o_order],
                        "特別": [f"{ex_tot.get(n, 0):+d}" for n in o_order],
                        "合計": [tot_all[n] for n in o_order],
                    }), use_container_width=True, hide_index=True)

                # ベスト＆グロス（4人チーム戦）
                bg_player_hdcps = None
                bg_override = None
                if "ベスト＆グロス" in games_sel:
                    st.markdown("**⛳ ベスト＆グロス**")
                    if len(players) != 4:
                        st.warning("ベスト＆グロスは4人ちょうどで行います。")
                    elif not course_hdcps or not any(course_hdcps):
                        st.warning("このコースのHDCP（ハンデ順）が未設定です。"
                                   "「コース管理」でHDCPを入力してください。")
                    else:
                        bg_player_hdcps = dict(raw_hdcp)
                        # 手動でチーム・ハンデを指定（任意）
                        bg_manual = st.checkbox("チーム・ハンデを手動で指定する",
                                                key="bg_manual")
                        if bg_manual:
                            mteamA = st.multiselect("Aチーム（2人選択）", players,
                                                    max_selections=2,
                                                    key="bg_manual_teamA")
                            if len(mteamA) == 2:
                                mteamB = [n for n in players if n not in mteamA]
                                mc1, mc2 = st.columns(2)
                                with mc1:
                                    mhi = st.radio("ハンデをもらうチーム",
                                                   ["Aチーム", "Bチーム"], key="bg_manual_hi")
                                with mc2:
                                    mN = st.number_input("ハンデ数（ホール）",
                                                         min_value=0, max_value=18,
                                                         value=0, key="bg_manual_N")
                                bg_override = {
                                    "teamA": mteamA, "teamB": mteamB,
                                    "hi_team": "A" if mhi == "Aチーム" else "B",
                                    "N": int(mN)}
                            else:
                                st.info("Aチームを2人選んでください。")

                        bg = best_and_gross(
                            {n: all_scores[n] for n in players}, pars,
                            course_hdcps, bg_player_hdcps, start=bg_start,
                            birdie_bonus=bg_birdie, num_holes=num_holes,
                            played_count=through, override=bg_override)
                        A_t, B_t = bg["teamA"], bg["teamB"]
                        hi_name = "A" if bg["hi_team"] == "A" else "B"
                        st.caption(
                            f"Aチーム: {A_t[0]}＋{A_t[1]}（HDCP計{bg['sumA']}）／ "
                            f"Bチーム: {B_t[0]}＋{B_t[1]}（HDCP計{bg['sumB']}）／ "
                            f"ハンデ: {hi_name}チームが{bg['N']}ホール")
                        if bg_settle.startswith("ハーフ"):
                            res_df = pd.DataFrame({
                                "チーム": ["Aチーム", "Bチーム"],
                                "前半": [bg["front"]["A"], bg["front"]["B"]],
                                "後半": [bg["back"]["A"], bg["back"]["B"]],
                                "合計": [bg["totals"]["A"], bg["totals"]["B"]],
                            })
                        else:
                            res_df = pd.DataFrame({
                                "チーム": ["Aチーム", "Bチーム"],
                                "得点": [bg["totals"]["A"], bg["totals"]["B"]],
                            })
                        st.dataframe(res_df, use_container_width=True,
                                     hide_index=True)
                        ta, tb = bg["totals"]["A"], bg["totals"]["B"]
                        lead = ("🅰 Aチーム リード" if ta > tb else
                                "🅱 Bチーム リード" if tb > ta else "同点")
                        st.markdown(f"**{lead}**（A {ta} - {tb} B）")
                        with st.expander("ホール別明細"):
                            tmap = {"best": "ベスト", "gross": "グロス", None: "—"}
                            rows = [{
                                "H": d["hole"],
                                "ハンデ": tmap[d["htype"]],
                                "Aベ/合": f"{d['A_best']}/{d['A_gross']}",
                                "Bベ/合": f"{d['B_best']}/{d['B_gross']}",
                                "A点": d["ptsA"], "B点": d["ptsB"],
                                "B賞": "○" if d["birdie"] else "",
                            } for d in bg["per_hole"]]
                            st.dataframe(pd.DataFrame(rows),
                                         use_container_width=True, hide_index=True)

                # ポイントターニー（個人戦）
                if "ポイントターニー" in games_sel:
                    st.markdown("**🎯 ポイントターニー**")
                    pr = current_rules["point"]
                    pt_tot, _ = point_tourney_results(
                        [{"name": n, "scores": all_scores[n]} for n in players],
                        pars, pr, num_holes=num_holes, played_count=through)
                    live_standings["point"] = dict(pt_tot)
                    pt_order = sorted(players, key=lambda n: pt_tot[n], reverse=True)
                    st.dataframe(pd.DataFrame({
                        "順": [f"{i+1}" for i in range(len(pt_order))],
                        "名前": pt_order,
                        "得点": [pt_tot[n] for n in pt_order],
                    }), use_container_width=True, hide_index=True)

                # ラスベガス（2対2）
                if "ラスベガス" in games_sel:
                    st.markdown("**🎰 ラスベガス**")
                    if len(players) != 4:
                        st.warning(f"ラスベガスは4人ちょうどで行います"
                                   f"（現在 {len(players)}人）。"
                                   "ルールの選択は上の「🎰 ラスベガスの設定」でできます。")
                    else:
                        lv_t1 = render_lasvegas_team(
                            players, lv_rules["team_mode"], key_prefix="lv",
                            saved=prefs.get("lasvegas") or {})
                        if lv_rules["team_mode"] == "固定" and len(lv_t1) != 2:
                            st.info("チーム1のメンバーを2人選んでください。"
                                    "（オプションは上の「🎰 ラスベガスの設定」です）")
                        else:
                            lv_t2 = [n for n in players if n not in lv_t1]
                            lv = las_vegas_results(
                                lv_t1, lv_t2, {n: all_scores[n] for n in players},
                                num_holes=num_holes, played_count=through,
                                pars=pars, players=players,
                                team_mode=lv_rules["team_mode"],
                                birdie_reverse=lv_rules["birdie_reverse"],
                                drop_ones=lv_rules["drop_ones"],
                                carry=lv_rules["carry"],
                                push_by_hole=lv_rules["push_by_hole"])
                            render_lasvegas_result(lv, lv_t1, lv_t2,
                                                   lv_rules["team_mode"],
                                                   live=True)
            else:
                # 1人プレーは対パーの状況のみ
                me = players[0]
                cur = sum(all_scores[me][:through])
                par_cur = sum(pars[:through])
                st.metric(f"{me} スルー{through}H",
                          f"{cur} (Par {par_cur})", f"{cur - par_cur:+d}")
                st.caption("ゲーム集計（タテ/ヨコ/オリンピック）は2人以上で表示されます。")

            # ===== ライブ共有の保存と LINE 速報 =====
            _entered = st.session_state.get("_entered_map") or {}
            live_payload = build_live_payload(
                live_id, play_date, selected_course_name, selected_tee, pars,
                num_holes, players, all_scores, _entered, through,
                live_standings)
            _done_hole = st.session_state.pop("_completed_hole", None)
            _line_tok = _secret_or_env("LINE_CHANNEL_ACCESS_TOKEN", "line_token")
            _line_to = _secret_or_env("LINE_TO", "line_to")

            if st.session_state.get("live_share_on") and _done_hole:
                try:
                    save_live(live_id, live_payload)
                except Exception as e:
                    st.warning(f"ライブ共有の保存に失敗しました: {e}")
                _mode = st.session_state.get("line_send_mode",
                                             live_share.SEND_MODES[1])
                _sent = st.session_state.setdefault("_line_sent", set())
                if (_done_hole in live_share.milestones(_mode, num_holes)
                        and _done_hole not in _sent):
                    ok, msg = live_share.line_push(
                        _line_tok, _line_to,
                        live_share.flash_text(live_payload, _done_hole,
                                              live_url))
                    if ok:
                        _sent.add(_done_hole)
                        st.success(f"LINEに速報を送りました（{_done_hole}H）")
                    else:
                        st.warning(f"LINE速報を送れませんでした: {msg}")

            if st.session_state.get("live_share_on") or (_line_tok and _line_to):
                mc1, mc2 = st.columns(2)
                with mc1:
                    if st.button("🔄 観戦ページをいま更新する",
                                 use_container_width=True, key="live_push_now"):
                        try:
                            save_live(live_id, live_payload)
                            st.success("観戦ページを更新しました。")
                        except Exception as e:
                            st.error(f"更新に失敗しました: {e}")
                with mc2:
                    if st.button("📣 いまの状況をLINEに送る",
                                 use_container_width=True, key="line_push_now"):
                        ok, msg = live_share.line_push(
                            _line_tok, _line_to,
                            live_share.flash_text(live_payload, through,
                                                  live_url))
                        (st.success if ok else st.error)(msg)

            st.divider()
            if st.button("💾 スコアを保存", type="primary", use_container_width=True):
                round_data = {
                    "date": play_date.isoformat(),
                    "course_name": selected_course_name,
                    "pars": pars,
                    "hdcps": course_hdcps,
                    "tee": selected_tee,
                    "yards": tee_yards,
                    "num_holes": num_holes,
                    "players": [
                        {"name": name,
                         "scores": all_scores[name],
                         "putts": all_putts[name]}
                        for name in players
                    ],
                }
                round_data["games"] = games_sel
                round_data["rules"] = current_rules
                if live_olympic and "オリンピック" in games_sel:
                    round_data["olympic"] = live_olympic
                    round_data["olympic_medals"] = {n: medals[n] for n in players}
                    round_data["extra"] = live_extra
                    round_data["extra_awards"] = {
                        a: {str(h): w for h, w in (ex_awards.get(a) or {}).items()}
                        for a in EXTRA_HOLE_AWARDS}
                    round_data["extra_threeputt"] = ex_threeputt
                # ハンデ情報（タテ/ヨコ/B&G共通）
                if hcap_games:
                    round_data["hcap_mode"] = st.session_state.get("hcap_mode")
                    round_data["raw_hdcp"] = raw_hdcp
                    round_data["ty_handicaps"] = ty_handicaps
                if "ベスト＆グロス" in games_sel and bg_player_hdcps:
                    round_data["bg"] = {
                        "player_hdcps": bg_player_hdcps,
                        "start": bg_start,
                        "birdie_bonus": bg_birdie,
                        "settle": bg_settle,
                        "override": bg_override,
                    }
                lv_t1 = st.session_state.get("lv_team1") or []
                if "ラスベガス" in games_sel and len(players) == 4:
                    round_data["lasvegas"] = {
                        "team1": lv_t1,
                        "team_mode": st.session_state.get("lv_team_mode", "固定"),
                        "birdie_reverse": bool(
                            st.session_state.get("lv_birdie_reverse")),
                        "drop_ones": bool(st.session_state.get("lv_drop_ones")),
                        "carry": bool(st.session_state.get("lv_carry")),
                        "push_by_hole": {
                            str(k): v for k, v in
                            (st.session_state.get("_lv_push") or {}).items()},
                    }
                save_round(round_data)
                # 次回のために自分の名前・ティー・やるゲーム・ルール・HDCPを記憶
                _pref_kwargs = dict(my_name=players[0], last_tee=selected_tee,
                                    games=games_sel, rules=current_rules,
                                    record_putts=record_putts)
                if "ラスベガス" in games_sel:
                    _pref_kwargs["lasvegas"] = {
                        "team1": st.session_state.get("lv_team1") or [],
                        "team_mode": lv_rules["team_mode"],
                        "birdie_reverse": lv_rules["birdie_reverse"],
                        "drop_ones": lv_rules["drop_ones"],
                        "carry": lv_rules["carry"],
                        "push_by_hole": {str(k): v for k, v
                                         in lv_rules["push_by_hole"].items()},
                    }
                if hcap_games and any(raw_hdcp.values()):
                    saved_ph = dict(prefs.get("player_hdcps", {}))
                    saved_ph.update(raw_hdcp)
                    _pref_kwargs["player_hdcps"] = saved_ph
                update_prefs(**_pref_kwargs)
                if (st.session_state.get("live_share_on")
                        and _line_tok and _line_to
                        and st.session_state.get("line_send_mode")
                        != live_share.SEND_MODES[0]):
                    ok, msg = live_share.line_push(
                        _line_tok, _line_to,
                        live_share.flash_text(live_payload, num_holes, live_url))
                    if not ok:
                        st.warning(f"最終結果のLINE送信に失敗: {msg}")
                st.success("スコアを保存しました！")
                st.balloons()
        else:
            st.info("全プレーヤーの名前を入力してください。")

# --- 集計・分析タブ用ヘルパー（直近Nラウンド窓・HDCP対応）---
def _sorted_player_course_rounds(rounds, player_name, course_name=None):
    """指定プレーヤー（任意でコース）のラウンドを日付降順で返す。"""
    out = []
    for r in rounds:
        if course_name is not None and r.get("course_name") != course_name:
            continue
        if any(p["name"] == player_name for p in r["players"]):
            out.append(r)
    out.sort(key=lambda r: (str(r.get("date", "")), r.get("id", 0)), reverse=True)
    return out


def windowed_course_averages(rounds, player_name, last_n):
    """コース別に、直近 last_n ラウンドの平均スコア・ベスト・使用/総ラウンド数。"""
    by_course = {}
    for r in rounds:
        for p in r["players"]:
            if p["name"] == player_name:
                by_course.setdefault(r["course_name"], []).append(
                    (str(r.get("date", "")), r.get("id", 0), sum(p["scores"])))
                break
    result = []
    for course, items in by_course.items():
        items.sort(key=lambda x: (x[0], x[1]), reverse=True)
        window = items[:last_n]
        totals = [t for _, _, t in window]
        result.append({
            "course": course,
            "avg": round(sum(totals) / len(totals), 1),
            "best": min(totals),
            "used": len(window),
            "total": len(items),
        })
    return sorted(result, key=lambda x: x["course"])


def windowed_hole_averages(rounds, player_name, course_name, last_n, hdcps=None):
    """指定コースの直近 last_n ラウンドでのホール別平均。HDCPはcoursesマスタ由来。
    Returns: (per_hole list, 使用ラウンド数, 総ラウンド数)"""
    plays = _sorted_player_course_rounds(rounds, player_name, course_name)
    total = len(plays)
    window = plays[:last_n]
    pars_ref = window[0].get("pars", []) if window else []
    hole_scores = {}
    for r in window:
        for p in r["players"]:
            if p["name"] == player_name:
                for i, s in enumerate(p["scores"]):
                    hole_scores.setdefault(i, []).append(s)
                break
    result = []
    for i in sorted(hole_scores.keys()):
        sc = hole_scores[i]
        par = pars_ref[i] if i < len(pars_ref) else None
        hd = hdcps[i] if (hdcps and i < len(hdcps)) else None
        result.append({
            "hole": i + 1, "par": par, "hdcp": hd,
            "avg_score": round(sum(sc) / len(sc), 1),
            "min_score": min(sc), "max_score": max(sc), "count": len(sc),
        })
    return result, len(window), total


def course_hdcps_lookup():
    """coursesマスタ name -> hdcps配列。"""
    out = {}
    for c in load_courses():
        out[c.get("name")] = c.get("hdcps")
    return out


# ========== 近似ハンディキャップインデックス（HI）==========
# CR/SR/Par/HDCP が分かるコース・ティーだけを対象に、SDから近似HIを算出する。
# 【拡張方法】他コースを増やすには HI_RATINGS に (コース名, ティー) の行を足すだけ。
#   例: ("三好カントリー倶楽部 東コース", "レギュラー"): {"cr":.., "sr":.., "par":.., "hdcp":[..18..]}
# 近似の限界: PCC=0固定・調整スコアは反復近似・対象ティー以外は除外。J-SYS正式値とは一致しない。
_KE_HDCP = [9, 15, 3, 13, 1, 7, 11, 17, 5, 16, 10, 4, 14, 2, 8, 12, 18, 6]   # 霞東
_KW_HDCP = [9, 15, 3, 13, 7, 1, 11, 5, 17, 10, 16, 4, 8, 14, 2, 12, 6, 18]   # 霞西
HI_RATINGS = {
    ("霞ヶ関CC 東/東", "ブルー"): {"cr": 70.6, "sr": 126, "par": 71, "hdcp": _KE_HDCP},
    ("霞ヶ関CC 西/西", "ブルー"): {"cr": 71.6, "sr": 130, "par": 73, "hdcp": _KW_HDCP},
}
HI_PCC = 0.0
HI_WINDOW = 20


def _hi_course_handicap(hi, sr, cr, par):
    return round(hi * (sr / 113.0) + (cr - par))


def _hi_strokes_per_hole(ch, hdcp_index):
    n = len(hdcp_index)
    base = ch // n
    rem = ch % n
    return [base + (1 if hdcp_index[i] <= rem else 0) for i in range(n)]


def _hi_adjusted_gross(scores, pars, ch, hdcp_index):
    sph = _hi_strokes_per_hole(ch, hdcp_index)
    return sum(min(s, pars[i] + 2 + sph[i]) for i, s in enumerate(scores))


def _hi_score_diff(ags, cr, sr, pcc=HI_PCC):
    return round((113.0 / sr) * (ags - cr - pcc), 1)


def _hi_from_diffs(diffs):
    """SDリスト -> (HI, 採用枚数)。枚数別ベスト枚数＋調整、1桁切り捨て、上限54.0。"""
    ds = sorted(diffs)
    n = len(ds)
    if n < 3:
        return None
    table = {3: (1, -2.0), 4: (1, -1.0), 5: (1, 0.0), 6: (2, -1.0),
             7: (2, 0.0), 8: (2, 0.0), 9: (3, 0.0), 10: (3, 0.0), 11: (3, 0.0),
             12: (4, 0.0), 13: (4, 0.0), 14: (4, 0.0), 15: (5, 0.0), 16: (5, 0.0),
             17: (6, 0.0), 18: (6, 0.0), 19: (7, 0.0), 20: (8, 0.0)}
    use, adj = table[min(n, 20)]
    import math as _m
    hi = sum(ds[:use]) / use + adj
    return min(_m.floor(hi * 10) / 10, 54.0), use


def compute_approx_hi(rounds, player_name):
    """近似HIを計算。
    Returns: (hi, use, rows, n_eligible, n_skipped_tee) or None
      rows: [(date, course, gross, ags, ch, sd, used_bool)] （SD昇順）
    対象ティー以外の同コースは n_skipped_tee にカウント。対象0/SD3枚未満はNone。
    """
    covered_courses = {c for (c, _t) in HI_RATINGS}
    elig, skipped_tee = [], 0
    for r in rounds:
        cn = r.get("course_name")
        if cn not in covered_courses:
            continue
        tee = r.get("tee")
        key = (cn, tee)
        if key not in HI_RATINGS:
            skipped_tee += 1
            continue
        info = HI_RATINGS[key]
        sc = None
        for p in r["players"]:
            if p["name"] == player_name:
                sc = p["scores"]
                break
        pars = r.get("pars") or []
        if not sc or len(sc) != 18 or len(pars) != 18:
            continue
        elig.append({"date": str(r.get("date", "")), "course": cn,
                     "cr": info["cr"], "sr": info["sr"], "par": info["par"],
                     "hdcp": info["hdcp"], "scores": sc, "pars": pars,
                     "gross": sum(sc)})
    if len(elig) < 3:
        return None
    elig.sort(key=lambda x: x["date"], reverse=True)
    window = elig[:HI_WINDOW]

    hi = 20.0
    for _ in range(100):
        diffs = []
        for r in window:
            ch = _hi_course_handicap(hi, r["sr"], r["cr"], r["par"])
            ags = _hi_adjusted_gross(r["scores"], r["pars"], ch, r["hdcp"])
            diffs.append(_hi_score_diff(ags, r["cr"], r["sr"]))
        res = _hi_from_diffs(diffs)
        if res is None:
            return None
        new_hi, _use = res
        if abs(new_hi - hi) < 0.05:
            hi = new_hi
            break
        hi = new_hi

    rows = []
    for r in window:
        ch = _hi_course_handicap(hi, r["sr"], r["cr"], r["par"])
        ags = _hi_adjusted_gross(r["scores"], r["pars"], ch, r["hdcp"])
        sd = _hi_score_diff(ags, r["cr"], r["sr"])
        rows.append([r["date"], r["course"], r["gross"], ags, ch, sd])
    hi, use = _hi_from_diffs([x[5] for x in rows])
    rows.sort(key=lambda x: x[5])
    out_rows = [(d, c, g, a, ch, sd, i < use) for i, (d, c, g, a, ch, sd) in enumerate(rows)]
    return hi, use, out_rows, len(elig), skipped_tee


# --- タブ2: 集計・分析 ---
with tab2:
    st.header("集計・分析")

    all_players = get_all_player_names()
    if not all_players:
        st.info("スコアデータがありません。まずスコアを入力してください。")
    else:
        selected_player = st.selectbox("プレーヤーを選択", all_players, key="stats_player")

        # スコア・パットのサマリー
        _rounds = load_rounds()
        _scores, _putts = [], []
        for r in _rounds:
            for p in r["players"]:
                if p["name"] == selected_player:
                    _scores.append(sum(p["scores"]))
                    pts = p.get("putts") or []
                    if any(pts):
                        _putts.append(sum(pts))

        if not _scores:
            st.info(f"{selected_player} のスコアデータがありません。")
        else:
            putt_avg, putt_n = get_recent_putt_avg(selected_player, 10)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ラウンド数", f"{len(_scores)}")
            m2.metric("平均スコア", f"{sum(_scores)/len(_scores):.1f}")
            m3.metric("ベストスコア", f"{min(_scores)}")
            m4.metric("平均パット(直近10R)",
                      f"{putt_avg}" if putt_avg is not None else "—",
                      help="パット数を記録したラウンドのみ・直近10回まで")
            if putt_avg is not None and putt_n < len(_scores):
                st.caption(f"※ 平均パットはパット記録のある {putt_n}ラウンドで算出"
                           "（記録なしはノーカウント）")

            # === 近似ハンディキャップインデックス（現状: 霞ヶ関ブルー基準）===
            hi_res = compute_approx_hi(_rounds, selected_player)
            if hi_res:
                hi_val, hi_use, hi_rows, hi_elig, hi_skip = hi_res
                h1, h2 = st.columns([1, 2])
                h1.metric("近似HI（霞ヶ関ブルー基準）", f"{hi_val}",
                          help="CR/SRが判明している霞ヶ関(東/西)ブルーのラウンドのみで算出。"
                               "PCC=0・調整スコアは反復近似のため、J-SYS正式HIとは一致しません（傾向把握用）。"
                               "他コースはCR/SR登録後に対応予定。")
                with h2:
                    st.caption(f"直近{len(hi_rows)}ラウンドのベスト{hi_use}枚平均で算出"
                               f"（対象{hi_elig}R／同コースでブルー以外はスキップ{hi_skip}R）")
                    st.caption("※ 正式なJGA HIは全コース・全ティーの直近20＋PCCで計算されます。")
                with st.expander("HIの内訳（SD一覧・★＝採用）"):
                    st.dataframe(pd.DataFrame([{
                        "日付": d, "コース": c, "gross": g, "AGS": a,
                        "CH": ch, "SD": sd, "採用": "★" if used else "",
                    } for (d, c, g, a, ch, sd, used) in hi_rows]),
                        use_container_width=True, hide_index=True)

            # === コース別スコア平均（直近Nラウンド窓）===
            st.subheader("コース別スコア平均")
            avg_n = st.number_input(
                "平均に使う直近ラウンド数", min_value=1, max_value=100, value=10, step=1,
                key="course_avg_n",
                help="各コースについて日付の新しい順にこの本数だけを使って平均・ベストを算出します。デフォルト10。")
            csa = windowed_course_averages(_rounds, selected_player, int(avg_n))
            if csa:
                st.caption(f"各コースの直近{int(avg_n)}ラウンドで集計（それ未満のコースは在る分だけ使用）")
                st.dataframe(pd.DataFrame([{
                    "コース": c["course"],
                    f"平均(直近{int(avg_n)})": c["avg"],
                    f"ベスト(直近{int(avg_n)})": c["best"],
                    "使用R": c["used"],
                    "総R": c["total"],
                } for c in csa]), use_container_width=True, hide_index=True)

            # === Par別分析（コースをまたいでも比較できる）===
            st.subheader("Par別の傾向（得意・不得意）")
            st.caption("コースが違っても、Par3/4/5という種類で見れば比較できます。"
                       "対パーがマイナスほど得意、プラスほど苦手です。")
            par_stats = get_par_type_stats(selected_player)
            if par_stats:
                ps_df = pd.DataFrame([{
                    "種類": s["label"],
                    "平均スコア": s["avg_score"],
                    "対パー": f"{s['vs_par']:+.2f}",
                    "ホール数": s["count"],
                } for s in par_stats])
                st.dataframe(ps_df, use_container_width=True, hide_index=True)

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=[s["label"] for s in par_stats],
                    y=[s["vs_par"] for s in par_stats],
                    marker_color=["#51cf66" if s["vs_par"] < 0 else
                                  "#339af0" if s["vs_par"] == 0 else "#ff6b6b"
                                  for s in par_stats],
                    text=[f"{s['vs_par']:+.2f}" for s in par_stats],
                    textposition="outside",
                ))
                fig.update_layout(
                    height=300, margin=dict(l=20, r=20, t=30, b=20),
                    yaxis_title="対パー（平均）", title="Par種類別 対パー")
                st.plotly_chart(fig, use_container_width=True)

                best = min(par_stats, key=lambda s: s["vs_par"])
                worst = max(par_stats, key=lambda s: s["vs_par"])
                if best["par"] != worst["par"]:
                    st.markdown(f"🟢 一番得意: **{best['label']}**（対パー {best['vs_par']:+.2f}）　"
                                f"🔴 一番苦手: **{worst['label']}**（対パー {worst['vs_par']:+.2f}）")

            # === スコア内訳 ===
            st.subheader("スコア内訳")
            cats, total = get_score_breakdown(selected_player)
            if total:
                bd_df = pd.DataFrame([{
                    "種類": k, "回数": v, "割合": f"{v/total*100:.1f}%"
                } for k, v in cats.items()])
                st.dataframe(bd_df, use_container_width=True, hide_index=True)
                figb = px.pie(values=list(cats.values()), names=list(cats.keys()),
                              hole=0.4)
                figb.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(figb, use_container_width=True)

            # === コース別ホール分析（同一コースを複数回プレーした場合のみ意味あり）===
            st.subheader("コース別のホール分析")
            pcourses = get_player_courses(selected_player)
            repeat_courses = {c: n for c, n in pcourses.items() if n >= 2}
            if not repeat_courses:
                st.info("ホール別の分析は「同じコースを2回以上」プレーすると表示されます。"
                        "（コースが違うとH1同士でも別のホールなので比較できないため）")
            else:
                csel = st.selectbox(
                    "コースを選択（2回以上プレーしたコース）",
                    list(repeat_courses.keys()),
                    format_func=lambda c: f"{c}（{repeat_courses[c]}回）",
                    key="course_hole_select")
                hole_n = st.number_input(
                    "平均に使う直近ラウンド数", min_value=1, max_value=100, value=10, step=1,
                    key="course_hole_n",
                    help="選んだコースについて日付の新しい順にこの本数だけで各ホールの平均を出します。デフォルト10。")
                _hdcp_map = course_hdcps_lookup()
                ch_avgs, rcount, rtotal = windowed_hole_averages(
                    _rounds, selected_player, csel,
                    int(hole_n), _hdcp_map.get(csel))
                has_hdcp = any(h["hdcp"] is not None for h in ch_avgs)
                cap = (f"{csel} の直近{rcount}ラウンドの平均（総{rtotal}ラウンド中）。"
                       "このコース内ならH1同士の比較に意味があります")
                if not has_hdcp:
                    cap += "／HDCPは登録コースに未設定のため空欄です"
                st.caption(cap)
                if ch_avgs:
                    labels = [f"H{h['hole']}" for h in ch_avgs]
                    avgs = [h["avg_score"] for h in ch_avgs]
                    pars_v = [h["par"] or 0 for h in ch_avgs]
                    hd_v = ["—" if h["hdcp"] is None else h["hdcp"] for h in ch_avgs]
                    figc = go.Figure()
                    figc.add_trace(go.Bar(
                        x=labels, y=avgs, name="平均",
                        marker_color=["#ff6b6b" if a > p else "#51cf66" if a < p
                                      else "#339af0" for a, p in zip(avgs, pars_v)],
                        text=[f"{v}" for v in avgs], textposition="outside",
                        customdata=hd_v,
                        hovertemplate="%{x}　平均%{y}　HDCP%{customdata}<extra></extra>"))
                    figc.add_trace(go.Scatter(
                        x=labels, y=pars_v, name="Par", mode="lines+markers",
                        line=dict(color="#868e96", dash="dash")))
                    figc.update_layout(
                        height=380, margin=dict(l=20, r=20, t=30, b=20),
                        legend=dict(orientation="h", y=1.02), yaxis_title="打数")
                    st.plotly_chart(figc, use_container_width=True)
                    st.caption("🟢 Parより良い　🔵 Par通り　🔴 Parより悪い")

                    # ホール別テーブル（HDCP列つき）
                    tbl = pd.DataFrame([{
                        "H": h["hole"],
                        "Par": h["par"],
                        "HDCP": "—" if h["hdcp"] is None else h["hdcp"],
                        "平均": h["avg_score"],
                        "対Par": (round(h["avg_score"] - h["par"], 1) if h["par"] else None),
                        "最小": h["min_score"],
                        "最大": h["max_score"],
                        "回数": h["count"],
                    } for h in ch_avgs])
                    st.dataframe(tbl, use_container_width=True, hide_index=True)

                    diffs = [{"hole": h["hole"], "diff": round(h["avg_score"] - h["par"], 1),
                              "avg": h["avg_score"], "par": h["par"], "hdcp": h["hdcp"]}
                             for h in ch_avgs if h["par"]]
                    if diffs:
                        ds = sorted(diffs, key=lambda x: x["diff"])
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**🟢 得意ホール**")
                            for d in ds[:3]:
                                hd = "" if d["hdcp"] is None else f", HDCP{d['hdcp']}"
                                st.markdown(f"- H{d['hole']}: 平均{d['avg']} "
                                            f"(Par{d['par']}{hd}, {d['diff']:+})")
                        with c2:
                            st.markdown("**🔴 苦手ホール**")
                            for d in ds[-3:][::-1]:
                                hd = "" if d["hdcp"] is None else f", HDCP{d['hdcp']}"
                                st.markdown(f"- H{d['hole']}: 平均{d['avg']} "
                                            f"(Par{d['par']}{hd}, {d['diff']:+})")

            # === スコア推移 ===
            player_rounds = []
            for r in _rounds:
                for p in r["players"]:
                    if p["name"] == selected_player:
                        player_rounds.append({
                            "date": r["date"], "course": r["course_name"],
                            "total": sum(p["scores"])})
            # 保存順のままだと線が時系列を往復して読めないため、日付昇順に並べる
            player_rounds.sort(key=lambda x: x["date"])
            if len(player_rounds) > 1:
                st.subheader("スコア推移")
                fig2 = px.line(pd.DataFrame(player_rounds), x="date", y="total",
                               markers=True,
                               labels={"date": "日付", "total": "トータルスコア"},
                               hover_data=["course"])
                fig2.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig2, use_container_width=True)

# --- タブ5: ゲーム集計 ---
with tab5:
    st.header("🎮 ゲーム集計")
    st.caption("⚠️ 金品を賭けるのは賭博罪です。点数（ポイント）の集計としてご利用ください。")

    g_rounds = load_rounds()
    if not g_rounds:
        st.info("ラウンドデータがありません。まずスコアを入力してください。")
    else:
        g_sorted = sorted(g_rounds, key=lambda r: r["date"], reverse=True)
        g_labels = [
            f"{r['date']} {r['course_name']} "
            f"（{', '.join(p['name'] for p in r['players'])}）"
            for r in g_sorted
        ]
        gi = st.selectbox("ラウンドを選択", range(len(g_sorted)),
                          format_func=lambda i: g_labels[i], key="game_round")
        gr = g_sorted[gi]
        g_players = gr["players"]
        g_num = gr.get("num_holes", len(gr.get("pars", [])))
        g_names = [p["name"] for p in g_players]

        if len(g_names) < 2:
            st.warning("ゲーム集計には2人以上のプレーヤーが必要です。")
        else:
            # このラウンドの保存ルール（無ければ現在のルール）
            g_rules = gr.get("rules") or get_rules()
            g_oru = {**DEFAULT_RULES["olympic"], **(g_rules.get("olympic") or {})}

            game = st.radio("ゲームを選択", GAME_OPTIONS,
                            horizontal=True, key="game_select")

            with st.expander("📖 このゲームのルール"):
                st.markdown(GAME_GUIDE[game])

            # ハンデ設定（タテ/ヨコ用）。ラウンド保存値を初期値に。
            g_chdcps_t = gr.get("hdcps") or []
            g_ty_handicaps = {n: 0 for n in g_names}
            if game in ("タテ", "ヨコ"):
                saved_raw = gr.get("raw_hdcp", {})
                with st.expander("⛳ ハンデ設定", expanded=False):
                    gmode = st.radio("ハンデの決め方",
                                     ["HDCPを入力して自動", "手動で設定", "ハンデなし"],
                                     index=["HDCPを入力して自動", "手動で設定",
                                            "ハンデなし"].index(
                                         gr.get("hcap_mode", "ハンデなし"))
                                     if gr.get("hcap_mode") in
                                     ["HDCPを入力して自動", "手動で設定", "ハンデなし"]
                                     else 2,
                                     key=f"g5_hmode_{gr['id']}", horizontal=True)
                    if gmode != "ハンデなし":
                        g_raw = {}
                        hc = st.columns(len(g_names))
                        for col, n in zip(hc, g_names):
                            with col:
                                g_raw[n] = st.number_input(
                                    f"{n}", min_value=0, max_value=54,
                                    value=int(saved_raw.get(n, 0)),
                                    key=f"g5_hcap_{gr['id']}_{n}")
                        if gmode == "HDCPを入力して自動":
                            g_ty_handicaps = dict(g_raw)  # スクラッチ基準（フル）
                        else:
                            g_ty_handicaps = dict(g_raw)
                        if game == "ヨコ" and (not g_chdcps_t or not any(g_chdcps_t)):
                            st.warning("ヨコのハンデ配分にはコースHDCPが必要です。")

            # === タテ ===
            if game == "タテ":
                st.subheader("タテ（トータルストローク勝負）")
                st.caption(f"1ストローク = {g_rules.get('tate_pt', 1)}点。"
                           "ネット（グロス−ハンデ）の差を総当たりで合計。")
                g_tot, nt_tot, net, matrix = tate_results(
                    g_players, g_rules.get("tate_pt", 1), g_ty_handicaps)
                order = sorted(g_names, key=lambda n: nt_tot[n])
                rank_df = pd.DataFrame({
                    "順位": [f"{i+1}位" for i in range(len(order))],
                    "プレーヤー": order,
                    "グロス": [g_tot[n] for n in order],
                    "ネット": [nt_tot[n] for n in order],
                    "タテ得点": [f"{net[n]:+d}" for n in order],
                })
                st.dataframe(rank_df, use_container_width=True, hide_index=True)

                with st.expander("対戦表（自分から見たネット打数差）"):
                    mat = {"対 →": g_names}
                    for b in g_names:
                        mat[b] = [
                            (f"{matrix[(a, b)]:+d}" if a != b else "—")
                            for a in g_names
                        ]
                    st.dataframe(pd.DataFrame(mat), use_container_width=True,
                                 hide_index=True)

            # === ヨコ ===
            elif game == "ヨコ":
                st.subheader("ヨコ（ホールマッチ）")
                st.caption(f"各ホールでネット最少打数が勝ち（1勝 = {g_rules.get('yoko_pt', 1)}点）。")
                holes_won, hole_winners, net = yoko_results(
                    g_players, g_num, g_rules.get("yoko_pt", 1),
                    g_ty_handicaps, g_chdcps_t)
                order = sorted(g_names, key=lambda n: net[n], reverse=True)
                rank_df = pd.DataFrame({
                    "順位": [f"{i+1}位" for i in range(len(order))],
                    "プレーヤー": order,
                    "勝ちホール数": [holes_won[n] for n in order],
                    "ヨコ得点": [f"{net[n]:+d}" for n in order],
                })
                st.dataframe(rank_df, use_container_width=True, hide_index=True)

                with st.expander("ホール別の勝者"):
                    win_df = pd.DataFrame({
                        "ホール": [f"H{i+1}" for i in range(g_num)],
                        "勝者": [w if w else "引分" for w in hole_winners],
                    })
                    st.dataframe(win_df.set_index("ホール").T,
                                 use_container_width=True)

            # === オリンピック ===
            elif game == "オリンピック":
                st.subheader("オリンピック（パット競争）")
                st.caption(
                    f"金={g_oru['金']} / 銀={g_oru['銀']} / 銅={g_oru['銅']} / "
                    f"鉄={g_oru['鉄']} / チップイン={g_oru['チップイン']} / なし=0。"
                    "各セルでメダルを選択してください。"
                )

                existing = gr.get("olympic_medals") or {}
                data = {n: list(existing.get(n, ["なし"] * g_num)) for n in g_names}
                for n in g_names:  # 長さ調整
                    if len(data[n]) < g_num:
                        data[n] += ["なし"] * (g_num - len(data[n]))
                    data[n] = [m if m in OLYMPIC_MEDALS else "なし"
                               for m in data[n][:g_num]]

                edit_df = pd.DataFrame(data, index=[f"H{i+1}" for i in range(g_num)])
                edited = st.data_editor(
                    edit_df, use_container_width=True, key=f"olympic_{gr['id']}",
                    column_config={
                        n: st.column_config.SelectboxColumn(
                            n, options=OLYMPIC_MEDALS, required=True)
                        for n in g_names
                    },
                )

                medals = {n: list(edited[n]) for n in g_names}
                points = olympic_points_from_medals(medals, g_oru)
                totals = {n: sum(points[n]) for n in g_names}
                order = sorted(g_names, key=lambda n: totals[n], reverse=True)
                rank_df = pd.DataFrame({
                    "順位": [f"{i+1}位" for i in range(len(order))],
                    "プレーヤー": order,
                    "オリンピック得点": [totals[n] for n in order],
                })
                st.dataframe(rank_df, use_container_width=True, hide_index=True)

                if st.button("💾 オリンピックの点数を保存", type="primary",
                             use_container_width=True):
                    update_round(gr["id"], olympic=points, olympic_medals=medals)
                    st.success("オリンピックの点数を保存しました！")

            # === ポイントターニー ===
            elif game == "ポイントターニー":
                st.subheader("ポイントターニー（ポイント制）")
                g_point = {**DEFAULT_RULES["point"], **(g_rules.get("point") or {})}
                st.caption(
                    f"イーグル以上={g_point['eagle']} / バーディ={g_point['birdie']} / "
                    f"パー={g_point['par']} / ボギー={g_point['bogey']} / "
                    f"ダブル以上={g_point['double']}")
                pt_tot, _ = point_tourney_results(g_players, gr["pars"], g_point,
                                                  num_holes=g_num)
                order = sorted(g_names, key=lambda n: pt_tot[n], reverse=True)
                st.dataframe(pd.DataFrame({
                    "順位": [f"{i+1}位" for i in range(len(order))],
                    "プレーヤー": order,
                    "ポイント": [pt_tot[n] for n in order],
                }), use_container_width=True, hide_index=True)

            # === ラスベガス ===
            elif game == "ラスベガス":
                st.subheader("ラスベガス（2対2ペア戦）")
                lv_saved = gr.get("lasvegas") or {}
                if len(g_names) != 4:
                    st.warning("ラスベガスは4人ちょうどのラウンドが対象です。")
                else:
                    kp = f"lv5_{gr['id']}"
                    o = render_lasvegas_rule_options(g_num, key_prefix=kp,
                                                     saved=lv_saved)
                    lv_t1 = render_lasvegas_team(g_names, o["team_mode"],
                                                 key_prefix=kp, saved=lv_saved)
                    if o["team_mode"] == "固定" and len(lv_t1) != 2:
                        st.info("チーム1のメンバーを2人選んでください。")
                    else:
                        lv_t2 = [n for n in g_names if n not in lv_t1]
                        lv = las_vegas_results(
                            lv_t1, lv_t2,
                            {p["name"]: p["scores"] for p in g_players},
                            num_holes=g_num, pars=gr.get("pars"),
                            players=g_names, team_mode=o["team_mode"],
                            birdie_reverse=o["birdie_reverse"],
                            drop_ones=o["drop_ones"], carry=o["carry"],
                            push_by_hole=o["push_by_hole"])
                        render_lasvegas_result(lv, lv_t1, lv_t2, o["team_mode"])
                        if st.button("💾 チーム・オプションを保存",
                                     key=f"lv5save_{gr['id']}"):
                            update_round(gr["id"], lasvegas={
                                "team1": lv_t1, "team_mode": o["team_mode"],
                                "birdie_reverse": o["birdie_reverse"],
                                "drop_ones": o["drop_ones"], "carry": o["carry"],
                                "push_by_hole": {str(k): v for k, v
                                                 in o["push_by_hole"].items()},
                            })
                            st.success("保存しました！")

            # === ベスト＆グロス ===
            else:
                st.subheader("ベスト＆グロス（4人チーム戦）")
                g_course = next((c for c in load_courses()
                                 if c["name"] == gr["course_name"]), None)
                g_chdcps = gr.get("hdcps") or (g_course or {}).get("hdcps") or []
                bg_saved = gr.get("bg") or {}

                if len(g_names) != 4:
                    st.warning("ベスト＆グロスは4人ちょうどのラウンドが対象です。")
                elif not g_chdcps or not any(g_chdcps):
                    st.warning("このコースのHDCP（ハンデ順）が未設定です。"
                               "「コース管理」でHDCPを入力してください。")
                else:
                    bcol1, bcol2 = st.columns(2)
                    with bcol1:
                        g_start = st.radio("スタート", ["OUT", "IN"], horizontal=True,
                                           index=0 if bg_saved.get("start", "OUT") == "OUT" else 1,
                                           key=f"bg5_start_{gr['id']}")
                    with bcol2:
                        g_settle = st.radio("精算単位",
                                            ["18ホール通し", "ハーフ(9H)ごと"],
                                            key=f"bg5_settle_{gr['id']}")
                    g_birdie = st.checkbox("バーディ賞を有効にする",
                                           value=bg_saved.get("birdie_bonus", True),
                                           key=f"bg5_birdie_{gr['id']}")

                    saved_hp = bg_saved.get("player_hdcps", {})
                    st.caption("各プレーヤーのHDCP：")
                    hp_cols = st.columns(4)
                    g_phdcps = {}
                    for col, n in zip(hp_cols, g_names):
                        with col:
                            g_phdcps[n] = st.number_input(
                                f"{n}", min_value=0, max_value=54,
                                value=int(saved_hp.get(n, 0)),
                                key=f"bg5_hdcp_{gr['id']}_{n}")

                    g_override = None
                    g_manual = st.checkbox(
                        "チーム・ハンデを手動で指定する",
                        value=bool(bg_saved.get("override")),
                        key=f"bg5_manual_{gr['id']}")
                    if g_manual:
                        ov = bg_saved.get("override") or {}
                        defA = [n for n in (ov.get("teamA") or []) if n in g_names]
                        mteamA = st.multiselect(
                            "Aチーム（2人選択）", g_names,
                            default=defA if len(defA) == 2 else [],
                            max_selections=2, key=f"bg5_mteamA_{gr['id']}")
                        if len(mteamA) == 2:
                            mteamB = [n for n in g_names if n not in mteamA]
                            mc1, mc2 = st.columns(2)
                            with mc1:
                                mhi = st.radio("ハンデをもらうチーム",
                                               ["Aチーム", "Bチーム"],
                                               key=f"bg5_mhi_{gr['id']}")
                            with mc2:
                                mN = st.number_input(
                                    "ハンデ数（ホール）", min_value=0, max_value=18,
                                    value=int(ov.get("N", 0)),
                                    key=f"bg5_mN_{gr['id']}")
                            g_override = {"teamA": mteamA, "teamB": mteamB,
                                          "hi_team": "A" if mhi == "Aチーム" else "B",
                                          "N": int(mN)}

                    bg = best_and_gross(
                        {p["name"]: p["scores"] for p in g_players}, gr["pars"],
                        g_chdcps, g_phdcps, start=g_start, birdie_bonus=g_birdie,
                        num_holes=g_num, override=g_override)
                    A_t, B_t = bg["teamA"], bg["teamB"]
                    st.markdown(
                        f"**Aチーム**: {A_t[0]}＋{A_t[1]}（HDCP計{bg['sumA']}）　"
                        f"**Bチーム**: {B_t[0]}＋{B_t[1]}（HDCP計{bg['sumB']}）")
                    st.caption(f"ハンデ: {bg['hi_team']}チームが{bg['N']}ホール分。"
                               "ハンデホールはコースHDCPが小さい順。")

                    if g_settle.startswith("ハーフ"):
                        res_df = pd.DataFrame({
                            "チーム": ["Aチーム", "Bチーム"],
                            "前半": [bg["front"]["A"], bg["front"]["B"]],
                            "後半": [bg["back"]["A"], bg["back"]["B"]],
                            "合計": [bg["totals"]["A"], bg["totals"]["B"]],
                        })
                    else:
                        res_df = pd.DataFrame({
                            "チーム": ["Aチーム", "Bチーム"],
                            "得点": [bg["totals"]["A"], bg["totals"]["B"]],
                        })
                    st.dataframe(res_df, use_container_width=True, hide_index=True)
                    ta, tb = bg["totals"]["A"], bg["totals"]["B"]
                    win = ("🅰 Aチームの勝ち" if ta > tb else
                           "🅱 Bチームの勝ち" if tb > ta else "引き分け")
                    st.markdown(f"### {win}（A {ta} - {tb} B）")

                    with st.expander("ホール別明細"):
                        tmap = {"best": "ベスト", "gross": "グロス", None: "—"}
                        rows = [{
                            "H": d["hole"], "ハンデ": tmap[d["htype"]],
                            "Aベ/合": f"{d['A_best']}/{d['A_gross']}",
                            "Bベ/合": f"{d['B_best']}/{d['B_gross']}",
                            "A点": d["ptsA"], "B点": d["ptsB"],
                            "B賞": "○" if d["birdie"] else "",
                        } for d in bg["per_hole"]]
                        st.dataframe(pd.DataFrame(rows),
                                     use_container_width=True, hide_index=True)

                    if st.button("💾 ベスト＆グロス設定を保存", type="primary",
                                 use_container_width=True):
                        update_round(gr["id"], bg={
                            "player_hdcps": g_phdcps, "start": g_start,
                            "birdie_bonus": g_birdie, "settle": g_settle,
                            "override": g_override})
                        st.success("ベスト＆グロスの設定を保存しました！")

# --- タブ3: コース管理 ---
with tab3:
    st.header("コース管理")

    # --- セッション初期値 ---
    if "hole_count" not in st.session_state:
        st.session_state["hole_count"] = 18
    if "course_name_field" not in st.session_state:
        st.session_state["course_name_field"] = ""
    for i in range(18):
        st.session_state.setdefault(f"par_{i}", 4)

    def make_course_name(base, course, single):
        """ゴルフ場名 + コース名 を組み立てる（1コースのみなら場名だけ）"""
        cn = course.get("course_name", "")
        if single or not cn or cn in ("本コース", "コース"):
            return base.strip()
        return f"{base.strip()} {cn}".strip()

    def apply_course(base, course, single, page=""):
        """取得した1コースのホール情報を入力欄に反映する"""
        name = make_course_name(base, course, single)
        st.session_state["course_name_field"] = name
        st.session_state["hole_count"] = course["hole_count"]
        for i, h in enumerate(course["holes"]):
            st.session_state[f"par_{i}"] = h["par"]
        # HDCP / ティー別ヤードを保持（登録時にparと合わせて保存する）
        st.session_state["fetched_holes"] = {
            "name": name, "holes": course["holes"],
        }
        src = f"（取得元ページ: {page}）" if page else ""
        st.session_state["fetched_msg"] = (
            f"「{name}」のホール情報を反映しました"
            f"（{course['hole_count']}H / Par {course['total_par']}）{src}。"
            "下で内容を確認して登録してください。"
        )

    def handle_fetch_result(base, layout):
        """fetch結果(複数コース)を処理。1コースなら即反映、複数なら選択待ちへ。
        取得ページの実名(page_name)を優先し、URL違いをユーザーが気づけるようにする。"""
        page = layout.get("page_name", "")
        base = (page or base or "コース").strip()
        courses = layout["courses"]
        if len(courses) == 1:
            apply_course(base, courses[0], single=True, page=page)
        else:
            st.session_state["pending_fetch"] = {
                "base": base, "courses": courses, "page": page,
            }
        st.rerun()

    st.subheader("ゴルフ場を追加")
    add_method = st.radio(
        "追加方法",
        ["🌐 楽天GORAから自動取得（名前で検索）", "🔗 URL / ID から取得", "✏️ 手動で入力"],
        key="add_method",
    )

    # === 方法1: 楽天GORA API 名前検索 ===
    if add_method.startswith("🌐"):
        app_id = get_rakuten_app_id()
        access_key = get_rakuten_access_key()
        referer = get_rakuten_referer()
        # 認証情報は secrets / 環境変数 で設定するのが本筋。
        # 3つそろっていれば画面には一切出さない（伏字でも表示しない）。
        missing = [lab for lab, val in
                   (("App ID", app_id), ("Access Key", access_key),
                    ("呼び出し元サイトURL", referer)) if not val]
        if not missing:
            st.caption("🔑 楽天ウェブサービスの認証情報: 設定済み"
                       "（secrets / 環境変数から読み込み）")
        else:
            with st.expander(f"⚙️ 未設定の項目があります（{' / '.join(missing)}）",
                             expanded=True):
                st.caption("本来は .streamlit/secrets.toml（ローカル）または "
                           "Streamlit Cloud の Secrets に "
                           "RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY / RAKUTEN_REFERER "
                           "を設定してください。ここでの入力はこのセッション限りの"
                           "応急処置です。値は "
                           "webservice.rakuten.co.jp/app/list で確認できます。")
                if not app_id:
                    key_in = st.text_input("楽天 applicationId（App ID）",
                                           value="", type="password",
                                           key="app_id_input")
                    if key_in:
                        st.session_state["rakuten_app_id"] = key_in.strip()
                        app_id = key_in.strip()
                if not access_key:
                    ak_in = st.text_input("楽天 accessKey（Access Key）",
                                          value="", type="password",
                                          key="access_key_input")
                    if ak_in:
                        st.session_state["rakuten_access_key"] = ak_in.strip()
                        access_key = ak_in.strip()
                if not referer:
                    rf_in = st.text_input(
                        "呼び出し元サイトURL（Referer）", value="",
                        placeholder="https://xxxx.streamlit.app/",
                        key="referer_input",
                        help="楽天のアプリ設定「許可されたWebサイト」に登録したURL。")
                    if rf_in:
                        st.session_state["rakuten_referer"] = rf_in.strip()
                        referer = rf_in.strip()

        kw = st.text_input("ゴルフ場名で検索", key="search_keyword",
                           placeholder="例: 霞ヶ関カンツリー")
        if st.button("🔍 検索", use_container_width=True):
            if not app_id:
                st.error("applicationId（App ID）を入力してください。")
            elif not access_key:
                st.error("accessKey（Access Key）を入力してください。"
                         "2026年2月の楽天ウェブサービス刷新で必須になりました。")
            elif not kw:
                st.error("ゴルフ場名を入力してください。")
            else:
                res = search_rakuten(kw, app_id, access_key, referer=referer)
                if isinstance(res, tuple):
                    st.error(res[1])
                    st.session_state["search_results"] = []
                else:
                    st.session_state["search_results"] = res
                    if not res:
                        st.warning("該当するゴルフ場が見つかりませんでした。")

        results = st.session_state.get("search_results", [])
        if results:
            labels = [
                f"{r['golfCourseName']}（{r['prefecture']}{r['areaName']}）"
                f"{' ★' + str(r['evaluation']) if r['evaluation'] else ''}"
                for r in results
            ]
            idx = st.selectbox("候補から選択", range(len(results)),
                               format_func=lambda i: labels[i], key="search_pick")
            if st.button("⬇️ このコースのホール情報を取得", type="primary",
                         use_container_width=True):
                cid = results[idx]["golfCourseId"]
                layout = fetch_holes_from_layout(cid)
                if isinstance(layout, tuple):
                    st.error(layout[1])
                else:
                    handle_fetch_result(results[idx]["golfCourseName"], layout)

    # === 方法2: URL / ID から取得 ===
    elif add_method.startswith("🔗"):
        st.caption("ブラウザで「ゴルフ場名 楽天GORA」を検索 → コースページのURLを貼り付け"
                   "（または c_id の数字）")
        url_in = st.text_input("楽天GORA コースURL または c_id", key="url_input",
                               placeholder=".../guide/layout_disp/c_id/240014/")
        name_in = st.text_input("保存するゴルフ場名（任意・空欄ならページ名を自動使用）",
                                key="url_name_input")
        st.caption("⚠️ 取得後はページの実際のゴルフ場名が表示されます。"
                   "違うゴルフ場が出たらURL(c_id)をご確認ください。")
        if st.button("⬇️ ホール情報を取得", type="primary", use_container_width=True):
            cid = extract_cid(url_in)
            if not cid:
                st.error("URL または c_id を認識できませんでした。")
            else:
                layout = fetch_holes_from_layout(cid)
                if isinstance(layout, tuple):
                    st.error(layout[1])
                else:
                    handle_fetch_result(name_in.strip() or f"コース{cid}", layout)

    # === 複数コースの選択 ===
    pf = st.session_state.get("pending_fetch")
    if pf:
        src = f"（取得元ページ: {pf.get('page', '')}）" if pf.get("page") else ""
        st.info(f"**{pf['base']}**{src} には **{len(pf['courses'])}コース** あります。"
                "登録するコースを選んでください。")
        c_labels = [
            f"{(c['course_name'] or f'コース{i+1}')}"
            f"（{c['hole_count']}H / Par {c['total_par']}）"
            for i, c in enumerate(pf["courses"])
        ]
        sel = st.selectbox("コースを選択", range(len(pf["courses"])),
                           format_func=lambda i: c_labels[i], key="course_pick")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⬇️ このコースを反映", type="primary", use_container_width=True):
                apply_course(pf["base"], pf["courses"][sel], single=False,
                             page=pf.get("page", ""))
                st.session_state.pop("pending_fetch", None)
                st.rerun()
        with col_b:
            if st.button("📥 全コースをまとめて登録", use_container_width=True):
                saved = []
                for c in pf["courses"]:
                    nm = make_course_name(pf["base"], c, single=False)
                    save_course(create_manual_course(nm, c["holes"]))
                    saved.append(nm)
                st.session_state.pop("pending_fetch", None)
                st.session_state["fetched_msg"] = (
                    "次のコースを登録しました: " + " / ".join(saved)
                )
                st.rerun()

    # 取得結果メッセージ
    if st.session_state.get("fetched_msg"):
        st.success(st.session_state.pop("fetched_msg"))

    st.divider()
    st.subheader("ホール構成の確認・登録")

    course_name_input = st.text_input("ゴルフ場名", key="course_name_field",
                                      placeholder="例: 東京よみうりカントリークラブ")
    hole_count = st.radio("ホール数", [9, 18], horizontal=True, key="hole_count")

    st.markdown("**各ホールのPar**（自動取得後も手で修正できます）")
    PAR_OPTS = [3, 4, 5, 6]

    if hole_count == 18:
        st.markdown("*OUT (1-9)*")
        out_cols = st.columns(9)
        out_pars = []
        for i in range(9):
            with out_cols[i]:
                p = st.selectbox(f"H{i+1}", PAR_OPTS, key=f"par_{i}")
                out_pars.append(p)

        st.markdown("*IN (10-18)*")
        in_cols = st.columns(9)
        in_pars = []
        for i in range(9):
            with in_cols[i]:
                p = st.selectbox(f"H{i+10}", PAR_OPTS, key=f"par_{i+9}")
                in_pars.append(p)

        all_pars = out_pars + in_pars
        st.markdown(f"OUT: Par {sum(out_pars)}　IN: Par {sum(in_pars)}　"
                    f"TOTAL: **Par {sum(all_pars)}**")
    else:
        cols = st.columns(9)
        all_pars = []
        for i in range(9):
            with cols[i]:
                p = st.selectbox(f"H{i+1}", PAR_OPTS, key=f"par_{i}")
                all_pars.append(p)
        st.markdown(f"TOTAL: **Par {sum(all_pars)}**")

    # 自動取得した HDCP / ティー別ヤードのプレビュー
    fetched = st.session_state.get("fetched_holes")
    use_fetched = (
        fetched
        and fetched.get("name") == course_name_input.strip()
        and len(fetched.get("holes", [])) == hole_count
    )
    if use_fetched:
        fh = fetched["holes"]
        tee_names = []
        for h in fh:
            for t in (h.get("yards") or {}):
                if t not in tee_names:
                    tee_names.append(t)
        has_hdcp = any(h.get("hdcp") is not None for h in fh)
        if tee_names or has_hdcp:
            with st.expander("📋 取得した HDCP / ティー別ヤード（確認）", expanded=True):
                p_pars = [h["par"] for h in fh]
                p_hdcps = [h.get("hdcp") for h in fh]
                p_tees = [(t, [(h.get("yards") or {}).get(t) for h in fh])
                          for t in tee_names]
                st.dataframe(
                    make_info_table(len(fh), p_pars, p_hdcps, p_tees),
                    use_container_width=True,
                )
                st.caption(f"ティー: {', '.join(tee_names) if tee_names else 'なし'}　/　"
                           f"HDCP: {'あり' if has_hdcp else 'なし'}　"
                           "（合計ヤードも含めて一緒に保存されます）")

    if st.button("✅ コースを登録", type="primary", use_container_width=True,
                 key="save_course_btn"):
        if not course_name_input.strip():
            st.error("ゴルフ場名を入力してください。")
        else:
            holes_data = []
            for i in range(hole_count):
                hd = {"hole": i + 1, "par": all_pars[i]}
                if use_fetched and i < len(fetched["holes"]):
                    src = fetched["holes"][i]
                    hd["hdcp"] = src.get("hdcp")
                    hd["yards"] = src.get("yards") or {}
                holes_data.append(hd)
            course = create_manual_course(course_name_input.strip(), holes_data)
            result = save_course(course)
            verb = "上書き保存" if result["replaced"] else "登録"
            st.success(f"「{course_name_input}」を{verb}しました！"
                       + ("（HDCP・ティー別ヤード付き）" if use_fetched else ""))

    st.divider()
    st.subheader("登録済みコース一覧")
    courses = load_courses()
    if courses:
        for c in courses:
            tees = c.get("tees", [])
            tee_tag = f"｜ティー: {', '.join(tees)}" if tees else ""
            with st.expander(f"⛳ {c['name']} ({c['holes']}H, Par {c['total_par']}){tee_tag}"):
                tees_yards = [(t, c["yards"][t]) for t in tees]
                st.dataframe(
                    make_info_table(c["holes"], c["pars"],
                                    c.get("hdcps"), tees_yards),
                    use_container_width=True,
                )

                # HDCP手動編集（楽天GORAが連番=未設定の場合の補正用）
                ch = c.get("hdcps") or [None] * c["holes"]
                is_seq = [x for x in ch if x is not None] == list(
                    range(1, c["holes"] + 1))
                if is_seq:
                    st.caption("⚠️ HDCPがホール番号と同じ連番です。"
                               "楽天GORAに正しいデータが無い可能性があります。下で修正できます。")
                with st.expander("✏️ HDCP（ハンデ順）を手動編集"):
                    st.caption("各ホールの難易度ランキング（1〜18、重複なし）を入力してください。"
                               "スコアカード裏の数字です。ベスト＆グロスのハンデ計算に使います。")
                    hd_init = [int(x) if x is not None else 0 for x in ch]
                    while len(hd_init) < c["holes"]:
                        hd_init.append(0)
                    hd_df = pd.DataFrame(
                        {"HDCP": hd_init[:c["holes"]]},
                        index=[f"H{i+1}" for i in range(c["holes"])])
                    hd_edited = st.data_editor(
                        hd_df.T, use_container_width=True,
                        key=f"hdcp_edit_{c['name']}",
                        column_config={
                            f"H{i+1}": st.column_config.NumberColumn(
                                f"H{i+1}", min_value=0, max_value=18, step=1)
                            for i in range(c["holes"])
                        },
                    )
                    if st.button("💾 HDCPを保存", key=f"savehdcp_{c['name']}"):
                        new_hdcps = [int(hd_edited.loc["HDCP", f"H{i+1}"])
                                     for i in range(c["holes"])]
                        vals = [v for v in new_hdcps if v > 0]
                        if sorted(vals) != list(range(1, c["holes"] + 1)):
                            st.error(f"HDCPは1〜{c['holes']}を重複なく入力してください。"
                                     f"（現在: {sorted(vals)}）")
                        else:
                            updated = dict(c)
                            updated["hdcps"] = new_hdcps
                            for i, hd in enumerate(updated.get("hole_data", [])):
                                if i < len(new_hdcps):
                                    hd["hdcp"] = new_hdcps[i]
                            save_course(updated)
                            st.success("HDCPを保存しました。")
                            st.rerun()

                del_key = f"delcourse_{c['name']}"
                confirm_key = f"confirm_{c['name']}"
                if st.session_state.get(confirm_key):
                    st.warning(f"「{c['name']}」を削除します。よろしいですか？")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("✅ 削除する", key=f"yes_{c['name']}",
                                     use_container_width=True):
                            delete_course(c["name"])
                            st.session_state.pop(confirm_key, None)
                            st.success(f"「{c['name']}」を削除しました。")
                            st.rerun()
                    with cc2:
                        if st.button("キャンセル", key=f"no_{c['name']}",
                                     use_container_width=True):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                else:
                    if st.button("🗑️ このコースを削除", key=del_key):
                        st.session_state[confirm_key] = True
                        st.rerun()
    else:
        st.info("登録されたコースがありません。")

# --- タブ4: ラウンド履歴 ---
with tab4:
    st.header("ラウンド履歴")

    # ===== プレーヤー名の統合・修正 =====
    # OCRの誤読（蓑輪→養輪 等）や、呼び名と本名の混在で同じ人が別人として
    # 記録されてしまうため、全ラウンドをまたいで名前を付け替える。
    with st.expander("👤 プレーヤー名の統合・修正"):
        counts = player_round_counts()
        if not counts:
            st.info("ラウンドデータがありません。")
        else:
            st.caption("同じ人が違う名前で登録されている場合、ここで1つに"
                       "まとめられます。全ラウンドをまとめて書き換えます。")
            st.dataframe(pd.DataFrame({
                "登録名": list(counts.keys()),
                "ラウンド数": list(counts.values()),
            }), use_container_width=True, hide_index=True)

            rc1, rc2 = st.columns(2)
            with rc1:
                old_nm = st.selectbox("まとめたい名前（消える方）",
                                      list(counts.keys()), key="rn_old")
            with rc2:
                cand = [n for n in counts if n != old_nm]
                new_mode = st.radio("まとめ先", ["既存の名前から選ぶ", "新しく入力する"],
                                    horizontal=True, key="rn_mode")
                if new_mode == "既存の名前から選ぶ" and cand:
                    new_nm = st.selectbox("まとめ先の名前（残る方）", cand,
                                          key="rn_new_pick")
                else:
                    new_nm = st.text_input("まとめ先の名前（残る方）",
                                           key="rn_new_text")

            if old_nm and new_nm and old_nm != new_nm:
                st.warning(f"「{old_nm}」（{counts.get(old_nm, 0)}ラウンド）を "
                           f"**「{new_nm}」** に付け替えます。元に戻せません。")
                if st.checkbox("内容を確認しました", key="rn_confirm"):
                    if st.button("👤 名前を付け替える", type="primary",
                                 key="rn_go"):
                        res = rename_player(old_nm, new_nm)
                        if res["changed"]:
                            st.success(f"{res['changed']} ラウンドを"
                                       f"「{new_nm}」に付け替えました。")
                        else:
                            st.info("付け替え対象がありませんでした。")
                        if res["conflicts"]:
                            st.error(
                                "次のラウンドは同じ人が二重に記録されている可能性が"
                                "あるため付け替えていません（ラウンドID: "
                                + ", ".join(str(i) for i in res["conflicts"])
                                + "）。下の履歴で中身を確認してください。")
                        st.rerun()

            # ----- 名前ごと消す（誤登録・使わなくなった呼び名の整理）-----
            st.divider()
            st.markdown("**この名前を消す**")
            st.caption("誤って登録した名前や、使わなくなった呼び名を一覧から消します。"
                       "その人のスコアも一緒に消えるため、本人の記録が入っている"
                       "名前は上の「付け替え」を使ってください。")
            del_nm = st.selectbox("消す名前", list(counts.keys()), key="dp_name")
            where = player_rounds_of(del_nm) if del_nm else []
            if where:
                st.dataframe(pd.DataFrame([{
                    "ID": w["id"], "日付": w["date"],
                    "コース": w["course_name"], "スコア": w["total"],
                } for w in where]), use_container_width=True, hide_index=True)
                st.warning(f"「{del_nm}」を {len(where)} ラウンドから取り除きます。"
                           "そのラウンドの他の人の記録は残ります。元に戻せません。")
            else:
                st.info(f"「{del_nm}」はラウンドに記録がありません。"
                        "一覧から消えるだけです。")
            if st.checkbox("消してよいことを確認しました", key="dp_confirm"):
                if st.button("🗑️ この名前を消す", key="dp_go"):
                    res = forget_player(del_nm)
                    st.success(f"「{del_nm}」を {res['changed']} ラウンドから"
                               "取り除きました。")
                    if res["emptied"]:
                        st.error("次のラウンドはプレーヤーが0人になりました"
                                 "（ラウンドID: "
                                 + ", ".join(str(i) for i in res["emptied"])
                                 + "）。不要なら下の履歴から削除してください。")
                    st.rerun()

    rounds = load_rounds()
    if not rounds:
        st.info("ラウンドデータがありません。")
    else:
        rounds_sorted = sorted(rounds, key=lambda r: r["date"], reverse=True)

        for r in rounds_sorted:
            player_names = ", ".join([p["name"] for p in r["players"]])
            with st.expander(f"📅 {r['date']} - {r['course_name']} ({player_names})"):
                pars = r.get("pars", [])
                num_holes = r.get("num_holes", len(pars))

                header = ["ホール"] + [str(i + 1) for i in range(num_holes)]
                if num_holes == 18:
                    header.insert(10, "OUT")
                    header.append("IN")
                header.append("TOTAL")

                rows = []
                par_row = ["Par"] + [str(p) for p in pars]
                if num_holes == 18:
                    par_row.insert(10, str(sum(pars[:9])))
                    par_row.append(str(sum(pars[9:])))
                par_row.append(str(sum(pars)))
                rows.append(par_row)

                # HDCP行（合計は無いので "-"）
                hdcps = r.get("hdcps") or []
                if any(x is not None for x in hdcps):
                    hd_row = ["HDCP"] + [str(x) if x is not None else "-" for x in hdcps]
                    if num_holes == 18:
                        hd_row.insert(10, "-")
                        hd_row.append("-")
                    hd_row.append("-")
                    rows.append(hd_row)

                # ヤード行（ティーが記録されていれば）
                yards = r.get("yards") or []
                if any(y is not None for y in yards):
                    label = f"ヤード({r.get('tee')})" if r.get("tee") else "ヤード"
                    y_row = [label] + [str(y) if y is not None else "-" for y in yards]
                    if num_holes == 18:
                        y_row.insert(10, str(sum(y for y in yards[:9] if y)))
                        y_row.append(str(sum(y for y in yards[9:] if y)))
                    y_row.append(str(sum(y for y in yards if y)))
                    rows.append(y_row)

                for p in r["players"]:
                    row = [p["name"]] + [str(s) for s in p["scores"]]
                    if num_holes == 18:
                        row.insert(10, str(sum(p["scores"][:9])))
                        row.append(str(sum(p["scores"][9:])))
                    row.append(str(sum(p["scores"])))
                    rows.append(row)

                df = pd.DataFrame(rows, columns=header)
                st.dataframe(df, use_container_width=True, hide_index=True)

                # パット合計（記録があれば）
                putt_summ = []
                for p in r["players"]:
                    pts = p.get("putts") or []
                    if any(pts):
                        putt_summ.append(f"{p['name']}: {sum(pts)}")
                if putt_summ:
                    st.caption("🟢 パット合計　" + "　/　".join(putt_summ))

                if r.get("tee"):
                    st.caption(f"⛳ ティー: {r['tee']}")

                if st.button(f"🗑️ 削除", key=f"del_{r['id']}"):
                    delete_round(r["id"])
                    st.success("削除しました。")
                    st.rerun()
