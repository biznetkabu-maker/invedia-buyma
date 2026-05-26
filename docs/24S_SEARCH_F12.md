# 24S 検索 (24s.com) — F12 メモ & 実装マッピング

> **用途**: Step3 仕入先 URL 探索（LVMH グループ）  
> **Step4**: `scraper/strategies/twentyfoursevens.py` が PDP の価格・在庫を処理

## 方針Aでの位置づけ

| 層 | 24S の役割 |
|----|------------|
| 2 | `site:24s.com 型番` DDG 検索 |
| 3 | **本ドキュメント** — 検索 F12 解析 → URL 候補 |
| 4 | PDP Strategy + JSON-LD 型番照合 |

---

## 重要: Akamai / Bot ブロック

クラウド VM / headless では **403 Access Denied**（Akamai）になりやすい。  
**kato ローカル Windows + 通常 Chrome** で F12 キャプチャしてください。

---

## 商品 URL パターン（24S 固有）

```
/en-us/{product-slug}_{SKU}
```

例:
```
https://www.24s.com/en-us/celine-small-cabas-tote-bag_CESS24BAG001
```

- slug: ハイフン区切り英小文字
- SKU: アンダースコア `_` 以降（例 `CESS24BAG001`）

---

## F12 で確認する手順（ローカル Windows）

1. Chrome で開く:
   ```
   https://www.24s.com/en-us/search?q=PRADA+wallet
   ```
2. **F12 → Network → Fetch/XHR**
3. **Elements** — JSON-LD `@type: Product` / `ItemList`
4. ローカル検証:
   ```powershell
   py scripts\capture_24s_f12.py -q "PRADA wallet" -v
   py scripts\capture_24s_f12.py 1ML506 -p wallet -v
   ```

### 記録テンプレ

```
検索 URL テンプレ: https://www.24s.com/en-us/search?q={q}
JSON-LD Product: name, brand.name, offers.url, sku
商品 URL パターン: /en-us/{slug}_{SKU}
XHR URL（あれば）: 
403 時: ローカル Chrome
失敗時: DDG site:24s.com → 候補URLs
```

---

## 実装（コード側）

`supply_search/twentyfoursevens.py`:

| ソース | フィールド |
|--------|-----------|
| JSON-LD Product | `name`, `brand.name`, `offers.url`, `sku` |
| HTML リンク | `/en-us/..._{SKU}` |
| XHR | `supply_search/json_walk.py` 再帰走査 |

Access Denied 検出: NET-A-PORTER と同型（Akamai / edgesuite.net）

---

## 関連ファイル

- `supply_search/twentyfoursevens.py`
- `scripts/capture_24s_f12.py`
- `supply_url_finder.py`
- `docs/FARFETCH_SEARCH_F12.md` 等（P4 全5サイト）

---

## P4 完了

FARFETCH / MYTHERESA / SSENSE / NET-A-PORTER / **24S** — 5サイトすべて Strategy 実装済み。
