# SSENSE 検索 (ssense.com) — F12 メモ & 実装マッピング

> **用途**: Step3 仕入先 URL 探索  
> **Step4**: `scraper/strategies/ssense.py` が PDP の価格・型番（JSON-LD）を処理

## 方針Aでの位置づけ

| 層 | SSENSE の役割 |
|----|---------------|
| 2 | `site:ssense.com 型番` DDG 検索 |
| 3 | **本ドキュメント** — 検索 F12 解析 → URL 候補 |
| 4 | PDP Strategy + JSON-LD 型番照合 |

---

## 重要: 検索 URL

| URL | 結果 |
|-----|------|
| ~~`/en-us/search?q=`~~ | **404**（旧テンプレ・使用禁止） |
| **`/en-us/women?q=`** | 正常（women 検索） |
| `/en-us/men?q=` | men 検索 |

`product_finder.py` は `women?q=` に更新済み。

---

## F12 で確認する手順（ローカル Windows）

1. Chrome で開く:
   ```
   https://www.ssense.com/en-us/women?q=prada
   https://www.ssense.com/en-us/women?q=PRADA+1ML506+wallet
   ```
2. **F12 → Elements** — 複数の `<script type="application/ld+json">` に `@type: Product`
3. **F12 → Network → Fetch/XHR** — 追加 API があれば記録
4. ローカル検証:
   ```powershell
   py scripts\capture_ssense_f12.py -q prada -v
   py scripts\capture_ssense_f12.py 1ML506 -p wallet -v
   ```

### 記録テンプレ

```
検索 URL テンプレ: https://www.ssense.com/en-us/women?q={q}
JSON-LD Product フィールド: name, brand.name, offers.url, sku
商品ページ URL パターン: /en-us/women/product/{brand}/{slug}/{numericId}
0件時 HTML: "There are no WOMENSWEAR products that match ..."
XHR URL（あれば）: 
失敗時: DDG site:ssense.com → 候補URLs
```

---

## 実装で使っているフィールド（コード側）

`supply_search/ssense.py`:

| ソース | フィールド | 意味 |
|--------|-----------|------|
| JSON-LD Product | `name` | 商品名 |
| JSON-LD Product | `brand.name` | ブランド（例 Prada Eyewear） |
| JSON-LD Product | `offers.url` | PDP フル URL |
| JSON-LD Product | `sku` | SSENSE SKU（型番照合に使用） |
| HTML リンク | `href` | `/product/.../{id}` |

**0件ページ**: 「no products that match」検出時は **フォールバック商品を使わない**（誤探索防止）。

**複合クエリ注意**: `PRADA 1ML506 wallet` は 0 件になりやすい → `prada wallet` や DDG `site:` を併用。

---

## 例: PRADA サングラス（`q=prada`）

| 項目 | 値 |
|------|-----|
| JSON-LD | 49 件前後 |
| URL 例 | `https://www.ssense.com/en-us/women/product/prada-eyewear/black-prada-symbole-sunglasses/19213711` |
| sku 例 | `261208F005019` |

---

## 関連ファイル

- `supply_search/ssense.py`
- `scripts/capture_ssense_f12.py`
- `supply_url_finder.py`
- `docs/FARFETCH_SEARCH_F12.md` / `docs/MYTHERESA_SEARCH_F12.md`

---

## 残り P4

NET-A-PORTER → 24S
