# 🔍 ForkSight

Automatically scan GitHub fork networks to discover valuable code improvements that haven't been contributed back upstream.

## Why?

Many forks contain bug fixes, performance patches, or feature additions that upstream maintainers never see. ForkSight surfaces these hidden gems.

## Installation

```bash
git clone https://github.com/openks/forksight.git
cd forksight
pip install -r requirements.txt
```

## Usage

```bash
# Basic scan (unauthenticated — 60 req/hr limit)
python cli.py torvalds/linux

# Authenticated (5000 req/hr)
export GITHUB_TOKEN=ghp_your_token
python cli.py torvalds/linux --max-forks 50

# JSON output for scripting
python cli.py owner/repo --json

# From full GitHub URL
python cli.py https://github.com/owner/repo --min-ahead 3
```

## Example Output

```
🔍 ForkSight Report for pallets/flask
   Found 3 fork(s) with unmerged improvements

  1. alice/flask
     ⬆ 12 ahead | ⬇ 0 behind | 📅 2024-08-15
     🔗 https://github.com/alice/flask
```

## Security Notes

- All repository inputs are validated against a strict allowlist pattern
- GitHub tokens are never logged or echoed
- All HTTP requests use a 15-second timeout
- Rate-limit errors are detected and reported clearly

## Testing

```bash
pytest test_forksight.py -v
```

## License

MIT
