import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date
from data_manager import (
    load_courses, save_course, delete_course, load_rounds, save_round,
    delete_round, update_round, get_hole_averages, get_all_player_names,
    ensure_data_dir, load_prefs, update_prefs,
)
from games import (
    tate_results, yoko_results, olympic_totals, olympic_points_from_medals,
    best_and_gross, point_tourney_results, las_vegas_results,
    OLYMPIC_GUIDE, GAME_GUIDE, DEFAULT_RULES, OLYMPIC_MEDALS,
)

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


def get_rakuten_app_id():
    """APIキー(applicationId)を secrets / 環境変数 / 入力欄 から取得"""
    try:
        v = st.secrets.get("RAKUTEN_APP_ID")
        if v:
            return v
    except Exception:
        pass
    if os.environ.get("RAKUTEN_APP_ID"):
        return os.environ["RAKUTEN_APP_ID"]
    return st.session_state.get("rakuten_app_id", "")


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


def number_row(prefix, pi, holes, labels, defaults, minv, maxv):
    """ホールごとの number_input を横並びで作り、値リストを返す"""
    vals = []
    cols = st.columns(len(holes))
    for c, h, lab in zip(cols, holes, labels):
        with c:
            vals.append(st.number_input(
                lab, min_value=minv, max_value=maxv,
                value=defaults[h], key=f"{prefix}_{pi}_{h}",
            ))
    return vals

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

st.title("⛳ ゴルフスコア集計")

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

        # ゴルフ場検索（名前の一部で絞り込み）
        search = st.text_input("🔍 ゴルフ場を検索", key="course_search",
                               placeholder="名前の一部を入力（例: 霞）")
        if search.strip():
            filtered = [n for n in course_names if search.strip().lower() in n.lower()]
            if not filtered:
                st.caption("該当なし → 全件を表示します。")
                filtered = course_names
        else:
            filtered = course_names

        selected_course_name = st.selectbox("ゴルフ場を選択", filtered,
                                            key="score_course_select")
        selected_course = next(c for c in courses if c["name"] == selected_course_name)
        pars = selected_course["pars"]
        num_holes = selected_course["holes"]
        course_hdcps = selected_course.get("hdcps") or []
        course_tees = selected_course.get("tees") or []

        # ティー選択：初期はRegular、以降は前回保存したティーを記憶
        selected_tee = None
        tee_yards = []
        if course_tees:
            desired = prefs.get("last_tee") or "Regular"
            if ("tee_select" not in st.session_state
                    or st.session_state.get("tee_select") not in course_tees):
                st.session_state["tee_select"] = (
                    desired if desired in course_tees else course_tees[0]
                )
            selected_tee = st.selectbox("ティー", course_tees, key="tee_select")
            tee_yards = selected_course["yards"].get(selected_tee, [])

        # コース情報（Par / HDCP / ヤード）の参照表
        with st.expander("📋 コース情報（Par・HDCP・ヤード）"):
            tees_yards = [(f"{selected_tee}(Y)", tee_yards)] if selected_tee else []
            st.dataframe(
                make_info_table(num_holes, pars, course_hdcps, tees_yards),
                use_container_width=True,
            )

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
                             "olympic": olympic_rule, "point": point_rule}
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
        }

        st.subheader("プレーヤー設定")
        existing_players = get_all_player_names()

        # 自分の名前は前回を記憶（次回以降は自動入力）
        if "player_name_0" not in st.session_state:
            st.session_state["player_name_0"] = prefs.get("my_name", "")

        num_players = st.radio("プレーヤー数", [1, 2, 3, 4], horizontal=True)

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

        if all(players):
            st.subheader("スコア入力")
            all_scores = {}
            all_putts = {}

            for pi, player_name in enumerate(players):
                st.markdown(f"**{player_name}**")
                putt_defaults = [2] * num_holes

                if num_holes == 18:
                    st.markdown("*スコア OUT (1-9)*")
                    sc = number_row("score", pi, range(9),
                                    [f"H{h+1}(P{pars[h]})" for h in range(9)],
                                    pars, 1, 20)
                    st.markdown("*スコア IN (10-18)*")
                    sc += number_row("score", pi, range(9, 18),
                                     [f"H{h+1}(P{pars[h]})" for h in range(9, 18)],
                                     pars, 1, 20)
                    st.caption(f"OUT {sum(sc[:9])} / IN {sum(sc[9:])} / "
                               f"TOTAL **{sum(sc)}** (Par {sum(pars)})")

                    with st.expander("🟢 パット数を入力", expanded=False):
                        st.markdown("*パット OUT (1-9)*")
                        pt = number_row("putt", pi, range(9),
                                        [f"H{h+1}" for h in range(9)],
                                        putt_defaults, 0, 10)
                        st.markdown("*パット IN (10-18)*")
                        pt += number_row("putt", pi, range(9, 18),
                                         [f"H{h+1}" for h in range(9, 18)],
                                         putt_defaults, 0, 10)
                        st.caption(f"パット合計: **{sum(pt)}**")
                else:
                    st.markdown("*スコア*")
                    sc = number_row("score", pi, range(num_holes),
                                    [f"H{h+1}(P{pars[h]})" for h in range(num_holes)],
                                    pars, 1, 20)
                    st.caption(f"TOTAL **{sum(sc)}** (Par {sum(pars)})")
                    with st.expander("🟢 パット数を入力", expanded=False):
                        pt = number_row("putt", pi, range(num_holes),
                                        [f"H{h+1}" for h in range(num_holes)],
                                        putt_defaults, 0, 10)
                        st.caption(f"パット合計: **{sum(pt)}**")

                all_scores[player_name] = sc
                all_putts[player_name] = pt
                st.divider()

            # ===== ライブ・ゲーム集計（入力しながら途中経過を表示） =====
            # 保存処理でも参照するため、人数に関わらず既定値を用意しておく
            live_olympic = None
            medals = {}
            hcap_games = []
            raw_hdcp = {n: 0 for n in players}
            ty_handicaps = {n: 0 for n in players}
            bg_player_hdcps = None
            bg_override = None
            st.subheader("📊 現在のゲーム状況（ライブ）")
            st.caption("※ ゲームの種類・得点ルールは上の「🎮 ゲーム設定」で変更できます。")

            through = st.number_input(
                "集計対象ホール数（スルー）", min_value=1, max_value=num_holes,
                value=num_holes, key="live_through",
                help="ここまで消化したホール数。未入力ホールはParのまま計算されます。",
            )

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
                            key="hcap_mode", horizontal=True)
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
                    o_order = sorted(players, key=lambda n: o_tot[n], reverse=True)
                    st.dataframe(pd.DataFrame({
                        "順": [f"{i+1}" for i in range(len(o_order))],
                        "名前": o_order,
                        "得点": [o_tot[n] for n in o_order],
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
                        st.warning("ラスベガスは4人ちょうどで行います。")
                    else:
                        lv_t1 = st.multiselect(
                            "チーム1（2人選択）", players, key="lv_team1",
                            max_selections=2)
                        if len(lv_t1) != 2:
                            st.info("チーム1のメンバーを2人選んでください。")
                        else:
                            lv_t2 = [n for n in players if n not in lv_t1]
                            lv = las_vegas_results(
                                lv_t1, lv_t2, {n: all_scores[n] for n in players},
                                num_holes=num_holes, played_count=through)
                            st.dataframe(pd.DataFrame({
                                "チーム": [f"{lv_t1[0]}＋{lv_t1[1]}",
                                         f"{lv_t2[0]}＋{lv_t2[1]}"],
                                "得点": [f"{lv['net1']:+d}", f"{lv['net2']:+d}"],
                            }), use_container_width=True, hide_index=True)
                            lead = ("チーム1 リード" if lv["net1"] > 0 else
                                    "チーム2 リード" if lv["net1"] < 0 else "同点")
                            st.markdown(f"**{lead}**")
            else:
                # 1人プレーは対パーの状況のみ
                me = players[0]
                cur = sum(all_scores[me][:through])
                par_cur = sum(pars[:through])
                st.metric(f"{me} スルー{through}H",
                          f"{cur} (Par {par_cur})", f"{cur - par_cur:+d}")
                st.caption("ゲーム集計（タテ/ヨコ/オリンピック）は2人以上で表示されます。")

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
                if "ラスベガス" in games_sel and len(lv_t1) == 2:
                    round_data["lasvegas"] = {"team1": lv_t1}
                save_round(round_data)
                # 次回のために自分の名前・ティー・やるゲーム・ルール・HDCPを記憶
                _pref_kwargs = dict(my_name=players[0], last_tee=selected_tee,
                                    games=games_sel, rules=current_rules)
                if hcap_games and any(raw_hdcp.values()):
                    saved_ph = dict(prefs.get("player_hdcps", {}))
                    saved_ph.update(raw_hdcp)
                    _pref_kwargs["player_hdcps"] = saved_ph
                update_prefs(**_pref_kwargs)
                st.success("スコアを保存しました！")
                st.balloons()
        else:
            st.info("全プレーヤーの名前を入力してください。")

# --- タブ2: 集計・分析 ---
with tab2:
    st.header("集計・分析")

    all_players = get_all_player_names()
    if not all_players:
        st.info("スコアデータがありません。まずスコアを入力してください。")
    else:
        selected_player = st.selectbox("プレーヤーを選択", all_players, key="stats_player")

        hole_avgs = get_hole_averages(selected_player)

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
        if _scores:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ラウンド数", f"{len(_scores)}")
            m2.metric("平均スコア", f"{sum(_scores)/len(_scores):.1f}")
            m3.metric("ベストスコア", f"{min(_scores)}")
            if _putts:
                m4.metric("平均パット", f"{sum(_putts)/len(_putts):.1f}")
            else:
                m4.metric("平均パット", "—")

        if hole_avgs:
            st.subheader(f"{selected_player} のホール別平均スコア")

            df = pd.DataFrame(hole_avgs)

            df_display = df.copy()
            df_display.columns = ["ホール", "平均スコア", "ベスト", "ワースト", "ラウンド数", "Par"]
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            st.subheader("ホール別パフォーマンス")

            fig = go.Figure()

            par_values = []
            avg_values = []
            hole_labels = []
            for h in hole_avgs:
                hole_labels.append(f"H{h['hole']}")
                avg_values.append(h["avg_score"])
                par_values.append(h["par"] if h["par"] != "-" else 0)

            fig.add_trace(go.Bar(
                x=hole_labels, y=avg_values,
                name="平均スコア",
                marker_color=["#ff6b6b" if a > p else "#51cf66" if a < p else "#339af0"
                               for a, p in zip(avg_values, par_values)],
                text=[f"{v}" for v in avg_values],
                textposition="outside",
            ))

            if any(p > 0 for p in par_values):
                fig.add_trace(go.Scatter(
                    x=hole_labels, y=par_values,
                    name="Par",
                    mode="lines+markers",
                    line=dict(color="#868e96", dash="dash"),
                ))

            fig.update_layout(
                height=400,
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                yaxis_title="打数",
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption("🟢 Parより良い　🔵 Par通り　🔴 Parより悪い（苦手ホール）")

            # スコア推移
            rounds = load_rounds()
            player_rounds = []
            for r in rounds:
                for p in r["players"]:
                    if p["name"] == selected_player:
                        player_rounds.append({
                            "date": r["date"],
                            "course": r["course_name"],
                            "total": sum(p["scores"]),
                            "par": sum(r.get("pars", [])),
                        })

            if len(player_rounds) > 1:
                st.subheader("スコア推移")
                df_rounds = pd.DataFrame(player_rounds)
                fig2 = px.line(
                    df_rounds, x="date", y="total",
                    markers=True,
                    labels={"date": "日付", "total": "トータルスコア"},
                    hover_data=["course"],
                )
                fig2.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
                st.plotly_chart(fig2, use_container_width=True)

            # 得意・苦手ホール
            st.subheader("得意・苦手ホール TOP3")
            diffs = []
            for h in hole_avgs:
                par = h["par"] if h["par"] != "-" else 0
                if par > 0:
                    diffs.append({
                        "hole": h["hole"],
                        "diff": round(h["avg_score"] - par, 1),
                        "avg": h["avg_score"],
                        "par": par,
                    })

            if diffs:
                diffs_sorted = sorted(diffs, key=lambda x: x["diff"])
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("**🟢 得意ホール**")
                    for d in diffs_sorted[:3]:
                        sign = "+" if d["diff"] > 0 else ""
                        st.markdown(f"- H{d['hole']}: 平均{d['avg']} (Par{d['par']}, {sign}{d['diff']})")

                with col2:
                    st.markdown("**🔴 苦手ホール**")
                    for d in diffs_sorted[-3:][::-1]:
                        sign = "+" if d["diff"] > 0 else ""
                        st.markdown(f"- H{d['hole']}: 平均{d['avg']} (Par{d['par']}, {sign}{d['diff']})")
        else:
            st.info(f"{selected_player} のスコアデータがありません。")

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
                lv_saved = (gr.get("lasvegas") or {}).get("team1") or []
                if len(g_names) != 4:
                    st.warning("ラスベガスは4人ちょうどのラウンドが対象です。")
                else:
                    default_t1 = [n for n in lv_saved if n in g_names]
                    lv_t1 = st.multiselect(
                        "チーム1（2人選択）", g_names,
                        default=default_t1 if len(default_t1) == 2 else [],
                        max_selections=2, key=f"lv5_team1_{gr['id']}")
                    if len(lv_t1) != 2:
                        st.info("チーム1のメンバーを2人選んでください。")
                    else:
                        lv_t2 = [n for n in g_names if n not in lv_t1]
                        lv = las_vegas_results(
                            lv_t1, lv_t2,
                            {p["name"]: p["scores"] for p in g_players},
                            num_holes=g_num)
                        st.dataframe(pd.DataFrame({
                            "チーム": [f"{lv_t1[0]}＋{lv_t1[1]}",
                                     f"{lv_t2[0]}＋{lv_t2[1]}"],
                            "得点": [f"{lv['net1']:+d}", f"{lv['net2']:+d}"],
                        }), use_container_width=True, hide_index=True)
                        win = ("チーム1の勝ち" if lv["net1"] > 0 else
                               "チーム2の勝ち" if lv["net1"] < 0 else "引き分け")
                        st.markdown(f"### {win}")
                        with st.expander("ホール別明細"):
                            st.dataframe(pd.DataFrame([{
                                "H": d["hole"], "チーム1": d["n1"],
                                "チーム2": d["n2"], "差": f"{d['diff']:+d}",
                            } for d in lv["per_hole"]]),
                                use_container_width=True, hide_index=True)
                        if st.button("💾 チーム設定を保存", key=f"lv5save_{gr['id']}"):
                            update_round(gr["id"], lasvegas={"team1": lv_t1})
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
        with st.expander("⚙️ APIキー設定（楽天 applicationId）", expanded=not bool(app_id)):
            st.caption("楽天ウェブサービス(webservice.rakuten.co.jp)で無料取得した "
                       "applicationId を入力してください。一度入力すれば保持されます。")
            key_in = st.text_input("楽天 applicationId", value=app_id,
                                   type="password", key="app_id_input")
            if key_in:
                st.session_state["rakuten_app_id"] = key_in
                app_id = key_in

        kw = st.text_input("ゴルフ場名で検索", key="search_keyword",
                           placeholder="例: 霞ヶ関カンツリー")
        if st.button("🔍 検索", use_container_width=True):
            if not app_id:
                st.error("APIキー(applicationId)を入力してください。")
            elif not kw:
                st.error("ゴルフ場名を入力してください。")
            else:
                res = search_rakuten(kw, app_id)
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
