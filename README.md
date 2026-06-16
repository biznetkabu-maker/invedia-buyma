# Invedia BUYMA

BUYMA 無在庫バイヤー自動化パイプライン。

海外ブランド品の候補検出 → 型番照合 → 仕入先探索 → 価格スクレイピング → 利益計算 → BUYMA 出品 → 価格監視を自動化。

**運用マニュアル:** [docs/OPERATIONS.md](docs/OPERATIONS.md)  
**漏斗運用:** [docs/FUNNEL_OPS.md](docs/FUNNEL_OPS.md)  
**クイックスタート:** [docs/SIMPLE_START.md](docs/SIMPLE_START.md)

## クイックスタート（5分）

### 1. インストール

```bash
git clone https://github.com/biznetkabu-maker/invedia-buyma.git
cd invedia-buyma
pip install -e ".[dev,browser]"
playwright install chromium
```

### 2. 環境変数を設定

`.env.example` をコピーして `.env` を作成：

```bash
cp .env.example .env
```

最低限必要な値を入力：

```env
SPREADSHEET_ID=<Google スプレッドシートの ID>
GOOGLE_SERVICE_ACCOUNT_JSON=<サービスアカウント JSON の中身>
WORKSHEET_NAME=02_Purchase_Control
```

LINE 通知を使う場合（オプション）：

```env
LINE_CHANNEL_ACCESS_TOKEN=<Messaging API トークン>
LINE_USER_ID=<送信先の U から始まる ID>
```

### 3. Google スプレッドシートを準備

1. [Google Sheets](https://sheets.google.com) で新規作成
2. シート名を `02_Purchase_Control` に変更
3. サービスアカウント（`client_email`）を「編集者」として共有

### 4. 動作確認

```bash
pytest -q                    # テスト実行
python -m lib.main --once    # 1回だけ巡回実行
```

### 5. 定期巡回（GitHub Actions）

リポジトリの Settings → Secrets and variables → Actions に以下を登録：

| Secret 名 | 値 |
|-----------|-----|
| `SPREADSHEET_ID` | スプレッドシート ID |
| `GOOGLE_CREDENTIALS_JSON` | サービスアカウント JSON 全文 |
| `WORKSHEET_NAME` | `02_Purchase_Control` |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE トークン（オプション）|
| `LINE_USER_ID` | LINE ユーザー ID（オプション）|

登録後、6時間ごと（0/6/12/18時 UTC）に自動巡回が実行されます。

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
