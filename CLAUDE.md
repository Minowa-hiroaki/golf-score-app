# golf-score-app（社内コード: なし・個人用アプリ）

ゴルフのスコア・ゲーム集計を行う個人用Webアプリ（Streamlit + Google Sheets保存、Streamlit Cloudデプロイ、モバイル対応）。
現行版: Google Sheets保存版（チャンク分割・RAW書き込み対応 data_manager.py。HANDOVER_GOLF_SCORES_2.md 2026-07-02）。

## ドキュメント

- @docs/overview.md — 概要・主要機能
- @docs/business_rules.md — 業務ルール（根拠付き）
- @docs/data_model.md — データ構造・バックエンド
- @docs/changelog.md — 版の経緯

## 原則

- データ駆動。コード・資料で確認できる事実のみを記載する
- お世辞・評価的形容詞は不要。誤りは即指摘する
