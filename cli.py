#!/usr/bin/env python3
"""ForkSight CLI entry point."""
import argparse
import json
import sys

from scanner import GitHubScanner
from config import get_token, validate_token_format, mask_token


def main():
    parser = argparse.ArgumentParser(
        prog="forksight",
        description="Scan GitHub fork networks for valuable unmerged improvements",
    )
    parser.add_argument("repo", help="Repository as 'owner/repo' or full GitHub URL")
    parser.add_argument("--max-forks", type=int, default=30, help="Max forks to scan (1-200)")
    parser.add_argument("--min-ahead", type=int, default=1, help="Min commits ahead to report")
    parser.add_argument("--json", action="store_true", dest="json_out", help="JSON output")
    parser.add_argument("--token", default=None, help="GitHub token (or set FORKSIGHT_TOKEN env / .env)")
    args = parser.parse_args()

    if not 1 <= args.max_forks <= 200:
        print("Error: --max-forks must be between 1 and 200", file=sys.stderr)
        sys.exit(1)
    if args.min_ahead < 0:
        print("Error: --min-ahead must be non-negative", file=sys.stderr)
        sys.exit(1)

    token = get_token(cli_token=args.token)
    if token and not validate_token_format(token):
        print(f"Warning: token {mask_token(token)} may not be a valid GitHub PAT", file=sys.stderr)

    scanner = GitHubScanner(token=token)


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

    data = [
        {"fork": i.full_name, "ahead_by": i.ahead_by,
         "behind_by": i.behind_by, "url": i.url, "updated_at": i.updated_at}
        for i in insights
    ]

    if args.output_file:
        output_file = args.output_file
        if output_file.endswith(".json"):
            to_json(data, output_file, repo=args.repo)
        elif output_file.endswith(".md"):
            to_markdown(data, output_file, repo=args.repo)
        else:
            print("Error: --output-file must end with .json or .md", file=sys.stderr)
            sys.exit(1)
        print(f"Report written to {output_file}")
        return

    if args.json_out:
        print(json.dumps(data, indent=2))
        return

    if not insights:
        print(f"No forks with unique commits found for {args.repo}")
        return

    print(f"\n\U0001f50d ForkSight Report for {args.repo}")
    print(f"   Found {len(insights)} fork(s) with unmerged improvements\n")
    for idx, i in enumerate(insights, 1):
        print(f"  {idx}. {i.full_name}")
        print(f"     \u2b06 {i.ahead_by} ahead | \u2b07 {i.behind_by} behind | \U0001f4c5 {i.updated_at}")
        print(f"     \U0001f517 {i.url}")


if __name__ == "__main__":
    main()
