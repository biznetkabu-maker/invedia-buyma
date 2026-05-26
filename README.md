# Invedia BUYMA

BUYMA 無在庫バイヤー自動化パイプライン。

海外ブランド品の候補検出 → 型番照合 → 仕入先探索 → 価格スクレイピング → 利益計算 → BUYMA 出品 → 価格監視を自動化。

**運用マニュアル:** [docs/OPERATIONS.md](docs/OPERATIONS.md)  
**漏斗運用:** [docs/FUNNEL_OPS.md](docs/FUNNEL_OPS.md)  
**クイックスタート:** [docs/SIMPLE_START.md](docs/SIMPLE_START.md)

## 使い方

```bash
pip install -e ".[dev,browser]"
pytest
```

- 認証: `credentials.json` **または** `.env` の `GOOGLE_SERVICE_ACCOUNT_JSON`

**入口（bat）:** `invedia_buyma.bat`

| 日常操作 |
|----------|
| **[1]** 候補抽出（ブックマークレット） |
| **[2]** 候補取込（TSV → シート） |
| **[3]** 自動仕入れ検討 |
| **[5]** 定期監視 |

## 主な機能

| 機能 | 説明 |
|------|------|
| 価格スクレイパー | 19 サイト対応（FARFETCH, SSENSE, MYTHERESA, NAP, 24S 等） |
| 仕入先探索 | site: 検索 + Playwright 5 サイト巡回 |
| 利益計算 | A〜E グレード判定 + 利益率自動計算 |
| 公式照合 | PRADA 公式サイトとの型番マッチング |
| LINE 通知 | 利益閾値超えで自動通知 |
| 為替 | EUR/GBP/USD→JPY 自動取得 |

## フォルダ構成

```
invedia-buyma/
├── invedia_buyma.bat     # 入口
├── lib/                  # ロジック
│   ├── scraper/          # 19 サイト価格スクレイパー
│   │   └── strategies/   # サイト別戦略
│   ├── supply_search/    # 仕入先探索（Playwright）
│   └── official_catalog/ # 公式照合（PRADA 等）
├── scripts/              # 入口スクリプト
├── bookmarklets/         # BUYMA 候補抽出
├── tests/                # pytest
└── docs/                 # 運用マニュアル
```

## テスト

```bash
pytest -q
```
