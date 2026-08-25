# golf-score-app — 概要

## アプリ定義

ゴルフのラウンドスコア記録・6種のポイントゲーム集計・統計分析を行うStreamlitアプリ。データはGoogleスプレッドシート（app_dataシート）にJSON保存し、Streamlit Community Cloudで公開してスマホから利用する（根拠: data_manager.py 冒頭docstring、DEPLOY_GUIDE.md、HANDOVER.md §1-3）。

## 主な利用者

個人用（Hiro=hiroaki minowa。プレイヤー名は "hiroaki minowa" で統一。根拠: HANDOVER.md §4、ocr_score.py NAME_ALIASES L19-25）。

## 現行バージョン

Google Sheets保存版。data_manager.pyは1セル50,000字上限対策のチャンク分割（_CHUNK_LIMIT=45000）とRAW書き込みを適用済み（根拠: data_manager.py L29-30, L53-103、HANDOVER_GOLF_SCORES_2.md §3）。デプロイ先: GitHub Minowa-hiroaki/golf-score-app（Public）、Streamlit Cloud（根拠: HANDOVER.md §2）。

## 主要機能

- ラウンド登録（コース・ティー・パー・プレイヤー別スコア、パットのON/OFF入力）（根拠: app.py、data_manager.py save_round）
- 6種のゲーム集計: タテ／ヨコ／オリンピック／ポイントターニー／ラスベガス／ベスト＆グロス（根拠: app.py GAME_OPTIONS L21-22、games.py）
- ハンデ配分（コースHDCPの難しい順に配る allocate_strokes。タテ/ヨコ/ベスト＆グロスに適用）（根拠: games.py allocate_strokes L78、HANDOVER.md §7）
- 集計分析: Par別傾向・スコア内訳（バーディ/パー/ボギー…）・コース別平均・直近10ラウンド平均パット・同一コースのホール別平均（根拠: data_manager.py get_par_type_stats/get_score_breakdown/get_course_score_averages/get_recent_putt_avg/get_course_hole_averages）
- 楽天GORA APIによるコース検索＋レイアウトページのスクレイピングでPar/ヤード取得（根拠: course_search.py L1-25）
- ゴルフ場タッチパネル画面のスコアOCR（OpenAI Vision。_call_vision 実装済み。モデルは gpt-5.5 / gpt-4o / gpt-4o-mini から選択、既定 gpt-5.5。APIキーは 環境変数OPENAI_API_KEY → st.secrets → 画面入力 の順で解決）（根拠: ocr_score.py _call_vision L225-268、app.py _ocr_api_key L202-210・モデル選択 L228-230）
- 保存層の自動切替: DB_URLがあればPostgres／Google Sheets設定があればSheets／どちらも無ければローカルJSON（根拠: data_manager.py _backend L128-135）
- 得点ルール（タテ/ヨコ配点・オリンピック配点・ポイントターニー配点）のprefs保存（根拠: app.py get_rules L25-40、games.py DEFAULT_RULES L12-18）
- 回帰テスト: simulate_tests.py / test_data_and_parse.py / apptest_smoke.py（根拠: HANDOVER.md §7、各ファイル実在）
