"""Tests for check_gmail_watch_health (self-healing version).

Mocks are unavoidable here: wmill SDK is only available inside Windmill's
sandbox, and requests make real HTTP calls to Windmill API + SMS gateway.
All other logic is tested with real code.
"""

import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# Create a fake wmill module so the script can be imported outside Windmill
_wmill_mock = types.ModuleType("wmill")
_wmill_mock.get_variable = MagicMock()
sys.modules["wmill"] = _wmill_mock

# Now import the module under test
from f.switchboard.check_gmail_watch_health import (
    main,
    check_webhook_staleness,
    attempt_self_heal,
    format_failure_alert,
    send_alert,
    WATCH_SCRIPTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOKEN = "test-token-123"
SMS_URL = "http://100.125.176.16:8686/send-sms"


def _setup_wmill_vars():
    """Configure wmill.get_variable to return expected values."""
    def get_variable(name):
        return {
            "f/switchboard/router_token": TOKEN,
            "f/switchboard/sms_gateway_url": SMS_URL,
        }[name]
    _wmill_mock.get_variable = MagicMock(side_effect=get_variable)


def _recent_timestamp(hours_ago=2):
    """Return an ISO timestamp N hours in the past."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _stale_timestamp(hours_ago=72):
    """Return an ISO timestamp N hours in the past (stale)."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _mock_jobs_response(created_at, status_code=200):
    """Create a mock response for the Windmill jobs list endpoint."""
    resp = MagicMock()
    resp.status_code = status_code
    if created_at is None:
        resp.json.return_value = []
    else:
        resp.json.return_value = [{"created_at": created_at}]
    resp.raise_for_status = MagicMock()
    return resp


def _mock_renewal_response(success=True, error_msg="OAuth token revoked"):
    """Create a mock response for a watch renewal script call."""
    resp = MagicMock()
    if success:
        resp.status_code = 200
        resp.json.return_value = {"expiration": "12345"}
    else:
        resp.status_code = 500
        resp.json.return_value = {"error": {"message": error_msg}}
        resp.text = error_msg
    return resp


# ---------------------------------------------------------------------------
# 1. Healthy: webhook ran recently -> returns healthy, no alert
# ---------------------------------------------------------------------------

class TestHealthy:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_recent_webhook_returns_healthy(self, mock_requests):
        """When webhook ran within 48h, return healthy status with no SMS."""
        _setup_wmill_vars()
        ts = _recent_timestamp(hours_ago=5)
        mock_requests.get.return_value = _mock_jobs_response(ts)

        result = main()

        assert result["status"] == "healthy"
        assert result["hours_since_last_run"] <= 6  # roughly 5h
        assert result["last_run"] == ts
        # No SMS should be sent
        mock_requests.post.assert_not_called()

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_healthy_at_boundary(self, mock_requests):
        """At exactly 48h, still healthy (<=48 check)."""
        _setup_wmill_vars()
        ts = _recent_timestamp(hours_ago=47)
        mock_requests.get.return_value = _mock_jobs_response(ts)

        result = main()

        assert result["status"] == "healthy"
        mock_requests.post.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Stale + self-heal succeeds: both renewals work -> self_healed, no alert
# ---------------------------------------------------------------------------

class TestStaleSelfHealSuccess:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_stale_both_renewals_succeed(self, mock_requests):
        """When stale and both renewals succeed, return self_healed."""
        _setup_wmill_vars()
        ts = _stale_timestamp(hours_ago=72)

        def route_requests(url, **kwargs):
            if "jobs/list" in url:
                return _mock_jobs_response(ts)
            elif "setup_gmail_watch" in url:
                return _mock_renewal_response(success=True)
            elif "setup_gmail_leads_watch" in url:
                return _mock_renewal_response(success=True)
            return MagicMock()

        mock_requests.get.return_value = _mock_jobs_response(ts)
        mock_requests.post.side_effect = route_requests

        result = main()

        assert result["status"] == "self_healed"
        assert result["hours_since_last_run"] >= 71
        assert result["renewals"] is not None
        assert all(r["success"] for r in result["renewals"])
        # No SMS alert sent (post calls are only renewal calls, no SMS)
        for c in mock_requests.post.call_args_list:
            assert SMS_URL not in str(c)


# ---------------------------------------------------------------------------
# 3. Stale + self-heal fails: renewal fails -> sends alert with error details
# ---------------------------------------------------------------------------

class TestStaleSelfHealFails:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_stale_both_renewals_fail(self, mock_requests):
        """When stale and both renewals fail, send SMS alert."""
        _setup_wmill_vars()
        ts = _stale_timestamp(hours_ago=72)

        call_count = {"post": 0}

        def route_post(url, **kwargs):
            call_count["post"] += 1
            if "setup_gmail_watch" in url or "setup_gmail_leads_watch" in url:
                return _mock_renewal_response(success=False, error_msg="OAuth token revoked")
            # SMS gateway call -- just return ok
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_requests.get.return_value = _mock_jobs_response(ts)
        mock_requests.post.side_effect = route_post

        result = main()

        assert result["status"] == "alert_sent"
        assert result["reason"] == "self_heal_failed"
        assert not all(r["success"] for r in result["renewals"])
        # Verify SMS was sent (at least one post call to SMS URL)
        sms_calls = [
            c for c in mock_requests.post.call_args_list
            if SMS_URL in str(c)
        ]
        assert len(sms_calls) == 1


# ---------------------------------------------------------------------------
# 4. Stale + partial failure: one succeeds, one fails -> sends alert
# ---------------------------------------------------------------------------

class TestStalePartialFailure:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_one_renewal_succeeds_one_fails(self, mock_requests):
        """When stale and one renewal fails, send SMS alert."""
        _setup_wmill_vars()
        ts = _stale_timestamp(hours_ago=72)

        def route_post(url, **kwargs):
            if "setup_gmail_watch" in url and "leads" not in url:
                return _mock_renewal_response(success=True)
            if "setup_gmail_leads_watch" in url:
                return _mock_renewal_response(success=False, error_msg="Token expired")
            # SMS gateway
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_requests.get.return_value = _mock_jobs_response(ts)
        mock_requests.post.side_effect = route_post

        result = main()

        assert result["status"] == "alert_sent"
        assert result["reason"] == "self_heal_failed"
        # One succeeded, one failed
        successes = [r for r in result["renewals"] if r["success"]]
        failures = [r for r in result["renewals"] if not r["success"]]
        assert len(successes) == 1
        assert len(failures) == 1
        assert "Token expired" in failures[0]["error"]


# ---------------------------------------------------------------------------
# 5. No jobs found + self-heal succeeds
# ---------------------------------------------------------------------------

class TestNoJobsSelfHealSuccess:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_no_jobs_both_renewals_succeed(self, mock_requests):
        """When no webhook jobs found but renewals succeed, return self_healed."""
        _setup_wmill_vars()

        def route_post(url, **kwargs):
            if "setup_gmail_watch" in url or "setup_gmail_leads_watch" in url:
                return _mock_renewal_response(success=True)
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_requests.get.return_value = _mock_jobs_response(None)  # empty jobs
        mock_requests.post.side_effect = route_post

        result = main()

        assert result["status"] == "self_healed"
        assert result["reason"] == "no_jobs_found"
        assert all(r["success"] for r in result["renewals"])


# ---------------------------------------------------------------------------
# 6. No jobs found + self-heal fails
# ---------------------------------------------------------------------------

class TestNoJobsSelfHealFails:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_no_jobs_renewals_fail(self, mock_requests):
        """When no webhook jobs and renewals fail, send SMS alert."""
        _setup_wmill_vars()

        def route_post(url, **kwargs):
            if "setup_gmail_watch" in url or "setup_gmail_leads_watch" in url:
                return _mock_renewal_response(success=False, error_msg="Refresh token revoked")
            # SMS gateway
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_requests.get.return_value = _mock_jobs_response(None)
        mock_requests.post.side_effect = route_post

        result = main()

        assert result["status"] == "alert_sent"
        assert result["reason"] == "no_jobs_found"
        # SMS was sent
        sms_calls = [
            c for c in mock_requests.post.call_args_list
            if SMS_URL in str(c)
        ]
        assert len(sms_calls) == 1


# ---------------------------------------------------------------------------
# 7. Staleness check errors -> sends alert
# ---------------------------------------------------------------------------

class TestStalenessCheckError:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_api_error_sends_alert(self, mock_requests):
        """When Windmill API call fails, send SMS alert."""
        _setup_wmill_vars()

        # GET raises an exception
        mock_requests.get.side_effect = Exception("Connection refused")

        # POST (SMS gateway) should succeed
        def route_post(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_requests.post.side_effect = route_post

        result = main()

        assert result["status"] == "error"
        assert "Connection refused" in result["error"]
        # SMS was sent
        sms_calls = [
            c for c in mock_requests.post.call_args_list
            if SMS_URL in str(c)
        ]
        assert len(sms_calls) == 1


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestCheckWebhookStaleness:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_returns_none_when_no_jobs(self, mock_requests):
        mock_requests.get.return_value = _mock_jobs_response(None)
        hours, last_run = check_webhook_staleness("token")
        assert hours is None
        assert last_run is None

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_returns_hours_for_recent_job(self, mock_requests):
        ts = _recent_timestamp(hours_ago=10)
        mock_requests.get.return_value = _mock_jobs_response(ts)
        hours, last_run = check_webhook_staleness("token")
        assert 9 < hours < 11
        assert last_run == ts

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_raises_on_api_error(self, mock_requests):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("401 Unauthorized")
        mock_requests.get.return_value = resp
        with pytest.raises(Exception, match="401 Unauthorized"):
            check_webhook_staleness("token")


class TestAttemptSelfHeal:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_both_succeed(self, mock_requests):
        mock_requests.post.return_value = _mock_renewal_response(success=True)
        results = attempt_self_heal("token")
        assert len(results) == 2
        assert all(r["success"] for r in results)

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_captures_http_error(self, mock_requests):
        mock_requests.post.return_value = _mock_renewal_response(
            success=False, error_msg="Token revoked"
        )
        results = attempt_self_heal("token")
        assert len(results) == 2
        assert not any(r["success"] for r in results)
        assert "Token revoked" in results[0]["error"]

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_captures_network_exception(self, mock_requests):
        mock_requests.post.side_effect = ConnectionError("DNS resolution failed")
        results = attempt_self_heal("token")
        assert len(results) == 2
        assert not any(r["success"] for r in results)
        assert "DNS resolution failed" in results[0]["error"]


class TestFormatFailureAlert:
    def test_with_hours_since(self):
        results = [
            {"script": "setup_gmail_watch", "account": "teamgotcher@", "success": True},
            {"script": "setup_gmail_leads_watch", "account": "leads@", "success": False, "error": "Token revoked"},
        ]
        msg = format_failure_alert(results, hours_since=72)
        assert "72h" in msg
        assert "teamgotcher@" in msg
        assert "OK" in msg
        assert "FAILED" in msg
        assert "Token revoked" in msg

    def test_with_reason(self):
        results = [
            {"script": "setup_gmail_watch", "account": "teamgotcher@", "success": False, "error": "err"},
            {"script": "setup_gmail_leads_watch", "account": "leads@", "success": False, "error": "err"},
        ]
        msg = format_failure_alert(results, reason="no prior webhook jobs")
        assert "no prior webhook jobs" in msg
        assert "Self-heal failed" in msg


class TestSendAlert:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_sends_sms_with_correct_payload(self, mock_requests):
        send_alert(SMS_URL, "Test message")
        mock_requests.post.assert_called_once_with(
            SMS_URL,
            json={"phone": "+17348960518", "message": "[RRG Alert] Test message"},
            timeout=30,
        )

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_swallows_exceptions(self, mock_requests):
        mock_requests.post.side_effect = ConnectionError("Network down")
        # Should not raise
        send_alert(SMS_URL, "Test message")
