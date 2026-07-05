"""course_info.py — 楽天GORA「コース情報」ページのパーサ

対象URL:
  https://booking.gora.golf.rakuten.co.jp/guide/course_info/disp/c_id/<c_id>/
このページには HOLE/PAR/ティー別ヤード/HDCP の各ナイン表と、
末尾にティー別コースレーティング(CR)表が載っている（サーバーサイド描画）。

方針:
  - 各ナイン表(OUT=H1-9 / IN=H10-18)を抽出し、OUT+INをペアにして1コースへまとめる。
  - Par / ティー別ヤード / HDCP を取得。
  - HDCP が 1..9 の連番なら「要確認(誤りの可能性)」フラグを立てる（楽天の既知の癖）。
  - CR表(日本語ティー→CR→合計ヤード)と、各ティーの18ヤード合計を突き合わせ、
    英語ティー(Regular等)↔日本語ティー(ブルー等)↔CR を自動対応させる。
  - SR(スロープレーティング)は楽天に無いので、取り込みUI側で手入力する（ここでは扱わない）。
"""
import re
import io
import requests
from bs4 import BeautifulSoup
import pandas as pd  # noqa: F401  (将来の拡張用)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
INFO_URL = "https://booking.gora.golf.rakuten.co.jp/guide/course_info/disp/c_id/{cid}/"

_HDCP_LABELS = ("HDCP", "HCP", "HANDICAP", "ハンディ", "ハンデ")


def extract_cid(text: str):
    """URL or 数字文字列から c_id を取り出す。"""
    text = (text or "").strip()
    if text.isdigit():
        return text
    m = re.search(r"c_id/(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4,7})", text)
    return m.group(1) if m else None


def _to_int(s):
    s = str(s).replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _rows_of(table):
    out = []
    for tr in table.find_all("tr"):
        out.append([c.get_text(strip=True) for c in tr.find_all(["th", "td"])])
    return out


def _parse_nine(rows):
    """1ナイン表の行リスト -> dict or None。
    {which, holes, pars, hdcp, hdcp_suspect, yards{tee:[9]}}"""
    if not rows:
        return None
    label0 = [r for r in rows if r and r[0].upper() == "HOLE"]
    if not label0:
        return None
    head = label0[0]
    # ホール番号（"計"や空を除く数値のみ）
    holes = [_to_int(x) for x in head[1:]]
    holes = [h for h in holes if h is not None]
    if not holes:
        return None
    ncols = len(holes)  # 通常9
    which = "OUT" if min(holes) <= 9 else "IN"

    pars, hdcp, yards = None, None, {}
    for r in rows:
        if not r:
            continue
        key = r[0].strip()
        ku = key.upper()
        vals = [_to_int(x) for x in r[1:1 + ncols]]
        if ku == "PAR":
            pars = vals
        elif ku in _HDCP_LABELS or key in _HDCP_LABELS:
            hdcp = vals
        elif ku == "HOLE":
            continue
        else:
            # ティー行：数値が過半数ならヤードとして採用
            nums = [v for v in vals if isinstance(v, int)]
            if len(nums) >= max(5, ncols - 2) and key:
                yards[key] = vals

    if pars is None:
        return None
    hdcp_suspect = False
    if hdcp and all(isinstance(v, int) for v in hdcp):
        # 1..9 の連番（＝楽天の仮HDCP）を要確認とする
        if hdcp == list(range(1, ncols + 1)):
            hdcp_suspect = True
    return {"which": which, "holes": holes, "pars": pars,
            "hdcp": hdcp, "hdcp_suspect": hdcp_suspect, "yards": yards}


def _parse_cr_table(table):
    """コースレート表 -> [{tee_ja, cr, yard}]。CR列(小数)がある表のみ対象。"""
    rows = _rows_of(table)
    if not rows:
        return None
    header = [c.strip() for c in rows[0]]
    joined = " ".join(header)
    if "コースレーティング" not in joined and "レーティング" not in joined:
        return None
    # 列位置を推定
    def col_idx(keys):
        for i, h in enumerate(header):
            if any(k in h for k in keys):
                return i
        return None
    ci_tee = col_idx(["ティー"])
    ci_cr = col_idx(["コースレーティング", "レーティング"])
    ci_yd = col_idx(["ヤード", "ヤール"])
    out = []
    for r in rows[1:]:
        if not r:
            continue
        tee = r[ci_tee].strip() if ci_tee is not None and ci_tee < len(r) else ""
        cr = None
        if ci_cr is not None and ci_cr < len(r):
            m = re.search(r"\d+\.\d+", r[ci_cr])
            cr = float(m.group()) if m else None
        yd = _to_int(r[ci_yd]) if ci_yd is not None and ci_yd < len(r) else None
        if tee and (cr is not None or yd is not None):
            out.append({"tee_ja": tee, "cr": cr, "yard": yd})
    return out or None


def parse_course_info_html(html: str) -> dict:
    """コース情報ページHTML -> 構造化データ。
    Returns: {cid?, cr_table, courses:[...]}
      courses[i] = {
        pars18, hdcp18, hdcp_suspect, yards18{tee:[18]}, par_total,
        tee_totals{tee:int}, tee_cr{tee:{"tee_ja":.., "cr":..}}  # ヤード合計で対応付け
      }
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    nines, cr_table = [], None
    for t in tables:
        rows = _rows_of(t)
        cr = _parse_cr_table(t)
        if cr:
            cr_table = cr
            continue
        nine = _parse_nine(rows)
        if nine:
            nines.append(nine)

    # OUT+IN をペアにしてコース化（出現順、OUTで新規開始）
    courses, cur = [], None
    for n in nines:
        if n["which"] == "OUT":
            if cur:
                courses.append(cur)
            cur = {"out": n, "in": None}
        else:  # IN
            if cur and cur.get("in") is None:
                cur["in"] = n
            else:
                courses.append({"out": None, "in": n})
                cur = None
    if cur:
        courses.append(cur)

    result_courses = []
    for c in courses:
        o, i = c.get("out"), c.get("in")
        pars, hdcp, yards18 = [], [], {}
        suspect = False
        # ティー名の和集合
        tee_names = []
        for part in (o, i):
            if part:
                for t in part["yards"]:
                    if t not in tee_names:
                        tee_names.append(t)
        for part in (o, i):
            if not part:
                continue
            pars += part["pars"]
            if part["hdcp"]:
                hdcp += part["hdcp"]
            suspect = suspect or part["hdcp_suspect"]
        for t in tee_names:
            seq = []
            for part in (o, i):
                if part:
                    seq += part["yards"].get(t, [None] * 9)
            yards18[t] = seq
        par_total = sum(p for p in pars if isinstance(p, int))
        tee_totals = {t: sum(v for v in ys if isinstance(v, int))
                      for t, ys in yards18.items()}

        # CR表のヤード合計と突き合わせて、英語ティー -> {tee_ja, cr} を対応付け
        tee_cr = {}
        if cr_table:
            for t, total in tee_totals.items():
                best = None
                for row in cr_table:
                    if row.get("yard") is None:
                        continue
                    if best is None or abs(row["yard"] - total) < abs(best["yard"] - total):
                        best = row
                # 合計ヤードが±30以内で一致すれば採用
                if best and abs(best["yard"] - total) <= 30:
                    tee_cr[t] = {"tee_ja": best["tee_ja"], "cr": best["cr"]}

        result_courses.append({
            "pars18": pars,
            "hdcp18": hdcp if len(hdcp) == len(pars) else None,
            "hdcp_suspect": suspect,
            "yards18": yards18,
            "par_total": par_total,
            "tee_totals": tee_totals,
            "tee_cr": tee_cr,
        })

    return {"cr_table": cr_table, "courses": result_courses}


def fetch_course_info(cid_or_url: str):
    """c_id または URL からコース情報を取得してパースする。
    Returns: dict（parse_course_info_html の結果に cid, url を付与） or ("error", msg)
    ネットワークはこの関数を呼ぶ環境（ユーザーPC/Cloud）で実行される。"""
    cid = extract_cid(cid_or_url)
    if not cid:
        return ("error", "c_id を特定できませんでした（URLか数字IDを入力してください）。")
    url = INFO_URL.format(cid=cid)
    try:
        r = requests.get(url, headers=UA, timeout=20)
    except Exception as e:
        return ("error", f"通信エラー: {e}")
    if r.status_code != 200:
        return ("error", f"ページ取得失敗 ({r.status_code})")
    r.encoding = "utf-8"
    data = parse_course_info_html(r.text)
    data["cid"] = cid
    data["url"] = url
    return data
