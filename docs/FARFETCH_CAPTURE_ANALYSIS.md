# FARFETCH capture ログ詳細分析 — 1ML506 wallet

> **実行環境**: クラウド headless Chromium（2026-05-21）  
> **コマンド**: `py scripts/capture_farfetch_f12.py 1ML506 -p wallet -v`  
> **ブランチ**: `cursor/farfetch-f12-xhr-f0ed`（PR #26）

---

## 1. 実行サマリ

| 項目 | 値 | 判定 |
|------|-----|------|
| Playwright | OK | Step3 Strategy 実行可能 |
| 検索 URL | `.../items.aspx?q=PRADA+1ML506+wallet` | テンプレ一致 |
| JSON-LD ItemList | **96 件** | 主ソース正常 |
| Apollo キャッシュ | **108 件** | 冗長バックアップあり |
| XHR JSON 捕捉 | **0 件** | 初回 HTML のみで十分（想定内） |
| 候補 URL 数（Strategy 出力） | **8 件** | 上位 5 件を JSON 出力 |
| 先頭 score | **110** | wallet カテゴリ一致 |

**結論**: FARFETCH Step3 Strategy は **クラウド headless でも正常動作**。1ML506 wallet は JSON-LD から wallet 系 PDP を取得できる。

---

## 2. 診断ログの読み方

```
--- 診断 ---
  Playwright: OK
  検索URL: https://www.farfetch.com/jp/shopping/women/search/items.aspx?q=PRADA+1ML506+wallet
  JSON-LD ItemList: 96 件
  Apollo キャッシュ: 108 件
  XHR JSON 捕捉: 0 件
  候補URL数: 8
    score=110 [json_ld_itemlist] small Saffiano leather wallet → https://...
```

| 表示 | 意味 | 正常目安 |
|------|------|----------|
| `Playwright: OK` | 検索ページ到達 | OK / NG |
| `JSON-LD ItemList: N 件` | `<script type="application/ld+json">` の ItemList 解析 | **N ≥ 1**（検索ヒット時） |
| `Apollo キャッシュ: N 件` | HTML 内 GraphQL キャッシュ | 0 でも JSON-LD があれば可 |
| `XHR JSON 捕捉: N 件` | Network 傍受 JSON | 0 でも可（FARFETCH は HTML 主ソース） |
| `score=NN [source]` | カテゴリ・ブランド・型番ヒントによる順位 | wallet なら **110 前後** |

---

## 3. 上位候補の解釈

| 順位 | score | 商品名 | ソース | 解釈 |
|------|-------|--------|--------|------|
| 1 | 110 | small Saffiano leather wallet | json_ld_itemlist | wallet カテゴリ一致 → **Step3 採用候補** |
| 2 | 110 | large Saffiano leather wallet | json_ld_itemlist | サイズ違いの sibling SKU |
| 3 | 85 | nappa-leather wallet with shoulder-strap | json_ld_itemlist | wallet だが shoulder 要素あり |
| 4 | 75 | pre-owned ... Zip Around Wallet | json_ld_itemlist | **pre-owned** — Step3/4 で除外される可能性 |
| 5 | 50 | pre-owned Saffiano Triang bi-fold | json_ld_itemlist | 同上 |

### 先頭 URL（JSON 出力）

```
https://www.farfetch.com/jp/shopping/women/prada-small-saffiano-leather-wallet-item-36404881.aspx
```

- **Step3**: 探索成功として intake に渡される
- **Step4**: JSON-LD `style_id` / `sku` と BUYMA 型番 `1ML506` を照合
  - 一致 → MatchScore **S/A** → シート反映 + **P2 キャッシュ書込み**
  - 不一致 → 自動見送り（別 SKU URL の安全装置）

---

## 4. データソース優先順位（実装）

`supply_search/farfetch.py` のマージ順:

1. **JSON-LD ItemList** — 今回 96 件、主ソース
2. **Apollo キャッシュ** — 108 件、JSON-LD と重複多い
3. **XHR JSON** — 0 件（ページネーション未発生 or headless では不要）

XHR が 0 でも **NG ではない**。FARFETCH は初回 HTML に ItemList を埋め込むため、Strategy は HTML パースのみで完結できる。

---

## 5. kato ローカルとの比較観点

| 観点 | クラウド（本分析） | kato ローカル |
|------|-------------------|---------------|
| headless | OK | 通常 OK |
| JSON-LD 件数 | 96 | 90+ なら同等 |
| Bot/403 | なし | なしが正常 |
| XHR | 0 | 手動 Chrome ではページ送り時に増える場合あり |

kato で `JSON-LD ItemList: 0` の場合:
- Cookie / 地域ブロック
- 検索クエリ typo
- FARFETCH UI 変更 → `docs/FARFETCH_SEARCH_F12.md` 更新

---

## 6. 他サイトとの対比（同一セッション）

| サイト | 1ML506 wallet | 備考 |
|--------|---------------|------|
| FARFETCH | **OK**（96 ItemList） | 本ドキュメント |
| SSENSE | 0 件（複合クエリ） | `-q prada` 単体は 65 件 |
| MYTHERESA | Bot ブロック | 候補URLs 救済 |
| NET-A-PORTER | Akamai 403 | 候補URLs 救済 |
| 24S | Akamai 403 | 候補URLs 救済 |

**運用**: FARFETCH + SSENSE（ブランド単体検索）が headless で使える。MYTHERESA/NAP/24S は kato Chrome F12 または候補URLs。

---

## 7. 1BH026 shoulder-bag との違い（参考）

| 型番 | クエリ | リスク |
|------|--------|--------|
| 1ML506 wallet | `PRADA 1ML506 wallet` | wallet 上位 → Step4 型番照合が最終判定 |
| 1BH026 shoulder | `PRADA 1BH026 shoulder-bag` | bonnie-m 等 **別 SKU** が上位になりやすい → Step4 拒否（意図どおり） |

capture 診断で URL が取れても **Step4 不一致は正常な安全装置**。救済は候補URLs。

---

## 8. 再現コマンド

```powershell
py -m playwright install chromium
py scripts\capture_farfetch_f12.py 1ML506 -p wallet -v
py scripts\capture_farfetch_f12.py 1BH026 -p shoulder-bag -v
py -m unittest test_supply_search_farfetch.py -v
```

成功目安: `JSON-LD ItemList: 1+`、`候補URL数: 1+`、`Playwright: OK`
