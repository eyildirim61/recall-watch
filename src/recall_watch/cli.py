"""recall-watch check: compare recent recalls with your product list and report new matches."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .match import find_matches
from .notify import NotifyError, open_github_issues, post_webhook
from .products import ProductError, load_products
from .report import summary_markdown, write_html, write_json
from .sources import SOURCES, SourceError, fetch_enforcement, fetch_press, load_recorded, now_iso
from .state import load_state, mark, save_state


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recall-watch", description="Check FDA food recalls against your product list.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="fetch recent recalls and report matches")
    c.add_argument("--products", required=True, help="CSV or XLSX with name / brand / barcode / box barcode columns")
    c.add_argument("--source", action="append", choices=sorted(SOURCES), help="default: both sources")
    c.add_argument("--days", type=int, default=30, help="enforcement reports from the last N days (default: %(default)s)")
    c.add_argument("--recorded", action="append", default=[], metavar="FILE",
                   help="use a saved openFDA .json or RSS .xml instead of downloading (repeatable)")
    c.add_argument("--state", default="state/seen.json", help="file that remembers reported recalls (default: %(default)s)")
    c.add_argument("--out", default="reports", help="report directory (default: %(default)s)")
    c.add_argument("--ignore-brand", action="append", default=[], metavar="BRAND",
                   help="brand names too common to match on (repeatable)")
    c.add_argument("--ignore-brands-file", metavar="FILE",
                   help="text file with one brand per line to skip (lines starting with # are comments)")
    c.add_argument("--no-brand-from-name", action="store_true",
                   help="do not take the brand from the part of the name before the first comma")
    c.add_argument("--github-issues", action="store_true", help="open a GitHub issue for each new match")
    c.add_argument("--webhook-url", default=os.environ.get("RECALL_WEBHOOK_URL", ""),
                   help="Slack / Teams / Discord webhook (or set RECALL_WEBHOOK_URL)")
    c.add_argument("--dry-run", action="store_true", help="report, but do not notify or update the state file")
    c.add_argument("--fail-on-match", action="store_true", help="exit with code 1 when there are new matches")
    c.set_defaults(func=cmd_check)
    return p


def _collect(args) -> (List, Dict[str, int], List[str]):
    recalls, errors = [], []
    if args.recorded:
        for path in args.recorded:
            recalls += load_recorded(path)
    else:
        for name in args.source or ["fda-enforcement", "fda-press"]:
            try:
                recalls += fetch_enforcement(days=args.days) if name == "fda-enforcement" else fetch_press()
            except SourceError as exc:
                errors.append(f"{name}: {exc}")
    checked: Dict[str, int] = {}
    for r in recalls:
        checked[r.source] = checked.get(r.source, 0) + 1
    return recalls, checked, errors


def cmd_check(args) -> int:
    try:
        products = load_products(args.products, brand_from_names=not args.no_brand_from_name)
    except ProductError as exc:
        print(f"recall-watch: {exc}", file=sys.stderr)
        return 2

    recalls, checked, errors = _collect(args)
    for e in errors:
        print(f"recall-watch: source failed: {e}", file=sys.stderr)
    if errors and not recalls:
        return 2

    ignore = list(args.ignore_brand)
    if args.ignore_brands_file and Path(args.ignore_brands_file).exists():
        ignore += [line.strip() for line in Path(args.ignore_brands_file).read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.lstrip().startswith("#")]
    matches = find_matches(recalls, products, ignore_brands=ignore)
    seen = load_state(args.state)
    new = [m for m in matches if m.recall.key not in seen]

    out = Path(args.out)
    generated = now_iso()
    write_html(matches, checked, out / "report.html", generated, new_keys=[m.recall.key for m in new])
    write_json(matches, out / "matches.json")
    summary = summary_markdown(new, checked, len(matches) - len(new))
    (out / "summary.md").write_text(summary + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")

    with_barcodes = sum(1 for p in products if p.gtins)
    with_brand = sum(1 for p in products if p.brand)
    print(f"Products: {len(products)} ({with_barcodes} with a valid barcode, {with_brand} with a brand)")
    print(f"Recalls checked: " + (", ".join(f"{n} {s}" for s, n in checked.items()) or "none"))
    print(f"Matches: {len(matches)} ({len(new)} new)")
    for m in new:
        print(f"  NEW {m.level:<7} {m.recall.date}  {m.recall.firm or m.recall.title[:60]}  -> "
              f"{', '.join(p.label for p in m.products[:3])}{' …' if len(m.products) > 3 else ''}")
    print(f"Report: {out / 'report.html'}")

    notify_failed = False
    if new and not args.dry_run:
        if args.github_issues:
            try:
                for url in open_github_issues(new):
                    print(f"Issue:  {url}")
            except NotifyError as exc:
                print(f"recall-watch: could not open issues: {exc}", file=sys.stderr)
                notify_failed = True
        if args.webhook_url:
            try:
                post_webhook(new, args.webhook_url)
                print("Webhook: sent")
            except NotifyError as exc:
                print(f"recall-watch: webhook failed: {exc}", file=sys.stderr)
                notify_failed = True

    # Only remember recalls once they were delivered, so a failed notification is retried next run.
    if not args.dry_run and not notify_failed:
        mark(seen, (m.recall.key for m in new))
        save_state(args.state, seen)

    if notify_failed or errors:
        return 2
    return 1 if args.fail_on_match and new else 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
