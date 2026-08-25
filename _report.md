# 生成サマリ: golf-score-app

## 検出結果

| 項目 | 内容 |
|---|---|
| 社内コード | なし（個人用アプリ） |
| バックエンド | Googleスプレッドシート app_dataシート（courses/rounds/prefsをJSON保存、8秒キャッシュ、45,000字チャンク分割、RAW書込）。DB_URL時はPostgres、無設定時はローカルJSON |
| 主要機能数 | 9 |
| 抽出ルール数 | 22 |
| AS400利用 | なし |
| 要確認数 | 5 |

## 要確認

- ⚠️ ラウンド件数の記載が文書間で異なる: HANDOVER.md（2026-07-01）=40ラウンド、HANDOVER_GOLF_SCORES_2.md（2026-07-02）=174ラウンド保存済み。現在の実件数は未確認（HANDOVER.md §4、HANDOVER_GOLF_SCORES_2.md §1）
- ⚠️ HANDOVER_GOLF_SCORES_2.md §1の未解決事項（Streamlitプロセス再起動による新data_manager.py反映、174ラウンド表示確認）が解消済みか未確認
- ⚠️ 霞ヶ関CCのコース名表記ゆれ（登録時の略記「霞ヶ関CC 東/東」と既存DBの正式表記）の名寄せが未解決のまま記載されている（HANDOVER_GOLF_SCORES_2.md §2）
- ⚠️ OCRのVision呼び出し（ocr_score.py _call_vision）は実装済み（2026-08-25 確認・docstring修正）。ただし Streamlit Cloud 側 secrets に OPENAI_API_KEY / RAKUTEN_APP_ID が設定済みかは未確認（ローカル .streamlit/secrets.toml には両方あり）
- ⚠️ .streamlit/secrets.toml が実ファイルとしてフォルダ内に存在（サービスアカウント鍵を含む想定）。gitignore対象とDEPLOY_GUIDE.mdに記載はあるが、実際の除外状態は未確認（DEPLOY_GUIDE.md ③、.streamlit/secrets.toml）

## [提案]

- HANDOVER.md（40ラウンド）とHANDOVER_GOLF_SCORES_2.md（174ラウンド）の記載を統合し、最新のHANDOVERを1本化すると引継ぎ時の混乱を防げる
- コース名の名寄せ（略記→正式表記のリネームスクリプト）をHANDOVER_2 §2の方針どおり実施し、コース別集計の二分を解消する
- ocr_score.py の _call_vision 実装（HANDOVER記載の「名刺アプリと同じクライアント」流用）でOCR機能を完成させる
