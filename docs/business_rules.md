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
  - 根拠: games.py las_vegas_number / las_vegas_results
- ラスベガスのチーム分けは選択式。`固定` / `3ホールごとに入れ替え`（3ホール単位で
  (1-2,3-4)→(1-3,2-4)→(1-4,2-3) を巡回）。入れ替え方式では合計をプレーヤー別に集計する
  - 根拠: games.py LV_TEAM_MODES / lv_pairings / lv_teams_for_hole / by_player
- ラスベガスのオプション（既定はすべてOFF）:
  - `バーディ逆転`: 自チームにパー−1以下が出たら **相手チーム** の数値を反転（多い方×10+少ない方）
  - `1の位切り捨て`: 各チームの数値の1の位を0にする（57→50）
  - `キャリー`: 差が0のホールは勝ち点0で持ち越し、次ホールの倍率を+1（2倍→3倍…）。差が付いた時点で倍率は1に戻る
  - `プッシュ`: 宣言したホールの倍率を2倍（2人宣言なら4倍）。ホール番号を選択式で指定
  - 根拠: games.py las_vegas_results の birdie_reverse / drop_ones / carry / push_by_hole
  - 出典: enjoy-golfer.com「ゴルフのラスベガスの計算方法を徹底解説！」の数値例
    （チームX 5・7 が相手のバーディで 57→75、チームY 3・6 は 36、差 39）で検算済み
- ハンデ配分: コースHDCPの難しい順にホールへ1打ずつ、18超は2巡目
  - 根拠: games.py allocate_strokes（L78-80）
- スコア入力タブの「ハンデの決め方」の既定は **「ハンデなし」**（index=2）。ハンデ戦のときだけ切り替える
  - 根拠: app.py ハンデ設定 expander の st.radio(index=2)
  - 理由: 既定が「HDCPを入力して自動」だと、prefs に保存済みの player_hdcps が無自覚に適用され、
    ハンデ無しのつもりでネット集計になる事故が起きるため（ゲーム集計タブは以前から既定「ハンデなし」）

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
- APIキー・accessKey・Refererが secrets / 環境変数 で揃っている場合、画面には入力欄を出さず
  「設定済み」の表示だけにする。欠けている項目だけ応急入力欄を出す（OpenAIキーも同様）
  - 根拠: app.py 楽天の missing 判定、_render_image_ocr のキー分岐
  - 理由: 伏字でも肩越しに見える／セッションに残る／誤操作で消えるため、常設しない
- 各ホールのPar/ヤードはAPIではなくレイアウトページ（layout_disp URL）のスクレイピングで取得
  - 根拠: course_search.py 冒頭docstring（L7-9）、LAYOUT_URL_TMPL
- ゴルフ場検索APIのエンドポイントは `https://openapi.rakuten.co.jp/engine/api/Gora/GoraGolfCourseSearch/20170623`。
  `applicationId` はクエリ、`accessKey` はHTTPヘッダー（`accessKey: <値>`）で送る。どちらか欠けると 400 になる
- `RAKUTEN_REFERER` が設定されていれば `Referer` ヘッダーに入れ、その URL の `scheme://host` を
  `Origin` ヘッダーに入れて送る。未設定だと 403 `REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING` になる
  - 根拠: course_search.py `_origin_of` / search_rakuten のヘッダー組み立て
  - 根拠: course_search.py RAKUTEN_SEARCH_ENDPOINT / search_rakuten、楽天公式ドキュメント（gora-golf-course-search）
- `applicationId または accessKey が空` → APIを叩かずエラーメッセージを返す（通信前に弾く）
  - 根拠: course_search.py search_rakuten 冒頭のガード
- キーは secrets → 環境変数 → 画面入力 の順に解決し、前後の空白・改行を除去する
  - 根拠: app.py _secret_or_env / get_rakuten_app_id / get_rakuten_access_key
- 「URL / ID から取得」はAPIを使わずレイアウトページのスクレイピングのみ。**APIキーが無くても動く**
  - 根拠: course_search.py fetch_holes_from_layout（APIキーを引数に取らない）
