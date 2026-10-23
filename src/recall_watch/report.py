"""Write results: Markdown (GitHub job summary, issues), HTML (browsable report), JSON."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, List

from . import __version__
from .match import Match

LEVEL_TEXT = {"barcode": "Barcode match", "brand": "Brand mentioned, please check"}


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def match_markdown(m: Match) -> str:
    r = m.recall
    lines = [
        f"**{LEVEL_TEXT[m.level]}** · {r.source} · {r.date or 'date unknown'}",
        "",
        f"**{_md_escape(r.title)}**",
        "",
    ]
    if r.firm:
        lines.append(f"- Firm: {_md_escape(r.firm)}")
    if r.reason:
        lines.append(f"- Reason: {_md_escape(r.reason)}")
    if r.classification:
        lines.append(f"- Classification: {r.classification}" + (f" · status {r.status}" if r.status else ""))
    if r.distribution:
        lines.append(f"- Distribution: {_md_escape(r.distribution)}")
    if r.extra.get("initiated"):
        lines.append(f"- Recall started: {r.extra['initiated']}")
    lines.append(f"- Source: {r.url}")
    lines += ["", "**Your products**", ""]
    lines += [f"- {_md_escape(p.label)}" for p in m.products[:25]]
    if len(m.products) > 25:
        lines.append(f"- … and {len(m.products) - 25} more")
    lines += ["", "**Why it matched**", ""] + [f"- {_md_escape(e)}" for e in m.evidence]
    return "\n".join(lines)


def summary_markdown(new: List[Match], checked: Dict[str, int], already_seen: int) -> str:
    counts = ", ".join(f"{n} from {s}" for s, n in checked.items())
    head = [f"## Recall check: {len(new)} new match{'es' if len(new) != 1 else ''}", "",
            f"Checked {sum(checked.values())} recalls ({counts}). {already_seen} earlier match(es) were already reported.", ""]
    if not new:
        return "\n".join(head + ["No new recalls matched your products."])
    return "\n".join(head) + "\n" + "\n\n---\n\n".join(match_markdown(m) for m in new)


def write_json(matches: List[Match], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [{
        "level": m.level, "recall_key": m.recall.key, "source": m.recall.source, "id": m.recall.id,
        "date": m.recall.date, "title": m.recall.title, "firm": m.recall.firm, "reason": m.recall.reason,
        "classification": m.recall.classification, "url": m.recall.url,
        "products": [{"row": p.row, "sku": p.sku, "name": p.name, "brand": p.brand} for p in m.products],
        "evidence": m.evidence,
    } for m in matches]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _e(v) -> str:
    return html.escape(str(v or ""), quote=True)


def write_html(matches: List[Match], checked: Dict[str, int], path, generated: str, new_keys=()) -> Path:
    new_keys = set(new_keys)
    cards = []
    for m in matches:
        r = m.recall
        facts = "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in (
            ("Firm", r.firm), ("Reason", r.reason), ("Class", r.classification), ("Distribution", r.distribution),
            ("Started", r.extra.get("initiated", "")), ("Reported", r.date)) if v)
        products = "".join(f"<li>{_e(p.label)}</li>" for p in m.products[:50])
        evidence = "".join(f"<li>{_e(e)}</li>" for e in m.evidence)
        badge_new = '<span class="pill new">new</span>' if r.key in new_keys else ""
        cards.append(f"""<article class="card {m.level}">
  <header><span class="pill {m.level}">{_e(LEVEL_TEXT[m.level])}</span>{badge_new}<span class="src">{_e(r.source)} · {_e(r.id)}</span></header>
  <h2><a href="{_e(r.url)}" target="_blank" rel="noopener">{_e(r.title)}</a></h2>
  <dl>{facts}</dl>
  <div class="cols"><div><h3>Your products</h3><ul>{products}</ul></div><div><h3>Why it matched</h3><ul>{evidence}</ul></div></div>
</article>""")
    checked_text = ", ".join(f"{n} {s}" for s, n in checked.items())
    body = "".join(cards) or '<p class="empty">No recalls matched your products in this window.</p>'
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recall Watch Report</title>
<style>
:root {{ --bg:#f4f6f5; --panel:#fff; --ink:#18211d; --muted:#5f6b65; --line:#dfe5e2; --red:#b42318; --red-bg:#fdecea;
  --amber:#8a5a00; --amber-bg:#fff3d6; --green:#1f6f4a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111614; --panel:#19201d; --ink:#e7ece9; --muted:#9aa7a0; --line:#2c3632;
  --red:#ff8a80; --red-bg:#3a1714; --amber:#f2c14e; --amber-bg:#33280f; --green:#7fd6a8; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:32px 16px 64px; display:grid; gap:14px; }}
h1 {{ margin:0; font-size:24px; }} .meta {{ color:var(--muted); font-size:13px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:10px; padding:16px; display:grid; gap:10px; }}
.card.barcode {{ border-left-color:var(--red); }}
.card header {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.pill {{ font-size:12px; font-weight:600; padding:1px 8px; border-radius:999px; }}
.pill.barcode {{ color:var(--red); background:var(--red-bg); }} .pill.brand {{ color:var(--amber); background:var(--amber-bg); }}
.pill.new {{ color:var(--green); border:1px solid currentColor; }}
.src {{ color:var(--muted); font-size:12px; font-family:ui-monospace,Menlo,monospace; }}
h2 {{ margin:0; font-size:16px; }} h2 a {{ color:inherit; }} h3 {{ margin:0 0 4px; font-size:13px; color:var(--muted); }}
dl {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:6px 16px; margin:0; }}
dt {{ font-size:12px; color:var(--muted); }} dd {{ margin:0; }}
.cols {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
ul {{ margin:0; padding-left:18px; }} .empty {{ color:var(--muted); }}
footer {{ color:var(--muted); font-size:12px; }}
</style></head><body><main>
<h1>Recall Watch</h1>
<div class="meta">{_e(generated)} · checked {_e(checked_text)} · {len(matches)} match(es)</div>
{body}
<footer>recall-watch {__version__}. Data provided by the U.S. Food and Drug Administration (open.fda.gov).
Not an official alert service: always confirm on fda.gov before acting.</footer>
</main></body></html>"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
