# MYTHERESA 検索 (mytheresa.com) — F12 メモ & 実装マッピング

> **用途**: Step3 仕入先 URL 探索  
> **Step4**: `scraper/strategies/mytheresa.py` が PDP の価格・在庫を処理

## 方針Aでの位置づけ

| 層 | MYTHERESA の役割 |
|----|------------------|
| 2 | `site:mytheresa.com 型番` DDG 検索 |
| 3 | **本ドキュメント** — 検索 F12 解析 → URL 候補 |
| 4 | PDP Strategy で型番・価格・在庫を裁判 |

---

## 重要: Bot 検知

MYTHERESA は **headless / クラウド IP から Bot ページ**（`Something went wrong` / `Reference BOT:`）を返すことがあります。

| 環境 | 推奨 |
|------|------|
| **kato ローカル Windows** | Chrome + Playwright（通常ブラウザプロファイル推奨） |
| クラウド VM | 検索 HTML が空 → **候補URLs 救済** |

F12 キャプチャは **必ずローカル** で行ってください。

---

## F12 で確認する手順（ローカル Windows）

1. Chrome で検索 URL を開く:
   ```
   https://www.mytheresa.com/en-us/search/?q=PRADA+1ML506+wallet
   ```
2. **F12 → Network → Fetch/XHR**
3. 検索実行後、次を確認:
   - **GraphQL POST**（`/graphql` 等）— 商品名・slug・SKU
   - **JSON-LD** `ItemList` / `ListItem`（HTML 内 `<script type="application/ld+json">`）
   - **商品リンク** — `/en-us/women/...-{id}.html`
4. ローカル検証:
   ```powershell
   py scripts\capture_mytheresa_f12.py 1ML506 -p wallet -v
   py scripts\capture_mytheresa_f12.py 1BH026 -p shoulder-bag -v
   ```

### 記録テンプレ

```
検索 URL テンプレ: https://www.mytheresa.com/en-us/search/?q={q}
GraphQL XHR URL: 
GraphQL operation: （例 SearchProducts / productSearch）
レスポンス SKU パス: 例 data.products[].sku / designerStyleId
商品ページ URL パターン: /en-us/women/{category}/{slug}-p{id}.html
JSON-LD: ItemList.itemListElement[].url / Product.offers.url
Bot 回避: 通常 Chrome プロファイル / Accept-Language: en-US
失敗時: DDG site:mytheresa.com → 候補URLs
```

---

## 実装で使っているフィールド（コード側）

`supply_search/mytheresa.py`:

| ソース | フィールド | 意味 |
|--------|-----------|------|
| JSON-LD ItemList | `name`, `url` / `item.url` | 商品名・PDP URL |
| JSON-LD Product | `offers.url` | PDP URL |
| HTML リンク | `href` | `/women/...-{id}.html` |
| __NEXT_DATA__ | 再帰 JSON 走査 | `supply_search/json_walk.py` |
| GraphQL XHR | 同上 | F12 で確定した URL を `capture` スクリプトでダンプ |

型番照合: 一覧に型番が無いことが多い → **Step4 JSON-LD** で最終確認。

---

## 例: 1ML506 財布

| 項目 | 値 |
|------|-----|
| 検索クエリ | `PRADA 1ML506 wallet` |
| 期待 | wallet 系 PDP が上位 |
| URL 例 | `https://www.mytheresa.com/en-us/women/.../...-p00892014.html` |

---

## 関連ファイル

- `supply_search/mytheresa.py` — 検索解析
- `scripts/capture_mytheresa_f12.py` — ローカルキャプチャ
- `supply_url_finder.py` — Step3 統合
- `docs/FARFETCH_SEARCH_F12.md` — 姉妹ドキュメント（先に実装済み）

---

## 次サイト

SSENSE → NET-A-PORTER → 24S（同手順）
