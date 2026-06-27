"""ローカルのJSONデータ（data/*.json）をクラウド保存先へ移行するスクリプト。

使い方（PCのターミナルで）:
  ・Google スプレッドシートへ移行: .streamlit/secrets.toml に gsheet_id と
    [gcp_service_account] を設定してから `python migrate_to_db.py`
  ・Postgres(Supabase)へ移行: `set DB_URL=postgresql://...` してから実行

設定された保存先（Sheets / Postgres）に、ローカルの courses / rounds / prefs を
そのまま書き込みます。
"""
import os
import json

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _read_file(name, default):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    import data_manager as dm

    backend = dm._backend()
    if backend == "file":
        print("クラウド保存先が未設定です。"
              "Google Sheets（gsheet_id + gcp_service_account）または "
              "DB_URL を設定してください。")
        return

    courses = _read_file("courses.json", [])
    rounds = _read_file("rounds.json", [])
    prefs = _read_file("prefs.json", {})

    dm._store("courses", courses)
    dm._store("rounds", rounds)
    dm._store("prefs", prefs)

    dest = "Google スプレッドシート" if backend == "gs" else "Postgres"
    print(f"移行完了（保存先: {dest}）: コース {len(courses)}件 / "
          f"ラウンド {len(rounds)}件 / 設定 {len(prefs)}項目 を保存しました。")


if __name__ == "__main__":
    main()
