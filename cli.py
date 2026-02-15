#!/usr/bin/env python3
"""ForkSight CLI entry point."""
import argparse
import json
import sys

from scanner import GitHubScanner


def main():
    parser = argparse.ArgumentParser(
        prog="forksight",
        description="Scan GitHub fork networks for valuable unmerged improvements",
    )
    parser.add_argument("repo", help="Repository as 'owner/repo' or full GitHub URL")
    parser.add_argument("--max-forks", type=int, default=30, help="Max forks to scan (1-200)")
    parser.add_argument("--min-ahead", type=int, default=1, help="Min commits ahead to report")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    parser.add_argument("--token", default=None, help="GitHub token (or set GITHUB_TOKEN env)")
    args = parser.parse_args()

    if not 1 <= args.max_forks <= 200:
        print("Error: --max-forks must be between 1 and 200", file=sys.stderr)
        sys.exit(1)
    if args.min_ahead < 0:
        print("Error: --min-ahead must be non-negative", file=sys.stderr)
        sys.exit(1)

    scanner = GitHubScanner(token=args.token)
    try:
        insights = scanner.scan(
            args.repo, max_forks=args.max_forks, min_ahead=args.min_ahead
        )
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json_out:
        data = [
            {"fork": i.full_name, "ahead_by": i.ahead_by,
             "behind_by": i.behind_by, "url": i.url, "updated_at": i.updated_at}
            for i in insights
        ]
        print(json.dumps(data, indent=2))
        return

    if not insights:
        print(f"No forks with unique commits found for {args.repo}")
        return

    print(f"\nForkSight Report for {args.repo}")
    print(f"  Found {len(insights)} fork(s) with unmerged improvements\n")
    for idx, item in enumerate(insights, 1):
        date = item.updated_at[:10] if item.updated_at else "N/A"
        print(f"  {idx}. {item.full_name}")
        print(f"     +{item.ahead_by} ahead | -{item.behind_by} behind | updated {date}")
        print(f"     {item.url}\n")


if __name__ == "__main__":
    main()
