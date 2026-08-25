"""ocr_score.py — ゴルフ場タッチパネル画面のスコアOCR（コアロジック）

役割:
  - OpenAI Vision に画面画像を投げ、プレーヤー別の9ホール素点をJSONで受け取る。
  - OUT/INを判別し、18ホールの器に流し込む（途中撮影＝残り穴は空のまま）。
  - HALF/TOTAL検算、氏名の名寄せを行う。

現状: Vision呼び出し(_call_vision)は実装済み。OpenAI公式クライアント(openai>=1.30)を
      使い、response_format=json_object・モデル別リトライ（gpt-5系は
      max_completion_tokens/reasoning_effort、旧モデルは max_tokens）で呼ぶ。
      APIキーは環境変数 OPENAI_API_KEY → st.secrets → 画面入力 の順で解決する。
      parse_vision_json / merge_into_round / verify_half などの純ロジックは
      API呼び出し無しで単体でも使える・テストできる。
"""
from __future__ import annotations
import json
import base64

# ---- 氏名の名寄せ（表示名 -> アプリ内プレーヤー名）----
# Visionが読む表示名の揺れ（姓のみ/姓名/全角空白等）を吸収する。
NAME_ALIASES = {
    "蓑輪 宏晃": "hiroaki minowa",
    "蓑輪宏晃": "hiroaki minowa",
    "蓑輪": "hiroaki minowa",
    # 「蓑」は難読でVisionが誤読しやすい（実測: 蓑輪→義輪）。既知の誤読を吸収する。
    "義輪": "hiroaki minowa",
    "みのわ": "hiroaki minowa",
    "hiroaki minowa": "hiroaki minowa",
}


def normalize_name(name_raw: str) -> str | None:
    """表示名をアプリ内プレーヤー名へ名寄せ。未知ならNone（手選択にフォールバック）。"""
    if not name_raw:
        return None
    key = name_raw.strip().replace("　", " ").replace("  ", " ")
    if key in NAME_ALIASES:
        return NAME_ALIASES[key]
    nospace = key.replace(" ", "")
    if nospace in NAME_ALIASES:
        return NAME_ALIASES[nospace]
    # 姓だけでも一致を試す
    for alias, canonical in NAME_ALIASES.items():
        if alias and (alias in nospace or nospace in alias):
            return canonical
    return None


def _nospace(s):
    return (s or "").strip().replace("　", " ").replace(" ", "")


def match_player_scores(names, scores_list, pick_name, pick_idx):
    """このハーフの (names, scores_list) から選択プレーヤーのスコア9個を返す。
    OUT画面とIN画面は別々にOCRするため、IN画面に氏名ヘッダが写っていないと
    氏名一致では拾えない。そこで次の優先順で対応列を決める:
      1. 表示名の完全一致
      2. 名寄せ後(normalize_name)の一致
      3. 姓の部分一致（全角/半角空白・敬称ゆれを吸収）
      4. 列位置(pick_idx)フォールバック ← 氏名が無い/読めない画面はこれで拾う
    どれも当たらなければ []（＝このハーフは空扱い）。"""
    names = names or []
    scores_list = scores_list or []
    # 1. 完全一致
    for nm, sc in zip(names, scores_list):
        if nm and nm == pick_name:
            return sc or []
    # 2. 名寄せ一致
    pc = normalize_name(pick_name)
    if pc:
        for nm, sc in zip(names, scores_list):
            if nm and normalize_name(nm) == pc:
                return sc or []
    # 3. 姓の部分一致
    pk = _nospace(pick_name)
    if pk:
        for nm, sc in zip(names, scores_list):
            n2 = _nospace(nm)
            if n2 and (n2 in pk or pk in n2):
                return sc or []
    # 4. 列位置フォールバック
    if 0 <= pick_idx < len(scores_list):
        return scores_list[pick_idx] or []
    return []


# ---- Vision へ渡すプロンプト（この端末レイアウト前提）----
VISION_PROMPT = """あなたはゴルフ場のスコア確認画面（表形式）を読むOCRです。
画面は横に列、縦にホール行が並ぶ表です。左側に固定列（Hole / HC / Yard / Par）があり、
その右に各プレーヤーの列が左から順に並びます。プレーヤー列にはそのホールの打数（大きい数字）と、
その隣に成績記号（△ □ ○ — や +2 など）が付きます。上部に "OUT"（前半 1-9）か "IN"（後半 10-18）、
最上部にプレーヤー氏名の見出しがあります（見出しが画面外で見えない場合は氏名は空文字にする）。

重要な列の扱い:
- 読むのは各プレーヤーの「打数（各ホールの大きい数字）」だけ。
- "PT"（パット数）の列はプレーヤーではない。無視して players に含めない。
- HC / Yard / Par / 記号(△ □ ○ — / +N) の列も無視する。
- players は左から右のプレーヤー順に並べる（PT列は飛ばす）。人数は氏名見出しの列数に合わせる
  （氏名が見えなくても、打数の列＝プレーヤー列の数だけ players を作る。PT列は数えない）。

次のJSONだけを返してください（前後の説明・マークダウン・コードフェンス禁止）:
{
  "half": "OUT" または "IN",
  "hole_numbers": [表示されているホール番号9個, 例 1..9 か 10..18],
  "hole_pars": [各表示ホールのPar9個],
  "players": [
    {"name_raw": "見出しの氏名（無ければ空文字）", "scores": [9個の打数], "half_total": 前半/後半の合計, "grand_total": TOTAL}
  ]
}

厳守事項:
- scores は表示9ホール分。まだ打っていない/空欄のホールは null（0で埋めない）。
- 打数は大きい数字のみ。隣の成績記号や、小さい PT（パット）数字は読まない。
- half は画面の "OUT"/"前半" または "IN"/"後半" 表示で判断する。
- 読めない値は null。推測で埋めない。
"""


def parse_vision_json(text: str) -> dict:
    """Visionの返答テキストからJSONを取り出してdict化（コードフェンス除去に強く）。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        # 先頭の 'json' ラベルを除去
        nl = t.find("\n")
        if nl != -1 and t[:nl].strip().lower() in ("json", ""):
            t = t[nl + 1:]
    # 最初の { から最後の } まで
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1:
        t = t[i:j + 1]
    return json.loads(t)


def which_half(data: dict) -> str | None:
    """OUT/INを判定。halfフィールド優先、無ければホール番号帯で判断。"""
    h = (data.get("half") or "").strip().upper()
    if h in ("OUT", "IN"):
        return h
    nums = data.get("hole_numbers") or []
    nums = [n for n in nums if isinstance(n, int)]
    if nums:
        if max(nums) <= 9:
            return "OUT"
        if min(nums) >= 10:
            return "IN"
    return None


def verify_half(scores9, half_total):
    """9マス合計とHALF表示の一致を検算。
    Returns: (ok: bool, computed: int|None, filled_count: int)
    空(None)を含む場合は「途中」とみなし、埋まっている分だけ合計してHALFとは比較しない。"""
    filled = [s for s in scores9 if isinstance(s, int)]
    computed = sum(filled) if filled else None
    if len(filled) < 9:
        return (True, computed, len(filled))  # 途中：検算スキップ（合計は参考）
    ok = (half_total is None) or (computed == half_total)
    return (ok, computed, len(filled))


def empty_round(num_holes=18):
    return {"scores": [None] * num_holes, "pars": [None] * num_holes}


def merge_half_into(scores18, half, scores9):
    """18穴の器の該当ブロック(OUT=0..8 / IN=9..17)に9マスを流し込む。
    既に値がある穴は上書きせず温存（手入力済みを尊重）。空(None)穴だけ埋める。"""
    base = 0 if half == "OUT" else 9
    for i in range(9):
        v = scores9[i] if i < len(scores9) else None
        idx = base + i
        if isinstance(v, int) and scores18[idx] is None:
            scores18[idx] = v
    return scores18


def filled_holes(scores18):
    return sum(1 for s in scores18 if isinstance(s, int))


def build_round_record(scores18, pars18, course_name, tee, date_iso, player_name,
                       next_id):
    """保存用レコードを作る。埋まった穴数で num_holes を決める（9穴ラウンド対応）。
    HI・コース別平均は num_holes==18 のみ拾う（集計側ガードで対応）。"""
    n = filled_holes(scores18)
    return {
        "id": next_id,
        "date": date_iso,
        "course_name": course_name,
        "pars": pars18,
        "hdcps": None,
        "tee": tee,
        "yards": [],
        "num_holes": n,
        "players": [{"name": player_name, "scores": scores18, "putts": []}],
    }


def finalize_scores(scores18):
    """保存直前に穴数を確定する。
    Returns: (mode, scores, start, end)
      mode: "full18" / "out9" / "in9" / "invalid"
      scores: 保存用の int リスト（Noneを含まない）。invalid のときは None。
      start,end: 元18穴のどの範囲か（pars等の対応スライス用）。
    ルール: 18穴すべて埋まる=full18 / H1-9のみ=out9 / H10-18のみ=in9 /
            それ以外(片ナインの途中など)=invalid（空欄を埋めさせる）。"""
    def allfilled(seq):
        return all(isinstance(s, int) for s in seq)
    def allempty(seq):
        return all(s is None for s in seq)

    if allfilled(scores18):
        return ("full18", list(scores18), 0, 18)
    out, inn = scores18[:9], scores18[9:]
    if allfilled(out) and allempty(inn):
        return ("out9", list(out), 0, 9)
    if allfilled(inn) and allempty(out):
        return ("in9", list(inn), 9, 18)
    return ("invalid", None, 0, 0)


# ---- Vision 呼び出し（名刺アプリ meishi_mailer_app.py と同一パターン）----
# APIキーはこのモジュールでは保持しない。呼び出し側(app.py)が
#   os.environ["OPENAI_API_KEY"] → st.secrets → サイドバー入力
# の順で用意した文字列を api_key 引数で渡す（名刺アプリと同じ流儀）。
def _call_vision(image_bytes: bytes, api_key: str, model: str = "gpt-4o") -> str:
    """画像をVisionに投げ、生テキスト（JSON文字列）を返す。
    名刺アプリの ocr_image と同じく response_format=json_object・モデル別リトライ。"""
    from openai import OpenAI

    b64 = base64.standard_b64encode(image_bytes).decode()
    client = OpenAI(api_key=(api_key or "").strip())
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}",
                           "detail": "high"}},
        ],
    }]
    base = dict(model=model, messages=messages,
                response_format={"type": "json_object"})
    # 推論型(gpt-5系)は出力枠を大きく・推論は最小限に。空応答/旧モデルにも順に対応。
    if model.startswith("gpt-5"):
        attempts = [
            {"max_completion_tokens": 4000, "reasoning_effort": "low"},
            {"max_completion_tokens": 4000},
            {"max_completion_tokens": 2048},
        ]
    else:
        attempts = [
            {"max_completion_tokens": 1500},
            {"max_tokens": 1024},
        ]
    content = ""
    for extra in attempts:
        try:
            resp = client.chat.completions.create(**base, **extra)
        except Exception:
            continue
        content = (resp.choices[0].message.content or "").strip()
        if content:
            break
    return content


def ocr_screen(image_bytes: bytes, api_key: str, model: str = "gpt-4o") -> dict:
    """画像1枚 -> パース済みdict（half, hole_numbers, hole_pars, players[...]）。
    api_key は呼び出し側が用意（名刺アプリと同じ読み方）。既定モデルは gpt-4o。"""
    raw = _call_vision(image_bytes, api_key, model=model)
    return parse_vision_json(raw)
