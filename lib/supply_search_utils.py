"""
仕入先検索用のクエリ整形（BUYMA タイトルのノイズ除去・型番候補の抽出）。
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

_BRACKET_TAG = re.compile(r"【[^】]*】|\[[^\]]*\]")
_DECORATIVE_CHARS = re.compile(r"[♪★☆♥♡♫♬♩♭♯]+")
_MODEL_CODE = re.compile(r"\b([A-Z0-9][A-Z0-9-]{3,})\b", re.I)
_NUMERIC_ONLY = re.compile(r"^\d{7,}$")
# 容量・寸法のみ（型番ではない）
_VOLUME_OR_SIZE = re.compile(
    r"^\d+\s*(?:ml|mL|l|oz|g|kg|mm|cm)$|^\d+ml$|^\d+l$",
    re.I,
)

# BUYMA タイトルでよく見る日本語表記 → 英語ブランド（site: 検索・公式照合用）
_BRAND_JA_ALIASES: dict[str, str] = {
    "プラダ": "PRADA",
    "グッチ": "GUCCI",
    "セリーヌ": "CELINE",
    "シャネル": "CHANEL",
    "ルイヴィトン": "LOUIS VUITTON",
    "ヴィトン": "LOUIS VUITTON",
    "バレンシアガ": "BALENCIAGA",
    "サンローラン": "SAINT LAURENT",
    "ボッテガ": "BOTTEGA VENETA",
    "フェンディ": "FENDI",
    "ディオール": "DIOR",
    "ロエベ": "LOEWE",
    "マルジェラ": "MAISON MARGIELA",
    "ジルサンダー": "JIL SANDER",
}


def dedupe_product_phrase(text: str) -> str:
    """同じフレーズが2回続く商品名を1回にまとめる。"""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) < 4:
        return s
    mid = len(s) // 2
    left, right = s[:mid].strip(), s[mid:].strip()
    if left and left == right:
        return left
    words = s.split()
    n = len(words)
    for size in range(1, n // 2 + 1):
        if n % size != 0:
            continue
        chunk = " ".join(words[:size])
        if all(" ".join(words[i : i + size]) == chunk for i in range(0, n, size)):
            return chunk
    return s


def clean_product_name_for_search(product_name: str, brand: str = "") -> str:
    """BUYMA 由来の冗長な商品名を検索用に短くする。"""
    s = (product_name or "").strip()
    if not s:
        return ""

    s = _DECORATIVE_CHARS.sub(" ", s)
    s = _BRACKET_TAG.sub(" ", s)
    s = re.sub(r"[◆・]+", " ", s)

    b = normalize_brand_name(brand) if brand else ""
    if b:
        bl = b.lower()
        s = re.sub(rf"\b{re.escape(b)}◆", " ", s, flags=re.I)
        for _ in range(4):
            st = s.strip()
            if st.lower().startswith(bl):
                s = st[len(b):].strip(" -|/：:・◆")
            else:
                break
    for noise in (
        "VIPセール", "vip sale", "新品", "正規品", "送料込", "コイン",
        "re-nylon", "re nylon", "直営", "アウトレット", "outlet",
    ):
        s = re.sub(re.escape(noise), " ", s, flags=re.I)

    if b:
        bl = b.lower()
        tokens = []
        for tok in s.split():
            tl = tok.lower()
            if tl == bl or tl.startswith(bl + "◆"):
                continue
            if "◆" in tok:
                for part in re.split(r"◆", tok):
                    part = part.strip()
                    if part and part.lower() not in (bl, "re-nylon", "re"):
                        tokens.append(part)
                continue
            tokens.append(tok)
        s = " ".join(tokens)

    return dedupe_product_phrase(re.sub(r"\s+", " ", s).strip())


def is_plausible_model_code(code: str) -> bool:
    """仕入先検索・型番照合に使えるコードか（50ml / 100ml 等は除外）。"""
    c = (code or "").strip()
    if len(c) < 5:
        return False
    if _NUMERIC_ONLY.match(c) or _VOLUME_OR_SIZE.match(c):
        return False
    if not re.search(r"[A-Za-z]", c) or not re.search(r"\d", c):
        return False
    return True


def compress_style_id_for_search(style_id: str, *, max_len: int = 10) -> str:
    """完全 SKU（2VG1312CYAF0216 等）から site: 検索用の短い型番を推定。"""
    s = (style_id or "").strip().upper()
    if len(s) <= max_len:
        return s
    m = re.match(r"^(\d{1,2}[A-Z]{1,3}\d{3})(?:[A-Z0-9]|$)", s)
    if m:
        return m.group(1)
    return s[:max_len]


def style_id_for_site_search(style_id: str) -> str:
    """DDG site: / Playwright 検索クエリ用（照合は完全 SKU のまま）。"""
    return compress_style_id_for_search(style_id)


def extract_model_codes(*texts: str) -> list[str]:
    """タイトル・型番欄から仕入先検索に使えるコード候補を抽出。"""
    seen: set[str] = set()
    out: list[str] = []

    def add(code: str) -> None:
        raw = code.strip()
        if not is_plausible_model_code(raw) or raw.upper() in seen:
            return
        seen.add(raw.upper())
        out.append(raw)

    for text in texts:
        if not text:
            continue
        for m in _MODEL_CODE.finditer(text):
            add(m.group(1))

    return out


def supplemental_search_queries(brand: str, raw_product_name: str) -> list[str]:
    """英語サイト向けの補助クエリ（Re-Nylon 等、clean で落ちた語を復元）。"""
    brand = normalize_brand_name(brand)
    raw = (raw_product_name or "").strip()
    if not brand or not raw:
        return []

    out: list[str] = []
    raw_l = raw.lower()
    if "re-nylon" in raw_l or "re nylon" in raw_l:
        if "ミニ" in raw or "mini" in raw_l:
            out.append(f"{brand} re nylon mini pouch")
        else:
            out.append(f"{brand} re nylon pouch")
    if "ミニポーチ" in raw or "mini pouch" in raw_l:
        q = f"{brand} mini pouch"
        if "nylon" in raw_l or "re-nylon" in raw_l:
            q = f"{brand} nylon mini pouch"
        out.append(q)
    return out



def infer_supply_department(product_name: str) -> str:
    """仕入先検索の部門（men / women）。未判定は women。"""
    raw = (product_name or "").strip()
    name_l = f" {raw.lower()} "
    if any(
        k in name_l
        for k in (" メンズ ", " men's ", " mens ", " men ", "ボーイズ", " boys ")
    ):
        return "men"
    if raw.lower().startswith(("men ", "mens ", "men's ")):
        return "men"
    if any(
        k in name_l
        for k in (" レディース ", " women's ", " womens ", " women ", "ウィメンズ")
    ):
        return "women"
    return "women"



_FOOTWEAR_KEYS = (
    "サンダル", "sandal", "スニーカー", "sneaker", "シューズ", "shoe",
    "ブーツ", "boot", "ローファー", "loafer", "パンプス", "pump",
    "スライド", "slide", "サボ", "mule", "フラット", "flat", "trainer",
)
_JP_LINE_HINTS: dict[str, str] = {
    "モノリス": "monolith",
    "シンティーロ": "cinturo",
    "レディー": "lady",
    "ガレリア": "galleria",
    "ジャルディニエール": "jardiniere",
    "フラグメント": "fragment",
}
_POUCH_ACCESSORY_MARKERS = (
    "ポーチ付", "ポーチつき", "pouch付", "with pouch", "w/ pouch",
)


def is_footwear_product_name(product_name: str) -> bool:
    name_l = (product_name or "").lower()
    return any(k in name_l for k in _FOOTWEAR_KEYS)


def is_primary_pouch_product_name(product_name: str) -> bool:
    """ポーチ本体。ポーチ付スニーカー等は付属語のため False。"""
    name_l = (product_name or "").lower()
    if is_footwear_product_name(product_name):
        return False
    if any(k in name_l for k in _POUCH_ACCESSORY_MARKERS):
        return False
    return any(k in name_l for k in ("ポーチ", "pouch", "ミニポーチ"))



def line_name_search_tokens(product_name: str, official_english_name: str = "") -> list[str]:
    """商品ライン名（モノリス等）を英語検索トークンに。"""
    out: list[str] = []
    seen: set[str] = set()
    for src in (product_name or "", official_english_name or ""):
        for jp, en in _JP_LINE_HINTS.items():
            if jp in src and en not in seen:
                seen.add(en)
                out.append(en)
        low = src.lower()
        for en in _JP_LINE_HINTS.values():
            if en in low and en not in seen:
                seen.add(en)
                out.append(en)
    return out


def footwear_search_extras(product_name: str) -> list[str]:
    name_l = (product_name or "").lower()
    if any(k in name_l for k in ("スニーカー", "sneaker", "trainer")):
        return ["sneaker", "sneakers", "shoes"]
    if any(
        k in name_l
        for k in ("モノリス", "monolith", "厚底", "platform", "mule", "ミュール")
    ):
        return ["monolith", "sandal", "mules", "mule", "sandals"]
    if any(k in name_l for k in ("サンダル", "sandal", "slide", "サボ")):
        return ["sandal", "sandals", "mule", "shoes"]
    return ["shoes", "sneakers"]


def is_fragment_case_product_name(product_name: str) -> bool:
    name_l = (product_name or "").lower()
    return any(
        k in name_l
        for k in (
            "フラグメント",
            "fragment",
            "フラグメントケース",
            "カードケース",
            "card case",
            "card-case",
            "card holder",
            "card-holder",
            "名刺入れ",
            "名刺ケース",
        )
    )


def category_site_search_extras(product_name: str) -> list[str]:
    """site: 検索・型番クエリ用の英語カテゴリ語（優先順）。"""
    name_l = (product_name or "").lower()
    if any(
        k in name_l
        for k in (
            "ベルトバッグ",
            "ボディバッグ",
            "belt bag",
            "body bag",
            "bum bag",
            "waist bag",
        )
    ):
        return ["belt-bag", "body-bag", "crossbody"]
    if any(k in name_l for k in ("財布", "wallet", "ウォレット")):
        return ["wallet"]
    if is_fragment_case_product_name(product_name):
        return ["fragment", "card-holder", "card-case"]
    if any(
        k in name_l
        for k in ("バケット", "bucket bag", "bucket-bag", "bucket")
    ) or any(k in name_l for k in ("ウィッカー", "wicker", "ラタン", "rattan")):
        extras = ["bucket-bag", "bucket", "bag"]
        if any(k in name_l for k in ("ウィッカー", "wicker", "ラタン", "rattan")):
            return ["wicker", "bucket-bag", "bucket"]
        return extras
    if any(
        k in name_l
        for k in ("ハンドバッグ", "handbag", "hand bag", "hand-bag")
    ):
        return ["hand-bag", "handbag", "bag"]
    if any(k in name_l for k in ("サングラス", "sunglass", "eyewear", "メガネ", "眼鏡")):
        return ["sunglasses"]
    if any(
        k in name_l
        for k in ("ドックキャリ", "キャリーバッグ", "dog carrier", "pet carrier")
    ):
        return ["dog-carrier", "carrier", "tote"]
    if is_footwear_product_name(product_name):
        return footwear_search_extras(product_name)
    if any(k in name_l for k in ("バッグ", "bag", "トート", "tote")):
        if any(k in name_l for k in ("クロシェ", "crochet")):
            return ["crochet", "tote", "bag"]
        if any(k in name_l for k in ("ショルダー", "shoulder", "2way", "2-way")):
            return ["shoulder-bag", "shoulder", "bag"]
        if any(k in name_l for k in ("トート", "tote")):
            return ["tote", "bag"]
        return ["bag"]
    if is_primary_pouch_product_name(product_name):
        return ["pouch", "bag"]
    pos, _ = infer_supply_category_hints(product_name)
    return list(pos[:3])


def apply_department_to_search_template(template: str, department: str, domain: str = "") -> str:
    """サイト検索 URL テンプレに men / women 部門を反映する。"""
    dept = "men" if (department or "").lower().startswith("men") else "women"
    tpl = template
    if dept == "men" and domain == "net-a-porter.com":
        from lib.product_finder import SITE_BY_DOMAIN

        mr = SITE_BY_DOMAIN.get("mrporter.com")
        if mr:
            return mr.search_url_template
    if dept == "men":
        tpl = tpl.replace("/women/", "/men/").replace("/women?", "/men?")
    return tpl


def infer_supply_category_hints(product_name: str) -> tuple[list[str], list[str]]:
    """探索・ランキング用のカテゴリ語（加点）と URL パス除外語（減点）。"""
    name_l = (product_name or "").lower()
    positive: list[str] = []
    negative: list[str] = []

    if any(k in name_l for k in ("サングラス", "sunglass", "eyewear", "メガネ", "眼鏡")):
        positive.extend(("sunglasses", "eyewear", "glasses"))
        negative.extend(("wallet", "trouser", "boots", "boot"))
    elif any(k in name_l for k in ("財布", "wallet", "ウォレット")):
        positive.extend(("wallet", "zip", "saffiano", "leather-wallet"))
        negative.extend(("eyewear", "sunglasses", "trouser", "boot"))
    elif is_fragment_case_product_name(product_name):
        positive.extend(("fragment", "card-holder", "card-case", "card"))
        negative.extend(
            ("eyewear", "sunglasses", "trouser", "boot", "bag", "tote", "pouch")
        )
    elif any(
        k in name_l
        for k in ("ハンドバッグ", "handbag", "hand bag", "hand-bag")
    ):
        positive.extend(("hand-bag", "handbag", "bag", "tote"))
        negative.extend(("eyewear", "sunglasses", "wallet", "pouch", "trouser"))
    elif any(
        k in name_l
        for k in ("バケット", "bucket bag", "bucket-bag", "bucket")
    ) or any(k in name_l for k in ("ウィッカー", "wicker", "ラタン", "rattan")):
        positive.extend(("wicker", "bucket-bag", "bucket", "bag"))
        negative.extend(
            ("eyewear", "sunglasses", "wallet", "pouch", "darling", "wish", "re-nylon")
        )
    elif any(
        k in name_l
        for k in ("ドックキャリ", "キャリーバッグ", "dog carrier", "pet carrier")
    ):
        positive.extend(("dog-carrier", "carrier", "tote", "bag"))
        negative.extend(("pouch", "wallet", "mini-pouch", "eyewear", "sunglasses"))
    elif any(
        k in name_l
        for k in (
            "ベルトバッグ",
            "ボディバッグ",
            "belt bag",
            "body bag",
            "bum bag",
            "waist bag",
        )
    ):
        positive.extend(("belt-bag", "body-bag", "bum-bag", "crossbody"))
        negative.extend(("wallet", "eyewear", "sunglasses", "trouser", "boot", "pouch"))
    elif any(k in name_l for k in ("バッグ", "bag", "トート", "tote")):
        if any(k in name_l for k in ("クロシェ", "crochet")):
            positive.extend(("crochet", "tote", "bag"))
        elif any(k in name_l for k in ("ショルダー", "shoulder", "2way", "2-way")):
            positive.extend(("shoulder-bag", "shoulder", "bag"))
        elif any(k in name_l for k in ("トート", "tote")):
            positive.extend(("tote", "bag", "shoulder"))
        else:
            positive.extend(("bag", "shoulder", "tote"))
        negative.extend(("eyewear", "sunglasses", "trouser", "pouch", "wallet"))
    elif is_footwear_product_name(product_name):
        if any(k in name_l for k in ("スニーカー", "sneaker", "trainer")):
            positive.extend(("sneaker", "sneakers", "shoes", "trainers"))
        elif any(k in name_l for k in ("サンダル", "sandal", "slide")):
            positive.extend(("sandal", "sandals", "slide", "slides", "shoes"))
        else:
            positive.extend(("shoes", "sneakers", "sandal"))
        negative.extend(
            ("wallet", "eyewear", "sunglasses", "pouch", "bag", "leather-wallet", "t-shirt")
        )
    elif is_primary_pouch_product_name(product_name):
        positive.extend(("pouch", "bag"))
        negative.extend(("eyewear", "sunglasses", "trouser", "wallet"))
    elif any(
        k in name_l
        for k in (
            "tシャツ", "t-shirt", "t shirt", "Ｔシャツ", "tee",
            "トップス", "シャツ", "shirt", "ポロ", "カーディガン",
            "ニット", "スウェット", "パーカー", "フーディ", "hoodie",
            "コート", "ジャケット", "jacket", "dress", "スカート",
        )
    ):
        positive.extend(("t-shirt", "shirt", "top"))
        negative.extend(("wallet", "eyewear", "sunglasses", "leather-wallet", "bag"))
    else:
        from lib.funnel_policy import is_eyewear_product_name

        if is_eyewear_product_name(product_name):
            positive.extend(("sunglasses", "eyewear"))
            negative.extend(("wallet", "trouser"))
        else:
            # 型番のみ・セール等 — eyewear は DDG/FARFETCH 検索のノイズになりやすい
            positive.extend(("wallet", "leather-wallet", "bag", "saffiano"))
            negative.extend(("eyewear", "sunglasses", "trouser", "boot"))

    return positive, negative


def build_supply_search_queries(
    brand: str,
    product_name: str,
    style_id: Optional[str] = None,
    *,
    raw_product_name: Optional[str] = None,
    official_english_name: str = "",
) -> list[str]:
    """仕入先検索に使うクエリを優先順で列挙する。"""
    brand = normalize_brand_name(brand)
    cleaned = clean_product_name_for_search(product_name, brand)
    queries: list[str] = []

    if brand and cleaned:
        queries.append(f"{brand} {cleaned}".strip())

    raw = (raw_product_name or product_name or "").strip()
    for extra in supplemental_search_queries(brand, raw):
        if extra not in queries:
            queries.append(extra)

    sid = (style_id or "").strip()
    search_sid = style_id_for_site_search(sid) if sid else ""
    pos, _ = infer_supply_category_hints(raw or cleaned)

    for code in extract_model_codes(product_name, style_id or "", raw):
        if pos and brand and code.upper() == (search_sid or sid).upper():
            continue  # 型番のみは別SKUヒットしやすい
        if brand:
            queries.append(f"{brand} {code}")
        queries.append(code)

    extras = category_site_search_extras(raw or cleaned)
    line_tokens = line_name_search_tokens(raw or cleaned, official_english_name)
    if search_sid and is_plausible_model_code(search_sid) and brand:
        cat_queries: list[str] = []
        for hint in extras[:3]:
            cat_q = f"{brand} {search_sid} {hint}".strip()
            if cat_q.lower() not in {q.lower() for q in queries + cat_queries}:
                cat_queries.append(cat_q)
        for token in line_tokens[:2]:
            cat_q = f"{brand} {search_sid} {token}".strip()
            if cat_q.lower() not in {q.lower() for q in queries + cat_queries}:
                cat_queries.insert(0, cat_q)
        if official_english_name and brand:
            short = " ".join(official_english_name.split()[:4])
            off_q = f"{brand} {search_sid} {short}".strip()
            if off_q.lower() not in {q.lower() for q in queries + cat_queries}:
                cat_queries.insert(0, off_q)
        if cat_queries:
            queries = cat_queries + queries

    if sid and is_plausible_model_code(sid) and sid not in queries:
        queries.append(sid)
    if search_sid and search_sid != sid:
        bare = f"{brand} {search_sid}".strip() if brand else search_sid
        if bare.lower() not in {q.lower() for q in queries}:
            queries.append(bare)
    elif search_sid and brand and not pos:
        bare = f"{brand} {search_sid}".strip()
        if bare.lower() not in {q.lower() for q in queries}:
            queries.append(bare)

    if cleaned and cleaned not in queries:
        queries.append(cleaned)

    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique


def resolve_style_id_for_supply_search(
    product_name: str,
    style_id: Optional[str] = None,
) -> Optional[str]:
    """仕入先検索用。タイトル中の型番を優先し、長い数字のみの BUYMA ID は使わない。"""
    codes = extract_model_codes(product_name, style_id or "")
    if codes:
        return codes[0]
    sid = (style_id or "").strip()
    if sid and is_plausible_model_code(sid):
        return sid
    return None


def best_demand_search_phrase(
    brand: str,
    product_name: str,
    style_id: Optional[str] = None,
) -> str:
    """BUYMA 需要検索用の短いフレーズ。"""
    queries = build_supply_search_queries(brand, product_name, style_id)
    if queries:
        return queries[0]
    cleaned = clean_product_name_for_search(product_name, brand)
    return f"{brand} {cleaned}".strip() if cleaned else brand


def _canonical_brand_from_japanese(text: str) -> Optional[str]:
    """プラダ☆キルティング 等から PRADA を抽出。"""
    s = (text or "").strip()
    if not s:
        return None
    for segment in re.split(r"[☆★◆・\s]+", s):
        seg = segment.strip()
        if not seg:
            continue
        for alias, canon in _BRAND_JA_ALIASES.items():
            if seg == alias or seg.startswith(alias):
                return canon
    for alias, canon in sorted(_BRAND_JA_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in s:
            return canon
    return None


def _brand_from_bracket_tags(text: str) -> str:
    """【PRADA】等のブランドタグ（セール系タグは除外）。"""
    for m in _BRACKET_TAG.finditer(text or ""):
        inner = m.group(0).strip("【】[] ").strip()
        if not inner or re.search(
            r"セール|sale|vip|限定|数量|国内|送料|即発|新品",
            inner,
            re.I,
        ):
            continue
        if re.match(r"^[A-Za-z]{2,20}$", inner):
            return inner.upper()
        ja = _canonical_brand_from_japanese(inner)
        if ja:
            return ja
    return ""


_MARKETPLACE_BRAND_NOISE = frozenset({"buyma", "バイマ"})


def is_marketplace_brand_noise(brand: str) -> bool:
    """BUYMA ページ JSON-LD / シート列のプラットフォーム名。"""
    s = (brand or "").strip().casefold()
    return s in _MARKETPLACE_BRAND_NOISE


def resolve_merchandise_brand(*sources: Optional[str]) -> str:
    """複数ソースから最初の有効な商品ブランドを選ぶ（BUYMA 等は除外）。"""
    for source in sources:
        s = (source or "").strip()
        if not s:
            continue
        tag = _brand_from_bracket_tags(s)
        if tag:
            b = normalize_brand_name(tag)
            if b and not is_marketplace_brand_noise(b):
                return b
        first = s.split(None, 1)[0]
        if first:
            b = normalize_brand_name(first)
            if b and not is_marketplace_brand_noise(b):
                if re.match(r"^[A-Za-z]{2,20}$", b) or _canonical_brand_from_japanese(first):
                    return b
        if " " not in s:
            b = normalize_brand_name(s)
            if b and not is_marketplace_brand_noise(b):
                return b
    return ""


def normalize_brand_name(brand: str) -> str:
    """【VIPセール】PRADA / ♪直営アウトレット♪PRADA / プラダ☆キルティング 等を正規化。"""
    tag_brand = _brand_from_bracket_tags(brand or "")
    if tag_brand and not is_plausible_model_code(tag_brand):
        return tag_brand

    s = _BRACKET_TAG.sub(" ", brand or "").strip()
    s = _DECORATIVE_CHARS.sub(" ", s)
    s = re.sub(r"[◆・☆★]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""

    ja_brand = _canonical_brand_from_japanese(brand or s)
    if ja_brand:
        return ja_brand

    # セラー装飾語の後ろの PRADA 等（♪直営アウトレット♪PRADA）
    upper_tokens = re.findall(r"\b([A-Z]{2,20})\b", s)
    if upper_tokens:
        return upper_tokens[-1]

    # PRADA◆Re-Nylon のように連結されている場合
    head = re.match(r"^([A-Za-z]{2,20})", s.replace(" ", ""))
    if head:
        word = head.group(1)
        if word.isupper() or len(word) <= 6:
            return word.upper() if word.isupper() else word

    for token in s.split():
        for part in re.split(r"[◆\-]", token):
            t = part.strip(" -|/：:・◆")
            if not t:
                continue
            if re.match(r"^[A-Za-z]{2,20}$", t):
                return t.upper() if t.isupper() else t
    result = s.split()[0] if s.split() else s
    if is_plausible_model_code(result):
        if tag_brand:
            return tag_brand
        ja = _canonical_brand_from_japanese(brand or s)
        if ja:
            return ja
    return result


def brand_slug(brand: str) -> str:
    b = normalize_brand_name(brand).lower()
    return re.sub(r"[^a-z0-9]+", "-", b).strip("-")


def url_matches_brand(brand: str, url: str) -> bool:
    """仕入先 URL にブランド名が含まれるか（誤ヒット除外）。"""
    slug = brand_slug(brand)
    if not slug or len(slug) < 3:
        return True
    return slug in url.lower()


def sheet_style_id_value(product_name: str, style_id: Optional[str] = None) -> str:
    """シートの型番列・照合用。モデル番号を優先。BUYMA 商品 ID のみの場合は空。"""
    resolved = resolve_style_id_for_supply_search(product_name, style_id)
    if resolved:
        return resolved
    sid = (style_id or "").strip()
    if sid and is_plausible_model_code(sid):
        return sid
    return ""

_DISALLOWED_SUPPLY_PATH = re.compile(
    r"pre-?owned|vintage|second-hand|used-wear|outlet|archive-sale",
    re.I,
)


def url_is_retail_supply_candidate(url: str) -> bool:
    """中古・アウトレット系の商品URLを除外（新品仕入れ向け）。"""
    return not _DISALLOWED_SUPPLY_PATH.search(url or "")


_FARFETCH_ITEM_PATH = re.compile(
    r"(?:/[a-z]{2})?/shopping/(?:women|men)/(.+)-item-(\d+)\.aspx$",
    re.I,
)


def is_valid_farfetch_product_url(url: str) -> bool:
    """FARFETCH 商品 URL の形式チェック（検索結果の壊れた slug を除外）。"""
    path = urlparse(url).path
    if not path.lower().endswith(".aspx"):
        return False
    if "--" in path:
        return False
    m = _FARFETCH_ITEM_PATH.search(path)
    if not m:
        return False
    slug, item_id = m.group(1), m.group(2)
    if len(item_id) < 5:
        return False
    if any(not p for p in slug.split("-")):
        return False
    parts = [p for p in slug.split("-") if p]
    if len(parts) < 2 or len(slug) < 8:
        return False
    return True


def url_matches_style_hint(style_id: str, url: str) -> bool:
    """型番が分かっているとき、URL に型番らしき文字列が無い候補を除外。

    ページ内 JSON-LD のみに型番がある商品もあるため、妥当な型番のみ検査する。
    """
    sid = (style_id or "").strip()
    if not sid or not is_plausible_model_code(sid):
        return True
    compact = re.sub(r"[^a-z0-9]", "", sid.lower())
    if len(compact) < 5:
        return True
    path_compact = re.sub(r"[^a-z0-9]", "", urlparse(url).path.lower())
    return compact in path_compact


def style_id_for_matching(sheet_style_id: str, buyma_style_id: str = "") -> str:
    """型番照合・選定用。BUYMA 商品 ID（数字のみ）や空は使わない。"""
    sid = (sheet_style_id or "").strip()
    if sid and is_plausible_model_code(sid):
        return sid
    legacy = (buyma_style_id or "").strip()
    if legacy and is_plausible_model_code(legacy):
        return legacy
    return ""


def filter_scrape_candidate_urls(
    brand: str,
    urls: list[str],
    *,
    style_id: str = "",
) -> tuple[list[str], list[str]]:
    """スクレイプ前に仕入先 URL を検証し、(有効, 除外) を返す。"""
    ok: list[str] = []
    rejected: list[str] = []
    for u in urls:
        if url_is_valid_supply_candidate(brand, u, style_id=style_id):
            ok.append(u)
        else:
            rejected.append(u)
    return ok, rejected


def rank_supply_urls_for_discovery(
    urls: list[str],
    *,
    style_id: str = "",
    product_name: str = "",
) -> list[str]:
    """探索用 URL の優先順位付け（型番スラッグ一致 > カテゴリ語 > その他）。"""
    sid = (style_id or "").strip()
    category_hints, mismatch_hints = infer_supply_category_hints(product_name)

    def score(url: str) -> int:
        s = 0
        path = urlparse(url).path.lower()
        if sid and url_matches_style_hint(sid, url):
            s += 200
        for i, hint in enumerate(category_hints):
            if hint in path:
                s += 50 - i
        for bad in mismatch_hints:
            if bad in path:
                s -= 150
        if "pre-owned" in path or "vintage" in path:
            s -= 100
        return s

    return sorted(urls, key=score, reverse=True)


_GENERIC_BAG_HINTS = frozenset({"bag", "shoulder", "tote"})


def _requires_specific_path_match(product_name: str, positive: list[str]) -> bool:
    """バケット/ウィッカー等 — URL にカテゴリ語が無い候補を拒否する。"""
    name_l = (product_name or "").lower()
    if is_footwear_product_name(product_name):
        return False
    if any(
        k in name_l
        for k in (
            "バケット", "bucket", "ウィッカー", "wicker", "ラタン", "rattan",
            "ハンドバッグ", "handbag", "hand bag", "hand-bag",
            "ベルトバッグ", "ボディバッグ", "belt bag", "body bag", "bum bag",
            "フラグメント", "fragment", "カードケース", "card-case", "card-holder",
            "名刺",
        )
    ):
        return True
    return len([h for h in positive if h not in _GENERIC_BAG_HINTS]) >= 2


def url_has_line_or_style_slug_match(
    product_name: str, style_id: str, url: str,
) -> bool:
    """Step3 用 — URL スラッグが型番・ライン名・（非フットウェアは）カテゴリ語と一致。"""
    sid = (style_id or "").strip()
    if sid and url_matches_style_hint(sid, url):
        return True
    path = urlparse(url).path.lower()
    path_norm = path.replace("-", " ")

    def path_has(token: str) -> bool:
        t = token.lower().replace("-", " ")
        return t in path or t in path_norm

    for token in line_name_search_tokens(product_name):
        if token in path:
            return True
    if is_footwear_product_name(product_name):
        return False
    positive, _ = infer_supply_category_hints(product_name)
    return any(path_has(hint) for hint in positive)


def url_requires_line_or_style_slug(product_name: str, style_id: str) -> bool:
    """Step3 で汎用カテゴリ URL（別 SKU の sandal 等）を拾わない。"""
    sid = (style_id or "").strip()
    if not sid or not is_plausible_model_code(sid):
        return False
    if is_footwear_product_name(product_name):
        return True
    return _requires_specific_path_match(
        product_name, infer_supply_category_hints(product_name)[0]
    )


def url_has_category_path_mismatch(product_name: str, url: str) -> bool:
    """URL パスが商品カテゴリと明らかに矛盾するか（eyewear vs bag 等）。"""
    if not (product_name or "").strip() or not url:
        return False
    positive, negative = infer_supply_category_hints(product_name)
    path = urlparse(url).path.lower()
    path_norm = path.replace("-", " ")

    def path_has(token: str) -> bool:
        t = token.lower().replace("-", " ")
        return t in path or t in path_norm

    if _requires_specific_path_match(product_name, positive):
        if not any(path_has(hint) for hint in positive):
            return True

    if not negative:
        return False

    mismatches = [bad for bad in negative if path_has(bad)]
    if not mismatches:
        return False
    if any(path_has(hint) for hint in positive):
        return False
    return True


def url_is_valid_supply_candidate(
    brand: str, url: str, *, style_id: str = "", require_style_in_url: bool = False,
    product_name: str = "",
) -> bool:
    """仕入先 URL が探索・スクレイプ候補として妥当か。

    require_style_in_url=False（既定）では型番が URL に無くても通す。
    別 SKU の除外はスクレイプ後の JSON-LD 型番照合（BestSourceFinder）に任せる。
    """
    if not url_matches_brand(brand, url):
        return False
    if not url_is_retail_supply_candidate(url):
        return False
    if product_name and url_has_category_path_mismatch(product_name, url):
        return False
    if (
        product_name
        and style_id
        and url_requires_line_or_style_slug(product_name, style_id)
        and not url_has_line_or_style_slug_match(product_name, style_id, url)
    ):
        return False
    if "farfetch.com" in (url or "").lower():
        if not is_valid_farfetch_product_url(url):
            return False
        if require_style_in_url and style_id and not url_matches_style_hint(
            style_id, url
        ):
            return False
        return True
    if require_style_in_url and style_id and not url_matches_style_hint(style_id, url):
        return False
    return True
