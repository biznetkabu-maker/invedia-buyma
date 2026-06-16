"""商品ページの schema.org JSON-LD から sku / mpn / GTIN 系を拾う。"""

from __future__ import annotations

import logging
import re

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# ページ内の全 JSON-LD ブロックを走査し、商品識別子候補を列挙する
_COLLECT_PRODUCT_CODES_JS = """() => {
  const out = [];
  const push = (v) => {
    if (v == null) return;
    const s = String(v).trim();
    if (s && !out.includes(s)) out.push(s);
  };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const data = JSON.parse(s.textContent);
      const roots = Array.isArray(data) ? data : [data];
      for (const root of roots) {
        const nodes = [];
        if (root && typeof root === 'object') {
          nodes.push(root);
          if (Array.isArray(root['@graph'])) {
            for (const g of root['@graph']) nodes.push(g);
          }
        }
        for (const node of nodes) {
          if (!node || typeof node !== 'object') continue;
          push(node.sku);
          push(node.mpn);
          push(node.productID);
          push(node.product_id);
          for (const k of Object.keys(node)) {
            if (k.toLowerCase().startsWith('gtin')) push(node[k]);
          }
        }
      }
    } catch {}
  }
  return out;
}"""


_CODE_LIKE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-./]{3,39}$")


def _pick_primary_style_id(candidates: list[str]) -> str | None:
    """英数字中心のコードを優先。無ければ先頭候補（GTIN 等）。"""
    if not candidates:
        return None
    for c in candidates:
        s = c.strip()
        if _CODE_LIKE.match(s):
            return s
    c0 = candidates[0].strip()
    return c0 if len(c0) >= 4 else None


async def extract_primary_style_id_from_json_ld(page: Page) -> str | None:
    """Playwright Page から JSON-LD の識別子を抽出し、代表1件を返す。"""
    try:
        raw = await page.evaluate(_COLLECT_PRODUCT_CODES_JS)
        if not raw:
            return None
        codes = [str(x).strip() for x in raw if x]
        primary = _pick_primary_style_id(codes)
        return primary
    except Exception as e:
        logger.debug("json_ld style_id extract failed: %s", e)
        return None
