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

## 2026-08-25 楽天ゴルフ場検索APIの400エラー修正

- 症状: 「コース管理」→「🌐 楽天GORAから自動取得」で `APIエラー (400): specify valid applicationId`。secretsにキーは設定済みだった
- 原因: **キーの問題ではなく、楽天ウェブサービス側の基盤刷新（2026年2月）にコードが追随していなかった**。
  旧ドメイン `app.rakuten.co.jp/services/api/` は2026年5月13日で停止し、新基盤 `openapi.rakuten.co.jp/engine/api/` へ移行。
  あわせて認証が applicationId 単体から **applicationId + accessKey の2点** に変更された
- 対応: エンドポイントを新URLへ変更／`accessKey` をHTTPヘッダーで送るよう `search_rakuten` を修正（URLにキーを載せない）／
  キー未設定時は通信前にエラーを返すガードを追加／キー取得を `_secret_or_env` に集約し前後の空白を除去／
  画面に accessKey の入力欄を追加／`secrets.toml.example` に `RAKUTEN_ACCESS_KEY` を追記
- ルール: **外部APIの400/401は自分のキーを疑う前に、提供元の仕様変更告知を確認する。**
  今回は「キーが無効」というメッセージが実際には「認証方式が変わった」ことを指していた
- 補足: 「🔗 URL / ID から取得」はAPIを使わないため、この障害中も動作していた（実際にこの方法でコース登録済み）
- 続き（同日・実機確認）: 上記対応で 400 は解消したが、次に
  `403 REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING` が出た。
  新基盤は「どのサイトから呼ばれたか」を見る方式に変わっており、**サーバー側（Streamlit）からの
  呼び出しにはブラウザのような Referer が付かない**ため弾かれる
- 追加対応: `Referer` と `Origin` をこちらで付けて送るようにした（`RAKUTEN_REFERER` で設定、
  Origin は URL から scheme://host を切り出して自動生成）。楽天アプリ側の
  「許可されたWebサイト(Allowed websites)」に同じドメインの登録が必要。
  403の文面に Referer/Origin が含まれる場合だけ、その旨を案内するようエラー文言も分岐させた
- ルール（追記）: **サーバーから外部APIを叩くときは、ブラウザが自動で付けるヘッダー
  （Referer / Origin / User-Agent）が付かないことを前提に考える。**
  「ブラウザでは通るのにプログラムでは403」はこの型が多い

## 2026-08-25 ハンデ設定の既定値を「ハンデなし」に変更

- 変更: スコア入力タブの「ハンデの決め方」の既定を `index=2`（ハンデなし）にし、選択時に「全員ハンデ0（グロスのまま）で集計します」と表示
- 理由: 既定が「HDCPを入力して自動」だったため、prefs に保存済みの player_hdcps が無自覚に適用され、
  ハンデ無しのつもりでネット集計されてしまう。ゲーム集計タブ（tab5）は以前から既定が「ハンデなし」で、挙動も不揃いだった

