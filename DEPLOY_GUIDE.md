# スマホで使う：クラウド公開の手順

ゴルフ場でスマホから使えるように、アプリをインターネット上に公開します。
**無料**でできます。所要 20〜40分。

データの保存先は **Google スプレッドシート**（おすすめ）か **Supabase(Postgres)** を選べます。
このガイドは **Google スプレッドシート** 版です。

---

## 全体像
1. **Google スプレッドシート**（無料）でデータの保存先を用意
2. **GitHub**（無料）にアプリのコードを置く
3. **Streamlit Community Cloud**（無料）で公開
4. スマホのブラウザで開く → ホーム画面に追加してアプリ化

---

## ① 保存先のGoogleスプレッドシートを用意
1. Google ドライブで新しいスプレッドシートを作成（名前は何でもOK、例: `golf-data`）
2. URL の `/d/` と `/edit` の間が **シートID** → 控える
   - 例: `https://docs.google.com/spreadsheets/d/`**`1AbCdE...XYZ`**`/edit`

## ② Google サービスアカウント（アプリがシートに書き込む鍵）を作成
1. https://console.cloud.google.com にアクセス（Googleアカウントでログイン）
2. 上部でプロジェクトを新規作成（例: `golf-app`）
3. 「APIとサービス → ライブラリ」で **Google Sheets API** を検索して **有効化**
4. 「APIとサービス → 認証情報 → 認証情報を作成 → サービスアカウント」を作成
5. 作成したサービスアカウントを開き「キー → 鍵を追加 → JSON」で**JSONキーをダウンロード**
6. JSON内の `client_email`（`xxxx@xxxx.iam.gserviceaccount.com`）をコピー
7. ①のスプレッドシートを開き、**「共有」** からその `client_email` を **編集者** で追加
   - （これでアプリがシートに書き込めるようになります。表は初回に自動作成されます）

## ③ GitHub にコードを置く
1. https://github.com でアカウント作成（無料）
2. 「New repository」→ 名前を付けて作成（Private でOK）
3. このフォルダ（`golf-score-app`）の中身をアップロード
   - `data/` と `.streamlit/secrets.toml` は **`.gitignore` で自動的に除外**（公開されません）
   - 上げるファイル: `app.py` `games.py` `course_search.py` `data_manager.py`
     `requirements.txt` `.gitignore` `.streamlit/secrets.toml.example` など

## ④ Streamlit Community Cloud で公開
1. https://share.streamlit.io にアクセス → GitHubでサインイン
2. 「Create app」→ 上記リポジトリと `app.py` を選択
3. **Advanced settings → Secrets** に以下を貼り付け：
   ```toml
   gsheet_id = "①で控えたシートID"

   [gcp_service_account]
   # ②でダウンロードしたJSONの中身をそのまま貼り付け（type, project_id, private_key ...）
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "xxxx@xxxx.iam.gserviceaccount.com"
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."

   # 楽天GORA名前検索を使うなら↓も
   # RAKUTEN_APP_ID = "あなたのapplicationId"
   ```
   - ※ `private_key` は改行を `\n` のままにしてください
4. 「Deploy」をクリック → 数分でURL（例: `https://xxxx.streamlit.app`）が発行されます

## ⑤ スマホで使う
1. 発行された `https://xxxx.streamlit.app` をスマホのブラウザで開く
2. **ホーム画面に追加**するとアプリのように起動できます
   - iPhone(Safari): 共有 → 「ホーム画面に追加」
   - Android(Chrome): メニュー → 「ホーム画面に追加」

---

## データの移行（任意）
今PC内にあるデータ（`data/*.json`）をクラウドへ移したい場合は、
`migrate_to_db.py` を使えます（ローカルにも同じsecretsを置いて実行）。必要なら声をかけてください。

## 補足
- ローカル(PC)で動かすときは secrets を設定しなければ、今まで通りファイル保存で動きます
- **Supabase(Postgres)を使いたい場合**は、③④で secrets に `db_url = "..."` だけを設定すればOK
  （`gsheet_id` と `db_url` の両方があるときは Postgres が優先されます）
- Googleスプレッドシートはセル1つあたり約5万文字までです。ラウンドが非常に多くなった場合は
  Supabaseへの切り替えをおすすめします（その場合も移行可能）。
