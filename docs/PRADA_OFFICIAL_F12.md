# PRADA 公式 (prada.com) — F12 メモ & 実装マッピング

> **用途**: BUYMA 型番（例 `PR09ZS`）と公式 SKU の同一性を確定し、英語検索クエリを強化する。  
> **仕入れ価格には使わない**（公式は基準カタログ。仕入は FARFETCH 等）。

## 方針Aでの位置づけ

| 層 | prada.com の役割 |
|----|------------------|
| 0.5 | **同一性の基準**（MPN / 完全 SKU） |
| 2 | 英語商品名 → `site:` 検索クエリ強化 |
| 3 | 仕入先 JSON-LD と公式 SKU の突合 |

自動探索が失敗 → `自動見送り_仕入先なし` → 人が **候補URLs** を貼って再実行。

---

## F12 で確認する手順（ローカル Windows）

1. Chrome で `https://www.prada.com/jp/ja/search?q=PR09ZS` を開く（地域 Cookie は JP 推奨）。
2. F12 → **Network** → **Fetch/XHR**、フィルタ `search` / `product` / `api`。
3. 検索実行後、Status 200 の JSON を開き、以下フィールドを探す。
4. 商品詳細ページを開き、同様に XHR と `script[type=application/ld+json]` を確認。
5. 確定した URL を `scripts/capture_prada_f12.py` でダンプ（下記）。

### 記録テンプレ（メモを貼って PR に追記）

```
検索 XHR URL: 
検索レスポンス SKU パス: 例 products[].partNumber / code / mpn
商品ページ URL パターン: /jp/ja/p/{slug}/{PARTNUMBER}.html
PDP JSON-LD: Product.sku / mpn
PDP XHR URL: 
価格フィールド（参考）: 
```

---

## 実装で使っているフィールド（コード側）

`official_catalog/prada.py` は JSON を再帰走査し、次を収集します。

| キー名（いずれか） | 意味 |
|-------------------|------|
| `partNumber`, `part_number`, `mpn`, `sku`, `code`, `productCode` | 型番・SKU |
| `url`, `productUrl`, `seoURL`, `link` | 商品 URL |
| `name`, `productName`, `title` | 英語名 |
| `price`, `salePrice`, `fullPrice` | 参考価格 |

型番照合: `PR09ZS` は **先頭一致**（完全 SKU が `PR09ZS-1AB1O1-1BO1O1` の場合も一致）。

---

## 例: PR09ZS サングラス（想定パターン）

| 項目 | 値 |
|------|-----|
| BUYMA 型番 | `PR09ZS` |
| 公式完全 SKU（例） | `PR09ZS-1AB1O1-1BO1O1` |
| 商品 URL（例） | `https://www.prada.com/jp/ja/p/.../PR09ZS-1AB1O1-1BO1O1.html` |
| 英語検索 | `PRADA PR09ZS sunglasses` |

※ クラウド VM から prada.com へは接続できない場合あり。**ローカル Playwright** で `capture_prada_f12.py` を実行。

---

## 環境変数

| 変数 | 既定 | 意味 |
|------|------|------|
| `INTAKE_OFFICIAL_PRADA` | `1` | PRADA 時に公式照合を実行 |
| `INTAKE_WEEKLY_LIMIT` | `40` | 週次 `--auto-sheet` 上限 |

---

## 関連ファイル

- `official_catalog/prada.py` — 照合ロジック
- `scripts/capture_prada_f12.py` — F12 XHR ダンプ（ローカル）
- `funnel_policy.py` — 方針A・除外ルール
