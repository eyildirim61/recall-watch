"""Find and normalise GTIN/UPC/EAN barcodes in free text."""

from __future__ import annotations

import re
from typing import List, Optional, Set

# 8 to 14 digits, optionally grouped with single spaces or hyphens: "094922980045", "6 66186 27762 1".
_CANDIDATE = re.compile(r"(?<![\d-])\d(?:[ -]?\d){7,13}(?![\d-])")


def check_digit(body: str) -> int:
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def is_valid(code: str) -> bool:
    return code.isdigit() and len(code) in (8, 12, 13, 14) and check_digit(code[:-1]) == int(code[-1])


def normalize(raw: str) -> Optional[str]:
    """Digits only, padded to 14. None if the value is not a valid GTIN."""
    digits = re.sub(r"[\s-]", "", raw or "")
    if digits.endswith(".0") and digits[:-2].isdigit():
        digits = digits[:-2]
    return digits.zfill(14) if is_valid(digits) else None


def item_from_case(gtin14: str) -> Optional[str]:
    """The item GTIN a case GTIN-14 (indicator 1-8) is built from, as GTIN-14."""
    if len(gtin14) != 14 or gtin14[0] not in "12345678":
        return None
    body = gtin14[1:13]
    return (body + str(check_digit(body))).zfill(14)


def extract(text: str) -> List[str]:
    """Valid GTINs mentioned in text, normalised to 14 digits, in order of appearance.

    The check digit filters out lot numbers, dates and phone numbers that happen to have the
    right length. A run of digits that is not valid as a whole is also tried without its first or
    last digit group, because recall texts often write "UPC 0 12345 67890 5 lot 123".
    """
    found: List[str] = []
    seen: Set[str] = set()
    for match in _CANDIDATE.finditer(text or ""):
        raw = match.group(0)
        options = [raw]
        groups = re.split(r"[ -]", raw)
        if len(groups) > 1:
            options += [" ".join(groups[1:]), " ".join(groups[:-1])]
        for option in options:
            code = normalize(option)
            if code and code not in seen:
                seen.add(code)
                found.append(code)
                break
    return found
