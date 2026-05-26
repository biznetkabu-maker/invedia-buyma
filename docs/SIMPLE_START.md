# いちばん簡単な使い方

## Git で迷ったら（1回だけ）

**`0_環境を整える.bat`** をダブルクリック → 自動で `main` の最新に揃えます（ローカルの未保存 Git 変更は破棄）。

## 初回だけ（5分）

1. シートのタブ名を決める（例: **PurchaseControl**）— Google 側のタブ名と同じにする
2. **credentials.json** をこのフォルダに置く（サービスアカウントをシートの編集者に追加）
3. **初回だけ設定.bat** → スプレッドシート URL を貼る

## 毎日 — 候補を溜める（2ファイルだけ）

| 順番 | ファイル | やること |
|------|----------|----------|
| **1** | **1_候補_抽出.bat** | 説明ページが開く → BUYMA 一覧で **F12 → Console → Ctrl+V → Enter** → 白い画面で **TSV をコピー** |
| **2** | **2_候補_取込.bat** | ダブルクリック（シートに追記） |

件数だけ見たいとき: **候補_件数.bat**

週1でシートを整理: **型番あり**の行を残し、不要行は削除（または `自動見送り` を確認）

## 仕入れを検討するとき（週に数件・漏斗モード）

**自動（おすすめ）** — 候補をシートに溜めたあと:

| 操作 | ファイル / コマンド |
|------|---------------------|
| 漏斗で自動検討（週上限40件・型番必須） | **3_候補_自動仕入れ検討.bat** |
| 1件だけ試す | `py intake.py --auto-sheet --limit 1` |
| BUYMA URL から1件 | `py intake.py --auto-buyma <URL>` |

**漏斗でやること（自動）**

1. **型番あり**（またはシートの **候補URLs** に海外URLが1本入っている）行だけ処理
2. **候補URLs** があれば探索スキップ → 価格・利益だけ判定
3. なければ **型番 + site:farfetch.com 等** で商品URL検索 → ダメなら Playwright サイト内検索
4. 失敗した行は **削除しない** → 在庫ステータスが `自動見送り_*` に変わる

**手動** — 自動見送り・1BB108 のような難しい SKU:

```powershell
py intake.py
```

またはシートの **候補URLs** 列に正しい FARFETCH URL を貼ってから `--auto-sheet --limit 1`。

売価は **Enter** だけ（競合最安 × 0.97）。

運用は **方針A**（`FUNNEL_OPS.md`）: 自動失敗 → `自動見送り_*` → **候補URLs** で救済。

環境変数（任意）:

- `INTAKE_WEEKLY_LIMIT=40` … 週の自動処理上限
- `INTAKE_REQUIRE_STYLE=1` … 型番なし行はスキップ（既定ON）
- `INTAKE_OFFICIAL_PRADA=1` … PRADA 時 prada.com 公式照合（`PR09ZS` 等）

## 古いファイル名について

`BUYMA候補抽出.bat` / `BUYMA取込.bat` も同じ動作です（中身は上記2つに転送）。

## うまくいかないとき

- **`git pull` で unmerged files / 競合** → **`修復_gitで最新を取得.bat`**
- 開始時に **`[intake 自動 v7]`** と **漏斗モード** が出るか → `py scripts\verify_intake_version.py` / `py scripts\diagnose_code_version.py`
- **シートが見つかりません** → **シート接続確認.bat** / `worksheet_name.txt` をタブ名に合わせる
- 詳細は `OPERATIONS.md` / `FUNNEL_OPS.md`
