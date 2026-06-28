"""データ保存層。

保存先を自動で切り替える（優先順）:
  1. DB_URL（st.secrets["db_url"] か環境変数 DB_URL）があれば → Postgres(Supabase等)
  2. Google Sheets の設定があれば → Googleスプレッドシート
  3. どちらも無ければ → ローカルのJSONファイル（data/*.json）

いずれも "courses" / "rounds" / "prefs" の3つのJSONを丸ごと保存する
（少人数の個人用途向け）。
"""
import json
import os
import time
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_FILES = {
    "courses": os.path.join(DATA_DIR, "courses.json"),
    "rounds": os.path.join(DATA_DIR, "rounds.json"),
    "prefs": os.path.join(DATA_DIR, "prefs.json"),
}

_engine = None
_gs_ws = None

# API節約用キャッシュ（key -> (timestamp, value)）。"__all__" はSheets全体。
_cache = {}
_CACHE_TTL = 8  # 秒


def _gs_read_all():
    """Google Sheets の app_data 全体を1回の読み取りで取得しキャッシュする。"""
    now = time.time()
    c = _cache.get("__all__")
    if c and now - c[0] < _CACHE_TTL:
        return c[1]
    ws = _get_ws()
    rows = ws.get_all_values()  # [[key, value], ...]（1行目はヘッダ）
    d = {}
    for r in rows:
        if len(r) >= 2 and r[0] and r[0] != "key":
            d[r[0]] = r[1]
    _cache["__all__"] = (now, d)
    return d


def clear_cache():
    _cache.clear()


def _db_url():
    """DB接続URLを secrets / 環境変数 から取得（無ければ None＝ファイル保存）"""
    try:
        import streamlit as st
        if "db_url" in st.secrets:
            return st.secrets["db_url"]
    except Exception:
        pass
    return os.environ.get("DB_URL")


def _gsheets_conf():
    """Google Sheets の設定（service accountとシートID）を取得。無ければ None。"""
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets and "gsheet_id" in st.secrets:
            return dict(st.secrets["gcp_service_account"]), st.secrets["gsheet_id"]
    except Exception:
        pass
    return None


def _backend():
    if os.environ.get("GOLF_BACKEND") == "file":  # テスト用にファイル保存を強制
        return "file"
    if _db_url():
        return "pg"
    if _gsheets_conf():
        return "gs"
    return "file"


def _get_ws():
    """Google Sheets の app_data ワークシートを返す（無ければ作成）。"""
    global _gs_ws
    if _gs_ws is None:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_info, sheet_id = _gsheets_conf()
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        try:
            ws = sh.worksheet("app_data")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title="app_data", rows=100, cols=2)
            ws.update("A1:B1", [["key", "value"]])
        _gs_ws = ws
    return _gs_ws


def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        url = _db_url()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        _engine = create_engine(url, pool_pre_ping=True)
        with _engine.begin() as con:
            con.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS app_data "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
    return _engine


def _load(key, default):
    """key に対応するJSONを読み込む（API節約のためキャッシュ）。"""
    backend = _backend()
    if backend == "gs":
        data = _gs_read_all()
        raw = data.get(key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return default
        return default
    if backend == "pg":
        now = time.time()
        c = _cache.get(key)
        if c and now - c[0] < _CACHE_TTL:
            return c[1]
        from sqlalchemy import text
        eng = _get_engine()
        with eng.begin() as con:
            row = con.execute(
                text("SELECT value FROM app_data WHERE key=:k"), {"k": key}
            ).fetchone()
        val = default
        if row and row[0]:
            try:
                val = json.loads(row[0])
            except Exception:
                val = default
        _cache[key] = (now, val)
        return val
    # ファイル保存
    os.makedirs(DATA_DIR, exist_ok=True)
    path = _FILES[key]
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _store(key, value):
    """key に value(JSON可能なオブジェクト) を保存する。"""
    backend = _backend()
    payload = json.dumps(value, ensure_ascii=False)
    if backend == "gs":
        ws = _get_ws()
        keys = ws.col_values(1)
        if key in keys:
            ws.update_cell(keys.index(key) + 1, 2, payload)
        else:
            ws.append_row([key, payload])
        # キャッシュを更新（保存直後に再読込しないで済むように）
        c = _cache.get("__all__")
        if c:
            c[1][key] = payload
        return
    if backend == "pg":
        from sqlalchemy import text
        eng = _get_engine()
        with eng.begin() as con:
            con.execute(text(
                "INSERT INTO app_data(key, value) VALUES(:k, :v) "
                "ON CONFLICT(key) DO UPDATE SET value=:v"
            ), {"k": key, "v": payload})
        _cache[key] = (time.time(), value)
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_FILES[key], "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def ensure_data_dir():
    """互換用（ファイル保存時のみ意味を持つ）。"""
    if _backend() == "file":
        os.makedirs(DATA_DIR, exist_ok=True)


# ---------- prefs ----------
def load_prefs():
    return _load("prefs", {})


def save_prefs(prefs):
    _store("prefs", prefs)


def update_prefs(**kwargs):
    prefs = load_prefs()
    prefs.update({k: v for k, v in kwargs.items() if v is not None})
    save_prefs(prefs)
    return prefs


# ---------- courses ----------
def load_courses():
    return _load("courses", [])


def save_course(course):
    """コースを保存する。同名コースがあれば上書き、なければ追加する。"""
    courses = load_courses()
    replaced = False
    for i, c in enumerate(courses):
        if c["name"] == course["name"]:
            courses[i] = course
            replaced = True
            break
    if not replaced:
        courses.append(course)
    _store("courses", courses)
    return {"course": course, "replaced": replaced}


def delete_course(name):
    courses = [c for c in load_courses() if c["name"] != name]
    _store("courses", courses)


def course_exists(name):
    return any(c["name"] == name for c in load_courses())


# ---------- rounds ----------
def load_rounds():
    return _load("rounds", [])


def save_round(round_data):
    rounds = load_rounds()
    next_id = max([r.get("id", 0) for r in rounds], default=0) + 1
    round_data["id"] = next_id
    round_data["created_at"] = datetime.now().isoformat()
    rounds.append(round_data)
    _store("rounds", rounds)
    return round_data


def delete_round(round_id):
    rounds = [r for r in load_rounds() if r.get("id") != round_id]
    _store("rounds", rounds)


def update_round(round_id, **fields):
    """指定ラウンドにフィールドを追記・更新する（オリンピックの点数保存など）"""
    rounds = load_rounds()
    for r in rounds:
        if r.get("id") == round_id:
            r.update(fields)
            break
    _store("rounds", rounds)


# ---------- 集計ヘルパー ----------
def get_player_stats(player_name):
    rounds = load_rounds()
    player_scores = []
    for r in rounds:
        for p in r["players"]:
            if p["name"] == player_name:
                player_scores.append({
                    "date": r["date"],
                    "course": r["course_name"],
                    "scores": p["scores"],
                    "total": sum(p["scores"]),
                })
    return player_scores


def get_hole_averages(player_name):
    rounds = load_rounds()
    hole_scores = {}
    hole_pars = {}
    for r in rounds:
        pars = r.get("pars", [])
        for p in r["players"]:
            if p["name"] == player_name:
                for i, score in enumerate(p["scores"]):
                    hole_num = i + 1
                    if hole_num not in hole_scores:
                        hole_scores[hole_num] = []
                        hole_pars[hole_num] = []
                    hole_scores[hole_num].append(score)
                    if i < len(pars):
                        hole_pars[hole_num].append(pars[i])
    result = []
    for hole_num in sorted(hole_scores.keys()):
        scores = hole_scores[hole_num]
        pars = hole_pars.get(hole_num, [])
        avg_par = sum(pars) / len(pars) if pars else 0
        result.append({
            "hole": hole_num,
            "avg_score": round(sum(scores) / len(scores), 1),
            "min_score": min(scores),
            "max_score": max(scores),
            "count": len(scores),
            "par": round(avg_par, 1) if avg_par else "-",
        })
    return result


def get_all_player_names():
    rounds = load_rounds()
    names = set()
    for r in rounds:
        for p in r["players"]:
            names.add(p["name"])
    return sorted(names)


def _iter_player_holes(player_name):
    """そのプレーヤーの全ホールを (par, score) で列挙する（全ラウンド横断）。"""
    for r in load_rounds():
        pars = r.get("pars", [])
        for p in r["players"]:
            if p["name"] == player_name:
                for i, s in enumerate(p["scores"]):
                    if i < len(pars) and pars[i]:
                        yield pars[i], s


def get_par_type_stats(player_name):
    """Par3/4/5 ごとの平均スコア・対パーを集計（コース非依存で意味がある）。"""
    buckets = {}
    for par, s in _iter_player_holes(player_name):
        buckets.setdefault(par, []).append(s)
    result = []
    for par in sorted(buckets):
        scores = buckets[par]
        avg = sum(scores) / len(scores)
        result.append({
            "par": par,
            "label": f"Par {par}",
            "avg_score": round(avg, 2),
            "vs_par": round(avg - par, 2),
            "count": len(scores),
        })
    return result


def get_score_breakdown(player_name):
    """スコアの内訳（バーディ/パー/ボギー…）をカウント。"""
    cats = {"イーグル以上": 0, "バーディ": 0, "パー": 0,
            "ボギー": 0, "ダブルボギー": 0, "トリプル以上": 0}
    total = 0
    for par, s in _iter_player_holes(player_name):
        total += 1
        d = s - par
        if d <= -2:
            cats["イーグル以上"] += 1
        elif d == -1:
            cats["バーディ"] += 1
        elif d == 0:
            cats["パー"] += 1
        elif d == 1:
            cats["ボギー"] += 1
        elif d == 2:
            cats["ダブルボギー"] += 1
        else:
            cats["トリプル以上"] += 1
    return cats, total


def get_player_courses(player_name):
    """そのプレーヤーがプレーしたコース名とラウンド数。"""
    counts = {}
    for r in load_rounds():
        if any(p["name"] == player_name for p in r["players"]):
            counts[r["course_name"]] = counts.get(r["course_name"], 0) + 1
    return counts


def get_recent_putt_avg(player_name, n=10):
    """直近n回（パット記録があるラウンドのみ）の平均パット。
    Returns: (平均, 件数)。記録が無ければ (None, 0)。
    """
    rounds = sorted(load_rounds(),
                    key=lambda r: (r.get("date", ""), r.get("id", 0)),
                    reverse=True)
    vals = []
    for r in rounds:
        for p in r["players"]:
            if p["name"] == player_name:
                pts = p.get("putts") or []
                if any(pts):
                    vals.append(sum(pts))
    vals = vals[:n]
    if not vals:
        return None, 0
    return round(sum(vals) / len(vals), 1), len(vals)


def get_course_score_averages(player_name):
    """コースごとの平均スコア・ベスト・ラウンド数。"""
    data = {}
    for r in load_rounds():
        for p in r["players"]:
            if p["name"] == player_name:
                data.setdefault(r["course_name"], []).append(sum(p["scores"]))
    result = []
    for course, totals in data.items():
        result.append({
            "course": course,
            "avg": round(sum(totals) / len(totals), 1),
            "best": min(totals),
            "count": len(totals),
        })
    return sorted(result, key=lambda x: x["course"])


def get_course_hole_averages(player_name, course_name):
    """指定コースに限定したホール別平均（同一コースを複数回プレーした時に意味を持つ）。
    Returns: (per_hole list, round_count)
    """
    hole_scores = {}
    pars_ref = []
    rcount = 0
    for r in load_rounds():
        if r["course_name"] != course_name:
            continue
        played = False
        for p in r["players"]:
            if p["name"] == player_name:
                played = True
                for i, s in enumerate(p["scores"]):
                    hole_scores.setdefault(i, []).append(s)
                if not pars_ref:
                    pars_ref = r.get("pars", [])
        if played:
            rcount += 1
    result = []
    for i in sorted(hole_scores.keys()):
        scores = hole_scores[i]
        par = pars_ref[i] if i < len(pars_ref) else None
        result.append({
            "hole": i + 1,
            "par": par,
            "avg_score": round(sum(scores) / len(scores), 1),
            "min_score": min(scores),
            "max_score": max(scores),
            "count": len(scores),
        })
    return result, rcount
