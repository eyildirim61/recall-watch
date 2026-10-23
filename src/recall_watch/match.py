"""Match recalls against a product list.

barcode  a valid UPC/EAN/GTIN in the recall text equals one of the product's barcodes (or the item
         inside its case barcode). Strong: almost certainly the same product.
brand    the product's brand appears as a whole phrase in the recall. Needs a person to check:
         a brand recall may cover other products, or a common word may collide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set

from .gtin import extract
from .products import Product, norm_text
from .sources import Recall

MIN_BRAND_LENGTH = 3


@dataclass
class Match:
    recall: Recall
    products: List[Product] = field(default_factory=list)
    level: str = "brand"  # "barcode" outranks "brand"
    evidence: List[str] = field(default_factory=list)


def _display(gtin14: str) -> str:
    """Show a GTIN the way it is printed: UPC-A 12, EAN 13 or GTIN-14 digits."""
    if gtin14.startswith("00"):
        return gtin14[2:]
    return gtin14[1:] if gtin14.startswith("0") else gtin14


_STOP = {"with", "and", "the", "for", "from", "pack", "jar", "bag", "box", "case", "pcs", "brand", "ile", "adet", "paket"}


def _product_words(p: Product) -> Set[str]:
    """Distinctive words of a product name, without the brand, sizes and filler words."""
    brand = set(norm_text(p.brand).split())
    words = set(norm_text(p.name).split()) - brand - _STOP
    return {w for w in words if len(w) >= 4 and not any(c.isdigit() for c in w)}


def _brand_pattern(brand: str) -> "re.Pattern[str]":
    words = norm_text(brand).split()
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, words)) + r"(?![a-z0-9])")


def find_matches(recalls: Iterable[Recall], products: Sequence[Product],
                 ignore_brands: Iterable[str] = ()) -> List[Match]:
    ignored = {norm_text(b) for b in ignore_brands}
    by_gtin: Dict[str, List[Product]] = {}
    for p in products:
        for g in p.gtins:
            by_gtin.setdefault(g, []).append(p)

    brands: Dict[str, List[Product]] = {}
    for p in products:
        key = norm_text(p.brand)
        if len(key.replace(" ", "")) >= MIN_BRAND_LENGTH and key not in ignored:
            brands.setdefault(key, []).append(p)
    brand_patterns = {key: _brand_pattern(key) for key in brands}

    matches: List[Match] = []
    for recall in recalls:
        hit_products: List[Product] = []
        seen: Set[int] = set()
        evidence: List[str] = []
        level = None

        for code in extract(recall.text):
            for p in by_gtin.get(code, []):
                if p.row not in seen:
                    seen.add(p.row)
                    hit_products.append(p)
                    evidence.append(f"barcode {_display(code)} = {p.label}")
                    level = "barcode"

        searchable = norm_text(f"{recall.text}\n{recall.firm}")
        recall_words = set(searchable.split())
        for key, pattern in brand_patterns.items():
            if pattern.search(searchable):
                new = [p for p in brands[key] if p.row not in seen]
                if not new:
                    continue
                # Products whose own words also appear in the recall come first.
                named = [p for p in new if _product_words(p) & recall_words]
                rest = [p for p in new if p not in named]
                evidence.append(f"brand '{brands[key][0].brand}' mentioned ({len(brands[key])} of your products)")
                if named:
                    evidence.append("product named in the recall: " + ", ".join(p.label for p in named[:5]))
                for p in named + rest:
                    seen.add(p.row)
                    hit_products.append(p)
                level = level or "brand"

        if level:
            matches.append(Match(recall=recall, products=hit_products, level=level, evidence=evidence))

    matches.sort(key=lambda m: m.recall.date, reverse=True)  # newest first...
    matches.sort(key=lambda m: m.level != "barcode")          # ...with barcode matches on top (stable sort)
    return matches
