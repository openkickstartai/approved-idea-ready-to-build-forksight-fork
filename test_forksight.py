"""Tests for ForkSight — scanner, validation, and CLI."""
import pytest
from unittest.mock import patch
from scanner import validate_repo, GitHubScanner, ForkInsight


def _make_fork(login, full_name, branch="main"):
    return {
        "owner": {"login": login},
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "default_branch": branch,
        "updated_at": "2024-06-01T12:00:00Z",
    }


class TestValidateRepo:
    def test_valid_owner_repo(self):
        assert validate_repo("torvalds/linux") == ("torvalds", "linux")

    def test_github_url(self):
        assert validate_repo("https://github.com/torvalds/linux") == ("torvalds", "linux")

    def test_trailing_slash(self):
        assert validate_repo("owner/repo/") == ("owner", "repo")

    def test_dotgit_suffix(self):
        assert validate_repo("owner/repo.git") == ("owner", "repo")

    def test_rejects_bare_name(self):
        with pytest.raises(ValueError):
            validate_repo("just-a-name")

    def test_rejects_shell_injection(self):
        with pytest.raises(ValueError):
            validate_repo("owner/repo; rm -rf /")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_repo("")

    def test_rejects_overlong(self):
        with pytest.raises(ValueError):
            validate_repo("a" * 201)

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            validate_repo(12345)


class TestGitHubScanner:
    def test_returns_ahead_forks(self):
        scanner = GitHubScanner()
        forks = [_make_fork("alice", "alice/repo")]
        cmp_resp = {"ahead_by": 7, "behind_by": 1}
        with patch.object(scanner, "_get", side_effect=[forks, cmp_resp]):
            results = scanner.scan("owner/repo")
        assert len(results) == 1
        assert results[0].ahead_by == 7
        assert results[0].full_name == "alice/repo"

    def test_filters_zero_ahead(self):
        scanner = GitHubScanner()
        forks = [_make_fork("bob", "bob/repo")]
        cmp_resp = {"ahead_by": 0, "behind_by": 5}
        with patch.object(scanner, "_get", side_effect=[forks, cmp_resp]):
            results = scanner.scan("owner/repo", min_ahead=1)
        assert len(results) == 0

    def test_sorts_descending_by_ahead(self):
        scanner = GitHubScanner()
        forks = [_make_fork("a", "a/r"), _make_fork("b", "b/r")]
        with patch.object(scanner, "_get", side_effect=[
            forks,
            {"ahead_by": 2, "behind_by": 0},
            {"ahead_by": 15, "behind_by": 0},
        ]):
            results = scanner.scan("owner/repo")
        assert results[0].full_name == "b/r"
        assert results[0].ahead_by == 15
        assert results[1].full_name == "a/r"

    def test_handles_api_error_gracefully(self):
        scanner = GitHubScanner()
        forks = [_make_fork("err", "err/repo")]
        with patch.object(scanner, "_get", side_effect=[forks, Exception("boom")]):
            results = scanner.scan("owner/repo")
        assert len(results) == 0

    def test_min_ahead_threshold(self):
        scanner = GitHubScanner()
        forks = [_make_fork("x", "x/repo")]
        cmp_resp = {"ahead_by": 3, "behind_by": 0}
        with patch.object(scanner, "_get", side_effect=[forks, cmp_resp]):
            results = scanner.scan("owner/repo", min_ahead=5)
        assert len(results) == 0


class TestForkInsight:
    def test_dataclass_fields(self):
        fi = ForkInsight("a/b", "a", 5, 2, 5, "https://github.com/a/b", "2024-01-01")
        assert fi.ahead_by == 5
        assert fi.owner == "a"
        assert fi.url == "https://github.com/a/b"
