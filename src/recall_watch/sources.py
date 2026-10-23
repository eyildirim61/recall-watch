"""Recall sources. Each returns a list of Recall records.

fda-enforcement  openFDA food enforcement reports. Weekly, detailed, often lists UPC codes.
                 A recall appears only after FDA classifies it, usually weeks after it starts.
fda-press        FDA recalls press-release RSS feed. Same day, but only a title and a summary,
                 and only the latest ~20 announcements (food, drugs, devices, pet products).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__

ENFORCEMENT_URL = "https://api.fda.gov/food/enforcement.json"
PRESS_RSS_URL = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml"
USER_AGENT = f"recall-watch/{__version__} (+https://github.com/eyildirim61/recall-watch)"


class SourceError(Exception):
    pass


@dataclass
class Recall:
    source: str
    id: str
    title: str
    date: str  # ISO yyyy-mm-dd
    url: str
    firm: str = ""
    reason: str = ""
    classification: str = ""
    status: str = ""
    distribution: str = ""
    text: str = ""  # everything searchable, joined
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"


def _get(url: str, timeout: float = 30, retries: int = 2) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise SourceError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise SourceError(f"{url}: {exc}") from exc
    raise SourceError(f"{url}: no response")  # pragma: no cover


def _ymd(value: str) -> str:
    value = (value or "").strip()
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 and value.isdigit() else value


# --- openFDA food enforcement -----------------------------------------------------------

def parse_enforcement(payload: Dict[str, Any]) -> List[Recall]:
    recalls = []
    for r in payload.get("results", []):
        number = r.get("recall_number", "")
        if not number:
            continue
        description = r.get("product_description", "")
        query = urllib.parse.urlencode({"search": f'recall_number:"{number}"'})
        recalls.append(Recall(
            source="fda-enforcement",
            id=number,
            title=description[:160] + ("…" if len(description) > 160 else ""),
            date=_ymd(r.get("report_date", "")),
            url=f"{ENFORCEMENT_URL}?{query}",
            firm=r.get("recalling_firm", ""),
            reason=r.get("reason_for_recall", ""),
            classification=r.get("classification", ""),
            status=r.get("status", ""),
            distribution=r.get("distribution_pattern", ""),
            text="\n".join(r.get(k, "") or "" for k in ("product_description", "code_info", "more_code_info", "recalling_firm")),
            extra={"initiated": _ymd(r.get("recall_initiation_date", "")), "event_id": r.get("event_id", ""),
                   "quantity": r.get("product_quantity", "")},
        ))
    return recalls


def fetch_enforcement(days: int = 30, today: Optional[date] = None, page_size: int = 1000) -> List[Recall]:
    today = today or date.today()
    start = today - timedelta(days=days)
    search = f"report_date:[{start:%Y%m%d} TO {today:%Y%m%d}]"
    recalls: List[Recall] = []
    skip = 0
    while True:
        params = urllib.parse.urlencode({"search": search, "limit": page_size, "skip": skip, "sort": "report_date:desc"})
        try:
            payload = json.loads(_get(f"{ENFORCEMENT_URL}?{params}"))
        except urllib.error.HTTPError as exc:  # openFDA answers 404 when nothing matches
            if exc.code == 404:
                break
            raise SourceError(f"openFDA: HTTP {exc.code}") from exc
        page = parse_enforcement(payload)
        recalls += page
        total = payload.get("meta", {}).get("results", {}).get("total", 0)
        skip += page_size
        if not page or skip >= total or skip >= 25000:
            break
    return recalls


# --- FDA press releases (RSS) -----------------------------------------------------------

def parse_press_rss(xml_bytes: bytes) -> List[Recall]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise SourceError(f"FDA press RSS: not valid XML ({exc})") from exc
    recalls = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        summary = (item.findtext("description") or "").strip()
        when = ""
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            pass
        if not title:
            continue
        recalls.append(Recall(
            source="fda-press", id=guid.rstrip("/").rsplit("/", 1)[-1] or guid, title=title, date=when,
            url=link, text=f"{title}\n{summary}", reason=summary,
        ))
    return recalls


def fetch_press() -> List[Recall]:
    return parse_press_rss(_get(PRESS_RSS_URL))


# --- recorded data (tests, demos, offline runs) -------------------------------------------

def load_recorded(path) -> List[Recall]:
    """Load a saved openFDA JSON response (.json) or RSS feed (.xml)."""
    path = Path(path)
    data = path.read_bytes()
    if path.suffix.lower() == ".xml":
        return parse_press_rss(data)
    return parse_enforcement(json.loads(data.decode("utf-8")))


SOURCES = {"fda-enforcement": fetch_enforcement, "fda-press": fetch_press}


def fetch(names: List[str], days: int) -> List[Recall]:
    out: List[Recall] = []
    for name in names:
        if name not in SOURCES:
            raise SourceError(f"Unknown source '{name}'. Use: {', '.join(SOURCES)}")
        out += fetch_enforcement(days=days) if name == "fda-enforcement" else fetch_press()
    return out


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
