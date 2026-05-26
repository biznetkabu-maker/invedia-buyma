# 漏斗（ファネル）運用 — 方針A（単一ドキュメント）

> **コード上の定義**: `funnel_policy.py`（方針・上限・除外）  
> **実装**: `intake_funnel.py` / `intake.py --auto-sheet`

---

## 方針A: 半自動（失敗は候補URLsで救済）

| 原則 | 内容 |
|------|------|
| 自動の範囲 | 週 **40件**まで（`INTAKE_WEEKLY_LIMIT`）、型番あり `BUYMA候補` |
| 失敗時 | 行は**削除しない** → `自動見送り_*` |
| 人の救済 | シート **`候補URLs`** に仕入先新品URLを貼る → `--auto-sheet` 再実行（層3以降） |
| 出品 | **常に手動**（BUYMA規約） |
| 同一性 | 公式MPN（PRADA→prada.com）+ 仕入先 JSON-LD 型番照合（P1 MatchScore） |

```
毎日: 1_候補_抽出.bat → 2_候補_取込.bat
週次: 3_候補_自動仕入れ検討.bat  または  py intake.py --auto-sheet
救済: 自動見送り → 候補URLs 貼付 → 再 auto-sheet
出品: 出品前 の行のみ手動
```

---

## パイプライン層

| 層 | 内容 | ツール |
|----|------|--------|
| 0 | 候補の質 | ブックマークレット + 日次整理 |
| 1 | BUYMA型番確定 | Step1 / `VariantKey` |
| 1.5 | **公式照合（PRADA）** | `official_catalog.prada`（F12/XHR） |
| 2 | 仕入先URL発見 | 候補URLs → site:型番 → 5サイト検索 |
| 3 | 価格・利益・型番裁判 | `BestSourceFinder` + `price_sanity` |
| 4 | 出品 | 手動 |

---

## 環境変数（`.env`）

| 変数 | 既定 | 意味 |
|------|------|------|
| `INTAKE_FUNNEL` | `1` | 漏斗ON |
| `INTAKE_WEEKLY_LIMIT` | `40` | 週次 auto-sheet 上限 |
| `INTAKE_REQUIRE_STYLE` | `1` | 型番なし（数字IDのみ）は対象外 |
| `INTAKE_OFFICIAL_PRADA` | `1` | PRADA 時 prada.com 公式照合 |
| `SUPPLY_URL_CACHE` | `1` | (brand, MPN) → URL キャッシュ（P2） |
| `SUPPLY_URL_CACHE_TTL_DAYS` | `90` | キャッシュ有効日数 |
| `SUPPLY_URL_CACHE_MIN_GRADE` | `A` | 書込み最低同一性スコア（S のみにするなら `S`） |

---

## 在庫ステータス

| 値 | 意味 | 方針Aでの次アクション |
|----|------|---------------------|
| BUYMA候補 | 漏斗入力 | 週次 auto-sheet |
| 自動見送り_型番なし | BUYMA商品IDのみ | 型番入力 or 候補URLs |
| 自動見送り_対象外 | 香水・Re-Nylonポーチ等 | 手動 intake のみ |
| 自動見送り_仕入先なし | URL自動取得失敗 | **候補URLs 救済** |
| 自動見送り_価格不明 | スクレイプ失敗 | 候補URLs or 手動 |
| 自動見送り_利益不足 | D/E | 見送り継続 or 手動判断 |
| 出品前 | 成功 | 手動出品 |

---

## カテゴリ別（コードと一致）

| カテゴリ | 自動探索 | 救済 |
|----------|----------|------|
| 財布・バッグ（型番あり） | ◎ | 候補URLs |
| サングラス・眼鏡（型番あり） | △（PRADA公式→5サイト） | **候補URLs 推奨** |
| 香水・コスメ・50ml | × 対象外 | 手動のみ |
| Re-Nylon ミニポーチ | × 対象外 | 手動のみ |

---

## 同一性スコア（P1）

| スコア | 目安 |
|--------|------|
| S | 型番+URLヒント+公式SKU一致+在庫+価格妥当 |
| A | 型番+在庫+価格（URLヒントなし可） |
| B/C/F | 手動確認 or 見送り |

列: `同一性スコア` / `価格根拠`（S/A は自動反映の信頼度が高い目安）

---

## PRADA 公式（PR09ZS 等）

1. 自動: Step 1.5 で prada.com 照合（ローカル推奨）
2. F12メモ: `docs/PRADA_OFFICIAL_F12.md`
3. キャプチャ: `py scripts/capture_prada_f12.py PR09ZS`
4. 失敗時: FARFETCH 等の URL を `候補URLs` に貼って再実行

---

## KPI（週1メモで十分）

- 漏斗実行件数
- `出品前` になった件数
- 仕入URL取得率 = 反映 / 実行
- 救済件数（候補URLs 後に成功した件数）

---

## やらないこと

- 失敗行の自動削除
- 型番なし全件 auto-sheet
- 型番不一致の安い別SKUフォールバック
- buyma.com を main.py でスクレイプ
- 公式 prada.com を仕入先価格として採用
