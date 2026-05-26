# FARFETCH 検索 (farfetch.com) — F12 メモ & 実装マッピング

> **用途**: Step3 仕入先 URL 探索（型番 + カテゴリで FARFETCH 検索結果から PDP URL を取得）  
> **Step4**: `scraper/strategies/farfetch.py` が PDP の価格・型番（JSON-LD / `__NEXT_DATA__`）を処理

## 方針Aでの位置づけ

| 層 | FARFETCH の役割 |
|----|-----------------|
| 2 | `site:farfetch.com 型番` DDG 検索 |
| 3 | **本ドキュメント** — 検索ページ F12 解析 → URL 候補 |
| 4 | PDP Strategy で型番・価格・在庫を裁判 |

自動探索が失敗 → `自動見送り_仕入先なし` → 人が **候補URLs** に正 URL を貼って再実行。

---

## F12 で確認する手順（ローカル Windows）

1. Chrome で検索 URL を開く:
   ```
   https://www.farfetch.com/jp/shopping/women/search/items.aspx?q=PRADA+1ML506+wallet
   ```
2. **F12 → Network → Fetch/XHR**（または **Doc** で初回 HTML も確認）
3. 次を確認:
   - **JSON-LD** `ItemList`（`<script type="application/ld+json">`）— 商品名・`/jp/shopping/.../item-NNNN.aspx`
   - **Apollo キャッシュ**（HTML 内 `ProductCatalogItem:...` — `shortDescription` + `path`）
   - **XHR**（ページネーション時の GraphQL — 環境により 0 件のことあり）
4. 確定したフィールドを下記テンプレに記録
5. ローカル検証:
   ```powershell
   py scripts\capture_farfetch_f12.py 1ML506 -p wallet -v
   py scripts\capture_farfetch_f12.py 1BH026 -p shoulder-bag -v
   ```

### 記録テンプレ（メモを貼って PR に追記）

```
検索 URL テンプレ: https://www.farfetch.com/jp/shopping/women/search/items.aspx?q={q}
主ソース（2026-05）: JSON-LD ItemList（XHR 不要な場合あり）
JSON-LD パス: itemListElement[].name / offers.url
Apollo パス: ProductCatalogItem → shortDescription + resourceIdentifier.path
XHR URL（あれば）: 
XHR レスポンス SKU パス: 
商品ページ URL パターン: /jp/shopping/women/{slug}-item-{id}.aspx
型番の有無: 一覧 JSON には型番が無いことが多い → Step4 JSON-LD で照合
Cookie / ヘッダ必須: Accept-Language: ja-JP（推奨）
失敗時フォールバック: DDG site:farfetch.com → DOM <a> → 候補URLs
```

---

## 実装で使っているフィールド（コード側）

`supply_search/farfetch.py` は次を解析します。

| ソース | フィールド | 意味 |
|--------|-----------|------|
| JSON-LD ItemList | `name` | 英語商品名（カテゴリスコア用） |
| JSON-LD ItemList | `offers.url` | PDP パス（`/jp/shopping/.../item-ID.aspx`） |
| Apollo キャッシュ | `shortDescription` | 商品名 |
| Apollo キャッシュ | `resourceIdentifier.path` | PDP パス |
| XHR JSON | `sku` / `styleId` / `path` / `url` 等 | 再帰走査（`supply_search/json_walk.py`） |

型番照合:
- 一覧に型番があれば URL / 名前で **先頭一致**
- **無い場合が多い** → Step4 の JSON-LD `style_id` で拒否/採用（安全装置）

カテゴリスコア: `infer_supply_category_hints()` — wallet / shoulder-bag / sandal 等で順位付け。  
除外: `pre-owned` パス、`eyewear`（眼鏡カテゴリでない場合）、不正 slug（`prada--item-`）。

---

## 例: 1ML506 財布

| 項目 | 値 |
|------|-----|
| BUYMA 型番 | `1ML506` |
| 検索クエリ | `PRADA 1ML506 wallet` |
| 期待 | wallet 系 PDP が上位（型番は Step4 で確認） |
| 商品 URL（例） | `https://www.farfetch.com/jp/shopping/women/prada-small-saffiano-leather-wallet-item-36404881.aspx` |

## 例: 1BH026 ショルダーバッグ

| 項目 | 値 |
|------|-----|
| BUYMA 型番 | `1BH026` |
| 検索クエリ | `PRADA 1BH026 shoulder bag` |
| 注意 | 検索上位に `bonnie-m` 等別 SKU が出やすい → **Step4 型番不一致で拒否**（意図した安全動作） |
| 救済 | 正 URL を **候補URLs** に貼る |

---

## 環境変数

| 変数 | 既定 | 意味 |
|------|------|------|
| `SUPPLY_SEARCH_TIMEOUT_MS` | `45000` | Playwright 検索タイムアウト |
| `INTAKE_FUNNEL` | `1` | 漏斗 ON |

---

## 関連ファイル

- `supply_search/farfetch.py` — 検索解析（JSON-LD / Apollo / XHR）
- `scripts/capture_farfetch_f12.py` — ローカル F12 キャプチャ
- `supply_url_finder.py` — Step3 統合（FARFETCH は Strategy 優先）
- `scraper/strategies/farfetch.py` — Step4 PDP
- `docs/PRADA_OFFICIAL_F12.md` — 公式照合（Step1.5）の姉妹ドキュメント

---

## 他サイトへの展開（P4 ロードマップ）— **完了**

| サイト | ドキュメント | キャプチャ |
|--------|-------------|-----------|
| FARFETCH | `docs/FARFETCH_SEARCH_F12.md` | `scripts/capture_farfetch_f12.py` |
| MYTHERESA | `docs/MYTHERESA_SEARCH_F12.md` | `scripts/capture_mytheresa_f12.py` |
| SSENSE | `docs/SSENSE_SEARCH_F12.md` | `scripts/capture_ssense_f12.py` |
| NET-A-PORTER | `docs/NETAPORTER_SEARCH_F12.md` | `scripts/capture_netaporter_f12.py` |
| 24S | `docs/24S_SEARCH_F12.md` | `scripts/capture_24s_f12.py` |

コード: `supply_search/` 配下各 Strategy + `supply_url_finder.py` 統合
