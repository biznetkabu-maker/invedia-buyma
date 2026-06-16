"""
仕入先サイト 検索URL生成・表示モジュール。

【設計方針】
  「検索結果ページの自動スクレイプ」は採用しない。理由:
    - 検索結果ページは商品ページより構造が複雑で壊れやすい
    - 日本語商品名が英語サイトで一致しないことが多い
    - ブラウザブロック・レート制限を受けやすい

  このモジュールが担う役割:
    1. ブランド名・商品名から各サイトの検索URLを生成する
    2. サイトをカテゴリ別に整理して表示する
    3. ユーザーが商品URLを貼り付けた後の BestSourceFinder を補助する

  信頼性の高い自動化（BestSourceFinder）は「商品ページURL」に対して行う。
  「検索結果ページ→商品ページURL」の変換だけが手動パートとして残る。

対象サイト選定根拠:
  BUYMA の「バイヤー利用可能な仕入れ先」に準拠し、かつ専用スクレイパー
  戦略が実装済みのサイトのみを対象とする。
    - 公式オンラインストア系: なし（ブランドごとに異なるため別途対応）
    - 百貨店: HARRODS / SELFRIDGES / SAKS / HARVEY NICHOLS / NEIMAN MARCUS
    - グローバルセレクト: SSENSE / NET-A-PORTER / MR PORTER / MYTHERESA /
                          FARFETCH / MATCHESFASHION / LUISAVIAROMA / 24S
    - 欧州セレクト: TESSABIT / GIGLIO / BIFFI
    - アウトレット: YOOX / THE OUTNET（除外 — 正規品・新品が基本のため）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote_plus

# ============================================================================
# サイト定義（全15サイト）
# ============================================================================

@dataclass(frozen=True)
class SiteDefinition:
    """仕入先サイトの定義。"""
    name: str
    domain: str                     # scraper/engine.py と対応するドメイン
    search_url_template: str        # {q} をエンコード済みクエリに置換
    currency: str
    category: str                   # "百貨店" / "グローバルセレクト" / "欧州セレクト"
    buyma_certified: bool = True    # BUYMA認定仕入先か


# グローバルセレクト系（BUYMAで最も頻繁に使用される）
_GLOBAL_SELECT: list[SiteDefinition] = [
    SiteDefinition(
        name="SSENSE",
        domain="ssense.com",
        search_url_template="https://www.ssense.com/en-us/women?q={q}",
        currency="USD",
        category="グローバルセレクト",
    ),
    SiteDefinition(
        name="NET-A-PORTER",
        domain="net-a-porter.com",
        search_url_template="https://www.net-a-porter.com/en-us/search?q={q}",
        currency="USD",
        category="グローバルセレクト",
    ),
    SiteDefinition(
        name="MR PORTER",
        domain="mrporter.com",
        search_url_template="https://www.mrporter.com/en-us/search?q={q}",
        currency="USD",
        category="グローバルセレクト",
        buyma_certified=True,
    ),
    SiteDefinition(
        name="MYTHERESA",
        domain="mytheresa.com",
        search_url_template="https://www.mytheresa.com/en-us/search/?q={q}",
        currency="USD",
        category="グローバルセレクト",
    ),
    SiteDefinition(
        name="FARFETCH",
        domain="farfetch.com",
        search_url_template="https://www.farfetch.com/shopping/women/search/items.aspx?q={q}",
        currency="USD",
        category="グローバルセレクト",
    ),
    SiteDefinition(
        name="MATCHESFASHION",
        domain="matchesfashion.com",
        search_url_template="https://www.matchesfashion.com/search?q={q}",
        currency="GBP",
        category="グローバルセレクト",
    ),
    SiteDefinition(
        name="24S（LVMHグループ）",
        domain="24s.com",
        search_url_template="https://www.24s.com/en-us/search?q={q}",
        currency="EUR",
        category="グローバルセレクト",
    ),
    SiteDefinition(
        name="LUISAVIAROMA",
        domain="luisaviaroma.com",
        search_url_template="https://www.luisaviaroma.com/en-us/shop/?lvrid=_search&q={q}",
        currency="USD",
        category="グローバルセレクト",
    ),
]

# 百貨店系（BUYMA公認の正規販売代理店）
_DEPARTMENT_STORES: list[SiteDefinition] = [
    SiteDefinition(
        name="HARRODS",
        domain="harrods.com",
        search_url_template="https://www.harrods.com/en-gb/search-results?q={q}",
        currency="GBP",
        category="百貨店",
    ),
    SiteDefinition(
        name="SELFRIDGES",
        domain="selfridges.com",
        search_url_template="https://www.selfridges.com/GB/en/cat/?q={q}",
        currency="GBP",
        category="百貨店",
    ),
    SiteDefinition(
        name="SAKS FIFTH AVENUE",
        domain="saksfifthavenue.com",
        search_url_template="https://www.saksfifthavenue.com/search?q={q}",
        currency="USD",
        category="百貨店",
    ),
    SiteDefinition(
        name="HARVEY NICHOLS",
        domain="harveynichols.com",
        search_url_template="https://www.harveynichols.com/search?q={q}",
        currency="GBP",
        category="百貨店",
    ),
    SiteDefinition(
        name="NEIMAN MARCUS",
        domain="neimanmarcus.com",
        search_url_template="https://www.neimanmarcus.com/search?q={q}",
        currency="USD",
        category="百貨店",
    ),
]

# 欧州セレクト系（イタリア系 — CELINE / Margiela に強い）
_EUROPEAN_SELECT: list[SiteDefinition] = [
    SiteDefinition(
        name="TESSABIT",
        domain="tessabit.com",
        search_url_template="https://www.tessabit.com/en/search?q={q}",
        currency="EUR",
        category="欧州セレクト",
    ),
    SiteDefinition(
        name="GIGLIO",
        domain="giglio.com",
        search_url_template="https://www.giglio.com/en/search/?q={q}",
        currency="EUR",
        category="欧州セレクト",
    ),
    SiteDefinition(
        name="BIFFI",
        domain="biffi.com",
        search_url_template="https://www.biffi.com/en/search?q={q}",
        currency="EUR",
        category="欧州セレクト",
    ),
]

# 全サイトリスト（アウトレットは除外）
ALL_SITES: list[SiteDefinition] = _GLOBAL_SELECT + _DEPARTMENT_STORES + _EUROPEAN_SELECT

# ドメイン→サイト定義のマップ（BestSourceFinder のURL逆引き用）
SITE_BY_DOMAIN: dict[str, SiteDefinition] = {s.domain: s for s in ALL_SITES}


# ============================================================================
# データモデル
# ============================================================================

@dataclass
class SearchURLSet:
    """ブランド・商品名から生成した全サイトの検索URLセット。"""

    brand: str
    product_name: str
    query: str
    by_category: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # カテゴリ名 → [(サイト名, 検索URL), ...]

    def display(self) -> str:
        """ターミナル表示用の整形テキストを返す。"""
        lines = [
            f"\n  「{self.brand} {self.product_name}」の検索URL一覧",
            "  " + "─" * 56,
        ]
        idx = 1
        for category, items in self.by_category.items():
            lines.append(f"\n  【{category}】")
            for site_name, url in items:
                lines.append(f"  [{idx:2}] {site_name}")
                lines.append(f"       {url}")
                idx += 1
        lines.append("")
        return "\n".join(lines)


# ============================================================================
# 公開 API
# ============================================================================

def build_search_urls(
    brand: str,
    product_name: str,
    sites: list[str] | None = None,
) -> SearchURLSet:
    """ブランド名・商品名から全サイトの検索URLを生成する。

    Args:
        brand: ブランド名（例: "CELINE"）
        product_name: 商品名（例: "トリオバッグ スモール"）
        sites: 対象サイト名リスト（None で全サイト）

    Returns:
        SearchURLSet（.display() でターミナル表示、.by_category で辞書アクセス）
    """
    # 日本語を含む場合は英語商品名も試みる
    # （サイトが英語のため、日本語クエリが機能しないことがある）
    query = f"{brand} {product_name}"
    encoded = quote_plus(query)

    target_sites = [s for s in ALL_SITES if sites is None or s.name in sites]

    by_category: dict[str, list[tuple[str, str]]] = {}
    for site in target_sites:
        url = site.search_url_template.replace("{q}", encoded)
        if site.category not in by_category:
            by_category[site.category] = []
        by_category[site.category].append((site.name, url))

    return SearchURLSet(
        brand=brand,
        product_name=product_name,
        query=query,
        by_category=by_category,
    )


def get_all_candidate_urls(brand: str, product_name: str) -> list[str]:
    """ブランド名・商品名から全サイトの検索URLをリストで返す（後方互換用）。"""
    result = build_search_urls(brand, product_name)
    urls = []
    for items in result.by_category.values():
        for _, url in items:
            urls.append(url)
    return urls


def site_name_from_url(url: str) -> str:
    """URLからサイト名を返す。不明な場合はドメインを返す。"""
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower()
    for domain, site in SITE_BY_DOMAIN.items():
        if domain in netloc:
            return site.name
    return netloc
