"""ForkSight scanner — core logic for fork network analysis."""
import re
import os
import requests
from dataclasses import dataclass
from typing import List, Optional, Tuple

from analyzer import analyze_diff

REPO_PATTERN = re.compile(r"^[a-zA-Z0-9\-_.]+/[a-zA-Z0-9\-_.]+$")



def validate_repo(repo_str: str) -> Tuple[str, str]:
    """Parse and validate a repository identifier. Rejects anything suspicious."""
    if not isinstance(repo_str, str) or len(repo_str) > 200:
        raise ValueError("Invalid repository identifier")
    repo_str = repo_str.strip().rstrip("/")
    if repo_str.endswith(".git"):
        repo_str = repo_str[:-4]
    if repo_str.startswith("https://github.com/"):
        repo_str = repo_str[len("https://github.com/"):]
    if not REPO_PATTERN.match(repo_str):
        raise ValueError(f"Invalid format: '{repo_str}'. Use 'owner/repo'")
    owner, repo = repo_str.split("/", 1)
@dataclass
class ForkInsight:
    """Analysis result for a single fork."""
    full_name: str
    owner: str
    ahead_by: int
    behind_by: int
    unique_commits: int
    url: str
    updated_at: str
    significance_score: Optional[int] = None
    diff_analysis: Optional[dict] = None

    unique_commits: int
    url: str
    updated_at: str


class GitHubScanner:
    """Scans fork networks via the GitHub REST API."""
    API_BASE = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/vnd.github.v3+json"
        self.session.headers["User-Agent"] = "ForkSight/1.0"
        resolved = token or os.environ.get("GITHUB_TOKEN", "")
        if resolved:
            self.session.headers["Authorization"] = f"token {resolved}"

    def _get(self, path: str, params: Optional[dict] = None):
        """Perform a GET request with timeout and rate-limit detection."""
        resp = self.session.get(
            f"{self.API_BASE}{path}", params=params or {}, timeout=15
        )
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise RuntimeError("GitHub API rate limit exceeded. Set GITHUB_TOKEN.")
        resp.raise_for_status()
        return resp.json()

    def list_forks(self, owner: str, repo: str, max_forks: int = 30) -> list:
        """Fetch forks sorted by stargazers, paginated."""
        forks: list = []
        page = 1
        while len(forks) < max_forks:
            per_page = min(30, max_forks - len(forks))
            batch = self._get(
                f"/repos/{owner}/{repo}/forks",
                {"per_page": per_page, "page": page, "sort": "stargazers"},
            )
            if not batch:
                break
            forks.extend(batch)
            if len(batch) < 30:
                break
            page += 1
        return forks[:max_forks]

    def compare(self, owner: str, repo: str, base: str, head: str) -> dict:
        """Compare two refs via the GitHub compare API."""
        return self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}")

    def scan(
        self, repo_str: str, max_forks: int = 30, min_ahead: int = 1
    ) -> List[ForkInsight]:
        """Scan fork network and return insights sorted by commits ahead."""
        owner, repo = validate_repo(repo_str)
        forks = self.list_forks(owner, repo, max_forks)
        insights: List[ForkInsight] = []
        for fork in forks:
            fork_owner = fork["owner"]["login"]
            branch = fork.get("default_branch", "main")
            try:
                cmp = self.compare(
                    owner, repo, f"{owner}:{branch}", f"{fork_owner}:{branch}"
                )
                ahead = cmp.get("ahead_by", 0)
                behind = cmp.get("behind_by", 0)
                if ahead >= min_ahead:
                    insights.append(ForkInsight(
                        full_name=fork["full_name"], owner=fork_owner,
                        ahead_by=ahead, behind_by=behind, unique_commits=ahead,
                        url=fork["html_url"], updated_at=fork.get("updated_at", ""),
                    ))
            except Exception:
                continue
        insights.sort(key=lambda x: x.ahead_by, reverse=True)
        return insights
