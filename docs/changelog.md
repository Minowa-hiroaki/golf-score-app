# golf-score-app — 経緯

版番号の体系はなし。HANDOVER各文書（日付入り）とコードから以下が確認できる。

## 確認できる経緯

- ローカルJSON版 → Google Sheets版へ移行。data_manager.pyはDB_URL→Postgres／Sheets設定→Sheets／無し→ローカルJSONの自動切替構造で、本番はGoogle Sheets（根拠: data_manager.py docstring L1-10、HANDOVER.md §3「本番=Googleスプレッドシート」）。migrate_to_db.py が同梱（内容未確認）
- デプロイ: GitHub `Minowa-hiroaki/golf-score-app`（Public）、Streamlit Community Cloud。DEPLOY_GUIDE.mdにGoogle Sheets版の公開手順を文書化（根拠: HANDOVER.md §2、DEPLOY_GUIDE.md）
- 2026-07-01（HANDOVER.md）: 総ラウンド40。スコアカード画像→登録手順、機能一覧（Par別傾向・スコア内訳等）を記載
- 2026-07-01（HANDOVER_GOLF_SCORES.md）: J-SYS画像からの過去ラウンド一括登録作業を開始。重複防止キー(date, course_name)、検算（OUT+IN=Total）等の規則を確立。RE1バッチ19ラウンド検算済み
- 2026-07-02（HANDOVER_GOLF_SCORES_2.md）:
  - Google Sheetsの1セル50,000字上限で保存クラッシュ → data_manager.py にチャンク分割（_CHUNK_LIMIT=45000）＋RAW書き込みを実装（現行 data_manager.py L29-30, L53-103 に反映済み）
  - import_all.py（96レコード、RE1〜RE6）を実行し、174ラウンド（既存79+95）がGoogle Sheetsに保存済み
  - 未解決として記載: アプリプロセス再起動（旧data_manager.pyのメモリ保持解消）、霞ヶ関CCのコース名表記ゆれ（略記 vs 既存DBの正式表記）の名寄せ

## その他の実在ファイル

- app.py.bak（旧版バックアップ、内容未確認）
- data_manager.py 末尾に「# redeploy nudge」コメント（再デプロイ誘発用の変更痕跡。data_manager.py L528）

## 2026-08-25 ドキュメント修正の記録

- 修正内容: OCRのVision呼び出し（ocr_score.py `_call_vision`）を「プレースホルダ・未実装」と書いていた記述を、実装済みの内容に改めた（ocr_score.py 冒頭docstring / docs/overview.md 主要機能 / _report.md 要確認）
- 誤りの原因: docstring がコミット `5667c30`（patch data_manager chunk load + HI + OCR）以降の `_call_vision` 実装時に更新されず残り、docs/overview.md と _report.md がその docstring を根拠に生成されたため、誤りが3ファイルに伝播した
- ルール: 実装を差し替えたら、同じコミット内で該当ファイルの docstring も更新する。docs/ と _report.md は docstring を一次根拠にするため、docstring の陳腐化がそのまま文書の誤りになる
