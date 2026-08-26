# -*- coding: utf-8 -*-
"""live_share.py — ライブ観戦（QR共有）と LINE 速報配信

役割:
  - 同伴者がスマホで途中経過を見るための観戦URL・QRコードを作る。
  - LINE Messaging API でグループへ速報を送る。

LINE の前提（2026-08 時点で確認）:
  - LINE Notify は2025年3月末で終了。代替は Messaging API（LINE公式アカウント）。
  - 無料枠（コミュニケーションプラン）は月200通。
  - **グループ送信は「送信対象の人数」でカウントされる**（4人グループなら1送信=4通）。
    そのため毎ホール配信は 18送信×人数 で無料枠をすぐ使い切る。
    観戦URLをQRで配って画面で見てもらい、LINEは節目だけ送る運用を既定にしている。
  - 出典: https://developers.line.biz/ja/docs/messaging-api/pricing/
"""
from __future__ import annotations

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

# 配信頻度（選択式）。値は「送信するホール番号(1始まり)の決め方」。
SEND_MODES = [
    "送らない",
    "ハーフごと＋最終（おすすめ）",
    "3ホールごと＋最終",
    "毎ホール（無料枠に注意）",
]


def milestones(mode, num_holes):
    """その配信頻度で送信対象になるホール番号(1始まり)の集合を返す。"""
    if mode == "送らない":
        return set()
    if mode.startswith("毎ホール"):
        return set(range(1, num_holes + 1))
    if mode.startswith("3ホールごと"):
        s = set(range(3, num_holes + 1, 3))
        s.add(num_holes)
        return s
    # ハーフごと＋最終
    s = {num_holes}
    if num_holes == 18:
        s.add(9)
    return s


def estimate_units(mode, num_holes, n_recipients):
    """1ラウンドで消費するおおよその通数（人数分カウントされる）。"""
    return len(milestones(mode, num_holes)) * max(1, int(n_recipients))


def _diff_str(v):
    return f"{v:+d}" if v else "±0"


def flash_text(payload, upto_hole, viewer_url=None):
    """LINEに送る速報テキストを組み立てる。"""
    pars = payload.get("pars") or []
    num_holes = payload.get("num_holes") or len(pars)
    cut = max(0, min(int(upto_hole), num_holes))
    par_cut = sum(pars[:cut])

    head = f"⛳ {payload.get('course_name', '')}"
    if payload.get("date"):
        head += f"\n{payload['date']}"
    if cut >= num_holes:
        head += f"\n🏁 ホールアウト（{num_holes}H）"
    elif num_holes == 18 and cut == 9:
        head += "\n⛳ OUT終了（9H）"
    else:
        head += f"\n⛳ {cut}ホール終了"

    lines = [head, ""]
    rows = []
    for p in payload.get("players", []):
        sc = (p.get("scores") or [])[:cut]
        rows.append((p.get("name", ""), sum(sc)))
    for name, total in sorted(rows, key=lambda x: x[1]):
        lines.append(f"{name}　{total}（{_diff_str(total - par_cut)}）")

    for label, key in (("タテ", "tate"), ("ヨコ", "yoko"),
                       ("オリンピック", "olympic"), ("ポイントターニー", "point")):
        d = (payload.get("standings") or {}).get(key)
        if not d:
            continue
        order = sorted(d, key=lambda n: d[n], reverse=True)
        body = " / ".join(f"{n} {_diff_str(d[n])}" for n in order)
        lines.append("")
        lines.append(f"【{label}】{body}")

    if viewer_url:
        lines.append("")
        lines.append("▼ 途中経過はこちら")
        lines.append(viewer_url)
    return "\n".join(lines)


def qr_svg(url, scale=6):
    """URLのQRコードをSVG文字列で返す。segno が無ければ None。"""
    try:
        import segno
    except Exception:
        return None
    import io as _io
    buf = _io.StringIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale,
                                    dark="#e6e9ef", light=None, xmldecl=False)
    return buf.getvalue()


def line_push(token, to, text):
    """LINE Messaging API でテキストを1通送る。

    Returns: (ok: bool, message: str)
    """
    import requests
    token = (token or "").strip()
    to = (to or "").strip()
    if not token:
        return False, "チャネルアクセストークンが未設定です。"
    if not to:
        return False, "送信先（グループID / ユーザーID）が未設定です。"
    text = (text or "").strip()
    if not text:
        return False, "送信内容が空です。"
    if len(text) > 4900:
        text = text[:4900] + "…"
    try:
        r = requests.post(
            LINE_PUSH_ENDPOINT,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
            json={"to": to, "messages": [{"type": "text", "text": text}]},
            timeout=15)
    except Exception as e:
        return False, f"通信エラー: {e}"
    if r.status_code == 200:
        return True, "送信しました。"
    detail = (r.text or "")[:300]
    hint = ""
    if r.status_code == 401:
        hint = "　→ チャネルアクセストークンをご確認ください。"
    elif r.status_code == 403:
        hint = "　→ 無料枠（月200通）を超えたか、送信先が友だち/参加者でない可能性があります。"
    elif r.status_code == 400:
        hint = "　→ 送信先ID（グループID/ユーザーID）の形式をご確認ください。"
    return False, f"LINEエラー ({r.status_code}): {detail}{hint}"
