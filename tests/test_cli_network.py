import io
import json
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from recall_watch import notify, sources
from recall_watch.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run(tmp_path, *extra):
    return main(["check", "--products", str(EXAMPLES / "products.csv"),
                 "--recorded", str(EXAMPLES / "enforcement.json"), "--recorded", str(EXAMPLES / "press.xml"),
                 "--state", str(tmp_path / "seen.json"), "--out", str(tmp_path / "out"), *extra])


def test_cli_reports_then_remembers(tmp_path, capsys):
    assert run(tmp_path, "--fail-on-match") == 1
    out = capsys.readouterr().out
    assert "Matches: 5 (5 new)" in out
    assert (tmp_path / "out" / "report.html").exists()
    matches = json.loads((tmp_path / "out" / "matches.json").read_text())
    assert matches[0]["level"] == "barcode"
    assert "Recall check: 5 new matches" in (tmp_path / "out" / "summary.md").read_text()

    assert run(tmp_path, "--fail-on-match") == 0  # second run: already reported
    assert "Matches: 5 (0 new)" in capsys.readouterr().out


def test_dry_run_does_not_write_state(tmp_path):
    run(tmp_path, "--dry-run")
    assert not (tmp_path / "seen.json").exists()


def test_step_summary(tmp_path, monkeypatch):
    summary = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run(tmp_path, "--dry-run")
    assert "Barcode match" in summary.read_text()


def test_report_escapes_html(tmp_path):
    data = json.loads((EXAMPLES / "enforcement.json").read_text())
    data["results"][0]["product_description"] += " <script>alert(1)</script>"
    rec = tmp_path / "e.json"
    rec.write_text(json.dumps(data))
    main(["check", "--products", str(EXAMPLES / "products.csv"), "--recorded", str(rec),
          "--state", str(tmp_path / "s.json"), "--out", str(tmp_path / "o"), "--dry-run"])
    page = (tmp_path / "o" / "report.html").read_text()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_cli_bad_products(tmp_path, capsys):
    assert main(["check", "--products", str(tmp_path / "none.csv"), "--recorded", str(EXAMPLES / "press.xml")]) == 2
    assert "not found" in capsys.readouterr().err


# --- network code, with urllib replaced -----------------------------------------------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_enforcement_builds_query_and_pages(monkeypatch):
    payload = json.loads((EXAMPLES / "enforcement.json").read_text())
    calls = []

    def fake(request, timeout=None):
        calls.append(request.full_url)
        page = dict(payload)
        page["meta"] = {"results": {"total": 7}}
        page["results"] = payload["results"] if len(calls) == 1 else payload["results"][:2]
        return FakeResponse(json.dumps(page).encode())

    monkeypatch.setattr(sources.urllib.request, "urlopen", fake)
    recalls = sources.fetch_enforcement(days=30, today=date(2026, 10, 23), page_size=5)
    assert len(recalls) == 7 and len(calls) == 2
    assert "report_date%3A%5B20260923+TO+20261023%5D" in calls[0]
    assert "skip=5" in calls[1]


def test_fetch_enforcement_404_means_empty(monkeypatch):
    def fake(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(sources.urllib.request, "urlopen", fake)
    assert sources.fetch_enforcement(days=7) == []


def test_fetch_retries_then_fails(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    calls = []

    def fake(request, timeout=None):
        calls.append(1)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(sources.urllib.request, "urlopen", fake)
    with pytest.raises(sources.SourceError):
        sources.fetch_press()
    assert len(calls) == 3


def test_source_failure_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    monkeypatch.setattr(sources.urllib.request, "urlopen",
                        lambda request, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    code = main(["check", "--products", str(EXAMPLES / "products.csv"), "--state", str(tmp_path / "s.json"),
                 "--out", str(tmp_path / "o")])
    assert code == 2


def test_github_issues(monkeypatch, tmp_path, capsys):
    posted = []

    def fake(request, timeout=None):
        posted.append((request.full_url, json.loads(request.data), dict(request.header_items())))
        return FakeResponse(json.dumps({"html_url": f"https://github.com/me/r/issues/{len(posted)}"}).encode())

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert run(tmp_path, "--github-issues") == 0
    assert len(posted) == 5
    url, body, headers = posted[0]
    assert url == "https://api.github.com/repos/me/r/issues"
    assert body["title"].startswith("[Recall] Barcode match: Sample Creamery")
    assert body["labels"] == ["recall-watch", "barcode"]
    assert "DM-002" in body["body"]
    assert headers["Authorization"] == "Bearer t0ken"
    assert (tmp_path / "seen.json").exists()


def test_failed_notification_is_retried_next_run(monkeypatch, tmp_path):
    def fake(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"no"))

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert run(tmp_path, "--github-issues") == 2
    assert not (tmp_path / "seen.json").exists()  # nothing marked as reported


def test_webhook(monkeypatch, tmp_path):
    posted = []
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda request, timeout=None: posted.append(json.loads(request.data)) or FakeResponse(b"ok"))
    assert run(tmp_path, "--webhook-url", "https://hooks.example.com/x") == 0
    assert len(posted) == 5 and "Barcode match" in posted[0]["text"]


def test_ignore_brands_file(tmp_path, capsys):
    f = tmp_path / "ignore.txt"
    f.write_text("# common words\nClassic\n", encoding="utf-8")
    run(tmp_path, "--dry-run", "--ignore-brands-file", str(f))
    assert "Matches: 4 (4 new)" in capsys.readouterr().out


def test_issue_without_labels_when_labels_rejected(monkeypatch, tmp_path):
    bodies = []

    def fake(request, timeout=None):
        body = json.loads(request.data)
        bodies.append(body)
        if "labels" in body:
            raise urllib.error.HTTPError(request.full_url, 422, "Unprocessable", {}, io.BytesIO(b"labels"))
        return FakeResponse(b'{"html_url": "https://github.com/me/r/issues/1"}')

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert run(tmp_path, "--github-issues") == 0
    assert len(bodies) == 10 and "labels" not in bodies[1]
