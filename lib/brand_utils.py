"""ブランド名の正規化・抽出ユーティリティ。

supply_search_utils.py から分離。
"""

from __future__ import annotations

import re
from typing import Optional

from lib.style_id_utils import is_plausible_model_code

_BRACKET_TAG = re.compile(r"【[^】]*】|\[[^\]]*\]")
_DECORATIVE_CHARS = re.compile(r"[♪★☆♥♡♫♬♩♭♯]+")

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

_MARKETPLACE_BRAND_NOISE = frozenset({"buyma", "バイマ"})


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


def is_marketplace_brand_noise(brand: str) -> bool:
    """BUYMA ページ JSON-LD / シート列のプラットフォーム名。"""
    s = (brand or "").strip().casefold()
    return s in _MARKETPLACE_BRAND_NOISE


def _extract_latin_brand_token(s: str) -> str:
    """整形済み文字列からブランドらしい英字トークンを抽出する（無ければ空）。"""
    upper_tokens: list[str] = re.findall(r"\b([A-Z]{2,20})\b", s)
    if upper_tokens:
        return upper_tokens[-1]

    head = re.match(r"^([A-Za-z]{2,20})", s.replace(" ", ""))
    if head:
        word = head.group(1)
        if word.isupper() or len(word) <= 6:
            return word.upper() if word.isupper() else word

    for token in s.split():
        for part in re.split(r"[◆\\-]", token):
            t = part.strip(" -|/：:・◆")
            if not t:
                continue
            if re.match(r"^[A-Za-z]{2,20}$", t):
                return t.upper() if t.isupper() else t
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

    token = _extract_latin_brand_token(s)
    if token:
        return token

    result = s.split()[0] if s.split() else s
    if is_plausible_model_code(result):
        if tag_brand:
            return tag_brand
        ja = _canonical_brand_from_japanese(brand or s)
        if ja:
            return ja
    return result


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


def brand_slug(brand: str) -> str:
    """ブランド名をURL比較用のスラッグに変換。"""
    b = normalize_brand_name(brand).lower()
    return re.sub(r"[^a-z0-9]+", "-", b).strip("-")


def url_matches_brand(brand: str, url: str) -> bool:
    """仕入先 URL にブランド名が含まれるか（誤ヒット除外）。"""
    slug = brand_slug(brand)
    if not slug or len(slug) < 3:
        return True
    return slug in url.lower()
