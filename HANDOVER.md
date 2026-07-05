# ゴルフスコア集計アプリ — 引継ぎ書類（2026-07-01）

新しいチャットの最初に、このファイルを読ませてから作業を続けてください。

## 0. 「止まる」問題
アプリ・データ・コマンドの問題ではなく、**AI側のツール呼び出しの書式ミス**が原因。
新セッションで再開すれば改善しやすい。1応答=1ツール呼び出しにすると安定。

## 1. アプリ概要
- Python + Streamlit のゴルフスコア＆ゲーム集計アプリ（モバイル対応）。
- ローカル: `C:\Users\h_minowa\golf-score-app\`
- 主要: app.py(画面) / games.py(ゲーム計算) / course_search.py(楽天GORA取得) / data_manager.py(保存層)

## 2. デプロイ
- GitHub: `Minowa-hiroaki/golf-score-app`(Public)
- Streamlit Cloud: `https://r8pqvcgks6uaq7ex9dj6t9.streamlit.app`
- 更新: 編集 → `git add -A && git commit -m "..." && git push` → 自動再デプロイ

## 3. データ保存（本番=Googleスプレッドシート）
- data_manager が自動切替: DB_URL→Postgres / gsheet設定→Sheets / 無し→ローカルJSON
- サービスアカウント: golf-app@aiba-memorial.iam.gserviceaccount.com
- シートID: 1t4naHOT96DVJPU7IWubymfaQetD752Br5IjKUeGysJQ
- app_data シートに courses/rounds/prefs をJSON保存。8秒キャッシュ有(書込後 dm.clear_cache())。
- ローカル .streamlit/secrets.toml に同設定あり（PCから本番データを読み書き可）。

## 4. データ現状
- 総ラウンド 40。自分の名前は **"hiroaki minowa" で統一**（カード表記「蓑輪 宏晃」でもこの名前）。
- 4人ラウンド1件: 中軽井沢GC 2026/6/30（自分99/岡本善明112/垣谷宗孝88/井上大介116）。

## 5. スコアカード画像→登録手順
1. 画像を読む（**チャットに直接貼ってもらうのが最も鮮明・確実**。zip展開+PIL拡大でも可）
2. マーク換算: —=パー / △=+1 / □=+2 / ○=-1 / ◎=-2 / ☆=-3 / +3等=数字がパー差
   各ホール打数 = Par + 差
3. **必ず検証**: OUT合計+IN合計 = カードTOTAL（チェックサム）
4. IN/OUT表記(INスタート)は H1→H18 に並べ替えて保存
5. パットは「-」なら putts=[]（未記録・平均はノーカウント）
6. 登録スクリプト例:
```python
import data_manager as dm
from datetime import datetime
rounds=dm.load_rounds()
exist={(r.get("date"),r.get("course_name")) for r in rounds}  # 重複防止
nid=max([r.get("id",0) for r in rounds],default=0)
# R=[(date,course,tee,pars18,scores18), ...]
for d,c,t,pars,sc in R:
    if (d,c) in exist: continue
    nid+=1
    rounds.append({"id":nid,"created_at":datetime.now().isoformat(),"date":d,"course_name":c,
      "pars":pars,"hdcps":None,"tee":t,"yards":[],"num_holes":18,
      "players":[{"name":"hiroaki minowa","scores":sc,"putts":[]}]})
dm._store("rounds",rounds); dm.clear_cache()
```

## 6. 未処理
- `C:\Users\h_minowa\Desktop\golf-data\golf_kasumi.zip`（PNG5枚 IMG_1623-1627）**未登録**。
  "kasumi"=霞ヶ関の可能性。要確認。

## 7. 機能メモ
- 集計分析: Par別傾向 / スコア内訳 / コース別スコア平均 / 直近10R平均パット / 同一コース2回以上でホール別。
- ハンデ: タテ/ヨコ/ベスト＆グロスに適用(スクラッチ基準or手動)。
- パット: 事前ON/OFF、ONは各ホール直下入力。
- 回帰テスト: simulate_tests.py / test_data_and_parse.py / apptest_smoke.py

## 8. コマンド
```
cd C:/Users/h_minowa/golf-score-app && streamlit run app.py --server.port 8501
git add -A && git commit -m "..." && git push
python -c "import data_manager as dm; print(len(dm.load_rounds()))"
```
