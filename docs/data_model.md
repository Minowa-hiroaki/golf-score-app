# golf-score-app — データモデル

## バックエンド

- 本番: Googleスプレッドシート（シートID 1t4naHOT96DVJPU7IWubymfaQetD752Br5IjKUeGysJQ、サービスアカウント golf-app@aiba-memorial.iam.gserviceaccount.com）の「app_data」ワークシートに key-value 形式でJSON文字列を保存（根拠: HANDOVER.md §3、data_manager.py _get_ws L138-155）
- 切替: DB_URLがあればPostgres（app_dataテーブル key TEXT PRIMARY KEY, value TEXT）、Sheets設定がなければローカル data/courses.json, rounds.json, prefs.json（根拠: data_manager.py _backend L128-135、_get_engine L158-173、_FILES L17-21）
- 8秒キャッシュ（_CACHE_TTL）、45,000字超のチャンク分割保存（key__0, key__1…＋マニフェスト）、RAW書き込み（根拠: data_manager.py L28-30, L53-103）
- 認証情報は .streamlit/secrets.toml（ローカル）／Streamlit Cloud Secrets（本番）（根拠: HANDOVER.md §3、DEPLOY_GUIDE.md ④）

## データ構造

### rounds（ラウンド。app_dataの"rounds"キー）

- `[{id(連番), created_at(ISO), date(YYYY-MM-DD), course_name, pars(18要素), hdcps(またはNone), tee, yards, num_holes, players:[{name, scores(18要素), putts}], ...(オリンピック点数等をupdate_roundで追記)}]`
  - 根拠: data_manager.py save_round（L312-319）/update_round（L327-334）、HANDOVER.md §5 登録スクリプト例のレコード構造
- 集計はplayers[].name="hiroaki minowa"等のプレイヤー名で横断集計（根拠: data_manager.py get_player_stats L338-350 ほか集計関数群）

### courses（コース。app_dataの"courses"キー）

- `[{name, ...}]`。nameをキーに同名上書き（根拠: data_manager.py save_course L283-295、course_exists L303-304）
- 楽天GORAレイアウト取得によるPar/ヤード情報を含むコース定義を作成（根拠: course_search.py fetch_holes_from_layout、app.py import L41-44）

### prefs（設定。app_dataの"prefs"キー）

- `{rules: {tate_pt, yoko_pt, olympic{金/銀/銅/鉄/チップイン}, point{eagle/birdie/par/bogey/double}}, ...}`（根拠: app.py get_rules L25-40、data_manager.py load_prefs/update_prefs L262-275）

### Google Sheets 上の物理形式（app_dataシート）

- A列=key（"courses"/"rounds"/"prefs"、分割時は "rounds__0" 等）、B列=value（JSON文字列）。1行目はヘッダ（key, value）（根拠: data_manager.py _gs_read_all L40-44、_get_ws L152-153、_gs_write L66-103）

### 付随スクリプト・データ

- import_all.py / import_kasumi.py / hi_kasumi.py / register_courses.py / migrate_to_db.py / rename_ibaraki.py: 一括登録・移行用スクリプト（ファイル実在。import_all.pyの内容はHANDOVER_GOLF_SCORES_2.md §4に記載: 96レコード・検算済み・(date,course_name)重複スキップ）
- data/ フォルダ: ローカルJSONバックエンド時の保存先（根拠: data_manager.py DATA_DIR L16-21）
