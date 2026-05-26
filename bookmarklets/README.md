# ブックマークレット（BUYMA 候補抽出）

## 何のためか

- **需要把握**: いまブラウザで見ている BUYMA の**検索結果・ランキング・一覧**から、`/item/<商品ID>/` 形式の**商品詳細 URL** と、取れた範囲の**タイトル推定**を一覧にします。
- **「検索結果URLからの自動スクレイピングが壊れやすい」問題への別解**:
  - サーバー側の Playwright と違い、**あなたと同じ描画済み DOM** を読むので、ボット検知の影響を受けにくいことがあります。
  - **最終的な「この SKU で仕入を検討するか」「同一商品か」は必ず人手**でチェックを付け外ししてからコピーしてください（問題の「緩和」であり、ゼロリスクではありません）。

## SNS を加味したい場合

Instagram / TikTok / X は **コンテンツセキュリティポリシー（CSP）** のため、**ページ上でブックマークレットが動かない**ことが多いです。

1. SNS のキャプションやコメントを**手でコピー**する。  
2. リポジトリ内の **`bookmarklets/sns_keyword_paste.html`** をブラウザで開く（ローカルファイルで可）。  
3. 貼り付けて「抽出」→ ハッシュタグ・**BUYMA 商品 URL**（文中にあれば）を取得。  
4. BUYMA で検索／ランキングを開き、本ブックマークレットで **商品詳細 URL 候補**をまとめる。

これで 「SNS上の注目キーワード」＋「BUYMA 上の需要の目安」を**同じ作業チャネル（人間の確認付き）**に寄せられます。

## ⚠️ 利用規約・法令

BUYMA および各 SNS の利用規約を確認してください。  
本ツールは DOM をユーザー環境で読むだけであり、サイト外への自動大量取得はしません。**自己責任**でご利用ください。

---

## BUYMA ブックマークレットの作り方

### 方法A — Python 不要（おすすめ）

1. リポジトリの **`bookmarklets/install_bookmarklet.html`** をエクスプローラーでダブルクリック（Chrome / Edge で開く）。
2. **「ブックマーク用 URL をコピー」** を押す。または下のリンクを**ブックマークバーへドラッグ**。
3. BUYMA の一覧ページで実行。

（GitHub から取得する場合: ブランチ `cursor/beginner-brand-guide-6d93` の  
`bookmarklets/install_bookmarklet.html` を Raw 表示でダウンロードしても同じです。）

### 方法B — テキストファイルから手動コピー

1. **ブックマークレット本文を生成**（リポジトリルートで）:

   ```bash
   python3 scripts/build_buyma_bookmarklet.py
   ```

2. `bookmarklets/buyma_bookmarklet.txt` を開き、`javascript:` から文末までを**すべてコピー**する。

3. ブラウザのブックマークに新規登録し、**URL欄に貼り付け**て名前をつける（例: `BUYMA候補抽出`）。

4. **検索結果・ランキングなど商品リンクが並ぶページ**で、そのブックマークをクリック。

5. モーダルで一覧を確認し、**不要行のチェックを外す** → 「TSV をコピー」。

6. スプレッドシートへ:
   - **自動追記（おすすめ）**（`.env` と `credentials.json` 設定済み）:
     1. 「TSV をコピー」の直後、リポジトリルートで  
        `python3 scripts/import_buyma_tsv.py`（省略時はクリップボードから読む）  
        Windows なら `scripts\import_clipboard.bat` をダブルクリックでも可
     2. シートに **在庫ステータス = BUYMA候補** の行が追加（重複 URL はスキップ）
     3. 本番登録は `python3 intake.py` で仕入れ先 URL・価格を埋める
   - **手動**: Google スプレッドシートの A1 に貼り付け（列は分かるが `BUYMA候補` 等は自動では入らない）
   - **ファイル経由**: メモ帳に貼って `candidates.tsv` 保存 → `py scripts/import_buyma_tsv.py candidates.tsv`

### Windows: デスクトップ用ショートカット

BUYMA で「TSV をコピー」した直後に、**ダブルクリック1回**でシートへ追記する手順です。

#### 前提

- リポジトリを PC に置いている（例: `C:\Users\あなた\EC-project\invedia-automation`）  
  ※ `invedia-automation\invedia-automation` の二重フォルダになっていないか確認
- `.env` と `credentials.json` がリポジトリ**直下**にある
- Python が入っている（`py` または `python` が動く）
- 最新版を pull 済み（`scripts\import_clipboard.bat` があること）

#### 方法A — エクスプローラーから（いちばん簡単）

1. エクスプローラーで `invedia-automation\scripts` を開く
2. **`import_clipboard.bat`** を右クリック
3. **「ショートカットの作成」** → できたショートカットを**デスクトップにドラッグ**
4. デスクトップのショートカットを右クリック → **名前の変更**  
   例: `BUYMA候補→シート取込`

#### 方法B — デスクトップで新規作成（場所を自分で指定）

1. デスクトップの空いているところで右クリック → **新規作成** → **ショートカット**
2. **項目の場所**に次を貼る（パスは自分の環境に合わせて書き換え）:

   ```
   C:\Users\あなた\EC-project\invedia-automation\scripts\import_clipboard.bat
   ```

3. **次へ** → 名前: `BUYMA候補→シート取込` → **完了**

#### 使い方（毎回）

1. BUYMA の一覧ページでブックマークレット → **「TSV をコピー」**（「クリップボードにコピーしました」まで）
2. デスクトップの **`BUYMA候補→シート取込`** をダブルクリック
3. 黒い窓に `追加: …` や `完了: 追加 N 件` と出れば成功  
   エラー時だけ窓が残る（内容を読んで Enter）

#### うまく動かないとき

| 症状 | 対処 |
|------|------|
| `py` が見つからない | [python.org](https://www.python.org/downloads/) から Python を入れ、インストール時に **Add to PATH** にチェック。または bat の `py` を `python` に書き換え |
| 認証エラー | `credentials.json` の場所と `.env` の `CREDENTIALS_PATH` を確認。サービスアカウントをシートの編集者に追加 |
| 0件 / データなし | ブックマークレットのコピー直後に実行する。一覧でチェックが付いているか確認 |
| 一瞬で消えて分からない | ショートカットの「作業」欄の先頭に `cmd /k ` を付けて常に窓を残す（下記「上級」） |

#### 上級（任意）

- **作業フォルダを固定**: ショートカットのプロパティ → **作業用フォルダ** に  
  `C:\Users\あなた\EC-project\invedia-automation` を指定（通常は bat 内で自動移動するため不要）
- **窓を常に表示**: ショートカットのプロパティ → **リンク先** を  
  `cmd /k "C:\...\invedia-automation\scripts\import_clipboard.bat"` に変更
- **タスクバーに固定**: ショートカットをタスクバーへドラッグ

---

### トラブルシュート

- **何も起きない／一覧がおかしい**:  
  **過去のビルドでは**: `buyma_bookmarklet.txt` を生成するミニファイアが、`https://` 内の `//` をコメントと誤認し **コードが途中で切れていました**。  
  → **`python3 scripts/build_buyma_bookmarklet.py` で再生成した `bookmarklets/buyma_bookmarklet.txt` をブックマークの URL に貼り直してください。**  
- **エラーアラート**: メッセージを確認（最新版では予期しない例外も alert で表示します）。  
- **0件**: 読み込み未完了、または DOM に `/item/数字/` が無い。無限スクロールは下までスクロールしてから再実行。  
- **長すぎてブックマークに保存できない**: URL 長制限あり得ます。その場合は `buyma_candidates.source.js` を BUYMA のページで開発者コンソールに貼って実行（上級者向け）。  
- **誤リンクが混ざる**: チェックを外して除外。

---

## ファイル

| ファイル | 説明 |
|----------|------|
| `buyma_candidates.source.js` | 読みやすいソース（コメント付き） |
| `buyma_bookmarklet.txt` | `build_buyma_bookmarklet.py` 生成の1行 URL |
| `sns_keyword_paste.html` | SNS 文面貼り付け用（ローカルで開く） |
| `../scripts/build_buyma_bookmarklet.py` | ミニファイして txt 出力 |
