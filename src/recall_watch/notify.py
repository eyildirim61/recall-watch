"""Send new matches somewhere a person will see them.

github-issues  opens one issue per new recall in the repository the job runs in. GitHub then emails
               everyone watching the repository, so no mail server or password is needed.
webhook        posts {"text": ...} to a Slack, Microsoft Teams (workflow) or Discord-style webhook URL.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List

from .match import Match
from .report import LEVEL_TEXT, match_markdown


class NotifyError(Exception):
    pass


def _post(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            body = resp.read().decode("utf-8") or "{}"
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {}
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"{url}: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:200]}") from exc
    except urllib.error.URLError as exc:
        raise NotifyError(f"{url}: {exc}") from exc


def issue_title(m: Match) -> str:
    who = m.recall.firm or m.recall.title
    tag = "Barcode match" if m.level == "barcode" else "Check"
    title = f"[Recall] {tag}: {who}"
    return title if len(title) <= 120 else title[:119] + "…"


def open_github_issues(matches: List[Match], repo: str = "", token: str = "", api: str = "") -> List[str]:
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    api = (api or os.environ.get("GITHUB_API_URL", "https://api.github.com")).rstrip("/")
    if not repo or not token:
        raise NotifyError("GitHub issues need GITHUB_REPOSITORY and GITHUB_TOKEN (set automatically in GitHub Actions)")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    urls = []
    for m in matches:
        body = match_markdown(m) + f"\n\n<sub>recall-watch · {m.recall.key}</sub>"
        issue = {"title": issue_title(m), "body": body, "labels": ["recall-watch", m.level]}
        try:
            data = _post(f"{api}/repos/{repo}/issues", issue, headers)
        except NotifyError as exc:
            if "HTTP 422" not in str(exc):  # 422: labels not allowed here; an issue without labels still alerts
                raise
            data = _post(f"{api}/repos/{repo}/issues", {k: v for k, v in issue.items() if k != "labels"}, headers)
        urls.append(data.get("html_url", ""))
    return urls


def post_webhook(matches: List[Match], url: str) -> None:
    for m in matches:
        r = m.recall
        products = ", ".join(p.label for p in m.products[:5]) + (" …" if len(m.products) > 5 else "")
        text = (f"*{LEVEL_TEXT[m.level]}*: {r.title}\n{r.firm} · {r.reason}\n"
                f"Your products: {products}\n{r.url}")
        _post(url, {"text": text}, {})
