# golf-score-app — 業務ルール

コードから読み取れた業務ルールを条件式で列挙する。根拠を示せないルールは記載しない。

## 保存層の切替・キャッシュ

- `環境変数 GOLF_BACKEND == "file"` → ローカルJSON保存を強制（テスト用）
  - 根拠: data_manager.py _backend（L129-130）
- `DB_URL（secrets["db_url"]または環境変数）あり` → Postgres／`gcp_service_account と gsheet_id のsecretsあり` → Google Sheets／`どちらも無し` → ローカルJSON（data/*.json）
  - 根拠: data_manager.py _backend（L128-135）、_db_url（L106-114）、_gsheets_conf（L117-125）
- 読み取りキャッシュTTL = 8秒（Sheetsは全体を1回で読み"__all__"キャッシュ）
  - 根拠: data_manager.py _CACHE_TTL（L28）、_gs_read_all（L33-45）
- `保存ペイロード長 > 45,000文字（_CHUNK_LIMIT）` → keyセルに分割マニフェスト {"__chunked__": true, "n": N} を置き、本体を key__0, key__1… に分割保存
  - 根拠: data_manager.py _gs_write（L66-103）
- `読み込んだ値が {"__chunked__": true}` → 断片を結合して復元（旧単一セル形式もそのまま読める後方互換）
  - 根拠: data_manager.py _load（L188-197)
- Sheetsへの書き込みは常に `value_input_option="RAW"`（式/数値への誤解釈防止）
  - 根拠: data_manager.py _gs_set_cell（L53-63）
- `チャンク数が減った` → 余ったチャンクセルの値を空にする
  - 根拠: data_manager.py _gs_write（L97-102）

## ラウンド・コースの保存

- `save_round` → id = 既存idの最大値+1、created_at = 現在時刻ISOを自動付与
  - 根拠: data_manager.py save_round（L312-319）
- `save_course で同名コースが既存` → 上書き、無ければ追加
  - 根拠: data_manager.py save_course（L283-295）
- 一括登録の重複防止キー = `(date, course_name)`。日付はISO（YYYY-MM-DD）。既存キーと一致すればスキップ
  - 根拠: HANDOVER.md §5 登録スクリプト例、HANDOVER_GOLF_SCORES.md §1「重複防止キーは (date, course_name)」、import_all.py（HANDOVER_GOLF_SCORES_2.md §4）
- プレイヤー名は "hiroaki minowa" で統一（カード表記「蓑輪 宏晃」等も名寄せ）
  - 根拠: HANDOVER.md §4、ocr_score.py NAME_ALIASES（L19-25）
- `パット未記録` → putts=[]（平均パット集計のノーカウント）
  - 根拠: HANDOVER.md §5、data_manager.py get_recent_putt_avg（L456-473: any(pts)のラウンドのみ集計）

## ゲーム集計（games.py）

- タテ: 1ストローク=1点（既定 tate_pt=1）。総打数が少ないほど良い
  - 根拠: games.py docstring（L3）、DEFAULT_RULES（L13）
- ヨコ: ホール単位の勝敗（最少打数が勝ち、既定 yoko_pt=1）
  - 根拠: games.py docstring（L4）、DEFAULT_RULES（L14）
- オリンピック配点: 金4/銀3/銅2/鉄1/チップイン5（手入力、選択肢は なし/鉄/銅/銀/金/チップイン）
  - 根拠: games.py DEFAULT_RULES（L15）、OLYMPIC_MEDALS（L75）
- ポイントターニー配点: `パー差<=-2`→eagle=4／`-1`→birdie=2／`0`→par=1／`+1`→bogey=0／`+2以上`→double=-1
  - 根拠: games.py DEFAULT_RULES（L17）、point_tourney_results pts（L26-35）
- ラスベガス: 2人のスコアを「少ない方×10+多い方」で数値化し、チーム間の差を勝ち点にする
  - 根拠: games.py las_vegas_number（L50-53）、las_vegas_results（L56-72）
- ハンデ配分: コースHDCPの難しい順にホールへ1打ずつ、18超は2巡目
  - 根拠: games.py allocate_strokes（L78-80）

## 集計分析（data_manager.py）

- スコア内訳: パー差 `<=-2`イーグル以上／`-1`バーディ／`0`パー／`+1`ボギー／`+2`ダブルボギー／`それ以上`トリプル以上
  - 根拠: data_manager.py get_score_breakdown（L424-444）
- 直近平均パット: パット記録のあるラウンドのみ直近n件（既定10）で平均
  - 根拠: data_manager.py get_recent_putt_avg（L456-473）

## OCR（ocr_score.py）

- 表示名の名寄せ: NAME_ALIASES（完全一致→空白除去一致→部分一致）で "hiroaki minowa" に変換。未知の名前はNone（手選択にフォールバック）
  - 根拠: ocr_score.py normalize_name（L28-42）
- 読み取り検証: OUT合計+IN合計 = カードTOTAL のチェックサム（合わなければ登録しない）
  - 根拠: ocr_score.py docstring（L6「HALF/TOTAL検算」）、HANDOVER_GOLF_SCORES.md §1「検算（必須）」

## 楽天GORAコース検索（course_search.py）

- c_id の抽出: `数字のみ`→そのまま／`URL内 c_id/(\d+)`→抽出／`4〜7桁数字`→抽出、いずれも不可ならNone
  - 根拠: course_search.py extract_cid（L28-39）
- 各ホールのPar/ヤードはAPIではなくレイアウトページ（layout_disp URL）のスクレイピングで取得
  - 根拠: course_search.py 冒頭docstring（L7-9）、LAYOUT_URL_TMPL（L25）
