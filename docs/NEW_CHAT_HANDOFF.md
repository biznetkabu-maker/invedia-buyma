# 新チャット引き継ぎ — invedia-automation

> **最終更新**: 2026-05-21（Cloud Agent セッション反映）  
> **リポジトリ**: `biznetkabu-maker/invedia-automation`（非公開）  
> **kato ローカル**: `C:\Users\kato\EC-project\invedia-automation`  
> **コード版**: `verify_intake_version.py` → **`20250521-v11-fragment-case`**

---

## 0. 今すぐ読むこと

### main の状態

| 項目 | 状態 |
|------|------|
| **#25–#28** | マージ済み（ブランド正規化 / P4 / P2 / 探索精度） |
| **#28 以降の hotfix** | main 直マージ済み（本ファイル §3.2 参照） |
| **kato ローカル** | **`git pull origin main` 必須** — 古いコードだと wallet/eyewear 誤ヒットが再発 |

```powershell
cd C:\Users\kato\EC-project\invedia-automation
git fetch origin
git checkout main
git pull origin main
py scripts\verify_intake_version.py   # BUILD_ID と OK 行を確認
py -m playwright install chromium
```

**verify で確認する代表 OK 行**（すべて出れば最新版）:

- `OK: ウィッカーバケット → wicker クエリ`
- `OK: 【PRADA】タグ → PRADA ブランド正規化`
- `OK: 汎用 sandal（型番スラッグなし）を Step3 で除外`
- `OK: フラグメントケース検索クエリ（PRADA 1MC038 fragment）`
- `OK: フラグメントケース探索から汎用 wallet を除外`

---

## 1. プロジェクト概要

| 項目 | 内容 |
|------|------|
| 目的 | BUYMA 候補 → 仕入先 URL 探索 → 価格・型番照合 → 半自動 intake |
| 運用 | **方針A（半自動）** — 失敗行は削除せず `自動見送り_*`、人が **候補URLs** で救済 |
| コード定義 | `funnel_policy.py` / `FUNNEL_OPS.md` / 本ファイル |

---

## 2. パイプライン（漏斗）

```
候補URLs → P2キャッシュ → site:型番 → Playwright 5サイト → Step4裁判 → P2書込(S/A)
```

| 層 | 内容 | モジュール |
|----|------|-----------|
| 0 | 候補抽出 | ブックマークレット |
| 1 | BUYMA 型番確定 | `buyma_item_parser.py` / `VariantKey` |
| 1.5 | PRADA 公式照合 | `official_catalog/prada.py` |
| 2 | DDG `site:型番` | `supply_site_search.py` |
| 2.5 | (brand, MPN) キャッシュ | `supply_url_cache.py` |
| 3 | 5サイト Playwright | `supply_url_finder.py` + `supply_search/*` |
| 4 | PDP 価格・型番・利益 | `scraper/strategies/*` |
| 救済 | 候補URLs → Step3 スキップ | 人手 |

**Step4 の型番不一致拒否は安全装置** — 誤 URL をシートに書かない（意図どおり）。

---

## 3. 実装サマリ

### 3.1 マージ済み PR（#25–#28）

| PR | 内容 |
|----|------|
| #25 | ブランド正規化・Step3 ログ・カテゴリ探索 |
| #26 | P4: 5サイト F12/XHR Strategy |
| #27 | P2: (brand, MPN) → URL キャッシュ |
| #28 | ベルトバッグ / スニーカー / モノリスサンダル探索精度 |

### 3.2 main 直マージ hotfix（2026-05-21 セッション）

| 問題 | 型番/例 | 修正 | 主要ファイル |
|------|---------|------|-------------|
| `official_english_name` TypeError | 1BG464 | async 引数追加 + P2 キャッシュ参照復元 | `supply_url_finder.py` |
| ハンドバッグ → eyewear | 1BG464 | `hand-bag` クエリ + eyewear Step3 除外 | `supply_search_utils.py` |
| ウィッカー → darling | 1BE083 | `wicker`/`bucket` クエリ + 特定カテゴリ URL 必須 | 同上 |
| site: 検索でカテゴリ未検証 | — | `product_name` 付き `url_is_valid_supply_candidate` | `supply_site_search.py` |
| サンダル → 汎用 sandal | 1X1030 | フットウェアは URL に型番 or ライン名必須 | 同上 + `supply_url_finder.py` |
| 【PRADA】→ 型番がブランド化 | 2X3119 | bracket ブランド抽出 + 型番解決に raw_title | `buyma_item_parser.py` / `intake.py` |
| フラグメント → generic wallet | 1MC038 | `fragment`/`card-holder` クエリ + wallet 除外 | `supply_search_utils.py` |

**Step3 カテゴリ判定の共通ルール**（`supply_search_utils.py`）:

- `category_site_search_extras()` — site:/Playwright クエリ先頭語
- `url_has_category_path_mismatch()` — カテゴリ矛盾 URL 除外
- `url_requires_line_or_style_slug()` — フットウェア等は型番/ライン名/特定カテゴリ語必須
- `line_name_search_tokens()` — monolith / jardiniere / fragment 等

---

## 4. サイト別 headless

| サイト | kato/クラウド | 備考 |
|--------|--------------|------|
| FARFETCH | **OK** | Step3 主戦場 |
| SSENSE | **OK** | |
| MYTHERESA | Bot | 候補URLs 救済 |
| NET-A-PORTER | Akamai 403 | 候補URLs 救済 |
| 24S | Akamai 403 | 候補URLs 救済 |

---

## 5. kato 実地検証（2026-05-21）

### 確認済み（正常動作）

| 現象 | 評価 |
|------|------|
| Step4 型番不一致 → C → シート未反映 | **安全装置 OK** |
| Step1.5 / Step3 失敗 → 見送り（削除なし） | **方針A OK** |
| DNS 一時障害（sheets.googleapis.com） | 再実行で復旧 |
| `【PRADA】` タイトル → ブランド PRADA / 型番表示 | **pull 後** |

### 検証ケース一覧

| 型番 | 商品 | kato ログ時点 | 最新 main 期待 | 救済 |
|------|------|--------------|----------------|------|
| 1BG464 | ハンドバッグ | eyewear 誤ヒット → Step4 C | `hand-bag` クエリ | 候補URLs |
| 1BE083 | ウィッカーバケット | darling 誤ヒット → Step4 C | `wicker` クエリ | 候補URLs |
| 1X1030 | サンダル | generic sandal → Step4 C | 型番スラッグ必須 | 候補URLs |
| 2X3119 | サンダル | ブランド=2X3119（**旧コード**） | PRADA + site:検索 | pull 後再検証 |
| 1MC038 | フラグメントケース | wallet 誤ヒット（**旧コード**） | `fragment` クエリ | pull 後 / 候補URLs |
| 2VL977 | ボディバッグ | wallet 誤ヒット（#28前） | `belt-bag` | pull 後再検証 |
| 2TG193 | ポーチ付スニーカー | pouch 誤ヒット（#28前） | footwear 優先 | pull 後再検証 |
| 1XX751 | モノリスサンダル | wish バッグ（#28前） | `monolith` | pull 後再検証 |

**旧コードの見分け方**（pull 不足）:

- site: が `PRADA 1MC038 wallet` → **旧**（正: `fragment`）
- site: が `PRADA 1BE083 bag` → **旧**（正: `wicker`）
- Playwright `[1/6]: PRADA 1MC038 wallet` + FARFETCH OK → **旧**

### P2 キャッシュ

- Step4 未到達（C 見送り）の行は `.supply_url_cache.json` **未生成**（正常）
- 初回 S/A 成功後、2回目で `URLキャッシュヒット` を確認

---

## 6. 方針A 運用

| 頻度 | 操作 |
|------|------|
| 毎日 | `1_候補_抽出.bat` → `2_候補_取込.bat` |
| 週次 | `py intake.py --auto-sheet`（`INTAKE_WEEKLY_LIMIT=40`） |
| 失敗 | `自動見送り_*` → Chrome で正 URL → **候補URLs** → 再 `--auto-sheet` |
| 出品 | 手動のみ |

---

## 7. kato コマンド早見

```powershell
# セットアップ（毎回 intake 前）
git pull origin main
py scripts\verify_intake_version.py

# テスト（PowerShell は glob 不可）
py -m unittest discover -s . -p "test_supply_search_*.py" -v
py -m unittest test_supply_search_utils.py test_supply_url_cache.py -v

# intake
py intake.py --auto-sheet --limit 1

# 診断
py scripts\capture_farfetch_f12.py 1MC038 -p fragment -v
py scripts\capture_prada_f12.py 2X3119 -v
```

---

## 8. ログの読み方

| 表示 | 意味 |
|------|------|
| `⏭️ スキップ: 型番なし` | 正常（方針A 対象外） |
| `型番 site: 検索` → `Playwright` | Step3 探索中（1〜3分） |
| `-- 候補N件はカテゴリ不一致...` | Step3 改善が効いている |
| `OK FARFETCH (型番はページ照合)` | URL 取得（**Step4 で最終判定**） |
| `【同一性スコア】 C` | 見送り正常 → 候補URLs 推奨 |
| `仕入先ID未取得` | JSON-LD に型番なし → 別 SKU の可能性 |

---

## 9. 主要ファイル

| ファイル | 役割 |
|----------|------|
| `intake.py` | `--auto-sheet` エントリ |
| `buyma_item_parser.py` | BUYMA タイトル → ブランド/型番 |
| `supply_url_finder.py` | Step3 漏斗（キャッシュ/site:/Playwright） |
| `supply_search_utils.py` | **カテゴリ判定・クエリ・URL 検証の中枢** |
| `supply_site_search.py` | DDG site: 検索 |
| `supply_url_cache.py` | P2 キャッシュ |
| `product_identity.py` | VariantKey / MatchScore |
| `scripts/verify_intake_version.py` | ローカルコード版チェック |
| `scripts/capture_*_f12.py` | サイト別診断 |

---

## 10. 環境変数

| 変数 | 既定 |
|------|------|
| `INTAKE_FUNNEL` | `1` |
| `INTAKE_WEEKLY_LIMIT` | `40` |
| `INTAKE_OFFICIAL_PRADA` | `1` |
| `SUPPLY_URL_CACHE` | `1` |
| `SUPPLY_URL_CACHE_TTL_DAYS` | `90` |
| `SUPPLY_SEARCH_TIMEOUT_MS` | `45000` |

---

## 11. ロードマップ

| Phase | 内容 | 状態 |
|-------|------|------|
| P1 | VariantKey + MatchScore | ✅ |
| P2 | URL キャッシュ | ✅ (#27) |
| P2.5 | カテゴリ/ライン名探索 | ✅ 継続改善中 |
| P3 | 価格マルチソース投票 | 未 |
| P4 | 5サイト F12/XHR | ✅ (#26) |
| Bot/403 | MYTHERESA/NAP/24S | 候補URLs 運用本命 |

---

## 12. 新チャットへの依頼例

```
# 検証
「kato が git pull 後、1MC038 で verify と intake ログを確認してほしい」
「Step3 で fragment クエリが出るか、generic wallet が除外されるか見てほしい」

# 救済
「候補URLs 貼付後 Step3 スキップを確認したい」

# 開発
「P3 価格マルチソース投票を実装してほしい」
「MYTHERESA Bot 回避の調査をしてほしい」
「新カテゴリ（キーケース等）の Step3 精度改善を追加してほしい」
```

---

## 13. 一言サマリ（新チャット用）

**main = #25–#28 + 2026-05-21 hotfix 一式（eyewear/wicker/footwear/bracket/fragment 等）。Step4 安全装置は kato 実地で正常。kato は必ず `git pull` → `verify_intake_version.py`（v11-fragment-case）→ intake。Step3 改善後も URL が見つからない行は候補URLs 救済。Bot/403 サイトは運用上 候補URLs が本命。**

---

*BUYMA・各 EC の利用規約遵守は利用者の責任。本ファイルは会話要約であり、公式仕様の代替ではない。*
