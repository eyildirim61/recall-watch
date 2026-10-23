"""Remember which recalls were already reported, so each one alerts only once.

The state file holds recall IDs and dates only, never product data, so it is safe to commit.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable

KEEP_DAYS = 400  # forget entries older than this so the file stays small


def load_state(path) -> Dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    seen = data.get("seen", {}) if isinstance(data, dict) else {}
    return {str(k): str(v) for k, v in seen.items()}


def save_state(path, seen: Dict[str, str], today: date = None) -> None:
    today = today or date.today()
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    kept = {k: v for k, v in sorted(seen.items()) if v >= cutoff}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": kept}, indent=2) + "\n", encoding="utf-8")


def mark(seen: Dict[str, str], keys: Iterable[str], today: date = None) -> None:
    stamp = (today or date.today()).isoformat()
    for key in keys:
        seen.setdefault(key, stamp)
