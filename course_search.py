"""ゴルフ場情報の取得モジュール（楽天GORA）

2つの方法をサポート:
  方法1: 楽天GORA ゴルフ場検索API でコース名 → c_id を取得（要 applicationId）
  方法2: 楽天GORAのコースURL（または c_id）を直接指定

どちらの場合も、各ホールのPar/ヤードは
  https://booking.gora.golf.rakuten.co.jp/guide/layout_disp/c_id/<c_id>/
をスクレイピングして取得する（APIでは取得不可のため）。
"""
import re
import io
import requests
import pandas as pd
from bs4 import BeautifulSoup

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

RAKUTEN_SEARCH_ENDPOINT = (
    "https://app.rakuten.co.jp/services/api/Gora/GoraGolfCourseSearch/20170623"
)
LAYOUT_URL_TMPL = "https://booking.gora.golf.rakuten.co.jp/guide/layout_disp/c_id/{cid}/"


def extract_cid(text):
    """入力文字列（URL or 数字）から c_id を抽出する"""
    text = text.strip()
    if text.isdigit():
        return text
    m = re.search(r"c_id/(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4,7})", text)
    if m:
        return m.group(1)
    return None


def search_rakuten(keyword, application_id, hits=20):
    """楽天GORA ゴルフ場検索APIでコースを検索する。

    Returns: list of dict {golfCourseId, golfCourseName, prefecture, ...}
    エラー時は ("error", メッセージ) を返す。
    """
    params = {
        "applicationId": application_id,
        "keyword": keyword,
        "hits": hits,
        "format": "json",
    }
    try:
        r = requests.get(RAKUTEN_SEARCH_ENDPOINT, params=params, headers=UA, timeout=15)
    except Exception as e:
        return ("error", f"通信エラー: {e}")

    if r.status_code != 200:
        try:
            err = r.json()
            msg = err.get("error_description", r.text[:200])
        except Exception:
            msg = r.text[:200]
        return ("error", f"APIエラー ({r.status_code}): {msg}")

    data = r.json()
    items = data.get("Items", [])
    results = []
    for it in items:
        g = it.get("Item", it)
        results.append({
            "golfCourseId": g.get("golfCourseId"),
            "golfCourseName": g.get("golfCourseName"),
            "prefecture": g.get("prefecture", ""),
            "areaName": g.get("areaName", ""),
            "evaluation": g.get("evaluation", ""),
            "golfCourseCaption": g.get("golfCourseCaption", ""),
        })
    return results


HDCP_LABELS = ("HDCP", "HCP", "HANDICAP", "ハンディ", "ハンデ", "ハンディキャップ")


def _is_num(v):
    return str(v).replace(",", "").replace(".", "").strip().isdigit()


def _parse_hole_table(df):
    """1つの表(DataFrame)からホール情報を抽出する。
    HOLE / PAR / HDCP 行と、各ティー（Champion, Back, Regular, Front...）の
    ヤード行をすべて取り込む。
    各ホール: {"hole":1, "par":4, "hdcp":9, "yards":{"Back":428,...}}
    """
    if df.shape[0] < 2:
        return []
    labels = [str(x).strip() for x in df.iloc[:, 0].tolist()]
    upper = [l.upper() for l in labels]
    if "HOLE" not in upper or "PAR" not in upper:
        return []

    hole_row = df.iloc[upper.index("HOLE")].tolist()
    par_row = df.iloc[upper.index("PAR")].tolist()

    hdcp_row = None
    for key in HDCP_LABELS:
        if key in upper:
            hdcp_row = df.iloc[upper.index(key)].tolist()
            break

    # ティー行（HOLE/PAR/HDCP 以外で数値が多く並ぶ行）を順序保持で収集
    tee_rows = []  # (ティー名, 値リスト)
    for idx in range(len(upper)):
        if upper[idx] in ("HOLE", "PAR") or upper[idx] in HDCP_LABELS:
            continue
        name = labels[idx]
        if not name or name.lower() == "nan":
            continue
        vals = df.iloc[idx].tolist()
        nums = [v for v in vals[1:] if _is_num(v)]
        if len(nums) >= 5:
            tee_rows.append((name, vals))

    holes = []
    for col in range(1, len(hole_row)):
        hnum = str(hole_row[col]).strip()
        par_v = str(par_row[col]).strip()
        if not hnum.isdigit() or not par_v.replace(".", "").isdigit():
            continue
        hole = int(hnum)
        par = int(float(par_v))
        if hole < 1 or hole > 18 or par < 3 or par > 6:
            continue

        yards = {}
        for name, vals in tee_rows:
            if col < len(vals):
                yv = str(vals[col]).replace(",", "").strip()
                if yv.isdigit():
                    yards[name] = int(yv)

        hdcp = None
        if hdcp_row and col < len(hdcp_row):
            hv = str(hdcp_row[col]).strip()
            if hv.isdigit():
                hdcp = int(hv)

        holes.append({"hole": hole, "par": par, "hdcp": hdcp, "yards": yards})
    return holes


def _course_name_from_label(label):
    """'東コースOUT' などのラベルからコース名(東コース)を取り出す"""
    if not label:
        return None
    name = re.sub(r"\s*(OUT|IN|アウトコース|インコース|アウト|イン)\s*$", "", label).strip()
    return name or None


def _build_course(name, holes):
    """ホールのリストを1コースにまとめる（重複ホールは最初を優先）"""
    seen = {}
    for h in holes:
        if h["hole"] not in seen:
            seen[h["hole"]] = h
    hs = [seen[k] for k in sorted(seen.keys())]
    return {
        "course_name": name or "",
        "holes": hs,
        "total_par": sum(h["par"] for h in hs),
        "hole_count": len(hs),
    }


def fetch_holes_from_layout(cid):
    """コースレイアウトページから各ホールのPar/ヤードを取得する。
    複数コース（東/西など）がある場合は全コースを返す。

    Returns: dict {
        "cid": str, "url": str,
        "courses": [
            {"course_name":"東コース", "holes":[{"hole":1,"par":4,"yard":371},...],
             "total_par":72, "hole_count":18}, ...
        ]
    }
    取得失敗時は ("error", メッセージ)
    """
    url = LAYOUT_URL_TMPL.format(cid=cid)
    try:
        r = requests.get(url, headers=UA, timeout=15)
    except Exception as e:
        return ("error", f"通信エラー: {e}")
    if r.status_code != 200:
        return ("error", f"ページ取得失敗 ({r.status_code})")
    r.encoding = "utf-8"

    soup = BeautifulSoup(r.text, "html.parser")

    # ページから実際のゴルフ場名を取得（URL違いの検知用）
    page_name = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        page_name = og["content"].strip()
    elif soup.title and soup.title.string:
        page_name = soup.title.string.strip()
    # 余計な接尾辞を除去
    page_name = re.sub(
        r"\s*(の)?(コース情報|コースレイアウト|コースガイド).*$", "", page_name
    ).strip()
    page_name = re.sub(r"\s*[\|｜【].*$", "", page_name).strip()

    # (ラベル, ホールリスト) を出現順に収集
    raw = []
    for tb in soup.find_all("table"):
        txt = tb.get_text(" ", strip=True).upper()
        if "HOLE" not in txt or "PAR" not in txt:
            continue
        node = tb.find_previous(string=lambda s: s and "コース" in s)
        label = node.strip() if node else None
        try:
            dfs = pd.read_html(io.StringIO(str(tb)))
        except Exception:
            continue
        if not dfs:
            continue
        holes = _parse_hole_table(dfs[0])
        if holes:
            raw.append((label, holes))

    if not raw:
        return ("error", "ホール情報が見つかりませんでした。URL/IDをご確認ください。")

    courses = []
    has_named = any(_course_name_from_label(lbl) for lbl, _ in raw)

    if has_named:
        # コース名でグルーピング（東コースOUT + 東コースIN → 東コース）
        groups, order = {}, []
        for label, holes in raw:
            cn = _course_name_from_label(label) or "本コース"
            if cn not in groups:
                groups[cn] = []
                order.append(cn)
            groups[cn].extend(holes)
        for cn in order:
            courses.append(_build_course(cn, groups[cn]))
    else:
        # ラベルが無い場合: ホール番号1を境にコースを分割
        cur = []
        for label, holes in raw:
            minh = min(h["hole"] for h in holes)
            if minh == 1 and cur:
                nm = f"コース{len(courses) + 1}"
                courses.append(_build_course(nm, cur))
                cur = []
            cur.extend(holes)
        if cur:
            nm = "" if not courses else f"コース{len(courses) + 1}"
            courses.append(_build_course(nm, cur))

    return {"cid": str(cid), "url": url, "page_name": page_name, "courses": courses}


def create_manual_course(name, holes_data):
    """コース情報を作成する。
    holes_data の各要素は {"hole","par"} 最低限、任意で "hdcp","yards"(dict) を含む。
    """
    pars = [h["par"] for h in holes_data]
    hdcps = [h.get("hdcp") for h in holes_data]

    # ティー名を出現順に収集
    tee_names = []
    for h in holes_data:
        for t in (h.get("yards") or {}):
            if t not in tee_names:
                tee_names.append(t)

    # ティーごとのヤード配列
    yards_by_tee = {
        t: [(h.get("yards") or {}).get(t) for h in holes_data]
        for t in tee_names
    }

    return {
        "name": name,
        "holes": len(holes_data),
        "hole_data": holes_data,
        "pars": pars,
        "hdcps": hdcps,
        "tees": tee_names,
        "yards": yards_by_tee,
        "total_par": sum(pars),
    }


def create_default_18hole_course(name):
    """デフォルトの18ホールコースを作成（Par 72）"""
    default_pars = [4, 3, 4, 5, 4, 3, 4, 5, 4, 4, 3, 4, 5, 4, 3, 4, 5, 4]
    holes_data = [{"hole": i + 1, "par": p} for i, p in enumerate(default_pars)]
    return create_manual_course(name, holes_data)
