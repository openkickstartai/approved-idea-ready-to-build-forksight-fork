"""Tests for ForkSight \u2014 scanner, validation, and CLI."""
import pytest
import requests
from unittest.mock import patch, MagicMock
from scanner import (
    validate_repo,
    GitHubScanner,
    ForkInsight,
    RateLimitExhaustedError,
    _validate_fork_json,
    _validate_comparison_json,
    REQUEST_TIMEOUT,
)


def _make_fork(login, full_name, branch="main"):
    return {
        "owner": {"login": login},
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "default_branch": branch,
        "updated_at": "2024-06-01T12:00:00Z",
    }


def _mock_response(status_code=200, json_data=None, headers=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


# ============================================================
# Validation tests
# ============================================================
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

    # --- NEW: path traversal tests ---
    def test_rejects_path_traversal_multi_level(self):
        """owner='../../etc' must raise ValueError with 'invalid' in message."""
        with pytest.raises(ValueError, match="invalid"):
            validate_repo("../../etc")

    def test_rejects_dotdot_owner(self):
        """'../repo' should be rejected — '..' is a path traversal component."""
        with pytest.raises(ValueError, match="invalid"):
            validate_repo("../repo")

    def test_rejects_dotdot_repo(self):
        """'owner/..' should be rejected."""
        with pytest.raises(ValueError, match="invalid"):
            validate_repo("owner/..")


# ============================================================
# Schema validation tests
# ============================================================
class TestSchemaValidation:
    def test_valid_fork_json(self):
        assert _validate_fork_json(_make_fork("alice", "alice/repo")) is True

    def test_fork_missing_owner(self):
        bad = {"full_name": "x/y", "html_url": "u", "default_branch": "m", "updated_at": "d"}
        assert _validate_fork_json(bad) is False

    def test_fork_owner_missing_login(self):
        bad = _make_fork("alice", "alice/repo")
        del bad["owner"]["login"]
        assert _validate_fork_json(bad) is False

    def test_fork_not_dict(self):
        assert _validate_fork_json("string") is False
        assert _validate_fork_json(None) is False

    def test_valid_comparison_json(self):
        assert _validate_comparison_json({"ahead_by": 5, "behind_by": 1}) is True

    def test_comparison_missing_field(self):
        assert _validate_comparison_json({"ahead_by": 5}) is False

    def test_comparison_wrong_type(self):
        assert _validate_comparison_json({"ahead_by": "5", "behind_by": 1}) is False


# ============================================================
# GitHubScanner tests
# ============================================================
class TestGitHubScanner:
    def test_returns_ahead_forks(self):
        scanner = GitHubScanner()
        forks = [_make_fork("alice", "alice/repo")]
        cmp_resp = {"ahead_by": 7, "behind_by": 1}
        with patch.object(scanner, "_get", side_effect=[forks, cmp_resp]):
            results = scanner.scan("owner/repo", min_ahead=1)
        assert len(results) == 1
        assert results[0].ahead_by == 7
        assert results[0].full_name == "alice/repo"

    def test_filters_below_min_ahead(self):
        scanner = GitHubScanner()
        forks = [_make_fork("alice", "alice/repo")]
        cmp_resp = {"ahead_by": 0, "behind_by": 5}
        with patch.object(scanner, "_get", side_effect=[forks, cmp_resp]):
            results = scanner.scan("owner/repo", min_ahead=1)
        assert len(results) == 0

    def test_skips_invalid_fork_schema(self):
        """Forks with missing required fields should be silently skipped."""
        scanner = GitHubScanner()
        bad_fork = {"full_name": "bad/fork"}  # missing owner, html_url, etc.
        good_fork = _make_fork("alice", "alice/repo")
        cmp_resp = {"ahead_by": 3, "behind_by": 0}
        with patch.object(scanner, "_get", side_effect=[[bad_fork, good_fork], cmp_resp]):
            results = scanner.scan("owner/repo", min_ahead=1)
        assert len(results) == 1
        assert results[0].full_name == "alice/repo"

    # --- NEW: timeout tests ---
    def test_get_includes_timeout(self):
        """All requests.get calls must include a timeout parameter."""
        scanner = GitHubScanner()
        resp = _mock_response(200, {"ok": True}, {"X-RateLimit-Remaining": "100"})
        with patch.object(scanner.session, "get", return_value=resp) as mock_get:
            scanner._get("/repos/owner/repo")
            mock_get.assert_called_once()
            _, kwargs = mock_get.call_args
            assert "timeout" in kwargs
            assert kwargs["timeout"] == REQUEST_TIMEOUT

    def test_timeout_exception_handled(self):
        """requests.exceptions.Timeout must be caught and re-raised as RuntimeError."""
        scanner = GitHubScanner()
        with patch.object(
            scanner.session, "get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                scanner._get("/repos/owner/repo")

    def test_connection_error_handled(self):
        """requests.exceptions.ConnectionError must be caught and re-raised."""
        scanner = GitHubScanner()
        with patch.object(
            scanner.session, "get",
            side_effect=requests.exceptions.ConnectionError("DNS failure"),
        ):
            with pytest.raises(RuntimeError, match="Connection error"):
                scanner._get("/repos/owner/repo")

    # --- NEW: HTTP status code tests ---
    def test_401_raises_runtime_error_about_token(self):
        """HTTP 401 should raise RuntimeError mentioning invalid token."""
        scanner = GitHubScanner()
        resp = _mock_response(401, headers={})
        with patch.object(scanner.session, "get", return_value=resp):
            with pytest.raises(RuntimeError, match="token"):
                scanner._get("/repos/owner/repo")

    def test_403_rate_limit_raises_rate_limit_error(self):
        """HTTP 403 + X-RateLimit-Remaining: 0 must raise RateLimitExhaustedError."""
        scanner = GitHubScanner()
        resp = _mock_response(403, headers={"X-RateLimit-Remaining": "0"})
        with patch.object(scanner.session, "get", return_value=resp):
            with pytest.raises(RateLimitExhaustedError):
                scanner._get("/repos/owner/repo")

    def test_403_permission_denied(self):
        """HTTP 403 without rate limit exhaustion raises RuntimeError about permissions."""
        scanner = GitHubScanner()
        resp = _mock_response(403, headers={"X-RateLimit-Remaining": "50"})
        with patch.object(scanner.session, "get", return_value=resp):
            with pytest.raises(RuntimeError, match="forbidden"):
                scanner._get("/repos/owner/repo")

    def test_404_raises_not_found(self):
        """HTTP 404 should raise RuntimeError mentioning repository not found."""
        scanner = GitHubScanner()
        resp = _mock_response(404, headers={})
        with patch.object(scanner.session, "get", return_value=resp):
            with pytest.raises(RuntimeError, match="not found"):
                scanner._get("/repos/owner/repo")

    # --- NEW: rate limit header tests ---
    def test_rate_limit_zero_on_200_raises(self):
        """Even on HTTP 200, X-RateLimit-Remaining: 0 should raise RateLimitExhaustedError."""
        scanner = GitHubScanner()
        resp = _mock_response(200, json_data=[], headers={"X-RateLimit-Remaining": "0"})
        with patch.object(scanner.session, "get", return_value=resp):
            with pytest.raises(RateLimitExhaustedError):
                scanner._get("/repos/owner/repo")

    def test_rate_limit_low_logs_warning(self):
        """When X-RateLimit-Remaining < 10, a warning should be logged."""
        scanner = GitHubScanner()
        resp = _mock_response(200, json_data=[], headers={"X-RateLimit-Remaining": "5"})
        with patch.object(scanner.session, "get", return_value=resp):
            with patch("scanner.logger") as mock_logger:
                scanner._get("/repos/owner/repo")
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert "5" in str(call_args)

    def test_rate_limit_sufficient_no_warning(self):
        """When X-RateLimit-Remaining >= 10, no warning should be logged."""
        scanner = GitHubScanner()
        resp = _mock_response(200, json_data=[], headers={"X-RateLimit-Remaining": "500"})
        with patch.object(scanner.session, "get", return_value=resp):
            with patch("scanner.logger") as mock_logger:
                scanner._get("/repos/owner/repo")
                mock_logger.warning.assert_not_called()

    def test_scan_sorts_by_ahead_descending(self):
        """Results should be sorted by ahead_by in descending order."""
        scanner = GitHubScanner()
        forks = [
            _make_fork("alice", "alice/repo"),
            _make_fork("bob", "bob/repo"),
        ]
        cmp_alice = {"ahead_by": 3, "behind_by": 0}
        cmp_bob = {"ahead_by": 10, "behind_by": 2}
        with patch.object(scanner, "_get", side_effect=[forks, cmp_alice, cmp_bob]):
            results = scanner.scan("owner/repo", min_ahead=1)
        assert len(results) == 2
        assert results[0].full_name == "bob/repo"
        assert results[1].full_name == "alice/repo"
