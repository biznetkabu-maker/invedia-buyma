# NET-A-PORTER 検索 (net-a-porter.com) — F12 メモ & 実装マッピング

> **用途**: Step3 仕入先 URL 探索（YNAP グループ）  
> **Step4**: `scraper/strategies/netaporter.py` が PDP の価格・在庫を処理

## 方針Aでの位置づけ

| 層 | NET-A-PORTER の役割 |
|----|---------------------|
| 2 | `site:net-a-porter.com 型番` DDG 検索 |
| 3 | **本ドキュメント** — 検索 F12 解析 → URL 候補 |
| 4 | PDP Strategy + JSON-LD 型番照合 |

---

## 重要: Akamai / Bot ブロック

クラウド VM / headless では **403 Access Denied**（Akamai）になりやすい。

| 環境 | 推奨 |
|------|------|
| **kato ローカル Windows** | 通常 Chrome + Playwright |
| クラウド | HTML 空 → **候補URLs 救済** |

F12 キャプチャは **必ずローカル** で行ってください。

---

## F12 で確認する手順（ローカル Windows）

1. Chrome で検索 URL を開く:
   ```
   https://www.net-a-porter.com/en-us/search?q=PRADA+wallet
   https://www.net-a-porter.com/en-us/search?q=PRADA+1ML506
   ```
2. **F12 → Network → Fetch/XHR** — 検索 API / GraphQL
3. **Elements** — JSON-LD `Product` / `ItemList`
4. 商品 URL パターン:
   ```
   /en-us/shop/product/{brand}/{category}/.../{numericId}
   ```
5. ローカル検証:
   ```powershell
   py scripts\capture_netaporter_f12.py -q "PRADA wallet" -v
   py scripts\capture_netaporter_f12.py 1ML506 -p wallet -v
   ```

### 記録テンプレ

```
検索 URL テンプレ: https://www.net-a-porter.com/en-us/search?q={q}
代替（F12で確認）: /en-us/search?text= / shop/search/ ...
XHR URL: 
JSON-LD Product: name, brand.name, offers.url, sku
商品ページ URL: /en-us/shop/product/.../{id}
403 時: ローカル Chrome / Accept-Language: en-US
失敗時: DDG site:net-a-porter.com → 候補URLs
```

---

## 実装で使っているフィールド（コード側）

`supply_search/netaporter.py`:

| ソース | フィールド | 意味 |
|--------|-----------|------|
| JSON-LD Product | `name`, `brand.name`, `offers.url`, `sku` | 商品名・PDP URL |
| JSON-LD ItemList | `itemListElement[].item` | 一覧 |
| HTML リンク | `/shop/product/.../{id}` | フォールバック |
| XHR JSON | 再帰走査 | `supply_search/json_walk.py` |

Access Denied 検出: `Access Denied` / `errors.edgesuite.net`

---

## 例: CELINE トート（コード内テスト URL）

```
https://www.net-a-porter.com/en-us/shop/product/celine/bags/tote-bags/
  medium-cabas-leather-tote/1647597310916060
```

---

## 関連ファイル

- `supply_search/netaporter.py`
- `scripts/capture_netaporter_f12.py`
- `supply_url_finder.py`
- `scraper/strategies/netaporter.py`（Step4）
- MR PORTER は別ドメイン（将来同型で拡張可）

---

## 残り P4

24S（最後）
