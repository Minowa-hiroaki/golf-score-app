"""ダウンロードしたサービスアカウントJSONから .streamlit/secrets.toml を自動生成する。

使い方:
    python make_secrets.py "C:\\Users\\h_minowa\\Downloads\\xxxx.json" シートID

例:
    python make_secrets.py "C:\\Users\\h_minowa\\Downloads\\aiba-memorial-abc123.json" 1t4naHOT96DVJPU7IWubymfaQetD752Br5IjKUeGysJQ
"""
import sys
import os
import json


def main():
    if len(sys.argv) < 3:
        print('使い方: python make_secrets.py "JSONファイルのパス" シートID')
        return
    json_path = sys.argv[1]
    sheet_id = sys.argv[2]

    with open(json_path, "r", encoding="utf-8") as f:
        sa = json.load(f)

    out_dir = os.path.join(os.path.dirname(__file__), ".streamlit")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "secrets.toml")

    lines = [f'gsheet_id = {json.dumps(sheet_id)}', "", "[gcp_service_account]"]
    for key in ["type", "project_id", "private_key_id", "private_key",
                "client_email", "client_id", "auth_uri", "token_uri",
                "auth_provider_x509_cert_url", "client_x509_cert_url",
                "universe_domain"]:
        if key in sa:
            lines.append(f"{key} = {json.dumps(sa[key])}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"作成しました: {out_path}")
    print(f"サービスアカウント: {sa.get('client_email')}")
    print("このメールをスプレッドシートに『編集者』で共有していればOKです。")


if __name__ == "__main__":
    main()
